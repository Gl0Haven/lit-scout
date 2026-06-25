---
name: verify_agent
description: 调用 verify_citations.py 确定性核验候选，分三档 confirmed/review/rejected（0 幻觉硬门）
---

# verify_agent

任务：把候选论文清单交给确定性脚本核验，**不靠自己判断真伪**。

步骤：
1. 把候选汇成 JSON 数组（含 title，及已知的 doi/arxiv/authors/year）。
2. 运行（用 `python`；部分 Windows 上 `python3` 是商店占位别名）：
   ```
   python <skill>/scripts/verify_citations.py --in candidates.json > verdict.json
   ```
   或管道：`type candidates.json | python verify_citations.py`（PowerShell）/ `cat ... | python ...`（bash）。
3. 读 `verdict.json`：三个桶 `confirmed[]` / `review[]` / `rejected[]`。confirmed 必须带 canonical `title`、resolved id、match_title、score，并在检索源提供时带真实 `year`；review 可能带 resolved id + match_title + score，也可能只有 unresolved id / query_errors / reason（表示脚本无法判定），还可能带 note 和 alternatives；rejected 带 reason。

铁律：
- **只有 confirmed 进入最终产物 / .bib / 导出**。
- **review 绝不静默丢弃**：先交 `adjudicate_agent` 扒原文按硬字段自动裁决（升 confirmed / 降 rejected，附扒回字段证据）；仍不决的写入 `needs-review.md`，连同 match_title、score、alternatives 举给用户消歧。这是避免错杀真论文的关键。
- rejected 写入 `rejected.md` 隔离清单，保留 reason。
- 脚本离线/限流报错时：相关条目按 review 处理（不可臆断存在、也不可当不存在删除），提示用户脚本未能联网。
- 向用户报告三档计数：confirmed N / review M（需你确认）/ rejected K，并列出 review 与 rejected 摘要。
