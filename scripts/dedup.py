#!/usr/bin/env python
"""dedup.py — lit-scout 候选去重引擎（scout 之后、verify 之前过一遍）。

多源 scatter-gather(arXiv/CrossRef/OpenAlex/DBLP/S2/GitHub...) 必然产生跨源重复:
同一篇的 arXiv 预印本与正式出版版、带 DOI 与不带 DOI 的两条记录等。纯标题归一化
漏得厉害, 会污染引用图计数与 SOTA 表。本脚本做三件事:

  1) DOI 主键归并: 归一化 DOI 相同 -> 同一篇。
  2) 标题+作者兜底: 无 DOI 时, 标题 Jaccard >= 0.90 且第一作者姓氏一致 -> 同一篇。
  3) 预印本<->出版版本归并: 一条仅 arXiv、一条有 DOI, 标题高度相似且作者吻合 ->
     归并为一条, 保留 DOI(出版版优先)同时保留 arxiv id, 标 version_status。

合并优先级(选哪条做主记录): 元数据更全(DOI+venue+year) > 出版版优于预印本 > 被引更高。
被合并的次记录的非空字段用来补主记录缺失字段(不覆盖)。

只用标准库。输入 stdin 或 --in 一个 JSON 数组, 每项至少含 title, 可含
authors/year/doi/arxiv/venue/source/cited_by_count 等。输出 JSON:
  {"deduped": [...], "merge_log": [{"kept": "...", "merged": ["..."], "rule": "doi|title-author|preprint-published"}]}
"""
import sys, json, re, argparse
from difflib import SequenceMatcher

_STOP = {"a", "an", "the", "in", "of", "for", "on", "to", "and", "with", "by",
         "et", "al", "via", "from", "using", "based"}


def norm_doi(d):
    if not d:
        return ""
    d = str(d).strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d.strip()


def norm_arxiv(a):
    if not a:
        return ""
    a = str(a).strip().lower()
    a = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", a)
    a = re.sub(r"v\d+$", "", a)        # 去版本后缀 v1/v2
    return a.strip()


def norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_tokens(t):
    return {w for w in norm_title(t).split() if w not in _STOP}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def seq_ratio(a, b):
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def first_author_surname(authors):
    """authors 可能是 list 或 'A and B' / 'A; B' / 'Last, First' 字符串。取第一作者姓氏。"""
    if not authors:
        return ""
    if isinstance(authors, list):
        first = authors[0] if authors else ""
    else:
        first = re.split(r"\band\b|;|/", str(authors))[0]
    first = first.strip()
    if not first:
        return ""
    if "," in first:                      # "Last, First"
        return first.split(",")[0].strip().lower()
    return first.split()[-1].strip().lower()  # "First Last" -> Last


def metadata_score(r):
    """越全越优先做主记录。"""
    s = 0
    if norm_doi(r.get("doi")):
        s += 4
    if r.get("venue"):
        s += 2
    if r.get("year"):
        s += 1
    if r.get("authors"):
        s += 1
    return s


def is_published(r):
    return bool(norm_doi(r.get("doi"))) and not _arxiv_only(r)


def _arxiv_only(r):
    return bool(norm_arxiv(r.get("arxiv"))) and not norm_doi(r.get("doi"))


def cited(r):
    try:
        return int(r.get("cited_by_count") or r.get("cited") or 0)
    except (TypeError, ValueError):
        return 0


def prefer(a, b):
    """返回 (主, 次): 元数据更全 > 出版版 > 被引更高。"""
    for key in (metadata_score, lambda r: 1 if is_published(r) else 0, cited):
        ka, kb = key(a), key(b)
        if ka != kb:
            return (a, b) if ka > kb else (b, a)
    return a, b


def merge_into(main, other):
    """次记录非空字段补主记录缺失字段(不覆盖已有)。保留两边 id 与来源。"""
    for k, val in other.items():
        if k in ("source", "source_query"):
            continue
        if val in (None, "", [], {}) :
            continue
        if main.get(k) in (None, "", [], {}):
            main[k] = val
    # 保留两边 id: 预印本<->出版归并时主记录可能缺 arxiv 或 doi
    if not norm_doi(main.get("doi")) and norm_doi(other.get("doi")):
        main["doi"] = other["doi"]
    if not norm_arxiv(main.get("arxiv")) and norm_arxiv(other.get("arxiv")):
        main["arxiv"] = other["arxiv"]
    # 合并来源痕迹
    srcs = []
    for r in (main, other):
        s = r.get("source")
        if s:
            srcs += s if isinstance(s, list) else [s]
    if srcs:
        main["source"] = sorted(set(srcs))
    return main


def same_paper(a, b):
    """返回 (是否同篇, rule)。"""
    da, db = norm_doi(a.get("doi")), norm_doi(b.get("doi"))
    if da and db:
        return (da == db, "doi")
    aa, ab = norm_arxiv(a.get("arxiv")), norm_arxiv(b.get("arxiv"))
    if aa and ab and aa == ab:
        return True, "arxiv"
    # 标题+作者兜底
    ta, tb = title_tokens(a.get("title")), title_tokens(b.get("title"))
    jac = jaccard(ta, tb)
    seq = seq_ratio(a.get("title"), b.get("title"))
    title_match = jac >= 0.90 or seq >= 0.93
    if not title_match:
        return False, ""
    sa, sb = first_author_surname(a.get("authors")), first_author_surname(b.get("authors"))
    author_ok = (not sa or not sb) or (sa == sb)   # 缺作者时只凭标题(保守: 仍需高相似)
    if not author_ok:
        return False, ""
    # 预印本<->出版: 一条 arxiv-only, 一条有 doi
    if _arxiv_only(a) != _arxiv_only(b) and (da or db):
        return True, "preprint-published"
    return (jac >= 0.90 or seq >= 0.93), "title-author"


def dedup(items):
    clusters = []   # 每簇: {"main": rec, "members": [rec...], "rule": str}
    for it in items:
        placed = False
        for cl in clusters:
            ok, rule = same_paper(cl["main"], it)
            if ok:
                main, _ = prefer(cl["main"], it)
                merge_into(main, it if main is cl["main"] else cl["main"])
                cl["main"] = main
                cl["members"].append(it)
                if rule == "preprint-published" or cl["rule"] == "preprint-published":
                    cl["rule"] = "preprint-published"
                elif cl["rule"] == "doi" or rule == "doi":
                    cl["rule"] = "doi"
                else:
                    cl["rule"] = rule or cl["rule"]
                placed = True
                break
        if not placed:
            clusters.append({"main": dict(it), "members": [it], "rule": ""})
    deduped, log = [], []
    for cl in clusters:
        m = cl["main"]
        if cl["rule"] == "preprint-published" or (norm_doi(m.get("doi")) and norm_arxiv(m.get("arxiv"))):
            m["version_status"] = "published(有正式版+预印本)"
        elif _arxiv_only(m):
            m["version_status"] = "preprint-only(仅预印本)"
        elif norm_doi(m.get("doi")):
            m["version_status"] = "published"
        deduped.append(m)
        if len(cl["members"]) > 1:
            log.append({"kept": m.get("title", "")[:80],
                        "merged": [x.get("title", "")[:80] for x in cl["members"][1:]],
                        "rule": cl["rule"] or "title-author"})
    return {"deduped": deduped, "merge_log": log,
            "stats": {"in": len(items), "out": len(deduped), "merged": len(items) - len(deduped)}}


def main():
    try:  # 管道进来的非 ASCII 标题须按 utf-8 读, 否则 Windows cp936 会读坏
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp")
    a = ap.parse_args()
    raw = open(a.inp, encoding="utf-8").read() if a.inp else sys.stdin.read()
    items = json.loads(raw)
    json.dump(dedup(items), sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
