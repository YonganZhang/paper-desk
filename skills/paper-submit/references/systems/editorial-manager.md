# Editorial Manager（Aries）：Elsevier 老刊、KeAi、部分 Springer 刊

实测：多个刊走到了「生成待批准 PDF」这一步；终点动作 Approve Submission 的位置见下文。

## 入口

- 网址形如 `https://www.editorialmanager.com/<刊名缩写>/`。以期刊官网 Submit 按钮给出的地址为准，缩写不一定是刊名首字母。
- 登录直接去 `login.ashx`。直接打开 `default.aspx` 时，iframe 可能还停在上一次的内部页。

## 账号与邮箱

- **每个期刊一个独立账号**，用户名和密码在各刊之间不通用。
- 注册流程：
  1. 从 `PreRegistration.aspx` 开始，填名、姓、邮箱，点 Continue。系统认出已有账号时会提示重复，这时用「Forgot Your Login Details?」找回，不要重复注册。
  2. 完整表单的必填项：用户名、密码两遍、Title、名、姓、邮箱、Institution、Country。地址可以填单位的公开地址。
  3. Confirm 页：必勾「接受出版商条款」，营销邮件勾「不接收」。
- 注册后立刻就能登录，不用等邮箱验证。
- 邮箱唯一性：同一篇稿件里，作者邮箱不能重复。重复时报「Duplicate e-mail addresses are not permitted」。
- 投稿人就是系统里唯一的通讯作者。投稿人的邮箱在 Manuscript Data 的作者编辑框里显示为「Your E-mail Address」；勾选「Save these changes to my user registration as well」后，会同步改掉账号资料里的邮箱。

## 步骤与终点动作

1. **Article Type Selection**：研究论文一般选 Research Article。
2. **Attach Files**：顶部列出必传项。先看这份清单，它决定投稿包的形态，比如要不要双盲、作者页要不要分开交。
3. **General Information**：Section/Category 按主题选；分类树可能为空。部分刊必须选 personal classifications。
4. **Additional Information**：期刊自定义问卷。按 form-answers.md 回答，原题和所选项记进声明清单。
5. **Comments**：可以留空。
6. **Manuscript Data**：题目、摘要、关键词、作者、基金。
7. **Build PDF for Approval**：混合刊会先出一个 Publishing Options 页，选 Subscription，然后点 Proceed。生成 PDF 要几分钟。
8. 稿件进入「Submissions Waiting for Approval by Author」，状态为 Needs Approval。到这里**还没有提交**。
9. **终点动作：Approve Submission**。在待批准列表的 Action Links 里。前面有 View Submission 可以先看 PDF。

修改已经生成的稿件：Action Links → Edit Submission，整个向导从头再走一遍。问卷和元数据会保留，改完必须重新 Build PDF。

## 文件与类型

- 页面上方「Select Item Type」先选好类型，再点 Browse，再 `upload`。一次只传一个文件，传多个不生效。
- Title Page (with author information) 只认 Word。传 PDF 的话，类型会停在 Choose。
- 利益冲突声明（Elsevier 系）：用出版社的 declaration 模板生成 .docx，不能转成 PDF。
- Manuscript：
  - 有的刊收 PDF；
  - 有的刊不收 PDF，要交 LaTeX 源（见「各刊差异」）。系统编译时找不到 `\input` 的子文件，要先把各节平铺进一个 main.tex，并核对编译结果和审阅版一致。
  - 系统编译 LaTeX 时不跑 BibTeX，上传的 `.bbl` 也不一定被读到，结果引文全显示成 `(?)`。
    - 做法：先在本地跑一遍 BibTeX，把 `.bbl` 的内容直接贴进 main.tex，替换掉 `\bibliography{…}`，同时删掉 `\bibliographystyle`；`.bib`、`.bst`、`.bbl` 都不再上传。
    - 本地只用要上传的这几个文件编译两遍，确认没有 `(?)`，再上传。
- 删除文件：勾选那一行最右边的 Delete，点 Remove，再点 Proceed 确认。

## 坑与对策

| 现象 | 原因 | 对策 |
|---|---|---|
| ref 每页都变 | 业务页在 iframe 里，翻页后前缀会变 | 每一步都重新 snapshot 取 ref |
| 「Institution could not be identified」，整张表被清空 | 用了 `fill`，联想列表没有被触发 | 先点输入框、等 1 秒，再用 `press` 一个字一个字地输，然后点选列表项 |
| 单位的按键打进了邮箱栏 | 焦点还没跟上 | 先点再等，填完回读核对 |
| 系统 PDF 里作者重复 | 添加作者报错后重试，留下了旧条目 | Remove This Author，然后在 jQuery 弹窗「Confirm Deletion」点 OK。弹窗没关的话，遮罩会挡住后面所有点击 |
| 摘要被截断 | 摘要里有 LaTeX 转义，例如 `\%` | 填纯 Unicode 文本，生成 PDF 后核对第 1 页的摘要结尾 |
| CKEditor 改不动 | `fill` 不会触发编辑器的变更 | 点 paragraph，`Control+a`、`Delete`，再 `type` |
| 「A network change was detected」 | iframe 没加载出来，请求通常已经发出 | 回到 default2，页面显示「Cannot Edit Submission」就表示正在构建，不要重复点 |
| default2 停在向导的某一页 | iframe 会恢复上次停留的页面 | 从顶部的 Main Menu 进各个列表看状态 |
| 下载 PDF 时 snapshot 里找不到链接 | `viewAuthorPDFs(…)` 写在 href 的 JS 里 | 从待批准 iframe 的 HTML 里取（em_wait_pdf.sh 已经实现） |
| 按钮名匹配失败 | 按钮文字前面带私有区图标字符 | 用不带图标的文字片段匹配，或直接用 ref |
| 拖动作者排序无效 | `drag` 和 dragTo 不触发 | 用 `page.mouse` 分 20 多步拖动行首的 `td.fl-listitem-sortable` |
| 勾了通讯作者，投稿人被换掉 | 系统只允许一位通讯作者 | 共同通讯只写在稿件里，系统里不勾 |
| 点开作者详情，弹出「Author's Name is Not Unique」，或详情框显示「Form could not be loaded」 | 上一个作者详情框还没关，就去点下一位作者 | 在确认框里点 Cancel，不要点 OK：OK 会再加一个同名作者。然后关掉详情框，切到别的步骤再切回 Manuscript Data，重读作者列表 |
| 登录页没有用户名密码框（Elsevier 刊常见） | 默认显示单点登录 | 展开「Alternatively, use your username and password」 |
| 弹窗要求在正文放 AI 声明 | Elsevier 系的统一提示 | 按 form-answers.md 处理，关掉弹窗即可 |

作者页写法：单位编号用 Word 真上标；所有通讯作者共用同一个上标星号，在下面逐人列出邮箱，投稿人另行注明。

## 各刊差异

示例，以投稿当时的期刊页面和系统为准；投新刊时把差异补进来。

- 某些刊（如 A 刊）双盲审稿，稿件按该刊的双盲要求准备。
- 某些刊（如 B 刊）要交 LaTeX 源，并且必须选 personal classifications。
- 某些刊（如 C 刊）对 Highlights 有条数和字数限制（例如 3–5 条、每条不超过 85 个字符），上传前逐条数字符。
- 投稿问卷各刊不同，常见题目：基金是否已写进致谢、是否引用补充材料、录用后是否付 APC、是否双倍行距加连续行号、SSRN、数据声明。逐题按稿件实际情况答，拿不准的按 `form-answers.md` 处理。

刊名缩写（`<刊名缩写>`，网址 `editorialmanager.com/<刊名缩写>/` 里的那一段）以该刊投稿页为准。

## 脚本

| 脚本 | 用途 |
|---|---|
| `em_register.sh <session> <用户名> <Title> <名> <姓> <邮箱> <单位检索词> <单位选项> <国家> [系 街道 城市]` | 注册 |
| `em_add_author.sh <session> <名> <姓> <邮箱> <单位检索词> <单位选项> <国家> <角色…>` | 添加作者并勾选 CRediT |
| `em_move_author.sh <session> <作者> <参照作者> [after\|before]` | 调整作者顺序 |
| `em_replace_file.sh <session> <刊名缩写> <旧文件名\|-> <类型> <新文件>` | 待批准稿件换文件；已经在 Attach Files 页时，可以连续调用 |
| `em_build.sh <session>` | 生成待批准 PDF，会处理 Publishing Options 和网络切换页 |
| `em_wait_pdf.sh <session> <刊名缩写> <out.pdf>` | 后台等 Needs Approval，然后下载 PDF |
