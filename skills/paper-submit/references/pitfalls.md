# 常见坑：规则从哪里来

正文只写现行规则和「为什么」。这里按类别汇总实际投稿中反复出现的坑，以及它们沉淀成了哪条规则，方便复盘时查重（见 retro.md）。

## 不可逆动作

| 条件 | 做法 | 落到 |
|---|---|---|
| 用户说过「全权交给你」「弄完就投」，执行方就把它当成了终点批准 | 一般性授权只到终点动作之前；每篇在用户看过审阅包后单独批准 | SKILL.md 不变量 1、review-gate.md 第 3 节 |
| 用 `next()` 循环翻页，最后一次翻页就是正式投稿 | 终点所在步不进循环；倒数第二步起每次点击前 snapshot | SKILL.md 不变量 1、systems/journalx.md |

## 身份与邮箱

| 条件 | 做法 | 落到 |
|---|---|---|
| 会议专用邮箱、别人的专用邮箱被填成合著者或通讯作者邮箱 | 用之前对照邮箱登记的用途，不符就先报 | SKILL.md 不变量 3 |
| 同一个自管邮箱在同一系统里挂了多个人，事前没人登记、没人报 | 「邮箱 → 人」按系统登记；同一系统冲突先报 | preflight.md 第 3 节「系统范围」 |
| 通讯作者用了服务器读不到的邮箱，或几位作者共用一个邮箱被系统拒绝 | 先定邮箱方案表，再录作者 | preflight.md 第 3 节 |
| 投稿用的统一登录（如 Elsevier ID）早先绑在另一个人的 EM 账号上，提交后系统通讯作者成了不在作者表里的人 | 换刊或复用邮箱前查该邮箱在本系统绑了谁；提交后回读确认信 | preflight.md「账号身份」、systems/elsevier-new-submission.md、review-gate.md |
| 想靠改档案名把通讯作者改回来，账号名改了，稿件封面页仍是旧名 | 封面页在提交时生成，改名补不回；仍要写信请编辑部改 | systems/elsevier-new-submission.md |

## 系统与清单不一致

| 条件 | 做法 | 落到 |
|---|---|---|
| 系统 PDF 里同一作者出现两次 | 回读作者表；报错重试后先删旧条目 | review-gate.md、systems/editorial-manager.md |
| 摘要在 `\%` 处被截断 | 摘要框填纯 Unicode 文本，生成 PDF 后核对摘要结尾 | systems/editorial-manager.md |
| 系统编译 LaTeX 不跑 BibTeX，引文全成了 `(?)`，前两轮审阅都没发现 | 审阅时搜 `(?)`；把 `.bbl` 内容贴进 main.tex | review-gate.md、systems/editorial-manager.md |
| 中文刊摘要框里的上标变成「?」 | 改用 ASCII 写法，回确认页核对 | systems/journalx.md |

## 状态误判与证据口径

| 条件 | 做法 | 落到 |
|---|---|---|
| EM 的 default2 停在向导页、等待脚本卡死、网络切换页盖住结果 | 从顶部菜单进列表看状态；等待放后台脚本 | SKILL.md 不变量 5、em_wait_pdf.sh、em_build.sh |
| 合著者确认链接显示「not currently available」，被判成「失败」，其实早已确认 | 以投稿人账号的 Author Status 页为准 | review-gate.md 第 4 节 |
| 没查确认页，就告诉用户「某某要本人去点」 | 先查 Author Status 再下结论 | review-gate.md 第 4 节 |
| 曾说「合著者确认邮件可以不点」，实际该刊写明不确认就不进入编辑流程 | 合著者确认列清单交用户决定，以确认信原文为准 | review-gate.md 第 4 节 |

## 期刊要求与文书

| 条件 | 做法 | 落到 |
|---|---|---|
| 改投中文刊只核对了投稿须知，漏了模板里的结构式摘要、「式中」、图名字体等 | 模板说明逐条成表 | preflight.md 第 1 节 |
| 拿近期刊出的文章当样板，其实规范已经修订 | 下载中心各规范按最新修订日期执行 | preflight.md 第 1 节 |
| 用户第一眼看到的是公式乱、图小、大片空白：MathType 在 LibreOffice 下失真，图片有裁切属性，长段落不许跨页 | 排版检查 + `page_fill.py`；预览注明是 LibreOffice | preflight.md 第 4 节 |
| 双栏稿里小表、单面板图都用了通栏，单面板图还带孤零零的「a」 | 能放一栏的用单栏；单面板不加分图标号 | preflight.md 第 4 节 |
| 转写公式时发现原稿错误（符号、目标函数写反） | 转写对照原始公式；改动交审查并标「需作者确认」 | preflight.md 第 5 节（回真源） |
| 换文件、改作者页时只改了上传副本 | 改论文项目的真源再重新生成 | preflight.md 第 5 节 |
| 投稿信只套了版式，没走写作规范 | 文书走写作规范的全流程 | SKILL.md 不变量 4 |

## 系统表单

| 条件 | 做法 | 落到 |
|---|---|---|
| 为选填项（电话、地址、职称）追问用户 | 只保证必填项，选填没有现成信息就留空 | form-answers.md「必填与选填」 |
| 把期刊允许作者自选的审稿方式拿去问用户 | 作者自选时用期刊默认 | form-answers.md「常规类」 |

## 系统怪癖与浏览器

| 条件 | 做法 | 落到 |
|---|---|---|
| EM 删作者后点开另一位作者，弹出「作者名不唯一」，点 OK 多出一个作者 | 点 Cancel，关详情框，切步骤再回来 | systems/editorial-manager.md |
| 平台密码只许字母数字；注册必须短信验证码 | 用 `PAPER_SUBMIT_ALNUM_PASSWORD`；短信验证码交用户 | paper_browser.sh、systems/founder.md |
| JournalX 终点页因刊而异；排序按钮是 input；文件超过 5 MB 有提示 | 开投前看左侧步骤；按 `onclick` 定位；`docx_light.py` | systems/journalx.md |
| EM「Send E-mail」弹窗把浏览器会话挂住 | 按 PID 杀客户端，stop 再 open | browser.md |
| 用户接管浏览器时 AI 还在发命令，两边输入串字 | 接管期间不发命令，交还后重新 snapshot | browser.md「让用户接管」 |
| 用别人的账号查进度，要求绝对只读 | 只进列表、详情、状态页；查完 logout | SKILL.md「别人的账号」、systems/springer-nature.md |
