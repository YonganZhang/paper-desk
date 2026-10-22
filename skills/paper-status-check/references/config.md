# 配置

本技能有两份 JSON 配置和一组环境变量。配置里只写环境变量名或取密码命令，不写密码真值。

| 文件 | 位置（环境变量覆盖） | 示例 |
|---|---|---|
| 查稿配置 | `PAPER_STATUS_CONFIG`，默认 `~/.config/paper-desk/status-check.json` | `assets/status-check.example.json` |
| 邮箱登记 | `PAPER_MAILBOXES`，默认 `~/.config/paper-desk/mailboxes.json`（建议 chmod 600） | `assets/mailboxes.example.json` |
| 投稿账号登记 | `$PAPER_SUBMIT_HOME/accounts.json`，与 paper-submit 共用 | paper-submit 的 `assets/accounts.example.json` |
| 定时任务环境 | `~/.config/paper-desk/status-check.env`（systemd `EnvironmentFile`） | `assets/status-check.env.example` |

查稿配置不存在时脚本按默认值运行，并在 stderr 提示；邮箱登记不存在时，扫信类脚本报错退出（体检脚本把邮箱一项全按未登记处理）。

## 查稿配置 `status-check.json`

| 字段 | 默认 | 含义 |
|---|---|---|
| `ledger_cli` | `paper` | 台账 CLI 命令（可带参数）；环境变量 `PAPER_CLI` 优先。脚本调用 `<cli> --json list/show/credentials/followup/check-in` |
| `self_names` | `[]` | 「本人」的姓名写法。台账没登记 `follow_mode` 时，负责人是其中之一就按 AI 代查推 |
| `always_scan` | `[]` | 本人的可读邮箱，每篇论文都扫；`untracked_scan.py` 只扫这些 |
| `blocking_confirm_journals` | `[]` | 确认信写明「合著者全部确认前不进入编辑流程」的期刊名（与台账里的期刊名一致）。这些刊的未确认合著者进「需要您处理」 |
| `near_acceptance_stages` | `["小修","已录用"]` | 邮箱混用例外到这些阶段时提醒改回 |
| `extra_manuscript_id_patterns` | `[]` | 漏登扫描额外识别的稿号正则（只用非捕获分组 `(?:…)`）。代码只内置 EM／ScholarOne 一类通用格式；某些刊自有格式（如 `XYZ-2026-0001`、五个字母加五位数字）照示例配置里的写法按自己期刊的确认信补 |
| `work_dir` | `~/.cache/paper-status-check` | playwright-cli 写快照的工作目录；环境变量 `PAPER_STATUS_WORK` 优先 |
| `report.from` | 空 | 每周报告的发件邮箱，必须在邮箱登记里配了 `smtp` |
| `report.to` | `[]` | 收件人列表 |
| `report.subject` | `投稿与期刊情况追踪（{date}）` | 主题模板，`{date}` 换成当天日期 |
| `report.greeting` | `您好：` | 正文第一行称呼 |
| `report.sender_label` | `投稿服务器` | 正文里「由…自动生成」的机器称呼 |
| `report.schedule_label` | `每周一` | 页脚里的发送频率说明 |
| `report.timezone` | 空（服务器本地时区） | IANA 时区名，例如 `Asia/Shanghai` |
| `report.out_dir` | `~/.local/share/paper-desk/weekly-status` | 报告存档目录（`<日期>.md` 与 `.json`，下周拿 json 对比状态变化） |

## 邮箱登记 `mailboxes.json`

顶层是 `{"mailboxes": {地址: 配置}}`（也接受直接的 `{地址: 配置}`）；以 `_` 开头的键当注释忽略。

| 字段 | 含义 |
|---|---|
| `imap` | `host[:port]`，默认端口 993，IMAP over SSL |
| `smtp` | `host[:port]`；只发信的邮箱需要 |
| `smtp_tls` | `ssl`（默认，465）或 `starttls`（587） |
| `username` | 登录名，默认就是地址 |
| `password_env` | 存密码或授权码的环境变量名 |
| `password_cmd` | 取密码的命令，stdout（去掉首尾空白）即密码（例如 `pass show mail/xxx`）；`password_env` 为空时才用 |
| `auth` + `token_cmd` | `auth: "xoauth2"` 时用 SASL XOAUTH2，`token_cmd` 输出当前有效的 access token。本技能不实现 OAuth 授权和续期，Outlook、Gmail OAuth 这类请用你自己的取 token 工具 |
| `readable` | `true` 表示已实测能读。先跑 `scripts/mailboxes.py check <地址>`，通过再手动标上。扫信和体检只认它 |
| `checked_at` | 上次实测日期（可选，体检里显示） |
| `owner`、`purpose` | 邮箱归谁、用途（会议专用、本人专用、临时合作者备用…）。录作者前对照它 |
| `author_links` | `[{person, role, papers: [编号…]}]`：这个邮箱在哪几篇论文里代表谁、什么角色（`投稿人`、`通讯`、`合著者`）。体检按 role 里有没有「投稿人」「通讯」判断关键邮箱 |
| `exceptions` | `[{person, papers, scope, reason, remind: "near-acceptance"}]`：用途不符但用户批准的临时借用；稿件到 `near_acceptance_stages` 时每周报告提醒改回 |

网易系邮箱（163、126、yeah.net）登录后要先发 IMAP ID 命令，`mailboxes.py` 已处理。Gmail 应用专用密码存成不带空格的形式。

## 环境变量汇总

| 变量 | 作用 |
|---|---|
| `PAPER_STATUS_CONFIG`、`PAPER_MAILBOXES` | 两份配置的路径 |
| `PAPER_CLI` | 台账 CLI，覆盖 `ledger_cli` |
| `PAPER_STATUS_WORK` | 工作目录，覆盖 `work_dir`（`page_text.sh` 也读它） |
| `PAPER_BROWSER` | `paper_browser.sh` 的路径，默认同仓库 `skills/paper-submit/scripts/paper_browser.sh` |
| `PAPER_SUBMIT_HOME`、`PAPER_SUBMIT_DISPLAY`、`PAPER_SUBMIT_PLAYWRIGHT`、密码相关 | 与 paper-submit 共用，见 paper-submit 的 `references/setup.md` |
| `password_env` 指向的变量 | 各邮箱的密码或授权码 |
