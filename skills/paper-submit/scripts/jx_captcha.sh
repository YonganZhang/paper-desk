#!/usr/bin/env bash
# jx_captcha.sh <session> <out.png>：截取 JournalX 页面上的 kaptcha 图片并放大 3 倍，供读图识别
set -u
S=$1 OUT=$2; P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"; raw="${OUT%.png}_raw.png"
$P run-code "async page => { await page.locator('img[src*=\"kaptcha\"]').first().screenshot({ path: '$(realpath -m "$raw")' }); return 'ok'; }" >/dev/null 2>&1
python3 -I -c "import sys; from PIL import Image; im=Image.open(sys.argv[1]); im.resize((im.size[0]*3, im.size[1]*3)).save(sys.argv[2])" "$raw" "$OUT" && echo "$OUT"
