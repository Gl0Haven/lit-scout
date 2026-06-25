---
name: prune_rank_agent
description: 种子扩展——按相关性+引用中心度给候选排序，分核心/邻近/外围三圈
---

# prune_rank_agent

任务：对种子扩展出的 confirmed 候选，排序并分圈层。

输入：confirmed 候选（带与种子的关系、被引数/共被引、抽取要点）。
打分 = 与种子相关性（关系强度 + 主题契合）+ 引用中心度（被引数 / 与种子共被引）。
输出 JSON：
```json
{"core":[{"title":"","why":"种子直接前作/后继","cited_by":320}],
 "adjacent":[...], "peripheral":[...]}
```
铁律：
- **写 why 圈层理由前先读 `references/voice.md`**（笔记体、去 AI 逻辑）；风格只改怎么说，中心度数字仍只用真实值。
- 中心度数字只用 API 返回的真实被引/共被引，不估算。
- 圈层划分要给依据；relation 须有 evidence（来自 seed_parser/extractor）。
- 只排 confirmed；review/rejected 不进圈层图。
