# 邮箱登记 `mailboxes.json`

位置：环境变量 `PAPER_MAILBOXES`，默认 `~/.config/paper-desk/mailboxes.json`，建议 `chmod 600`。示例见 `assets/mailboxes.example.json`。

顶层是 `{"mailboxes": {地址: 配置}}`（也接受直接的 `{地址: 配置}`）；以 `_` 开头的键当注释忽略，`link` / `unlink` 写回时原样保留。

## 字段

| 字段 | 含义 |
|---|---|
| `imap` | `host[:port]`，默认端口 993，IMAP over SSL |
| `smtp` | `host[:port]`；要发信的邮箱需要 |
| `smtp_tls` | `ssl`（默认，465）或 `starttls`（587） |
| `username` | 登录名，默认就是地址 |
| `password_env` | 存密码或授权码的环境变量名 |
| `password_cmd` | 取密码的命令，stdout（去掉首尾空白）即密码；`password_env` 为空时才用 |
| `auth` + `token_cmd` | `auth: "xoauth2"` 时用 SASL XOAUTH2，`token_cmd` 输出当前有效的 access token |
| `readable` | `true` 表示已实测能读。先跑 `mailboxes.py check <地址>`，通过再手动标上。扫信、体检和 `audit` 只认它 |
| `checked_at` | 上次实测日期（可选） |
| `owner` | 邮箱归谁、分给谁 |
| `purpose` | 用途。`audit` 按这几个词推断：含「会议」「服务」→ 不应登记为作者邮箱；含「专用」（不含「备用」）→ 只给 `owner`；含「备用」→ 给谁都行，但要登记 |
| `author_links` | `[{person, role, papers: [编号…]}]`：这个邮箱在哪几篇论文里代表谁、什么角色。`role` 写 `投稿人`、`通讯`、`作者`（可组合，如 `投稿人/通讯`）；含「投稿人」或「通讯」的是关键邮箱，必须 readable。`papers` 里每项取第一个词作编号，后面可跟备注 |
| `exceptions` | `[{person, papers, scope, reason, remind}]`：用途不符但用户批准的临时借用。`audit` 不再对这些（人, 论文）报用途提示；`remind: "near-acceptance"` 时，查稿技能的每周报告在稿件进入小修或已录用时提醒改回 |

不写密码真值。Gmail 应用专用密码存成不带空格的形式。

## 和投稿账号登记的分工

- `$PAPER_SUBMIT_HOME/accounts.json`（`paper-submit` 维护）：每个投稿系统账号一条，记「这个系统里，这个邮箱 → 哪个人」。字段见 `paper-submit` 的 `references/setup.md`。
- `mailboxes.json`（本技能维护）：每个邮箱一条，记凭证、能不能读、用途，以及「每篇论文里，这个人 → 这个邮箱」（`author_links`）。
- `usage <地址>` 把两边合起来看；`audit` 两边一起查。地址比较不分大小写。

## `audit` 检查什么

| 级别 | 检查 | 依据 |
|---|---|---|
| 必须处理 | 同一投稿系统里一个邮箱对应多个人 | `accounts.json`，按 `system` + 站点（域名加第一段路径）分组；`login: "elsevier-sso"` 的都算「Elsevier ID」一个系统 |
| 必须处理 | 投稿账号或 `author_links` 里投稿人、通讯作者用的邮箱没标 `readable` | 两边 |
| 必须处理 | 同一篇论文里同一邮箱登记给了两位作者 | `author_links` |
| 提示 | 投稿账号用的邮箱不在邮箱登记里 | 两边 |
| 提示 | 用途与绑定的人不符（见上面 `purpose` 的推断规则，`exceptions` 里的除外） | `mailboxes.json` |

「提示」是按文字推断的，报给用户判断；「必须处理」项让 `audit` 以退出码 3 结束，投稿前要先解决。

## `link` / `unlink`

- `link <地址> --paper P01 --person 姓名 [--role 作者]`：同一人同一角色已有条目就把编号加进去，否则新增一条。拒绝（退出码 3）的情况：这篇论文里该邮箱已登记给别人；这个人在这篇里已登记为别的角色（先 `unlink` 再 `link`）。登记关键角色而邮箱未标 readable 时给出提醒。
- `unlink <地址> --paper P01 [--person 姓名] [--role 角色]`：从匹配的条目里去掉编号，空条目一并删除；没有匹配就报错、不改文件。
- 写回前把旧文件复制成 `mailboxes.json.bak-<时间>`（保留权限），再原子替换；恢复时把备份改回原名即可。备份含凭证来源配置，和原文件一样不外发。

## 示例（虚构数据）

```json
{
  "mailboxes": {
    "alice@example.com": {
      "imap": "imap.example.com:993", "smtp": "smtp.example.com:465", "password_env": "MAIL_ALICE_PASSWORD",
      "readable": true, "checked_at": "2026-01-15", "owner": "张三", "purpose": "本人专用：投稿账号、期刊来信",
      "author_links": [{"person": "张三", "role": "投稿人/通讯", "papers": ["P01", "P03"]}]
    },
    "spare@example.org": {
      "imap": "imap.example.org", "password_cmd": "pass show mail/spare", "readable": true,
      "owner": "课题组", "purpose": "临时合作者备用",
      "author_links": [{"person": "李四", "role": "作者", "papers": ["P03"]}],
      "exceptions": [{"person": "李四", "papers": ["P03"], "scope": "仅 P03 投稿期间",
                      "reason": "李四暂无可读邮箱，录用前请改回他本人的邮箱。", "remind": "near-acceptance"}]
    }
  }
}
```
