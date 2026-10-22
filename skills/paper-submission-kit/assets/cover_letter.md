---
# Cover letter source. Render:
#   python3 <skill>/scripts/render_cover_letter.py <this file> <out dir> --roster <authors.yml>
# Required keys
title: "<Manuscript title exactly as in the manuscript>"
authors: [<First Author>, <Second Author>, <Last Author>]   # display order of the manuscript
journal: <Journal Name>
signers: [<author-id>, <author-id>]   # corresponding authors; the order the authors choose, else reverse author order
# Optional keys
# logos: [<logo-stem>, <logo-stem>]   # files <assets>/logos/<stem>.png, left to right, one per institution
# closing: "Sincerely,"               # default
# signers_label: "Corresponding Authors:"   # default follows the number of signers
# date: "1 January 2026"              # default: no date line
# A signer may override roster facts, or carry all facts when it is not in the roster:
#   signers: [{id: wang-wu, title: Associate Professor, affiliation: [School of Example Studies, "Example University, Example City"], email: wangwu@example.com, name: Wu Wang}]
---

Dear Editor,

We respectfully submit our manuscript, "<Manuscript title>", for consideration as <an Article / a Research Article> in *<Journal Name>*.

<Why the problem matters, in one sentence.> Yet <the task> faces a persistent challenge. <Route 1> provides <its strength> but <its limit>, whereas <route 2> <its strength> but <its limit>. <What therefore remains unknown.> This study addresses this gap <with / by …>.

<Method paragraph: what the work builds on, the core design, and the data or cases it covers.>

The manuscript makes four principal contributions.

**<Contribution 1: the method or assessment>.** <What it does.> <Decisive validation numbers, e.g. stability and accuracy.>

**<Contribution 2: first main finding>.** <Finding with its key number.> <What it means.>

**<Contribution 3: second main finding>.** <Finding with its key number.> <What it means.>

**<Contribution 4: strategy or implication>.** <Finding.> <Use for planning, policy or practice.>

The manuscript is closely aligned with the scope of *<Journal Name>* through its integration of <themes>. The journal has recently published <2–3 recent papers of the journal, DOIs checked on Crossref>. Beyond <what a reader might expect>, the study <what it adds>. <Data and code availability, when open.>

We affirm that this manuscript reports original work that has not been published and is not under consideration elsewhere. <Journal-required statements, as decided by the authors, e.g. prior contact with editors.> All authors have reviewed and approved the manuscript and declare no competing interests. Funding, data availability and code availability are fully disclosed in the manuscript.
