#!/usr/bin/env bash
# 启动投稿台账（前台）。用法：
#   bash run.sh                                   # 127.0.0.1:8611，数据在 ./data
#   PORT=8700 PORTAL_DATA_DIR=/srv/paper-desk bash run.sh
# 解释器默认 python3，可用 PYTHON=/path/to/venv/bin/python 指定。
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-8611}"
export HOST="${HOST:-127.0.0.1}"
exec "${PYTHON:-python3}" app.py
