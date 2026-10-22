# 安装与配置

本技能假设一台能长时间开着浏览器的 Linux 服务器（无显示器也行），AI 通过 shell 调 `playwright-cli` 操作浏览器。

## 依赖

| 依赖 | 用途 | 安装示例（Debian/Ubuntu） |
|---|---|---|
| `playwright-cli` 与 Chromium | 浏览器操作 | 按官方说明安装：<https://github.com/microsoft/playwright-cli> |
| Xvfb | 虚拟屏幕，让有界面的 Chromium 在无显示器的服务器上跑 | `apt install xvfb` |
| Python 3 + Pillow | `jx_captcha.sh`、`docx_light.py`、`page_fill.py` | `pip install pillow`（或系统包 `python3-pil`） |
| poppler-utils | `page_fill.py` 用 `pdftoppm` 渲染页面 | `apt install poppler-utils` |
| LibreOffice（可选） | Word 稿转 PDF 预览、审阅包 | `apt install libreoffice-writer` |
| systemd 用户实例（可选） | 浏览器和 Xvfb 放进限内存的 scope，比调用它的命令活得久 | 多数发行版自带；没有时脚本直接启动 |

## 环境变量

`paper_browser.sh` 只读环境变量，不读别的私有脚本。建议写进一个只有自己能读的文件（例如 `~/.config/paper-submit/env`，权限 0600），在 shell 配置里 `set -a; . ~/.config/paper-submit/env; set +a`。可以从示例 `assets/paper-submit.env.example` 复制后修改。

| 变量 | 默认值 | 作用 |
|---|---|---|
| `PAPER_SUBMIT_DEFAULT_PASSWORD` | 无 | 投稿账号统一密码的真值。和下一项二选一 |
| `PAPER_SUBMIT_PASSWORD_CMD` | 无 | 一条命令，stdout 输出密码，例如 `pass show paper-submit/default`、`secret-tool lookup service paper-submit`。优先级低于上一项 |
| `PAPER_SUBMIT_EXTRA_SECRETS` | 空 | 逗号分隔的额外 secret 名（别人的账号），例如 `ADVISOR_MTS_PASSWORD` |
| `PAPER_SUBMIT_SECRET_CMD` | 无 | 取额外 secret 的命令，脚本执行 `<命令> <KEY>`，stdout 为值；没有它时读同名环境变量 |
| `PAPER_SUBMIT_HOME` | `~/.local/share/paper-submit` | 状态目录：`profiles/<投稿人ID>/`（登录状态）、`accounts.json`（账号登记）、Xvfb pid |
| `PAPER_SUBMIT_CONFIG_DIR` | `~/.config/paper-submit` | 生成的 `cli.config.json` 放这里（含 secret 真值，权限 0600，每次 open 重写） |
| `PAPER_SUBMIT_DISPLAY` | `:97` | Xvfb 显示号。多人共用的服务器上换一个没人用的 |
| `PAPER_SUBMIT_SCREEN` | `1440x960x24` | 虚拟屏幕尺寸 |
| `PAPER_SUBMIT_PROXY` | 取 `HTTPS_PROXY` / `https_proxy` | 浏览器代理。Chromium 不会自己读环境变量里的代理，脚本写进配置 |
| `PAPER_SUBMIT_PLAYWRIGHT` | `playwright-cli` | CLI 可执行文件名或路径；`paper_browser.sh` 和 `em_*`／`els_*`／`jx_*` 脚本都用它 |
| `PAPER_SUBMIT_SYSTEMD` | `auto` | `yes`／`no`／`auto`：是否用 `systemd-run --user --scope` 启动并限内存 |

密码只在三个地方出现：你的凭证库、环境变量（或取密码命令的输出）、`cli.config.json`。命令行、日志和 AI 的回复里只出现 secret 名。

## 验证

```bash
scripts/paper_browser.sh check                      # 依赖、密码来源、systemd 是否就绪，不打印真值
scripts/paper_browser.sh open test-user https://example.com
export DISPLAY=:97                                  # 与 PAPER_SUBMIT_DISPLAY 一致
playwright-cli -s=submit-test-user snapshot | head
scripts/paper_browser.sh stop test-user
```

## 账号登记

`$PAPER_SUBMIT_HOME/accounts.json` 是一个 JSON 数组，每个投稿系统账号一条，示例见 `assets/accounts.example.json`。字段：

| 字段 | 含义 |
|---|---|
| `system` | 系统名，如 `Editorial Manager`、`Elsevier new submission`、`Springer Nature`、`JournalX` |
| `login_url` | 登录或刊首页网址。EM 写到刊缩写为止，如 `https://www.editorialmanager.com/abcd/` |
| `person` | 账号属于谁（档案姓名） |
| `username`、`email` | 用户名与绑定邮箱 |
| `password_key` | 密码的 secret 名，一般是 `PAPER_SUBMIT_DEFAULT_PASSWORD` |
| `login` | `password`（用户名加密码）或 `elsevier-sso`（点 Elsevier account login，用 profile 里保存的登录态） |
| `browser_profile` | `paper_browser.sh open` 用的投稿人 ID |
| `paper` | 空格分隔的台账编号，表示这些稿件挂在这个账号下 |
| `registered`、`email_verified` | 注册日、邮箱是否已验证 |

查稿技能 `paper-status-check` 读同一份登记，所以两边共用 `PAPER_SUBMIT_HOME`。
