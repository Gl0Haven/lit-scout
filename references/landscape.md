# 模式② 主题地形图

目标：把一个研究领域梳理成 taxonomy + SOTA 对照 + **集合内引用图** + 必读种子，供综述选题/进入新方向。
> 默认只输出"集合内引用图"(relation=cites)；**只有为每条边补到原文 evidence(论文自述改进/施引句)时，才升级为"方法谱系"(improves)**。无 evidence 不得标谱系。

## 流程
1. **圈定范围**：与用户确认主题、年限、目标 venue、深度（快扫/系统）。
2. **展概念簇**：派 `scope_agent`，把主题拆成概念簇 + 同义词 + 关键团队/作者。
3. **并行多角度扫**：每个概念簇派一个 `scout_agent`（可并行），候选只来自检索返回；带 id。
4. **逐篇抽取**：`extractor_agent` 抽 方法/数据集/指标/venue/贡献 + GitHub `code_repo`，取证据。
5. **验证门**：`verify_agent` → 三档；review 经 `adjudicate_agent` 扒原文裁决；仅 confirmed 进图。
6. **聚类**：`taxonomy_agent` 把 confirmed **按方法/问题重聚类**成流派/分支。⚠ 不要直接拿 OpenAlex primary_topic / S2 fields 当 taxonomy（粒度粗、常错位），只当弱提示。
7. **排谱系**：`lineage_agent` 排"谁改进了谁"的演进链（每条边须有 evidence）。
8. **查漏循环**：`completeness_critic` 指出未覆盖的子方向/年份/venue → 回第 3 步补，直到 K 轮无新增。
9. **合成**：产出下方 report，写 `lit-scout-out/`。

## 产物 report.md
```markdown
## Taxonomy（方法流派）
- 流派A：代表作 [X], [Y] — 共同思路…
- 流派B：…

## SOTA 对照表
| 方法 | 数据集 | 指标 | venue/年 | 代码 |
|------|--------|------|---------|------|

## 集合内引用图（relation=cites；有原文 evidence 才升级为"演进谱系/谁改进了谁"）
- [A2018] →(改进:加注意力) [B2020] →(改进:多尺度) [C2022]   每条注 evidence

## 必读种子清单
- 奠基 / 里程碑 / 当前 SOTA

## 待确认(needs-review) / 已隔离(rejected)
```

## 守则
严守 SKILL.md 0 幻觉铁律；谱系边无 evidence 不画；指标只记原文数字；coverage 不足要 `log` 说明漏了什么，不假装覆盖全。
