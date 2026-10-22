# API 参考

基址 `<你的台账地址>/api/v1`（本机默认 `http://127.0.0.1:8611/api/v1`，下文示例用 `https://paper.example.org/api/v1`）· 认证 `Authorization: Bearer <token>`

机器可读版：[`openapi.json`](openapi.json)（OpenAPI 3.0.3），线上同一份走 `GET /openapi.json`（需同 token）。

---

## 🔴 必须发送 User-Agent

台账如果放在 CDN / 反向代理后面（例如 Cloudflare），CDN 的浏览器完整性检查可能拦掉
`Python-urllib/3.x` 这类默认签名，返回 `403`（Cloudflare 显示 `error code: 1010`），请求根本到不了认证环节。

任何自定义 UA（如 `paper-desk-client/1.1`、`curl/8.x`）一般都能通过；示例脚本已内置自定义 UA。
更彻底的做法是在 CDN 面板对 `/api/v1/*` 单独放行（例如 Cloudflare 的 WAF 规则跳过 Browser Integrity Check），
不建议为此关闭整站防护。本机直连 `127.0.0.1` 没有这个问题。

---

## 端点

### `GET /papers`

| 参数 | 说明 |
|---|---|
| `status` | 按论文状态过滤，如 `?status=投稿中` |
| `position` | 按「本人」（`PAPER_DESK_OWNER_NAMES` 配置的台账主人）的作者位次过滤，如 `?position=第一作者` |
| `q` | 标题 / 中文名 / 编号 模糊搜 |

返回 `{count, server_time, timezone, papers:[…]}`

### `GET /papers/{code}`

编号大小写不敏感（`p13` = `P13`）。比列表多 `files`。编号不存在 → `404`。

### `GET /stats`

`{total, by_status, by_author_position, corresponding_count, generated_at, timezone}`


另有两个字段：`by_category`（主序列 / 其他论文（不计入主序列） / 合作方论文 各几篇）和 `main_series`（只算主序列的统计，口径同其他字段）。原有字段口径不变。

### `GET /openapi.json`

本接口的 OpenAPI 描述，需同一 token。

### 错误码

| 码 | 含义 |
|---|---|
| `403`（CDN 返回，如 `error code: 1010`） | CDN 拦的，不是认证问题。加 User-Agent |
| `401` | token 缺失或不对 |
| `404` | 编号不存在 |
| `503` | 服务端还没生成 token |

---

## 数据语义（读之前务必看）

### 时区与日期

- `server_time` / `generated_at` / `updated_at`：`YYYY-MM-DD HH:MM:SS`，**服务器本地时间**，字符串里不带时区后缀；响应里的 `timezone` 字段给出部署配置的时区（`PAPER_DESK_TZ`）。
- `submit_date` / `result_date`：**纯日期，没有时间也没有时区**。是人手填的「哪天投的」，不是系统时间戳。
- `days_since_current_submit`：服务端按服务器本地日期算出的自然日差。客户端不必自己解析日期，避免时区偏差。

### 论文 `status`

`撰写中` · `投稿中` · `已录用` · `被拒` · `撤稿`

**等于最新一次投稿的状态**（服务端 `sync_paper_status` 自动同步）。没有任何投稿记录时是 `撰写中`。

### 🔴 不要用编号前缀判断当前是否在投

`P##` / `X##` / `F##` 是**分配编号那一刻**的历史分组（在投主序列 / 其他论文 / 已发表；「其他论文」指不计入主序列、不算主要成果的论文），
**编号一旦分配就不再随状态变化**（否则外部引用会失效）。
一篇 `P##` 后来录用了，编号还是 `P##`。

**判断当前状态只看 `status` 字段。** 前缀只有一个含义仍然可靠：`X##` = 其他论文（不计入主序列），
不计入台账主人的主要成果。合作方论文（`category` = `合作方论文`）沿用 `P` 前缀，靠 `category` 区分，同样不计入主序列。

### `is_current` 与「已转投」

`submissions` 按 `seq` 倒序，`[0]` 就是 `is_current: true` 那条，也是 `current_submission`。

**只有 `is_current: true` 的那条 `status` 是真实存储值。** 其余的 `status` 仍恒为 `已转投`（兼容老调用方）。

每轮另有两个字段：
- `outcome`：旧轮的真实结局，取值 `""`（未记录）`被拒` `撤回` `编辑建议转投` `编辑移除` `未关闭`。
  `未关闭` 表示原刊流程还挂着（例如大修邀请没撤），是防一稿多投要看的那一类。
- `display_status`：给人看的状态。当前轮 = `status`；旧轮按 `outcome` 显示 `已转投` / `已转投（被拒）` / `未关闭（原刊流程仍在）`。

保留下来的：`journal`、`submit_date`、`result_date`、`manuscript_id`、`notes` 都还在。

### `submission_count`

投了几次。`1` = 只投过一家；`>1` = 转投过，**转投次数 = `submission_count - 1`**。
「转投」不是状态，是第几次。

### 作者位次与通讯

- `my_author_position`（「本人」的位次）：`第一作者` / `第二作者` / `第三作者` / `第四作者` / `其他位置` / `非作者` / `""`
  - 第五作者及以后统一归 `其他位置`，不细分。
  - **`""` 表示管理员还没标注，不等于「不是作者」。**
- `i_am_corresponding`：布尔，**与位次相互独立**，可以同时是第一作者 + 通讯作者。
- 统计一作篇数请用 `GET /stats` 的 `by_author_position`，它已排除未标注的。

### 空字段怎么解释

| 情况 | 含义 |
|---|---|
| 论文级字符串是 `""` | 没录入。不代表不存在 |
| `authors` 是 `[]` | 作者顺序没录入。**不代表这篇没有作者** |
| 投稿级字段是 `null` | 该项没填（`submit_date`、`manuscript_id`、`result_date`、`site_url`、`notes`） |
| `current_submission` 是 `null` | 完全没有投稿记录（多半是 `撰写中`） |
| `days_since_current_submit` 是 `null` | 有投稿记录但 `submit_date` 空，**算不出天数，不要当成 0** |

### 超期判断：三个自然月 ≠ 90 天

两种口径都合理，但结果不同，**用之前先定死一种**：

- **90 天**：直接用 `days_since_current_submit >= 90`。服务端已算好，最省事。
- **三个自然月**：`(今年-投稿年)*12 + (今月-投稿月)`，若今天的「日」小于投稿的「日」则减 1。
  例：2026-05-31 投 → 2026-08-30 只满 2 个月，8-31 才满 3 个月。而按 90 天在 8-29 就到了。

差异最大可到 3 天（2 月更明显）。示例脚本 `--stale N` 用的是 **天数**口径，
同时在输出里把自然月数一并打出来，方便对照。

---

## 普通查询不返回什么

服务端用**显式字段白名单**（`PAPER_FIELDS` / `SUBMISSION_FIELDS`）拼输出，不是把行整个 dump 出来。

不在白名单里、接口永远拿不到的：

- `sys_account` / `sys_password`（每次投稿的投稿系统账号密码）
- `shared_accounts` 整表（课题组公共投稿账号池）
- `roster` 花名册、`users` 用户表与密码哈希、`audit` 操作日志
- 附件的磁盘路径（只给文件名、大小、说明、上传时间）

**另有兜底脱敏**：自由文本（`notes` / 标题 / `site_url` / 附件名等）在输出前会被扫一遍，
命中「库里存着的真实凭证值」或 `密码:xxx` / `password=xxx` / `https://user:pass@host` 这类模式的，
替换成 `[已脱敏]`。

例：把库里存着的某个密码和 `password: hunter2xyz` 写进投稿备注，
接口输出为 `临时测试：密码是 [已脱敏] 另外 [已脱敏]`（测试 `tests/test_vault.py`、`tests/test_tracking.py` 覆盖）。

## 两种 token

| token | 能做什么 | 在哪拿 |
|---|---|---|
| **只读 token** | 普通 GET；专用凭证/下载/正文接口和所有写操作返回 `403` | 管理页「外部 API token」 |
| **写 token** | GET + 新建 / 修改 / 删除 / 上传附件 | 管理页「写 token」 |

分开是有意的：只读集成（例如只查进度的脚本）不会因为后来加了写能力而获得改数据的权限。
两个 token 各自独立轮换，互不影响。

实测：只读 token 调 `PATCH` / `POST` / `DELETE` 一律 `403`；错 token `401`。

## 写接口

全部需要**写 token**。所有写操作都进审计日志（actor = `api`），删除前自动打数据库快照。

### `POST /papers` — 新建

JSON body，`title` 必填。可写：`title` `title_cn` `lead_author` `authors`（数组或换行字符串）
`corresponding` `status` `notes` `current_note` `author_pos` `is_corresponding` `category` `code` `follow_mode`。
返回 `201` + 论文对象（含自动分配的编号）。

### `PATCH /papers/{code}` — 改论文（部分更新）

只传要改的字段。传了白名单外的字段返回 `422` 并列出可写字段。

### 跟进方式 `follow_mode` 与当前情况 `current_note`

- `follow_mode`：`ai`（AI代查）/ `self`（本人自查）/ `student`（学生自管）/ `watch`（学生自管·AI盯截止）/
  `partner`（合作方自管）/ `''`（未登记）。写入也接受中文名和 `none`（=未登记），其他值 `422`，同一请求的其他字段不落库。
  网页只有管理员能改（口径同 `category`）。论文 JSON 输出 `follow_mode` 与 `follow_mode_label`。
  `lead_author` 只表示跟进人姓名。
- 写 `follow_mode` 时同步跟进计划 `active`（ai/watch→true，self/student/partner→false，未登记不动），
  跟进计划版本号 +1 并留修订记录。持有旧版本号的客户端下次写跟进计划会收到 `409`，重读即可。
- `current_note`：一两句话的当前情况，整段覆盖；`notes` 继续是只追加的历史记录。两者输出都走脱敏。

### 跟进计划 `/papers/{code}/followup`、`/followups`（与台账推导）

输出的 `stage`、`due_at`、`active` 为推导值，另给 `stage_source`/`due_source`（`ledger`|`followup`）、
`follow_mode`、`follow_mode_label`、`review_stage` 与存储原值 `stored_stage`/`stored_due_at`/`stored_active`。
`GET /followups` 新增 `follow_mode` 过滤参数（`none`=未登记）。推导规则与 schema 见 `openapi.json` 的 `Followup`。

**会让旧调用方收到 `422` 的写法**：

| 写法 | 改用 |
|---|---|
| PATCH 跟进计划 `stage` = draft/submitted/under_review/revision_required/resubmit_ready/accepted/closed | `POST /papers/{code}/events`（`paper progress --stage`） |
| 论文已有返修截止时 PATCH 不同的非空 `due_at` | 事件的 `due_date`（`paper progress --due` / `review-add --due`） |
| `follow_mode` 已登记时 PATCH 冲突的 `active` 或 DELETE 归档 | `PATCH /papers/{code}` 改 `follow_mode` |

流程型阶段 `unverified`（跟随台账）/`waiting_support`/`awaiting_author`/`awaiting_close`/`paused` 照常可写；
`POST /followups/import` 不做上述校验，历史数据照存。

### `POST /papers/{code}/submissions` — 新增一轮投稿（转投）

`journal` 必填。**旧轮自动成为历史，不会被删**；论文状态自动同步为新轮状态。
这是转投的唯一正确做法——**不要去改旧轮的期刊名**，那样历史就丢了。

补录更早的一轮：加 `"history": true`（必须是布尔值），此时 `submit_date` 必填。服务端按日期插到第一个
更晚的轮次之前，后面的轮次 `seq` 顺延 +1；不改当前轮和论文状态，附件与事件仍挂在原轮上。
新日期晚于所有已有轮次时返回 `422`（那是转投，不是补录）。可同时写 `outcome`。

### `PATCH /submissions/{sid}` — 改某条投稿记录

改完自动重新同步论文状态。`sid` 是 `GET /papers/{code}` 返回的 `submissions[].id`，
`paper show` 每条投稿记录行末也会打印 `[记录号 N]`。

可写 `outcome`（见上文取值，填别的值 `422`）。

### `POST /papers/{code}/files` — 上传附件

`multipart/form-data`：`f`（文件）、`label`（说明）、`submission_seq`（关联第几轮，可空）。
单文件 100 MB；经 CDN 时 CDN 自身也可能有请求体上限（如 Cloudflare 免费版约 100 MB），大包建议 SSH 进机器用 `paper upload`。

### `DELETE /papers/{code}?confirm=<code>` · `DELETE /submissions/{sid}?confirm=<sid>` · `DELETE /files/{fid}?confirm=<fid>&paper=<code>`

`confirm` 必须等于编号 / sid / fid，否则 `428`；删附件时可带 `paper=<code>` 让服务端核对归属（不符 `422`），会同时删磁盘文件，快照只含数据库。删除**不可恢复**（无软删除），
但服务端删前会自动打数据库快照并在响应里返回快照文件名。

### 写操作状态码

| 码 | 含义 |
|---|---|
| `403` | 用的是只读 token |
| `422` | 字段不可写、必填缺失、状态值/`follow_mode` 不在词表里；跟进计划写了台账推导的字段（见上） |
| `428` | 删除缺 `confirm` |
| `413` | 附件超过大小上限 |

## 本机命令行（SSH 进机器时用这个）

不经公网、无 UA 问题、token 自动读本地库（或 `PORTAL_TOKEN_FILE` / `PORTAL_WRITE_TOKEN_FILE`）：

```bash
paper list --status 投稿中
paper show P02
paper submit P02 --journal "Example Letters" --date 2026-09-09
paper upload P02 ./revised.zip --label "R1 修改稿" --seq 3
paper --help
```

## 1.3：完整维护接口

详细使用合同：[CLI.md](CLI.md)。普通查询仍不返回凭证；以下专用敏感接口只允许写 token。

| 方法与路径（均以 `/api/v1` 开头） | 权限 | 行为 |
|---|---|---|
| GET/PATCH `/papers/{code}/credentials?seq=N` | 写 | 读取/更新账号密码、网址、Cookie、extra；GET no-store；默认当前轮 |
| GET `/papers/{code}/events?seq=N&kind=review` | 读 | 时间线与审稿意见；省略 seq 列出全部轮次 |
| POST `/papers/{code}/events?seq=N` | 写 | 追加进展/核查/审稿/回复，默认当前轮 |
| PATCH `/events/{eid}` | 写 | 修改正文、审稿人、返修轮数或截止日期 |
| GET `/papers/{code}/files?kind=latex&seq=N` | 读 | 附件版本列表，ID 降序，含 latest |
| POST `/papers/{code}/files` | 写 | multipart 增加 kind 分类；原文件保留 |
| PATCH `/papers/{code}/files/{fid}` | 写 | 修改 kind / label / submission_seq（关联已有投稿轮次） |
| GET `/papers/{code}/files/latest/download?kind=latex&seq=N` | 写 | 下载最新上传原件，原始字节；X-File-Id 响应头 |
| GET `/papers/{code}/files/{fid}/download` | 写 | 下载指定版本原件 |
| GET `/papers/{code}/document?kind=latex&seq=N` | 写 | 返回正文、成员列表、静态检查结果；可指定 fid/member/all_text |

凭证 PATCH 接受 `site_url/sys_account/sys_password/sys_cookie/extra`。extra 必须为对象并整体替换；未提供字段保留。普通查询只返回 credentials_present 布尔值，既有只读集成不会因此获得读取凭证的权限。

事件 POST 接受 `kind/event_date/stage/text/reviewer/round/due_date`。kind 为 progress/check/review/response/note；check/note 不接受阶段/截止日期。stage 与论文总体状态分开，允许外审中/大修/小修/返修已提交等。事件日期不得在未来，due_date 可以在未来。PATCH 事件只允许修订 text/reviewer/round/due_date，新进展另建事件。

Paper 查询新增 `review_stage/last_progress_date/last_checked_date/days_without_progress/days_since_last_check/revision_due_date/revision_days_remaining/progress_date_basis`。没有结构化进展时，无进展天数从本轮 submit_date 计算，basis=submit_date；有事件时 basis=event。材料上传、凭证变更、check 事件不改变无进展天数。

接口不自动访问期刊网站，不自动把既有备注推断成正式审稿决定。历史附件默认 other；最新版本按上传 ID 判定，不代表已提交至期刊。

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
