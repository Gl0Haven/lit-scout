# lit-scout

学术调研侦察 skill —— 把"一堆搜索结果"变成**可直接用于写作和定位**的结构化产物（集合内引用图(有原文 evidence 才升级为方法谱系) / SOTA 对照 / gap 定位 / 候选 baseline / 必引清单），而不是散搜结果或裸书目。

核心承诺：**引用幻觉 = 0**。任何论文/DOI/作者只能来自检索工具真实返回；每条引用经多源检索命中真实 DOI/arXiv 并标题比对后才采用；灰区不删、交人工或自动扒原文裁决。

## 五种模式
| 模式 | 用途 | 详细 |
|---|---|---|
| ① 论文定位 | 给你的工作找 baseline / related work / gap | `references/positioning.md` |
| ② 主题地形图 | 梳理领域流派、SOTA、集合内引用图(有原文 evidence 才升级为方法谱系) | `references/landscape.md` |
| ③ 持续追踪 | 定期追 arXiv/新文，relevance 筛 + digest（`--merge-corpus` 累积不丢历史） | `references/tracking.md` |
| ④ 种子扩展 | 沿一篇论文的前后向引用滚雪球 | `references/seed-expansion.md` |
| ⑤ 稿件引文核验 | 核验现成 .bib/.ris/.tex 引用是否真实/对得上（验证门直接应用，不插引用） | `references/citation-check.md` |

## 0 幻觉机制（三档验证门）
`scripts/verify_citations.py` 调 **CrossRef + arXiv + OpenAlex + DBLP + Semantic Scholar** 五源逐条核验，输出：
- **confirmed**：id 解析 + 标题/年份吻合 → 进产物
- **needs-review**：强但不完美（含标题孪生）→ 保留待裁决，**绝不静默删**；可由 `adjudicate_agent` 扒原文按硬字段自动升/降档
- **rejected**：无法解析 / 相似度过低（疑似编造）→ 隔离

不变量：**最终产物 0 编造引用** 且 **0 真论文被静默丢弃**。

## 依赖与环境
- Python 3.8+，仅标准库即可运行；建议 `pip install truststore certifi`（HTTPS 证书，避免精简环境 arXiv 报 CERTIFICATE_VERIFY_FAILED）。
- 部分 Windows 上 `python3` 是商店占位别名 → 用 `python` 或绝对路径。
- 验证脚本无需任何 API key（OpenAlex/CrossRef/DBLP/arXiv 免 key；S2 无 key 时限流即跳过）。

## 验证门用法
```bash
echo '[{"title":"Attention Is All You Need","year":2017}]' > cand.json
python scripts/verify_citations.py --in cand.json --threshold 0.92 --sleep 0.5 > verdict.json
# 输出 {confirmed:[...], review:[...], rejected:[...]}
```

## 产物
默认落 `lit-scout-out/<topic>/`：`report.md`、`verified.bib`/`verified.ris`（仅 confirmed，带真实 DOI + 代码链接）、`needs-review.md`、`rejected.md`、`obsidian/`。Obsidian 用 `cites::`/`cited-by::` wikilink 渲染**集合内引用图**(有原文 evidence 才升级 `improves::` 方法谱系)，MOC 按 taxonomy 分组；见 `references/export-zotero-obsidian.md`。

## 目录
```
lit-scout/
├── SKILL.md                 # 模式路由 + 0幻觉铁律 + 共享底座
├── scripts/
│   ├── verify_citations.py  # 确定性多源验证门 (输出 verdict.json 三档) + 持久缓存
│   ├── verification_cache.py# SQLite 验证缓存 (跨运行只验一次, TTL 90 天)
│   ├── dedup.py             # 候选去重 (DOI主键 + 标题作者兜底 + 预印本↔出版归并)
│   ├── parse_refs.py        # 模式⑤: .bib/.ris/.tex/.txt 参考文献 → 候选 JSON
│   ├── build_outputs.py     # 单一 canonical 数据流导出 (verdict → corpus → bib/report/obsidian) + trust层
│   ├── check_outputs.py     # 输出一致性校验门 (交付前必跑, 支持 --mode)
│   └── check_voice.py       # 去 AI 味扫描(WARN) + survey 草稿 \cite 硬校验
├── references/              # 各模式流程 + 检索源 + 输出/OS 规则
├── agents/                  # 各 agent prompt（按模式调度）
├── assets/                  # watchlist 等模板
├── evals/
│   ├── trigger-eval.json    # 触发评测集
│   ├── gold-citations.json  # 验证门回归 gold set (已知真/假引用)
│   └── run_gold.py          # 跑 gold set, 报混淆矩阵 + 校验 0幻觉不变量
├── requirements.txt         # 可选 truststore/certifi (HTTPS 证书)
└── LICENSE                  # MIT
```

可信度层(Trust)：confirmed 只代表"真实存在"，build_outputs 另算 **撤稿/评审层(preprint/conference/journal)/引用热度/版本状态**，report 出「可信度告警」，撤稿条目禁作 baseline。**存在性 ≠ 可信度**。

输出人设(去 AI 味)：报告散文走"同领域资深同门"人设，两种语域——**笔记体**(默认 report.md，给自己看)与**投稿体**(可选 `survey-draft.md`，能直接进综述/论文，只引 verified.bib)。规范见 `references/voice.md`；`check_voice.py` 扫 AI 套话(WARN) + 硬校验 survey 的 `\cite` 必须命中 verified.bib。

## 端到端数据流（杜绝漂移）
```
candidates → verify_citations.py → verdict.json(confirmed/review/rejected)
  agent 产出可选输入: summaries.json(总结) · code_repos.json(代码) · taxonomy.json · sota.json · seeds.json · manual_overrides.json
          → build_outputs.py [--summaries --code-repos --taxonomy --sota --seeds --overrides]
              → corpus.json(canonical) → report.md / verified.bib / verified.ris / obsidian/ / needs-review.md / rejected.md
          → check_outputs.py [--mode landscape] (必须 ALL PASS 才交付; landscape 额外查 Taxonomy/SOTA/种子三章与 schema)
```
身份(id/title/year)以 verdict 为权威，富化只补不覆盖；引用边诚实标 `cites`（方法谱系须每边带原文 evidence）；`--overrides` 仅改导出类型不伪造源 type。

## License
MIT，见 [LICENSE](LICENSE)。
