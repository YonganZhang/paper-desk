# 投稿包输出目录与命名

装配投稿包、给投稿材料起文件名、对外发送文件时读本页。目标：任何人或 AI 打开项目，不读说明就能找到"这篇投哪个刊、第几版、投稿信在哪"。项目已有固定输出目录时沿用项目的，只借本页的分层和命名。

## 1. 目录

```text
<论文项目>/_outputs/submission/
└── <journal-slug>-<round>/              例：ejws-initial、ejws-r1
    ├── v01_20260105/                    每次装配一个版本目录，装好后不再改
    │   ├── README.md                    清单：每个文件的用途、投稿系统里的文件类型、来源提交号
    │   ├── 01_manuscript/               正文、补充材料、匿名版、单独上传的图
    │   ├── 02_letters/                  投稿信、返修的回复信
    │   ├── 03_statements/               作者页、Highlights、利益冲突声明、清单表、给编辑的说明
    │   └── 04_supporting/               source data、Extended Data 单图、相关稿件副本
    ├── v02_20260108/
    └── latest -> v02_20260108           相对软链，指向最新版本
```

- `journal-slug`：期刊的小写短名，例如 `ejws`（虚构的 Example Journal of Water Systems）。同一期刊在所有项目里用同一个短名，团队可在本页补一张对照表。
- `round`：`initial` 首投，`r1`、`r2` 返修轮次；转投用新期刊的 slug 重新开始。
- 版本目录 `v<两位序号>_<YYYYMMDD>`：序号决定先后，日期给人看。重新装配就开新版本；只有确认上一版从未发出去时才覆盖它。
- 四个子目录固定，用不到的就不建。

## 2. 文件名

- 英文小写加下划线，只写用途：`manuscript.pdf`、`supplementary_information.pdf`、`cover_letter.pdf`、`highlights.docx`、`title_page.docx`、`declaration_of_competing_interests.docx`。
- 可编辑副本加 `_editable`，匿名版加 `_anonymous`，草稿加 `_draft`。
- 文件名里不放日期、版本号、期刊名，这些由所在目录表达，同一角色在任何项目里都叫同一个名字。
- 期刊规定了编号名的条目保留期刊写法，空格换下划线：`Extended_Data_Fig_1.pdf`、`Fig_2_source_data.xlsx`。
- 作者指定的文件名照用。

## 3. README 清单

每个版本目录的 README.md 写：

- 论文题目、期刊、轮次、装配时间（注明时区）。
- 来源：项目 Git 提交号，以及工作区是否有未提交改动；正文构建的版本标识。
- 文件表：路径 | 用途 | 投稿系统里选的文件类型 | 是否需要作者再确认。
- 还缺什么、由谁补。

## 4. 对外发送

文件离开版本目录时（邮件、网盘、上传前另存），改成自带身份的名字：

```text
<paper-slug>_<role>_<journal-slug>-<round>_v<NN>.<ext>
例：pgnet-demand_cover_letter_ejws-initial_v01.pdf
```

`paper-slug` 由论文项目定，同一项目里固定不变。

## 5. 归档

- `_outputs/` 是可重算产物，一般不进 Git；生成它的脚本、信的 Markdown 源、清单模板进 Git。
- 实际投出去的那一版，回执和最终文件按 `../paper-submit/` 的登记步骤存档，并在 README 里写明"已投出"；附件需要进台账时用 `paper upload`（规则见 `../paper-ledger/`）。
- 旧版本目录不删；需要腾空间时按项目归档规则移走。
