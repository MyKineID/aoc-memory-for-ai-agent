#!/usr/bin/env python3
"""Smoke tests for AoC Memory. Run: python3 tests/test_smoke.py

Each test runs the real CLI in an isolated store (ANT_MEMORY_DIR temp dir).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "ant_memory.py")


def run(*args, store):
    env = dict(os.environ, ANT_MEMORY_DIR=store)
    return subprocess.run([sys.executable, ENGINE, *args],
                          capture_output=True, text=True, env=env)


def trails(store):
    with open(os.path.join(store, "trails.json"), encoding="utf-8") as f:
        return json.load(f)


def first_id(out):
    m = re.search(r"^.\s+([0-9a-f]{8})\s", out, re.M)
    return m.group(1) if m else None


class AoCMemoryTest(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="aoc-test-")

    def test_add_and_list(self):
        r = run("add", "deploy preview runs on every push", "--tags", "ci,deploy", store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr)
        tid = first_id(r.stdout)
        self.assertIsNotNone(tid)
        r = run("list", store=self.store)
        self.assertIn(tid, r.stdout)
        self.assertEqual(len(trails(self.store)), 1)

    def test_exact_duplicate_is_relearn(self):
        run("add", "cache warmup takes 90 seconds", store=self.store)
        r = run("add", "cache warmup takes 90 seconds", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertIn("re-learn", r.stdout)
        ts = trails(self.store)
        self.assertEqual(len(ts), 1)
        self.assertAlmostEqual(ts[0]["tau"], 1.1, places=4)

    def test_near_duplicate_merges(self):
        run("add", "deploy kiwstudio via git push to production server", store=self.store)
        r = run("add", "deploy kiwstudio via git push on production server", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertIn("merged", r.stdout)
        self.assertEqual(len(trails(self.store)), 1)

    def test_force_bypasses_merge(self):
        run("add", "release checklist step one", store=self.store)
        r = run("add", "release checklist step one", "--force", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(trails(self.store)), 2)

    def test_recall_ranks_by_keyword(self):
        run("add", "nginx rate limit is set at 30 req/min", "--tags", "nginx", store=self.store)
        run("add", "postgres backup runs nightly at 2 am", "--tags", "db", store=self.store)
        r = run("recall", "nginx rate limit", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertIn("nginx rate limit is set", r.stdout)
        self.assertNotIn("postgres backup", r.stdout)

    def test_recall_no_match(self):
        run("add", "completely unrelated fact about turtles", store=self.store)
        r = run("recall", "quantum flux capacitor zzq", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no matching trails", r.stdout)

    def test_reinforce_and_fail(self):
        tid = first_id(run("add", "staging db port is 5433", store=self.store).stdout)
        r = run("reinforce", tid[:4], store=self.store)
        self.assertIn("success=1", r.stdout)
        r = run("fail", tid, store=self.store)
        self.assertIn("fail=1", r.stdout)
        e = trails(self.store)[0]
        self.assertEqual(e["success"], 1)
        self.assertEqual(e["fail"], 1)
        self.assertLess(e["tau"], 1.0)

    def test_spike_evaporates(self):
        tid = first_id(run("add", "old api version v1 will be removed", store=self.store).stdout)
        r = run("spike", tid, store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertAlmostEqual(trails(self.store)[0]["tau"], 0.5, places=4)

    def test_decay_archives_old_trail(self):
        run("add", "ancient fact nobody accessed", "--age-days", "400", store=self.store)
        r = run("decay", store=self.store)
        self.assertIn("1 archived", r.stdout)
        self.assertEqual(trails(self.store), [])
        with open(os.path.join(self.store, "archive.json"), encoding="utf-8") as f:
            arch = json.load(f)
        self.assertEqual(arch[0]["archived_reason"], "evaporated")

    def test_forget_moves_to_archive(self):
        tid = first_id(run("add", "temporary note to forget later", store=self.store).stdout)
        r = run("forget", tid, store=self.store)
        self.assertIn("-> archive", r.stdout)
        self.assertEqual(trails(self.store), [])
        with open(os.path.join(self.store, "archive.json"), encoding="utf-8") as f:
            arch = json.load(f)
        self.assertEqual(arch[0]["archived_reason"], "manual")

    def test_corruption_salvage(self):
        run("add", "entry that survives corruption", store=self.store)
        good = trails(self.store)[0]
        with open(os.path.join(self.store, "trails.json"), "w", encoding="utf-8") as f:
            # realistic truncated write: intact object followed by garbage
            f.write(json.dumps(good) + "\nTRUNCATED GARBAGE no closing brace here {")
        r = run("list", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertIn("salvaged", r.stderr)
        self.assertIn("entry that survives corruption", r.stdout)

    def test_bad_id_exits_nonzero(self):
        run("add", "only one entry here", store=self.store)
        r = run("reinforce", "ffffffff", store=self.store)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stderr)

    def test_concurrent_adds(self):
        def add(i):
            return run("add", "parallel stress entry marker%04d payload checksum%05d" % (i, i * 7919 + 13),
                       store=self.store)

        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(add, range(10)))
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(trails(self.store)), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
