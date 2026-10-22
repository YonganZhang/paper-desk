#!/usr/bin/env bash
# 投稿台账数据库快照。用法：bash backup.sh（数据目录取 PORTAL_DATA_DIR，默认 ./data）
# 快照写进 <数据目录>/backups/，保留最近 30 份；上传的投稿包 uploads/ 不在内（请整目录另行拷贝）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$(cd "${PORTAL_DATA_DIR:-$HERE/data}" && pwd)"
[ -f "$D/portal.db" ] || { echo "找不到数据库：$D/portal.db" >&2; exit 1; }
mkdir -p "$D/backups"
OUT="$D/backups/portal.$(date +%Y%m%d-%H%M%S).db"
"${PYTHON:-python3}" -c "
import sqlite3,sys
s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
" "$D/portal.db" "$OUT"
ls -1t "$D"/backups/portal.*.db | tail -n +31 | xargs -r rm -f
echo "$OUT"
