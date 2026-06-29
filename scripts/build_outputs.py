#!/usr/bin/env python
"""build_outputs.py — lit-scout 单一 canonical 数据流导出器。

输入: verify_citations.py 产出的 verdict.json (confirmed/review/rejected 三档)。
输出 (全部从同一份 canonical 记录派生, 杜绝 verdict->corpus->bib/report 漂移):
  corpus.json, report.md, verified.bib, verified.ris, needs-review.md, rejected.md,
  obsidian/<slug>.md + obsidian/_MOC.md
  可选: search-strategy.md(--search-log)。报告含 trust 可信度层(撤稿/评审层/引用热度)。
  模式产物经 --positioning / --circles 注入; 追踪累积用 --merge-corpus。

canonical 原则:
  - 身份(id/title/year/score) 一律取自 verdict 的 confirmed 记录, 富化只**补**缺失字段, 绝不覆盖。
  - 引用关系仅来自 OpenAlex referenced_works, 诚实标为 "cites"(集合内引用图), **不**当作 builds-on/谱系
    (谱系需每条边带原文 evidence; 无 evidence 时只出引用图)。
  - 缺字段跨源兜底再留空; 摘要按句界截断; citekey 转 ASCII; 作者用 " and " 分隔, 不含 et al.。

用法: python build_outputs.py --verdict verdict.json --out <dir> --topic "<主题>"
"""
import sys, json, re, os, argparse, ssl, unicodedata, urllib.parse, urllib.request, datetime


def _ctx():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()


CTX = _ctx()
UA = {"User-Agent": "lit-scout-build/0.1"}
ENRICH_MATCH_MIN = 0.82  # 标题检索兜底的相似度门: 低于此不采信 enrichment(防写错元数据)
# 不内置任何领域样例代码仓库; 仓库须经 --code-repos 输入(来自 agent 的真实 GitHub/PwC 检索)


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25, context=CTX) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def ascii_key(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]", "", s) or "ref"


def short_title(t):
    """取冒号前主标题作短名(不硬切字符), 供 MOC/卡片 wikilink 别名。"""
    head = (t or "").split(":")[0].strip()
    return head if head else (t or "")


_STOP = {"a", "an", "the", "of", "for", "and", "on", "in", "to", "with", "from", "via"}


def make_slug(title, year):
    """稳定 slug: 仅由 canonical 标题+年确定性生成(不依赖会漂移的富化作者)。"""
    main = short_title(title)
    toks = [w for w in re.findall(r"[A-Za-z0-9]+", main) if w.lower() not in _STOP]
    base = "".join(toks[:2])[:24] if toks else "ref"
    return ascii_key(base) + str(year or "")


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def title_sim(a, b):
    from difflib import SequenceMatcher
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    r = SequenceMatcher(None, na, nb).ratio()
    short, lng = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 15 and short in lng:
        r = max(r, 0.95)
    return round(r, 3)


def first_sentence(text, limit=300):
    """按句界截断, 超长加省略号; 不在词中间硬切。"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    m = re.search(r"^(.*[.!?。])\s", cut)
    if m:
        return m.group(1)
    return cut.rsplit(" ", 1)[0] + " …"


def humanize_enrich(p):
    """把 enrichment_errors 工程日志转成给读者看的人话。"""
    errs = p.get("enrichment_errors") or []
    if not errs:
        return ""
    src = {"openalex/doi": "OpenAlex(按DOI)", "openalex/id": "OpenAlex(按id)",
           "openalex/title-search": "OpenAlex(标题检索)", "crossref/doi": "CrossRef(按DOI)"}
    failed = [src.get(e, e) for e in errs if not e.startswith("openalex/title-low")]
    low = [e for e in errs if e.startswith("openalex/title-low")]
    parts = []
    if failed:
        parts.append("查询失败: " + "、".join(failed))
    if low:
        parts.append("标题检索相似度过低未采信")
    miss = [n for n, v in (("venue", p.get("venue")), ("摘要", p.get("abstract")),
                           ("作者", p.get("authors"))) if not v]
    tail = f"；可能缺: {', '.join(miss)}" if miss else "；其余字段已由其他源补齐"
    return "；".join(parts) + tail


def abstract_from_inv(inv):
    if not inv:
        return ""
    pos = {}
    for w, ps in inv.items():
        for p in ps:
            pos[p] = w
    return " ".join(pos[i] for i in sorted(pos))


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def arxiv_abstract(arxiv_id):
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "http://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id),
                headers=UA), timeout=25, context=CTX) as r:
            xml = r.read().decode("utf-8", "replace")
        m = re.search(r"<entry>.*?<summary>(.*?)</summary>", xml, re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except Exception:
        return ""


def resolved_id(rec):
    for k in ("resolved_doi", "resolved_arxiv", "resolved_openalex", "resolved_dblp", "resolved_s2"):
        if rec.get(k):
            return k.replace("resolved_", ""), rec[k]
    return None, None


def classify_venue(p, w):
    """评审层判定: preprint / workshop / conference / journal / unknown。
    优先用 OpenAlex primary_location.source.type, 再用 venue 字符串兜底。"""
    v = (p.get("venue") or "").lower()
    loc = ((w or {}).get("primary_location") or {})
    st = ((loc.get("source") or {}).get("type") or "").lower()
    wtype = ((w or {}).get("type") or "").lower()
    if p.get("arxiv") and not p.get("doi"):
        return "preprint"
    if "arxiv" in v or st == "repository" or wtype == "preprint" or "preprint" in v:
        return "preprint"
    if "workshop" in v:
        return "workshop"
    if st == "conference" or any(k in v for k in ("proceedings", "conference", "symposium", "sigkdd")):
        return "conference"
    if st == "journal" or any(k in v for k in ("transactions", "journal", "access", "computers & security")):
        return "journal"
    if wtype in ("article", "journal-article", "proceedings-article"):
        return "conference" if wtype == "proceedings-article" else "journal"
    return "unknown"


def compute_trust(p, w):
    """可信度层(非存在性): 撤稿 / 评审层 / 引用热度 / 版本状态。
    只记检索源给出的事实, 判不准的留 unknown, 不臆断。"""
    venue_type = classify_venue(p, w)
    vs = p.get("version_status") or ""
    # dedup 已确认存在正式发表版时, 它对"是否经评审"更权威; 富化偶尔会误匹配到 arXiv 转贴
    if vs.startswith("published") and venue_type == "preprint":
        venue_type = "unknown"   # 已知有正式版但 venue 类型判不准, 不冤判为纯预印本
    peer_reviewed = {"journal": True, "conference": True, "workshop": True,
                     "preprint": False}.get(venue_type)  # unknown -> None
    if vs.startswith("published"):
        peer_reviewed = True
    velocity = None
    yr, cited = p.get("year"), p.get("cited")
    if yr and cited is not None:
        try:
            age = max(1, datetime.date.today().year - int(yr))
            velocity = round(int(cited) / age, 1)
        except (TypeError, ValueError):
            velocity = None
    # 期刊质量软信号(融合自 ARS 掠夺性筛查, 保守、不下"掠夺"定性以免误伤):
    # 仅当是 journal 且 OpenAlex 源既不在 DOAJ、又无 ISSN、且零被引时, 标"venue 元数据稀薄, 留意"。
    src = ((w or {}).get("primary_location") or {}).get("source") or {}
    venue_quality = None
    if venue_type == "journal" and w:
        in_doaj = bool(src.get("is_in_doaj"))
        has_issn = bool(src.get("issn") or src.get("issn_l"))
        if not in_doaj and not has_issn and (cited or 0) == 0:
            venue_quality = "thin"   # 元数据稀薄, 报告里软提示, 非"掠夺"指控
        elif in_doaj or has_issn:
            venue_quality = "indexed"
    return {
        "is_retracted": bool((w or {}).get("is_retracted")),
        "venue_type": venue_type,
        "peer_reviewed": peer_reviewed,
        "citation_velocity": velocity,        # 年均被引(影响力辅助信号)
        "venue_quality": venue_quality,       # indexed / thin / None(判不准)
        "version_status": p.get("version_status"),  # 来自 dedup 的预印本<->出版归并
    }


def enrich(rec, code_map=None):
    """补 authors/venue/work_type/abstract/refs/oaid/cited; 不覆盖 verdict 的 title/year/id。
    富化失败/低相似度不写错元数据, 记入 enrichment_errors。另算 trust 可信度层。"""
    code_map = code_map or {}
    kind, ident = resolved_id(rec)
    p = {
        "title": rec.get("title", ""),          # canonical: 来自 verdict
        "year": rec.get("year"),                # canonical: 来自 verdict
        "id_kind": kind, "id": ident,
        "doi": rec.get("resolved_doi", "") or (rec.get("doi", "") if rec.get("doi") else ""),
        "arxiv": rec.get("resolved_arxiv", ""),
        "score": rec.get("score"),
        # 年份审计: 透传验证门记录的 input_year / 年份说明
        "input_year": rec.get("input_year"),
        "year_note": rec.get("note") if (rec.get("note") and "年份" in str(rec.get("note"))) else None,
        "authors": [], "venue": "", "work_type": "", "cited": None,
        "oaid": None, "refs": [], "tldr": "", "abstract": "",
        "enrich_match_score": None, "enrichment_errors": [],
        "version_status": rec.get("version_status"),  # 来自 dedup(若跑过)
        "triangulation": rec.get("triangulation"),    # 来自验证门的跨索引一致性
    }

    def err(src):
        p["enrichment_errors"].append(src)

    w = None
    if kind == "doi":
        w = get("https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(ident))
        if not w:
            err("openalex/doi")
    elif kind == "openalex":
        w = get("https://api.openalex.org/works/" + ident)
        if not w:
            err("openalex/id")
    if not w and p["title"]:
        r = get("https://api.openalex.org/works?per-page=1&filter=title.search:" + urllib.parse.quote(p["title"]))
        cand = (((r or {}).get("results") or [None])[0]) if r else None  # results 可能是空 list, 不能用默认值兜
        if r is None:
            err("openalex/title-search")
        if cand:
            ms = title_sim(p["title"], cand.get("display_name", ""))
            p["enrich_match_score"] = ms
            if ms >= ENRICH_MATCH_MIN:   # 相似度门: 低分不采信, 留空
                w = cand
            else:
                err(f"openalex/title-low-match({ms})")
    if w:
        if p["enrich_match_score"] is None:
            p["enrich_match_score"] = 1.0  # 按 id 命中
        p["authors"] = [a["author"]["display_name"] for a in w.get("authorships", [])]
        p["venue"] = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "") or ""
        p["work_type"] = w.get("type", "") or ""
        p["cited"] = w.get("cited_by_count")
        p["oaid"] = w["id"].split("/")[-1]
        p["refs"] = [r.split("/")[-1] for r in w.get("referenced_works", [])]
        p["abstract"] = abstract_from_inv(w.get("abstract_inverted_index"))
        if not p["doi"] and w.get("doi"):
            p["doi"] = w["doi"].replace("https://doi.org/", "")
    # CrossRef 兜底 venue + work_type + abstract
    if (not p["venue"] or not p["work_type"] or not p.get("abstract")) and p["doi"]:
        cr = get("https://api.crossref.org/works/" + urllib.parse.quote(p["doi"]))
        if not cr:
            err("crossref/doi")
        if cr:
            m = cr.get("message", {})
            p["venue"] = p["venue"] or (m.get("container-title") or [""])[0]
            p["work_type"] = p["work_type"] or m.get("type", "")
            if not p.get("abstract"):
                p["abstract"] = strip_tags(m.get("abstract", ""))
    # arXiv 兜底 abstract: 直接 arxiv 篇, 或 DOI 篇有 arXiv 版(扫 OpenAlex locations)
    if not p.get("abstract") and p["arxiv"]:
        p["abstract"] = arxiv_abstract(p["arxiv"])
    if not p.get("abstract") and w:
        for loc in (w.get("locations") or []):
            u = (loc.get("landing_page_url") or "") + (loc.get("pdf_url") or "")
            m = re.search(r"arxiv\.org/(?:abs|pdf)/([\d.]+)", u)
            if m:
                p["abstract"] = arxiv_abstract(m.group(1))
                if p["abstract"]:
                    break
    p["abstract"] = p.get("abstract", "")
    p["tldr"] = first_sentence(p["abstract"])
    # code_repo: 仅来自外部 --code-repos 输入(agent 的真实检索), 按 doi/arxiv/title-key 查; 否则 none-found
    entry = (code_map.get(p["doi"]) or code_map.get(p["arxiv"])
             or next((v for k, v in code_map.items() if k and k.lower() in p["title"].lower()), None))
    if entry and entry.get("url"):
        p["code_repo"] = entry["url"]
        p["code_meta"] = {k: entry.get(k) for k in ("source", "official", "stars", "evidence")}
    else:
        p["code_repo"] = "none-found"
        p["code_meta"] = None
    p["trust"] = compute_trust(p, w)   # 可信度层: 撤稿/评审层/引用热度/版本
    p["slug"] = make_slug(p["title"], p["year"])   # 稳定: 仅依赖 canonical 标题+年
    return p


def bibtype(p):
    if p.get("bibtype_override"):   # 人工导出修正优先; 不改 p["work_type"](源 type)
        return p["bibtype_override"]
    v = (p["venue"] or "").lower()
    if any(k in v for k in ["proceedings", "symposium", "conference", "workshop"]):
        return "inproceedings"
    if any(k in v for k in ["transactions", "journal", "computers & security"]):
        return "article"
    return {"journal-article": "article", "article": "article", "proceedings-article": "inproceedings",
            "report": "techreport", "dissertation": "techreport", "book-chapter": "incollection",
            "posted-content": "misc"}.get(p.get("work_type"), "misc")


def bib_authors(authors):
    return " and ".join(authors) if authors else "Unknown"


def write_bib(papers, path):
    out = ["% lit-scout verified.bib — 仅 confirmed, 单一 canonical 数据流 (UTF-8, ASCII citekey)."]
    for p in papers:
        bt = bibtype(p)
        vkey = {"inproceedings": "booktitle", "article": "journal",
                "incollection": "booktitle", "techreport": "institution"}.get(bt)
        fld = [f"  title = {{{p['title']}}}", f"  author = {{{bib_authors(p['authors'])}}}",
               f"  year = {{{p['year']}}}"]
        if vkey and p["venue"]:
            fld.append(f"  {vkey} = {{{p['venue']}}}")
        if p["doi"]:
            fld.append(f"  doi = {{{p['doi']}}}")
        elif p["arxiv"]:
            fld += [f"  eprint = {{{p['arxiv']}}}", "  archivePrefix = {arXiv}"]
        notes = []
        if p["code_repo"] != "none-found":
            notes.append(f"code: {p['code_repo']}")
        if (p.get("trust") or {}).get("is_retracted"):
            notes.append("RETRACTED (OpenAlex)")
        if notes:
            fld.append(f"  note = {{{'; '.join(notes)}}}")
        out.append(f"@{bt}{{{p['slug'].lower()},\n" + ",\n".join(fld) + "\n}")
    open(path, "w", encoding="utf-8").write("\n\n".join(out) + "\n")


RIS_TY = {"article": "JOUR", "inproceedings": "CPAPER", "incollection": "CHAP",
          "techreport": "RPRT", "misc": "GEN"}


def write_ris(papers, path):
    """RIS 导出: Zotero/EndNote 原生可导入。"""
    out = []
    for p in papers:
        bt = bibtype(p)
        out.append("TY  - " + RIS_TY.get(bt, "GEN"))
        out.append("TI  - " + p["title"])
        for a in p["authors"]:
            out.append("AU  - " + a)
        if p["year"]:
            out.append("PY  - " + str(p["year"]))
        if p["venue"]:
            out.append("T2  - " + p["venue"])
        if p["doi"]:
            out.append("DO  - " + p["doi"])
            out.append("UR  - https://doi.org/" + p["doi"])
        elif p["arxiv"]:
            out.append("UR  - https://arxiv.org/abs/" + p["arxiv"])
        if p.get("abstract"):
            out.append("AB  - " + p["abstract"])
        if p["code_repo"] != "none-found":
            out.append("N1  - code: " + p["code_repo"])
        out.append("ER  - ")
        out.append("")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def _split_author(a):
    """'He, Kaiming' / 'Kaiming He' -> {family, given}; 尽力而为。"""
    a = a.strip()
    if "," in a:
        fam, _, giv = a.partition(",")
        return {"family": fam.strip(), "given": giv.strip()}
    parts = a.split()
    return {"family": parts[-1], "given": " ".join(parts[:-1])} if len(parts) > 1 else {"family": a}


_CSL_TYPE = {"inproceedings": "paper-conference", "article": "article-journal", "misc": "article"}
_ENW_TYPE = {"inproceedings": "Conference Paper", "article": "Journal Article", "misc": "Generic"}


def write_csl(papers, path):
    """CSL-JSON: Zotero / pandoc / citeproc 通用交换格式(比 .nbib 更适合 CS/ML)。"""
    out = []
    for p in papers:
        item = {"id": p["slug"], "type": _CSL_TYPE.get(bibtype(p), "article"),
                "title": p["title"], "author": [_split_author(a) for a in p["authors"]]}
        if p["year"]:
            item["issued"] = {"date-parts": [[int(p["year"])]]}
        if p["venue"]:
            item["container-title"] = p["venue"]
        if p["doi"]:
            item["DOI"] = p["doi"]; item["URL"] = "https://doi.org/" + p["doi"]
        elif p["arxiv"]:
            item["URL"] = "https://arxiv.org/abs/" + p["arxiv"]
        out.append(item)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def write_enw(papers, path):
    """EndNote (.enw): EndNote 原生导入格式。"""
    out = []
    for p in papers:
        out.append("%0 " + _ENW_TYPE.get(bibtype(p), "Generic"))
        out.append("%T " + p["title"])
        for a in p["authors"]:
            out.append("%A " + a)
        if p["year"]:
            out.append("%D " + str(p["year"]))
        if p["venue"]:
            out.append("%J " + p["venue"])
        if p["doi"]:
            out.append("%R " + p["doi"]); out.append("%U https://doi.org/" + p["doi"])
        elif p["arxiv"]:
            out.append("%U https://arxiv.org/abs/" + p["arxiv"])
        out.append("")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def write_obsidian(papers, edges, outdir, summaries=None, taxonomy=None, seeds=None):
    os.makedirs(outdir, exist_ok=True)
    for old in os.listdir(outdir):  # 清旧 .md, 避免 slug 变更后留孤儿笔记
        if old.endswith(".md"):
            os.remove(os.path.join(outdir, old))
    summaries = summaries or {}
    by = {p["slug"]: p for p in papers}
    role_of = {s.get("slug"): s.get("role") for s in (seeds or [])}
    cited_in, cites = {s: [] for s in by}, {s: [] for s in by}
    for a, b in edges:
        cites[b].append(a)        # b cites a
        cited_in[a].append(b)
    for p in papers:
        s = p["slug"]
        ident = f"doi: {p['doi']}" if p["doi"] else (f"arxiv: {p['arxiv']}" if p["arxiv"] else "id:")
        tags = ["seed/" + re.sub(r"\s+", "-", role_of[s])] if role_of.get(s) else []
        tr = p.get("trust") or {}
        fm = ["---", f'title: "{p["title"]}"', f'authors: [{", ".join(p["authors"])}]',
              f"year: {p['year']}", f'venue: "{p["venue"]}"', ident,
              f"cited_by: {p['cited']}",
              f'venue_type: {tr.get("venue_type") or "unknown"}',
              f'peer_reviewed: {tr.get("peer_reviewed")}',
              f'retracted: {bool(tr.get("is_retracted"))}',
              f"tags: [{', '.join(tags)}]", "---", ""]
        sm = summaries.get(s)
        if isinstance(sm, dict):
            summ, prov = sm.get("summary", ""), sm
        elif isinstance(sm, str) and sm:
            summ, prov = sm, {}
        else:
            summ, prov = (p.get("tldr") or "(摘要不可得)"), {}
        body = [f"# {p['title']}", "", "## 论文总结", summ]
        ev = " · ".join(f"{lab}: {prov[k]}" for lab, k in
                        (("来源类型", "source_type"), ("来源", "source_url_or_id"),
                         ("证据", "evidence"), ("注", "note")) if prov.get(k))
        if ev:
            body += ["", "## 来源证据", ev]
        body += ["", "## 集合内引用图 (relation=cites, 证据=referenced_works; 非方法谱系)"]
        for a in cites[s]:
            body.append(f"- cites:: [[{a}]]")
        for b in cited_in[s]:
            body.append(f"- cited-by:: [[{b}]]")
        if p["code_repo"] != "none-found":
            m = p.get("code_meta") or {}
            tag = "official" if m.get("official") else "community"
            body += ["", "## 代码",
                     f"- {p['code_repo']} — {tag} · {m.get('source','?')}"
                     + (f" · 证据: {m['evidence']}" if m.get("evidence") else "")]
        open(os.path.join(outdir, f"{s}.md"), "w", encoding="utf-8").write("\n".join(fm + body) + "\n")
    # _MOC: 有 taxonomy 则按流派分组(研究地图); 否则扁平. 标题用 [[slug|短标题]] 不硬切
    moc = ["# MOC — 研究地图", ""]
    if taxonomy:
        covered = set()
        for fam in taxonomy:
            moc.append(f"## {fam.get('family', '?')}")
            if fam.get("idea"):
                moc.append(f"> {fam['idea']}")
            for sl in fam.get("members", []):
                p = by.get(sl)
                if p:
                    moc.append(f"- [[{sl}|{short_title(p['title'])}]] — {p['title']}")
                    covered.add(sl)
            moc.append("")
        # 未被任何流派覆盖的 confirmed 也要进图(否则从研究地图消失 + 校验不全)
        uncovered = [p for p in papers if p["slug"] not in covered]
        if uncovered:
            moc.append("## 未归类")
            for p in sorted(uncovered, key=lambda x: -(x["cited"] or 0)):
                moc.append(f"- [[{p['slug']}|{short_title(p['title'])}]] — {p['title']}")
            moc.append("")
    else:
        moc += ["> 未提供 taxonomy；扁平索引(由 taxonomy_agent 重聚类后可分组)。", ""]
        for p in sorted(papers, key=lambda x: -(x["cited"] or 0)):
            moc.append(f"- [[{p['slug']}|{short_title(p['title'])}]] — {p['title']}")
    open(os.path.join(outdir, "_MOC.md"), "w", encoding="utf-8").write("\n".join(moc) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdict", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="research landscape")
    ap.add_argument("--summaries", help="可选结构化 JSON {slug:{summary,source_type,source_url_or_id,evidence,note}}")
    ap.add_argument("--code-repos", help="可选 JSON {doi/arxiv/title-key:{url,source,official,stars,evidence}}; 无则全 none-found")
    ap.add_argument("--taxonomy", help="可选 JSON [{family,idea,members:[slug],evidence}]; 方法重聚类")
    ap.add_argument("--sota", help="可选 JSON [{slug,method,dataset,metric,value,note,evidence,source}]")
    ap.add_argument("--seeds", help="可选 JSON [{slug,role}]; role 推荐 奠基/里程碑/方法基座/当前SOTA/直接竞品/最新近邻/必读")
    ap.add_argument("--overrides", help="可选 JSON {slug|doi|arxiv|id:{bibtype?,venue?,year?,work_type?,reason}}; 人工导出修正")
    ap.add_argument("--search-log", dest="search_log",
                    help="可选 JSON {date,databases,queries:[{db,string,cluster,hits}],inclusion,exclusion,counts}; 生成检索可复现报告")
    ap.add_argument("--merge-corpus", dest="merge_corpus",
                    help="可选 上一次 corpus.json 路径; 追踪模式累积用: 把旧 confirmed 并入本次, 不丢历史笔记")
    ap.add_argument("--positioning",
                    help="可选 JSON(模式①) {contribution, neighbors:[{slug,diff,evidence}], gap, baselines:[{slug,why,metric}], must_cite:[{slug,role}], related_work_skeleton}; 定位综合产物")
    ap.add_argument("--circles",
                    help="可选 JSON(模式④) {seed:{slug,title}, core:[{slug,relation,evidence,cited_by}], adjacent:[...], peripheral:[...]}; 同心圆相关工作")
    a = ap.parse_args()

    def load(path, default):
        return json.loads(open(path, encoding="utf-8").read()) if path and os.path.exists(path) else default
    summaries = load(a.summaries, {})
    code_map = load(a.code_repos, {})
    taxonomy = load(a.taxonomy, None)   # None=未提供(报告明示), []=空
    sota = load(a.sota, None)
    seeds = load(a.seeds, None)
    overrides = load(a.overrides, {})
    search_log = load(a.search_log, None)
    positioning = load(a.positioning, None)
    circles = load(a.circles, None)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    v = json.loads(open(a.verdict, encoding="utf-8").read())
    os.makedirs(a.out, exist_ok=True)
    papers = [enrich(r, code_map) for r in v.get("confirmed", [])]
    for p in papers:
        p["_new_this_run"] = True   # 本次验证门新确认的(追踪 digest 用)
    # 人工覆盖: 匹配顺序 slug -> doi -> arxiv -> id; 记命中 key; bibtype 只改导出, 不反向伪造 work_type
    for p in papers:
        ov = mk = None
        for k in (p["slug"], p["doi"], p["arxiv"], p["id"]):
            if k and k in overrides:
                ov, mk = overrides[k], k
                break
        if not ov:
            continue
        applied = {}
        if ov.get("bibtype"):
            p["bibtype_override"] = ov["bibtype"]; applied["bibtype"] = ov["bibtype"]
        for fld in ("venue", "year", "work_type"):  # 仅在 override 显式给出时才改源字段
            if fld in ov and ov[fld] is not None:
                p[fld] = ov[fld]; applied[fld] = ov[fld]
        p["override_meta"] = {"matched_key": mk, "applied": applied, "reason": ov.get("reason", "")}
    # 追踪模式累积: 并入上次 corpus 的 confirmed(已富化), 按 doi/arxiv/slug 去重, 不重抓网络
    if a.merge_corpus and os.path.exists(a.merge_corpus):
        prev = json.loads(open(a.merge_corpus, encoding="utf-8").read()).get("papers", [])
        def pid(p):
            return (p.get("doi") or "").lower() or (p.get("arxiv") or "").lower() or p.get("slug")
        have = {pid(p) for p in papers}
        for pp in prev:
            if pid(pp) not in have:
                pp["_new_this_run"] = False
                papers.append(pp)
                have.add(pid(pp))
    by_oa = {p["oaid"]: p for p in papers if p.get("oaid")}
    edges = []
    for p in papers:
        for r in p["refs"]:
            if r in by_oa and by_oa[r]["slug"] != p["slug"]:
                edges.append((by_oa[r]["slug"], p["slug"]))  # (cited, citing)
    json.dump({"topic": a.topic, "papers": papers, "citation_edges": edges,
               "edge_semantics": "cites (集合内引用图; 非 builds-on/谱系, 无逐边原文 evidence)",
               "taxonomy": taxonomy, "sota": sota, "seeds": seeds,
               "positioning": positioning, "circles": circles},
              open(os.path.join(a.out, "corpus.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_bib(papers, os.path.join(a.out, "verified.bib"))
    write_ris(papers, os.path.join(a.out, "verified.ris"))
    write_csl(papers, os.path.join(a.out, "verified.csl.json"))   # Zotero/pandoc
    write_enw(papers, os.path.join(a.out, "verified.enw"))        # EndNote
    write_obsidian(papers, edges, os.path.join(a.out, "obsidian"), summaries, taxonomy, seeds)
    # report.md — At a glance + 卡片式; 完整 title/venue 不截断
    by = {p["slug"]: p for p in papers}
    ranked = sorted(papers, key=lambda x: -(x["cited"] or 0))
    nrev, nrej = len(v.get("review", [])), len(v.get("rejected", []))
    ncode = sum(1 for p in papers if p["code_repo"] != "none-found")
    ntax = len(taxonomy) if taxonomy else 0

    def prov_line(p):
        s = summaries.get(p["slug"])
        if not isinstance(s, dict):
            return None
        bits = [s.get(k2) and f"{lab}: {s[k2]}" for lab, k2 in
                (("来源类型", "source_type"), ("来源", "source_url_or_id"), ("注", "note"))]
        return " · ".join(b for b in bits if b)

    def summ_text(p):
        s = summaries.get(p["slug"])
        if isinstance(s, dict):
            return s.get("summary", "")
        if isinstance(s, str) and s:
            return s
        return p.get("tldr") or "(摘要不可得)"

    L = [f"# 调研产物 — {a.topic}", "",
         f"> **At a glance** — {len(papers)} confirmed · {nrev} review · {nrej} rejected · "
         f"{ncode} code repos · {len(edges)} citation edges · {ntax} taxonomy 流派", "",
         "_canonical 数据流(id/title/year 取自验证门) · 关系=cites 引用图(非谱系)_", ""]

    # 论文定位(模式①核心综合; 只引用 confirmed slug, 关系须带 evidence)
    if positioning:
        def pslug(sl):
            p = by.get(sl)
            return f"{sl} — {short_title(p['title'])}" if p else sl
        L += ["## 论文定位"]
        if positioning.get("contribution"):
            L += ["", "### 你的贡献（原话）", f"> {positioning['contribution']}"]
        nb = positioning.get("neighbors") or []
        if nb:
            L += ["", "### 最近邻竞品", "| 工作 | 与你的差异 | 证据 |", "|---|---|---|"]
            for n in nb:
                L.append(f"| {pslug(n.get('slug',''))} | {n.get('diff','—')} | {n.get('evidence','—')} |")
        if positioning.get("gap"):
            L += ["", "### Gap 定位", positioning["gap"]]
        bl = positioning.get("baselines") or []
        if bl:
            L += ["", "### 候选 baseline（你该对比谁）"]
            for b in bl:
                L.append(f"- {pslug(b.get('slug',''))} — {b.get('why','')}"
                         + (f"；{b['metric']}" if b.get("metric") else ""))
        mc = positioning.get("must_cite") or []
        if mc:
            L += ["", "### 必引清单"]
            for m in mc:
                L.append(f"- {pslug(m.get('slug',''))}（{m.get('role','必读')}）")
        if positioning.get("related_work_skeleton"):
            L += ["", "### Related Work 草骨架", positioning["related_work_skeleton"]]
        L.append("")

    # 同心圆相关工作(模式④; 关系须带 evidence, 中心度只记 API 真实被引)
    if circles:
        def cslug(sl):
            p = by.get(sl)
            return f"{sl} — {short_title(p['title'])}" if p else sl
        sd = circles.get("seed") or {}
        L += ["## 同心圆相关工作",
              f"**种子**: {sd.get('slug') or sd.get('title','?')}" + (f" — {sd.get('title','')}" if sd.get('slug') else "")]
        for ring, label in (("core", "核心圈（直接相关，必读/必引）"),
                            ("adjacent", "邻近圈"), ("peripheral", "外围圈（弱相关，可选）")):
            items = circles.get(ring) or []
            if items:
                L += ["", f"### {label}"]
                for it in items:
                    cb = f" | 被引 {it['cited_by']}" if it.get("cited_by") is not None else ""
                    ev = f" — 证据: {it['evidence']}" if it.get("evidence") else ""
                    L.append(f"- {cslug(it.get('slug',''))} —（{it.get('relation','?')}）{cb}{ev}")
        L.append("")

    # 本次新增 digest(仅累积/追踪模式: 有历史并入时才出)
    if a.merge_corpus and any(not p.get("_new_this_run", True) for p in papers):
        fresh = [p for p in papers if p.get("_new_this_run")]
        L += [f"## 本次新增（digest，{len(fresh)} 篇新确认 / 累积 {len(papers)} 篇）"]
        if fresh:
            for p in sorted(fresh, key=lambda x: -(x["cited"] or 0)):
                L.append(f"- **{p['slug']}** — {short_title(p['title'])}（{p['year']} · {p['venue'] or 'venue缺'}）")
        else:
            L.append("_本窗口无新确认文献_")
        L.append("")

    # 必读种子
    L += ["## 必读种子"]
    if seeds:
        for s in seeds:
            p = by.get(s.get("slug"))
            if p:
                L.append(f"- **{s['slug']}**（{s.get('role', '必读')}）— {short_title(p['title'])}")
    else:
        L.append("_未提供 seeds 输入（由 agent 标注奠基/里程碑/方法基座/当前SOTA/直接竞品/必读）_")

    # Taxonomy
    L += ["", "## Taxonomy（方法重聚类，非源 auto-topic）"]
    if taxonomy:
        for fam in taxonomy:
            L.append(f"### {fam.get('family', '?')}")
            if fam.get("idea"):
                L.append(f"_{fam['idea']}_")
            for sl in fam.get("members", []):
                p = by.get(sl)
                L.append(f"- **{sl}** — {short_title(p['title'])}" if p else f"- {sl}")
    else:
        L.append("_未提供 taxonomy 输入（由 taxonomy_agent 按方法/问题重聚类生成）_")

    # SOTA / 能力对照 (拆 定量指标 / 定性能力证据)
    L += ["", "## SOTA / 能力对照"]
    if sota:
        def sota_table(rows, header):
            seg = [f"### {header}"]
            if not rows:
                return seg + ["_无_"]
            seg += ["| slug | 方法 | 数据集 | 指标 | 值 | 证据/来源 |", "|---|---|---|---|---|---|"]
            for r in rows:
                seg.append(f"| {r.get('slug','')} | {r.get('method','—')} | {r.get('dataset','—')} | "
                           f"{r.get('metric','—')} | {r.get('value','—')} | {r.get('evidence') or r.get('source','—')} |")
            return seg
        quant = [r for r in sota if r.get("kind") == "quantitative"]
        qual = [r for r in sota if r.get("kind") != "quantitative"]
        L += sota_table(quant, "定量指标（只放原文真实数值，缺则不进表）")
        L += sota_table(qual, "定性能力证据（能力性论证，非严格指标）")
        L.append("> 定量与定性分列；二者都须可追溯到原文，不猜。")
    else:
        L.append("_未提供 SOTA 输入（指标须来自原文，缺则标 —，不得猜测）_")

    def trust_tag(p):
        t = p.get("trust") or {}
        bits = []
        if t.get("is_retracted"):
            bits.append("⚠撤稿")
        vt = t.get("venue_type")
        if vt and vt != "unknown":
            label = {"preprint": "预印本(未评审)", "workshop": "workshop",
                     "conference": "会议(评审)", "journal": "期刊(评审)"}.get(vt, vt)
            bits.append(label)
        if t.get("citation_velocity") is not None:
            bits.append(f"~{t['citation_velocity']}/yr")
        return " · ".join(bits)

    # 关键工作(卡片式)
    L += ["", "## 关键工作（卡片式）"]
    for p in ranked:
        codeflag = f"✓ code({(p.get('code_meta') or {}).get('source','?') if p['code_repo']!='none-found' else ''})" if p["code_repo"] != "none-found" else "无公开代码"
        tt = trust_tag(p)
        L += ["", f"### ▸ {p['slug']} — {p['title']}",
              f"{p['year']} · {p['venue'] or '(venue 缺)'} · cited {p['cited']} · {codeflag}"
              + (f" · {tt}" if tt else ""),
              "", f"> {summ_text(p)}"]
        pl = prov_line(p)
        if pl:
            L.append(f"_{pl}_")
        if p["code_repo"] != "none-found":
            L.append(f"代码: {p['code_repo']}")
        L.append(f"DOI/ID: {p['doi'] or p['arxiv'] or p['id'] or '—'}")

    # 集合内引用图
    L += ["", "## 集合内引用图（relation=cites；非方法谱系）",
          "> 仅证明引用关系(OpenAlex referenced_works)。每条边补到原文 evidence 才升级为方法谱系。", ""]
    for cdt, cig in edges:
        L.append(f"- {cig} ({by[cig]['year']}) cites {cdt} ({by[cdt]['year']})")

    # 代码可得性
    L += ["", "## 代码可得性"]
    for p in ranked:
        if p["code_repo"] != "none-found":
            m = p.get("code_meta") or {}
            tag = "official" if m.get("official") else "community"
            star = f" · ★{m['stars']}" if m.get("stars") else ""
            L.append(f"- **{p['slug']}** — {tag} · {m.get('source','?')}{star} · {p['code_repo']}"
                     + (f" · 证据: {m['evidence']}" if m.get("evidence") else ""))
    if ncode == 0:
        L.append("_本批均未找到公开代码（none-found）_")
    else:
        for p in ranked:
            if p["code_repo"] == "none-found":
                L.append(f"- {p['slug']} — none-found")

    # 可信度告警(存在性之外: 撤稿 / 纯预印本未评审)
    retracted = [p for p in papers if (p.get("trust") or {}).get("is_retracted")]
    preprints = [p for p in papers if (p.get("trust") or {}).get("venue_type") == "preprint"]
    # 跨索引一致性低(三角验证): 仅 1 索引命中而其余源查得正常 -> 存疑
    single_idx = [p for p in papers if (p.get("triangulation") or {}).get("n_matched", 9) <= 1
                  and (p.get("triangulation") or {}).get("n_queried_ok", 0) >= 3]
    thin_venue = [p for p in papers if (p.get("trust") or {}).get("venue_quality") == "thin"]
    if retracted or preprints or single_idx or thin_venue:
        L += ["", "## 可信度告警（存在性已确认，但选 baseline/判 SOTA 前请留意）"]
        for p in retracted:
            L.append(f"- ⚠ **撤稿** — {p['slug']}：{p['title']}（OpenAlex is_retracted=true；勿作为 baseline）")
        for p in preprints:
            L.append(f"- **纯预印本(未同行评审)** — {p['slug']}：{p['venue'] or 'arXiv'}；引用时注意尚未正式发表")
        for p in single_idx:
            tr = p["triangulation"]
            L.append(f"- **单索引存疑** — {p['slug']}：仅 {tr['n_matched']}/{tr['n_queried_ok']} 个索引命中"
                     f"（命中: {', '.join(tr.get('matched_indexes') or []) or '—'}）；可能冷门/新预印本，也可能存疑，建议核对原文")
        for p in thin_venue:
            L.append(f"- **venue 元数据稀薄** — {p['slug']}：{p['venue'] or '?'}（未见 DOAJ/ISSN 且零被引；非掠夺定性，仅提示留意期刊可信度）")

    # 年份审计
    yaudit = [p for p in papers if p.get("input_year") is not None and str(p["input_year"]) != str(p["year"])]
    if yaudit:
        L += ["", "## 年份审计（按检索源校正）"]
        for p in yaudit:
            L.append(f"- {p['slug']}: 输入 {p['input_year']} → 采用 {p['year']}（{p.get('year_note') or '以检索源为准'}）")

    # 富化告警(人话化)
    enr = [p for p in papers if p.get("enrichment_errors")]
    if enr:
        L += ["", "## 富化告警（元数据可能不全，已留空非臆造）"]
        for p in enr:
            L.append(f"- **{p['slug']}**: {humanize_enrich(p)}")

    # 人工覆盖记录(导出修正, 可审计)
    ovs = [p for p in papers if p.get("override_meta")]
    if ovs:
        L += ["", "## 人工覆盖记录（导出修正，可审计）"]
        for p in ovs:
            m = p["override_meta"]
            L.append(f"- **{p['slug']}**: 命中 key `{m['matched_key']}` · 覆盖 {m['applied']} · 理由: {m['reason']}")

    # 完整标题对照(供审计/校验全标题)
    L += ["", "## 完整标题对照"]
    for p in papers:
        L.append(f"- **{p['slug']}**: {p['title']}")
    open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    # 检索可复现报告(survey-grade): 库/检索式/日期/纳排/PRISMA 式计数
    if search_log is not None:
        cnt = search_log.get("counts", {}) or {}
        S = ["# 检索策略（可复现）", "",
             f"- 检索日期: {search_log.get('date', '(未填)')}",
             f"- 检索库: {', '.join(search_log.get('databases', [])) or '(未填)'}", ""]
        S += ["## 检索式", "| 库 | 概念簇 | 检索式 | 命中 |", "|---|---|---|---|"]
        for q in search_log.get("queries", []):
            S.append(f"| {q.get('db','')} | {q.get('cluster','')} | `{q.get('string','')}` | {q.get('hits','—')} |")
        inc, exc = search_log.get("inclusion", []), search_log.get("exclusion", [])
        S += ["", "## 纳入标准"] + ([f"- {x}" for x in inc] or ["- (未填)"])
        S += ["", "## 排除标准"] + ([f"- {x}" for x in exc] or ["- (未填)"])
        S += ["", "## 文献流（PRISMA 式计数）",
              f"- 检索命中(去重前): {cnt.get('found', '(未填)')}",
              f"- 去重后: {cnt.get('after_dedup', '(未填)')}",
              f"- 验证门 confirmed: {len(papers)}",
              f"- 验证门 needs-review: {nrev}",
              f"- 验证门 rejected(疑似不存在/编造): {nrej}",
              "", "> 计数中的 confirmed/review/rejected 由 verdict.json 派生，与产物一致。"]
        open(os.path.join(a.out, "search-strategy.md"), "w", encoding="utf-8").write("\n".join(S) + "\n")

    # 默认空状态文件
    for tier, fn in (("review", "needs-review.md"), ("rejected", "rejected.md")):
        items = v.get(tier, [])
        lines = [f"# {fn[:-3]} ({len(items)})", ""]
        if not items:
            lines.append(f"无 {tier} 条目。")
        for it in items:
            lines.append(f"- {it.get('title') or it.get('input_doi_unresolved') or it.get('unresolved_arxiv') or '?'}"
                         f" — {it.get('note') or it.get('reason') or ''}")
        open(os.path.join(a.out, fn), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(json.dumps({"confirmed": len(papers), "edges": len(edges),
                      "files": sorted(os.listdir(a.out))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
