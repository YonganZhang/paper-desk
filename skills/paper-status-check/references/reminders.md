# 催人跟进（自动提醒跟进人）

`scripts/reminders.py` 按台账给组内跟进人发汇总提醒；`scripts/weekly_report.py --remind` 在周报之后调用同一套逻辑。

## 边界

- **只提醒组内的人。** 收件人只来自配置 `people`；没登记邮箱的不提醒、不猜邮箱，列进「无法提醒」。合著者等外部人员（`role: external`）只有在 `reminders.include_external: true` 时才提醒。
- **绝不给期刊或编辑部发信。** 在审太久只提醒负责人「可以考虑问编辑部」，问不问、怎么写由人决定。
- **默认只预览。** 不加 `--send` 只打印每封信的预览；`weekly_report.py --remind --send --test` 时提醒也只预览，不发给跟进人。
- 发信走技能 `paper-mailbox` 的 `send()`，发件邮箱取 `reminders.from`，空时用 `report.from`。

## 数据

- `paper --json list`：`status`、`follow_mode`、`lead_author`（负责人）、`revision_due_date`、`revision_days_remaining`、`days_without_progress`、`last_progress_date`、`current_submission`、`submissions[].outcome` / `is_current`。
- `paper --json followup list`：`stage`（台账推导或流程卡点）、`stage_label`、`waiting_for`、`waiting_since`、`next_action`、`action_owner`、`version`。
- 只看总体状态为「投稿中」的论文。跟进方式只认 `follow_mode`；没登记时与体检同口径推：负责人是 `self_names` 里的人 → `ai`（跟进计划 `action_owner` 写了「本人自查」→ `self`），其余 → `student`。

## 规则

| 类型 | 条件（默认值可在 `reminders` 段改） | 提醒谁 | 去重用的「截止日」 |
|---|---|---|---|
| 返修截止 | `revision_days_remaining` ≤ `due_days`（14，含已逾期） | 负责人 | 返修截止日 |
| 跟进卡点 | 跟进阶段在 `blocked_stages`（等待作者、等待客服、等待关闭确认），或 `waiting_for` 命中 `waiting_pattern` / 写了 `people` 里的姓名；正文带上 `waiting_for` 和 `next_action` | 负责人 | `waiting_since` 的日期 |
| 久无进展 | 跟进阶段为 submitted / under_review，且 `days_without_progress` ≥ `stalled_days`（60） | 负责人（只建议考虑问编辑部） | 最近进展日，没有就当前轮投稿日 |
| 旧轮未关闭 | 旧轮 `outcome` 为「未关闭」（防一稿多投）；`partner` 论文不提醒 | 负责人和本人（`reminders.owner`，默认 `self_names` 第一个） | `seq<轮次>` |

- 「提醒负责人」只对 `reminders.modes` 里的跟进方式生效（默认 `student`、`watch`、`ai`；`self`、`partner` 不提醒）。旧轮未关闭时，除合作方论文外都提醒本人。
- 每人一封汇总信，同一地址的多项合在一起；`people` 里 `cc_owner: true` 的人，信抄送本人。
- 去重：状态文件（默认 `$PAPER_STATUS_WORK/reminders-state.json`，配置 `reminders.state_file`）按「编号|类型|截止日」记上次发送日，`min_interval_days`（7）天内不重复。截止日变了（例如返修截止改期、换了等待对象并更新 `waiting_since`）算新的一件事。同一件事要发给两个人时，两封都发成功才记为已发。
- 发出后，每篇论文、每位收件人给台账记一条跟进事件：`paper --json followup event <编号> --from-json - --expected-version <版本>`，`kind: outgoing`，`text` 为「已提醒 某人：返修截止 2026-11-01；…」，带 `idempotency_key`（`remind:<日期>:<编号>:<摘要>`，同一天重跑不会重复记）。失败（例如版本冲突）只告警，不影响其他提醒。

## 运行

```bash
python3 -I scripts/reminders.py                 # 只预览：每封信的收件人、主题、正文；被去重跳过的、无法提醒的
python3 -I scripts/reminders.py --json          # 只输出提醒计划 JSON
python3 -I scripts/reminders.py --send          # 真的发，记去重状态和台账事件
python3 -I scripts/weekly_report.py --remind    # 周报 + 提醒预览；无法提醒的人写进周报第五节
```

退出码：0 成功（含没有要发的）；1 有提醒没发出或缺配置（发件邮箱、邮箱登记）。

## 配置示例（虚构）

```json
{
  "self_names": ["张三"],
  "people": {
    "张三": {"email": "alice@example.com", "role": "owner"},
    "李四": {"email": "lisi@example.com", "role": "student", "cc_owner": true},
    "王五": {"email": "wangwu@example.org", "role": "external"}
  },
  "reminders": {"modes": ["student", "watch", "ai"], "due_days": 14, "stalled_days": 60, "min_interval_days": 7,
                "include_external": false, "subject": "论文跟进提醒（{date}）：{count} 项"}
}
```

字段完整说明见 [config.md](config.md)。

## 示例邮件（虚构）

```
From: alice@example.com
To: lisi@example.com
Cc: alice@example.com
Subject: 论文跟进提醒（2026-10-22）：2 项
------------------------------
李四您好：

以下 2 项需要您跟进：
1. [返修截止] P01《Example Title》：返修截止 2026-11-01，还剩 10 天。请确认修改进度和回复信。
2. [跟进卡点] P04《Another Title》：跟进计划停在「等待作者」。
   等待：等王五确认作者身份
   下一步：提醒王五点确认链接

——
本邮件由投稿服务器自动发送，只提醒组内跟进人，不会替您联系期刊或编辑部。
```
