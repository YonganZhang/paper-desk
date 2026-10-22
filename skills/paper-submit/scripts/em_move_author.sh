#!/bin/bash
# 在 Editorial Manager 作者列表里，把一位作者拖到另一位作者的下方（after）或上方（before）。
# 用法: em_move_author.sh <session> <要移动的作者名片段> <参照作者名片段> [after|before]
# 只能拖每行最左侧的把手 td.fl-listitem-sortable，并用分步鼠标移动；drag 命令无效。
set -u
S=$1 WHO=$2 REF=$3 WHERE=${4:-after}
FRAC=$([ "$WHERE" = after ] && echo 0.9 || echo 0.1)
"${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli}" -s="$S" run-code "async page => { const fr = page.frames().find(x => x.url().includes('SubManuscriptData')); const h = (n) => fr.locator('li.fl-listitem-item', { hasText: n }).first().locator('td.fl-listitem-sortable'); const a = await h('$WHO').boundingBox(); const t = await h('$REF').boundingBox(); const x = a.x + a.width/2, y0 = a.y + a.height/2, y1 = t.y + t.height*$FRAC; await page.mouse.move(x, y0); await page.mouse.down(); await page.mouse.move(x, y0 + (y1 > y0 ? 5 : -5)); for (let i = 1; i <= 25; i++) { await page.mouse.move(x, y0 + (y1 - y0) * i / 25); await page.waitForTimeout(30); } await page.waitForTimeout(200); await page.mouse.up(); return 'moved'; }" >/dev/null 2>&1
sleep 2
"${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli}" -s="$S" snapshot 2>&1 | grep -E 'button "Edit This Author' | sed -E 's/^ +- button "Edit This Author //' | cut -c1-60
