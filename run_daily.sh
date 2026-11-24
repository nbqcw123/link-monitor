#!/bin/bash
# 飞牛 NAS 本地定时入口：检测 -> 生成静态页
# 用法：bash /path/to/link-monitor/run_daily.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export CHECK_TIMEOUT="${CHECK_TIMEOUT:-12}"
export CHECK_WORKERS="${CHECK_WORKERS:-6}"
export CHECK_RETRIES="${CHECK_RETRIES:-2}"
cd "$DIR"
echo "[$(date '+%F %T')] 开始检测..."
python3 scripts/check.py
echo "[$(date '+%F %T')] 生成发布页..."
python3 scripts/publish.py
echo "[$(date '+%F %T')] 完成。发布页：$DIR/index.html"
