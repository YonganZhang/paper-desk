# 投稿浏览器通用技巧

## 启动

- `scripts/paper_browser.sh open <投稿人ID> [网址]` 打开浏览器；`env` 查看配置；`check` 查依赖和密码来源；`stop <投稿人ID>` 关闭。之后用 `playwright-cli -s=submit-<投稿人ID> …` 操作（先 `export DISPLAY=<PAPER_SUBMIT_DISPLAY>`）。
- 每位投稿人一个独立的 profile（`$PAPER_SUBMIT_HOME/profiles/<投稿人ID>`），登录状态会保留。浏览器跑在 Xvfb 虚拟屏幕上。
- 开浏览器前先看这个 profile 有没有别的会话在用：`pgrep -af "$PAPER_SUBMIT_HOME/profiles/<投稿人ID>( |$)"`。同一个 profile 被两个会话同时用，会互相把页面跳走。
- 代理：Chromium 不会自动用环境变量里的 `HTTPS_PROXY`，不配就直连；直连外网慢的机器上页面会卡到超时。启动脚本每次都会按当前环境重写配置。

## 让用户接管

读不出或要拖动、点选的验证码，登录、二次验证、需要本人确认的勾选：停下来，回复里写明会话名 `submit-<投稿人ID>` 和要做的事，请用户接管，完成后交还。

- 接管方式由部署决定，常见做法：在服务器上对虚拟屏幕开只监听本机的 VNC（例如 `x11vnc -display :97 -localhost -nopw -once`），用户用 SSH 隧道连上；或者用你们已有的远程浏览器面板。
- 接管期间不对该会话发命令：用户和 AI 同时输入会互相串字。交还后重新 `snapshot`。
- 设了 `DISPLAY` 后不要运行 `playwright-cli show`：它会在虚拟屏幕上真的开一个监听 TCP 端口的 Dashboard。

## 操作

- 按 snapshot 里的 ref 操作。页面一变，ref 就会变，所以每一步重新取。
- 截图只在需要看图时用，例如验证码、PDF 预览、排查页面没反应。
- 文件上传：先点上传按钮，紧接着 `upload <文件>`。点开了上传框却没有文件可传时，后面所有命令都会卡住，只能 `paper_browser.sh stop` 再重开。
- 联想下拉框（单位、基金机构）：用 `press` 一个字一个字地输入，联想列表才会出来，再点选列表项。`fill` 不会触发联想。
- 弹窗：
  - 原生的 alert 和 confirm，要在触发前用 `page.once('dialog', …)` 挂好处理；
  - 页面自己画的弹窗（jQuery、模态框），在 snapshot 里找 `alertdialog`，点它的按钮。
- 新标签页：有的系统把子流程放在新标签页里（出版方式选择、作者中心）。用 `tab-list` 查看，`tab-select` 切换，做完关掉，再切回原来的标签页。
- 页面上写着 `javascript:` 的链接，在 snapshot 里看不到实际调用的函数。从 frame 的 HTML 里取出函数调用，再用 `evaluate` 执行。
- 自动化循环（翻页、批量勾选）：
  - 先写清楚在哪一步停，用网址或页面标题这类明确标识判断，不用模糊的正则；
  - 终点动作所在的那一步不能放进循环。
- 等系统生成 PDF 这类慢任务：放到后台脚本里等，完成会通知，不手动轮询。
- 进程收尾：杀进程要按 PID。用 `pkill -f` 按命令行匹配，可能把当前这条 shell 命令自己也杀掉。

## 浏览器出错

| 现象 | 对策 |
|---|---|
| `ERR_NETWORK_CHANGED`、「A network change was detected」 | 先确认请求有没有已经生效，比如去列表页看状态；没生效再重试。频繁出现就重启浏览器会话 |
| `EMFILE: too many open files`（`playwright-cli list` 报错，inotify 上限低的机器常见） | 不影响已经开着的会话；需要列会话时，改看 profile 目录或 `pgrep` |
| 403、「system error」 | 站点反爬，换浏览器标签页打开，或者以系统页内的提示为准 |
| 某条命令之后，同一会话的所有命令都超时（`tab-list` 也不返回） | 多半是点开了会弹新窗口的链接（如 EM 的「Send E-mail」），会话被挂住。按 PID 杀掉自己卡住的 playwright-cli 客户端进程，`paper_browser.sh stop` 再 `open`，profile 里的登录还在；只为读信息时不要点这类弹窗链接 |
| 上传后系统显示的大小和本地不一样 | 系统按自己的单位或换算显示。用「查看」把文件下载回来，比对 SHA256 |

## 脚本清单

| 脚本 | 用途 | 说明在 |
|---|---|---|
| `paper_browser.sh` | 开关投稿浏览器、生成带 secret 的配置 | 本文件、setup.md |
| `em_*.sh` | Editorial Manager 注册、加作者、排序、换文件、生成并下载待批准 PDF | systems/editorial-manager.md |
| `els_*.sh` | submit.elsevier.com 上传、作者卡片、CRediT 角色 | systems/elsevier-new-submission.md |
| `jx_*.sh`、`docx_light.py` | JournalX 验证码、检索作者、新作者表；轻量版 docx | systems/journalx.md |
| `page_fill.py` | PDF 逐页留白检查 | preflight.md 第 4 节 |
