---
name: paper-status-check
description: "查已投论文的审稿状态与期刊来信：按跟进方式分流，AI 代查的登录投稿系统、扫通讯邮箱，含每周自动邮件报告。触发：查论文、查投稿状态、有没有回复、每周报告、check submission status。不触发：投稿（paper-submit）、改稿、登记台账。"
---

# 查论文（投稿状态核查）

本技能只做一件事：已经投出去的论文，期刊那边现在是什么状态，有没有来信。投稿本身走 `paper-submit`，改稿回论文项目，登记规则见台账技能 `paper-ledger`。

谁来执行：例行查稿（跑脚本、读列表页和邮件原文）可以交给便宜模型或子代理，主模型复核关键结论（决定信、需要作者动作、状态变化）后再汇报，分工见 [../paper-submit/references/agents-and-models.md](../paper-submit/references/agents-and-models.md)。
第一次在一台机器上用：按 [references/config.md](references/config.md) 写好查稿配置；邮箱登记和收发走技能 `paper-mailbox`，跑 `python3 -I ../paper-mailbox/scripts/mailboxes.py check <地址>` 验证邮箱。

## 不变量

1. **按跟进方式分流，不是每篇都查。** 分流只看台账的「跟进方式」（`follow_mode`）：
   - `ai`：登录投稿系统，并查期刊来信。
   - `self`：本人自查，跳过。
   - `student`、`partner`：不登录、不查信。学生或合作方自己管，用户点名时才看；催人跟进（`--remind`）默认提醒 `student` 的负责人，`partner` 不提醒，见 [references/reminders.md](references/reminders.md)。
   - `watch`：学生改稿，只提醒返修截止。
   - 没登记时脚本按负责人推（负责人是配置 `self_names` 里的人 → `ai`），并提示补登 `paper edit <编号> --follow-mode …`；推不出跟进人的，问用户是谁在跟。
   - 已录用、撰写中、被拒、撤稿：默认不查，用户点名时才查。
2. **每篇 AI 代查的论文，都必须有一条已实测的查询路径。**
   - 投稿人、系统通讯作者和第一作者，可能是三个人，也可能是同一个人。
   - 要先弄清：稿件挂在谁的账号下，在哪个系统、哪个网址；期刊来信发到哪个邮箱，服务器能不能读到。
   - 只「有账号」不算。要登录后在列表页亲眼看到这个稿号，才算可查。
   - 登录不进、看不到记录，或者投稿人和通讯作者的邮箱都读不到：当轮就告诉用户，并写明该找谁。不能只记一笔「待核实」就放过。
   - 为什么：一篇论文很久没消息，最后才发现一作、通讯、投稿人的账号都查不到这条投稿记录。
3. **只读。** 查的过程中，不点任何会改变稿件状态的按钮，例如提交返修、撤稿、批准、接受转投；不回编辑的信，不发催稿信。需要动作就报给用户。
4. **以系统列表页为准。** 状态以作者中心列表页为准，要看当前页面本身的状态，不凭印象推断。来信以邮件原文为准；邮件和系统不一致时，两边都记。
5. **查完就记，记的时候区分「有变化」和「没变化」。** 见下面第 4 步。

## 流程

| 步骤 | 做什么 |
|---|---|
| 1 体检 | `python3 -I scripts/access_audit.py`：只读台账、投稿账号登记和邮箱登记，列出 AI 代查的论文：每篇的登录路径、来信邮箱能不能读、上次实测时间，并标红黄绿 |
| 2 补路径 | 红、黄的论文先补齐查询路径，方法见 [references/access-rules.md](references/access-rules.md) |
| 3 查 | `scripts/mail_scan.py <编号…>`：每个能读的邮箱只连一次，按各轮稿号、题目和中文刊名一起匹配信头；要看正文时 `../paper-mailbox/scripts/mailboxes.py read <地址> <uid>`。然后 `scripts/page_text.sh <投稿人ID> <列表页网址>` 读系统列表页的纯文本（含 iframe），比整页 snapshot 省很多 token。各系统看哪一页见 [references/systems.md](references/systems.md) |
| 4 记 | 没变化：`paper check-in <编号> --note …`。有变化：`paper progress <编号> --stage … --date <系统更新日> --note …`；决定信用 `paper upload --kind review` 和 `paper review-add`。第一次在列表页看到稿号时，加一条跟进事件，正文以 `[可查性已验证]` 开头，写明系统、账号和稿号，体检脚本靠它判断是否已实测 |
| 4b 查漏登 | `scripts/untracked_scan.py --days 30`：扫本人邮箱（配置 `always_scan`）的投稿确认信，列出台账里没有的稿号。整篇漏登就 `paper new`，漏一轮就 `paper submit`；比当前轮还早的轮次用 `paper submit --history` 补录，旧轮结局用 `--outcome` 记 |
| 5 报告 | 按「AI 代查／不查」两段汇总，学生论文不报：每篇写当前状态、和上次相比的变化、需要用户做的事；查不到的写清是卡在哪一步 |

- 跟进计划（`paper followup`）同步改等待对象和下一步，改的时候必须带版本号（`--expected-version`），防止覆盖别人的修改。
- **作者确认要看确认页，不凭邮件推断。** 有的刊在列表行有 Author Status 链接；没有的直接打开 `ContributingAuthorStatus.aspx`，参数取自同一行 View Submission 的 `viewAuthorPDFs(…)`（见 systems.md）。同一个 EM 账号的列表页会列出账号下的全部稿件，一次能看到好几篇。
- **用户决定不管的事，写进跟进计划。** 例如旧稿撤回、不卡流程的合著者确认：在 `waiting_for`／`next_action` 里写明「用户某日决定不再跟进」。下次查论文先读跟进计划，不再报给用户。
- **用户要通知合著者去确认时，给他能直接转发的说明**：邮件主题、发件人、认准哪个稿号和日期、要点哪两个按钮，写法见 systems.md「给合著者的提醒」。

## 每周报告（可定时）

`scripts/weekly_report.py` 每周跑一次（systemd 用户定时器模板在 `scripts/systemd/`），生成中文报告，按配置 `report.from` 发给 `report.to`；主题、称呼、时区、存档目录都是配置项。

- **范围**：跟进方式 `ai` 的在投论文；其他只列编号，`watch` 另提醒返修截止。
- **内容**：分五节。一、需要您处理；二、和上周相比系统状态的变化；三、近 7 天的期刊来信；四、各篇当前状态；五、没查到的。「需要您处理」只放：卡流程的合著者未确认、非例行来信、21 天内到期的返修、邮箱混用待清理、台账漏登。
- **只读**：不点任何稿件按钮，不回信。系统页读到状态时给台账记一条 check-in。
- 手动跑：`python3 -I scripts/weekly_report.py`（只打印和存档）；`--send`、`--test`、`--no-browser`、`--no-checkin`、`--days`、`--remind`。安装定时器、各节细则见 [references/weekly-report.md](references/weekly-report.md)。
- **催人跟进**：`scripts/reminders.py`（或周报加 `--remind`）给组内跟进人各发一封汇总提醒：返修将到期、跟进计划卡住、在审太久没进展、旧轮未关闭。收件人只认配置 `people`，默认只预览，`--send` 才发；不给期刊发信。规则与配置见 [references/reminders.md](references/reminders.md)。

## 浏览器与账号

- 浏览器、投稿人 profile 和密码都沿用 `paper-submit`：打开浏览器用 `../paper-submit/scripts/paper_browser.sh open <投稿人ID> <网址>`；账号登记在 `$PAPER_SUBMIT_HOME/accounts.json`；密码只用 secret 名，真值不进命令、日志和回复。
- 登录状态保存在投稿人 profile 里。EM 会话过期时自己登录，不叫用户登录：按账号登记的 `login` 方式（`elsevier-sso` 点 Elsevier account login；`password` 填用户名和 secret 名），登上后直接开 Submissions Being Processed（`auth_pendSubmissions.asp`）。会话卡住（snapshot 超时）时，先 `paper_browser.sh stop <投稿人ID>` 再重开，不要反复重试。
- 只存在台账本轮凭证里的密码，不是标准密码：
  - 用 `paper credentials show <编号> --reveal --out <新文件>` 取出，设成一个环境变量，`PAPER_SUBMIT_EXTRA_SECRETS=<该变量名> paper_browser.sh open …`，命令里只出现 secret 名；
  - 用完删掉凭证文件，unset 变量。
  - **同一个账号最多试两种密码**，都失败就停，报给用户，避免账号被锁。
- 要点击或填表时才 snapshot，并且只 grep 需要的 ref，不把整页输出读进上下文。
- 开浏览器前先看这个 profile 有没有别的会话在用：`pgrep -af "$PAPER_SUBMIT_HOME/profiles/<投稿人ID>( |$)"`。`page_text.sh` 遇到已开的会话会直接 goto，会把对方的页面跳走。查完用 `paper_browser.sh stop` 关掉自己开的会话。
- 邮箱：收信、搜信、读信、取确认链接、查登记冲突都用技能 `paper-mailbox`（`../paper-mailbox/scripts/mailboxes.py inbox | search | read | links | usage | audit`）；作者邮箱能不能读，看邮箱登记的 `readable` 和 `author_links`。

## 频率与阈值

- AI 代查的论文：用户要求时查；平时大约两周查一次。
- 有返修截止日的论文：截止前 14 天起，每次报告都要提。
- 学生、合作方论文：不查。提醒只走催人跟进（`reminders.modes` 控制哪些跟进方式提醒）。
- 同一阶段停留太久时（例如 With Editor 超过 60 天）：提醒用户考虑问编辑部，由用户决定，不自动发催稿信。

## 测试

`python3 -m pytest -q tests`（在本技能目录下运行）：`tests/test_reminders.py` 用假的台账 JSON 和假 SMTP 测提醒分组、去重、无法提醒清单、发信和跟进事件参数，以及周报 `--remind` 的串联，不联网。邮箱模块的测试在 `paper-mailbox/tests/`。
