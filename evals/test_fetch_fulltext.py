#!/usr/bin/env python
"""test_fetch_fulltext.py — fetch_fulltext.py 的离线单测(不联网)。

mock 掉网络函数, 验证纯逻辑分支:
  - resolve_pdf_url: arXiv 直出 / OpenAlex 优先 pdf_url / 退 oa_url / 真无 OA / 查询失败(区分于无 OA)
  - process: %PDF 魔数守卫(非 PDF 内容拒收)
  - extract: 用 fitz 现造一个含已知文本的 PDF, 验证真能抽出来(需 PDF venv; 没装则 SKIP)

跑(优先用 PDF venv 的 python, 才能跑 extract 那条):
  .venv/Scripts/python evals/test_fetch_fulltext.py     # Windows
退出码: 全过 0, 有失败 1。
"""
import sys, os, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import fetch_fulltext as ff

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(f"{name} — {detail}")


# 1) resolve_pdf_url: arXiv id 直出, 不联网
url, note = ff.resolve_pdf_url({"arxiv": "2010.11929"})
check("resolve:arxiv-direct", url == "https://arxiv.org/pdf/2010.11929.pdf" and note == "arxiv", f"{url} / {note}")

# 2) OpenAlex 分支: 优先 best_oa_location.pdf_url
ff._get_json = lambda u: {"best_oa_location": {"pdf_url": "http://x/p.pdf"}, "open_access": {"oa_url": "http://x/land"}}
url, note = ff.resolve_pdf_url({"doi": "10.x/y"})
check("resolve:prefer-pdf_url", url == "http://x/p.pdf", url)

# 3) 退到 open_access.oa_url
ff._get_json = lambda u: {"best_oa_location": {}, "open_access": {"oa_url": "http://x/oa"}}
url, note = ff.resolve_pdf_url({"doi": "10.x/y"})
check("resolve:fallback-oa_url", url == "http://x/oa", url)

# 4) 真无 OA: 记录存在但无 OA 字段
ff._get_json = lambda u: {"best_oa_location": {}, "open_access": {}}
url, note = ff.resolve_pdf_url({"doi": "10.x/y"})
check("resolve:no-oa", url is None and "无开放获取" in note, note)

# 5) 查询失败 != 无 OA(本轮新修的关键分支)
def _boom(u):
    raise RuntimeError("SSL EOF")
ff._get_json = _boom
url, note = ff.resolve_pdf_url({"doi": "10.x/y"})
check("resolve:query-failed-distinct", url is None and "查询失败" in note, note)

# 6) process: %PDF 魔数守卫——非 PDF 内容拒收
outdir = tempfile.mkdtemp()
ff.resolve_pdf_url = lambda rec, email=None: ("http://x/p.pdf", "openalex-oa")
ff._get_bytes = lambda u, retries=2: b"<html>not a pdf</html>"
res = ff.process({"slug": "t", "doi": "10.x"}, outdir, ["fitz"])
check("process:magic-byte-guard", res["ok"] is False and "PDF" in res.get("error", ""), str(res))

# 7) extract: 现造 PDF 验证真能抽出文本(需 fitz)
try:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "HELLO LITSCOUT abstract 12.5 BLEU on TestSet")
    pdfp = os.path.join(outdir, "gen.pdf")
    doc.save(pdfp)
    doc.close()
    text, method = ff.extract(pdfp, ff._check_libs())
    check("extract:real-pdf", "LITSCOUT" in text and "12.5" in text, f"method={method} got={text[:60]!r}")
except ImportError:
    PASS.append("extract:real-pdf — SKIP(无 PDF 库, 用 .venv python 跑可启用)")
except Exception as e:
    FAIL.append(f"extract:real-pdf — {type(e).__name__}: {e}")

print(f"== fetch_fulltext 离线单测: {len(PASS)} 过 / {len(FAIL)} 败 ==")
for p in PASS:
    print("  [PASS]", p)
for f in FAIL:
    print("  [FAIL]", f)
sys.exit(1 if FAIL else 0)
