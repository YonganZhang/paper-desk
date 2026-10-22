# ledger —— 课题组投稿台账

一个自托管的小网站 + 命令行，用来记清楚「哪篇论文、谁写的、投到哪、什么时候投的、用哪个账号投的、审到哪一步了」。
学生各自登记自己的论文，导师（管理员）一处看全；被拒转投只加新的一轮，投稿历史永久保留。

- 后端：FastAPI + SQLite（单文件库），页面是服务端渲染的 Jinja2 模板，无前端构建步骤，手机可用。
- 命令行：`paper`（`bin/paper` → `paper_cli.py`），走同一套 HTTP API，适合 SSH 和 AI 助手调用。
- 功能：论文 / 投稿轮次 / 附件版本、期刊进展与审稿意见时间线、逐篇跟进计划、公共投稿账号池、花名册、
  管理员专用加密期刊账号、CSV 导出、只读 / 读写两种 API token。

**这个目录放什么**：程序代码、页面模板、测试、示例脚本。**不放**：运行数据（数据库、上传件、快照、密钥、token），
它们默认在 `data/`（已被 `.gitignore` 排除），部署时建议用 `PORTAL_DATA_DIR` 放到程序目录之外。
API / CLI 的完整说明在仓库的 `docs/api/`（`API.md`、`CLI.md`、`openapi.json`、`SAMPLES.md`）。
改动原因查 `git log -- <文件>`。

## 5 分钟本机跑起来

需要 Python 3.9+。

```bash
cd ledger
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 1) 初始化：建表 + 建管理员（会提示输入口令；也可用环境变量 PAPER_DESK_ADMIN_PASSWORD 非交互给出）
#    --api-tokens 顺便生成只读 / 写 API token，--samples 导入几篇虚构样例论文（可不加）
python3 seed.py --api-tokens --samples

# 2) 启动（默认 127.0.0.1:8611，数据在 ./data）
bash run.sh
```

浏览器打开 <http://127.0.0.1:8611>，用管理员登录（账号默认 `admin`，可用 `PAPER_DESK_ADMIN_USER` 改）。
学生在登录页「自己注册一个」：新装默认要邀请码（首次启动随机生成，管理员在后台「设置」里查看、修改或关闭）；关闭邀请码后任何能打开网站的人都能注册，公网部署时请保留。

另开一个终端用命令行（在 `ledger/` 目录下）：

```bash
mkdir -p ~/.local/bin && ln -s "$PWD/bin/paper" ~/.local/bin/paper   # 把 paper 放进 PATH（~/.local/bin 需在 PATH 里），之后任意目录可用 paper
bin/paper list
bin/paper show P01
bin/paper new --title "My First Paper" --authors "San Zhang;Alice Example" --pos 第一作者
bin/paper submit P03 --journal "Example Letters" --date 2026-09-09 --ms-id EXL-2026-0100
bin/paper --help
```

`bin/paper` 会顺着软链找回 `paper_cli.py`（也可以设 `PAPER_DESK_HOME=<ledger 目录>`），
并优先用 `ledger/.venv/bin/python`，所以不激活虚拟环境也能用。

### 管理员口令从哪来

- 跑过 `seed.py`：就是你输入（或 `PAPER_DESK_ADMIN_PASSWORD` 给出）的口令。
- 没跑 `seed.py` 直接启动：首次启动时如果库里还没有管理员，会自动创建；`PAPER_DESK_ADMIN_PASSWORD` 有值就用它，
  否则随机生成一个，**只在启动日志（stderr）里打印这一次**。
- 已有管理员时以上都不会再改口令。忘了口令时：先 `bash backup.sh`，再在 `ledger/` 目录（同样的 `PORTAL_DATA_DIR`）运行
  `python3 -c "import db,sqlite3; c=db.connect(); c.execute('UPDATE users SET password_hash=? WHERE username=?', (db.hash_password('新口令'), 'admin')); c.commit()"`。

### `paper` 命令的 token 从哪来

`paper` 通过 HTTP API 操作（所以写操作同样进审计日志、删前自动快照），需要 API token：

1. 生成：`seed.py --api-tokens`，或网页「管理」页的「外部 API token」（只读）和「写 token」（读写）按钮。
2. 读取顺序：环境变量 `PORTAL_TOKEN_FILE`（只读）/ `PORTAL_WRITE_TOKEN_FILE`（写）指向的文件（文件内容只有 token）；
   没设时从本机数据库 `settings` 表只读取出（所以在服务器本机上通常什么都不用配）。
3. 服务地址默认 `http://127.0.0.1:8611/api/v1`，用 `PORTAL_LOCAL_BASE` 改。

其他机器建议 SSH 到服务器上调 `paper`（见 `examples/paper_remote.py` 和 `docs/api/CLI.md`），不必分发 token。

## 配置项（环境变量）

| 变量 | 默认 | 作用 |
|---|---|---|
| `PORTAL_DATA_DIR` | `ledger/data` | 数据目录：`portal.db`、`uploads/`、`backups/`、`.session_secret` |
| `HOST` / `PORT` | `127.0.0.1` / `8611` | 网站监听地址（`run.sh` / `app.py`） |
| `PAPER_DESK_ADMIN_USER` | `admin` | 首个管理员账号名（只在还没有管理员时使用） |
| `PAPER_DESK_ADMIN_PASSWORD` | 空 | 首个管理员口令；空时 `seed.py` 交互询问、启动时随机生成并打印一次 |
| `PAPER_DESK_OWNER_NAMES` | 空 | 台账「本人」的姓名，逗号分隔（如 `张三,San Zhang`）。作者位次、是否通讯都是相对这个人记的；界面标签用第一个名字（「张三的作者位次」），为空时显示「本人」 |
| `PAPER_DESK_TZ` | `Asia/Shanghai` | 跟进计划时间戳和接口 `timezone` 字段的时区（IANA 名）。投稿日、天数等纯日期按服务器本地日期算，建议进程 `TZ` 与它一致 |
| `PORTAL_VAULT_KEY` | `<数据目录>/vault.key` | 管理员专用期刊账号的加密密钥文件（首次使用自动生成，权限须为 0600；生产部署建议指到数据目录之外的私有位置，并单独备份） |
| `PORTAL_LOCAL_BASE` | `http://127.0.0.1:8611/api/v1` | `paper` 命令访问的 API 地址 |
| `PORTAL_TOKEN_FILE` / `PORTAL_WRITE_TOKEN_FILE` | 空 | `paper` 命令用的只读 / 写 token 文件 |
| `PAPER_DESK_HOME` | `bin/` 的上一级 | `bin/paper` 找 `paper_cli.py` 的目录 |
| `PYTHON` | `python3` | `run.sh` / `backup.sh` / `bin/paper` 用的解释器（可指向虚拟环境；`bin/paper` 在 `ledger/.venv/bin/python` 存在时优先用它） |
| `PAPER_SSH_HOST` / `PAPER_REMOTE_CMD` | 空 / `paper` | `examples/paper_remote.py`：SSH 别名、远端 `paper` 命令路径 |

站点标题、首页公告、注册邀请码在网页「管理」页改，存在数据库 `settings` 表里。

## 数据放在哪

| 内容 | 位置 |
|---|---|
| 数据库（WAL 模式） | `$PORTAL_DATA_DIR/portal.db` |
| 上传的投稿包 | `$PORTAL_DATA_DIR/uploads/<paper_id>/` |
| 数据库快照 | `$PORTAL_DATA_DIR/backups/` |
| 登录 cookie 签名密钥 | `$PORTAL_DATA_DIR/.session_secret`（0600，自动生成） |
| 期刊账号加密密钥 | `$PORTAL_VAULT_KEY`（与数据目录分开保管） |

## 备份

```bash
bash backup.sh      # 立刻打一份数据库快照，保留最近 30 份，打印快照路径
```

- 快照只含数据库，**不含 `uploads/`**，附件请整目录另行备份（rsync / 网盘均可）。
- 加密密钥（`PORTAL_VAULT_KEY`）不在快照里；恢复数据库时必须同时恢复原密钥，否则加密的期刊账号无法解密。
- 接口的三个删除操作（删论文 / 删投稿轮次 / 删附件）会在删前自动打一份快照并在响应里返回文件名。

定时快照（crontab 示例，每天 03:17）：

```cron
17 3 * * * PORTAL_DATA_DIR=/srv/paper-desk/data /srv/paper-desk/ledger/backup.sh >/dev/null
```

## systemd 示例

`~/.config/systemd/user/paper-desk.service`（用户级服务；系统级把路径和 `WantedBy` 换成对应写法即可）：

```ini
[Unit]
Description=paper-desk submission ledger
After=network.target

[Service]
WorkingDirectory=/srv/paper-desk/ledger
Environment=PORTAL_DATA_DIR=/srv/paper-desk/data
Environment=PAPER_DESK_OWNER_NAMES=张三,San Zhang
Environment=PAPER_DESK_TZ=Asia/Shanghai
Environment=TZ=Asia/Shanghai
Environment=HOST=127.0.0.1
Environment=PORT=8611
ExecStart=/srv/paper-desk/ledger/.venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now paper-desk
journalctl --user -u paper-desk -n 50     # 首次启动若随机生成了管理员口令，会在这里
```

## 可选：反向代理 / 隧道

应用默认只监听 `127.0.0.1`。要让别人从外网访问，在前面放一层带 HTTPS 的反向代理或隧道，**不要**直接把 8611 暴露到公网。

Caddy 示例（自动申请证书）：

```caddy
paper.example.org {
    request_body {
        max_size 110MB
    }
    reverse_proxy 127.0.0.1:8611
}
```

nginx 示例（证书配置略）：

```nginx
server {
    listen 443 ssl;
    server_name paper.example.org;
    client_max_body_size 110m;          # 应用自身单文件上限 100 MB
    location / {
        proxy_pass http://127.0.0.1:8611;
        proxy_set_header Host $host;    # 跟进计划的网页写入会校验 Origin 与 Host 一致
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

也可以用 Cloudflare Tunnel 等隧道（`cloudflared tunnel` 把 `paper.example.org` 指到 `http://127.0.0.1:8611`）。
经 CDN 时注意两点：部分 CDN 会拦截 `Python-urllib` 默认 User-Agent（脚本请自带 UA，`paper` 和示例脚本已内置）；
CDN 可能限制单次请求体大小，大附件走服务器本机 `paper upload`。

## 安全提示（请部署前读）

- 🔴 **数据库里会存投稿系统账号和密码**（每轮投稿的 `sys_account` / `sys_password` / Cookie，以及公共账号池），
  这些字段是**明文**存储的；只有「管理员专用期刊账号」一区用 Fernet 加密。数据库文件、快照、上传目录要按敏感数据保管，
  不要放进 Git、网盘公开链接或聊天群。是否在台账里存这些凭证由部署者自行判断并承担责任。
- 首个管理员口令请用强口令，上线后在「我的账号」页再改一次；学生账号最短口令只要求 4 位，公网部署时请保留「注册邀请码」（新装默认开启）。
- 注册默认要邀请码（新装时随机生成）。管理员如果关闭邀请码，任何拿到网址的人都能注册，并能看到「公共投稿账号」页里的账号密码；公网部署务必保留邀请码，或只在内网 / VPN 使用。
- API token 分只读和读写两种。写 token 能改删数据、读取凭证和下载附件，只发给确实需要写的机器；泄露后在管理页轮换。
- 普通查询接口按字段白名单输出，不返回凭证；自由文本里混进的已知凭证值和 `password: xxx` 之类片段会被替换成 `[已脱敏]`。
  这是兜底，不是保证——不要把密码写进备注。
- 应用没有软删除。删除不可恢复（接口删除前有数据库快照，但附件文件删了就没了）。
- 正文检查（`paper text` / `inspect`）读 PDF 时调用系统的 `pdftotext`（poppler-utils，可选；未安装时 PDF 正文检查返回 422，其他功能不受影响）。

## 文件说明

| 文件 | 职责 |
|---|---|
| `app.py` | 网页路由（登录注册、论文 / 投稿轮次 / 附件、公共账号、花名册、管理、CSV 导出）与核心 JSON API；末尾挂载其他模块的路由 |
| `db.py` | SQLite schema、连接、口令哈希（PBKDF2-SHA256）、设置项、审计日志、配置项（环境变量）读取、首个管理员创建 |
| `seed.py` | 初始化：建表、建管理员、可选生成 API token、可选导入 `examples/sample_papers.json` |
| `tracking.py` / `tracking_api.py` / `tracking_cli.py` | 期刊进展 / 审稿意见 / 核查时间线、附件分类与下载、凭证接口、正文检查，以及对应的 CLI 子命令 |
| `followup.py` / `followup_api.py` / `followup_cli.py` | 逐篇跟进计划（乐观版本号防覆盖、证据事件、修订历史）；说明见 `FOLLOWUP_API.md` |
| `follow_mode.py` | 跟进方式 `papers.follow_mode` 的取值，并推导跟进计划是否活跃 |
| `rounds.py` | 投稿轮次规则：旧轮真实结局 `outcome`、补录历史轮的 seq 顺延、论文分类 |
| `credential_vault.py` | 管理员专用加密期刊账号（Fernet） |
| `documents.py` | 有界、只读的附件正文读取（不执行 TeX、不解压到磁盘） |
| `paper_cli.py`、`bin/paper` | 命令行入口 |
| `examples/` | `paper_remote.py`（经 SSH 远程调用 `paper`）、`check_papers.py`（只读 API 查询脚本）、`AI_PROMPT.md`（给 AI 助手的使用提示）、`sample_papers.json`（虚构样例） |
| `RESUBMISSION_POLICY.md` | 撤稿 / 重投场景的记录口径 |
| `templates/`、`static/` | 页面模板（`base.html` 是外壳）和样式 / 脚本 |

## 设计要点

### 状态模型：一层、五个词

| 字段 | 取值 |
|---|---|
| `papers.status` | 撰写中 / 投稿中 / 已录用 / 被拒 / 撤稿 |
| `submissions.status` | 投稿中 / 已录用 / 被拒 / 撤稿 |

- **「转投」不是状态，是「投稿的第 N 次」**，由 `submissions.seq` 表达。投稿就等于在审，转投也是在审，只是第二次在审。
- 论文状态由 `sync_paper_status()` 跟最新一轮自动同步。只有最新一轮有真实状态；更早的轮次由结构推导显示为「已转投」。
- 旧轮真实结局 `submissions.outcome` 是可选补记（被拒 / 撤回 / 编辑建议转投 / 编辑移除 / 未关闭），显示为「已转投（被拒）」这类；
  `未关闭` 表示原刊流程还开着，`paper watch` 会单列提醒，防一稿多投。
- 大修、小修、外审中等属于期刊进展（`paper progress` 记录的 `review_stage`），不占论文状态。
- 加状态前先问：它和现有的词是不是同义？同义词并存是台账混乱最常见的来源。

### 编号

三条独立序列：在投主序列 `P01..`、其他论文 `X01..`、新建时已录用的 `F01..`。**编号一旦分配不随状态自动变**（否则外部引用会失效），
要改由管理员手动改。判断是否在投只看 `status`，不看前缀。

### 论文分类（管理员口径）

`papers.category`：`main` 主序列 / `extra` 其他论文（不计入主序列）（不计入主要成果的论文，走 `X` 序列）/
`partner` 合作方论文（台账主人只是署名，沿用 `P` 编号，统计单列）。
作者位次 `author_pos`、是否通讯 `is_corresponding`、`category`、`follow_mode`、旧轮 `outcome` 只有管理员能在网页改；
**服务端也二次拦截**——学生提交的这些字段一律丢弃。改这几处时别只改模板：只藏 UI 不挡后端等于没挡。

### 权限

| | 学生 | 管理员 |
|---|---|---|
| 论文列表 | 只有自己录入的 | 全部，带「录入人」列 |
| 别人的论文详情 | 403 | 可看可改 |
| 公共投稿账号 / 花名册 | 只读 | 增删改 |
| 转移论文归属 / 重置口令 / 停用账号 / 站点设置 / API token | ✗ | ✓ |
| CSV 导出 | 只导自己的 | 全部 |

### 改数据的铁律

- **转投用新增一轮（`paper submit`），绝不改旧轮的期刊名**，否则投稿历史丢失。
- **批量脚本永远不要先 DELETE 再重建。** 系统上线后是多人并发写，先删后建会把别人刚手工录入的记录冲掉且无法恢复。
  批量脚本必须：先备份 → 只 UPDATE 具体字段或 INSERT 缺失项 → 冲突留给人判断。`seed.py --samples` 也按这个原则只补缺失编号。
- 补录更早的一轮用 `paper submit --history`：按日期插到正确位置，后面轮次的 seq 在同一事务内顺延，附件和事件仍挂在原轮上。

### 跟进方式与跟进计划

谁跟进、自动化脚本怎么做只认 `papers.follow_mode`（`ai` / `self` / `student` / `watch` / `partner` / 未登记）；
`lead_author` 只是跟进人姓名。跟进计划的审稿阶段、返修截止由台账推导，计划本身只记流程型卡点（等客服、等作者、暂缓等）。
详见 `FOLLOWUP_API.md` 和 `docs/api/CLI.md`。

### 手机适配

`static/style.css` 末尾的 `@media (max-width: 700px)` 负责窄屏：表格整体改成一行一卡。加新表格时每个 `<td>` 要带
`data-label="列名"`，主标题单元格加 `class="head"`；标签用 `inline-block` 而不是 grid（一个单元格多个子节点时 grid 会错行）。

### 「实时」刷新

列表页每 15 秒轮询 `/api/pulse`，论文数或最后更新时间变了才整页刷新，不是 WebSocket。

## 测试

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q tests
```

测试全部使用临时数据目录和临时加密密钥（`tests/conftest.py`），会在随机端口起一个隔离的服务跑真实 CLI，不碰任何真实数据。

## 已知边界

- 上传单文件上限 100 MB（`db.MAX_UPLOAD_BYTES`），超限当场丢弃，不留半截文件。
- 无软删除；删论文会连带删除其投稿记录和磁盘上的附件。
- 只有「管理员专用期刊账号」加密存储；投稿轮次和公共账号池里的凭证是明文（见「安全提示」）。
- CLI 只记录核查结果，不会自动登录或轮询期刊网站。
