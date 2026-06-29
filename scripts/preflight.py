#!/usr/bin/env python
"""preflight.py — 批量核验/检索前的连通性自检（融合自 nature-academic-search）。

逐个探活 lit-scout 用到的检索源端点，报告可达性 + 可选 key/邮箱是否已设。
大批量(几十上百条)跑 verify/检索前先跑一遍，早发现网络/证书/限流问题，省得跑一半才失败。

  python scripts/preflight.py
退出码: 全部 T1 源可达 0; 有 T1 源不可达 1（T2/T3 不可达只 warn）。只用标准库。
"""
import sys, os, json, ssl, time, urllib.request

TIMEOUT = 15
UA = {"User-Agent": "lit-scout-preflight/0.1 (academic use)"}


def _ctx():
    try:
        import truststore; return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception: pass
    try:
        import certifi; return ssl.create_default_context(cafile=certifi.where())
    except Exception: return ssl.create_default_context()


CTX = _ctx()

# (名称, 层, 探活 url)
ENDPOINTS = [
    ("CrossRef", "T1", "https://api.crossref.org/works/10.1109/CVPR.2016.90"),
    ("arXiv", "T1", "http://export.arxiv.org/api/query?id_list=1706.03762"),
    ("OpenAlex", "T1", "https://api.openalex.org/works?per-page=1&filter=title.search:resnet"),
    ("DBLP", "T1", "https://dblp.org/search/publ/api?format=json&h=1&q=resnet"),
    ("SemanticScholar", "T2", "https://api.semanticscholar.org/graph/v1/paper/search?limit=1&fields=title&query=resnet"),
]


def probe(url, headers=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
            r.read(2048)
            return True, r.status, round((time.time() - t0) * 1000)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}", round((time.time() - t0) * 1000)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("== lit-scout 连通性自检 ==")
    s2_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    oa_mail = os.environ.get("OPENALEX_EMAIL")
    print(f"SSL 上下文: {'truststore' if 'truststore' in str(type(CTX)).lower() else 'certifi/默认'}")
    print(f"SEMANTIC_SCHOLAR_API_KEY: {'已设(高配额)' if s2_key else '未设(限流, 失败即跳过)'}")
    print(f"OPENALEX_EMAIL: {'已设(polite pool)' if oa_mail else '未设(默认池)'}\n")
    t1_down = []
    for name, tier, url in ENDPOINTS:
        hdr = {"x-api-key": s2_key} if (name == "SemanticScholar" and s2_key) else None
        ok, status, ms = probe(url, hdr)
        mark = "OK " if ok else "FAIL"
        print(f"  [{mark}] {tier} {name:<16} {ms:>5}ms  {status}")
        if not ok and tier == "T1":
            t1_down.append(name)
    if t1_down:
        print(f"\n⚠ T1 源不可达: {t1_down} —— 核验会大量落 review(fail-safe)。先查网络/代理/证书。")
        sys.exit(1)
    print("\n✓ T1 源全部可达，可以开跑。")
    sys.exit(0)


if __name__ == "__main__":
    main()
