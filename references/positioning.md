# 模式① 论文定位（primary）

目标：给用户的工作（贡献/claim）找到**最近邻竞品、差异点、gap、候选 baseline、必引清单**，产出可直接写进 Related Work 的素材。

## 流程

1. **录入贡献**：让用户用 1–3 句说清自己方法的核心贡献/claim，以及领域关键词。不清楚就追问（方法名、任务、数据集、对标的是谁）。
2. **找最近邻**：派 `scout_agent`，按"任务+方法+数据集"多角度检索，返回候选最近邻论文（只来自工具返回）。
3. **引用图扩展**：对最近邻派 `citation_graph_agent` 做前向(谁引了它)+后向(它引了谁)，补全竞品与 baseline 候选。
4. **逐篇抽取**：派 `extractor_agent`，每篇抽 方法/数据集/指标/venue/年份/核心贡献，并对"它与用户工作的关系"取**原文证据片段**。
5. **验证门**：候选汇成 JSON → `verify_agent` 调 `scripts/verify_citations.py` → 三档 confirmed/review/rejected。**仅 confirmed 进下一步**；review 举给用户消歧确认（不删），确认后升 confirmed。
6. **合成定位**：派 `positioning_agent`，只用 confirmed，产出下方产物。

## 产物（写入 lit-scout-out/<slug>/）

### report.md
```markdown
# 论文定位 — <你的方法名/主题>

## 你的贡献(用户原话)
<...>

## 最近邻竞品(按相似度)
| 工作 | venue/年 | 方法要点 | 与你的差异 | 证据 |
|------|---------|---------|-----------|------|
| [Author2021] | Venue'21 | ... | 你多了 X / 你用了 Y | "原文片段…" |

## Gap 定位
- 现有工作共同未解决: <...证据支撑...>
- 你的工作正好补在: <...>

## 候选 baseline(你该对比谁)
- [Author2020] — 同任务同数据集，公认 baseline，指标 PSNR=…(原文)
- ...

## 必引清单
- 种子/奠基: ...
- 直接竞品: ...

## 待确认(needs-review, 不删除, 请你裁决)
- "<标题>" — score / 查回标题 / 备选: <…>；确认是否同一篇

## 已隔离(rejected, 疑似不存在/编造)
- "<标题>" — 原因: <verify 给的 reason>
```

### verified.bib
仅 confirmed 条目，带真实 DOI/arXiv，供 Zotero/LaTeX 直接用。

### Related Work 草骨架
按"任务背景 → 主流方法分支 → 各分支代表作及局限 → 你的定位"组织的段落骨架（不替用户写满，只给可填的结构 + 已验证引用锚点）。

> **产物归属（统一走 canonical 管线）**：positioning_agent 把上面的综合结果写成 `positioning.json`
> `{contribution, neighbors:[{slug,diff,evidence}], gap, baselines:[{slug,why,metric}], must_cite:[{slug,role}], related_work_skeleton}`，
> 经 `build_outputs.py --positioning positioning.json` 渲染进 report 的「## 论文定位」段——
> 不要另写一份会被 build_outputs 覆盖的 report.md。slug 必须是 confirmed 的；交付用 `check_outputs.py --mode positioning`。

## 守则
- 严守 SKILL.md 0 幻觉铁律：候选只来自检索；未过验证门不写入；关系必须附证据。
- baseline/指标只记原文给出的数字，不推断。
- 用户的贡献用其原话，不替他拔高。
