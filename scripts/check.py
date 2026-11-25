#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源可用性检测：并发请求 + 超时重试 + 状态分级，输出 reports/availability.json。
纯 Python 标准库，零依赖。逻辑仿照 awesome-zhuiju-free 的 check-availability.mjs。
"""
import os
import json
import math
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
GH_TIMEOUT = float(os.getenv("GH_TIMEOUT", "10"))
GH_WORKERS = int(os.getenv("GH_WORKERS", "4"))
SKIP_AVAILABILITY = os.getenv("SKIP_AVAILABILITY") == "1"
SCORE_KEYS = ("more", "speed", "clean", "stable", "ease")


def star_score(stars):
    """GitHub Star 数 -> 1~5 分（对数映射，保留 1 位小数）。
    0→2.0，100→3.5，1k→4.3，10k+→5.0。
    """
    try:
        n = int(stars)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return round(max(1.0, min(5.0, 2.0 + math.log10(n + 1) * 0.75)), 1)


def fetch_github_meta(full_name):
    """从 GitHub API 拉取仓库最新 stars / pushed_at；失败返回 None。"""
    url = "https://api.github.com/repos/%s" % full_name
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer %s" % token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=GH_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    stars = payload.get("stargazers_count")
    if stars is None:
        return None
    return {"stars": int(stars), "pushed_at": payload.get("pushed_at")}


def update_github_meta(data):
    """并发刷新所有带 github.full_name 的仓库元数据，返回成功数量。"""
    targets = [r for r in data["resources"] if (r.get("github") or {}).get("full_name")]
    if not targets:
        return 0
    updated = 0
    with ThreadPoolExecutor(max_workers=GH_WORKERS) as ex:
        futures = {ex.submit(fetch_github_meta, r["github"]["full_name"]): r for r in targets}
        for fut in as_completed(futures):
            r = futures[fut]
            try:
                meta = fut.result()
            except Exception as e:
                print("  [WARN] GitHub meta %s: %s" % (r["id"], str(e)[:100]))
                continue
            if meta:
                g = r.setdefault("github", {})
                g.update(meta)
                updated += 1
    return updated


def apply_auto_scores(data):
    """按 GitHub Star 自动计算 scores；scores_locked=true 的资源保留手填分。"""
    scored = 0
    for r in data["resources"]:
        if r.get("scores_locked"):
            r["scores_source"] = "manual"
            continue
        stars = (r.get("github") or {}).get("stars")
        value = star_score(stars)
        if value is None:
            r["scores_source"] = "manual"
            continue
        r["scores"] = {k: value for k in SCORE_KEYS}
        r["scores_source"] = "github-stars"
        scored += 1
    return scored


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

    # 先刷新 GitHub 元数据并自动评分；即使后续可用性检测失败也不影响评分结果
    gh_updated = update_github_meta(data)
    auto_scored = apply_auto_scores(data)
    print("GitHub 元数据更新：%d 个仓库，自动评分：%d 个资源" % (gh_updated, auto_scored))

    if SKIP_AVAILABILITY:
        with open(RES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("仅刷新评分模式：已跳过可用性检测，reports/availability.json 未改动")
        return

    targets = [r for r in data["resources"] if r.get("enabled", True)]

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(check_one, r): r for r in targets}
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda x: x["resource_id"])

    # 将检测结果回写到 resources.json 的 verification 字段（仿源站机制）
    by_id = {r["resource_id"]: r for r in results}
    today = datetime.now(timezone.utc).date().isoformat()
    for res in data["resources"]:
        rid = res["id"]
        if rid not in by_id:
            continue
        r = by_id[rid]
        v = res.setdefault("verification", {})
        if r["status"] == "reachable":
            v["status"] = "active"
            v["notes"] = "自动检测通过 (HTTP %s, %dms)" % (r["http_status"], r["response_ms"])
        elif r["status"] == "restricted":
            v["status"] = "caution"
            v["notes"] = "访问受限 (HTTP %s)" % r["http_status"]
        else:
            v["status"] = "unreachable"
            v["notes"] = "无法访问 (%s)" % (r.get("http_status") or r.get("error") or "timeout")
        v["last_checked"] = today
        v["method"] = "auto"
    with open(RES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    report = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checker": {
            "environment": "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local",
            "timeout_s": TIMEOUT,
            "workers": WORKERS,
            "retries": RETRIES,
        },
        "scoring": {
            "github_meta_updated": gh_updated,
            "auto_scored": auto_scored,
            "method": "score = clamp(2.0 + log10(stars + 1) * 0.75, 1, 5)",
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
