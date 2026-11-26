import csv
from html.parser import HTMLParser
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from minesweeper import Board
from monitor.engine import ActionError, Engine, Settings
from monitor.memory import (
    REGIONS,
    Mapping,
    compare,
    fingerprints,
    parse_smaps,
    rss_totals,
)
from monitor.policy import classify, limits
from monitor.storage import Store


class CoreTests(unittest.TestCase):
    def test_smaps_disjoint_regions_and_total(self):
        rows = []
        for i, (perm, path) in enumerate(
            [
                ("r-xp", "/usr/bin/python"),
                ("rw-p", "[heap]"),
                ("rw-p", "[stack]"),
                ("rw-p", ""),
                ("rw-p", "[anon:arena]"),
                ("r--p", "/lib/a b"),
            ]
        ):
            rows += [
                f"{100 + i:x}-{101 + i:x} {perm} 0000 00:00 1 {path}\n",
                "Size: 700 kB\n",
                f"Rss: {i + 1} kB\n",
                "Pss: 0 kB\n",
            ]
        self.assertEqual(
            rss_totals(parse_smaps(rows)),
            dict(code=1, heap=2, stack=3, anon=9, other=6, total=21),
        )
        with self.assertRaises(OSError):
            parse_smaps(rows[:2])

    def test_thresholds(self):
        sample = dict.fromkeys(REGIONS, 100)
        b = limits([sample, {**sample, "heap": 150}], 0.1, 0.2)
        self.assertGreaterEqual(b["stack"]["limit"] - 100, 128)
        for val, label in [
            (b["heap"]["limit"], None),
            (b["heap"]["limit"] + 1, "warning"),
            (b["heap"]["danger"], "warning"),
            (b["heap"]["danger"] + 1, "danger"),
        ]:
            self.assertEqual(
                classify({**sample, "heap": val}, b).get("heap", {}).get("level"), label
            )

    def test_compare_partial_and_changed(self):
        def check(d):
            return compare(
                {"a": "alpha", "b": "beta"},
                {"digests": d, "errors": [], "excluded": []},
            )

        self.assertEqual(check({"a": "alpha"})["result"], "unknown")
        self.assertEqual(
            check({"a": "alpha", "b": "beta", "extra": "new"})["result"], "unknown"
        )
        self.assertEqual(check({"a": "changed"})["changes"][0]["expected"], "alpha")

    def test_mapping_hash_invariant_under_aslr(self):
        with tempfile.TemporaryFile() as mem:
            mem.write(b"same" * 2)
            mem.flush()

            def run(start):
                row = Mapping(start, start + 4, "r-xp", 0, 9, "/bin/fixture")
                with patch(
                    "builtins.open",
                    side_effect=lambda *a, **kw: os.fdopen(
                        os.dup(mem.fileno()), "rb", buffering=0
                    ),
                ):
                    return fingerprints(1, [row])

            self.assertEqual(run(0), run(4))
            self.assertEqual(run(8)["digests"], {})
            self.assertTrue(run(8)["errors"])

    def test_board(self):
        for p in [(0, 0), (2, 2), (5, 5)]:
            b = Board()
            b.flag(p)
            b.open(p)
            self.assertIsNone(b.mines)
            b.flag(p)
            b.open(p)
            self.assertNotIn(p, b.mines)
            self.assertEqual(len(b.mines), 6)
            for c in b.cells:
                if c not in b.mines:
                    b.open(c)
            self.assertEqual(b.result, "승리")
        b = Board()
        b.open((2, 2))
        b.open(next(iter(b.mines)))
        self.assertEqual(b.result, "패배")

    def test_empty_area_expands_and_flags_survive(self):
        b = Board()
        b.mines = {(5, i) for i in range(6)}
        b.flag((0, 1))
        b.open((0, 0))
        self.assertIn((4, 4), b.opened)
        self.assertNotIn((0, 1), b.opened)


class FakeProcess:
    next_pid = 5000

    def __init__(self, target):
        FakeProcess.next_pid += 1
        self.pid = FakeProcess.next_pid
        self.running, self.stopped = True, False
        self.child = type("Child", (), {"returncode": 0})()

    def initialized(self):
        return True

    def alive(self):
        return self.running

    def state(self):
        return "T" if self.stopped else "S"

    def pause(self, freeze):
        self.stopped = freeze
        return self.state()

    def close(self):
        self.running = False


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(
            self.tmp.name,
            settings=Settings(0.1, 1, 0, 2, 2),
            process_factory=FakeProcess,
        )
        self.rss = dict.fromkeys(REGIONS, 100)
        self.read = {
            "digests": {"native.so": "a" * 64},
            "excluded": ["[vdso]"],
            "errors": [],
        }
        self.engine.measure = lambda: self.rss.copy()
        self.engine.read_hashes = lambda: self.read

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def act(self, name):
        self.engine.action(name, self.engine.rev)

    def calibrate(self):
        self.act("calibrate")
        pids = set()
        for _ in range(4):
            pids.add(self.engine.process.pid)
            self.engine.next_rss = 0
            self.engine.tick()
        self.assertEqual(len(pids), 2)
        self.assertEqual(self.engine.phase, "review")
        self.assertIsNone(self.engine.store.profile(self.engine.profile))
        self.act("save")

    def watch(self):
        self.calibrate()
        self.act("start")

    def test_manual_runs_capture_late_normal_work_and_require_completion(self):
        e = self.engine
        self.act("calibrate_manual")
        with self.assertRaises(ActionError):
            self.act("finish_run")
        for run in range(2):
            for i in range(8):
                self.rss["heap"] = 100 if i < 5 else 2500
                e.next_rss = 0
                e.tick()
            self.assertEqual(e.phase, "calibrating")
            self.assertEqual(e.snapshot()["calibration"]["run"], run + 1)
            self.act("finish_run")
        self.act("save")
        self.assertEqual(e.base["samples"], 16)
        self.assertEqual(e.base["bounds"]["heap"]["max"], 2500)
        self.act("start")
        self.assertFalse(e.issues)

    def test_trusted_optional_library_absence_change_and_unseen_mapping(self):
        self.act("calibrate")
        self.engine.tick()
        normal = dict(self.read["digests"])
        plugin = {"codec.so": "c" * 64}
        self.read["digests"] = {**normal, **plugin}
        for _ in range(3):
            self.engine.next_rss = 0
            self.engine.tick()
        self.act("save")
        self.assertEqual(self.engine.base["optional_hashes"], plugin)
        self.read["digests"] = normal
        self.act("start")
        self.assertEqual(self.engine.hash["result"], "match")
        self.read["digests"] = {**normal, "unseen.so": "d" * 64}
        self.act("hash")
        self.assertEqual(self.engine.hash["result"], "unknown")
        self.read["digests"] = {**normal, "codec.so": "f" * 64}
        self.act("hash")
        self.assertEqual(self.engine.phase, "frozen")

    def test_targets_have_independent_bounds_logs_and_revisions(self):
        e = self.engine
        self.watch()
        original_base = e.base
        with self.assertRaises(ActionError):
            e.select("minesweeper", e.rev)
        self.act("close")
        stale = e.rev
        e.select("minesweeper", stale)
        with self.assertRaises(ActionError):
            e.action("launch", stale)
        self.assertIsNone(e.base)
        self.assertIsNone(e.hash)
        self.assertFalse(e.history)
        self.assertEqual(e.store.events(e.profile), [])
        self.rss["heap"] = 6000
        self.watch()
        self.assertNotEqual(e.base["bounds"]["heap"], original_base["bounds"]["heap"])
        self.act("close")
        client = create_app(e).test_client()
        rows = client.get("/api/events?target=viewer").json["events"]
        self.assertEqual({row["name"] for row in rows}, {"viewer"})
        self.assertEqual(client.get("/api/events?target=absent").status_code, 400)
        stream = client.get("/api/report.csv?target=minesweeper", buffered=False)
        e.select("viewer", e.rev)
        self.assertEqual(e.base, original_base)
        report = list(csv.reader(io.StringIO(stream.text.lstrip("\ufeff"))))
        self.assertEqual({row[4] for row in report[1:]}, {"minesweeper"})
        stream.close()

    def test_unknown_hash_revokes_existing_approval(self):
        self.watch()
        self.rss["heap"] = self.engine.base["bounds"]["heap"]["limit"] + 1
        self.engine.update_rss()
        self.act("approve")
        self.assertTrue(self.engine.allowed)
        self.read["errors"] = ["read failed"]
        self.act("hash")
        self.assertFalse(self.engine.allowed)
        self.assertEqual(self.engine.hash["result"], "unknown")

    def test_reuse_saved_profile_after_pid_change(self):
        self.watch()
        old = self.engine.process.pid
        self.act("close")
        self.act("launch")
        self.engine.tick()
        self.act("start")
        self.assertNotEqual(old, self.engine.process.pid)
        self.assertEqual(self.engine.hash["result"], "match")
        other = Store(self.tmp.name)
        try:
            self.assertEqual(other.profile(self.engine.profile)["samples"], 4)
        finally:
            other.db.close()

    def test_warning_approval_recovery(self):
        self.watch()
        base = self.engine.base.copy()
        self.rss["heap"] = base["bounds"]["heap"]["limit"] + 1
        self.engine.next_rss = 0
        self.engine.tick()
        self.assertEqual(self.engine.issues["heap"]["level"], "warning")
        self.act("approve")
        self.assertTrue(self.engine.allowed)
        self.assertEqual(self.engine.hash["reason"], "사용자 허용")
        self.assertEqual(self.engine.store.profile(self.engine.profile), base)
        self.rss["heap"] = 100
        self.engine.next_rss = 0
        self.engine.tick()
        self.assertFalse(self.engine.issues)
        self.assertFalse(self.engine.allowed)

    def test_danger_hash_match_keeps_warning(self):
        self.watch()
        self.rss["heap"] = self.engine.base["bounds"]["heap"]["danger"] + 1
        self.engine.next_rss = 0
        self.engine.tick()
        self.assertEqual(self.engine.hash["reason"], "위험 초과")
        self.assertEqual(self.engine.phase, "watching")
        with self.assertRaises(ActionError):
            self.act("approve")
        self.assertFalse(self.engine.allowed)
        self.assertEqual(self.engine.issues["heap"]["level"], "danger")
        hashes = [
            r
            for r in self.engine.store.events(self.engine.profile)
            if r["kind"] == "hash"
        ]
        self.engine.next_rss = 0
        self.engine.tick()
        self.assertEqual(
            len(hashes),
            len(
                [
                    r
                    for r in self.engine.store.events(self.engine.profile)
                    if r["kind"] == "hash"
                ]
            ),
        )

    def test_periodic_mismatch_freeze_and_refreeze(self):
        self.watch()
        self.read["digests"] = {"native.so": "b" * 64}
        self.engine.next_hash = 0
        self.engine.tick()
        self.assertEqual(self.engine.phase, "frozen")
        self.assertFalse(self.engine.issues)
        self.act("resume")
        self.assertEqual(self.engine.phase, "watching")
        self.engine.next_hash = 0
        self.engine.tick()
        self.assertEqual(self.engine.phase, "frozen")
        self.assertEqual(self.engine.hash["changes"][0]["actual"], "b" * 64)

    def test_hash_read_failure_never_approves(self):
        self.watch()
        self.rss["heap"] = self.engine.base["bounds"]["heap"]["limit"] + 1
        self.engine.update_rss()

        def denied():
            raise PermissionError("permission denied")

        self.engine.read_hashes = denied
        self.act("approve")
        self.assertFalse(self.engine.allowed)
        self.assertEqual(self.engine.hash["result"], "unknown")
        self.assertFalse(self.engine.process.stopped)

    def test_rss_error_does_not_cancel_periodic_hash(self):
        self.watch()

        def denied():
            raise OSError("smaps unavailable")

        self.engine.measure = denied
        self.read["digests"] = {"native.so": "b" * 64}
        self.engine.next_rss = self.engine.next_hash = 0
        self.engine.tick()
        self.assertIsNotNone(self.engine.rss_error)
        self.assertEqual(self.engine.phase, "frozen")

    def test_failed_recalibration_preserves_saved_profile(self):
        self.calibrate()
        old = self.engine.store.profile(self.engine.profile)
        self.act("calibrate")
        self.engine.tick()
        self.read["digests"] = {"native.so": "b" * 64}
        self.engine.next_rss = 0
        with self.assertRaises(OSError):
            self.engine.tick()
        self.assertEqual(self.engine.store.profile(self.engine.profile), old)

    def test_stale_action_and_exit(self):
        self.watch()
        old = self.engine.rev
        self.act("freeze")
        with self.assertRaises(ActionError):
            self.engine.action("resume", old)
        self.engine.process.running = False
        self.engine.tick()
        self.assertEqual(self.engine.phase, "idle")
        self.assertTrue(
            self.engine.store.events(self.engine.profile, "프로세스 종료 감지")
        )

    def test_web_token_actions_and_report(self):
        client = create_app(self.engine).test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)

        class TokenParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                fields = dict(attrs)
                if tag == "meta" and fields.get("name") == "control-token":
                    self.token = fields["content"]

        parser = TokenParser()
        parser.feed(response.text)
        token = parser.token
        request = {"revision": client.get("/api/state").json["revision"]}
        self.assertEqual(
            client.post("/api/action/launch", json=request).status_code, 403
        )
        headers = {"X-Control-Token": token, "Origin": "http://different.invalid"}
        self.assertEqual(
            client.post(
                "/api/action/launch", headers=headers, json=request
            ).status_code,
            403,
        )
        headers.pop("Origin")
        self.assertEqual(
            client.post(
                "/api/action/launch", headers=headers, json=request
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post("/api/action/close", headers=headers, json=request).status_code,
            409,
        )
        self.assertEqual(
            client.get("/", headers={"Host": "unexpected.invalid"}).status_code, 400
        )
        self.assertEqual(len(client.get("/api/events?q=launch").json["events"]), 1)
        for _ in range(60):
            self.engine.log("batch", "info", "기록")
        page = client.get("/api/events").json
        self.assertTrue(page["more"])
        self.assertEqual(len(page["events"]), 50)
        cursor = page["events"][-1]["id"]
        self.assertEqual(
            len(client.get(f"/api/events?before={cursor}").json["events"]), 11
        )
        csvrows = list(
            csv.reader(
                io.StringIO(client.get("/api/report.csv?q=batch").text.lstrip("\ufeff"))
            )
        )
        self.assertEqual(len(csvrows), 61)
        client.post(
            "/api/action/close", headers=headers, json={"revision": self.engine.rev}
        )
        selected = client.post(
            "/api/action/select",
            headers=headers,
            json={"revision": self.engine.rev, "target": "minesweeper"},
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json["target"]["id"], "minesweeper")
        self.assertEqual(client.get("/api/events").json["events"], [])
