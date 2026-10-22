# Elsevier 新投稿系统（submit.elsevier.com）

实测：走到 Review and submit 页为止；终点动作的位置见下文。

## 入口

- 网址形如 `https://submit.elsevier.com/<刊名缩写>/<稿件 UUID>/steps/<步骤>`。从期刊官网的 Submit your paper 进入。
- 同一出版社的期刊，有的还在用 Editorial Manager，有的已经换成这个新系统，以官网入口为准。

## 账号与邮箱

- 用 **Elsevier ID** 登录，和 ScienceDirect 是同一套账号，不是按期刊分开的。
- 注册时要点邮件里的确认链接，所以注册邮箱必须是服务器读得到的。
- 一个邮箱只能对应一个 Elsevier ID。换账号后，看不到别的账号建的草稿，只能新建；交付时写明旧草稿还留在旧账号下。
- 提交后，通讯作者会收到确认邮件，要登录（或设密码）才能跟踪稿件。所以通讯作者邮箱最好就用投稿账号的邮箱。
- **账号身份决定系统通讯作者**：
  - 提交后，稿件落到 Editorial Manager 里与这个 Elsevier ID 邮箱绑定的作者账号下；系统里的通讯作者就是这个账号的档案姓名，作者卡片上勾的「通讯作者」不起作用。
  - 所以投稿前要先查清楚：这个邮箱在该刊 EM 里有没有旧账号、档案名是谁，必须就是这篇预定的通讯作者。
  - 一个邮箱或账号已经替另一个人投过稿（例如做过别的稿件的系统联系人）时，不能再拿来投这篇。
  - 常见的坑：投稿用的邮箱早先绑在另一位合作者的 EM 账号上，提交后系统通讯作者成了一个不在作者名单里的人，只能写信请编辑部更正。
  - 提交后再改 EM 档案名（Update My Information）补不回来：账号和以后的邮件会用新名字，但稿件封面页是提交时生成的，重新下载仍是旧名，编辑和审稿人看到的就是这一页。改名之外仍要写信请编辑部改稿件记录；改名还会连带改掉这个账号下其他稿件的系统联系人，先问用户。
  - 一个邮箱在不同刊挂着不同人的 EM 账号时（例如某刊是甲、另一刊和 Elsevier ID 是乙），在这些刊只用用户名加密码登录，不点「Elsevier account login」，否则系统可能把乙的 Elsevier ID 绑到甲的账号上，造成上面这种串号。
  - EM 档案保存要求必填的 Personal Classifications 和 5 个以上 Personal Keywords；保存失败退回后，Institution 会恢复成旧值，要重新从下拉列表选。

## 步骤与终点动作

左侧「Submission tasks」依次是：
1. Choose your article type
2. Upload your submission files
3. Check or add your title, abstract and keywords
4. Check or add your author details
5. Add your funder details
6. Decide if you want to publish open access
7. Select your classifications
8. Provide additional information
9. Review and submit

每一步都要点 Save and continue。

- **终点动作**：Review and submit 页底部的「Complete your submission」。点它之前要勾 5 个确认框：ethics、copyright、submission declarations、authorship、funding acknowledgement。用户批准前，这些框都不勾。
- **提交前不生成系统 PDF**。审阅时把上传的 Word 转成 PDF，再附上系统里的元数据清单。

## 文件与类型

- 必传区只有 Manuscript、Cover letter、Highlights 等几种类型，**没有 Title page 类型**。作者信息只靠系统元数据。正文里要不要放作者页，按期刊的审稿方式（单盲或双盲）决定。
- 第一次上传 Word 正文时，系统会从文件里抽取题目、摘要和关键词。再传 Word 就不会再抽取了，所以正文要在第一次上传前定稿。之后替换文件，不影响已经填好的元数据。
- 替换文件：点该行的 `Delete <文件名>`（没有确认弹窗），再按类型重新上传。
- Declaration of competing interests：没有利益冲突时可以不传文件，改为勾选「无利益冲突」。但这句话包括「担任编辑职务」，作者里有该刊编委时不能勾。

## 坑与对策

| 现象 | 原因 | 对策 |
|---|---|---|
| ref 前缀一直在变 | 单页应用，节点不断重建 | 每次操作前都重新 snapshot |
| Contributor roles 只选上了一个 | 下拉框选一个就收起 | 每次重新打开下拉框再选（els_roles.sh 已经实现） |
| 单位选成了同名机构的其他分支 | 联想菜单里同名机构有多个分支 | 选项子串写到部门和城市，选完回读 |
| 基金机构搜不到 | 这里查的是机构库，不是 Crossref 基金库 | 点菜单最后一项「The institution name is not found」，保留手打的全称 |
| 点开出版方式后页面没反应 | Publishing Options 在新标签页打开 | 用 `tab-list` 和 `tab-select` 切过去，选 Subscription，点 Save and return，再切回原页 |
| 分类的父项勾选框是灰的 | 只能选子类 | 点父项那一行展开，勾 3–5 个子类 |
| 期刊指南页打不开（403 或系统错误） | ScienceDirect 有反爬 | 换浏览器标签页打开，或者以系统页内的提示为准 |

其他：
- 数据共享：稿件写「按需提供」时，选 No，再选「Data will be made available on request.」。
- SSRN 预印本：选 NO。

## 脚本

| 脚本 | 用途 |
|---|---|
| `els_upload.sh <session> <req\|opt> <类型> <文件>` | 按类型上传一个文件 |
| `els_author.sh <session> <名> <姓> <邮箱> <单位检索词> <单位选项子串> <yes\|no 通讯> <角色…>` | 填写当前打开的作者卡片并 Confirm。先点「Add another author」打开新卡片 |
| `els_roles.sh <session> <角色…>` | 只补选 CRediT 角色 |
