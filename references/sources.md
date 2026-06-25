# 检索源与各模式索引

## 检索源
| 源 | 用途 | 接入 | 备注 |
|---|---|---|---|
| arXiv | ML/CV/EE 主战场、预印本 | `http://export.arxiv.org/api/query`（verify 脚本已用）/ WebSearch | 标题精确检索用 `ti:"..."` |
| CrossRef | DOI 解析、正式发表元数据 | `https://api.crossref.org/works`（脚本已用） | 礼貌限流，带 UA |
| OpenAlex | 引用图、机构/作者、引用数 | `https://api.openalex.org/works` | **已接入 verify_citations.py**(标题兜底核验)；也供 citation_graph_agent |
| Semantic Scholar | 前后向引用、TLDR、广覆盖 | Graph API | **已接入 verify**；无 key 限流严, 失败即跳过 |
| DBLP | CS/IEEE/ACM 书目(计算机/工程命中率最高) | `dblp.org/search/publ/api` | **已接入 verify**；免 key、稳 |
| consensus | 主张级证据检索 | 可选 MCP（连了才用） | 环境相关：未连接则自动跳过、不影响其余源；用其返回的真实论文，遵守其引用格式要求 |
| **GitHub** | **论文级代码/复现仓库** | GitHub 搜索 API `api.github.com/search/repositories` 或 WebSearch | 见下"论文级代码检索" |
| Papers with Code | 论文↔代码↔SOTA 榜 | WebFetch/WebSearch | 补充代码与 benchmark 链接 |
| WebFetch/WebSearch | 落地页/PDF/补漏 | 内置 | 仅作补充，仍须过验证门 |

## 论文级代码检索（GitHub / Papers with Code）
agent 对每篇 confirmed 检索其官方/社区实现，把结果写成 `code_repos.json` 喂给 `build_outputs.py --code-repos`：
1. 检索关键词：论文标题、方法名/缩写、`作者 + 年`；优先 Papers with Code 的官方链接。
2. 排序：官方(作者本人/机构) > 最高 star > 最新维护。
3. **grounding**：repo URL 必须真实可解析（检索返回的，不臆造）；找不到该篇就**不写进 code_repos.json**，build_outputs 自动记 `none-found`。
4. **build_outputs 不内置任何样例仓库**——`code_repos.json` 缺该篇则一律 `none-found`，杜绝硬编码领域样例。

`code_repos.json` 格式（键用 doi / arxiv / 标题关键词）：
```json
{"10.1109/CVPR.2016.90": {"url":"https://github.com/KaimingHe/deep-residual-networks","source":"PapersWithCode","official":true,"stars":6000,"evidence":"作者本人 repo, README 对应该论文"}}
```

> 所有源的返回都必须经 `verify_citations.py` 核验后才算数。检索/核验无法判定时进 `review`，明确不存在或相似度过低时进 `rejected`，不臆造。
>
> **多源汇总后、核验前先过 `scripts/dedup.py`**：DOI 主键 + 标题作者兜底 + 预印本↔出版归并，消跨源重复（同一篇的 arXiv 版与出版版、带/不带 DOI 两条），否则引用图与 SOTA 计数会被重复污染。

## 各模式详细流程（已实现）
- ① 论文定位 → `references/positioning.md`
- ② 主题地形图 → `references/landscape.md`
- ③ 持续追踪 → `references/tracking.md`
- ④ 种子扩展 → `references/seed-expansion.md`
- 输出格式 / OS 规则 → `references/output-templates.md`
