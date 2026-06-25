#!/usr/bin/env python
"""run_gold.py — 验证门(verify_citations.py)回归: 跑 gold-citations.json 并报混淆矩阵。

校验两条不变量(对应 SKILL.md 的 0 幻觉脊柱):
  - FP=0: 任何 fake 条目都不得进 confirmed(否则编造引用会漏进产物);
  - FN=0: 任何 real 条目都不得进 rejected(真论文不能被静默错杀; review 可接受)。

用法(需联网):
  python evals/run_gold.py [--gold evals/gold-citations.json] [--threshold 0.92] [--no-cache]
退出码: 不变量全过 0, 违反 1。
"""
import sys, os, json, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
VERIFY = os.path.join(SKILL, "scripts", "verify_citations.py")


def run_verify(cands, threshold, no_cache, sleep):
    cmd = [sys.executable, VERIFY, "--threshold", str(threshold), "--sleep", str(sleep)]
    if no_cache:
        cmd.append("--no-cache")
    p = subprocess.run(cmd, input=json.dumps(cands, ensure_ascii=False),
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        sys.stderr.write(p.stderr + "\n")
        raise SystemExit("verify_citations.py 运行失败")
    return json.loads(p.stdout)


def title_set(items):
    return {(it.get("title") or "").lower() for it in items}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=os.path.join(HERE, "gold-citations.json"))
    ap.add_argument("--threshold", type=float, default=0.92)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="每条间隔(秒); arXiv 限流 1req/3s, 太小会假性失败, 校准建议 >=1.5")
    a = ap.parse_args()
    gold = json.loads(open(a.gold, encoding="utf-8").read())
    real, fake = gold.get("real", []), gold.get("fake", [])
    verdict = run_verify(real + fake, a.threshold, a.no_cache, a.sleep)
    conf, rev, rej = title_set(verdict["confirmed"]), title_set(verdict["review"]), title_set(verdict["rejected"])

    real_t, fake_t = title_set(real), title_set(fake)
    real_confirmed = real_t & conf
    real_review = real_t & rev
    real_rejected = real_t & rej           # FN: 真论文被错杀(违反不变量)
    fake_confirmed = fake_t & conf         # FP: 编造进 confirmed(违反不变量)
    fake_rejected = fake_t & rej
    fake_review = fake_t & rev

    print(f"== gold 验证门回归 (threshold={a.threshold}) ==")
    print(f"REAL  n={len(real)}: confirmed {len(real_confirmed)} · review {len(real_review)} · rejected {len(real_rejected)}")
    print(f"FAKE  n={len(fake)}: rejected {len(fake_rejected)} · review {len(fake_review)} · confirmed {len(fake_confirmed)}")
    print(f"recall(real→confirmed) = {len(real_confirmed)}/{len(real)}")
    print(f"specificity(fake→rejected) = {len(fake_rejected)}/{len(fake)}")

    fails = []
    if fake_confirmed:
        fails.append(f"FP!=0 编造进 confirmed: {sorted(fake_confirmed)}")
    if real_rejected:
        fails.append(f"FN!=0 真论文被 rejected: {sorted(real_rejected)}")
    if fails:
        print("\nFAIL(违反 0 幻觉不变量):")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("\nPASS: 0 编造进 confirmed, 0 真论文被错杀(review 可接受)。")
    if fake_review:
        print(f"  注: {len(fake_review)} 条 fake 落 review(未误判存在, 交人工即可)。")
    sys.exit(0)


if __name__ == "__main__":
    main()
