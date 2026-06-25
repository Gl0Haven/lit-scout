---
name: lit-scout
description: >-
  Use when the user asks for 学术调研 / 文献调研 / literature survey /
  related work / baseline / gap 定位 / 综述选题 / research landscape /
  SOTA 对比 / 方法谱系 / arXiv 新文追踪 / 沿种子论文找相关工作 /
  核验参考文献是否真实存在 / 查 .bib 引用是否编造 / citation existence check。
  适用于需要从真实论文检索结果生成可写作定位材料、或核验现成引用真伪的场景；
  不用于通用网络调研，也不用于给成稿逐句插入新引用（那是 nature-citation）。
---

# lit-scout — 学术调研侦察

把"一堆搜索结果"变成"可直接用于写作和定位"的结构化产物。区别于通用网络调研工具、纯检索工具、
裸书目工具：本 skill 必产**定位**产物（gap 在哪、该对比谁、必引是哪些；默认输出集合内引用图，有原文 evidence 才升级为方法谱系）。

## 0 幻觉铁律（最高优先，所有模式必守）

这是本 skill 的正确性脊柱，违反即作废：

1. **论文只能来自检索工具的真实返回**。严禁从模型记忆/训练知识生成任何论文、DOI、作者、年份、摘要。想不起就去搜，搜不到就如实说没有。
2. **溯源优先**：检索阶段就抓住每篇的真实 DOI/arXiv id 一起带进管道，核验**按 id 确认**而非按标题猜——这样真论文不会被错杀、假论文进不来。标题-only 是降级路径（仅用户手动粘贴无 id 时），尽量避免。
3. **每条引用过验证门**：`scripts/verify_citations.py` 输出**三档**（见下）。**只有 confirmed 进最终产物/导出**。
4. **三档产物，灰区绝不静默丢弃**：
   - `confirmed`：id 解析 + 元数据吻合 → 交付
   - `needs-review`：强但不完美匹配（标题 0.80–0.92 / id 解析但标题略偏 / 撞孪生）→ **先派 `adjudicate_agent` 扒原文按硬字段(作者/年份/venue/摘要)自动裁决**，能定的升 confirmed / 降 rejected（附扒回字段作证据）；仍不决的才连同备选举给用户。**绝不删除。**
   - `rejected`：无法解析 / 相似度过低（疑似编造）→ 隔离清单
5. **引用图 ≠ 方法谱系**：仅凭 referenced_works/被引拿到的是**引用关系(cites)**，只能命名为"集合内引用图"。要叫"方法谱系/builds-on"，**每条边必须有原文 evidence**（论文自述改进点或施引句）；无 evidence 时只出引用图，不得标 builds-on。
6. 任何数字（指标、年份、引用数）只记检索/原文给出的，不推断、不伪造。

> 不变量：**最终产物 0 编造引用（只放 confirmed）** 且 **0 真论文被静默丢弃（灰区全进 needs-review 给用户看）**。来源=检索、按 id 确认、灰区交人工、边须有据。

## 模式路由

先判定用户意图，选一个模式；不确定就问。每个模式的详细流程在 references/ 下。

| 模式 | 触发 | 详细流程 | 主要产物 |
|---|---|---|---|
| **① 论文定位** | "给我的工作找 baseline/related work/gap"、"我的方法和谁最像" | `references/positioning.md` | 定位报告 + baseline 表 + 必引 .bib + Related Work 草骨架 |
| **② 主题地形图** | "梳理 X 领域"、"综述选题"、"这个方向有哪些流派/SOTA" | `references/landscape.md` | taxonomy + SOTA 表 + **集合内引用图**(每边有原文 evidence 时才升级为方法谱系) + 种子清单 |
| **③ 持续追踪** | "定期追 X 的新论文"、"追 arXiv" | `references/tracking.md` | 按日 digest + 阅读队列；可挂 /schedule |
| **④ 种子扩展** | "沿这篇论文找相关工作"、给定一篇种子 | `references/seed-expansion.md` | 同心圆相关工作图(核心/邻近/外围) + 排序 .bib |
| **⑤ 稿件引文核验** | "核验我 .bib/参考文献里的引用是否真实/对得上"、给定 refs 文件 | `references/citation-check.md` | 逐条核验报告(confirmed/needs-review/疑似编造) |

> 五模式均已落地（references/ 各有详流程），复用同一底座与 agent。模式⑤是验证门的直接应用：
> 只**核验**用户现成引用的存在性，不插引用、不改稿（与 nature-citation 分工）。

## 共享底座

**检索源**（见 `references/sources.md`）：arXiv（ML 主战场）+ CrossRef + OpenAlex/Semantic Scholar（引用图）+ **GitHub（论文级代码/复现仓库检索）** + consensus（若已连该 MCP；未连则自动跳过、不影响其余源）+ 必要时 WebFetch 落地页/PDF。多角度互盲扫，避免单一检索漏网。

**Agent 编排**（prompt 在 `agents/`，用到才加载；可复用）：
- `scout_agent` — 多角度检索，返回候选论文（只来自工具返回）
- `citation_graph_agent` — 前向(谁引了它)/后向(它引了谁)扩展
- `extractor_agent` — 逐篇抽方法/数据集/指标/venue/贡献 + **GitHub 代码仓库**，附原文证据
- 模式专属：`scope_agent`(②展概念簇) `taxonomy_agent`(②聚流派) `lineage_agent`(②谱系边) `completeness_critic`(②查漏) `relevance_filter_agent`(③相关性筛) `seed_parser`(④解析种子) `prune_rank_agent`(④排序分圈)
- `positioning_agent` — 合成最近邻竞品 + 差异 + gap + 候选 baseline（模式①）
- `verify_agent` — **调用 verify_citations.py**（不靠自己判断），分流 confirmed/review/rejected
- `adjudicate_agent` — 对 review 灰区扒原文按硬字段裁决，升/降档（凭证据，保守）
- `faithfulness_agent` —（可选深度）对高风险断言(SOTA 指标值/"A改进B")回原文做 claim-faithfulness 二次核对，撤下不被支持的
- `survey_writer_agent` —（可选）把 confirmed 语料写成可直接进综述/论文的 Related Work 段落（投稿体，只引 verified.bib），产出 `survey-draft.md`

**确定性验证门**：`scripts/verify_citations.py`。吃候选 JSON，调 CrossRef + arXiv + OpenAlex + DBLP + Semantic Scholar 五源逐条核验（多源提 recall；标题含副标题也判同篇），输出三档 confirmed/review/rejected。用 `python` 运行（部分 Windows 上 `python3` 是微软商店占位别名）；脚本内置 SSL 上下文(truststore→certifi→默认)，避免精简环境下 arXiv 等 HTTPS 源报 CERTIFICATE_VERIFY_FAILED。**带持久验证缓存**（`verification_cache.py`，SQLite，默认 `~/.cache/lit-scout`，TTL 90 天）：同一篇跨运行只核验一次；只缓存稳定判定，网络失败的 fail-safe review 绝不缓存；`--no-cache` 可关。回归靠 `evals/run_gold.py`（已知真/假引用 gold set，保证 confirmed 0 编造、rejected 0 错杀真论文）。

**去重门**：`scripts/dedup.py`（scout 之后、verify 之前过一遍）。DOI 主键 + (标题 Jaccard≥0.90 且第一作者姓氏) 兜底 + **预印本↔出版版本归并**（保留 DOI 与 arxiv id，标 `version_status`）。多源 scatter-gather 必有跨源重复，纯标题归一化漏得厉害、会污染引用图与 SOTA 计数。

**Trust 可信度层**（存在性之外，`build_outputs.py` 自动算）：撤稿(OpenAlex `is_retracted`) / 评审层(preprint/workshop/conference/journal) / 引用热度(年均被引) / 版本状态。report 出「可信度告警」（撤稿禁作 baseline、纯预印本未评审提示），`.bib` 给撤稿条目加 RETRACTED note，Obsidian frontmatter 带 `venue_type/peer_reviewed/retracted` 供 Dataview 查询。**存在性 ≠ 可信度**：confirmed 只代表"真实存在"，选 baseline/判 SOTA 前看 trust。

**产物落盘（单一 canonical 数据流）**：
```
build_outputs.py --verdict verdict.json --out <dir> \
  [--summaries summaries.json] [--code-repos code_repos.json] \
  [--taxonomy taxonomy.json] [--sota sota.json] [--seeds seeds.json] \
  [--overrides manual_overrides.json] [--search-log search_log.json] \
  [--positioning positioning.json] [--circles circles.json] [--merge-corpus prev/corpus.json]
```
模式专属输入：`--positioning`(模式①: 最近邻/gap/baseline/必引/RW骨架) · `--circles`(模式④: 核心/邻近/外围三圈) · `--merge-corpus`(模式③累积: 并入上次 corpus 不丢历史，report 出「本次新增 digest」) · `--search-log`(生成 search-strategy.md 检索可复现报告)。
生成 `corpus.json`(canonical 记录) → 由它统一派生 `report.md`、`verified.bib`、`verified.ris`(Zotero/EndNote)、`needs-review.md`、`rejected.md`、`obsidian/`。身份(id/title/year)取自验证门，富化只补不覆盖；摘要按 OpenAlex→CrossRef→arXiv 兜底抓取(缺则标"摘要不可得")；citekey 转 ASCII、作者 ` and ` 分隔、空档也生成空态文件。输入侧 taxonomy/sota/seeds/code/overrides 缺省时报告明示"未提供"，不降级。`--overrides` 按 slug→doi→arxiv→id 命中，`bibtype` 只改导出类型不动源 `work_type`。
**论文总结**：由 agent(extractor/positioning) **基于抓取到的真实摘要/全文**逐篇写总结，存 `summaries.json`(slug→中文总结)，经 `--summaries` 注入 report 的"论文总结"段；摘要不可得的篇目须如实标注、不编造。
**交付前必跑校验门**：`scripts/check_outputs.py --verdict verdict.json --out <dir> [--mode landscape|positioning|seed|tracking]`，校验三档计数一致、year 无漂移、citekey ASCII、标题不截断、引用边不冒充谱系、撤稿已显式告警、trust 字段齐备等；`--mode` 额外校验该模式招牌产物（landscape 查 Taxonomy/SOTA/种子；positioning 查定位章节+slug 属 confirmed；seed 查同心圆；tracking 查 digest）；非 0 退出即不得交付。
**输出人设（去 AI 味）**（见 `references/voice.md`）：报告里的散文（总结/gap/定位/流派思路/Related Work）由 agent 写，统一走"同领域资深同门"人设 + 两种语域（**笔记体**默认进 report.md；**投稿体**可选进 `survey-draft.md`，能直接粘进综述/论文，只引 verified.bib 的 citekey）。写散文前 agent 先读 voice.md；风格只改"怎么说"，事实仍守 0 幻觉。`scripts/check_voice.py` 扫 AI 套话（WARN）并硬校验 survey 草稿的行内引用（`\cite{}` 或 `[citekey]` 两种格式，跳过代码块内的格式说明）必须命中 verified.bib（未核引用即 FAIL）；check_outputs 末尾自动调它。

**OS 针对性输出**（见 `references/output-templates.md`）：写文件前判定 OS；**Windows 强制 UTF-8（无 BOM）、脚本用 `python` 且 stdin/stdout reconfigure utf-8**，绝不依赖系统默认编码（否则中文/管道写坏）。

**可选导出**（见 `references/export-zotero-obsidian.md`）：.bib/.ris 给 Zotero/EndNote；Obsidian 笔记用 `cites::`/`cited-by::` 让 Graph View **默认渲染集合内引用图**，每条边有原文 evidence 才升级 `improves::` 方法谱系；MOC 按 taxonomy 分组。

## 通用流程骨架（各模式在此之上特化）

1. **圈定**：把模糊问题 → 可检索概念簇 + 同义词 + 关键作者/团队；与用户确认范围/年限/venue 偏好。记检索式/库/日期入 search-log（可复现）。
2. **扫**：派 `scout_agent`（多角度/多源，必要时并行），候选只来自工具返回。
3. **去重**：候选过 `scripts/dedup.py`（DOI 主键 + 标题作者兜底 + 预印本↔出版归并），消跨源重复再往下。
4. **扩**（按模式）：`citation_graph_agent` 前后向滚雪球（扩出的候选再过去重）。
5. **抽**：`extractor_agent` 逐篇结构化 + 取证据。
6. **核**：`verify_agent` → `verify_citations.py` 三档（带缓存）；review 灰区交 `adjudicate_agent` 扒原文裁决。
7. **合**：按模式产物模板合成（**只用 confirmed**）；模式①/④ 综合结果写 positioning/circles JSON。
8. **交付**：`build_outputs.py` 生成全部产物（含 trust 可信度层、search-strategy）→ `check_outputs.py --mode <模式>` 校验通过 → 才向用户报告三档计数 + needs-review 清单 + 撤稿/预印本告警。校验失败先修，不交付。

输出模板见 `references/output-templates.md`。
