# 回复信格式

样式来自一份已经顺利提交的返修样例，整理成统一规范。真源写成 `response.md`，由 `scripts/build_response_docx.py` 生成 Word 和 PDF，颜色、字体和顺序都由脚本统一，不在 Word 里手调。

期刊对回复信有自己的格式要求时，按期刊来。

## 版式与颜色

| 元素 | 样式 |
|---|---|
| 页面 | A4，上下边距 1 in、左右 1.25 in，单倍行距，无首行缩进，页脚居中页码 |
| 正文 | Times New Roman 11 pt，两端对齐 |
| 稿号行、"Response to Reviewers"、各大节标题 | Times New Roman 12 pt 粗体，黑色 |
| 编辑、审稿人原文 | 黑色，原样照录，保留审稿人自己的编号和页行号（如 P1L57） |
| 作者回复 | 蓝色 0070C0，包括 "Response:" 标签、交叉引用和改后原文 |
| 回复里新贴的图表 | 图表本身黑色；新增的 panel 标签、新增的表格行、图注里新增的部分用红色，与标红稿一致 |
| 图表文字与图注 | Arial 8 pt，居中；图注和表题粗体；图与图注不跨页 |

## 结构顺序

1. 稿号行："Manuscript <投稿系统当前稿号>"。
2. "Response to Reviewers"。
3. 开头段（黑字）：称呼用 "Dear Editor," 或具名的 "Dear Dr. X,"；感谢编辑和审稿人；写出题目（粗体加引号）和期刊名；说明已采纳大部分建议、改动已在稿中标红、下面用蓝字逐条回复。
4. **先回编辑**（Response to the Associate Editor / Editor）：先完整照录编辑原文，再写一段总回复。编辑意见如果概括了多个审稿人的问题，在回复里（蓝字）拆成 (1)、(2)… 逐点回答：每点先用一句话复述这一点，再写做了什么，最后用 "— Addressed in R1.3 (Section 2)" 指到具体审稿条目。拆分是作者的整理，用蓝字写在回复里，不要写成黑字冒充编辑原话。编辑只说"请按审稿意见修改"时，一句感谢加"逐条回复见下"即可。
5. **逐个审稿人**：标题 "Reviewer 1"，照录 "Comments to the Author" 和开场白，再逐条：
   - 黑字照录意见，原文从决定信复制，不从旧的回复草稿里取；
   - **Response:** 致谢 → 同意或澄清 → 具体做了什么、改在哪里；
   - **The revised text reads (in Section X):**，下一段用方括号 [ … ] 贴出稿中改后的完整句子或段落；同一条改了多处时编号为 "The revised text 1 reads (in Abstract):"、"The revised text 2 reads (in Section 1):"；
   - 删了内容时，在 Response 里用一句话说明删了什么、为什么删，不贴原文；
   - 新增图表时，直接贴新图和新表，新增部分标红。
6. **没有新意见的审稿人**：照录肯定意见，**Response:** "Thank you!" 加一句感谢。
7. **主编或期刊办公室的补充要求**（如符号表、格式问题）单独成节，照录后回复，新增内容整段或整表贴进来。
8. 结尾一句总结，再加落款："Sincerely," 和通讯作者姓名（代表全体作者）。

## 位置写法

至少写到节（in Abstract / Section II-B / Conclusion）。期刊要求写清改动位置，或者稿件带行号时，再加页码和行号（"Section III-A, p. 7, lines 210–218"）。页码行号以最终标红稿为准，全部改完后统一回填并核对一遍，不要边改边写。

## 回复写法

- 每条回复都要指向正文改动：写清改在哪一节、改了什么，贴出改后原文；只回答不改稿的回复不能交付。删除的用一句话说明删了什么，用 deleted / removed 表述；与别的条目是同一处改动的写 "Please see our response to R1.5 (Section 2.3)."。没提要求的纯肯定意见除外，写法和理由见 [分类与写法](comment-handling.md) 的"每条都改正文"。
- 每条先回应审稿人的具体关切，不用空泛的感谢凑字；同一段里只致谢一次。
- 同意的：说清做了什么、改在哪里，贴改后原文。
- 措辞过强被指出的：承认原说法过强，改成有证据支持的限定说法，并说明全文同类说法一起改了。
- 不采纳的：先肯定建议合理，再给出本研究的具体理由，最后给出折中改动（如加段落分隔、补一句说明），并贴出改动。不以时间、经费或方便为主要理由。
- 不能做的实验：说明原因，给出替代证据或限定结论，并在 Limitations 里写清。
- 审稿人在附件里改过的英文：回复里说明已逐处采纳，并说明还请了谁或用什么方式做了全文润色。

## response.md 语法

先复制 `assets/response-template.md`。生成命令和依赖见文末「生成与依赖」。脚本识别的写法：

| 写法 | 生成效果 |
|---|---|
| 文首 `---` 包住的 `manuscript_id:`、`title:`、`journal:` | 稿号行和 "Response to Reviewers" |
| 第一个 `#` 标题之前的段落 | 黑字开头段 |
| `# 标题` | 粗体大节标题 |
| `>` 开头的行 | 黑字原文，按字面输出（`*`、`**` 等不当作格式）；`>` 空行分段。以编号开头（"1."、"(2)"、"Q3"）的段落各算一条意见，每条后面都要有回复 |
| 其他段落、`- ` 列表 | 蓝字回复 |
| `[[` 和 `]]` 各占一行，中间是改后原文 | 蓝字段落，自动加方括号。改后原文**必须**这样包起来，脚本才会拿它和稿件逐字比对 |
| `**粗体**`、`*斜体*`、`<sup>…</sup>`、`<sub>…</sub>` | 对应格式 |
| `<red>…</red>` | 红字（只用于新增图表元素） |
| Markdown 表格 | Arial 8 pt 三线表，默认黑字 |
| `![](图片路径){width=3in}`，同一行可放多张 | 居中插图 |
| `Caption: …` | Arial 8 pt 粗体居中图注或表题 |
| 单独一行 `<!-- closing -->` | 之后的结尾段和落款恢复黑字 |
| 单独一行 `<!-- no-change: 理由 -->` | 不输出；声明这条意见没提要求、不改稿，只用于纯肯定类意见，理由列入脚本汇总 |
| 其他单独一行的 `<!-- … -->` | 写给自己的备注，不输出 |

`--check` 只做检查不生成，检查的是回复信相关条目（见 [返修质检](qa-checklist.md) 中标"脚本"且属于回复信的条目），包括每条回复是否指向正文改动。BLOCK 必须修掉才能交付；`--draft` 用于写作中预览，不改变检查结果。

## 生成与依赖

```bash
python3 scripts/build_response_docx.py response.md -o Response_to_Reviewers.docx --pdf \
  --manuscript-text <干净稿 .docx / .pdf / .txt> --expect-comments <决定信里的原意见条数，含编辑意见>
```

- 依赖：Python 3.9+ 和 `python-docx`（`pip install python-docx`，或不装到环境里直接 `uv run --no-project --with python-docx python scripts/build_response_docx.py …`）；`--pdf` 需要 LibreOffice（`soffice`）；`--manuscript-text` 给 PDF 时需要 poppler-utils 的 `pdftotext`。
- 只做检查（`--check`）不需要 python-docx，只用标准库。
- 输出最后一行是 JSON 汇总；`"ready": true` 要求没有 BLOCK 且给了 `--manuscript-text`。退出码：0 = 没有 BLOCK；1 = 有 BLOCK（`--draft` 时不算）或 `--strict` 下有 WARN；2 = 参数错误。
- 装不了 python-docx 时：仍用 `--check` 跑完全部检查，再由模型按上面「版式与颜色」「结构顺序」直接写 Word 文档，交付前人工核对颜色、字体和顺序。
- 检查逻辑的测试：在本技能目录下 `python3 -I -m unittest discover -s tests -v`。
