# 各投稿系统去哪看状态

登录方法和常见问题见 `../../paper-submit/references/systems/` 下对应系统的文档。这里只写：查状态要看哪一页，账号怎么进，哪些操作不能碰。

「实测」一列写查状态时有没有实际走通过，不是指投稿时走通过。第一次走通后，把实际菜单名补进来，并把该列改为已实测。

| 系统 | 常见期刊 | 状态在哪看 | 不能点 | 实测 |
|---|---|---|---|---|
| Editorial Manager | Elsevier 老刊、KeAi、部分 Springer 刊 | 打开 `https://www.editorialmanager.com/<刊名缩写>/default2.aspx`，profile 已登录时直接显示 Submissions Being Processed；列表在 iframe 里，Current Status 列就是当前阶段。没登录时去 `login.ashx`，Elsevier 刊要展开 "Alternatively, use your username and password"。共同作者确认表看 Confirmed? 列：有的刊每行有 Author Status 链接；没有的刊直接开 `<刊>/ContributingAuthorStatus.aspx?docID=<docID>&msid=<msid>&revision=0`，两个参数取自同一行 View Submission 的 `viewAuthorPDFs(docID, '稿号', 0, 'msid')`（有的刊行内链接要先点表头的 Expand Action Links 才显示；`weekly_report.py` 直接从 iframe HTML 取） | Submit Revision、Withdraw、Decline to Revise、Approve Submission；确认页上的 Send Letters（对外发信） | 已实测（含 ContributingAuthorStatus） |
| Elsevier 新投稿系统 submit.elsevier.com | 已切换到新系统的 Elsevier 刊 | Your submissions 列表**只显示用这个新服务投的稿**，不代表这个账号下的全部稿件。要看全部，进该刊 EM 的登录页，点 Elsevier account login 单点登录：凡是邮箱和这个 Elsevier ID 相同的 EM 账号都会进去。注意，进去后的账号档案名可能是别人（邮箱早先被绑到另一位合作者的 EM 账号上时） | 撤稿、提交修改稿、接受转投（Transfer） | 已实测 |
| Springer Nature（Snapp） | 用 Snapp 的 Springer 刊 | 用 Springer Nature 账号（邮箱加密码）登录，打开 `submission.springernature.com/submission-details/<Submission ID>`；页面上有 CURRENT STATUS 和 Progress so far 各步骤的状态 | 撤稿、提交修改 | 已实测 |
| Nature 系列 MTS（eJournalPress） | Nature 子刊 | 见 paper-submit 的 `systems/springer-nature.md`「只读查状态」 | 同该文档 | 已实测（只读） |
| IEEE Research Exchange（ieee.atyponrex.com） | IEEE 期刊 | 用 IEEE Account 登录，进作者中心的稿件列表 | 提交返修、撤稿 | 未实测 |
| JournalX（玛格泰克） | 国内中文刊 | 作者中心的稿件列表，看处理状态和审稿进度。来信主题常只有「投稿成功通知」，稿号、题目都不在主题里，`mail_scan.py` 按发件人里的中文刊名匹配；回执发到通信作者的邮箱 | 撤稿、提交修改稿 | 未实测（只看邮件） |

`weekly_report.py` 目前自动读 Editorial Manager（列表页 + 作者确认页）和 Snapp（稿件详情页）；其他系统只看邮件，并列进报告第五节。

## Elsevier 的作者确认邮件，哪些会卡住流程

| 邮件主题 | 含义 | 卡不卡流程 |
|---|---|---|
| Please verify your contribution to … | 每位作者同意署名并同意发表 | 某些刊（如 A 刊）的投稿确认信写明，作者确认完成前不进入编辑流程，60 天内没完成可能被撤回或拒稿。以该刊的确认信为准；会卡的刊写进配置 `blocking_confirm_journals` |
| Confirm co-authorship of submission to … | 共同作者同意署名，确认后可以跟踪稿件 | 信里没写会卡流程；进度可以在 Author Status 里看 |

这些确认是作者本人的声明，由作者自己点链接，或用户当次明确授权后才能代点。查论文时只报告谁还没确认。

### 给合著者的提醒（用户去通知时直接给他这段）

1. **搜哪封信**：在作者本人邮箱里搜主题 `Please verify your contribution to` 加论文题目开头几个词，发件人是该刊名，地址在 `editorialmanager.com` 域名下。
2. **认准是哪一封**：信的正文里有 `Manuscript Number`，以当前稿号为准，再写上发信的本地时间。同一题目可能还有旧稿号（转投前那一轮）的确认信，点旧信没用。
3. **点哪里**：
   - 先点信里的 `Yes, I am affiliated.`；
   - 网页打开后，按 `Submit to Publication`；
   - 看到 `Thank you for verifying` 才算完成。
   - 页面要登录时，用他在这个刊的账号登录，忘了密码就点 Forgot password。
4. **作者说「点过了」**：以 ContributingAuthorStatus 页的 Yes 为准，不以作者自述为准。

### 获授权代点时怎么做

1. **取链接。** 从该作者能读的邮箱里取确认链接，写进 0600 的临时文件，不打印。
2. **开浏览器。** 每位作者用一个独立的新 profile（新的投稿人 ID）打开链接，不能用已经登录了别人账号的 profile。
3. **先关 cookie 横幅。** 横幅会挡住页面上的按钮：点了没反应时，先点 Accept all cookies。
4. **按页面提示操作：**
   - 显示 Verify Contributing Authorship：点 Submit to Publication。看到 "Thank you for verifying" 才算完成。
   - 要求登录：用该作者在这个刊的账号登录，用户名常常就是邮箱，密码先试标准密码（secret 名）。登录后会回到确认页。同一账号最多试两种密码。
   - 提示 "A login session for a different user ID is still active"：这篇稿件里的作者记录关联的是该作者的另一个账号，换账号或报给用户。
   - 提示 "This action is not currently available … already affirmed"：可能已经确认过，去 Author Status 核对，不要反复点。
5. **没有账号的作者：** 确认前要先注册。Elsevier 刊注册时还要选研究分类，会以作者名义新建账号，需要用户当次同意再做。
6. **核对结果。** 做完回 Author Status（EM 有这个链接的刊）看 Confirmed? 列；没有 Author Status 的刊，看作者账号的 Submissions Being Processed 里有没有出现这篇稿件。

## 状态怎么对应到台账

| 系统里看到的 | `paper progress --stage` |
|---|---|
| With Editor、Editor Assigned、Technical check | 编辑处理中 |
| Under Review、Reviewers Assigned | 外审中 |
| Required Reviews Completed、Decision in Process | 等待决定 |
| Major Revision／Minor Revision（看决定信原文） | 大修／小修，`--due` 填截止日 |
| Revision submitted、Revisions Being Processed | 返修已提交 |
| Accept | 已录用 |
| Reject、Reject and transfer | 被拒；有转投邀请的，在备注里写明，不替用户接受 |

- Submitted to Journal、Manuscript Submitted：还在投稿后的初筛，阶段不改，只记一次 check-in。
- `--date` 填系统显示的更新日期，不填查看的那一天。
- EM 列表页的时间是美国东部时间，换成本地时间按时差换算（例如换成 UTC+8 要加 12 或 13 小时，看是否夏令时）。
