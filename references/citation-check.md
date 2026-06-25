# 模式⑤ 稿件引文核验

目标：吃用户**现成的参考文献列表**（`.bib`/`.ris`/`.tex`/`.txt`），逐条核验是否真实存在、
标题/年份是否对得上，产出"哪些可信、哪些需复核、哪些疑似不存在/编造"的核验报告。

> 与 nature-citation 的区别：nature-citation 是**往正文插**引用；本模式只**核验**用户已有引用的
> 存在性与一致性，是 lit-scout 验证门(verify_citations.py)的直接应用，**不改写稿件、不插引用**。

## 流程
1. **解析参考文献**：`scripts/parse_refs.py --in <refs.(bib|ris|tex|txt)>` → 候选 JSON
   （title/authors/year/doi/arxiv，带 `_src_key` 原 citekey；.tex/.txt 兜底解析标 `_partial`）。
   `.docx` 不直接解析（依赖脆弱），让用户先导出 `.bib` 或纯文本。
2. **过验证门**：候选 JSON → `verify_citations.py`（多源、三档、带持久缓存）。
   ```
   python scripts/parse_refs.py --in refs.bib | python scripts/verify_citations.py > verdict.json
   ```
3. **裁决灰区**：review 经 `adjudicate_agent` 扒原文按硬字段裁决；仍不决的举给用户。
4. **报告**：按 `_src_key` 对回原稿，逐条给状态：
   - `confirmed` ✓ 真实存在、元数据吻合（附 resolved DOI/arXiv）；
   - `needs-review` ⚠ 强但不完美（标题孪生/年份偏差/DOI 解析但标题略偏）——指出疑点，**不删**；
   - `rejected` ✗ 检索无命中或相似度过低（**疑似不存在或编造**，是稿件最该查的）。

## 产物 report.md
```markdown
# 稿件引文核验 — <稿件名>

> N 条引用：confirmed C · needs-review R · rejected K（疑似不存在/编造）

## ✗ 疑似不存在 / 编造（rejected，优先处理）
- `[vaswani2017b]` "<标题>" — 检索五源无命中；请核对是否笔误或编造

## ⚠ 需复核（needs-review）
- `[he2016]` "<标题>" — DOI 解析成功但标题略偏；查回标题 "<...>"；确认是否同一篇

## ✓ 已确认（confirmed）
- `[resnet]` "<标题>" — DOI 10.1109/... · 标题/年份吻合
```

## 守则
- 0 幻觉铁律照旧：只信检索返回；rejected 只说"疑似"，不替用户断定一定是编造（可能是冷门/笔误）。
- 按 `_src_key` 对回原 citekey，方便用户定位修改，但**不替用户改稿**。
- `.tex/.txt` 兜底解析的 `_partial` 条目可靠性低，报告中标注"解析不全，建议补 DOI 后复核"。
- 大批量（>30 条）时验证缓存自动生效，重复核验同一篇不再联网。
