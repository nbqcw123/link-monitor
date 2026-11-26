#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成/更新 admin.html 的管理员口令配置。

源码里只写 PBKDF2-SHA256 的盐和派生值，不保存明文密码。

用法：
  python scripts/set_admin_password.py                  # 随机生成强密码并写入
  python scripts/set_admin_password.py --password 你的密码
  python scripts/set_admin_password.py --user boss --password xxx
  python scripts/set_admin_password.py --print-only      # 只打印，不改文件
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import string
import sys

ITER = 150000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_HTML = os.path.join(ROOT, "admin.html")
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


def main():
    ap = argparse.ArgumentParser(description="设置 admin.html 管理员口令（不存明文）")
    ap.add_argument("--user", default="admin", help="管理员用户名，默认 admin")
    ap.add_argument("--password", help="自定义密码；不填则随机生成")
    ap.add_argument("--print-only", action="store_true", help="只打印配置，不写文件")
    args = ap.parse_args()

    password = args.password or gen_password()
    auth = make_auth(args.user, password)
    line = "var AUTH = %s;" % json.dumps(auth, ensure_ascii=False, separators=(",", ":"))

    if not args.print_only:
        with open(ADMIN_HTML, encoding="utf-8") as f:
            html = f.read()
        if not AUTH_RE.search(html):
            sys.exit("未在 admin.html 中找到 'var AUTH = {...};'，请检查文件结构")
        html = AUTH_RE.sub(lambda m: line, html, count=1)
        with open(ADMIN_HTML, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)

    print("用户名：%s" % auth["user"])
    print("密码：%s" % password)
    print("迭代：%d  PBKDF2-SHA256" % auth["iter"])
    if args.print_only:
        print("配置行（手动替换 admin.html 中的 AUTH）：")
        print(line)
    else:
        print("已写入：%s" % ADMIN_HTML)
    print("\n提示：密码仅此处显示一次，请自行保存；忘记可重跑本脚本重置。")


if __name__ == "__main__":
    main()
