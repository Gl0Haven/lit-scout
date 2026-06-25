#!/usr/bin/env python
"""check_outputs.py — lit-scout 输出一致性校验器。

校验 build_outputs.py 产物与 verdict.json 是否一致、是否符合 skill 约定。
用法: python check_outputs.py --verdict verdict.json --out <dir>
退出码: 全过 0, 有 FAIL 1。
"""
import sys, json, re, os, argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdict", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="",
                    help="模式: landscape|positioning|seed|tracking; 各自额外校验对应招牌产物")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails, checks = [], []

    def ck(name, ok, detail=""):
        checks.append((name, "PASS" if ok else "FAIL", detail))
        if not ok:
            fails.append(name)

    def warn(name, ok, detail=""):  # 不影响退出码, 仅提示
        checks.append((name, "PASS" if ok else "WARN", detail))

    v = json.loads(open(a.verdict, encoding="utf-8").read())
    conf = v.get("confirmed", [])
    O = a.out

    # 1) 必需文件存在
    req = ["corpus.json", "report.md", "verified.bib", "verified.ris", "needs-review.md", "rejected.md",
           os.path.join("obsidian", "_MOC.md")]
    for f in req:
        ck(f"file:{f}", os.path.exists(os.path.join(O, f)))

    if not os.path.exists(os.path.join(O, "corpus.json")):
        report(checks, fails)
        sys.exit(1)
    corpus = json.loads(open(os.path.join(O, "corpus.json"), encoding="utf-8").read())
    papers = corpus.get("papers", [])
    bib = open(os.path.join(O, "verified.bib"), encoding="utf-8").read()
    notes = [f for f in os.listdir(os.path.join(O, "obsidian")) if f.endswith(".md") and f != "_MOC.md"]
    report_txt = open(os.path.join(O, "report.md"), encoding="utf-8").read()

    # 2) 计数一致: verdict.confirmed == corpus == bib == obsidian notes
    n = len(conf)
    bib_entries = re.findall(r"^@\w+\{([^,]+),", bib, re.M)
    ck("count:corpus==confirmed", len(papers) == n, f"{len(papers)} vs {n}")
    ck("count:bib==confirmed", len(bib_entries) == n, f"{len(bib_entries)} vs {n}")
    ck("count:obsidian==confirmed", len(notes) == n, f"{len(notes)} vs {n}")

    # 3) citekey 全 ASCII
    nonascii = [k for k in bib_entries if not k.isascii()]
    ck("bib:citekey-ascii", not nonascii, f"non-ascii: {nonascii}")

    # 4) bib 作者用 ' and ' 分隔, 不含 'et al'
    auth_fields = re.findall(r"author = \{([^}]*)\}", bib)
    bad_auth = [x for x in auth_fields if ("et al" in x.lower()) or ("," in x and " and " not in x and x.strip() != "Unknown")]
    ck("bib:author-and-separated", not bad_auth, f"bad: {bad_auth[:2]}")

    # 5) year 一致: corpus vs bib (按 slug/citekey)
    cy = {p["slug"].lower(): p.get("year") for p in papers}
    drift = []
    for m in re.finditer(r"@\w+\{([^,]+),(.*?)\n\}", bib, re.S):
        key, body = m.group(1), m.group(2)
        ym = re.search(r"year = \{(\d+)\}", body)
        if ym and key in cy and cy[key] is not None and int(ym.group(1)) != int(cy[key]):
            drift.append(f"{key}: bib {ym.group(1)} vs corpus {cy[key]}")
    ck("consistency:year corpus==bib", not drift, "; ".join(drift))

    # 6) 完整标题未截断: 每篇 corpus title 完整出现在 report
    missing = [p["slug"] for p in papers if p["title"] not in report_txt]
    ck("report:full-titles-present", not missing, f"truncated/missing: {missing}")

    # 7) 每篇 corpus 带 code_repo 字段
    nocode = [p["slug"] for p in papers if "code_repo" not in p]
    ck("corpus:code_repo-field", not nocode, f"missing: {nocode}")

    # 8) 谱系诚实: 默认导出不得出现任何无 evidence 的方法谱系关系标记
    LINEAGE = re.compile(r"(builds-on|improves|baseline-of|extends|influenced-by)\s*::")
    bad_lineage = []
    for f in notes:
        t = open(os.path.join(O, "obsidian", f), encoding="utf-8").read()
        if LINEAGE.search(t):
            bad_lineage.append(f)
    ck("honesty:no-evidenceless-lineage", not bad_lineage, f"{bad_lineage[:3]}")

    # 9) needs-review/rejected 文件计数 == verdict
    for tier, fn in (("review", "needs-review.md"), ("rejected", "rejected.md")):
        want = len(v.get(tier, []))
        txt = open(os.path.join(O, fn), encoding="utf-8").read()
        hm = re.search(r"\((\d+)\)", txt.splitlines()[0]) if txt.strip() else None
        got = int(hm.group(1)) if hm else -1
        ck(f"count:{fn}==verdict.{tier}", got == want, f"header {got} vs verdict {want}")

    # 10) report 头部含 confirmed/review/rejected 三档计数
    head = "\n".join(report_txt.splitlines()[:6])
    ck("report:three-tier-counts",
       all(k in head for k in ("confirmed", "review", "rejected")),
       "报告头缺三档计数")

    # 11) 每篇 Obsidian 笔记含 论文总结
    no_summary = [f for f in notes
                  if "## 论文总结" not in open(os.path.join(O, "obsidian", f), encoding="utf-8").read()]
    ck("obsidian:has-summary", not no_summary, f"缺总结: {no_summary[:3]}")

    # 12) MOC 不硬截断: 每篇完整 title 出现在 _MOC.md
    moc = open(os.path.join(O, "obsidian", "_MOC.md"), encoding="utf-8").read()
    moc_trunc = [p["slug"] for p in papers if p["title"] not in moc]
    ck("moc:no-truncated-titles", not moc_trunc, f"标题被截断/缺失: {moc_trunc[:3]}")

    # 13) 代码可得性小节存在
    ck("report:code-availability-section", "## 代码可得性" in report_txt, "报告缺代码可得性小节")

    # 14) 各模式招牌产物校验
    slugs_all = {p["slug"] for p in papers}
    if a.mode == "landscape":
        for sec in ("## 必读种子", "## Taxonomy", "## SOTA"):
            ck(f"landscape:has {sec}", sec in report_txt, f"landscape 缺章节 {sec}")
    elif a.mode == "positioning":
        pos = corpus.get("positioning")
        ck("positioning:section-present", "## 论文定位" in report_txt and bool(pos),
           "positioning 模式缺 --positioning 输入/章节")
        if pos:
            ref = [n.get("slug") for n in (pos.get("neighbors") or [])] \
                + [b.get("slug") for b in (pos.get("baselines") or [])] \
                + [m.get("slug") for m in (pos.get("must_cite") or [])]
            bad = [s for s in ref if s and s not in slugs_all]
            ck("positioning:slugs-confirmed", not bad, f"引用非 confirmed slug: {bad[:3]}")
    elif a.mode == "seed":
        cir = corpus.get("circles")
        ck("seed:circles-present", "## 同心圆相关工作" in report_txt and bool(cir),
           "seed 模式缺 --circles 输入/章节")
        if cir:
            ref = [it.get("slug") for ring in ("core", "adjacent", "peripheral")
                   for it in (cir.get(ring) or [])]
            bad = [s for s in ref if s and s not in slugs_all]
            ck("seed:slugs-confirmed", not bad, f"圈层引用非 confirmed slug: {bad[:3]}")
    elif a.mode == "tracking":
        ck("tracking:digest-present", "## 本次新增" in report_txt,
           "tracking 模式缺 digest(用 --merge-corpus 累积并生成本次新增段)")

    # 15) schema 强校验: taxonomy/sota/seeds/code
    slugs = {p["slug"] for p in papers}
    tax, sota, seeds = corpus.get("taxonomy"), corpus.get("sota"), corpus.get("seeds")
    if tax:
        bad_mem = [m for fam in tax for m in fam.get("members", []) if m not in slugs]
        ck("schema:taxonomy-members-confirmed", not bad_mem, f"非 confirmed slug: {bad_mem[:3]}")
        no_ev = [fam.get("family") for fam in tax if not fam.get("evidence")]
        ck("schema:taxonomy-has-evidence", not no_ev, f"缺 evidence: {no_ev[:3]}")
    if sota:
        no_ev = [r.get("slug") for r in sota if not (r.get("evidence") or r.get("source"))]
        ck("schema:sota-has-evidence", not no_ev, f"缺 evidence/source: {no_ev[:3]}")
    if seeds:
        ALLOWED = {"奠基", "里程碑", "方法基座", "当前SOTA", "直接竞品", "最新近邻", "必读"}
        off = [s.get("role") for s in seeds if s.get("role") not in ALLOWED]
        warn("schema:seeds-role-in-whitelist", not off, f"白名单外(允许但提示): {off}")
    code_bad = [p["slug"] for p in papers if p["code_repo"] != "none-found"
                and not ((p.get("code_meta") or {}).get("source") and (p.get("code_meta") or {}).get("evidence"))]
    ck("schema:code-has-source-evidence", not code_bad, f"code 缺 source/evidence: {code_bad[:3]}")

    # 16) 可信度: 撤稿论文必须在报告里显式告警(存在性合法, 但不能静默当 baseline)
    retracted = [p["slug"] for p in papers if (p.get("trust") or {}).get("is_retracted")]
    if retracted:
        ck("trust:retraction-surfaced", "撤稿" in report_txt,
           f"confirmed 含撤稿但报告未告警: {retracted}")
        warn("trust:retracted-in-confirmed", False,
             f"confirmed 含撤稿(已确认存在, 选 baseline 须排除): {retracted}")
    # 17) trust 字段齐备(build_outputs 应给每篇算出可信度层)
    notrust = [p["slug"] for p in papers if "trust" not in p]
    ck("corpus:trust-field", not notrust, f"缺 trust: {notrust[:3]}")

    # 18) 去 AI 味 + survey 引用硬校验(见 references/voice.md)
    try:
        from check_voice import scan_ai_tells, extract_cites
        tells = scan_ai_tells(report_txt, "report.md")
        warn("voice:report-ai-tells", not tells,
             "; ".join(f"{t['hit']}×{t['count']}" for t in tells[:4]) or "")
        survey_p = os.path.join(O, "survey-draft.md")
        if os.path.exists(survey_p):
            survey = open(survey_p, encoding="utf-8").read()
            keys = {k.lower() for k in bib_entries}
            unresolved = [k for k in extract_cites(survey) if k not in keys]
            ck("voice:survey-cites-resolve", not unresolved,
               f"survey \\cite 未命中 verified.bib(疑似未核引用): {sorted(set(unresolved))[:3]}")
            stells = scan_ai_tells(survey, "survey-draft.md")
            warn("voice:survey-ai-tells", not stells,
                 "; ".join(f"{t['hit']}×{t['count']}" for t in stells[:4]) or "")
    except Exception as e:
        warn("voice:check-skipped", False, f"check_voice 未运行: {type(e).__name__}")

    report(checks, fails)
    sys.exit(1 if fails else 0)


def report(checks, fails):
    nwarn = 0
    for name, status, detail in checks:
        if status == "WARN":
            nwarn += 1
        print(f"  [{status}] {name}" + (f"  ({detail})" if detail and status != "PASS" else ""))
    tail = f" ({nwarn} WARN)" if nwarn else ""
    print(f"\n{'ALL PASS' + tail if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails) + tail}")


if __name__ == "__main__":
    main()
