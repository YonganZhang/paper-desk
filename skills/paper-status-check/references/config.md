# 配置

本技能用两份 JSON 配置和一组环境变量；邮箱登记属于技能 `paper-mailbox`。配置里只写环境变量名或取密码命令，不写密码真值。

| 文件 | 位置（环境变量覆盖） | 示例 |
|---|---|---|
| 查稿配置 | `PAPER_STATUS_CONFIG`，默认 `~/.config/paper-desk/status-check.json` | `assets/status-check.example.json` |
| 邮箱登记 | `PAPER_MAILBOXES`，默认 `~/.config/paper-desk/mailboxes.json`（建议 chmod 600） | `../paper-mailbox/assets/mailboxes.example.json` |
| 投稿账号登记 | `$PAPER_SUBMIT_HOME/accounts.json`，与 paper-submit 共用 | paper-submit 的 `assets/accounts.example.json` |
| 催人跟进去重状态 | `reminders.state_file`，默认 `<work_dir>/reminders-state.json` | 脚本自动生成 |
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
| `people` | `{}` | 提醒收件人：`{姓名: {email, role, cc_owner}}`。姓名与台账「负责人」一致（带「（…）」后缀的会去掉后缀再找）。`role` 自由填写（`owner`、`student`、`member`…），`external` 表示合著者等外部人员；`cc_owner: true` 时给这个人的提醒抄送本人。没登记的人不提醒、不猜邮箱 |
| `reminders.modes` | `["student","watch","ai"]` | 哪些跟进方式要提醒负责人；`self`、`partner` 默认不提醒 |
| `reminders.due_days` | `14` | 返修截止前多少天起提醒（已逾期也提醒） |
| `reminders.stalled_days` | `60` | 在审（跟进阶段 submitted / under_review）多少天没有进展时提醒负责人考虑问编辑部 |
| `reminders.blocked_stages` | `["awaiting_author","waiting_support","awaiting_close"]` | 跟进计划停在这些卡点时提醒负责人 |
| `reminders.waiting_pattern` | `等.{0,12}(作者\|合著者\|老师\|同学\|学生\|确认\|签字\|回复)` | `waiting_for` 命中这个正则，或写了 `people` 里的姓名，也算卡点；空串关掉 |
| `reminders.min_interval_days` | `7` | 同一（编号, 提醒类型, 截止日）多少天内不重复发 |
| `reminders.include_external` | `false` | `people` 里 `role: external` 的人是否提醒 |
| `reminders.owner` | 空（取 `self_names` 第一个） | 本人在 `people` 里的姓名；旧轮未关闭时总会提醒本人 |
| `reminders.from` | 空（用 `report.from`） | 提醒发件邮箱，须在邮箱登记里配了 `smtp` |
| `reminders.subject` | `论文跟进提醒（{date}）：{count} 项` | 主题模板，可用 `{name}`、`{date}`、`{count}` |
| `reminders.greeting` | `{name}您好：` | 称呼模板 |
| `reminders.signature` | `——` 加一句「只提醒组内跟进人」的说明 | 落款模板，可用 `{sender_label}`、`{date}` |
| `reminders.sender_label` | 空（用 `report.sender_label`） | 落款里的机器称呼 |
| `reminders.state_file` | 空（`<work_dir>/reminders-state.json`） | 去重状态文件 |

规则、示例邮件和边界见 [reminders.md](reminders.md)。

## 邮箱登记 `mailboxes.json`

字段（凭证来源、`readable`、`owner`/`purpose`、`author_links`、`exceptions`）和 `audit` 规则见技能 `paper-mailbox` 的 [references/registry.md](../../paper-mailbox/references/registry.md)。查稿只认 `readable: true` 且 `author_links` 关联到本篇的邮箱。

## 环境变量汇总

| 变量 | 作用 |
|---|---|
| `PAPER_STATUS_CONFIG`、`PAPER_MAILBOXES` | 两份配置的路径 |
| `PAPER_CLI` | 台账 CLI，覆盖 `ledger_cli` |
| `PAPER_STATUS_WORK` | 工作目录，覆盖 `work_dir`（`page_text.sh` 也读它） |
| `PAPER_BROWSER` | `paper_browser.sh` 的路径，默认同仓库 `skills/paper-submit/scripts/paper_browser.sh` |
| `PAPER_SUBMIT_HOME`、`PAPER_SUBMIT_DISPLAY`、`PAPER_SUBMIT_PLAYWRIGHT`、密码相关 | 与 paper-submit 共用，见 paper-submit 的 `references/setup.md` |
| `password_env` 指向的变量 | 各邮箱的密码或授权码 |
