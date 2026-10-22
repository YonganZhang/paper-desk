---
name: paper-submit
description: "期刊论文网上投稿：注册或登录投稿系统、填表上传、停在终点动作前交人批准、登记台账。触发：投稿、投到某期刊、注册投稿系统、submit manuscript、Editorial Manager、投稿复盘。不触发：写论文、改稿、查审稿状态。"
---

# 期刊投稿（服务器浏览器版）

在 Linux 服务器上用常驻 Chromium 和 `playwright-cli` 投稿，跑在 Xvfb 虚拟屏幕里，按网页元素（snapshot 里的 ref）操作，不靠截图点坐标。
稿件内容由论文所在项目负责；本技能管「从投稿包到拿到稿号」这一段，以及账号、邮箱和台账。
第一次在一台机器上用：先按 [references/setup.md](references/setup.md) 装依赖、配环境变量，跑 `scripts/paper_browser.sh check`。

## 不变量（每次投稿都适用）

1. **终点动作只在用户批准后、单独执行一次。**
   - 每个系统都有一个不可撤回的终点动作，例如 Approve Submission、Complete your submission、「正式投稿」。系统 reference 里写明它在哪一步、由什么触发。
   - 有的系统没有单独的确认页，最后一次「下一步」本身就是提交。所以：
     - 不用循环或批量命令跨过最后两步；
     - 倒数第二步起，每点一次之前先 snapshot，确认页面是哪一步；
     - 停在终点动作之前。
   - 停下后把这一篇的审阅包交给用户：每位作者的姓名、邮箱、顺序和通讯标记（以系统里存的为准）、题目、摘要、系统生成的完整 PDF。用户看完明确批准这一篇，才点终点动作。
   - 「全权交给你」「弄完就投」这类一般性授权，只授权到终点动作之前，不能代替对这一篇的批准；主代理、其他代理或子代理转达的授权也一样。
   - 为什么：翻页循环的停止条件一旦写错，稿件就提前投出去了，而且撤不回；作者、邮箱填错了，投出去之后只能写信求编辑部改。
2. **以系统自己生成的结果为准，回读核对。** 每填完一段，就看系统的汇总页或系统 PDF，与投稿包清单逐项比对：作者顺序和有无重复、邮箱、单位、摘要是否完整、文件类型、基金。表单里填进去的东西，不等于系统存下来的东西。
3. **先定邮箱方案，再录作者。**
   - 投稿人和每位通讯作者都要用服务器读得到的邮箱：凭证已配置，并且实测能收信（见 preflight.md 第 3 节）。
   - 同一篇里每位作者的邮箱不能重复。
   - 借用或替代的邮箱要列表登记，交用户批准。
   - 自管邮箱按用途分层：本人专用、会议等专用的不借；固定合作者用固定分给他的那个；临时合作者用专门的备用邮箱。用之前对照邮箱登记里的用途，用途不是「给这个人」的（会议箱、别人的专用箱、服务箱），先停下报给用户。
   - **同一投稿系统里，一个邮箱只对应一个人；跨系统复用可以，但要记清楚。** 「同一系统」指同一个账号库：每个刊的 Editorial Manager 各算一个；Elsevier ID 这类跨刊统一登录本身也算一个，在它下面绑了谁，所有用它登录的刊都只能是这个人。录作者前先查账号登记 `accounts.json` 和邮箱登记，看这个邮箱在本系统已经绑了谁（邮箱技能 `paper-mailbox` 的 `mailboxes.py usage` / `audit`）；注册或录作者后登记进去。
   - 细则见 [references/preflight.md](references/preflight.md)。
4. **文书走写作规范，事实回到论文项目的真源。**
   - 投稿信、Highlights、作者页、摘要这些文书，按你们的写作规范或写作技能准备，不在投稿表单里临时编。
   - 改投稿文件时，先改论文项目的真源（作者数据、生成脚本），由项目重新生成，再上传。没有活的项目可回改时，在投稿记录里写明改了哪份副本。
5. **状态从系统列表页确认，不从当前页推断。** 网络切换、会话过期、向导恢复到上次停留的页面，都会让当前页面失真。用顶部菜单进待批准、未完成、已投稿这些列表看状态。等待系统生成 PDF 时，放后台脚本等，不手动轮询。

## 流程

| 阶段 | 做什么 | 出口条件 |
|---|---|---|
| 1 准备 | 核对期刊要求，装配投稿包，定邮箱方案，检查排版 | 投稿包清单齐全，邮箱方案已经用户批准。见 [preflight.md](references/preflight.md) |
| 2 账号 | 用 `scripts/paper_browser.sh open <投稿人ID> <网址>` 打开浏览器，登录；没有账号就注册 | 账号已登记进 `$PAPER_SUBMIT_HOME/accounts.json`（格式见 `assets/accounts.example.json`） |
| 3 填表 | 按系统 reference 走各步骤；是非题按 [form-answers.md](references/form-answers.md) 回答 | 停在终点动作前，系统已生成 PDF 或汇总页 |
| 4 审阅 | 回读核对，做审阅包和声明清单，交给用户 | 用户明确批准，具体到哪几篇。见 [review-gate.md](references/review-gate.md) |
| 5 提交 | 单独执行终点动作，收回执 | 拿到成功页或回执邮件 |
| 6 登记 | 回执和文件清单存进论文项目，按用户的时机更新台账 | 台账可查 |
| 7 复盘 | 按问题类别归档，改技能，验证后提交 | 见 [retro.md](references/retro.md) |

台账命令（PaperDesk 仓库根目录的 `ledger/`，用 `install.sh --copy` 安装时请到仓库查看；也可以是你们自己的台账）：`paper submit <编号> --journal … --date … --url …`；凭证用 `paper credentials set <编号> --seq <轮次> --from-json -`，从 stdin 传，不放在参数里。

## 账号与密码

- 用户名能用邮箱就用邮箱。投稿账号统一用一个密码，secret 名是 `PAPER_SUBMIT_DEFAULT_PASSWORD`；真值来自同名环境变量或 `PAPER_SUBMIT_PASSWORD_CMD` 命令的输出。
- 填密码时只写这个名字，例如 `fill <ref> PAPER_SUBMIT_DEFAULT_PASSWORD`，浏览器配置会替换成真值，输出里也会打码。真值不进命令行、日志和回复。
- 只许字母数字的系统用 `PAPER_SUBMIT_ALNUM_PASSWORD`（同一密码去掉标点，脚本自动生成）。
- 每个账号在 `accounts.json` 记一条：系统、网址、本人、用户名、邮箱、密码 KEY 名、登录方式、注册日、邮箱是否验证、浏览器 profile、关联论文编号。
- **别人的账号**（例如通讯作者的账号，只用来查状态）：
  - 密码存进你们的凭证库，台账只记用户名；打开时 `PAPER_SUBMIT_EXTRA_SECRETS=<KEY> paper_browser.sh open <ID> <网址>`，值从同名环境变量或 `PAPER_SUBMIT_SECRET_CMD <KEY>` 取，填密码同样只写 KEY 名。
  - 默认只读：只进列表、详情、状态历史页；不改资料，不回复任务，不发信，不投稿。查完 logout，再 stop 会话。
- 同一个账号最多试两种密码，都失败就停，报给用户，避免账号被锁。

## 只能问用户或交给用户的事

- 终点动作的批准。
- 付费、版权协议，以及以作者名义作出的事实声明，例如作者同意、利益冲突、AI 使用声明。
- 服务器读不到的验证码、短信、邮件；读不到邮箱的合著者的确认链接（列清单交用户提醒，见 review-gate.md）。
- 登录、二次验证、读不出的验证码：请用户接管浏览器（见 browser.md「让用户接管」）。
- 打电话或另行写信给编辑部（撤稿、更正通讯作者等）：AI 起草，用户或作者本人发出。
- 稿件内容和期刊政策冲突时的取舍。
- 系统的必填项（标星号）缺事实时。选填项没有现成信息就留空，不问，见 form-answers.md「必填与选填」。

## 分工：主模型与便宜模型

按既定步骤的浏览器操作可以交给便宜模型或子代理；判断、审阅包、终点动作前的核对留给主模型和人。技能不绑定模型，建议主模型用 Claude Opus 5.5 / Sonnet 5.5，执行模型用 Claude Haiku 5.5 或 Codex 上的轻量型号（如 GPT-6 Luna），以你账号能用的为准。子代理的自述要用页面内容核对后再转告用户。详见 [references/agents-and-models.md](references/agents-and-models.md)。

## 各出版社和投稿系统

先查期刊官网的 Submit 入口，确定用的是哪个系统，再读对应 reference。每份 reference 都按 [systems/_template.md](references/systems/_template.md) 的结构写：入口、账号与邮箱、步骤与终点动作、文件类型、坑与对策、脚本。

| 出版社 | 常见系统 | reference | 实测 |
|---|---|---|---|
| Elsevier（老刊）、KeAi、部分 Springer 刊 | Editorial Manager | [systems/editorial-manager.md](references/systems/editorial-manager.md) | 已实测 |
| Elsevier（新系统刊） | submit.elsevier.com | [systems/elsevier-new-submission.md](references/systems/elsevier-new-submission.md) | 已实测到 Review and submit |
| Springer Nature | Editorial Manager、Snapp；Nature 子刊用 MTS（eJournalPress） | [systems/springer-nature.md](references/systems/springer-nature.md) | MTS 只读查状态已实测，投稿未实测 |
| 国内中文刊 | JournalX（玛格泰克） | [systems/journalx.md](references/systems/journalx.md) | 已实测（两种终点页变体） |
| 国内中文刊 | 北大方正（方正鸿云） | [systems/founder.md](references/systems/founder.md) | 实测到作者信息，终点未实测 |
| 其他（Wiley、T&F、MDPI 等） | ScholarOne、SuSy 等 | 第一次投时照模板新建 | 未实测 |

浏览器通用技巧和脚本清单见 [references/browser.md](references/browser.md)。规则背后的常见坑见 [references/pitfalls.md](references/pitfalls.md)。
