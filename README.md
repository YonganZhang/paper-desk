# PaperDesk：课题组投稿台账 + AI 投稿与查稿技能

PaperDesk 帮一个课题组把"论文投到哪、审到哪、谁在跟"管清楚，并让 AI 代理在 Linux 服务器上用浏览器帮忙投稿、查稿、出每周报告。

- **投稿台账（`ledger/`）**：自托管小网站 + `paper` 命令行（FastAPI + SQLite）。论文、每一轮投稿（转投只加新的一轮，历史不丢）、旧轮结局、审稿意见与返修截止、逐篇跟进计划、附件。学生各自登记，导师一处看全。
- **AI 技能（`skills/`）**：可直接装进 Claude Code / Codex 等支持技能（Skills）的代理。
  - `paper-ledger`：怎么改台账——唯一真源、转投与补录、跟进方式、改数据的铁律。
  - `paper-submit`：在虚拟屏幕里的 Chromium 中按网页元素填表投稿（Editorial Manager、Elsevier 新系统、Springer Nature、国内 JournalX／方正等），终点动作前停下交人批准。
  - `paper-status-check`：按跟进方式分流，登录投稿系统读列表页、扫期刊来信，每周自动发一封报告；顺带查台账漏登。
- **项目规则模板（`templates/AGENTS.md`）**：放进你的论文项目，让 AI 按同一套规矩做事。

```
人（导师 / 学生） ──网页──┐                    ┌── paper-submit：虚拟屏幕里的浏览器填表投稿
                          ▼                    │
                 投稿台账 ledger（唯一真源） ◀──┼── paper-status-check：读列表页 + 扫邮箱 + 周报
                          ▲                    │
AI 代理（主模型 + 便宜模型）──paper CLI──┘     └── paper-ledger：改台账的规矩
```

## 核心原则

1. **论文信息只记在台账。** 计划表、版本表、README 只放指针，不抄副本——手抄的副本很快就和实际对不上。
2. **转投是"第几次投稿"，不是状态。** 转投新增一轮；绝不改旧轮的期刊名。更早的轮次可以补录，旧轮记真实结局（被拒／撤回／编辑建议转投／编辑移除／未关闭），"未关闭"会被单独列出，防一稿多投。
3. **终点动作留给人。** 投稿系统里不可撤回的那一步只在人对这一篇明确批准后执行一次；查稿全程只读。
4. **密码只给名字，不给真值。** AI 在命令里只写 secret 名，真值由浏览器配置替换，不进命令行、日志和回复。
5. **便宜模型干活，主模型把关。** 按既定步骤的浏览器操作和例行查稿可以交给便宜模型（如 Claude Haiku 子代理、Codex/GPT 的小模型）；判断、审阅、终点动作前的核对由主模型或人负责，子代理的自述要用页面内容核对后再转告。详见 [skills/paper-submit/references/agents-and-models.md](skills/paper-submit/references/agents-and-models.md)。

## 快速开始

```bash
git clone <本仓库> paper-desk && cd paper-desk

# 1. 台账：安装依赖、初始化管理员、启动（详见 ledger/README.md）
cd ledger && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 seed.py --api-tokens
bash run.sh        # 前台运行，打开 http://127.0.0.1:8611；常驻运行见 ledger/README.md 的 systemd 示例

# 另开一个终端，回到仓库根目录继续：
mkdir -p ~/.local/bin && ln -s "$PWD/ledger/bin/paper" ~/.local/bin/paper   # 把 paper 命令放进 PATH（~/.local/bin 需在 PATH 里）

# 2. 技能：装进 Claude Code（~/.claude/skills）和 Codex（~/.agents/skills）
bash install.sh

# 3. 服务器环境：虚拟屏幕、playwright-cli、浏览器资料、密码与邮箱配置、每周报告定时器
#    见 docs/setup-linux.md

# 4. 项目规则：复制到你管理已投稿论文的项目
cp templates/AGENTS.md <你的论文项目>/AGENTS.md
```

## 目录

| 路径 | 内容 |
|---|---|
| `ledger/` | 台账网站与 `paper` 命令行、测试、示例 |
| `docs/api/` | REST API 与 CLI 合同（API.md、CLI.md、openapi.json、SAMPLES.md） |
| `docs/architecture.md` | 数据模型与设计取舍 |
| `docs/setup-linux.md` | 无显示器 Linux 服务器上的部署步骤 |
| `skills/` | 三个 AI 技能（SKILL.md + references + scripts + assets） |
| `templates/AGENTS.md` | 项目级规则模板 |
| `install.sh` | 安装技能 |

## 安全提示

- 台账数据库里存有各轮投稿的系统账号和密码（明文；管理员专用账号区是加密的）。只在可信服务器上部署，数据目录不进 Git、不外发，并定期备份。
- 新装默认要邀请码才能注册；公网部署请保留邀请码、改掉管理员初始口令，并放在 HTTPS 反向代理后面。
- AI 操作投稿系统前，请确认你和合作者的期刊政策允许这样做；作者声明、版权协议、付费等事项由作者本人决定。

## 状态

在一个课题组的真实投稿流程中使用：台账测试 52 项、查稿技能邮箱模块测试 7 项。浏览器自动化依赖各期刊系统的页面结构，系统改版后需要按 `skills/paper-submit/references/systems/` 的模板更新对应说明。欢迎提 issue 和 PR。

---

## English summary

PaperDesk is a self-hosted submission ledger for research groups plus a set of agent skills. The ledger (FastAPI + SQLite, with a `paper` CLI) is the single source of truth for every paper's submission rounds, old-round outcomes, review events, deadlines and follow-up plans. The skills let AI agents (Claude Code, Codex, or any agent that loads Skills) submit manuscripts through journal systems using a real Chromium driven by `playwright-cli` on a headless Linux server (Xvfb), check review status read-only, and send a weekly email report. Irreversible submission steps always stop for explicit human approval; passwords are referenced by secret name only. Cheap models can do the routine browser work while a stronger model or a human reviews results. MIT licensed.
