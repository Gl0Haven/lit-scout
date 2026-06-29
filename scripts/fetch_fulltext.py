#!/usr/bin/env python
"""fetch_fulltext.py — 抓 confirmed 论文的开放获取全文并抽成 markdown（喂总结 / claim 核对）。

为什么：extractor/总结/claim 核对此前只能基于摘要(OpenAlex→CrossRef→arXiv)。本脚本在能拿到
开放获取 PDF 时抽**全文**，质量远高于摘要；拿不到就如实标注、回退到摘要，绝不编造。

PDF 来源解析顺序：arXiv id → arXiv PDF；否则 OpenAlex(open_access.oa_url / best_oa_location)；
再否则 Unpaywall(按 DOI, 需 --email)。只抓**开放获取**，不碰付费墙。

抽取后端（按质量，自动回退）：pymupdf4llm(直出 markdown) → fitz 纯文本 → pdfplumber。
这些库装在专用 venv（见 requirements-pdf.txt）；**必须用该 venv 的 python 运行本脚本**。
未装库 → 打印安装指引并退出(非 0)，不静默假装成功。核心 skill 其余脚本仍零依赖。

用法：
  # 单篇
  .venv/Scripts/python scripts/fetch_fulltext.py --arxiv 1706.03762 --out fulltext/
  .venv/Scripts/python scripts/fetch_fulltext.py --doi 10.1109/CVPR.2016.90 --email you@x.org --out fulltext/
  # 批量(吃 corpus.json 的 papers 或自定义 [{slug,arxiv?,doi?,oaid?,title?}])
  .venv/Scripts/python scripts/fetch_fulltext.py --in corpus.json --out fulltext/ --email you@x.org
输出：fulltext/<slug>.md（全文 markdown）+ stdout 一份 manifest JSON
  {slug:{ok, chars, source_url, method, error?}}。整合进 build_outputs 的 summaries 由 agent 完成。
"""
import sys, os, json, re, time, argparse, ssl, urllib.parse, urllib.request

UA = {"User-Agent": "lit-scout-fulltext/0.1 (academic use)"}
TIMEOUT = 60


def _ctx():
    try:
        import truststore; return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception: pass
    try:
        import certifi; return ssl.create_default_context(cafile=certifi.where())
    except Exception: return ssl.create_default_context()


CTX = _ctx()


def _check_libs():
    """返回可用的抽取后端列表; 一个都没有就给指引并退出。"""
    backends = []
    try:
        import pymupdf4llm  # noqa
        backends.append("pymupdf4llm")
    except Exception:
        pass
    try:
        import fitz  # noqa  (PyMuPDF)
        backends.append("fitz")
    except Exception:
        pass
    try:
        import pdfplumber  # noqa
        backends.append("pdfplumber")
    except Exception:
        pass
    if not backends:
        sys.stderr.write(
            "[fetch_fulltext] 未找到 PDF 抽取库。请建专用 venv 后安装, 并用该 venv 的 python 运行本脚本:\n"
            "  python -m venv .venv\n"
            "  .venv/Scripts/python -m pip install -r requirements-pdf.txt   # Windows\n"
            "  .venv/Scripts/python scripts/fetch_fulltext.py ...\n")
        sys.exit(2)
    return backends


def _get_bytes(url, retries=2):
    """带重试: 本机/精简环境 HTTPS 偶发 SSL EOF, 重试能救回, 免得把网络抖动当成'无全文'。"""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
                return r.read()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2)
    raise last


def _get_json(url):
    return json.loads(_get_bytes(url).decode("utf-8", "replace"))


def resolve_pdf_url(rec, email=None):
    """返回 (pdf_url, note) 或 (None, 原因)。只取开放获取。"""
    arxiv = (rec.get("arxiv") or rec.get("resolved_arxiv") or "").strip()
    if arxiv:
        arxiv = re.sub(r"v\d+$", "", arxiv.rsplit("/", 1)[-1])
        return f"https://arxiv.org/pdf/{arxiv}.pdf", "arxiv"
    doi = (rec.get("doi") or rec.get("resolved_doi") or "").strip().replace("https://doi.org/", "")
    title = rec.get("title") or rec.get("match_title")
    # OpenAlex: 按 doi 或标题找开放获取 url
    query_failed = False
    try:
        if doi:
            w = _get_json("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi))
        elif title:
            res = _get_json("https://api.openalex.org/works?per-page=1&filter=title.search:"
                            + urllib.parse.quote(title)).get("results", [])
            w = res[0] if res else None
        else:
            w = None
        if w:
            loc = w.get("best_oa_location") or {}
            oa = w.get("open_access") or {}
            # 优先显式 pdf_url, 再 oa_url(可能是落地页); 不按 .pdf 后缀过滤——
            # 很多 OA PDF 链接没有 .pdf 后缀, 真伪交给下载后的 %PDF 魔数判定。
            url = loc.get("pdf_url") or oa.get("oa_url")
            if url:
                return url, "openalex-oa"
    except Exception:
        query_failed = True   # 网络/限流失败 ≠ 无 OA, 分开报, 提示可重试
    # Unpaywall 兜底(需 email)
    if doi and email:
        try:
            u = _get_json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}")
            loc = u.get("best_oa_location") or {}
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"], "unpaywall"
        except Exception:
            query_failed = True
    if query_failed:
        return None, "OA 查询失败(网络/限流, 已重试); 建议稍后重跑, 勿当作无全文"
    return None, "无开放获取 PDF(可能付费墙); 回退摘要"


def extract(pdf_path, backends):
    """按后端质量顺序抽取, 返回 (text, method)。"""
    if "pymupdf4llm" in backends:
        try:
            import pymupdf4llm
            md = pymupdf4llm.to_markdown(pdf_path)
            if md and md.strip():
                return md, "pymupdf4llm"
        except Exception as e:
            sys.stderr.write(f"[fetch_fulltext] pymupdf4llm 失败, 回退: {e}\n")
    if "fitz" in backends:
        try:
            import fitz
            doc = fitz.open(pdf_path)
            txt = "\n".join(p.get_text() for p in doc)
            doc.close()
            if txt.strip():
                return txt, "fitz"
        except Exception as e:
            sys.stderr.write(f"[fetch_fulltext] fitz 失败, 回退: {e}\n")
    if "pdfplumber" in backends:
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                txt = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
            if txt.strip():
                return txt, "pdfplumber"
        except Exception as e:
            sys.stderr.write(f"[fetch_fulltext] pdfplumber 失败: {e}\n")
    return "", "none"


def process(rec, outdir, backends, email=None):
    slug = rec.get("slug") or rec.get("title", "paper")[:40]
    url, note = resolve_pdf_url(rec, email)
    if not url:
        return {"ok": False, "error": note}
    try:
        data = _get_bytes(url)
    except Exception as e:
        return {"ok": False, "source_url": url, "error": f"下载失败: {type(e).__name__}: {str(e)[:80]}"}
    if not data[:5].startswith(b"%PDF"):
        return {"ok": False, "source_url": url, "error": "下载内容非 PDF(可能是落地页/被拦)"}
    tmp = os.path.join(outdir, slug + ".pdf")
    os.makedirs(outdir, exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(data)
    text, method = extract(tmp, backends)
    try:
        os.remove(tmp)   # 默认不留 PDF(版权/体积); 要留改这里
    except OSError:
        pass
    if not text.strip():
        return {"ok": False, "source_url": url, "method": method, "error": "PDF 抽取为空"}
    mdpath = os.path.join(outdir, slug + ".md")
    with open(mdpath, "w", encoding="utf-8") as f:
        f.write(f"<!-- source: {url} ({note}) · method: {method} -->\n\n" + text)
    return {"ok": True, "source_url": url, "method": method, "chars": len(text), "path": mdpath}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", help="corpus.json 或 [{slug,arxiv?,doi?,title?}] 列表")
    ap.add_argument("--arxiv"); ap.add_argument("--doi"); ap.add_argument("--title")
    ap.add_argument("--out", default="fulltext", help="全文 markdown 落盘目录")
    ap.add_argument("--email", help="Unpaywall 兜底要用的邮箱(礼貌)")
    a = ap.parse_args()
    backends = _check_libs()
    if a.inp:
        raw = json.loads(open(a.inp, encoding="utf-8").read())
        recs = raw.get("papers", raw) if isinstance(raw, dict) else raw
    elif a.arxiv or a.doi:
        recs = [{"slug": (a.arxiv or a.doi).replace("/", "_"), "arxiv": a.arxiv, "doi": a.doi, "title": a.title}]
    else:
        sys.stderr.write("需要 --in 或 --arxiv/--doi\n"); sys.exit(1)
    manifest = {}
    for rec in recs:
        slug = rec.get("slug") or (rec.get("title", "paper")[:40])
        manifest[slug] = process(rec, a.out, backends, a.email)
        sys.stderr.write(f"  {slug}: {'✓' if manifest[slug]['ok'] else '✗ '+manifest[slug].get('error','')}\n")
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
