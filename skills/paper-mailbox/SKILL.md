---
name: paper-mailbox
description: "论文邮箱登记与收发：期刊来信、验证码与确认链接、作者邮箱方案与一人一箱检查。触发：查邮箱、收验证码、确认链接、邮箱登记、作者用哪个邮箱、mailbox、verification email。不触发：查审稿状态（paper-status-check）、个人日常邮件。"
---

# 论文邮箱（登记与收发）

本技能是仓库里邮箱能力的唯一来源：`scripts/mailboxes.py` 连 IMAP（只读）和 SMTP（须确认），并维护「邮箱 → 人 → 论文」登记。查稿（`paper-status-check`）的扫信、周报和催人跟进都按相对路径加载这个文件；投稿（`paper-submit`）定邮箱方案时用它查登记和冲突。

## 不变量

1. **只读。** 收信、搜信、读信都以只读方式打开文件夹，不标已读、不移动、不删除。`links` 只把链接列出来，不打开；点不点、在哪个浏览器 profile 里点，由用户决定或按 `paper-submit` 的浏览器流程做。
2. **发信要显式确认。** `send` 不加 `--confirm` 只打印预览。不替用户回复编辑，不发催稿信；需要回信时把草稿交给用户。脚本调用 `send()` 的（每周报告、催人跟进）也必须默认预览、显式参数才发。
3. **一人一箱。** 同一投稿系统（按账号库算：每个 EM 站点各一个，Elsevier ID 单点登录本身算一个）里，一个邮箱只对应一个人；同一篇论文里两位作者不能用同一邮箱。投稿人和通讯作者的邮箱必须服务器能读（登记里 `readable: true`，且先用 `check` 实测过）。
4. **按用途分层，不乱借。**
   - 本人专用：只给 `owner` 本人用。
   - 固定合作者专用：分给某位合作者（`owner` 写他），只给他用。
   - 临时合作者备用：没有可读邮箱的临时合作者用，谁用了哪篇要登记。
   - 会议、服务等专用箱不登记为作者邮箱。用途不符但用户批准的借用写进 `exceptions`。
5. **凭证不落盘。** 配置里只写凭证来源，真值只在内存里；不把密码、token 写进命令行参数、日志或回复。

## 凭证三种来源（每个邮箱选一种）

| 来源 | 配置 | 说明 |
|---|---|---|
| 环境变量 | `password_env` | 变量名；定时任务放进 systemd `EnvironmentFile` |
| 取密码命令 | `password_cmd` | stdout 即密码，例如 `pass show mail/xxx`；`password_env` 为空时才用 |
| OAuth2 | `auth: "xoauth2"` + `token_cmd` | 命令输出当前有效的 access token；授权与续期由你的命令负责，本技能不实现 OAuth 流程 |

建议用应用专用密码或授权码。网易系邮箱登录后要发 IMAP ID，脚本已处理。

## 命令

在本技能目录下运行 `python3 -I scripts/mailboxes.py <命令>`；`inbox`、`search`、`links`、`usage`、`audit` 可加 `--json`。

| 要做的事 | 命令 |
|---|---|
| 看登记了哪些邮箱 | `list`（不联网） |
| 实测能不能读 | `check <地址>`，通过后在登记里手动标 `readable: true` 和 `checked_at` |
| 最近来信 | `inbox <地址> [--limit 20] [--folder INBOX]` |
| 找某封信 | `search <地址> --subject … --from … --body … --since YYYY-MM-DD`：服务器端搜索，中文关键词走 UTF-8；服务器不支持时报错，改用英文关键词或先 `inbox` |
| 读信、取验证码 | `read <地址> <uid>` |
| 取确认链接 | `links <地址> <uid>`：列出正文链接，★ 标出像验证/确认的 |
| 发信 | `send <地址> --to … [--cc …] --subject … --body …`；看过预览、用户同意后再加 `--confirm` |
| 这个邮箱给谁用了 | `usage <地址>`：邮箱登记的归属、用途、`author_links`，加投稿账号登记里用它注册的系统和人 |
| 查登记冲突 | `audit`：有「必须处理」项时退出码 3 |
| 登记 / 取消登记 | `link <地址> --paper P01 --person 姓名 --role 通讯` / `unlink <地址> --paper P01 [--person 姓名]`；写回前自动备份旧文件 |

退出码：0 成功；1 连接、凭证或配置失败；2 参数错误；3 违反登记规则（`audit` 有必须处理项、`link` 被拒）。

## 常见流程

- **定作者邮箱方案（投稿前）**：每位作者先 `usage <候选地址>` 看已绑了谁，再 `audit`；确认后 `link` 登记，回 `paper-submit` 的 preflight 表。
- **注册投稿系统、收验证码**：`search <地址> --from <系统域名> --since <今天>` 找到信，`read` 取验证码，或 `links` 取激活链接后在投稿人 profile 里打开。
- **合著者确认信**：`search --subject "verify your contribution"`，`links` 取确认链接；要合著者自己点时，把链接和步骤交给用户转发。

## 配置与登记

- 邮箱登记：环境变量 `PAPER_MAILBOXES`，默认 `~/.config/paper-desk/mailboxes.json`（chmod 600），示例 [assets/mailboxes.example.json](assets/mailboxes.example.json)。字段、`author_links`、`exceptions` 与 `audit` 规则见 [references/registry.md](references/registry.md)。
- 投稿账号登记：`$PAPER_SUBMIT_HOME/accounts.json`（与 `paper-submit` 共用），`usage` 和 `audit` 只读它。

## 测试

在本技能目录下运行 `python3 -m pytest -q tests`：`test_mailboxes.py` 测配置、凭证来源和收发；`test_commands.py` 用假 IMAP/SMTP 和临时 JSON 测 inbox / search / links / send / usage / audit / link / unlink。不联网。
