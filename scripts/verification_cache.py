#!/usr/bin/env python
"""verification_cache.py — verify_citations.py 的持久化验证缓存。

一篇论文在多次运行(跨草稿、跨追踪窗口、重叠主题)里只需核验一次。本地 SQLite,
默认 ~/.cache/lit-scout/verification.db, 可用环境变量 LIT_SCOUT_CACHE 覆盖, TTL 90 天。

只缓存**稳定**判定: confirmed / rejected / 以及非网络失败导致的 review。
网络失败(query_errors)产生的 fail-safe review 绝不缓存(瞬时态, 缓存会固化错误)。
缓存键含 threshold, 阈值变化时不会错用旧档。

作为模块用(verify_citations.py import), 也可独立查看/清理:
  python verification_cache.py --stats
  python verification_cache.py --purge        # 清过期
  python verification_cache.py --clear         # 清全部
"""
import os, json, time, sqlite3, hashlib, argparse, re

TTL_SECONDS = 90 * 24 * 3600


def _default_path():
    env = os.environ.get("LIT_SCOUT_CACHE")
    if env:
        return env
    home = os.path.expanduser("~")
    return os.path.join(home, ".cache", "lit-scout", "verification.db")


def _norm(s):
    if not s:
        return ""
    s = str(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def make_key(cand, threshold):
    """由影响结果的输入(标题/doi/arxiv/年份/阈值)确定性生成键。"""
    payload = json.dumps({
        "t": _norm(cand.get("title")),
        "d": (cand.get("doi") or "").strip().lower(),
        "a": (cand.get("arxiv") or "").strip().lower(),
        "y": cand.get("year"),
        "th": round(float(threshold), 4),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, path=None, ttl=TTL_SECONDS, enabled=True):
        self.enabled = enabled
        self.ttl = ttl
        self.path = path or _default_path()
        self.conn = None
        if not enabled:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.conn = sqlite3.connect(self.path)
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS verify (k TEXT PRIMARY KEY, tier TEXT, info TEXT, ts REAL)")
            self.conn.commit()
        except Exception:
            self.conn = None  # 缓存不可用时静默降级, 不影响核验正确性

    def get(self, key, now=None):
        if not self.conn:
            return None
        now = now if now is not None else time.time()
        try:
            row = self.conn.execute("SELECT tier, info, ts FROM verify WHERE k=?", (key,)).fetchone()
        except Exception:
            return None
        if not row:
            return None
        tier, info, ts = row
        if now - ts > self.ttl:
            return None
        try:
            return tier, json.loads(info)
        except Exception:
            return None

    def put(self, key, tier, info, now=None):
        if not self.conn:
            return
        # 不缓存网络失败导致的 review(瞬时态)
        if info.get("query_errors"):
            return
        if tier not in ("confirmed", "rejected", "review"):
            return
        now = now if now is not None else time.time()
        try:
            self.conn.execute("INSERT OR REPLACE INTO verify VALUES (?,?,?,?)",
                              (key, tier, json.dumps(info, ensure_ascii=False), now))
            self.conn.commit()
        except Exception:
            pass

    def purge(self, now=None):
        if not self.conn:
            return 0
        now = now if now is not None else time.time()
        cur = self.conn.execute("DELETE FROM verify WHERE ? - ts > ?", (now, self.ttl))
        self.conn.commit()
        return cur.rowcount

    def stats(self):
        if not self.conn:
            return {"enabled": False, "path": self.path}
        n = self.conn.execute("SELECT COUNT(*) FROM verify").fetchone()[0]
        by = dict(self.conn.execute("SELECT tier, COUNT(*) FROM verify GROUP BY tier").fetchall())
        return {"enabled": True, "path": self.path, "total": n, "by_tier": by}

    def clear(self):
        if self.conn:
            self.conn.execute("DELETE FROM verify")
            self.conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    c = Cache(path=a.path)
    if a.clear:
        c.clear()
        print("cleared")
    if a.purge:
        print(f"purged {c.purge()} expired entries")
    print(json.dumps(c.stats(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
