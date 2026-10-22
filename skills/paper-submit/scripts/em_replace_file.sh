#!/usr/bin/env bash
# em_replace_file.sh <session> <journal-code> <old file name|-> <item type> <new file>
# 待批准稿件换一个文件：Main Menu → 待批准列表 → Edit Submission → Attach Files，
# 勾掉旧文件的 Delete、Remove、Proceed，再按类型上传新文件。old 写 - 表示只新增。已经停在 Attach Files 页时直接在当前页换，
# 所以同一稿件连换几个文件时连续调用即可。全部换完再用 em_build.sh 重新生成 PDF。
set -u
S=$1 J=$2 OLD=$3 TYPE=$4 NEW=$5; P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
ref() { $P snapshot 2>&1 | grep -m1 -- "$1" | grep -o 'ref=[a-z0-9]*' | cut -d= -f2; }
if $P snapshot 2>&1 | grep -q "Page Title: Attach Files"; then echo "edit: already on Attach Files"; else
  $P goto "https://www.editorialmanager.com/$J/default2.aspx" >/dev/null 2>&1; sleep 3
  m=$(ref 'link "Main Menu"'); [ -n "$m" ] && { $P click "$m" >/dev/null 2>&1; sleep 3; }
  l=$($P snapshot 2>&1 | grep -o "link \"Submissions Waiting for Author's Approval[^\"]*\" \[ref=[a-z0-9]*" | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
  [ -n "$l" ] && { $P click "$l" >/dev/null 2>&1; sleep 3; }
  r=$($P run-code "async page => { const fr = page.frames().find(x => x.url().includes('Approve')); if (!fr) return 'no approve frame'; const h = await fr.content(); const m = h.match(/gotoEdit\('[^']*'\)/); if (!m) return 'no edit link'; await fr.evaluate(m[0].replace(/&amp;/g,'&')).catch(()=>null); return 'ok'; }" 2>&1 | sed -n '/Result/,+1p' | tail -1)
  echo "edit: $r"; echo "$r" | grep -q ok || exit 1; sleep 5
  $P click "$(ref 'button "Attach Files')" >/dev/null 2>&1; sleep 6
fi
if [ "$OLD" != "-" ]; then
  snap=$($P snapshot 2>&1); n=$(echo "$snap" | grep -n -F "cell \"$OLD\"" | head -1 | cut -d: -f1)
  [ -z "$n" ] && { echo "old file not found: $OLD" >&2; exit 1; }
  cb=$(echo "$snap" | sed -n "$n,$((n+12))p" | grep -m1 'checkbox "Delete"' | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
  $P check "$cb" >/dev/null 2>&1; sleep 1
  $P click "$($P snapshot 2>&1 | grep -o 'button "[^"]*Remove[^"]*" \[ref=[a-z0-9]*' | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)" >/dev/null 2>&1; sleep 2
  $P click "$($P snapshot 2>&1 | grep -A4 'heading "Warning"' | grep -o 'button "Proceed"[^[]*\(\[active\] \)\?\[ref=[a-z0-9]*' | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)" >/dev/null 2>&1; sleep 4
  $P snapshot 2>&1 | grep -q -F "cell \"$OLD\"" && { echo "old file still listed" >&2; exit 1; }
  echo "removed: $OLD"
fi
$P select "$($P snapshot 2>&1 | grep -o 'combobox "Select Item Type" \[ref=[a-z0-9]*' | cut -d= -f2)" "$TYPE" >/dev/null 2>&1; sleep 2
$P click "$($P snapshot 2>&1 | grep -o 'button "Browse[^"]*"[^[]*\(\[active\] \)\?\[ref=[a-z0-9]*' | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)" >/dev/null 2>&1; sleep 1
$P upload "$(realpath "$NEW")" 2>&1 | grep -q setFiles || { echo "upload failed" >&2; exit 1; }
sleep 10
base=$(basename "$NEW"); snap=$($P snapshot 2>&1); n=$(echo "$snap" | grep -n -F "cell \"$base\"" | head -1 | cut -d: -f1)
[ -z "$n" ] && { echo "new file not listed" >&2; exit 1; }
echo "uploaded: $base as $(echo "$snap" | sed -n "$((n-25)),$n p" | grep -o 'option "[^"]*" \[selected\]' | tail -1)"
