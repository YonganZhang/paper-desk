# 逐篇论文跟进接口

跟进计划和台账存在同一个服务里；其他机器上的副本必须通过 API／paper 命令同步，不能直接拷文件。
原有论文、投稿轮次、附件、期刊审稿事件继续保留。跟进阶段独立于期刊总状态，
例如没有正式提交回执的草稿仍可登记等待客服，不能因此变成正式在审。

## 命令

远程入口：`ssh -T -n <台账服务器> "<paper 命令路径> --json followup <子命令>"`，
或在本地用 `examples/paper_remote.py --host <SSH 别名> --json followup <子命令>`。

- `followup list [--active true|false] [--stage STAGE] [--attention] [--follow-mode ai|self|student|watch|partner|none]`
- `followup show CODE [--history]`
- `followup set CODE --from-json FILE|- [--expected-version N]`
- `followup event CODE --from-json FILE|- [--expected-version N]`
- `followup events CODE [--include-deleted]`
- `followup event-edit CODE EVENT_ID --expected-version N --from-json FILE|-`
- `followup event-remove CODE EVENT_ID --expected-version N`
- `followup archive CODE --expected-version N --reason TEXT [--evidence TEXT]`
- `followup reopen CODE --expected-version N [--stage 流程型阶段]`
- `followup export [--out NEWFILE]`
- `followup import --from-json FILE|-`
- `followup schema`

## HTTP

API 根路径 `/api/v1`。CLI 沿用写／读 token；网页登录用户可使用同源会话，
按论文归属限定权限，网站写入同时校验 Origin。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/followups/schema` | 字段默认值、阶段与事件类型 |
| GET | `/followups?active=true&needs_attention=true&follow_mode=ai` | 汇总及派生提醒；`follow_mode=none` 筛未登记 |
| GET | `/followups/export` | 安全快照，含稿件和旧台账事件 |
| POST | `/followups/import` | 整批原子导入，所有版本先核验 |
| GET | `/papers/{code}/followup?history=true` | 单篇状态、跟进事件及状态历史 |
| PUT/PATCH | `/papers/{code}/followup` | 增建或修改字段 |
| DELETE | `/papers/{code}/followup` | 归档，保留记录 |
| GET/POST | `/papers/{code}/followup/events` | 查询／追加证据事件 |
| PATCH/DELETE | `/papers/{code}/followup/events/{eid}` | 修订文字／软移除，保留每版 |
| GET | `/papers/{code}/followup/events/{eid}/history` | 原始事件和修改历史 |

网站 `/followups` 显示活动表，`/followups?archived=true` 显示归档。
每篇详情 `/paper/{id}` 同时显示跟进计划、跟进事件和原有期刊进展。

## 状态及时间

阶段：`unverified` 未核验、`draft` 待投稿、`waiting_support` 等待客服、
`awaiting_author` 等待作者、`submitted` 已提交／等待审稿、`under_review` 外审中、
`revision_required` 待返修、`resubmit_ready` 待转投、`awaiting_close` 等待关闭确认、
`paused` 暂缓、`accepted` 已录用、`closed` 已结束。

### 台账推导

审稿阶段只有一套，在台账（`paper progress` / `review-add`）。输出的 `stage`、`due_at`、`active` 是推导值，
另给 `stage_source`、`due_source`（`ledger` / `followup`）、`follow_mode`、`follow_mode_label`、`review_stage`，
以及存储原值 `stored_stage`、`stored_due_at`、`stored_active`。规则详见 README「跟进方式、当前情况与跟进计划」。

- 写 `stage` 只能是流程型：`unverified`（跟随台账）、`waiting_support`、`awaiting_author`、`awaiting_close`、`paused`；
  后四个在论文投稿中时覆盖台账阶段。写可推导阶段返回 422。
- 论文已有返修截止时，写不同的非空 `due_at` 返回 422。
- 论文 `follow_mode` 已登记时，`active` 由它决定；写冲突值（含 DELETE 归档）返回 422。
- `import` 不做上述校验，原样保存。

计划字段：`target_journal`（跟进目标，草稿阶段不新增虚假的正式投稿轮次）、
`blocked_reason`、`waiting_for`、`next_action`、`action_owner`、
`completion_condition`、`completion_evidence`、`decision_required`、`decision_request`、
`last_progress_at`、`last_checked_at`、`waiting_since`、`next_check_at`、`due_at`、
`evidence_source`、`evidence_at`、`stale_after_days`、`priority`、`active`、`archive_reason`、
`policy_reference`。`followup schema` 返回完整默认值。

时间为 ISO 8601 带时区，接受 YYYY-MM-DD 并按服务配置的时区（`PAPER_DESK_TZ`，默认 Asia/Shanghai）标准化。
`stale_after_days=0` 关闭无进展提醒；正常审稿可设 30，客服等待可设 2—3。
等待阶段以 `waiting_since` 判断阻塞时长；检查或催信不重置等待起点。

事件类型 `check/outgoing/incoming/progress/decision/note`。
只有 `check` 推进最后核查时间，只有 `progress` 推进最后实质进展时间。
自动回执或已发送邮件不能自动代表事情已解决。归档须写明证据或归档原因；
已录用由台账推导，accepted/closed 不计停滞、不需处理，完整历史保留。

## 防覆盖与幂等

所有修改都需 `expected_version`（新记录为 0）。版本落后返回 HTTP 409，
不覆盖远端记录。整批导入先检查所有版本，任一冲突或验证失败时整批撤销。
本地副本必须保留自己的待写文件并重新拉取／合并，不能静默跳过冲突。

事件需唯一 `idempotency_key`。同键同内容重复发送不新增事件；同键不同内容
返回 409。事件修订仅改 `text/evidence_ref`；日期、性质变化应新增证据。
状态每版、事件每版和删除标记均有历史。

### 单篇修改

```json
{"expected_version":0,"stage":"waiting_support","waiting_for":"期刊客服",
 "next_action":"按原工单恢复草稿访问","waiting_since":"2026-10-10",
 "completion_condition":"原草稿可访问，明确退回原因","stale_after_days":3}
```

### 追加事件

```json
{"expected_version":1,"kind":"outgoing","occurred_at":"2026-10-13T10:00:00+08:00",
 "text":"已发送客服跟进信；仍待答复","evidence_ref":"邮件 Message-ID（实际核验后填写）",
 "idempotency_key":"P10-support-20261013-message-id"}
```

### 批量同步

```json
{"schema_version":1,"papers":[{"code":"P10","expected_version":2,
 "followup":{"last_checked_at":"2026-10-13T11:00:00+08:00"},"events":[]}]}
```

导出结构为 `{schema_version,source,timezone,server_time,papers:[…]}`。
每个 paper 对象为**平铺**计划字段+`version/code/title/title_cn/current_journal/paper_status`，
`current_journal` 优先显示跟进的目标期刊，`ledger_journal` 保留旧投稿轮次的实际期刊。
`events` 为新跟进历史，`state_history` 为状态修订，`ledger` 是原台账安全字段，
`ledger.events` 是旧期刊时间线。不导出投稿账号、密码、Cookie 或加密凭证。

## 验证与回滚

`tests/test_followup.py`、`tests/test_follow_mode_stage_note.py` 覆盖并发版本竞争、批量冲突回滚、事件幂等、
归档恢复、原始历史保留、凭证脱敏、会话归属权限、跨站写入拒绝及真实 CLI 导入导出。

迁移只增建跟进表（`followup.migrate()`），不改写旧台账。回滚到不含跟进功能的旧程序时，新增表可以保留，旧程序会忽略它们；
升级前先跑 `backup.sh` 打快照。
