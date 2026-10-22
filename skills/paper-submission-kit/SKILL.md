---
name: paper-submission-kit
description: "投稿前材料包：投稿信、Highlights、作者页、利益冲突/基金/CRediT/数据/AI 声明的模板与范本。触发：写投稿信、cover letter、highlights、title page、准备投稿材料。不触发：写正文、网上提交（paper-submit）、返修回复（paper-revision）。"
---

# 投稿材料包

论文正文以外、投稿时要一起交的材料，都由本技能准备：投稿信、Highlights、作者页、各类声明、基金与致谢、期刊表格，以及把它们装成一个整齐的投稿包。
正文写作归论文项目；打开投稿系统填表、上传、提交归 [`../paper-submit/`](../paper-submit/SKILL.md)；收到审稿意见后的返修归 [`../paper-revision/`](../paper-revision/SKILL.md)。

在整条线里的位置：**投稿前材料（本技能）→ 投稿（paper-submit）→ 跟进（paper-status-check、paper-ledger）→ 返修（paper-revision）**。

## 学术诚信边界

利益冲突、作者同意、作者贡献（CRediT）、AI 使用、基金名单、在审相关稿件这些都是**以作者名义作出的事实声明**。本技能只提供模板、列出期刊要求、提醒缺项，由作者本人决定内容并确认；作者确认前不写进投稿文件。细则见 [references/declarations.md](references/declarations.md) §1。

## 事实从哪里来

| 事实 | 真源 |
|---|---|
| 作者姓名、职称、邮箱、单位、ORCID | 课题组的作者名册（格式见 `assets/authors.example.yml`，放在私有项目里） |
| 机构 logo、签名图 | 名册旁的 `logos/`、`signatures/<作者 id>.*`（签名图不进公开仓库） |
| 基金、致谢里的计算资源 | 课题组的基金登记（模板 `assets/funding.example.yml`），按论文方向选 |
| 题目、贡献、数字、数据与代码地址 | 论文项目的正文真源 |
| 期刊要求（文件清单、字数、审稿方式、政策） | 期刊官网当天核对，记进论文项目 |

材料里只引用这些事实，不另存手写副本。发现不一致时先改真源，再重新生成；名册和正文冲突时交作者裁定。

## 各类期刊要准备什么

| 材料 | Elsevier 系 | Nature 系 | 中文刊 | 规范 | 输出文件 |
|---|---|---|---|---|---|
| 投稿信 | 要 | 要 | 视刊而定 | [cover-letter.md](references/cover-letter.md) | `02_letters/cover_letter.pdf` + `_editable.docx` |
| Highlights | 常要 | 不要 | 部分刊要"要点" | [highlights.md](references/highlights.md) | `03_statements/highlights.docx` |
| 作者页 | 双盲时单独交 | 双盲时写进投稿信 | 常要 | [declarations.md](references/declarations.md) | `03_statements/title_page.docx` |
| 利益冲突声明 | 常要单独文件 | 正文里一句 | 正文或表格 | declarations.md | `03_statements/declaration_of_competing_interests.docx` |
| 基金、致谢、CRediT、数据与代码、AI 使用 | 正文末尾 | 正文末尾 | 首页脚注 + 正文 | declarations.md | 写回正文真源 |
| 作者简介 | — | — | 常要 | declarations.md | 写回正文真源 |
| Reporting Summary 等官方表格 | — | 常要 | — | 期刊官方模板 | `03_statements/` |
| Source data、Extended Data 单图 | 少见 | 常要 | — | 论文项目生成 | `04_supporting/` |

表里是常见情况；以当天核对的期刊指南为准，指南更严时照指南，并告诉用户差别。

## 流程

1. **核对期刊要求**：读 Guide for Authors，列出必交材料、审稿方式、Highlights 规格、AI 与相关稿件政策。清单见 `../paper-submit/references/preflight.md`「1. 当天核对期刊要求」。
2. **取事实**：作者查名册，基金按方向取基金登记，研究事实取正文。以作者名义的声明列成清单交作者确认。
3. **起草**：投稿信从 `assets/cover_letter.md` 起步，先读虚构范本 `assets/example_cover_letter.md`；正式文字过 [写作原则](references/writing-principles.md)。作者需要时附逐段中文译文。
4. **渲染**：投稿信用 `scripts/render_cover_letter.py` 出签名 PDF 和可编辑 DOCX（用法和依赖见 cover-letter.md §3）；其他 docx 材料由论文项目的生成脚本或模型按模板生成，不手改输出。
5. **装包**：按 [output-layout.md](references/output-layout.md) 放进 `_outputs/submission/<期刊>-<轮次>/v<NN>_<日期>/`，写 README 清单。
6. **检查**：数字与正文一致、PDF 与 DOCX 页数、签名边缘、投稿信里没有基金号、各声明已经作者确认；然后交 `../paper-submit/` 投稿，投出后的台账登记规则见 `../paper-ledger/`。

## 投稿信渲染

```bash
python3 scripts/render_cover_letter.py <letter.md> <输出目录> --roster <authors.yml> [--check-docx]
```

- 输出 `cover_letter.pdf` 和 `cover_letter_editable.docx`，打印 JSON 报告（页数、签名人、缺签名图的人、LaTeX 警告）。超过一页退出码 1，输入有误退出码 2。
- 依赖 pandoc、XeLaTeX（latexmk）、poppler `pdfinfo`、Python 包 python-docx 与 PyYAML；装不了时改由模型按模板写 Word，详见 cover-letter.md §3。
- 测试：在本技能目录下 `python3 -m unittest discover -s tests -v`。

## 只能问作者或交给作者的事

- 以作者名义的事实声明（见上"学术诚信边界"）。
- 推荐或回避审稿人、在审相关稿件、是否事先联系过编辑。
- 签名图、新机构 logo、名册里缺的作者信息。
- 期刊要求与作者意愿冲突时的取舍。
