#!/usr/bin/env python
"""parse_refs.py — 把稿件的参考文献列表解析成验证门候选 JSON（模式⑤的前端）。

lit-scout 拥有最强的确定性存在性门(verify_citations.py), 但此前只能从主题/种子出发。
本脚本补上"吃用户现成参考文献 -> 候选 JSON -> 过门"的入口, 用于核验:
  - 稿件 .bib / .ris 里的每条引用是否真实存在、标题/年份是否对得上;
  - LaTeX/纯文本里散落的 DOI / arXiv id 是否解析得到真论文。

支持格式(按可靠性):
  .bib  — BibTeX 条目(title/author/year/doi/eprint+archivePrefix)。最可靠。
  .ris  — RIS(TI/AU/PY/DO/UR 中的 arXiv)。
  .tex/.txt — 兜底: 抽每条 \\bibitem / 行内 DOI / arXiv id, 标题尽力而为(标 partial)。
  .docx — 不直接解析(依赖脆弱); 提示用户先导出 .bib 或纯文本。

输出: stdin/文件 -> stdout 一个 JSON 数组, 每项 {title, authors, year, doi, arxiv, _src_key}。
直接喂给 verify_citations.py: python parse_refs.py --in refs.bib | python verify_citations.py
只用标准库。
"""
import sys, json, re, os, argparse

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
ARXIV_RE = re.compile(r"arxiv[:\s/]*(\d{4}\.\d{4,5})(v\d+)?", re.I)
ARXIV_OLD_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("{", "").replace("}", "").strip()).strip(", ")


def parse_bib(text):
    """简单 BibTeX 解析: 按 @type{key, ...} 切块, 取常见字段。不依赖第三方。"""
    out = []
    # 按 @ 开头的条目切分(粗粒度; 容忍嵌套花括号)
    for m in re.finditer(r"@(\w+)\s*\{([^,]*),", text):
        start = m.end()
        # 找到该条目结束(配平花括号)
        depth, i = 1, m.start(0)
        # 从 @type{ 的左括号开始配平
        lb = text.find("{", m.start(0))
        depth, j = 1, lb + 1
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[lb + 1:j - 1]
        key = _clean(m.group(2))

        def field(name):
            fm = re.search(name + r"\s*=\s*", body, re.I)
            if not fm:
                return ""
            p = fm.end()
            if p < len(body) and body[p] == "{":
                d, k = 1, p + 1
                while k < len(body) and d:
                    if body[k] == "{":
                        d += 1
                    elif body[k] == "}":
                        d -= 1
                    k += 1
                return _clean(body[p + 1:k - 1])
            if p < len(body) and body[p] == '"':
                k = body.find('"', p + 1)
                return _clean(body[p + 1:k])
            return _clean(body[p:body.find(",", p) if body.find(",", p) > 0 else len(body)])

        title = field("title")
        if not title and not field("doi") and not field("eprint"):
            continue
        authors = field("author")
        rec = {"title": title, "_src_key": key}
        if authors:
            rec["authors"] = [a.strip() for a in re.split(r"\s+and\s+", authors) if a.strip()]
        y = re.search(r"\d{4}", field("year"))
        if y:
            rec["year"] = int(y.group(0))
        doi = field("doi") or (DOI_RE.search(body).group(0) if DOI_RE.search(body) else "")
        if doi:
            rec["doi"] = doi
        ep = field("eprint")
        if ep and ("arxiv" in field("archiveprefix").lower() or ARXIV_OLD_RE.fullmatch(ep) or "." in ep):
            am = ARXIV_OLD_RE.search(ep)
            if am:
                rec["arxiv"] = am.group(1)
        out.append(rec)
    return out


def parse_ris(text):
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - (.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"title": "", "authors": []}
            out.append(cur)
        elif cur is None:
            continue
        elif tag == "TI" or tag == "T1":
            cur["title"] = val
        elif tag == "AU" or tag == "A1":
            cur["authors"].append(val)
        elif tag == "PY" or tag == "Y1":
            y = re.search(r"\d{4}", val)
            if y:
                cur["year"] = int(y.group(0))
        elif tag == "DO":
            cur["doi"] = val
        elif tag in ("UR", "L1"):
            am = ARXIV_RE.search(val)
            if am:
                cur["arxiv"] = am.group(1)
    return [r for r in out if r.get("title") or r.get("doi") or r.get("arxiv")]


def parse_tex_or_text(text):
    """兜底: 每条 \\bibitem 或每行一条; 抽 DOI/arXiv, 标题尽力而为(可能 partial)。
    显式 \\bibitem 一律视为引用; 行分割兜底时, 只对"像引用"的行(含年份/DOI/arXiv/带引号标题)
    生成候选, 避免把普通散文行当成伪引用塞进管道。"""
    out = []
    items = re.split(r"\\bibitem(?:\[[^\]]*\])?\{[^}]*\}", text)
    if len(items) > 1:
        chunks = [(c, True) for c in items[1:]]        # 显式 bibitem: 一定是引用
    else:
        chunks = [(ln, False) for ln in text.splitlines() if len(ln.strip()) > 20]
    for ch, is_bibitem in chunks:
        ch = ch.strip()
        if not ch:
            continue
        rec = {"_partial": True}
        dm = DOI_RE.search(ch)
        if dm:
            rec["doi"] = dm.group(0).rstrip(".")
        am = ARXIV_RE.search(ch) or (ARXIV_OLD_RE.search(ch) if "arxiv" in ch.lower() else None)
        if am:
            rec["arxiv"] = am.group(1)
        qm = re.search(r'[“"“]([^”"”]{8,})[”"”]', ch)   # 引号内标题
        has_year = re.search(r"\b(19|20)\d{2}\b", ch)
        # 行分割兜底: 不像引用(无年份/DOI/arXiv/引号标题)的行直接跳过
        if not (is_bibitem or dm or am or qm or has_year):
            continue
        if qm:
            rec["title"] = _clean(qm.group(1))
        else:
            seg = re.split(r"\.\s|\?\s", _clean(ch))
            cand = max(seg, key=len) if seg else ""
            rec["title"] = cand[:200]
        if rec.get("title") or rec.get("doi") or rec.get("arxiv"):
            out.append(rec)
    return out


def parse(path, text):
    ext = os.path.splitext(path or "")[1].lower()
    if ext == ".bib":
        return parse_bib(text)
    if ext == ".ris" or ext == ".nbib":
        return parse_ris(text)
    if ext == ".docx":
        sys.stderr.write("[parse_refs] .docx 不直接解析(依赖脆弱); 请先导出 .bib 或纯文本参考文献。\n")
        return []
    # .tex/.txt/未知: 先尝试 bib(若含 @), 否则文本兜底
    if "@" in text and re.search(r"@\w+\s*\{", text):
        b = parse_bib(text)
        if b:
            return b
    return parse_tex_or_text(text)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help=".bib/.ris/.tex/.txt 参考文献文件")
    a = ap.parse_args()
    text = open(a.inp, encoding="utf-8", errors="replace").read()
    recs = parse(a.inp, text)
    json.dump(recs, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
