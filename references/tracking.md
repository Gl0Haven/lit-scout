# 模式③ 持续追踪

目标：定期追某主题/作者/venue 的新论文，过滤相关性，产出按日 digest + 阅读队列。适合长期盯一个方向。

## 状态文件
`lit-scout-out/<watch-name>/watchlist.yaml`（模板见 assets/watchlist.example.yaml）：
```yaml
name: my-topic
topics: ["diffusion model image super-resolution", "latent diffusion image restoration"]
authors: []
venues: ["<相关期刊/顶会>", "arXiv <分类>"]
last_checked: 2026-06-15      # 每次跑完更新
min_relevance: 0.6
```
`reading-queue.md` — 累积的待读队列（带状态：todo/reading/done）。

## 流程
1. 读 watchlist，取 `last_checked` 之后的新文：`scout_agent` 按 topics/authors，arXiv 用 since-date 列表。候选只来自检索。
2. `relevance_filter_agent` 逐篇按 topics 打分 + 给理由；< min_relevance 的丢入 `skipped`（保留可回看，不静默删）。
3. 保留项：`extractor_agent` 取一句话要点 + GitHub code_repo；`verify_agent`/`adjudicate` 核验。
4. **累积产出**：`build_outputs.py --verdict <本窗口verdict> --out <watch-dir> --merge-corpus <watch-dir>/corpus.json`。
   `--merge-corpus` 把上次 corpus 的 confirmed 并入本次（按 doi/arxiv/slug 去重），**不丢历史笔记**；
   report 自动出「本次新增（digest）」段（标 N 篇新确认 / 累积 M 篇）。confirmed 追加进 `reading-queue.md`；更新 `last_checked`。
   > 注意：build_outputs 是全量重写 out 目录，**必须用 `--merge-corpus` 才能累积**；否则每次只剩本窗口的几篇。
   > 交付校验用 `check_outputs.py --mode tracking`（查 digest 段存在）。

**增量、不重复劳动**：本窗口只 scout/verify**新检索到的候选**即可——验证门的持久缓存
（`verification_cache.py`，TTL 90 天）会让任何与历史重叠的论文跳过联网核验，`--merge-corpus`
再把历史 confirmed 并回来。所以追踪是天然增量的：每周只为真正的新文付检索/核验成本。
可把整套挂到 `/schedule` 上自动周更。

## 产物 digest（report.md 追加）
```markdown
## 新文 digest — 2026-06-15（自 2026-06-08）
- [confirmed] "Title" (arXiv 2406.xxxxx) — 为何看：与 watchlist 主题相关，提了X | code: github…
- [skipped] "Title" — 相关性 0.3：偏硬件实现，与当前方向弱相关
```

## 自动化
可挂 `/schedule`（cron 云端）或 `/loop`（本地间隔）定期跑本模式。频率建议每周；arXiv 增量小，避免每天满窗。

## 守则
0 幻觉铁律；skipped 不删；last_checked 只在成功跑完后更新，避免漏窗。
