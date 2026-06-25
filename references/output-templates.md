# 输出格式、数据流与 OS 规则

## 单一 canonical 数据流
```
verdict.json(验证门三档) ──┐
summaries/code_repos/taxonomy/sota/seeds/manual_overrides.json(agent 产出, 均可选) ──┤
                          ▼
              build_outputs.py  → corpus.json(canonical 唯一真相)
                          ▼ 全部由 corpus 派生, 杜绝漂移
   report.md · verified.bib · verified.ris · obsidian/(*.md + _MOC.md) · needs-review.md · rejected.md
                          ▼
              check_outputs.py [--mode landscape]  必须 ALL PASS 才交付
```
身份(id/title/year)取自 verdict；富化只补不覆盖。`manual_overrides.json` 按 **slug→doi→arxiv→id** 命中，`bibtype` 只改导出类型、不改源 `work_type`。

## OS 针对性输出（必守）
| 项 | Windows | macOS/Linux |
|---|---|---|
| 编码 | **强制 UTF-8（无 BOM）**，绝不依赖 cp936/GBK 默认 | UTF-8 |
| 脚本 stdout | `sys.stdout.reconfigure(encoding="utf-8")`（脚本已做） | 默认即可 |
| 解释器 | 用 `python`（部分 Windows 上 `python3` 是商店占位别名，静默失效） | `python3` 通常可用 |
| 路径 | 绝对 Windows 路径或 `$HOME`，勿硬编码 POSIX 路径 | - |

## 产物清单
| 文件 | 内容 |
|---|---|
| `corpus.json` | canonical 记录 + citation_edges + taxonomy/sota/seeds；含 enrich_match_score/enrichment_errors/code_meta/override_meta |
| `report.md` | At a glance + 必读种子 + Taxonomy + SOTA(定量/定性) + 关键工作卡片 + 引用图 + 代码可得性 + 富化告警 + 人工覆盖记录 + 完整标题对照 |
| `verified.bib` / `verified.ris` | **仅 confirmed**；Zotero/EndNote 导入；citekey ASCII、作者 ` and ` 分隔、含 AB 摘要(.ris)与 code note |
| `obsidian/<slug>.md` | 论文总结 + 来源证据 + `cites::`/`cited-by::` 引用图 + 代码段(带 source/official) |
| `obsidian/_MOC.md` | 研究地图：有 taxonomy 则按流派分组，`[[slug|短标题]] — 完整title`(不截断) |
| `needs-review.md` / `rejected.md` | 三档落档，空档也生成"无…条目" |
| `survey-draft.md`（可选） | survey_writer_agent 产出的投稿体 Related Work/综述草稿；行内 `\cite{citekey}` 只引 verified.bib；交付前 check_voice 硬校验每个 \cite 解析 |

## report.md 结构（At a glance + 卡片式）
- 头部一行 `> **At a glance** — N confirmed · M review · K rejected · X code · Y edges · Z 流派`
- **必读种子**(seeds, 带 role) → **Taxonomy**(方法重聚类) → **SOTA/能力对照**(定量指标表 + 定性能力证据表) → **关键工作卡片**(▸slug—完整title / 元数据行 / 总结 / 来源 / 代码 / DOI) → **集合内引用图**(cites) → **代码可得性** → **富化告警**(人话化) → **人工覆盖记录** → **完整标题对照**
- 缺 taxonomy/sota/seeds 输入 → 明示"未提供 X 输入"，**不降级成裸清单**。

## bibtype 选择
- 优先 `manual_overrides` 的 `bibtype`(人工导出修正)；否则读源 work_type；冲突时 venue 性质校正(Proceedings/Symposium/Conference/Workshop→inproceedings；Transactions/Journal→article)；都缺才 `@misc`。
- override 的 bibtype 不写回 `work_type`，corpus 里保留"源 type"与"导出修正"之分。

## 缺字段跨源兜底
- venue/year/authors/摘要 在主源缺 → 换源补(OpenAlex↔CrossRef↔DBLP↔arXiv)；仍无则留空/标注，**不占位猜测**。
- 标题检索兜底有相似度门(ENRICH_MATCH_MIN)，低分不采信、记 `enrichment_errors`，报告"富化告警"人话化呈现。

## 输入文件 schema（agent 产出，均可选）
- `summaries.json` `{slug:{summary, source_type, source_url_or_id, evidence, note}}`
- `code_repos.json` `{doi|arxiv|title-key:{url, source, official, stars, evidence}}`（无则全 none-found，不内置样例）
- `taxonomy.json` `[{family, idea, members:[slug], evidence}]`（方法重聚类，members 须 confirmed slug）
- `sota.json` `[{slug, method, dataset, metric, value, kind:"quantitative"|"qualitative", evidence, source}]`
- `seeds.json` `[{slug, role}]`（role 推荐 奠基/里程碑/方法基座/当前SOTA/直接竞品/最新近邻/必读）
- `manual_overrides.json` `{slug|doi|arxiv|id:{bibtype?, venue?, year?, work_type?, reason}}`
- `positioning.json`（模式①）`{contribution, neighbors:[{slug,diff,evidence}], gap, baselines:[{slug,why,metric}], must_cite:[{slug,role}], related_work_skeleton}`；slug 须 confirmed，diff/baseline 须可追到原文。
- `circles.json`（模式④）`{seed:{slug,title}, core/adjacent/peripheral:[{slug,relation,evidence,cited_by}]}`；中心度只记 API 真实被引，关系须带 evidence。
- `search_log.json` `{date, databases:[...], queries:[{db,cluster,string,hits}], inclusion:[...], exclusion:[...], counts:{found,after_dedup}}` → 生成 `search-strategy.md`（PRISMA 式计数，confirmed/review/rejected 由 verdict 派生）。

## Trust 可信度层（build_outputs 自动算，存在性之外）
每篇 corpus 记录带 `trust: {is_retracted, venue_type, peer_reviewed, citation_velocity, version_status}`：
- `venue_type` ∈ preprint/workshop/conference/journal/unknown（OpenAlex source.type 优先，venue 串兜底；dedup 的 `version_status` 表明有正式版时不冤判为 preprint）。
- report 出「可信度告警」：撤稿（禁作 baseline）+ 纯预印本（未评审）；`.bib` 给撤稿条目加 `RETRACTED` note；Obsidian frontmatter 带 `venue_type/peer_reviewed/retracted`（Dataview 可查）。
- check_outputs：撤稿必须在报告显式告警，trust 字段须齐备。
