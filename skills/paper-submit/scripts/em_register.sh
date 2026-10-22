#!/bin/bash
# Editorial Manager 注册表（preRegistration2 之后那一页）一键填写并提交。
# 用法: em_register.sh <session> <用户名> <Title> <名> <姓> <邮箱> <单位联想查询词> <联想列表项全文> <国家下拉文本> [系 [街道 [城市]]]
# 前提: 当前停在完整注册表（PreRegistration 之后的页面，或提交失败后被清空重来的同一张表）。
# 密码统一用 PAPER_SUBMIT_DEFAULT_PASSWORD（secret 名，真值不出现）。最后停在 Confirm Registration 页之后的结果页并打印标题。
set -u
S=$1 USER=$2 TITLE=$3 FIRST=$4 LAST=$5 EMAIL=$6 Q=$7 PICK=$8 COUNTRY=$9; DEPT=${10:-} STREET=${11:-} CITY=${12:-}
P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
snap() { $P snapshot 2>&1; }
# 按标签找紧随其后的输入框：标签行形如 'generic [ref=..]: Title *'，有的刊没有星号
ref() { echo "$1" | grep -A2 -E -- "generic \[ref=[a-z0-9]+\]: $2( \*)?\$" | grep -o -E '(textbox|combobox).*\[ref=[a-z0-9]+' | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2; }
s=$(snap)
U=$(ref "$s" 'Enter preferred user name'); PW1=$(ref "$s" 'Password'); PW2=$(ref "$s" 'Re-type Password')
T=$(ref "$s" 'Title'); FN=$(ref "$s" 'Given/First Name'); LN=$(ref "$s" 'Family/Last Name'); EM=$(ref "$s" 'E-mail Address')
I=$(ref "$s" 'Institution'); D=$(ref "$s" 'Department'); SA=$(ref "$s" 'Street Address'); C=$(ref "$s" 'City'); CO=$(ref "$s" 'Country or Region')
for v in U PW1 PW2 T FN LN EM I CO; do [ -n "${!v}" ] || { echo "找不到字段 $v"; exit 2; }; done
$P fill "$U" "$USER" >/dev/null; $P fill "$PW1" PAPER_SUBMIT_DEFAULT_PASSWORD >/dev/null; $P fill "$PW2" PAPER_SUBMIT_DEFAULT_PASSWORD >/dev/null
$P fill "$T" "$TITLE" >/dev/null; $P fill "$FN" "$FIRST" >/dev/null; $P fill "$LN" "$LAST" >/dev/null; $P fill "$EM" "$EMAIL" >/dev/null
[ -n "$DEPT" ] && [ -n "$D" ] && $P fill "$D" "$DEPT" >/dev/null
[ -n "$STREET" ] && [ -n "$SA" ] && $P fill "$SA" "$STREET" >/dev/null
[ -n "$CITY" ] && [ -n "$C" ] && $P fill "$C" "$CITY" >/dev/null
$P select "$CO" "$COUNTRY" >/dev/null
[ "$($P eval '(el) => el.options[el.selectedIndex].text' "$CO" 2>&1 | sed -n 2p)" = "\"$COUNTRY\"" ] || { echo "国家没选上：$COUNTRY"; exit 2; }
$P fill "$I" "" >/dev/null; $P click "$I" >/dev/null; sleep 1
for ((i=0;i<${#Q};i++)); do c="${Q:$i:1}"; [ "$c" = " " ] && c=Space; $P press "$c" >/dev/null; done
sleep 3; s=$(snap); li=$(echo "$s" | grep -F -- "listitem \"$PICK\"" | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
[ -z "$li" ] && { echo "联想列表里没有：$PICK"; echo "$s" | grep -o 'listitem "[^"]*"' | head -10; exit 3; }
$P click "$li" >/dev/null; sleep 1
s=$(snap); echo "$s" | grep -E 'textbox "?(Institution|E-mail)' | head -3
c=$(echo "$s" | grep -o 'button "Continue >>" \[ref=[a-z0-9]*' | tail -1 | cut -d= -f2); $P click "$c" >/dev/null 2>&1; sleep 4
s=$(snap); echo "$s" | grep -o 'Page Title: .*' | head -1
# Confirm Registration: 勾选必选条款与「不接收营销」
for cb in $(echo "$s" | grep -o 'checkbox \[ref=[a-z0-9]*' | cut -d= -f2); do $P check "$cb" >/dev/null 2>&1; done
c=$(snap | grep -o 'button "Continue >>"[^r]*ref=[a-z0-9]*' | tail -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2); [ -n "$c" ] && $P click "$c" >/dev/null 2>&1; sleep 4
snap | grep -E 'heading "[^"]+"|generic \[ref=[a-z0-9]+\]: Check your email|already in use|Error' | head -5
