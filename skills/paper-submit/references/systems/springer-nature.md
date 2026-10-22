# Springer Nature

实测：投稿流程未实测；只读查状态实测过 Nature 系列 MTS（见下文「只读查状态」一节），Snapp 稿件详情页的只读查状态见查稿技能的 `../../../paper-status-check/references/systems.md`。第一次投 Springer Nature 的期刊时，照 `_template.md` 把投稿部分补全，并更新这一段。

## 入口（待实测确认）

- 期刊官网的「Submit manuscript」按钮会指向下面两类系统之一：
  - **Editorial Manager**：网址形如 `https://www.editorialmanager.com/<缩写>/`，按 [editorial-manager.md](editorial-manager.md) 走。各刊的问卷和文件类型不同，差异补进那份 reference 的「各刊差异」表。
  - **Springer Nature 自己的投稿系统**：网址在 springernature.com 域名下。账号、步骤和终点动作都还没实测，第一次投时按下面清单逐项记录。
  - **Nature 系列刊的 MTS（eJournalPress）**：网址形如 `https://mts-<刊缩写>.nature.com/cgi-bin/main.plex`，见下一节。
- 以官网按钮实际跳转到的网址为准，不按出版社猜。

## 第一次实测要记录的

- 账号是 Springer Nature 统一账号，还是按期刊分开；注册时要不要验证邮箱。
- 邮箱唯一性的范围；共同通讯作者怎么登记。
- 步骤列表；**终点动作**在哪一步，前面有没有确认页；提交前能不能拿到系统 PDF。
- 正文接受什么格式（Word、LaTeX、PDF）；有没有单独的作者页类型；声明（利益冲突、数据、作者贡献）是表单填写还是上传文件。
- 期刊是否要求 Data availability、Code availability、Author contributions 写进正文的固定小节。

## Nature 系列 MTS（eJournalPress）：只读查状态

实测：用通讯作者的账号只读查审稿进度。投稿步骤未实测。

- **账号**：Springer Nature 统一登录（`mts-spd.nature.com`），一个账号通 Nature 各子刊。用户名不是邮箱。别人的账号按 SKILL.md「账号与密码」走凭证库和 `PAPER_SUBMIT_EXTRA_SECRETS`。
- **登录后先落在个人资料页**（Personal Profile，带 Modify 按钮）：不要在这页点 Modify 或保存，直接用页面上的链接离开。
- **只读入口**：
  - 资料页顶部「Manuscript(s)」（`spd.plex?form_type=display_person_manuscripts`）：列出该账号在所有 Nature 刊的稿件、角色和当前状态。
  - 各刊 tracking 首页 →「Live Manuscripts」→「View Manuscript」：题名、作者、当前阶段、文件。
  - 稿件页底部「Check Status」（`form_type=status_details`）：逐阶段的开始日期，是判断「卡了多久」的依据。
- **不要点**：Send Manuscript Correspondence、Modify Unavailability Dates、Modify My Springer Nature Account、Submit Manuscript，以及任何 Withdraw、Revise、Agree、Decline 按钮。查完从顶部 logout，再关浏览器会话。
- 稿号后缀 `-T` 表示由其他 Nature 刊转来；状态历史第一行是「Manuscript Transferred」。
