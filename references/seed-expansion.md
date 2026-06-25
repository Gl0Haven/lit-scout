# 模式④ 种子扩展

目标：给一篇关键论文，沿引用图前后向滚雪球，产出按相关性+中心度排序的同心圆相关工作图。适合"我有一篇核心文，想找全周边"。

## 流程
1. **解析种子**：`seed_parser` 从种子论文（PDF/arXiv/DOI）抽元数据 + 参考文献列表。
2. **引用图扩展**：`citation_graph_agent` 取后向(它引的)+前向(引它的)，必要时二跳（用户指定深度，默认 1 跳）。候选只来自 API 真实返回。
3. **抽取**：`extractor_agent` 逐篇取方法/指标/贡献 + GitHub code_repo + 证据。
4. **验证门**：`verify_agent` 三档 → `adjudicate_agent` 裁决 review → 仅 confirmed 进图。
5. **剪枝排序**：`prune_rank_agent` 按"与种子相关性 + 引用中心度(被引数/共被引)"排序，分核心/邻近/外围三圈。
6. **合成**：产出同心圆相关工作图 + 排序 .bib。

## 产物 report.md
```markdown
## 种子
[Seed2021] <title> — doi/arxiv

## 同心圆相关工作
### 核心圈（直接相关，必读/必引）
- [A] —(关系:种子的直接前作) 证据… | 被引 320 | code…
### 邻近圈
- [B] —(关系:同方法不同任务) …
### 外围圈（弱相关，可选）
- [C] …

## 待确认 / 已隔离
```

> **产物归属（统一走 canonical 管线）**：prune_rank_agent 把三圈写成 `circles.json`
> `{seed:{slug,title}, core/adjacent/peripheral:[{slug,relation,evidence,cited_by}]}`，
> 经 `build_outputs.py --circles circles.json` 渲染进 report 的「## 同心圆相关工作」段，
> 不要另写会被覆盖的 report.md。slug 须 confirmed；交付用 `check_outputs.py --mode seed`。

## 守则
0 幻觉铁律；关系标注（前作/后继/同法）须有 evidence；中心度数字只记 API 返回的真实被引数；圈层划分说明依据。
