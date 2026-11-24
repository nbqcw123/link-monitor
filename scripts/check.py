#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源可用性检测：并发请求 + 超时重试 + 状态分级，输出 reports/availability.json。
纯 Python 标准库，零依赖。逻辑仿照 awesome-zhuiju-free 的 check-availability.mjs。
"""
import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_PATH = os.path.join(ROOT, "resources", "resources.json")
REPORT_PATH = os.path.join(ROOT, "reports", "availability.json")

TIMEOUT = float(os.getenv("CHECK_TIMEOUT", "12"))
WORKERS = int(os.getenv("CHECK_WORKERS", "6"))
RETRIES = int(os.getenv("CHECK_RETRIES", "2"))
UA = "link-monitor/1.0 (+self-hosted availability checker)"


def status_from_code(code):
    if code is not None and 200 <= code < 400:
        return "reachable"
    if code in (401, 403, 405, 429):
        return "restricted"
    return "unreachable"


def check_one(res):
    started = time.time()
    checked_at = datetime.now(timezone.utc).isoformat()
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(
                res["url"],
                headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                code = resp.status
                final = resp.geturl()
                # 只读少量字节，避免下载大文件
                resp.read(1024)
            status = status_from_code(code)
            if status == "unreachable" and code is not None and code >= 500 and attempt < RETRIES:
                continue
            return {
                "resource_id": res["id"],
                "url": res["url"],
                "status": status,
                "http_status": code,
                "final_url": final,
                "response_ms": int((time.time() - started) * 1000),
                "checked_at": checked_at,
                "attempts": attempt,
                "error": None,
            }
        except urllib.error.HTTPError as e:
            code = e.code
            status = status_from_code(code)
            if status != "unreachable" or attempt == RETRIES:
                return {
                    "resource_id": res["id"],
                    "url": res["url"],
                    "status": status,
                    "http_status": code,
                    "final_url": None,
                    "response_ms": int((time.time() - started) * 1000),
                    "checked_at": checked_at,
                    "attempts": attempt,
                    "error": None,
                }
            last_err = "HTTP %s" % code
        except Exception as e:
            last_err = str(e)
    return {
        "resource_id": res["id"],
        "url": res["url"],
        "status": "unreachable",
        "http_status": None,
        "final_url": None,
        "response_ms": int((time.time() - started) * 1000),
        "checked_at": checked_at,
        "attempts": RETRIES,
        "error": last_err,
    }


def main():
    with open(RES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    targets = [r for r in data["resources"] if r.get("enabled", True)]

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(check_one, r): r for r in targets}
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda x: x["resource_id"])

    report = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checker": {
            "environment": "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local",
            "timeout_s": TIMEOUT,
            "workers": WORKERS,
            "retries": RETRIES,
        },
        "summary": {
            "total": len(results),
            "reachable": sum(1 for r in results if r["status"] == "reachable"),
            "restricted": sum(1 for r in results if r["status"] == "restricted"),
            "unreachable": sum(1 for r in results if r["status"] == "unreachable"),
        },
        "results": results,
    }
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    icon = {"reachable": "[OK]", "restricted": "[!]", "unreachable": "[X]"}
    print("检测完成：%d 个资源" % report["summary"]["total"])
    for r in results:
        detail = r["http_status"] if r["http_status"] is not None else (r["error"] or "-")
        print("  %-4s %-16s %s (%dms)" % (icon[r["status"]], r["resource_id"], detail, r["response_ms"]))
    print("报告：%s" % REPORT_PATH)


if __name__ == "__main__":
    main()
