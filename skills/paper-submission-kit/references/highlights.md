# Highlights

期刊要求 Highlights 时读本页（Elsevier 系常见，Nature 系没有）。条数和字符上限以期刊作者指南为准；指南没写时默认 4 条。

## 1. 两种形态

| 形态 | 用途 | 规格 |
|---|---|---|
| 系统短版（多数期刊的硬要求） | 投稿系统或 `highlights.docx` | 3–5 条，每条一句，通常 ≤85 字符（含空格），以期刊指南为准 |
| 展开式（可选） | 期刊允许较长 Highlights 或作者想给编辑一份详版时 | 每条：粗体短句主张 + "This study finds/reveals/shows …" 展开 3–4 句，约 80–150 词 |

先确认期刊要哪一种。只要短版时，不另交展开式。

## 2. 每条的四层（展开式；短版只保留第 1 层）

1. 总起：本文做了什么（核心主张，人话，可含研究对象名，不给精确小数）。
2. 难点：领域里的具体卡点。
3. 做法：与既有方法的关键区别。
4. 升华：优先领域层（对整个学科或工程问题的意义），其次机理层（把做法重构成更普适的机理），最后方法层（可迁移到哪些任务）。

不用 "results show effectiveness" "this is a novel approach" "future work will …" 当升华。

## 3. 四条的分工

| 条 | 默认承担 |
|---|---|
| 1 | 总框架或评估 + 领域意义 |
| 2 | 第一个核心创新或发现 |
| 3 | 第二个核心创新或发现 |
| 4 | 结果与可迁移性或实践意义 |

只有一个核心创新时，2、3 合并，腾出一条写方法层面的价值；有三个核心创新时，第 1 条压成纯框架声明。各条与投稿信贡献、引言贡献一一对应，每句在正文里有出处。

## 4. 示例（虚构论文，与 `assets/example_cover_letter.md` 同一篇）

短版：

```text
- A physics-guided graph network forecasts hourly demand across 120 metered areas
- An inlet mass-balance term keeps area forecasts consistent with measured supply
- Neighbouring areas cut forecast error by 41% where records are short
- Persistent forecast residuals flag leaks about a day before night-flow analysis
```

展开式第 2 条：

> **Network coupling compensates for short demand records.** Most metered areas have only months of clean hourly data, too little for deep sequence models trained area by area. This study shows that passing information between hydraulically connected areas, under a mass-balance constraint at the supply inlets, lets data-rich neighbours inform data-poor areas. Forecasting short-record areas thus becomes a problem of sharing evidence across the network rather than of collecting longer histories, an idea that transfers to other networked infrastructure with uneven metering.

## 5. 检查

- [ ] 条数、字符数符合期刊指南（短版逐条 `len()` 计数，含空格）
- [ ] 各条之间有分工，不是同质口号
- [ ] 展开式每条第 4 层确实升华，不是 "future work" 或 "effectiveness shown"
- [ ] 与投稿信贡献、引言贡献一致，没有正文里找不到的数字或术语
