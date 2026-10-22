# 投稿信

写、改、渲染投稿信时读本页。动笔前先过 [写作原则](writing-principles.md)；作者事实查作者名册。

## 1. 硬规则

| 规则 | 为什么 |
|---|---|
| 不写基金号，资助只用一句 "Funding … are fully disclosed in the manuscript" | 基金属于正文的致谢/基金节；信里重复显得不专业，也容易两处不一致 |
| 不主动推荐或回避审稿人；作者给了名单才写 | 涉及学术伦理与人情，由作者决定 |
| 不写利益冲突声明以外的人事信息 | 避免暴露未经授权的合作关系 |
| 必含：原创、未一稿多投、全体作者同意、无利益冲突（按事实）、通讯作者联系方式 | 期刊和投稿系统通常要求 |
| 不解释投稿系统的限制（如"系统只能登记一位通讯作者"） | 这类事由作者另行与编辑部沟通，信里写显得像辩解 |
| AI 使用声明放在期刊指定的位置（正文专节或系统问卷），信里不另写，除非期刊要求 | 声明内容由作者决定，见 `../paper-submit/references/form-answers.md`「生成式 AI」 |
| 期刊要求在信里说明的事项（如在审相关稿件、是否事先联系过编辑）按作者的决定写；作者决定不写时照办，并把决定记进论文项目 | 这些是以作者名义作出的事实声明 |

作者明确要求时才打破前三条，例如"信里加推荐审稿人 XXX"。

## 2. 结构（统一模板）

骨架在 `assets/cover_letter.md`；`assets/example_cover_letter.md` 是用同一骨架写的虚构示例，只借结构和句式，内容一律来自当前论文，不同论文之间不复用研究性的句子。

1. 投稿句："We respectfully submit our manuscript, "…", for consideration as <文章类型> in *<期刊>*."
2. 重要性与缺口：一句为什么重要 → "… faces a persistent challenge." → 现有两条路线各自的局限 → 由此留下的未知 → "This study addresses this gap …"。
3. 方法一段：以什么为基础、核心设计、覆盖的数据或案例。
4. "The manuscript makes four principal contributions." 然后四段**加粗开头**的贡献，每段 2–4 句：
   - 第 1 条：方法或评估本身，加决定性的验证数字（稳定性、准确性等）。
   - 第 2–4 条：主要发现，最后一条落到策略或应用。
   - 四条与正文引言的贡献一一对应；每个数字和主张在正文里有出处，最好由项目测试绑定（见 §5）。贡献只有三条就写三条，不凑数。
5. 期刊匹配："The manuscript is closely aligned with the scope of *<期刊>* through its integration of …"，可引该刊近两三年 2–3 篇文章（按 DOI 用 Crossref 核对，找不到合适的就不引），再用 "Beyond …, the study …" 说明本文给读者的价值；数据代码公开时一句带过。
6. 声明段："We affirm that this manuscript reports original work that has not been published and is not under consideration elsewhere. All authors have reviewed and approved the manuscript and declare no competing interests. Funding, data availability and code availability are fully disclosed in the manuscript." 期刊要求的其他声明插在第一句之后；有利益冲突时按作者给的事实改写。
7. 结尾 "Sincerely,"，然后签名块（脚本生成）。

篇幅以一页为目标；渲染脚本超过一页会报错，先删重复再调版式。

## 3. 渲染与依赖

```bash
python3 scripts/render_cover_letter.py <letter.md> <输出目录> --roster <authors.yml> [--assets <目录>] [--check-docx]
```

- 输入是带 YAML 头的 Markdown（键见 `assets/cover_letter.md`）。签名人写作者名册里的 id；不在名册里的人在信里直接写全 name、title、affiliation、email。名册格式见 `assets/authors.example.yml`。
- 输出 `cover_letter.pdf`（XeLaTeX，版式唯一来源 `assets/cover_letter_layout.tex`）和 `cover_letter_editable.docx`（同文同版式），并打印 JSON 报告：页数、签名人、缺签名图的人、LaTeX 警告。超过 `--max-pages`（默认 1）时退出码 1；输入有误时退出码 2。
- 图片：`<assets>/logos/<stem>.*` 是页首机构 logo，`<assets>/signatures/<id>.*` 是签名图；`<assets>` 默认是名册所在目录。
- 临时文件放在输出目录里，用完删除。论文项目里的生成脚本应直接调用它，不在项目里另写版式。
- 依赖：
  - 命令行工具：`pandoc`、`latexmk` 与 XeLaTeX（TeX Live 或 MiKTeX）、TeX Gyre Termes 字体（TeX Live 自带）、`pdfinfo`（poppler-utils）；`--check-docx` 另需 LibreOffice（`soffice`）。
  - Python 3.9+ 包：`python-docx`、`PyYAML`。没有装到系统里时可以 `uv run --no-project --with python-docx --with pyyaml python scripts/render_cover_letter.py …`。
  - 装不了 XeLaTeX 时：不用脚本，由模型按 `assets/cover_letter.md` 的结构直接写 Word 文档，版式照 §4，交付前人工核对一页、签名块完整。
- 测试：在本技能目录下 `python3 -m unittest discover -s tests -v`，渲染虚构示例并检查页数、签名人和缺签名时的留白。

## 4. 版式与签名

- 页首横排作者单位的 logo，左右分开；新机构的 logo 由作者提供。
- 全文黑色；居中标题 "Cover Letter"；其下 Title、Authors 两行；不写回邮件式的 "Re:"。
- 签名块每位通讯作者一栏：签名图 → 姓名 → 职称 → 单位（通常两行）→ Email。
  - **有签名图的放签名，没有的留同高空白**，同一封信里可以有的有、有的没有。
  - 签名图是个人信息：只用于作者要求生成的投稿信，放在私有目录，不进公开仓库（在 `.gitignore` 里排除 `signatures/`）。
  - 姓名不加 Ph.D. 等学位后缀；职称、单位、邮箱一律查名册，不抄旧信。
  - 顺序以作者指定为准；没指定时按论文作者顺序倒排，资深的在前。
  - 标签按人数写 "Corresponding Author:" 或 "Corresponding Authors:"。投稿系统只登记一位通讯作者时，信里是否列出作者页上的全部通讯作者，由作者决定。
- 签名图有透明边、黑边或白底不齐时，先修图（裁边、铺白底），原图另存。透明像素在 PDF 和 Word 里可能显示成黑线。

## 5. 交付前检查

- [ ] 贡献条目与引言贡献一致，数字与正文一致（理想做法：项目测试读取信的 Markdown 源，与正文比对标题、关键数字、签名人邮箱）
- [ ] 没有基金号、未经作者要求的推荐审稿人、系统限制说明
- [ ] 期刊匹配段的引文已按 DOI 核对
- [ ] 签名人顺序、职称、邮箱与名册一致；缺签名图的人已在渲染报告里列出并告诉作者
- [ ] PDF 和 DOCX 各一页，签名图边缘干净
- [ ] 以作者名义的声明（利益冲突、在审相关稿件、事先联系编辑）已经作者确认
- [ ] 作者需要时附逐段中文译文（英文为真源，译文放在回复或 `cover_letter_zh.md`）
