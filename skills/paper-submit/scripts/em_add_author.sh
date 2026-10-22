#!/bin/bash
# 在 Editorial Manager 的 Manuscript Data → Authors 里新增一位作者并保存。
# 用法: em_add_author.sh <session> <名> <姓> <邮箱> <单位联想查询词> <联想列表项全文> <国家下拉文本> <CRediT角色>…
# 前提: Authors 一节已展开。单位必须从联想列表里点选（直接 fill 会被判为未识别单位）。
set -u
S=$1 FIRST=$2 LAST=$3 EMAIL=$4 Q=$5 PICK=$6 COUNTRY=$7; shift 7
P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
snap() { $P snapshot 2>&1; }
ref() { echo "$1" | grep -o -E "$2 \[ref=[a-z0-9]+" | tail -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2; }
s=$(snap); $P click "$(ref "$s" 'button "\+Add Another Author"')" >/dev/null 2>&1; sleep 3
s=$(snap)
$P fill "$(ref "$s" 'textbox "Given/First Name \*"')" "$FIRST" >/dev/null
$P fill "$(ref "$s" 'textbox "Family/Last Name \*"')" "$LAST" >/dev/null
$P fill "$(ref "$s" 'textbox "E-mail Address \*"')" "$EMAIL" >/dev/null
inst=$(ref "$s" 'textbox "Institution \*"'); $P fill "$inst" "" >/dev/null; $P click "$inst" >/dev/null; sleep 1
for ((i=0;i<${#Q};i++)); do c="${Q:$i:1}"; [ "$c" = " " ] && c=Space; $P press "$c" >/dev/null; done
sleep 3; s=$(snap)
li=$(echo "$s" | grep -F -- "listitem \"$PICK\"" | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
[ -z "$li" ] && { echo "联想列表里没有：$PICK"; echo "$s" | grep -o 'listitem "[^"]*"' | head -8; exit 3; }
$P click "$li" >/dev/null; sleep 1
s=$(snap); $P select "$(ref "$s" 'combobox "Country or Region"')" "$COUNTRY" >/dev/null
$P click "$(ref "$s" 'button "Edit Contributor Roles"')" >/dev/null; sleep 1
for r in "$@"; do s=$(snap); $P check "$(ref "$s" "checkbox \"$r\"")" >/dev/null || echo "角色没勾上：$r"; done
s=$(snap); $P click "$(ref "$s" 'button "Collapse and Save Changes"')" >/dev/null; sleep 1
s=$(snap)
echo "$s" | grep -E 'textbox "(Given|Family|E-mail|Institution)[^"]*" \[ref=[a-z0-9]+\]: ' | sed -E 's/^ +//' | cut -c1-110
echo "$s" | grep -E 'option .*\[selected\]' | tail -1 | sed -E 's/^ +//'
$P click "$(ref "$s" 'button "Save This Author"')" >/dev/null; sleep 3; snap | grep -E "dialog \[|already|existing|match" | head -4 | cut -c1-160
snap | grep -E 'button "Edit This Author' | sed -E 's/^ +- button "Edit This Author //' | cut -c1-70
