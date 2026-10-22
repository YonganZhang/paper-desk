# 每周报告

`scripts/weekly_report.py` 读台账、扫近 7 天期刊来信、读投稿系统列表页和作者确认页，生成中文报告，按配置 `report` 段发信。全程只读。

## 范围

- 跟进方式 `ai` 的在投论文：查系统、查来信。
- `self`（本人自查）：列在第四节「不查」。
- `student`、`partner`：只列编号和跟进人，不登录、不查信、不提醒。
- `watch`（学生改稿、AI 盯截止）：同上，但 21 天内到期的返修进「需要您处理」。
- 台账没登记跟进方式时按负责人推（`access_audit.follow_mode`）：负责人是配置 `self_names` 里的人 → `ai`；跟进计划的 `action_owner` 写了「本人自查」→ `self`；其余 → `student`。报告和体检都会提示补登 `paper edit <编号> --follow-mode …`。
- 已录用、撰写中、被拒、撤稿：不查。

## 内容

分五节，每篇都写编号加全名：
1. **需要您处理**，只放五类：
   - 卡流程的合著者未确认（期刊在配置 `blocking_confirm_journals` 里），附给合著者的操作说明；
   - 期刊来信里的非例行信。回执、注册、作者确认、编辑接手算例行；只涉及旧轮稿号或旧轮中文刊名的信不算；
   - 21 天内到期的返修（含 `watch` 论文）；
   - 邮箱混用待清理：邮箱登记里 `exceptions` 标了 `remind: near-acceptance` 的稿件进入小修或已录用；
   - 台账漏登：本周投稿确认信里的稿号台账里没有（`untracked_scan.py`，历史轮记在备注里的稿号也算已登记）。
2. 和上周相比系统状态的变化（对比上一份存档 json）。
3. 近 N 天的期刊来信（同一封信在几个邮箱里各有一份时合并）。
4. 各篇当前状态：系统读到的状态和日期、合著者确认进度；没读到的写台账状态。
5. 没查到的：登录失效、列表里没有本稿、系统没接入自动查询、浏览器 profile 被占用、邮箱读取失败；加 `--remind` 时还列出无法提醒的人（负责人没在 `people` 里登记邮箱、外部人员未开 `include_external`）。

## 行为

- 只读：不点任何稿件按钮，不回信。系统页读到状态时给台账记一条 check-in（`--no-checkin` 关掉）。
- EM 会话过期时按账号登记自动登录：`login: elsevier-sso` 的点 Elsevier account login，用 profile 里保存的登录态；其余用 `username` 加 `password_key`（secret 名）登录，每次运行只试一次密码。
- 别的会话正在用某个投稿人 profile 时，跳过那个 profile，写进第五节，不抢会话。
- 存档在 `report.out_dir/<日期>.md|.json`。

## 手动运行

```bash
python3 -I skills/paper-status-check/scripts/weekly_report.py               # 只打印和存档
python3 -I skills/paper-status-check/scripts/weekly_report.py --send --test # 发一封主题带【测试】的信
```

参数：`--send` 发信；`--test` 主题前加【测试】；`--no-browser` 不读系统页；`--no-checkin` 不记台账；`--days N` 扫多少天的来信；`--remind` 周报之后顺带催人跟进。

## 催人跟进 `--remind`

周报打印（和发出）之后，按 [reminders.md](reminders.md) 的规则给组内跟进人各发一封汇总提醒：返修将到期、跟进计划卡住、在审太久没进展、旧轮未关闭。

- 遵守 `--send`：不加只打印提醒预览；`--send --test` 时周报照发（主题带【测试】），提醒只预览，不发给跟进人。
- 无法提醒的人写进周报第五节；存档 json 的 `reminders` 字段记提醒计划。
- 有提醒没发出时，脚本以非零退出（周报本身已经发出），日志里看得到原因。

## 定时（systemd 用户单元）

模板在 `scripts/systemd/`，`@SKILL_DIR@` 换成本技能目录的绝对路径，`@PATH@` 换成能找到 `playwright-cli`、`paper`、`Xvfb` 的 PATH：

```bash
SKILL_DIR=$(realpath skills/paper-status-check)
mkdir -p ~/.config/systemd/user
for u in paper-weekly-report.service paper-weekly-report.timer; do
  sed -e "s|@SKILL_DIR@|$SKILL_DIR|g" -e "s|@PATH@|$PATH|g" "$SKILL_DIR/scripts/systemd/$u" > ~/.config/systemd/user/$u
done
systemctl --user daemon-reload
systemctl --user enable --now paper-weekly-report.timer
systemctl --user list-timers paper-weekly-report.timer
journalctl --user -u paper-weekly-report -n 50          # 日志
```

- 环境变量（邮箱密码变量、`PAPER_SUBMIT_PASSWORD_CMD`、代理等）写进 `~/.config/paper-desk/status-check.env`（示例 `assets/status-check.env.example`，chmod 600）；systemd 不展开 `$HOME`，里面写绝对路径。
- 用户退出登录后定时器也要跑，需要 `loginctl enable-linger $USER`（可能需要 root 或 sudo 权限）。
- 默认按服务器本地时间每周一 10:00 跑；要固定时区，在 timer 的 `OnCalendar` 后面加时区名。
- 改了模板以后重新执行上面的安装命令。
- 要每周顺带催人跟进：把 service 模板 `ExecStart` 行末的 `--send` 改成 `--send --remind`，再重新安装。先手动跑一次 `weekly_report.py --remind`（不加 `--send`）看预览，确认 `people` 和收件人无误再开。
