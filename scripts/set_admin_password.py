#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成/更新管理员口令配置（两种部署方式都支持）。

源码里只写 PBKDF2-SHA256 的盐和派生值，不保存明文密码。

用法：
  python scripts/set_admin_password.py                  # 随机生成强密码，写入 admin.html
  python scripts/set_admin_password.py --password 你的密码
  python scripts/set_admin_password.py --user boss --password xxx
  python scripts/set_admin_password.py --print-only      # 只打印，不改文件
  python scripts/set_admin_password.py --target env      # 写入 .env（NAS 服务端模式）
  python scripts/set_admin_password.py --target both     # 两边都写
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys

ITER = 150000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_HTML = os.path.join(ROOT, "admin.html")
ENV_FILE = os.path.join(ROOT, ".env")
ENV_SAMPLE = os.path.join(ROOT, ".env.example")
AUTH_RE = re.compile(r"var AUTH = \{.*?\};", re.S)


def make_auth(user, password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITER, 32)
    return {
        "user": user,
        "iter": ITER,
        "salt": salt,
        "hash": base64.b64encode(dk).decode("ascii"),
    }


def gen_password(n=14):
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    specials = "@#$%&*+"
    body = [
        secrets.choice(letters),
        secrets.choice(digits),
        secrets.choice(specials),
    ]
    pool = letters + digits
    body += [secrets.choice(pool) for _ in range(max(0, n - len(body)))]
    secrets.SystemRandom().shuffle(body)
    return "".join(body)


def env_spec(auth):
    """服务端使用的单行哈希：pbkdf2_sha256$iter$salt_hex$hash_b64"""
    return "pbkdf2_sha256$%d$%s$%s" % (auth["iter"], auth["salt"], auth["hash"])


def write_env(user, spec):
    """写入或更新 .env 里的 ADMIN_USER / ADMIN_PASS_HASH，保留其它配置。"""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    elif os.path.exists(ENV_SAMPLE):
        with open(ENV_SAMPLE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = ["PORT=8801"]

    def upsert(key, value):
        for i, line in enumerate(lines):
            if line.strip().startswith(key + "="):
                lines[i] = "%s=%s" % (key, value)
                return
        lines.append("%s=%s" % (key, value))

    upsert("ADMIN_USER", user)
    upsert("ADMIN_PASS_HASH", spec)
    with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return ENV_FILE


def main():
    ap = argparse.ArgumentParser(description="设置管理员口令（不存明文）")
    ap.add_argument("--user", default="admin", help="管理员用户名，默认 admin")
    ap.add_argument("--password", help="自定义密码；不填则随机生成")
    ap.add_argument("--print-only", action="store_true", help="只打印配置，不写文件")
    ap.add_argument("--target", choices=["html", "env", "both"], default="html",
                    help="html=写入静态页（GitHub Pages 用）；env=写入 .env（NAS 服务端用）；both=两边都写")
    args = ap.parse_args()

    password = args.password or gen_password()
    auth = make_auth(args.user, password)
    line = "var AUTH = %s;" % json.dumps(auth, ensure_ascii=False, separators=(",", ":"))

    written = []
    if not args.print_only and args.target in ("html", "both"):
        with open(ADMIN_HTML, encoding="utf-8") as f:
            html = f.read()
        if not AUTH_RE.search(html):
            sys.exit("未在 admin.html 中找到 'var AUTH = {...};'，请检查文件结构")
        html = AUTH_RE.sub(lambda m: line, html, count=1)
        with open(ADMIN_HTML, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        written.append(ADMIN_HTML)

    if not args.print_only and args.target in ("env", "both"):
        written.append(write_env(auth["user"], env_spec(auth)))

    print("用户名：%s" % auth["user"])
    print("密码：%s" % password)
    print("迭代：%d  PBKDF2-SHA256" % auth["iter"])
    if args.print_only:
        print("配置行（手动替换 admin.html 中的 AUTH）：")
        print(line)
        print("服务端 .env 用：")
        print("ADMIN_PASS_HASH=%s" % env_spec(auth))
    elif written:
        for path in written:
            print("已写入：%s" % path)
        if ENV_FILE in written:
            print("提示：.env 含凭据，已被 .gitignore 忽略，不要提交。")
    print("\n密码仅此处显示一次，请自行保存；忘记可重跑本脚本重置。")


if __name__ == "__main__":
    main()
