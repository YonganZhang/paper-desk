---
name: paper-ledger
description: "维护课题组投稿台账（PaperDesk ledger）：登记投稿、转投、补录旧轮、记结局、改阶段与跟进方式。触发：登记投稿、台账、转投了、登记转投、改状态、补录、update the submission ledger。不触发：网上填表投稿（paper-submit）、查审稿状态（paper-status-check）。"
---

# 投稿台账维护

台账是论文信息的**唯一真源**：状态、各轮期刊与稿号、作者、跟进人与跟进方式、审稿阶段、返修截止、决定信、跟进计划，只记在台账里。项目里的计划表、版本登记表、README 只放指针，不抄副本。命令行是 `paper`（`paper --help` 看全部子命令，`--json` 给机器读）。

## 先分清四个概念

| 概念 | 在台账里怎么表达 | 不要这样做 |
|---|---|---|
| 投了几家 | 投稿轮次 `seq`：1=首投，2+=转投 | 不要把"转投"当状态 |
| 现在在哪 | 只看最新一轮（`is_current`）的期刊和状态 | 不要按编号前缀判断在不在投 |
| 旧轮结局 | `outcome`：被拒／撤回／编辑建议转投／编辑移除／未关闭 | 不要改旧轮的期刊名 |
| 谁跟、AI 怎么做 | 负责人（姓名）+ 跟进方式 `follow_mode` | 不要在备注里写"本人自查"之类的暗号 |

跟进方式：`ai`=AI 代查（登录系统、查来信）；`self`=本人自查（AI 跳过）；`student`=学生自管（AI 不登录查稿；开了催人跟进时每周提醒学生）；`watch`=学生改稿，周报里给本人列返修截止；`partner`=合作方自管（AI 不查、不提醒，旧轮未关闭也不报）。

## 常用操作

| 要做的事 | 命令 |
|---|---|
| 新论文 | `paper new --title … --cn 简称 --authors "A; B; C" --corresponding … --lead 负责人 --follow-mode ai` |
| 转投（新增一轮） | `paper submit 编号 --journal … --date YYYY-MM-DD --ms-id … --url …` |
| 补录更早的一轮 | `paper submit 编号 --history --journal … --date … --outcome 被拒` |
| 改某轮（稿号、结果日、结局） | `paper sub-edit 记录号 --ms-id … --result-date … --outcome …` |
| 审稿阶段 | `paper progress 编号 --stage 外审中 --date 系统状态日 --note …` |
| 返修 | 决定信 `review-add --stage 大修 --due 截止日` 录全文；提交返修后 `progress --stage 返修已提交`，系统给的新稿号（如 `…R1`）用 `sub-edit 记录号 --ms-id` 更新本轮，**不新增一轮**（返修不是转投）；改稿流程见 `../paper-revision/` |
| 决定信与返修截止 | `paper review-add 编号 --seq N --text-file 决定信.txt --stage 大修 --due 截止日` |
| 只记一次核查（无变化） | `paper check-in 编号 --note …` |
| 当前情况（一两句，可覆盖） | `paper edit 编号 --current "…"` |
| 合作方论文 / 其他论文 | `paper edit 编号 --category partner`（或 `extra`），不计入主序列统计 |
| 跟进计划（等谁、下一步、何时再查） | `paper followup set 编号 --from-json f.json --expected-version V` |
| 附件 | `paper upload 编号 文件 --kind manuscript --seq N --label …`；删 `paper rm-file 编号 FID --yes` |
| 筛查 | `paper watch --days 30`（含"旧流程未关闭"清单，防一稿多投） |

记录号印在 `paper show` 每轮末尾的 `[记录号 N]`。

## 改数据的铁律

1. 转投用 `paper submit` 新增一轮；**绝不改旧轮的期刊名**，那样投稿历史就丢了。补到更早的投稿用 `--history`，系统按日期插入并顺延轮次。
2. 批量脚本**不许先删后建**；要改就更新具体字段。删除不可恢复，`rm`／`rm-sub`／`rm-file` 必须带 `--yes`，删前自动打库快照（快照不含附件文件本身，删附件前先另存）。
3. 写之前先 `paper show 编号` 看清楚；写完再读一遍确认系统存下的值。
4. 追加备注前从数据库**只读**取原文再拼接：CLI 输出会把凭证类字符串打码，拿输出改完写回会永久丢原文。
5. 备注只写结构化字段装不下的叙述；有字段的事实写字段。当前情况写 `--current`，原备注只往后追加。
6. 跟进计划里的审稿阶段和返修截止由台账推导：改阶段用 `paper progress`，改截止用 `review-add --due`；跟进计划只单独记"等作者确认、等客服、暂缓、等关闭确认"这类卡点。写跟进计划要带 `--expected-version`，冲突（409）就重新读一次。
7. 投稿系统密码、token 不写进仓库、日志或回复；`paper credentials show` 默认隐藏，确需真值时 `--reveal --out` 写本地新文件。

## 补漏

邮箱里的投稿确认信是查漏登的兜底：`../paper-status-check/scripts/untracked_scan.py --days 30`（查稿技能 paper-status-check） 列出确认信里有、台账没有的稿号；整篇漏了 `paper new`，漏一轮 `paper submit`（更早的加 `--history`）。

## 数据模型与接口

完整字段、API 与 CLI 合同见 PaperDesk 仓库根目录的 `docs/api/`（API.md、CLI.md、openapi.json）和 `ledger/README.md`（用 `install.sh --copy` 安装时，这些文件不在技能目录里，请到仓库查看）。
