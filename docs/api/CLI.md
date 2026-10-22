# 投稿台账 CLI：远程（含 AI 助手）操作合同

台账服务器上的 `paper`（`ledger/bin/paper`）是唯一业务命令，直接维护正在运行的台账。其他机器（如笔记本）优先用 SSH，
沿用已有 SSH 别名/密钥，不需要把台账 API token 或数据库拷到本地。

下文 `my-ledger-server` 是你的 SSH 别名，`/srv/paper-desk/ledger/bin/paper` 是服务器上 `paper` 的位置，按实际部署替换。

## 最短入口

```bash
ssh -T -n my-ledger-server '/srv/paper-desk/ledger/bin/paper --help'
ssh -T -n my-ledger-server '/srv/paper-desk/ledger/bin/paper --json list'
ssh -T -n my-ledger-server '/srv/paper-desk/ledger/bin/paper watch --days 30'
```

非交互调用（含 Windows 后台命令）使用 `-n`；需要发送正文或 JSON 的命令用 stdin，不能加 `-n`。跨平台 Python 包装器 `ledger/examples/paper_remote.py` 默认关闭 stdin，只有显式文件输入时才转发，避免 SSH 卡住。

```bash
export PAPER_SSH_HOST=my-ledger-server
export PAPER_REMOTE_CMD=/srv/paper-desk/ledger/bin/paper   # 默认 paper（需在远端非交互 PATH 里）
python ledger/examples/paper_remote.py --help
python ledger/examples/paper_remote.py --json show P02
python ledger/examples/paper_remote.py --json watch --days 30
python ledger/examples/paper_remote.py --host my-ledger-server --json list
```

要求 Python 3.9+、OpenSSH `ssh`/`scp` 和可用的 SSH 别名。包装器没有第三方 Python 依赖，不更改本地 SSH 配置。`--host` 放在最前（或用 `PAPER_SSH_HOST`），其余参数与 `paper` 相同。远端命令路径由 `PAPER_REMOTE_CMD` 指定。

## 投稿和期刊进度

```bash
paper submit P02 --journal 'New Journal' --date 2026-10-10 --url https://example.org/submit
paper sub-edit 19 --ms-id EXAMPLE-2026-001 --url https://example.org/submit
paper progress P02 --stage 外审中 --date 2026-10-10 --note '期刊网站核查'
paper progress P02 --stage 大修 --due 2026-11-10 --text-file decision.txt
paper check-in P02 --note '已核查，仍在外审，无新决定'
paper timeline P02
```

- 转投必须 `submit` 新增轮次，不能把旧记录的期刊改成新期刊。记录号用 `show` 读取。
- 总体状态保留：撰写中 / 投稿中 / 已录用 / 被拒 / 撤稿。大修、小修、外审等属于独立 `review_stage`。
- `progress`、`review-add`、`credentials` 默认当前最新投稿轮次，可用 `--seq N` 指定旧轮。
- 当前轮有阶段的事件按 `event_date`、事件 ID 排序推导最新阶段；录用/拒稿/撤稿同步总体状态，其余阶段同步为投稿中。回填旧日期的事件不会顶掉较新事件。
- `edit --status` 也同步当前轮总体状态；已有投稿轮次时不能改为撰写中。
- `check-in` 只记核查，不代表期刊有变化。普通论文备注、改密码和上传文件也不代表新进展。
- 日期严格为 `YYYY-MM-DD`；进展日期不能在未来，返修截止日期可在未来。
- 这些命令记录核查结果，**不会自动登录或轮询期刊网站**。

### 补录更早的投稿轮与旧轮真实结局

```bash
paper submit P02 --journal 'Earlier Journal' --date 2025-03-01 --history --outcome 被拒 --ms-id OLD-001
paper sub-edit 19 --outcome 未关闭
paper sub-edit 19 --outcome ''          # 清除，回到「已转投」
```

- `--history`（API 字段 `history: true`）补录一轮比当前轮更早的投稿，`--date` 必填。按日期插到第一个投稿日更晚的轮次之前，后面各轮 seq 顺延 +1；论文状态与当前轮不变，附件和审稿/进展事件仍挂在原轮上（显示的轮次号随之顺延）。新日期晚于所有已登记日期时拒绝（422）：那是转投，去掉 `--history`。
- `--outcome`（`submit` / `sub-edit`，API 字段 `outcome`）记录旧轮真实结局：`''`（未记录）、`被拒`、`撤回`、`编辑建议转投`、`编辑移除`、`未关闭`。
- 显示规则：最新轮照旧显示真实状态；旧轮 outcome 为空显示「已转投」，`未关闭` 显示「未关闭（原刊流程仍在）」，其他显示「已转投（被拒）」这类。`show` / `list` 文本用该显示值；JSON 每轮有 `outcome` 与 `display_status`，原 `status` 字段取值不变（旧轮仍为「已转投」）。

## 账号、密码、网站、Cookie 与扩展字段

```bash
paper credentials set P02 --from-json private.json
paper credentials set P02 --account author@example.org --url https://example.org/submit
paper credentials set P02 --password-file password.txt --cookie-file cookies.json
paper credentials show P02
paper credentials show P02 --reveal --out private-export.json
paper sub-edit 19 --password-file password.txt --account author@example.org
```

凭证 JSON 可包含：

```json
{
  "site_url": "https://example.org/submit",
  "sys_account": "author@example.org",
  "sys_password": "<在本地文件填写>",
  "sys_cookie": "<Cookie 请求头或浏览器 cookies JSON 原文>",
  "extra": {"platform": "Editorial Manager", "account_note": "submission contact"}
}
```

字段按需 PATCH，未提供的保留。`extra` 是完整替换的 JSON 对象，适合记录平台、备用账号、令牌或浏览器 storage 等；只改一项时先读取现有 extra 再合并。Cookie 的有效性和过期时间由期刊系统决定，台账只保存用户提供的原文。

远程机器用 `python ledger/examples/paper_remote.py credentials set P02 --from-json private.json`，包装器把文件经 SSH stdin 送入服务器，不把密码拼进进程参数。`--password-file`、`--cookie-file`、`--extra-file`、`--text-file` 同样自动处理本地文件。

默认 `credentials show` 只显示字段是否已保存；`--reveal` 才返回原值，建议加 `--out` 保存到新文件（0600，不覆盖）。所有凭证读写均需写权限并记录审计，审计不含字段值。只读 token 对凭证、附件下载和正文读取返回 403。普通查询与审稿文本会脱敏；附件下载原样返回，所以需要写权限。不要在对话回复、Git 或日志贴真实凭证。

## 论文分类

```bash
paper new --title '<标题>' --category partner      # main 主序列 / extra 其他论文（不计入主序列） / partner 合作方论文
paper edit P31 --category partner
paper new --title '<标题>' --extra                 # 旧参数，等同 --category extra
paper stats
```

- `partner` = 合作方论文，编号沿用 `P` 前缀（已有编号不变）；`extra` 仍走 `X`。JSON 的 `category` 输出中文名。
- `stats` 文本按主序列统计状态、位次和通讯数，其他论文与合作方论文单列、不计入主序列；JSON 原有 `total` / `by_status` / `by_author_position` / `corresponding_count` 口径不变（全部论文），另有 `by_category` 和 `main_series`。
- `--extra` 与非 extra 的 `--category` 同时给出时报错。

## 跟进方式与当前情况

```bash
paper edit P02 --follow-mode ai          # ai / self / student / watch / partner / none
paper edit P02 --current '外审中，等第二位审稿人'   # 当前情况：整段覆盖
paper edit P02 --notes '<备注>'          # 备注：历史记录
paper new --title '<标题>' --follow-mode student --current '学生在写初稿'
paper followup list --follow-mode ai     # none = 未登记
```

| `follow_mode` | 中文名（`follow_mode_label`） | AI 做什么 | 跟进计划 active |
|---|---|---|---|
| `ai` | AI代查 | 本人跟进，AI 登录系统查状态和来信 | true |
| `self` | 本人自查 | 跳过 | false |
| `student` | 学生自管 | 不查不提醒 | false |
| `watch` | 学生自管·AI盯截止 | 只提醒返修截止 | true |
| `partner` | 合作方自管 | 跳过 | false |
| `none`（存为 `''`） | 未登记 | 按旧口径 | 沿用跟进计划存储值 |

- 谁跟进、AI 怎么做**只认 `follow_mode`**；`lead_author`（负责人）只是跟进人姓名，脚本不要再从跟进计划 `action_owner` 里找「本人自查」。
- `edit --follow-mode` 同时把推导出的 active 写进跟进计划（版本号 +1，留修订记录）。之后直接 `followup set` 写冲突的 `active`、或 `followup archive`/`reopen` 与之冲突，返回 422。
- `show` 文本显示「跟进方式」，先「当前情况」后「备注」；`--json list` / `show` 有 `follow_mode`、`follow_mode_label`、`current_note`。

### 跟进计划的审稿阶段与截止由台账推导

`paper followup show/list` 输出的 `stage` 按论文状态和当前轮审稿阶段算（`stage_source=ledger`）：撰写中→draft，已录用→accepted，撤稿→closed，被拒→resubmit_ready；投稿中：大修/小修→revision_required，外审中/等待决定/返修已提交→under_review，编辑处理中/未标注→submitted。论文投稿中且跟进计划存的是流程卡点 awaiting_author / waiting_support / paused / awaiting_close 时保留（`stage_source=followup`）。`due_at` 有台账返修截止时用它（`due_source=ledger`）。存储原值在 `stored_stage` / `stored_due_at` / `stored_active`。

会收到 422 的写法（旧脚本要改）：

- `followup set` 写 `stage` 为 draft / submitted / under_review / revision_required / resubmit_ready / accepted / closed → 用 `paper progress --stage …`；
- 论文已有返修截止时写不同的 `due_at` → 用 `paper review-add --due` 或 `paper progress --due`（写空串允许）；
- `followup reopen --stage` 只接受 unverified / waiting_support / awaiting_author / awaiting_close / paused（unverified = 跟随台账）。

`followup import` 不做这些校验，历史数据照存。

## LaTeX、正文、审稿信、回复稿的版本

```bash
paper upload P02 /path/source.zip --kind latex --seq 3 --label 'R1 修改源文件'
paper upload P02 /path/decision.pdf --kind review --seq 3 --label '编辑决定与审稿意见'
paper upload P02 /path/response.pdf --kind response --seq 3 --label 'R1 回复'
paper files P02 --kind latex --seq 3
paper download P02 --latest --kind latex --seq 3 --out latest.zip
paper download P02 --id 123 --out original.zip
paper file-edit P02 123 --kind latex --seq 2 --label '原有投稿 LaTeX 包'
```

删除附件：

```bash
paper rm-file P02 123 --yes
```

服务端核对附件 123 属于 P02（不属于返回 422），删前打数据库快照，再删记录和磁盘文件并写审计；不加 `--yes` 拒绝执行。快照只含数据库，文件本身删除后不可恢复，删前确认已有别处副本。HTTP：`DELETE /api/v1/files/{fid}?confirm={fid}&paper=P02`（写 token）。

`kind` 支持 `latex / manuscript / review / response / supplement / other`。新上传不覆盖旧文件，ID 是稳定版本标识。`latest` 是筛选条件内最大文件 ID，表示最新上传，不证明已经向期刊提交。未指定 `--seq` 时查整篇论文全部轮次；需要审查某轮投稿稿件必须加 `--seq`。原有附件默认 `other`，可以用 `file-edit` 分类，无须重新上传；未绑定投稿轮次的旧附件可用 `--seq N` 明确关联，必须先核对，不能猜测。

```bash
python ledger/examples/paper_remote.py upload P02 ./source.zip --kind latex --seq 3
python ledger/examples/paper_remote.py download P02 --latest --kind latex --seq 3 --out ./latest.zip
```

包装器自动 SCP 上传/下载，并清理本次远端临时文件。传输失败返回非零退出码，本地下载先写临时文件再原子落盘。默认不覆盖本地目标，明确需要覆盖时用 `--force`。单附件上限 100 MB，走 SSH 可避开 CDN / 反向代理的单次上传限制，但仍受应用上限约束。

## 检查论文正文

```bash
paper text P02 --seq 3
paper text P02 --id 123 --member source/main.tex --out main.txt
paper inspect P02 --seq 3
paper text P02 --kind review --out review-text.txt
```

`text` 默认读取最新 `latex` 附件，识别 `.tex/.txt/.md/.pdf/.zip/.tar.gz/.tgz` 等。LaTeX 包自动找到含 documentclass 的主文件并展开静态 input/include。`--all` 查看所有文本成员。`--json text` 同时返回正文、成员列表与检查结果。`inspect` 只返回章节、缺失 include、未定义引用和未解析文献 key，不编译或执行 LaTeX。检查上限单文本 8 MB、累计 20 MB；拒绝路径穿越与符号链接；PDF 依赖服务器 pdftotext，最多 200 页。

7z、Word 附件可原样上传下载，暂不自动读取正文；需先转 ZIP/PDF。静态检查对宏定义生成的引用可能误报，不能替代完整编译或学术审查。

## 审稿与逐点回复

```bash
paper review-add P02 --text-file reviewer1.txt --reviewer 'Reviewer 1' --round 1 --stage 大修 --due 2026-11-10
paper review-add P02 --kind response --text-file response.md --round 1 --stage 返修已提交
paper reviews P02 --seq 3
paper review-edit 123 --text-file corrected-review.txt
```

`review-add` 新增独立记录，保存投稿轮次、审稿人、返修轮数、日期、截止日期和正文。审稿原件另用 `upload --kind review` 保留；逐点回复用 `--kind response`。`review-edit` 只修订选中的正文/审稿人/轮数/截止日期；新一轮进展请新增事件，避免覆盖历史。

## 哪些论文需要跟进

```bash
paper watch --days 30
paper watch --mode submitted --days 90
paper watch --mode unchecked --days 14
paper watch --mode due --days 7
```

默认只筛总体状态为投稿中的个人/合作论文。其他论文（extra）加 `--include-extra`，其他状态用 `--status`。模式含义：

| 模式 | 筛选规则 |
|---|---|
| stalled | 距当前轮最近 progress/review/response 事件 >= N 天；没有事件时从本轮投稿日算 |
| submitted | 距当前轮投稿日 >= N 天 |
| unchecked | 距最近 check-in >= N 天，或从未核查 |
| due | 返修截止在 N 天内，含已逾期；返修已提交/终结后不再提示 |

缺日期不会静默忽略：前三种模式会列出并提示补录。

不论哪种模式，总体状态为投稿中、且有旧轮 outcome=`未关闭` 的论文另列一节「旧流程未关闭（防一稿多投）」，给出编号、期刊、稿号、投稿日；JSON 字段 `unclosed_old_rounds`。这一节不受 `--include-extra` 过滤。`show` 与 `--json list` 同时提供投稿天数、无进展天数、最近核查日期、审稿阶段和返修截止日期；每次查询按服务器当天重新计算。

## 自动化与错误合同

`paper --json <command>` 输出 JSON，成功退出码 0；网络、业务、文件错误退出码 1，参数解析错误 2。错误信息走 stderr、stdout 为空。下载写入指定文件，不把二进制输出混入 JSON。CLI 不会弹交互确认；删除（`rm` / `rm-sub` / `rm-file`）须显式 `--yes`，服务端删前自动打数据库快照。

本机凭证自动从本地库读取。HTTP 直接调用可设置 `PORTAL_LOCAL_BASE` 和 `PORTAL_TOKEN_FILE` / `PORTAL_WRITE_TOKEN_FILE`（文件内容仅为对应 token）；经 CDN 时必须发送自定义 User-Agent。远程机器优先使用 SSH 包装器，避免另外分发 token。

验证：在 `ledger/` 目录运行 `python3 -m pytest -q tests`；全部测试使用临时数据库和临时密钥，不改真实论文。

## 管理员专用期刊账号

网站公共账号页新增「管理专用期刊账号（加密）」入口：`/private-accounts`。
此区仅管理员可用，不与共享账号池混用，不新增投稿轮次。

`paper journal-account list` 列表；`paper journal-account show "Example Journal"` 默认隐藏账号密码。
`paper journal-account set "Example Journal" --from-json -` 从 stdin 接收完整 `url/account/password` JSON。
确需登录时可 `show NAME --reveal --out NEWFILE`，文件权限0600，拒绝覆盖，不把内容输出到终端或对话。

API：GET `/api/v1/journal-accounts`；GET `/api/v1/journal-accounts/{name}`（默认隐藏，`?reveal=true` 明确读取）；PUT 同路径保存完整上述JSON。
全部端点要求写token；只读token返回403；响应no-store，审计不含凭证值。
账号和密码用Fernet加密存入独立表。密钥默认在数据目录下的 `vault.key`（权限 0600），可用 `PORTAL_VAULT_KEY` 指到别处；生产部署建议放在数据目录之外并单独备份。
恢复数据库时必须同时恢复原密钥；另行保管密钥，不能提交进仓库。数据库每日备份不包含密钥。
此新增区的加密不覆盖历史共享账号与投稿轮次凭证；这些旧字段仍沿用原有存储方式。
依赖：Python cryptography。新增测试覆盖密文、权限、默认隐藏、审计、脱敏和不改变投稿历史。
