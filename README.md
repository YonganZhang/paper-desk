# PaperDesk：让 AI 帮课题组投稿、查稿、跟进的论文工作台

**PaperDesk = 一个投稿台账 + 一组 AI 技能。** 台账记清"每篇论文投到哪、审到哪、谁在跟"；技能让 AI 代理在 Linux 服务器上自己开一块虚拟屏幕，用浏览器登录期刊投稿系统填表投稿、定期查审稿状态、读期刊来信、每周提醒相关的人跟进。适合导师管理一组学生的论文，也适合个人管理自己的投稿。

> 实际效果：材料齐全时，AI 在 Elsevier 的投稿系统里从登录到停在"最终提交"前，通常一小时左右；日常点击和查状态可以交给便宜的模型，人只在最终提交、签字、验证码这些节点确认。

## 能做什么

| 环节 | 技能 | AI 做的事 |
|---|---|---|
| 投稿前 | `paper-submission-kit` | 投稿信、Highlights、作者页、基金 / 利益冲突 / CRediT / 数据声明，按期刊要求出一套材料 |
| 投稿 | `paper-submit` | 在虚拟屏幕里的浏览器中注册或登录投稿系统、录作者、上传文件、回读系统生成的 PDF 核对，**停在最终提交前**交人批准；投完登记台账 |
| 记录 | `paper-ledger` + `ledger/` | 用 `paper` 命令行增删改查：作者与位次、每一轮投稿的期刊 / 日期 / 稿号 / 结局、审稿意见与返修截止、跟进计划、投稿账号密码、附件 |
| 跟进 | `paper-status-check` | 登录投稿系统读状态、扫期刊来信、每周发一封汇总邮件；**每周自动催负责人跟进**（返修快到期、等合著者确认、太久没进展、旧投稿流程没关），先预览、确认后发，7 天内不重复；顺带找出邮箱里有、台账里漏登的投稿 |
| 邮箱 | `paper-mailbox` | 登记每个邮箱给谁用、哪篇论文的哪位作者；收信、搜信、取验证码和确认链接、发信（须确认）；检查"一个投稿系统里一个邮箱只对应一个人" |
| 返修 | `paper-revision` | 拆审稿意见、改稿标红稿和干净稿、逐条回复信，可选多个模型独立模拟审稿；提交返修后更新台账 |

支持的投稿系统：Editorial Manager（Elsevier 老刊、KeAi、部分 Springer 刊）、Elsevier 新投稿系统、国内中文刊常用的 JournalX（玛格泰克）和方正系统；Springer Nature 自有系统目前只实测了查状态。其他系统可以照 `skills/paper-submit/references/systems/_template.md` 补一份说明。

## 怎么运作

```
导师 / 学生 ──网页──▶ ┌──────────────── 投稿台账 ledger（唯一真源） ────────────────┐
                     │ 论文 · 每轮投稿 · 旧轮结局 · 审稿意见/截止 · 跟进计划 · 附件 │
AI 代理 ──paper CLI─▶ └───────────────────────────────────────────────────────────┘
   │                        ▲ 登记               ▲ 状态 / 来信           ▲ 返修
   ├─ paper-submit ─────────┘                    │                       │
   │   Xvfb 虚拟屏幕 + Chromium + playwright-cli  │                       │
   ├─ paper-status-check ── 读投稿系统列表页 + 扫邮箱 ─┘── 每周报告 / 提醒学生
   ├─ paper-mailbox ────── IMAP 收信 / SMTP 发信 / 邮箱登记
   └─ paper-submission-kit · paper-revision ──────────────────────────────┘
```

## 设计原则

1. **论文信息只记在台账。** 计划表、版本表、README 只放指针，不抄副本。
2. **转投是"第几次投稿"，不是状态。** 转投新增一轮，不改旧轮；更早的投稿可以补录，旧轮记真实结局（被拒 / 撤回 / 编辑建议转投 / 未关闭），"未关闭"会被单独列出，防一稿多投。
3. **最终提交留给人。** 投稿系统里不可撤回的一步只在人对这一篇明确批准后执行一次；查稿只读，不替你回复编辑，提醒只发给组内的人。
4. **密码只给名字，不给真值。** AI 命令里只写 secret 名或取密码命令，真值不进命令行、日志和回复。
5. **便宜模型干活，强模型把关。** 详见下节。

## 推荐模型（不绑定，按你能用的选）

| 角色 | 推荐 | 也可以 |
|---|---|---|
| 主模型：判断、核对、终点前把关 | Claude Opus 5.5 / Claude Sonnet 5.5 | 其他强推理模型（如 OpenAI GPT 旗舰型号） |
| 执行模型：点网页、例行查稿、读邮件 | Claude Haiku 5.5 | OpenAI Codex 上的轻量型号（如 GPT-6 Luna）等便宜模型 |

在 Claude Code 里：主会话用 Opus 或 Sonnet，派子代理时指定 Haiku；Codex 同理。分工细则见 [skills/paper-submit/references/agents-and-models.md](skills/paper-submit/references/agents-and-models.md)。

## 快速开始

```bash
git clone https://github.com/YonganZhang/paper-desk.git && cd paper-desk

# 1. 台账（详见 ledger/README.md）
cd ledger && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 seed.py --api-tokens
bash run.sh        # 前台运行，打开 http://127.0.0.1:8611；常驻运行见 ledger/README.md 的 systemd 示例

# 另开一个终端，回到仓库根目录：
mkdir -p ~/.local/bin && ln -s "$PWD/ledger/bin/paper" ~/.local/bin/paper   # 把 paper 放进 PATH

# 2. 技能：装进 Claude Code（~/.claude/skills）和 Codex（~/.agents/skills）
bash install.sh

# 3. 服务器环境：虚拟屏幕、playwright-cli、浏览器资料、密码、邮箱、每周报告与提醒
#    见 docs/setup-linux.md

# 4. 项目规则：放进你管理论文的项目
cp templates/AGENTS.md <你的论文项目>/AGENTS.md
```

装好后可以直接对 AI 说："把这篇论文投到 XX 期刊""查一下我所有在审论文的状态""把 P03 的决定信录进台账""给学生发这周的跟进提醒（先给我看预览）"。

## 目录

| 路径 | 内容 |
|---|---|
| `ledger/` | 台账网站与 `paper` 命令行、测试、示例 |
| `skills/` | 六个 AI 技能（SKILL.md + references + scripts + assets） |
| `docs/setup-linux.md` | 无显示器 Linux 服务器上的部署步骤 |
| `docs/architecture.md` | 数据模型与设计取舍 |
| `docs/api/` | REST API 与 CLI 合同 |
| `templates/AGENTS.md` | 项目级规则模板 |
| `install.sh` | 安装技能 |

## 安全与边界

- 仓库本身不含任何真实论文、邮箱、账号或密码，示例全是虚构的；部署后这些数据都只在你自己的服务器上。
- 台账库里存有投稿系统账号和密码（各轮投稿的是明文，管理员专用账号区加密）。只部署在可信服务器上，数据目录不进 Git、不外发，并定期备份。
- 新装默认要邀请码才能注册；公网部署请保留邀请码、改掉管理员初始口令，并放在 HTTPS 反向代理后面。
- 邮箱凭证用应用专用密码或取密码命令；发信默认只预览，确认后才发。
- AI 使用声明、版权协议、作者贡献、付费等以作者名义的事项由作者本人决定；使用前请确认相关期刊对代理操作投稿系统的政策。

## 状态与贡献

已在一个课题组的真实投稿流程中使用；台账 52 项测试，邮箱、查稿与提醒、材料包、返修技能另有单元测试（不联网，用假的邮箱和台账）。浏览器自动化依赖各期刊系统的页面结构，系统改版后需要更新对应的说明。欢迎提 issue 和 PR，尤其是新的投稿系统说明。MIT 许可。

---

## English

PaperDesk is a self-hosted paper-submission ledger plus six agent skills. The ledger (FastAPI + SQLite, with a `paper` CLI) is the single source of truth for every paper: submission rounds, outcomes of earlier rounds, review comments and deadlines, follow-up plans, accounts and attachments. The skills let AI agents (Claude Code, Codex, or any agent that loads Skills) prepare submission materials, submit through journal systems with a real Chromium driven by `playwright-cli` on a headless Linux server (Xvfb), check review status read-only, read journal email, send weekly reports and reminder emails to the students responsible, and assemble revision packages. Irreversible steps always stop for explicit human approval; passwords are referenced by secret name only. Recommended split: a strong model (e.g. Claude Opus/Sonnet 5.5) for judgement and checks, a cheap model (e.g. Claude Haiku 5.5 or a lightweight Codex model) for routine browser work. MIT licensed.
