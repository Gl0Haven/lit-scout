#!/usr/bin/env python
"""verify_citations.py — lit-scout 的确定性验证门（0 幻觉硬门）。

输入: stdin 或 --in 给一个 JSON 数组, 每项:
    {"title": "...", "authors": "可选", "year": 2021, "doi": "可选", "arxiv": "可选"}
输出: stdout 一个 JSON:
    {"confirmed": [ {...原字段, "title", "resolved_doi"/"resolved_arxiv", "match_title", "year", "score", "source"} ],
     "review": [ {...原字段, "reason"/"note": "..."} ],
     "rejected": [ {...原字段, "reason": "..."} ]}

规则(与 SKILL.md 的 0 幻觉铁律一致):
  1) 必须解析出真实 id (DOI 或 arXiv);
  2) 查回标题与所声称标题归一化后相似度 >= THRESHOLD (默认 0.92), 防张冠李戴;
  3) id 解析失败但标题能多源兜底时保留兜底结果; 无法判定 -> review, 绝不放行.
离线/查询失败 -> 该条进 review(fail-safe, 永不臆造).

只用标准库(urllib/json/difflib), 无第三方依赖, Windows 可直接 `python verify_citations.py`.
"""
import sys, json, re, time, argparse, ssl, urllib.parse, urllib.request
from difflib import SequenceMatcher


def _build_ssl_ctx():
    """默认 SSL 上下文在 Windows/python.org 版常缺 CA, 导致 arXiv 等严格链站点
    CERTIFICATE_VERIFY_FAILED。优先用系统证书(truststore), 退 certifi, 再退默认。"""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


CTX = _build_ssl_ctx()

THRESHOLD = 0.92   # >= 此分: confirmed(可直接用)
REVIEW_LOW = 0.80  # [REVIEW_LOW, THRESHOLD): needs-review(保留并待人工确认, 绝不静默删除)
                   # < HARD_REJECT_LOW: rejected; 中间区间仅在查询源失败时 review
HARD_REJECT_LOW = 0.50  # 明显低相似度: 即使部分非关键源失败也隔离, 避免 review 被垃圾候选淹没
UA = {"User-Agent": "lit-scout-verify/0.1 (academic use)"}
TIMEOUT = 20
QUERY_ERRORS = []


def reset_query_errors():
    del QUERY_ERRORS[:]


def record_query_error(source, exc):
    msg = str(exc).replace("\n", " ")[:160]
    QUERY_ERRORS.append({"source": source, "error": f"{type(exc).__name__}: {msg}"})


def parse_year(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def append_note(info, text):
    if info.get("note"):
        info["note"] += "; " + text
    else:
        info["note"] = text


def add_year_info(info, claimed, resolved_year):
    """Use source-resolved year in outputs; preserve a conflicting input year for audit."""
    ry = parse_year(resolved_year)
    if ry is None:
        return info
    info["year"] = ry
    cy = parse_year(claimed.get("year"))
    if cy is not None and cy != ry:  # 任何差异(含差1年)都留痕供审计
        info["input_year"] = claimed.get("year")
        append_note(info, f"输入年份 {claimed.get('year')} 与检索年份 {ry} 不一致({'差>1年' if abs(cy-ry)>1 else '差1年'}), 已采用检索年份")
    return info


def use_match_title(info):
    if info.get("match_title"):
        info["title"] = info["match_title"]
    return info


def norm(s):
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sim(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    r = SequenceMatcher(None, na, nb).ratio()
    # 标题含副标题: 一方是另一方子串(且够长, 防短标题误撞) -> 视为同篇
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 15 and short in long:
        r = max(r, 0.95)
    return r


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def crossref_by_doi(doi):
    try:
        j = json.loads(_get("https://api.crossref.org/works/" + urllib.parse.quote(doi)))
        msg = j.get("message", {})
        t = (msg.get("title") or [""])[0]
        y = (msg.get("issued", {}).get("date-parts", [[None]]) or [[None]])[0][0]
        return ("doi", doi, t, y) if t else None
    except Exception as e:
        record_query_error("crossref/doi", e)
        return None


def crossref_by_title(title, year=None):
    try:
        url = "https://api.crossref.org/works?rows=5&query.bibliographic=" + urllib.parse.quote(title)
        items = json.loads(_get(url)).get("message", {}).get("items", [])
        best = None
        for it in items:
            t = (it.get("title") or [""])[0]
            doi = it.get("DOI")
            if not t or not doi:
                continue
            sc = sim(title, t)
            # 年份佐证: 给了 year 但与查回年份不符则重罚, 压住近似标题孪生
            iy = (it.get("issued", {}).get("date-parts", [[None]]) or [[None]])[0][0]
            if year:
                if iy and abs(int(iy) - int(year)) > 1:
                    sc -= 0.15
            if best is None or sc > best[3]:
                best = ("doi", doi, t, sc, iy)
        return best  # (kind, id, match_title, score) or None
    except Exception as e:
        record_query_error("crossref/title", e)
        return None


def arxiv_lookup(title=None, arxiv_id=None):
    try:
        if arxiv_id:
            q = "id_list=" + urllib.parse.quote(arxiv_id)
        else:
            q = "search_query=ti:%22" + urllib.parse.quote(title) + "%22&max_results=5"
        xml = _get("http://export.arxiv.org/api/query?" + q)
        entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
        best = None
        for e in entries:
            mt = re.search(r"<title>(.*?)</title>", e, re.S)
            mi = re.search(r"<id>(.*?)</id>", e, re.S)
            my = re.search(r"<published>(\d{4})-", e, re.S)
            if not mt or not mi:
                continue
            t = re.sub(r"\s+", " ", mt.group(1)).strip()
            aid = mi.group(1).strip().rsplit("/abs/", 1)[-1]
            y = int(my.group(1)) if my else None
            sc = 1.0 if arxiv_id else sim(title, t)
            if best is None or sc > best[3]:
                best = ("arxiv", aid, t, sc, y)
        return best
    except Exception as e:
        record_query_error("arxiv", e)
        return None


def openalex_by_title(title, year=None):
    """OpenAlex 兜底: 覆盖 CrossRef/arXiv 都没有但 OpenAlex 收录的论文(补 recall)。"""
    try:
        url = "https://api.openalex.org/works?per-page=5&filter=title.search:" + urllib.parse.quote(title)
        res = json.loads(_get(url)).get("results", [])
        best = None
        for w in res:
            t = w.get("display_name") or ""
            if not t:
                continue
            sc = sim(title, t)
            py = w.get("publication_year")
            if year:
                if py and abs(int(py) - int(year)) > 1:
                    sc -= 0.15
            doi = w.get("doi")
            if doi:
                kind, ident = "doi", doi.replace("https://doi.org/", "")
            else:
                kind, ident = "openalex", w.get("id", "")
            if best is None or sc > best[3]:
                best = (kind, ident, t, sc, py)
        return best
    except Exception as e:
        record_query_error("openalex/title", e)
        return None


def dblp_by_title(title, year=None):
    """DBLP: CS/IEEE/ACM 覆盖极全, 免 key, 对计算机/工程类 venue 命中率高。"""
    try:
        url = "https://dblp.org/search/publ/api?format=json&h=5&q=" + urllib.parse.quote(title)
        hits = json.loads(_get(url)).get("result", {}).get("hits", {}).get("hit", [])
        best = None
        for h in hits:
            info = h.get("info", {})
            t = (info.get("title") or "").rstrip(".")
            if not t:
                continue
            sc = sim(title, t)
            if year and info.get("year"):
                try:
                    if abs(int(info["year"]) - int(year)) > 1:
                        sc -= 0.15
                except ValueError:
                    pass
            doi = info.get("doi")
            kind, ident = ("doi", doi) if doi else ("dblp", info.get("key", ""))
            if best is None or sc > best[3]:
                best = (kind, ident, t, sc, parse_year(info.get("year")))
        return best
    except Exception as e:
        record_query_error("dblp/title", e)
        return None


def s2_by_title(title, year=None):
    """Semantic Scholar: 广覆盖 + 引用图。无 key 时限流严, 失败即跳过(fail-safe)。"""
    try:
        url = ("https://api.semanticscholar.org/graph/v1/paper/search?limit=5&fields=title,year,externalIds&query="
               + urllib.parse.quote(title))
        data = json.loads(_get(url)).get("data", [])
        best = None
        for p in data:
            t = p.get("title") or ""
            if not t:
                continue
            sc = sim(title, t)
            if year and p.get("year") and abs(int(p["year"]) - int(year)) > 1:
                sc -= 0.15
            ext = p.get("externalIds") or {}
            if ext.get("DOI"):
                kind, ident = "doi", ext["DOI"]
            elif ext.get("ArXiv"):
                kind, ident = "arxiv", ext["ArXiv"]
            else:
                kind, ident = "s2", p.get("paperId", "")
            if best is None or sc > best[3]:
                best = (kind, ident, t, sc, parse_year(p.get("year")))
        return best
    except Exception as e:
        record_query_error("semanticscholar/title", e)
        return None


def title_candidates(title, year=None):
    return [r for r in (crossref_by_title(title, year),
                        arxiv_lookup(title=title),
                        openalex_by_title(title, year),
                        dblp_by_title(title, year),
                        s2_by_title(title, year)) if r]


def classify_title_candidates(c, cands):
    if not cands:
        if QUERY_ERRORS:
            return "review", {"reason": "检索无命中或查询失败, 需复核后再判定",
                              "query_errors": QUERY_ERRORS[:5],
                              "note": "查询源异常时不可当作不存在删除"}
        return "rejected", {"reason": "检索无命中 (疑似不存在或检索失败)"}
    cands.sort(key=lambda x: -x[3])
    best = cands[0]
    key = "resolved_" + best[0]  # resolved_doi / resolved_arxiv / resolved_openalex / resolved_dblp / resolved_s2
    info = {key: best[1], "match_title": best[2], "score": round(best[3], 3), "source": best[0]}
    add_year_info(info, c, best[4] if len(best) > 4 else None)
    # year_sources: 各源给出的年份, 暴露多源年份分歧供审计
    ys = sorted({a[4] for a in cands if len(a) > 4 and a[4]})
    if len(ys) > 1:
        info["year_sources"] = [{"source": a[0], "year": a[4]} for a in cands if len(a) > 4 and a[4]]
        append_note(info, f"多源年份分歧: {ys}")
    alts = [{"id": a[1], "title": a[2], "year": a[4] if len(a) > 4 else None, "score": round(a[3], 3)}
            for a in cands[1:] if best[3] - a[3] < 0.1]
    if alts:
        info["alternatives"] = alts  # 近分备选, 供人工消歧
    if best[3] >= THRESHOLD:
        use_match_title(info)
        return "confirmed", info
    if best[3] >= REVIEW_LOW:
        info["note"] = "相似度处于待确认区间, 请人工确认是否同一篇(勿静默丢弃)"
        return "review", info
    if QUERY_ERRORS and best[3] >= HARD_REJECT_LOW:
        info["note"] = "最佳匹配相似度过低, 但部分查询源失败; 需复核后再判定"
        info["query_errors"] = QUERY_ERRORS[:5]
        return "review", info
    return "rejected", {"reason": f"最佳匹配相似度过低 (score={best[3]:.2f}): 查回='{best[2]}'"}


def verify_one(c):
    """返回 (tier, info), tier ∈ {confirmed, review, rejected}。
    原则: id 解析成功的一律不 reject(真实存在), 元数据不吻合则降为 review 交人工;
    仅标题且无命中/相似度过低才 rejected。绝不静默丢弃灰区。"""
    reset_query_errors()
    title = c.get("title", "")
    # 1) 已给 id: 按 id 确认(溯源优先, 真论文不会被杀)
    if c.get("doi"):
        r = crossref_by_doi(c["doi"])
        if r:
            sc = sim(title, r[2]) if title else 1.0
            info = {"resolved_doi": r[1], "match_title": r[2], "score": round(sc, 3), "source": "crossref/doi"}
            add_year_info(info, c, r[3] if len(r) > 3 else None)
            if sc >= THRESHOLD:
                use_match_title(info)
                return "confirmed", info
            append_note(info, "DOI 解析成功但标题不完全吻合, 请人工确认是否同一篇")
            return "review", info
        if title:
            tier, info = classify_title_candidates(c, title_candidates(title, c.get("year")))
            info.update({"doi": "", "input_doi_unresolved": c["doi"]})
            if tier == "confirmed":
                info["note"] = "输入 DOI 无法解析, 已按标题从其他源解析出真实 id; 不沿用原 DOI"
            elif tier == "review":
                info["note"] = "输入 DOI 无法解析, 标题兜底仍需复核; 不沿用原 DOI"
            return tier, info
        return "review", {"doi": "", "input_doi_unresolved": c["doi"],
                          "reason": "DOI 无法解析且无 title 可兜底, 需复核",
                          "query_errors": QUERY_ERRORS[:5]}
    if c.get("arxiv"):
        r = arxiv_lookup(arxiv_id=c["arxiv"])
        if r:
            sc = sim(title, r[2]) if title else 1.0
            info = {"resolved_arxiv": r[1], "match_title": r[2], "score": round(sc, 3), "source": "arxiv/id"}
            add_year_info(info, c, r[4] if len(r) > 4 else None)
            if sc >= THRESHOLD:
                use_match_title(info)
                return "confirmed", info
            append_note(info, "arXiv id 解析成功但标题不完全吻合, 请人工确认是否同一篇")
            return "review", info
        # arXiv 查询失败(常见: arXiv API 限流 1req/3s 偶发超时): 与 DOI 分支对称, 用标题从
        # 其他源(OpenAlex/CrossRef/DBLP/S2)兜底解析, 避免真论文因单源抖动被卡在 review。
        if title:
            tier, info = classify_title_candidates(c, title_candidates(title, c.get("year")))
            info["unresolved_arxiv"] = c["arxiv"]
            if tier == "confirmed":
                info["note"] = "arXiv id 查询失败, 已按标题从其他源解析出真实 id"
            elif tier == "review":
                info["note"] = "arXiv id 查询失败, 标题兜底仍需复核"
            return tier, info
        return "review", {"unresolved_arxiv": c["arxiv"],
                          "reason": "arXiv id 无法解析或查询失败且无 title 可兜底, 需复核",
                          "query_errors": QUERY_ERRORS[:5]}
    # 2) 仅标题 -> 多源取候选, 三档分流, 撞孪生列备选交消歧
    if not title:
        return "rejected", {"reason": "无 title 也无 id, 无法核验"}
    return classify_title_candidates(c, title_candidates(title, c.get("year")))


def main():
    global THRESHOLD
    try:  # Windows 控制台/管道默认非 utf-8, 强制之: stdin 避免管道进来的非 ASCII 标题被 cp936 读坏,
          # stdout/stderr 避免中文 reason 乱码/写坏
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--sleep", type=float, default=0.5, help="每条间隔, 礼貌限流")
    ap.add_argument("--no-cache", action="store_true", help="禁用持久化验证缓存")
    ap.add_argument("--cache", help="缓存 db 路径(默认 ~/.cache/lit-scout 或 $LIT_SCOUT_CACHE)")
    a = ap.parse_args()
    THRESHOLD = a.threshold
    # 持久化缓存: 同一篇跨运行只核验一次; 缓存不可用时静默降级, 不影响正确性
    cache = None
    try:
        from verification_cache import Cache, make_key
        cache = Cache(path=a.cache, enabled=not a.no_cache)
    except Exception:
        cache = None
    raw = open(a.inp, encoding="utf-8").read() if a.inp else sys.stdin.read()
    items = json.loads(raw)
    buckets = {"confirmed": [], "review": [], "rejected": []}
    n_cached = 0
    for c in items:
        key = make_key(c, THRESHOLD) if cache and cache.enabled else None
        hit = cache.get(key) if key else None
        if hit:
            tier, info = hit
            info = {**info, "from_cache": True}
            n_cached += 1
        else:
            tier, info = verify_one(c)
            if key:
                cache.put(key, tier, info)
            time.sleep(a.sleep)   # 仅真正联网时礼貌限流; 命中缓存不 sleep
        buckets[tier].append({**c, **info})
    if cache and cache.enabled and n_cached:
        sys.stderr.write(f"[verify] {n_cached}/{len(items)} 条命中验证缓存(跳过联网)\n")
    json.dump(buckets, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
