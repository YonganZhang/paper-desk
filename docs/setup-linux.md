# 在 Linux 服务器上部署

目标：一台没有显示器的 Linux 服务器上，台账常驻运行；AI 代理在虚拟屏幕里开 Chromium，按网页元素操作期刊投稿系统；每周自动出一封查稿报告。以下以 Ubuntu 为例，普通用户权限即可。

## 1. 台账

见 `ledger/README.md`：安装依赖、初始化管理员、`systemctl --user` 常驻、`paper` 命令行与 token。

## 2. 虚拟屏幕与浏览器

```bash
sudo apt-get install -y xvfb                     # 虚拟屏幕
npm install -g @playwright/cli                   # playwright-cli：按网页元素点击、填表、读页面
playwright-cli install-browser                   # 下载 Chromium（或用系统已有的 Chromium）
```

- 浏览器由 `skills/paper-submit/scripts/paper_browser.sh` 统一打开：没有虚拟屏幕时自动起一个 Xvfb（默认 `:97`，可用 `PAPER_SUBMIT_DISPLAY` 改），每个投稿人一个独立的浏览器资料目录，登录状态长期保留，下次不用重新登录。
- 资料目录默认在 `~/.local/share/paper-submit/profiles/<投稿人ID>/`（`PAPER_SUBMIT_HOME` 可改）。别的代理会话正在用某个投稿人的浏览器时，不要同时再开同一个。
- 需要代理才能访问期刊网站时，设置 `HTTPS_PROXY`，脚本会把它写进浏览器配置。
- 想看 AI 在虚拟屏幕里做了什么：可以在这个显示号上开 VNC（如 `x11vnc -display :97 -localhost`），或者让脚本截图；登录、验证码、二次验证需要人接手时也用这种方式。

## 3. 密码只给名字，不给真值

投稿系统的统一密码由浏览器配置里的 secret 替换：AI 在命令里只写 `fill <ref> PAPER_SUBMIT_DEFAULT_PASSWORD`，页面输出也会把真值打码。真值来自以下两种方式之一（在启动 AI 的环境里设置）：

```bash
export PAPER_SUBMIT_DEFAULT_PASSWORD='…'            # 直接给值（简单，但会留在环境里）
export PAPER_SUBMIT_PASSWORD_CMD='pass show paper/submit'   # 或给一条输出密码的命令（推荐：pass、gopass、1Password CLI 等）
```

各系统的账号（系统、网址、投稿人、用户名、邮箱、浏览器资料名、对应台账编号）登记在 `~/.local/share/paper-submit/accounts.json`，格式见 `skills/paper-submit/assets/` 下的示例。

## 4. 邮箱

查稿和每周报告要读期刊来信。按 `skills/paper-status-check/assets/` 下的示例写邮箱配置：每个邮箱的地址、IMAP/SMTP 主机、凭证从哪个环境变量或命令取。建议用应用专用密码（app password）；Outlook 等只支持 OAuth2 的邮箱，可以配置一条输出访问令牌的命令。

## 5. 每周报告

`skills/paper-status-check/scripts/systemd/` 里有 service 和 timer 模板。service 模板含占位符 `@SKILL_DIR@`（本技能目录的绝对路径）和 `@PATH@`（能找到 `playwright-cli`、`paper`、`Xvfb` 的 PATH），不能直接拷贝，要替换后再装（在仓库根目录执行；说明以 `skills/paper-status-check/references/weekly-report.md`「定时」一节为准）：

```bash
SKILL_DIR=$(realpath skills/paper-status-check)
mkdir -p ~/.config/systemd/user
for u in paper-weekly-report.service paper-weekly-report.timer; do
  sed -e "s|@SKILL_DIR@|$SKILL_DIR|g" -e "s|@PATH@|$PATH|g" "$SKILL_DIR/scripts/systemd/$u" > ~/.config/systemd/user/$u
done
systemctl --user daemon-reload && systemctl --user enable --now paper-weekly-report.timer
loginctl enable-linger "$USER"     # 退出登录后用户定时器仍然运行
```

先手动跑一次不发信的试运行（`weekly_report.py` 不加 `--send`），确认分组和来信识别正常，再打开定时器。

## 6. 让 AI 用起来

```bash
bash install.sh            # 把三个技能装进 ~/.claude/skills 和 ~/.agents/skills
cp templates/AGENTS.md <你的论文项目>/AGENTS.md   # 项目级规则，按自己的规定改
```

模型分工（主模型判断、便宜模型执行）见 `skills/paper-submit/references/agents-and-models.md`。
