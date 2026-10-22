#!/usr/bin/env bash
# jx_search_author.sh <session> <姓名或邮箱> <验证码>：JournalX 作者步骤里检索作者，打印候选（姓名/单位/邮箱）
# 有的刊姓名、E-mail、验证码是三个框（personSearch.name / personSearch.email / randomCode），按 name 属性定位；找不到再按顺序取前两个文本框
set -u
S=$1 NAME=$2 CODE=$3; P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
$P run-code "async page => { const by = async (sel, i) => (await page.locator(sel).count()) ? page.locator(sel).first() : page.locator('input[type=text]').nth(i); const isMail = '$NAME'.includes('@'); await (await by(isMail ? 'input[name=\"personSearch.email\"]' : 'input[name=\"personSearch.name\"]', 0)).fill('$NAME'); await (await by('input[name=\"randomCode\"]', 1)).fill('$CODE'); let msg=''; page.once('dialog', async d => { msg = d.message(); await d.accept(); }); await page.getByRole('button', { name: '添加作者' }).click(); await page.waitForLoadState('load').catch(()=>{}); await page.waitForTimeout(2500); return (msg||'') + ' | ' + page.url(); }" 2>&1 | sed -n '/Result/,+1p' | tail -1
$P eval "() => { const rows=Array.from(document.querySelectorAll('tr')).filter(r=>r.querySelector('input[type=radio]')); return rows.map(r=>r.innerText.replace(/\s+/g,' ').trim()).join(' || ') || document.body.innerText.slice(0,200).replace(/\s+/g,' '); }" 2>&1 | sed -n 2p | cut -c1-900
