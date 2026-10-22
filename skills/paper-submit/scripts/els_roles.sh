#!/usr/bin/env bash
# els_roles.sh <session> <role>… : 在 submit.elsevier.com 正在编辑的作者卡片里逐个选 Contributor roles（每选一个下拉就收起，所以每次重开）
set -u
S=$1; shift
P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
for role in "$@"; do
  cb=$($P snapshot 2>&1 | grep -m1 'combobox "Contributor roles"' | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
  $P click "$cb" >/dev/null; sleep 1
  opt=$($P snapshot 2>&1 | grep -F "option \"$role\"" | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
  if [ -z "$opt" ]; then echo "role not found: $role" >&2; exit 1; fi
  $P click "$opt" >/dev/null; sleep 1
done
$P snapshot 2>&1 | grep -o 'button "Remove [^"]*"' | grep -v "Remove Author" | sed 's/button "Remove /  role: /; s/"$//'
