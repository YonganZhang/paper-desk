# 给 AI 的使用提示

把这一整页贴给你的 AI 助手（Codex / Claude Code / ChatGPT），它就会查了。

---

我有一个课题组投稿台账，记录我所有论文投到哪、什么状态。查询使用只读 API；完整维护优先走 SSH CLI（见 docs/api/CLI.md）。

**准备**
- 台账地址在环境变量 `PORTAL_BASE`（例如 `https://paper.example.org/api/v1`）。
- token 在环境变量 `PORTAL_TOKEN`。没设就提醒我去台账网站的「管理」页生成，**别自己编一个**。
- 认证 header `Authorization: Bearer $PORTAL_TOKEN`
- 🔴 **请求必须带 User-Agent**（任意自定义值）。台账如果经 CDN（例如 Cloudflare）暴露，默认 UA 可能被拦成
  `403`，根本到不了认证。看到 403 先检查 UA，别以为是 token 错了。

**端点**

| 我问什么 | 你查什么 |
|---|---|
| 我的论文都什么情况 | `GET /papers` |
| 在投的有哪些 | `GET /papers?status=投稿中` |
| 某一篇 | `GET /papers/P13` 或 `GET /papers?q=关键词` |
| 我一作几篇 / 通讯几篇 | `GET /stats` |
| 哪些我是一作 | `GET /papers?position=第一作者` |

也可以直接跑 `ledger/examples/check_papers.py`（`--watch` / `--stats` / `--stale N` / `--json`）。

**读数据的硬规则**

1. **判断当前是否在投，只看 `status`，不要看编号前缀。** `P##`/`X##`/`F##` 是分配编号那一刻的
   历史分组，之后不随状态变化。唯一仍可靠的前缀含义：`X##` = 其他论文（不计入主序列），不算我的主要成果。
2. **`submissions` 里只有 `is_current: true` 那条的 `status` 是真的**，其余恒为 `已转投`。
   别把历史条目当成当前进展汇报。
3. `submission_count > 1` = 转投过，转投次数 = `submission_count - 1`。转投不是状态，是第几次。
4. 我的身份看 `my_author_position` + `i_am_corresponding`，**两者独立可同时成立**。
   位次是 `""` 表示还没标注，**不等于我不是作者**。
5. 空值有含义：`authors: []` 是没录入不是没作者；`days_since_current_submit: null` 是
   投稿日期没填算不出来，**不要当成 0 天**。
6. 时区看响应里的 `timezone` 字段（部署时由 `PAPER_DESK_TZ` 配置）；`submit_date` 是纯日期，没有时间没有时区。
7. 普通查询不返回账号密码。经授权需要登录期刊时，用写权限的专用 credentials 接口或 SSH CLI；读取后不在回复或日志展示真实值。

**超期怎么算**

用 `days_since_current_submit`（服务端按服务器本地日期算好的自然日数）。
**三个自然月 ≠ 90 天**，最多差 3 天。除非我指定，默认用 90 天，并在结论里写明用的哪种口径。
在投超过 90 天的要主动提醒我。

**回答我的时候**

- 先说结论（几篇在投、有没有该催的），再列细节。
- `manuscript_id` 为空、`current_journal` 为空、`submit_date` 为空的，提醒我补。
- 字段是空的就说空的，**不要编造状态或日期**。

**改数据（只有拿到写 token 才能做）**

我如果给了你写 token（和只读的是两个不同的 token），你可以：

| 我说什么 | 你做什么 |
|---|---|
| 这篇被拒了 / 录用了 | `PATCH /submissions/{sid}` 改那一轮的 status |
| 转投到 X 了 | `POST /papers/{code}/submissions`，body 带 journal + submit_date |
| 稿号下来了 | `PATCH /submissions/{sid}` 带 manuscript_id |
| 传一下修改稿 / LaTeX | `POST /papers/{code}/files`（multipart） |
| 新论文录进去 | `POST /papers`，title 必填 |

**转投一律新增一轮，绝不改旧轮的期刊名**——改旧的会把投稿历史抹掉。

**删除要我明确说「删掉」才做**，且必须带 `?confirm=`。删了不可恢复。
只有只读 token 时，写操作会返回 403，那不是 bug，是权限设计。


## 完整维护入口（1.3）

需要编辑、账号密码/Cookie、LaTeX 上传下载、审稿意见和停滞筛查时，先读 docs/api/CLI.md。
优先用 `python ledger/examples/paper_remote.py <paper 子命令>` 通过 SSH 操作；密码和正文从本地文件/stdin 输入。
普通查询不回凭证；专用 credentials show --reveal 才读取敏感内容，不把凭证粘进回复或日志。
进度用 progress/check-in/review-add，附件用 upload/files/download/text/inspect，长期未动用 watch。
