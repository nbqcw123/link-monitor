#!/usr/bin/env python3
"""link-monitor 服务端模式（推荐用于飞牛 NAS / 内网服务器）。

数据完全留在 NAS 本地：管理页保存时只写 resources.json 并重新生成 index.html，
不会推送到 GitHub。只有 GitHub Actions 静态部署方式才需要把更改推到仓库。

管理员口令只存 PBKDF2 哈希，校验在服务端完成，浏览器拿不到任何凭据。

用法：
    cp .env.example .env      # 填管理员口令哈希
    python3 server.py         # 默认 0.0.0.0:8801

只依赖 Python 3.9+ 标准库。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 配置

def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env_file(os.path.join(BASE, ".env"))


def env(key, default=""):
    return (os.getenv(key) or default).strip()


CFG = {
    "host": env("HOST", "0.0.0.0"),
    "port": int(env("PORT", "8801") or 8801),
    "user": env("ADMIN_USER", "admin"),
    "pass_hash": env("ADMIN_PASS_HASH"),
    "session_hours": float(env("SESSION_HOURS", "12") or 12),
    "cookie_secure": env("COOKIE_SECURE", "0") == "1",
    "protect_all": env("PROTECT_ALL", "0") == "1",
    "data_file": os.path.join(BASE, env("DATA_FILE", "resources/resources.json")),
    "publish_on_save": env("PUBLISH_ON_SAVE", "1") == "1",
}

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}

SESSIONS = {}          # token -> 过期时间戳
FAILS = {}             # ip -> [失败次数, 锁定到期时间]
LOCK = threading.Lock()


# ---------------------------------------------------------------- 口令

def verify_password(password):
    spec = CFG["pass_hash"]
    if not spec:
        return False
    try:
        algo, iterations, salt_hex, hash_b64 = spec.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
    except Exception:  # noqa: BLE001
        return False


def client_ip(handler):
    fwd = handler.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return handler.client_address[0]


def throttled(ip):
    with LOCK:
        rec = FAILS.get(ip)
        if not rec:
            return 0
        if rec[1] and rec[1] > time.time():
            return int(rec[1] - time.time())
        return 0


def note_fail(ip):
    with LOCK:
        rec = FAILS.setdefault(ip, [0, 0])
        rec[0] += 1
        if rec[0] >= 5:
            rec[0] = 0
            rec[1] = time.time() + 60


def clear_fail(ip):
    with LOCK:
        FAILS.pop(ip, None)


def new_session():
    token = secrets.token_urlsafe(32)
    with LOCK:
        SESSIONS[token] = time.time() + CFG["session_hours"] * 3600
        # 顺手清理过期会话
        for key, exp in list(SESSIONS.items()):
            if exp < time.time():
                SESSIONS.pop(key, None)
    return token


def session_valid(token):
    if not token:
        return False
    with LOCK:
        exp = SESSIONS.get(token)
        if not exp:
            return False
        if exp < time.time():
            SESSIONS.pop(token, None)
            return False
        return True


# ---------------------------------------------------------------- 数据

def read_data():
    with open(CFG["data_file"], encoding="utf-8") as fh:
        return json.load(fh)


def normalize(data):
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise ValueError("数据结构不正确：缺少 resources 数组")
    items = []
    seen = set()
    for row in data["resources"]:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        url = str(row.get("url") or "").strip()
        if not rid or not name or not url:
            raise ValueError("每条数据都要有 id / name / url")
        if rid in seen:
            raise ValueError("id 重复：%s" % rid)
        if not re.match(r"^https?://", url, re.I):
            raise ValueError("地址必须以 http(s) 开头：%s" % url)
        seen.add(rid)
        items.append(row)
    out = dict(data)
    out["resources"] = items
    out.setdefault("version", 1)
    return out


def regenerate_page():
    script = os.path.join(BASE, "scripts", "publish.py")
    if not os.path.exists(script):
        return
    try:
        subprocess.run([sys.executable, script], cwd=BASE, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "link-monitor"
    protocol_version = "HTTP/1.1"

    # 关闭默认的 stderr 访问日志噪音（保留错误）
    def log_message(self, fmt, *args):
        if os.getenv("ACCESS_LOG") == "1":
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ----- 工具
    def send_json(self, code, obj, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, val in (extra_headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code, text, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def cookie_token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if "=" in part:
                key, val = part.split("=", 1)
                if key.strip() == "lm_session":
                    return val.strip()
        return ""

    def authed(self):
        return session_valid(self.cookie_token())

    def read_json(self, limit=8 * 1024 * 1024):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            raise ValueError("请求体为空或过大")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ----- 路由
    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path == "/api/session":
            return self.send_json(200, {"server": True, "authed": self.authed(),
                                        "user": CFG["user"] if self.authed() else None})
        if path == "/api/resources":
            if not self.authed():
                return self.send_json(401, {"error": "未登录"})
            try:
                return self.send_json(200, read_data())
            except Exception as exc:  # noqa: BLE001
                return self.send_json(500, {"error": "读取失败：%s" % exc})

        if CFG["protect_all"] and not self.authed():
            if path in ("/admin.html", "/index.html", "/"):
                return self.send_json(401, {"error": "需要登录", "login": "/admin.html"})

        return self.serve_static(path)

    def do_POST(self):
        path = unquote(urlparse(self.path).path)

        if path == "/api/login":
            ip = client_ip(self)
            wait = throttled(ip)
            if wait:
                return self.send_json(429, {"error": "尝试过于频繁，请 %d 秒后再试" % wait})
            try:
                body = self.read_json(limit=64 * 1024)
            except Exception:  # noqa: BLE001
                return self.send_json(400, {"error": "请求格式不正确"})
            user = str(body.get("user") or "").strip()
            password = str(body.get("password") or "")
            if not CFG["pass_hash"]:
                return self.send_json(500, {"error": "服务端未配置管理员口令（ADMIN_PASS_HASH）"})
            if user == CFG["user"] and verify_password(password):
                clear_fail(ip)
                token = new_session()
                cookie = "lm_session=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
                    token, int(CFG["session_hours"] * 3600))
                if CFG["cookie_secure"]:
                    cookie += "; Secure"
                return self.send_json(200, {"ok": True, "user": user},
                                      {"Set-Cookie": cookie})
            note_fail(ip)
            time.sleep(0.6)  # 轻微延迟，降低暴力尝试速度
            return self.send_json(401, {"error": "用户名或密码不正确"})

        if path == "/api/logout":
            token = self.cookie_token()
            with LOCK:
                SESSIONS.pop(token, None)
            return self.send_json(200, {"ok": True},
                                  {"Set-Cookie": "lm_session=; Path=/; Max-Age=0; HttpOnly"})

        if path == "/api/save":
            if not self.authed():
                return self.send_json(401, {"error": "未登录"})
            try:
                raw = self.read_json()
                data = normalize(raw)
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                return self.send_json(400, {"error": "请求格式不正确：%s" % exc})

            text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            try:
                tmp = CFG["data_file"] + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(text)
                os.replace(tmp, CFG["data_file"])
            except Exception as exc:  # noqa: BLE001
                return self.send_json(500, {"error": "写入文件失败：%s" % exc})

            if CFG["publish_on_save"]:
                regenerate_page()

            return self.send_json(200, {
                "ok": True,
                "local": True,
                "github": False,
                "message": "已保存到 NAS 本地，未推送 GitHub",
                "total": len(data["resources"]),
            })

        return self.send_json(404, {"error": "接口不存在"})

    # ----- 静态文件
    def serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        rel = path.lstrip("/")
        if not rel or ".." in rel.split("/"):
            return self.send_text(403, "Forbidden")
        target = os.path.realpath(os.path.join(BASE, rel))
        if not target.startswith(os.path.realpath(BASE) + os.sep):
            return self.send_text(403, "Forbidden")
        if not os.path.isfile(target):
            return self.send_text(404, "Not Found")
        ext = os.path.splitext(target)[1].lower()
        if ext not in STATIC_TYPES:
            return self.send_text(403, "Forbidden")
        with open(target, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES[ext])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def main():
    if not CFG["pass_hash"]:
        print("警告：ADMIN_PASS_HASH 为空，管理页将无法登录。", file=sys.stderr)
        print("     先生成：python3 scripts/set_admin_password.py --target env", file=sys.stderr)
    print("link-monitor 服务端已启动：http://%s:%d/  (管理页 /admin.html)" % (CFG["host"], CFG["port"]))
    print("数据文件：%s" % CFG["data_file"])
    print("保存目标：NAS 本地（不推送 GitHub）")
    httpd = ThreadingHTTPServer((CFG["host"], CFG["port"]), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
