#!/usr/bin/env bash
# els_upload.sh <session> <req|opt> <file type option> <file>
# submit.elsevier.com 上传页：在必传区（req）或可选区（opt）选好文件类型，再点 Upload 传一个文件。
set -u
S=$1 AREA=$2 TYPE=$3 FILE=$4
P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"; idx=$([ "$AREA" = req ] && echo 1 || echo 2)
cb=$($P snapshot 2>&1 | grep -o 'combobox "Choose file type to upload" \[ref=[a-z0-9]*' | sed -n ${idx}p | cut -d= -f2)
$P click "$cb" >/dev/null 2>&1; sleep 1
opt=$($P snapshot 2>&1 | grep -o "option \"$TYPE\" \[ref=[a-z0-9]*" | head -1 | cut -d= -f2)
[ -z "$opt" ] && { echo "no option: $TYPE; available:" >&2; $P snapshot 2>&1 | grep -o 'option "[^"]*"' >&2; exit 2; }
$P click "$opt" >/dev/null 2>&1; sleep 1
up=$($P snapshot 2>&1 | grep -o 'button "Upload" \[ref=[a-z0-9]*' | sed -n ${idx}p | cut -d= -f2)
$P click "$up" >/dev/null 2>&1; sleep 1
$P upload "$(realpath "$FILE")" 2>&1 | grep -q setFiles && echo "uploaded $FILE -> $TYPE" || { echo "FAIL $FILE" >&2; exit 1; }
sleep 8
$P snapshot 2>&1 | grep -o 'button "Delete [^"]*"' | sed 's/button "Delete /  on page: /; s/"$//'
