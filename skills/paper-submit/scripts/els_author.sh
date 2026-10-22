#!/usr/bin/env bash
# els_author.sh <session> <first> <last> <email> <inst query> <inst pick substring> <corr yes|no> <role>…
# 填写 submit.elsevier.com 当前处于编辑状态的作者卡片并 Confirm。单位从联想列表里按子串选；同名分支多时 pick 写得具体些（例如带上部门和城市）。
set -u
S=$1 F=$2 L=$3 E=$4 Q=$5 PICK=$6 CORR=$7; shift 7
P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
here=$(dirname "$0")
ref() { $P snapshot 2>&1 | grep -m1 "$1" | grep -o 'ref=[a-z0-9]*' | cut -d= -f2; }
$P fill "$(ref 'textbox "First name"')" "$F" >/dev/null
$P fill "$(ref 'textbox "Last name"')" "$L" >/dev/null
$P click "$(ref 'combobox "Institution"')" >/dev/null; sleep 1
for ((i=0;i<${#Q};i++)); do c="${Q:$i:1}"; [ "$c" = " " ] && c=Space; $P press "$c" >/dev/null; done
sleep 3
snap=$($P snapshot 2>&1)
m=$(echo "$snap" | grep 'menuitem' | grep -F "$PICK" | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
if [ -z "$m" ]; then echo "institution not picked; menu:" >&2; echo "$snap" | grep menuitem | cut -c1-160 >&2; exit 1; fi
$P click "$m" >/dev/null; sleep 1
$P fill "$(ref 'textbox "Email address"')" "$E" >/dev/null
"$here/els_roles.sh" "$S" "$@" || exit 1
[ "$CORR" = yes ] && { $P click "$(ref 'checkbox "This is the corresponding author"')" >/dev/null; sleep 1; }
$P snapshot 2>&1 | grep -E 'combobox "Institution"|textbox "Email address"|checkbox "This is the corr' | cut -c1-160
$P click "$(ref 'button "Confirm"')" >/dev/null; sleep 2
$P snapshot 2>&1 | grep -E 'button "Edit Author|alert|error' | cut -c1-160
