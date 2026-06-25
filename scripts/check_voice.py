#!/usr/bin/env python
"""check_voice.py — lit-scout 散文「去 AI 味」校验 + survey 草稿引用硬校验。

两类检查（对应 references/voice.md）:
  1) AI 味扫描(WARN, 不影响退出码): 套话/结构套/标点滥用/空泛形容。启发式, 故只提示不硬失败。
  2) survey-draft.md 的 \\cite 解析(硬, 影响退出码): 草稿里每个 \\cite{key} 必须命中 verified.bib,
     否则 FAIL——综述/论文里绝不能出现没核过的引用(0 幻觉在写作侧的延伸)。

独立用:  python check_voice.py --out <dir> [--summaries summaries.json]
也被 check_outputs.py import 复用(scan_ai_tells / extract_cites / bib_citekeys)。
退出码: survey \\cite 有未解析 -> 1; 否则 0(AI 味仅 WARN)。
"""
import sys, os, re, json, argparse

# 套话/空泛形容(命中即 WARN)。词表按真实 lit-scout 产物(城市低空无人机调研)校准过:
# 既保留通用 AI 套话, 也补上实测高频的连接词脚手架与空泛赞美。
PHRASES = [
    # 通用套话
    "值得注意的是", "需要指出的是", "值得一提的是", "综上所述", "综上", "总而言之",
    "总的来说", "总体而言", "综观", "扮演着", "扮演了", "至关重要", "不可或缺",
    "具有重要意义", "具有重要的意义",
    # 实测高频: 连接词脚手架 / 万能过渡
    "可以清晰地", "不难看出", "显而易见", "典型代表", "这一阶段的", "与此同时，",
    # 实测高频: 空泛赞美 / 填充
    "广泛应用", "深入研究", "长足发展", "日益重要", "高度一致", "各有侧重",
    # 对冲口头禅
    "在一定程度上", "从某种程度上",
]
# 结构套 / 空泛句式用正则更准
PATTERNS = [
    (r"旨在[^，。；\n]{0,12}", "空泛目的句『旨在…』"),
    (r"在[^，。；\n]{1,10}方面", "套话框架『在…方面』"),
    (r"首先[^。\n]{0,40}。[^。\n]{0,60}其次[^。\n]{0,40}。[^。\n]{0,80}(最后|最终)", "机械三段『首先…其次…最后』"),
    (r"不仅[^，。\n]{1,30}(而且|还|也)", "对仗堆叠『不仅…而且』"),
    # 实测: 每节对称收尾(AI 爱给每个小节配一句同模板总结)
    (r"回答的是[^。\n]{0,40}的问题", "对称收尾『回答的是…的问题』"),
    (r"标志着[^。\n]{0,30}(转变|里程碑|跃迁|起点)", "拔高收尾『标志着…转变』"),
    # 实测: 空泛因果填充
    (r"为[^，。\n]{0,20}提供[^，。\n]{0,12}(支持|支撑|基础)", "空泛因果『为…提供…支撑』"),
]
HEDGES = ["可能", "也许", "或许", "大概", "似乎", "在一定程度上", "某种程度上", "或多或少"]


def scan_ai_tells(text, where=""):
    """返回 WARN 列表(每项 dict)。启发式, 只提示。"""
    warns = []
    if not text or not text.strip():
        return warns
    for p in PHRASES:
        n = text.count(p)
        if n:
            warns.append({"where": where, "kind": "套话", "hit": p, "count": n})
    for rx, label in PATTERNS:
        m = re.findall(rx, text)
        if m:
            warns.append({"where": where, "kind": "结构/空泛", "hit": label, "count": len(m)})
    # em-dash 滥用: 中文破折号 —— 超过 prose 段落数的一半
    dash = text.count("——")
    if dash >= 4:
        warns.append({"where": where, "kind": "标点", "hit": "破折号(——)偏多", "count": dash})
    # hedge 密度: 每 200 字超过 3 个对冲词 -> 提示
    hedge_n = sum(text.count(h) for h in HEDGES)
    if len(text) >= 120 and hedge_n / max(1, len(text)) > 0.015:
        warns.append({"where": where, "kind": "过度对冲", "hit": f"hedge 词 {hedge_n} 个/{len(text)} 字", "count": hedge_n})
    return warns


def bib_citekeys(bib_text):
    return {k.strip().lower() for k in re.findall(r"^@\w+\{([^,]+),", bib_text, re.M)}


def extract_cites(survey_text):
    """抽行内引用 key(小写)。支持两种格式:
      - LaTeX: \\cite/\\citep/\\citet{a,b}
      - lit-scout 默认: [citekey] (含 4 位年份, 排除 markdown 链接 [x](...) 和无年份的普通方括号)
    含年份这一条同时滤掉了 [citekey] 这种字面占位词与 [1] 这种数字引用。"""
    keys = []
    for m in re.finditer(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]+)\}", survey_text):
        keys += [k.strip().lower() for k in m.group(1).split(",") if k.strip()]
    for m in re.finditer(r"\[([A-Za-z][A-Za-z0-9]*(?:19|20)\d{2})\](?!\()", survey_text):
        keys.append(m.group(1).strip().lower())
    return keys


def check_survey_cites(survey_text, citekeys):
    """返回未解析的 \\cite key 列表(命中即应 FAIL)。"""
    used = extract_cites(survey_text)
    return [k for k in used if k not in citekeys], used


def _read(path):
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--summaries", help="可选 summaries.json, 一并扫 AI 味")
    a = ap.parse_args()
    O = a.out
    warns, fails = [], []

    report = _read(os.path.join(O, "report.md"))
    warns += scan_ai_tells(report, "report.md")
    if a.summaries and os.path.exists(a.summaries):
        sj = json.loads(_read(a.summaries) or "{}")
        for slug, v in sj.items():
            txt = v.get("summary", "") if isinstance(v, dict) else (v if isinstance(v, str) else "")
            warns += scan_ai_tells(txt, f"summaries[{slug}]")

    survey_path = os.path.join(O, "survey-draft.md")
    if os.path.exists(survey_path):
        survey = _read(survey_path)
        warns += scan_ai_tells(survey, "survey-draft.md")
        keys = bib_citekeys(_read(os.path.join(O, "verified.bib")))
        unresolved, used = check_survey_cites(survey, keys)
        print(f"survey-draft.md: {len(used)} 个 \\cite, {len(unresolved)} 个未解析")
        if unresolved:
            fails.append(f"survey \\cite 未命中 verified.bib(疑似未核引用): {sorted(set(unresolved))}")

    if warns:
        print(f"\n[AI 味 WARN] {len(warns)} 处(启发式, 不阻断交付, 建议按 voice.md 改写):")
        for w in warns:
            print(f"  - {w['where']}: {w['kind']} 『{w['hit']}』×{w['count']}")
    else:
        print("[AI 味] 未命中黑名单。")

    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("\nvoice 校验通过(\\cite 全部解析" + ("，无 AI 味告警" if not warns else f"，{len(warns)} 处 WARN 待改") + ")。")
    sys.exit(0)


if __name__ == "__main__":
    main()
