#!/usr/bin/env bash
# em_build.sh <session>：在编辑中的稿件里转到 Manuscript Data，点 Build PDF for Approval；有 Publishing Options 页就 Proceed。
# 「A network change was detected」时请求可能没发出去，脚本会回读状态；没看到 Building PDF 就重试一次。
set -u
S=$1; P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
ref() { $P snapshot 2>&1 | grep -m1 -- "$1" | grep -o 'ref=[a-z0-9]*' | cut -d= -f2; }
for attempt in 1 2; do
  b=$(ref 'button "Manuscript Data'); [ -n "$b" ] && { $P click "$b" >/dev/null 2>&1; sleep 8; }
  $P snapshot 2>&1 | grep -q 'Page Title: Manuscript' || { $P goto "$($P eval '() => location.href' 2>&1 | sed -n 2p | tr -d '"')" >/dev/null 2>&1; sleep 5; }
  bp=$(ref 'Build PDF for Approval'); [ -z "$bp" ] && { echo "no build button (attempt $attempt)"; continue; }
  $P click "$bp" >/dev/null 2>&1; sleep 12
  pr=$($P snapshot 2>&1 | grep -B2 -A6 -i 'publishing options' | grep -o 'button "Proceed" \[ref=[a-z0-9]*' | head -1 | cut -d= -f2)
  [ -n "$pr" ] && { $P click "$pr" >/dev/null 2>&1; sleep 10; }
  if $P snapshot 2>&1 | grep -q 'cell "Building PDF"\|cell "Needs Approval"'; then echo "building"; exit 0; fi
  # 网络切换页盖住了 iframe：回 default2 看，「Cannot Edit Submission」表示已在构建
  $P goto "$($P eval '() => location.origin + location.pathname' 2>&1 | sed -n 2p | tr -d '"')" >/dev/null 2>&1; sleep 4
  if $P snapshot 2>&1 | grep -q 'Page Title: Cannot Edit Submission\|cell "Building PDF"'; then echo "building"; exit 0; fi
  echo "state after attempt $attempt: $($P snapshot 2>&1 | grep -m1 'Page Title')"
done
exit 1
