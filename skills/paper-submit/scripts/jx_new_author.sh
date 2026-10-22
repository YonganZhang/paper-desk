#!/usr/bin/env bash
# jx_new_author.sh <session> <邮箱> <单位> <通讯地址> <邮编> <省份> <验证码> [第二单位] [第二单位英文]
# JournalX「检索并添加为新作者」没有匹配时弹出的新作者表：按左侧标签找输入框填写，再点「加入本文作者」。
# 每位作者的邮箱在系统里必须唯一，共用邮箱会被拒。
set -u
S=$1; shift; P="${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli} -s=$S"
$P run-code "async page => { const lab = async (txt) => page.locator('xpath=//td[contains(normalize-space(.), \"'+txt+'\")]/following-sibling::td[1]//input[1]').first(); const set = async (txt, v) => { if (!v) return; const el = await lab(txt); await el.fill(v); };
 await set('E-mail:', '$1'); await set('单位:', '$2'); await set('通讯地址:', '$3'); await set('邮政编码:', '$4');
 const prov = page.locator('xpath=//td[contains(normalize-space(.), \"省份:\")]/following-sibling::td[1]//select').first(); await prov.selectOption({ label: '$5' });
 const nat = page.locator('xpath=//td[contains(normalize-space(.), \"国籍:\")]/following-sibling::td[1]//select').first(); await nat.selectOption({ label: 'China' }).catch(()=>{});
 await set('第二单位:', '${7:-}'); await set('第二单位英文名称:', '${8:-}'); await set('验证码:', '$6');
 let msg=''; page.once('dialog', async d => { msg = d.message(); await d.accept(); });
 await page.getByRole('button', { name: '加入本文作者' }).click(); await page.waitForLoadState('load').catch(()=>{}); await page.waitForTimeout(2500); return (msg||'ok') + ' | ' + page.url(); }" 2>&1 | sed -n '/Result/,+1p' | tail -1
