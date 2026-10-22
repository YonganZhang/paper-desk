# 标红稿与干净稿

## 通用约定

- 在项目唯一的稿件真源里改；稿件格式不变（Word 稿改 Word，LaTeX 稿改 LaTeX）。上一轮投出去的版本冻结为只读底稿，只用来对比和试审，不在它上面改。
- 每一轮都从上一轮投出去的**干净稿**起步，不从上一轮的标红稿起步，否则上一轮的红字会被当成本轮修改。
- 新增或改写的文字标红：句子级以上的改动整句标红；只改一两个词时标改动所在的整句，让审稿人看得出上下文。
- 被替换的旧文字必须真正删掉。最常见的错误是旧句留在原处、新句接在后面，同一内容讲两遍。
- 删除的文字两版都不显示。每处删除在对照表里记一行（删了什么、在哪、为什么），写回复信时在对应条目里用一句话概述。只删不加的返修没有红字，生成干净稿时加 `--allow-no-red`。
- 新增的图、表、小节：标题和新增内容标红；新增的子图标签（如 "(c)"）、表格新增行、图注新增部分标红，其余保持黑色。
- 期刊上传稿不用 Word 的"修订"模式，也不用黄色高亮，除非期刊明确要求；期刊要求高亮或修订模式时按期刊来。给合著者审阅用的前后对照（如左右并排的 PDF 对比）另做，与上传稿分开交付。
- 改稿时保留期刊模板的特殊页和样式（如模板说明页、页眉稿号、行号设置），不顺手调整无关格式。

## Word 稿

1. 确认真源文件就是上一轮投出去的干净稿（哈希一致），另存一份只读副本作底稿。
2. 在 Word 里直接改，或用 python-docx 等库做保持格式的查找替换和段落插入（改 run 的文字，不重建段落，以免丢样式、公式和域代码）。新文字的 run 直接设为红色（`w:color w:val="FF0000"` 或 `EE0000`），不要通过样式着色；字体字号跟随所在段落。新增整张表时，表内全部单元格文字都标红。稿件里本来就有红色文字（如图例说明）时，修订改用另一种颜色，生成干净稿时用 `--colors` 指定。
3. 改完生成干净稿并检查：
   ```bash
   python3 -I scripts/docx_marked_to_clean.py \
     Manuscript_marked.docx Manuscript_clean.docx --list-red red_changes.md
   ```
   脚本把红字转黑，并检查：两版文字（含公式文字）逐字相同、干净稿没有残留红字、样式里没有定义修订红、没有残留的 Word 修订记录和批注；任何一项不过就退出码 1。输出里的 `colors_used_in_body` 用来发现本来就有的红字。`red_changes.md` 列出全部红字段落，标 ⚠ 的段落要人工确认旧句已删。
4. 用 Word 或 LibreOffice 把两版各转一份 PDF，抽查红字位置与图表版面。

依赖：`docx_marked_to_clean.py` 只用 Python 标准库。

## LaTeX 稿

1. 把 `assets/revmarks.tex` 复制到 `main.tex` 所在目录，在导言区加 `\input{revmarks}`。
2. 用宏标记改动：
   - `\rev{…}`：任意长度的新文字，可以包含公式，也可以跨段落；
   - `\begin{revblock} … \end{revblock}`：整段新增内容，如新小节、新表格主体；
   - 表格里每个单元格分别包 `\rev{}`，不要把 `&` 或 `\\` 包进同一个 `\rev{}`；
   - 章节标题：用了 hyperref 的稿件写 `\section{\texorpdfstring{\rev{New Title}}{New Title}}`，避免书签出错；没用 hyperref 的直接写 `\section{\rev{New Title}}`；
   - 不要直接写 `\textcolor{red}` 或 `\color{red}`，否则干净稿里也会是红色。
3. 同一份源码编译出两版并检查：
   ```bash
   bash scripts/build_latex_versions.sh main.tex out/ [pdflatex|xelatex|lualatex]
   ```
   依赖 `latexmk`、所选 TeX 引擎和 poppler-utils（`pdftotext`、`pdfinfo`）。输出 `out/main_marked.pdf` 和 `out/main_clean.pdf`，并检查两版文字一致，以及编译实际读到的全部 .tex（含 `\input` 的子文件）里没有绕开 `\rev` 的红字。
4. 期刊要求改动位置写页码行号时，在两版里都启用同样的行号（如 `lineno` 包），以标红版的页码行号填回复信。
5. 期刊要求上传 LaTeX 源码时，上传副本的 `main.tex` 第一行加 `\def\cleanversion{}`，连同 `revmarks.tex` 一起上传，这样系统编译出的是干净稿；上传前在一个新目录里用这份副本编译一次确认。

## 投稿系统生成的 PDF

上传后，投稿系统常把干净稿（主文档）、标红稿（marked copy）和图件拼成一份审稿 PDF。拿到系统 PDF 后核对：两版都在、标红版能看到红字、题目和稿号与回复信一致。
