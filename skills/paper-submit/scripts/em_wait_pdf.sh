#!/bin/bash
# em_wait_pdf.sh <session> <journal-code> <out.pdf>：轮询「待批准」列表直到 Needs Approval，再下载系统 PDF
S=$1 J=$2 OUT=$3; P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
end=$(( $(date +%s) + 1800 ))
# 每轮都从顶部导航「Main Menu」进待批准列表：default2.aspx 和 reload 会停在 iframe 上次的内部页（例如向导的 Manuscript Data），看不到状态
open_list() {
  $P goto "https://www.editorialmanager.com/$J/default2.aspx" >/dev/null 2>&1; sleep 3
  m=$($P snapshot 2>&1 | grep -m1 'link "Main Menu"' | grep -o 'ref=[a-z0-9]*' | cut -d= -f2); [ -n "$m" ] && { $P click $m >/dev/null 2>&1; sleep 3; }
  l=$($P snapshot 2>&1 | grep -o "link \"Submissions Waiting for Author's Approval[^\"]*\" \[ref=[a-z0-9]*" | head -1 | grep -o 'ref=[a-z0-9]*' | cut -d= -f2)
  [ -n "$l" ] && { $P click $l >/dev/null 2>&1; sleep 3; }
}
until [ $(date +%s) -gt $end ]; do open_list; s=$($P snapshot 2>&1)
  if echo "$s" | grep -q 'cell "Needs Approval"'; then echo "$(date +%T) Needs Approval"; break; fi
  echo "$s" | grep -q 'cell "Building PDF"' || { echo "$(date +%T) state:"; echo "$s" | grep -E 'Page Title|cell "[A-Z][^"]{3,30}"' | head -6; }
  sleep 30
done
# viewAuthorPDFs(…) 只在 onclick 里，snapshot 看不到；直接从「待批准」iframe 的 HTML 里取
$P run-code "async page => { const fr = page.frames().find(x => x.url().includes('Approve')); if (!fr) return 'no approve frame'; const h = await fr.content(); const call = (h.match(/viewAuthorPDFs\\([^)]*\\)/)||[])[0]; if (!call) return 'no viewAuthorPDFs call'; const dP = page.waitForEvent('download', { timeout: 60000 }).catch(() => null); await fr.evaluate(call).catch(e => null); const d = await dP; if (!d) return 'no download for ' + call; await d.saveAs('$OUT'); return 'ok ' + d.suggestedFilename(); }" 2>&1 | sed -n '/Result/,+1p'
