---
name: paper-revision
description: "期刊返修交付包：录决定信、拆审稿意见、标红稿+干净稿、逐条回复信(Word)、可选模拟审稿、登记台账。触发：返修、大修、小修、回复审稿人、response letter、rebuttal、revision。不触发：首次投稿材料（paper-submission-kit）、网上填表（paper-submit）、普通润色。"
---

# 论文返修

把一次期刊返修做成一套可直接上传的交付包，交付前可让几个模型假扮审稿人试审。本技能负责从收到决定信到交付包备齐；上传投稿系统交给 [`../paper-submit/`](../paper-submit/SKILL.md)，台账规则见 [`../paper-ledger/`](../paper-ledger/SKILL.md)。下文命令都在本技能目录下运行（`scripts/…`）。

在整条线里的位置：投稿前材料（`../paper-submission-kit/`）→ 投稿（paper-submit）→ 跟进（paper-status-check、paper-ledger）→ **返修（本技能）** → 再次提交（paper-submit）。

## 交付物

| 文件 | 格式 | 说明 |
|---|---|---|
| 回复信 | Word（上传用）+ PDF（阅读与试审用） | 真源是 `response.md`，由脚本生成，样式见 [回复信格式](references/response-letter-format.md) |
| 标红修改稿 | 沿用原稿格式：Word 稿出 docx，LaTeX 稿出 PDF | 新增或改写的文字标红；删除的文字直接删掉，在回复信对应条目里概述删了什么 |
| 干净稿 | 同上 | 由标红稿把红字转黑生成，两版文字逐字相同 |
| 试审汇总（可选） | 中文 Markdown | 各审稿者的结论和致命问题，以及主模型核实结果，供作者决定是否再改 |

稿件不换格式：期刊收的是 Word 就改 Word，收的是 LaTeX 就改 LaTeX。回复信统一从 Markdown 生成；改字时只改 `response.md`，再重新生成。

## 流程

每一步达到"完成标准"才进入下一步。

0. **录决定信。** 决定信全文和返修截止日先进台账（台账是截止日的唯一真源，跟进提醒据此推导）：
   ```bash
   paper review-add <编号> --text-file decision.txt --stage 大修 --due YYYY-MM-DD --date <决定信日期> --round 1
   paper upload <编号> decision.pdf --kind review --label "R1 决定信"   # 有原件时另存
   ```
   小修写 `--stage 小修`；第二轮返修 `--round 2`。返修是同一轮投稿的延续，**不用 `paper submit` 新增一轮**（转投才新增）。完成标准：`paper reviews <编号>` 能看到全文和截止日。
1. **收材料，定底稿。** 收齐决定信和全部审稿意见（包括只能在投稿系统里下载的附件和批注稿）；上一轮实际投出去的稿件和补充材料（用文件哈希、页数或系统 PDF 核对），冻结为只读底稿；期刊对返修的要求（截止日、高亮方式、页数与页费、回复填在哪个栏、要上传哪些文件）。
   工作区放在论文项目的返修目录（例如 `reviews/<轮次>/`）。正文继续在项目唯一的稿件真源里改，不另建一套正文。
   完成标准：每条意见都有原文；底稿版本有核对证据；期刊要求逐条列出。
2. **拆意见，出计划。** 给每条意见编号，按 [分类与写法](references/comment-handling.md) 归类，定下动作和改动位置，用中文给用户一张对照表。需要作者提供新结果或事实的条目标"待作者提供"，不编造。
   完成标准：对照表覆盖全部意见，每条都落到一处正文改动和位置（不采纳的写折中改动），用户已经看过。
3. **改正文。** 按 [标红稿与干净稿](references/manuscript-marking.md) 在真源里修改：新增或改写的文字标红，被替换的旧文字真正删掉，每处删除记进对照表。措辞按 [语气与写作](references/tone-and-cases.md) §5。
   完成标准：对照表里每条都有正文改动证据：新增或改写的有红字，纯删除的有删除记录；只有没提要求的意见（纯肯定）可以不改。
4. **生成两版稿件。** Word 稿跑 `scripts/docx_marked_to_clean.py`（只删不加的返修加 `--allow-no-red`），LaTeX 稿跑 `scripts/build_latex_versions.sh`。此后正文冻结；如果要再改，改完重新生成。
   完成标准：脚本退出码为 0，两版文字一致。
5. **写回复信。** 复制 `assets/response-template.md` 为 `response.md`，按 [回复信格式](references/response-letter-format.md) 写；不采纳和疑难情形读 [tone-and-cases.md](references/tone-and-cases.md)。生成：
   ```bash
   python3 scripts/build_response_docx.py response.md -o Response_to_Reviewers.docx --pdf \
     --manuscript-text <第 4 步的干净稿> --expect-comments <决定信里的原意见条数，含编辑意见>
   ```
   依赖 python-docx（`--pdf` 另需 LibreOffice），装法和无 python-docx 时的做法见回复信格式「生成与依赖」。写作中可加 `--draft` 预览。
   完成标准：脚本退出码为 0，没有 BLOCK，`"ready": true`。
6. **交付前质检。** 逐项过 [返修质检](references/qa-checklist.md) 第 1–5 节和第 6 节上传前的条目。
   完成标准：每项都标了"通过"或"已修复（改了什么）"；查不了的写明缺什么材料。
7. **模拟审稿（可选）。** 按 [多模型模拟审稿](references/mock-review.md) 打包冻结材料，用任意可用的模型或子代理各自独立假扮审稿人，给出通过与否和致命问题；主模型逐条核实后写中文汇总交给用户。发给外部服务前先问作者。
   完成标准：每个审稿者有一份通过 `verify` 的报告，或写明失败原因；汇总把每个致命问题标为"成立""不成立"或"无法判断"；是否继续修改由作者决定。决定修改的，回到第 3 或第 5 步，改完重新生成和质检。
8. **交付与提交。** 列出交付包里每个文件的路径和哈希（或页数），以及上传注意事项。上传交给 `../paper-submit/`（终点动作仍须作者对这一篇明确批准）；上传后按质检清单第 6 节核对系统生成的 PDF。
9. **登记台账。** 系统确认提交后：
   ```bash
   paper progress <编号> --stage 返修已提交 --date <提交日>
   paper review-add <编号> --kind response --text-file response.md --round 1 --stage 返修已提交
   paper upload <编号> Response_to_Reviewers.docx --kind response --label "R1 回复信"
   paper upload <编号> <修改稿> --kind manuscript --label "R1 修改稿"
   ```
   完成标准：`paper show <编号>` 显示阶段为返修已提交，`paper watch` 不再把它列为返修待办。

## 红线

- 每条意见都要改正文：意见不重要、或者没能完全做到的，也做一处小改动（补一句澄清、限定、定义或过渡），并在回复里写明改在哪、改了什么，贴出改后原文。只有没提任何要求的意见（纯肯定）例外，做法见 [分类与写法](references/comment-handling.md)。
- 回复里说改了的地方，正文必须真的改了，而且全文一致：同一个说法在摘要、正文、结论、图表里同步修改或删除。
- 不编造实验结果、统计量、页码、行号、引用和图表编号；作者没给的，在对照表里标"待作者提供"。
- 回复信和稿件里不出现 placeholder、TODO、XX 这类占位词。
- 稿号、题目、作者信息在回复信、稿件和投稿系统里保持一致；稿号用投稿系统里本轮的稿号。
- 新增结果、作者贡献变化、利益冲突、AI 使用声明等以作者名义的事实，由作者本人提供和确认；本技能只提醒和套模板。期刊在返修时问 AI 使用的，按 `../paper-submit/references/form-answers.md`「生成式 AI」交作者决定。
- 模拟审稿会把未发表的稿件发给模型服务；稿件有保密约定（合作方数据、专利等）时，先问作者。

## 测试

在本技能目录下 `python3 -I -m unittest discover -s tests -v`：`tests/test_response_checks.py` 测回复信的改动证据检查，不需要 python-docx。
