#!/usr/bin/env python3
"""AoC Memory - persistent memory for AI agents based on Ant Colony Optimization.

Store : ~/.ant-memory/trails.json (+ archive.json for pruned entries; override with ANT_MEMORY_DIR)
Math  : P = tau^alpha * eta^beta | evaporation tau *= (1-rho)^idle_days | prune tau < tau_min
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

STORE_DIR = os.environ.get("ANT_MEMORY_DIR") or os.path.expanduser("~/.ant-memory")
TRAILS = os.path.join(STORE_DIR, "trails.json")
ARCHIVE = os.path.join(STORE_DIR, "archive.json")
LOCK = os.path.join(STORE_DIR, "store.lock")

ALPHA, BETA = 1.0, 2.0   # pheromone vs local relevance weight (relevance dominates)
RHO = 0.01               # evaporation per idle day
K = 0.1                  # default reinforcement when a trail proves useful
TAU_MIN = 0.05           # below this = forgotten
SPIKE = 0.50             # extra evaporation on contradiction

STOP = set("yang dan di ke dari untuk pada dengan adalah itu ini the a an of to in on for "
           "is are be as at by or if with this that not no".split())


def now():
    return datetime.now(timezone.utc)


def load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _salvage(path, default)


def _salvage(path, default):
    """Corrupted file: salvage every intact {...} object, back up the rest, keep running."""
    raw = open(path, encoding="utf-8", errors="replace").read()
    objs, depth, start = [], 0, None
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    objs.append(json.loads(raw[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    if not objs:
        bak = path + ".corrupt." + now().strftime("%Y%m%d%H%M%S")
        os.replace(path, bak)
        save(path, default)
        print("! file fully corrupted, nothing salvageable; backup: %s" % bak, file=sys.stderr)
        return default
    data = objs if isinstance(default, list) else objs[0]
    bak = path + ".corrupt." + now().strftime("%Y%m%d%H%M%S")
    os.replace(path, bak)
    save(path, data)
    print("! corrupted file salvaged, recovered %d objects; backup: %s" % (len(objs), bak), file=sys.stderr)
    return data


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


@contextmanager
def locked():
    """Cross-process exclusive lock (flock) around every read->modify->write."""
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def jaccard(a, b):
    return len(a & b) / len(a | b) if (a | b) else 0.0


def tokens(text):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 1 and t not in STOP}


def mat(e, touch=False):
    """Materialize evaporation: tau *= (1-rho)^idle_days since last_access."""
    last = datetime.fromisoformat(e["last_access"])
    idle = max(0.0, (now() - last).total_seconds() / 86400)
    e["tau"] = round(e["tau"] * ((1.0 - RHO) ** idle), 6)
    if touch:
        e["last_access"] = now().isoformat()
    return e


def eta(e, qtok):
    """Desirability = local knowledge (query overlap) * prior knowledge (success history)."""
    hay = tokens(e["content"] + " " + " ".join(e.get("tags", [])))
    loc = (len(qtok & hay) / len(qtok)) if qtok else 0.0
    s, f = e.get("success", 0), e.get("fail", 0)
    prior = 0.5 if (s + f) == 0 else s / (s + f)
    return round(loc * (0.5 + 0.5 * prior), 6)


def find(entries, prefix):
    m = [e for e in entries if e["id"].startswith(prefix)]
    if len(m) != 1:
        sys.exit("! id '%s' %s" % (prefix, "ambiguous" if len(m) > 1 else "not found"))
    return m[0]


def cmd_add(a):
    with locked():
        trails = load(TRAILS, [])
        tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
        i = hashlib.sha1(a.content.encode()).hexdigest()[:8]
        if a.force:
            i = hashlib.sha1((a.content + now().isoformat()).encode()).hexdigest()[:8]
        for e in trails:
            if e["id"] == i:
                mat(e, touch=True)
                e["tau"] = round(e["tau"] + a.k, 6)
                save(TRAILS, trails)
                print("= %s already known, treating as re-learn: tau += %s -> %s" % (i, a.k, e["tau"]))
                return
        # near-duplicate: very similar content (jaccard >= 0.8) -> merge into the older trail
        qtok = tokens(a.content)
        for e in trails:
            if jaccard(qtok, tokens(e["content"])) >= 0.8:
                if a.force:
                    break
                mat(e, touch=True)
                e["tau"] = round(e["tau"] + a.k, 6)
                e["tags"] = sorted(set(e.get("tags", [])) | set(tags))
                save(TRAILS, trails)
                print("~ similar to %s (J=%.2f) -> merged: tau += %s -> %s" % (
                    e["id"], jaccard(qtok, tokens(e["content"])), a.k, e["tau"]))
                return
        t = (now() - timedelta(days=a.age_days)).isoformat()
        trails.append(dict(id=i, content=a.content, tags=tags, tau=a.tau,
                           success=0, fail=0, created=t, last_access=t))
        save(TRAILS, trails)
        print("+ %s tau=%s [%s] :: %s" % (i, a.tau, ",".join(tags), a.content[:70]))


def cmd_recall(a):
    with locked():
        trails = load(TRAILS, [])
        qtok = tokens(a.query)
        scored = []
        for e in trails:
            mat(e)
            scored.append(((e["tau"] ** ALPHA) * (eta(e, qtok) ** BETA), e))
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:a.n]
        for n, (p, e) in enumerate(top, 1):
            print("#%d P=%.4f tau=%.3f eta=%.3f id=%s [%s]" % (
                n, p, e["tau"], eta(e, qtok), e["id"], ",".join(e["tags"])))
            print("   %s" % e["content"][:110])
        if not top:
            print("(no matching trails yet)")
        for _, e in top:
            e["last_access"] = now().isoformat()
        save(TRAILS, trails)


def cmd_reinforce(a):
    with locked():
        trails = load(TRAILS, [])
        e = find(trails, a.id)
        mat(e, touch=True)
        e["tau"] = round(e["tau"] + a.k, 6)
        e["success"] = e.get("success", 0) + 1
        save(TRAILS, trails)
        print("^ %s tau=%s success=%d" % (e["id"], e["tau"], e["success"]))


def cmd_fail(a):
    with locked():
        trails = load(TRAILS, [])
        e = find(trails, a.id)
        mat(e, touch=True)
        e["fail"] = e.get("fail", 0) + 1
        e["tau"] = round(e["tau"] * 0.9, 6)
        save(TRAILS, trails)
        print("v %s tau=%s fail=%d" % (e["id"], e["tau"], e["fail"]))


def cmd_spike(a):
    with locked():
        trails = load(TRAILS, [])
        e = find(trails, a.id)
        mat(e, touch=True)
        e["tau"] = round(e["tau"] * (1.0 - SPIKE), 6)
        if a.superseded_by:
            e["superseded_by"] = a.superseded_by
        save(TRAILS, trails)
        print("~ %s spike evaporation: tau=%s" % (e["id"], e["tau"]))


def cmd_decay(a):
    with locked():
        trails = load(TRAILS, [])
        for e in trails:
            mat(e)
        keep = [e for e in trails if e["tau"] >= TAU_MIN]
        gone = [e for e in trails if e["tau"] < TAU_MIN]
        if gone:
            arch = load(ARCHIVE, [])
            for e in gone:
                e["archived_reason"] = "evaporated"
                e["archived_at"] = now().isoformat()
            save(ARCHIVE, arch + gone)
        save(TRAILS, keep)
        print("evaporation done: %d kept, %d archived (tau < %s)" % (len(keep), len(gone), TAU_MIN))


def cmd_list(a):
    trails = load(TRAILS, [])
    for e in sorted(trails, key=lambda x: -x["tau"]):
        idle = (now() - datetime.fromisoformat(e["last_access"])).total_seconds() / 86400
        print("%s tau=%.3f s/f=%d/%d idle=%.1fd [%s] %s" % (
            e["id"], e["tau"], e.get("success", 0), e.get("fail", 0),
            idle, ",".join(e["tags"]), e["content"][:60]))


def cmd_forget(a):
    with locked():
        trails = load(TRAILS, [])
        e = find(trails, a.id)
        trails.remove(e)
        e["archived_reason"] = "manual"
        e["archived_at"] = now().isoformat()
        save(ARCHIVE, load(ARCHIVE, []) + [e])
        save(TRAILS, trails)
        print("x %s -> archive" % e["id"])


def main():
    p = argparse.ArgumentParser(description="AoC Memory (ACO-based memory store for AI agents)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("add", help="store a new memory")
    sp.add_argument("content")
    sp.add_argument("--tags", help="comma-separated tags")
    sp.add_argument("--tau", type=float, default=1.0)
    sp.add_argument("--k", type=float, default=K)
    sp.add_argument("--force", action="store_true",
                    help="store even if similar to an existing trail (skip merge)")
    sp.add_argument("--age-days", type=float, default=0.0, help="backdate creation (for testing decay)")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("recall", help="retrieve memories: ranked by P = tau^a * eta^b")
    sp.add_argument("query")
    sp.add_argument("--n", type=int, default=5)
    sp.set_defaults(fn=cmd_recall)

    sp = sub.add_parser("reinforce", help="tau += K, success+1")
    sp.add_argument("id")
    sp.add_argument("--k", type=float, default=K)
    sp.set_defaults(fn=cmd_reinforce)

    sp = sub.add_parser("fail", help="memory did not help: fail+1, tau *= 0.9")
    sp.add_argument("id")
    sp.set_defaults(fn=cmd_fail)

    sp = sub.add_parser("spike", help="contradiction: extra evaporation")
    sp.add_argument("id")
    sp.add_argument("--superseded-by", dest="superseded_by", default=None)
    sp.set_defaults(fn=cmd_spike)

    sp = sub.add_parser("decay", help="global evaporation + prune tau < TAU_MIN")
    sp.set_defaults(fn=cmd_decay)

    sp = sub.add_parser("list", help="list all trails")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("forget", help="archive manually")
    sp.add_argument("id")
    sp.set_defaults(fn=cmd_forget)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
