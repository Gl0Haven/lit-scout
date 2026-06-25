# 可选导出：Zotero / Obsidian（非强需）

仅当用户明确要求时做。核心产物是 `lit-scout-out/<slug>/`（report.md + verified.bib），导出只是再加工。
**只导出 confirmed 条目；review/rejected 永不进入导出。**

## Zotero（存论文）
- 默认：导出 `verified.bib`(BibTeX) 或 `.ris`，用户拖进 Zotero 导入。零鉴权、最稳。
- 每条带真实 DOI/arXiv，Zotero 自行抓元数据/PDF。
- 进阶（可选，需用户提供 API key + libraryID）：Zotero Web API 程序化建条目。无 Zotero MCP/凭证时不设默认。

## Obsidian（展示引用图；有 evidence 才升级谱系）
为每篇 confirmed 论文生成一个 .md 笔记，用 wikilink 关系让 Graph View 渲染。**关系分两段，默认只输出引用图**（与 `build_outputs.py` 的 `cites::` 输出一致）：

笔记模板（内联，build_outputs.py 即按此生成）：
```markdown
---
title: "<title>"
authors: [...]
year: 2021
venue: <venue>
doi: 10.xxxx/xxxx        # 或 arxiv: 2407.xxxxx
tags: [<方法流派, 由 taxonomy_agent 填>]
---
# <title>
**TL;DR**: <来自真实摘要；缺则标 (摘要不可得)>

## 集合内引用图（默认；relation=cites，证据=referenced_works）
- cites:: [[<被引论文>]]
- cited-by:: [[<施引论文>]]

## 方法谱系（可选；仅当每条边有原文 evidence 才写，否则整段省略）
- improves:: [[<前驱>]]  — 证据: "原文/施引句片段…"
- baseline-of:: [[<...>]]  — 证据: "…"
```
铁律：**无原文 evidence 不得出现 improves::/baseline-of::/extends:: 等谱系标记**（check_outputs.py 会拦）。`uses-dataset::` 等事实关系可来自抽取。
- MOC：扁平索引由 build_outputs 生成；方法 taxonomy 由 taxonomy_agent 重聚类后填，勿用源 auto-topic。
- frontmatter 兼容 Dataview，可查询出 SOTA 表。

## 铁律
无 evidence 的关系**不写 wikilink**（避免画出臆造的边）。导出前确认每条都在 confirmed 集合内。
