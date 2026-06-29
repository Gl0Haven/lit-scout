#!/usr/bin/env python
"""check_claims.py — claim 层 faithfulness 的确定性证据定位器（配 faithfulness_agent）。

0 幻觉的两条通道：locator(引用是否存在，verify_citations 已守) + faithfulness(挂在某篇上的
论断是否被原文支持，更难的一半)。本脚本做**机械可判**的部分，把语义判断留给 faithfulness_agent：

  - metric 类断言（"X 在 Set5 上 PSNR=24.1"）：在该篇全文里定位 metric/dataset 词，抽附近的数字，
    判定 claimed 值是否出现 → supported / mismatch(找到 metric 但数字对不上) / not-found / unverifiable。
  - 关系/泛断言（"A 改进了 B 的注意力分支"）：按关键词重叠定位**最相关的几句**作为证据返回，
    verdict 标 evidence-found，最终是否成立由 faithfulness_agent(LLM) 判。

输入全文来自 `fetch_fulltext.py` 抽的 `<slug>.md`（拿不到全文时退化到摘要，标 unverifiable，不臆断）。
只用标准库，operate on 已抽好的文本，可用系统 python 跑。

用法：
  python check_claims.py --claims claims.json --fulltext fulltext/ > claim_audit.json
claims.json: [{"slug":"", "claim":"原话", "kind":"metric|relation", "metric":"PSNR", "dataset":"Set5", "value":"24.1"}]
  （kind=metric 时给 metric/value，dataset 可选；kind=relation 只需 claim 文本）
输出: {slug:[{claim,kind,verdict,value_claimed,values_found,evidence,note}]}
"""
import sys, os, json, re, argparse

NUM = re.compile(r"\d+(?:\.\d+)?")


def load_text(slug, ftdir):
    p = os.path.join(ftdir, slug + ".md")
    if os.path.exists(p):
        return open(p, encoding="utf-8", errors="replace").read()
    return None


def split_sentences(text):
    # 粗切句; markdown 表格/换行也切, 保证能定位到含数字的小段
    parts = re.split(r"(?<=[.!?。])\s+|\n+|\|", text)
    return [s.strip() for s in parts if len(s.strip()) > 3]


def _squash(s):
    """归一化: 去非字母数字(吸收 PDF 连字符断裂, 如 English-to-German↔Englishto-German)。"""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _close(a, b):
    try:
        return abs(float(a) - float(b)) < 0.05
    except ValueError:
        return a == b


def check_metric(claim, text):
    """定位 metric 语境, 抽附近数字, 判 claimed 值是否出现。
    数字从**所有含 metric 的句子**收集(union), dataset 只用来优选证据句、不作硬过滤——
    否则 PDF 连字符断裂会把真句子滤掉, 造成对真实指标的假性 mismatch。"""
    metric = (claim.get("metric") or "").strip()
    dataset = (claim.get("dataset") or "").strip()
    value = str(claim.get("value") or "").strip()
    sents = split_sentences(text)
    metric_re = re.compile(re.escape(metric), re.I) if metric else None
    metric_sents = [s for s in sents if (metric_re.search(s) if metric_re
                    else (dataset and _squash(dataset) in _squash(s)))]
    if not metric_sents:
        return {"verdict": "not-found", "values_found": [], "evidence": "",
                "note": f"全文未找到 metric『{metric}』的语境"}
    values_found = sorted({v for s in metric_sents for v in NUM.findall(s)}, key=lambda x: float(x))
    ds = _squash(dataset) if dataset else ""
    # 证据句优选: 同时含 claimed 值 + dataset > 含值 > 含 dataset > 第一句
    def pick(pred):
        return next((s for s in metric_sents if pred(s)), None)
    ev_s = (pick(lambda s: value and any(_close(v, value) for v in NUM.findall(s)) and (not ds or ds in _squash(s)))
            or pick(lambda s: value and any(_close(v, value) for v in NUM.findall(s)))
            or pick(lambda s: ds and ds in _squash(s))
            or metric_sents[0])
    ev = ev_s[:220]
    if value and any(_close(v, value) for v in values_found):
        return {"verdict": "supported", "values_found": values_found, "evidence": ev,
                "note": f"claimed 值 {value} 在 metric 语境中找到"}
    return {"verdict": "mismatch", "values_found": values_found, "evidence": ev,
            "note": f"找到 metric 语境但未见 claimed 值 {value}; 原文附近数字: {values_found[:8]}"}


def check_relation(claim, text):
    """关键词重叠定位最相关的句子作为证据, 交给 agent 判。"""
    claim_text = claim.get("claim", "")
    kw = {w for w in re.findall(r"[A-Za-z一-鿿]{2,}", claim_text.lower()) if len(w) > 1}
    sents = split_sentences(text)
    scored = []
    for s in sents:
        sw = set(re.findall(r"[A-Za-z一-鿿]{2,}", s.lower()))
        ov = len(kw & sw)
        if ov >= 2:
            scored.append((ov, s))
    scored.sort(key=lambda x: -x[0])
    top = [s[:220] for _, s in scored[:3]]
    if not top:
        return {"verdict": "no-evidence", "evidence": [],
                "note": "全文未找到与该断言关键词重叠的句子; faithfulness_agent 应据此判 unsupported/unverifiable"}
    return {"verdict": "evidence-found", "evidence": top,
            "note": "已定位候选证据句, 是否真支持该断言由 faithfulness_agent 判定(勿仅凭关键词重叠下结论)"}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", required=True)
    ap.add_argument("--fulltext", default="fulltext", help="fetch_fulltext.py 抽的 <slug>.md 目录")
    a = ap.parse_args()
    claims = json.loads(open(a.claims, encoding="utf-8").read())
    out = {}
    for cl in claims:
        slug = cl.get("slug", "?")
        text = load_text(slug, a.fulltext)
        base = {"claim": cl.get("claim", ""), "kind": cl.get("kind", "relation"),
                "value_claimed": cl.get("value")}
        if text is None:
            res = {"verdict": "unverifiable", "evidence": "",
                   "note": f"无 {slug} 全文(未抓到或付费墙); 不臆断, 建议人工或先跑 fetch_fulltext"}
        elif cl.get("kind") == "metric":
            res = check_metric(cl, text)
        else:
            res = check_relation(cl, text)
        out.setdefault(slug, []).append({**base, **res})
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
