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

**接需求（进门）**：见 `references/intake.md`。能从话里认出模式就不空问；**用户给模糊领域、没具体方向时，先轻量侦察该领域、把真实子方向摆成带名字+一句话解释的菜单让用户挑、逐级收敛**（兼顾"想广扫整个领域"与"不知道子领域叫啥名"两种），收敛后再路由到模式。

**检索覆盖（不偏科）**：`scout_agent` 两路并取——按时间分段（奠基/里程碑/近期 SOTA）+ 按引用中心度（OpenAlex cited_by 降序抓高被引核心，无论年份）；`completeness_critic` 再查"时间是否畸偏 / 核心文是否齐"。目标是覆盖领域核心，而非只调研老文章或只调研新文章。

## 0 幻觉机制（三档验证门）
`scripts/verify_citations.py` 调 **CrossRef + arXiv + OpenAlex + DBLP + Semantic Scholar** 五源逐条核验，输出：
- **confirmed**：id 解析 + 标题/年份吻合 → 进产物
- **needs-review**：强但不完美（含标题孪生）→ 保留待裁决，**绝不静默删**；可由 `adjudicate_agent` 扒原文按硬字段自动升/降档
- **rejected**：无法解析 / 相似度过低（疑似编造）→ 隔离

不变量：**最终产物 0 编造引用** 且 **0 真论文被静默丢弃**。

## 依赖与环境
- Python 3.8+，**核心脚本仅标准库即可运行**；建议 `pip install truststore certifi`（HTTPS 证书，避免精简环境 arXiv 报 CERTIFICATE_VERIFY_FAILED）。
- 部分 Windows 上 `python3` 是商店占位别名 → 用 `python` 或绝对路径。
- **无需任何 API key**（OpenAlex/CrossRef/DBLP/arXiv 免 key；S2 无 key 时限流即跳过）。可选设 `SEMANTIC_SCHOLAR_API_KEY`/`OPENALEX_EMAIL` 提速提配额。
- 批量核验/检索前可先 `python scripts/preflight.py` 自检源连通性 + key 状态。
- **PDF 全文抽取（可选）** 另需依赖，装进专用 venv，核心不受影响：`python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-pdf.txt`，用该 venv 的 python 跑 `fetch_fulltext.py`；未装则自动回退摘要。

## 验证门用法
```bash
echo '[{"title":"Attention Is All You Need","year":2017}]' > cand.json
python scripts/verify_citations.py --in cand.json --threshold 0.92 --sleep 0.5 > verdict.json
# 输出 {confirmed:[...], review:[...], rejected:[...]}
```

## 产物
默认落 `lit-scout-out/<topic>/`：`report.md`、`verified.bib`/`verified.ris`/`verified.csl.json`/`verified.enw`（仅 confirmed，带真实 DOI + 代码链接；覆盖 BibTeX/Zotero/pandoc/EndNote）、`needs-review.md`、`rejected.md`、`obsidian/`；可选 `search-strategy.md`（检索可复现报告，`--search-log`）与 `survey-draft.md`（投稿体综述草稿，survey_writer_agent 产，只引 verified.bib）。Obsidian 用 `cites::`/`cited-by::` wikilink 渲染**集合内引用图**(有原文 evidence 才升级 `improves::` 方法谱系)，MOC 按 taxonomy 分组；见 `references/export-zotero-obsidian.md`。

## 目录
```
lit-scout/
├── SKILL.md                 # 模式路由 + 0幻觉铁律 + 共享底座
├── scripts/
│   ├── verify_citations.py  # 确定性多源验证门 (三档 + 持久缓存 + 跨索引三角验证 + 可选API-key)
│   ├── verification_cache.py# SQLite 验证缓存 (跨运行只验一次, TTL 90 天)
│   ├── dedup.py             # 候选去重 (DOI主键 + 标题作者兜底 + 预印本↔出版归并)
│   ├── parse_refs.py        # 模式⑤: .bib/.ris/.tex/.txt 参考文献 → 候选 JSON
│   ├── preflight.py         # 批量前连通性自检 (源可达性 + key 状态)
│   ├── fetch_fulltext.py    # 抓开放获取 PDF 抽全文 markdown (PyMuPDF, 需 PDF venv)
│   ├── check_claims.py      # claim 层证据定位 (SOTA 数字/关系断言, 配 faithfulness_agent)
│   ├── build_outputs.py     # 单一 canonical 数据流导出 (verdict → corpus → bib/ris/csl/enw/report/obsidian) + trust层
│   ├── check_outputs.py     # 输出一致性校验门 (交付前必跑, 支持 --mode)
│   └── check_voice.py       # 去 AI 味扫描(WARN) + survey 引用硬校验(\cite{}/[citekey])
├── references/              # 各模式流程 + 检索源 + 输出/OS 规则
├── agents/                  # 各 agent prompt（按模式调度）
├── assets/                  # watchlist 等模板
├── evals/
│   ├── trigger-eval.json    # 触发评测集
│   ├── gold-citations.json  # 验证门回归 gold set (已知真/假引用)
│   ├── run_gold.py          # 跑 gold set, 报混淆矩阵 + 校验 0幻觉不变量
│   └── test_fetch_fulltext.py # fetch_fulltext 离线单测(mock 网络: resolver 分支 + %PDF 守卫 + 抽取)
├── requirements.txt         # 可选 truststore/certifi (HTTPS 证书)
├── requirements-pdf.txt     # 可选 PDF 全文抽取 (PyMuPDF/pymupdf4llm/pdfplumber, 装进 .venv)
└── LICENSE                  # MIT
```

可信度层(Trust)：confirmed 只代表"真实存在"，build_outputs 另算 **撤稿/评审层(preprint/conference/journal)/引用热度/版本状态/期刊质量软信号**，并结合验证门的**跨索引三角验证**，report 出「可信度告警」(撤稿禁作 baseline、纯预印本、单索引存疑、venue 元数据稀薄)。**存在性 ≠ 可信度**。

全文与 claim 核对(可选，0 幻觉脊柱的深化)：`fetch_fulltext.py` 抓开放获取 PDF 抽全文 → `check_claims.py` 在全文里机械定位 SOTA 指标值/关系断言的证据 → `faithfulness_agent` 判定并撤下不被支持的论断。把"引用存在"推进到"论断也对得上"。需 PDF venv（`requirements-pdf.txt`），抓不到自动回退摘要。

输出人设(去 AI 味)：报告散文走"同领域资深同门"人设（与进门 `intake.md` 同一人设），两种语域——**笔记体**(默认 report.md，给自己看)与**投稿体**(可选 `survey-draft.md`，能直接进综述/论文，只引 verified.bib)。规范见 `references/voice.md`；`check_voice.py` 扫 AI 套话(WARN) + 硬校验 survey 行内引用(`\cite{}` 或 `[citekey]`，跳过代码块内的格式说明)必须命中 verified.bib。

## 端到端数据流（杜绝漂移）
```
(可选先 preflight.py 自检源连通性)
candidates → dedup.py(去重: DOI主键+标题作者兜底+预印本↔出版归并)
          → verify_citations.py(五源核验 + 持久缓存 + 跨索引三角验证) → verdict.json(confirmed/review/rejected)
  可选深度: fetch_fulltext.py(抓OA全文) → check_claims.py(claim证据定位) → faithfulness_agent 撤下不实断言
  agent 产出可选输入: summaries · code_repos · taxonomy · sota · seeds · manual_overrides
                      · search_log(检索可复现) · positioning(模式①) · circles(模式④)
          → build_outputs.py [--summaries --code-repos --taxonomy --sota --seeds --overrides
                              --search-log --positioning --circles --merge-corpus]
              → corpus.json(canonical, 含 trust 可信度层)
                → report.md / verified.bib / verified.ris / verified.csl.json / verified.enw
                  / obsidian/ / needs-review.md / rejected.md
                  / search-strategy.md(可选) ; survey_writer_agent 另出 survey-draft.md(可选)
          → check_outputs.py [--mode landscape|positioning|seed|tracking] (必须 ALL PASS 才交付)
          → check_voice.py (去 AI 味 WARN + survey 引用硬校验; check_outputs 末尾自动调)
```
身份(id/title/year)以 verdict 为权威，富化只补不覆盖；引用边诚实标 `cites`（方法谱系须每边带原文 evidence）；`--overrides` 仅改导出类型不伪造源 type。

## 测试与回归
两层保护，改动后跑一遍防退化：
- **验证门 0 幻觉不变量**（需网络）：`python evals/run_gold.py --no-cache --sleep 2`。跑 28 条已知真/假引用 gold set，
  报混淆矩阵并断言「0 编造进 confirmed、0 真论文被 rejected」，违反即非 0 退出。
- **全文抽取逻辑**（离线，秒级）：`.venv/Scripts/python evals/test_fetch_fulltext.py`。mock 网络，覆盖 `fetch_fulltext`
  的 resolver 各分支（pdf_url 优先 / oa_url 兜底 / 真无 OA / 查询失败区分）+ `%PDF` 魔数守卫 + 真实抽取（用 fitz 现造 PDF）。
  未装 PDF 库时抽取那条自动 SKIP，其余仍跑。
- **触发评测**：`evals/trigger-eval.json`（25 条，含模糊领域/稿件核验等正反例），核对 skill 描述的触发准确度。

## License
MIT，见 [LICENSE](LICENSE)。
