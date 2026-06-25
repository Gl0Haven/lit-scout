---
name: seed_parser
description: 解析种子论文的元数据 + 参考文献列表，作为引用图扩展起点
---

# seed_parser

任务：从用户给的种子论文（PDF 路径 / arXiv id / DOI / 落地页）抽取元数据与参考文献。

步骤：
1. 拿到全文/落地页（本地 PDF 用 Read；arXiv/DOI 用 WebFetch 或对应 API）。
2. 抽种子元数据：title/authors/year/venue/doi/arxiv。
3. 抽参考文献列表（尽量带 title/作者/年；能解析到 DOI/arXiv 更好）。

输出 JSON：
```json
{"seed":{"title":"","authors":[],"year":0,"doi":"","arxiv":""},
 "references":[{"title":"","year":0,"doi":"","arxiv":""}]}
```
铁律：
- 参考文献只从种子真实文本抽，**不补全模型记得的引用**；抽不全就标 partial。
- 解析不到全文（付费墙）时如实说明，仅用可得的摘要/落地页信息。
