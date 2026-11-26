import os
import select
import subprocess
import sys
import tempfile
import time
import unittest

from monitor.engine import Engine, Settings
from monitor.catalog import ROOT
from monitor.target import ManagedProcess


class Probe(ManagedProcess):
    def start_child(self, demo, ready_write):
        return subprocess.Popen(
            [sys.executable, "-m", "tests.probe"],
            cwd=ROOT,
            pass_fds=(ready_write,),
            env={**os.environ, "MEMWATCH_READY_FD": str(ready_write)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def command(self, word):
        self.child.stdin.write(word + "\n")
        self.child.stdin.flush()
        if (
            not select.select([self.child.stdout], [], [], 4)[0]
            or self.child.stdout.readline().strip() != "OK"
        ):
            raise RuntimeError("검증 프로세스 응답 오류")

    def close(self):
        super().close()
        self.child.stdin.close()
        self.child.stdout.close()


@unittest.skipUnless(sys.platform.startswith("linux"), "실제 Linux /proc 필요")
class LinuxIntegration(unittest.TestCase):
    def test_live_rss_hash_signals(self):
        from tests.build_demo import build

        build()
        with tempfile.TemporaryDirectory() as data:
            e = Engine(data, True, Settings(0.1, 1, 0.1, 3, 2), Probe)
            try:

                def act(name):
                    e.action(name, e.rev)

                def until(predicate, seconds=12):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        e.tick()
                        if predicate():
                            return
                        time.sleep(0.03)
                    self.fail("예상 상태에 도달하지 않음: " + str(e.snapshot()))

                act("calibrate")
                until(lambda: e.phase == "review")
                act("save")
                act("start")
                self.assertEqual(e.hash["result"], "match")
                self.assertGreater(e.last_rss["total"], 0)
                for _ in range(256):
                    e.process.command("add")
                    e.update_rss()
                    if e.issues:
                        break
                self.assertIn("warning", {x["level"] for x in e.issues.values()})
                act("approve")
                self.assertTrue(e.allowed)
                for _ in range(256):
                    e.process.command("add")
                    e.next_rss = 0
                    e.tick()
                    if any(i["level"] == "danger" for i in e.issues.values()):
                        break
                self.assertEqual(e.hash["reason"], "위험 초과")
                self.assertEqual(e.hash["result"], "match")
                self.assertEqual(e.phase, "watching")
                e.process.command("release")
                until(lambda: not e.issues)
                pid = e.process.pid
                e.process.command("v2")
                until(lambda: e.phase == "frozen")
                self.assertEqual(e.process.pid, pid)
                self.assertEqual(e.process.state(), "T")
                self.assertEqual(e.hash["result"], "mismatch")
                self.assertTrue(
                    any("libboard.so" in r["region"] for r in e.hash["changes"])
                )
                act("resume")
                e.process.command("v1")
                until(lambda: e.hash["result"] == "match")
                self.assertEqual(e.phase, "watching")
                print(
                    f"Linux PID {pid}: {e.last_rss['total']} KiB RSS, {e.hash['checked']} native mappings, SIGSTOP/SIGCONT verified"
                )
            finally:
                e.close()

    @unittest.skipUnless(os.environ.get("DISPLAY"), "Tk 데스크톱 또는 Xvfb 필요")
    def test_real_game_window(self):
        from tkinter import Tk
        from minesweeper import GameWindow

        root = Tk()
        try:
            game = GameWindow(root)
            root.update()
            game.buttons[(0, 0)].invoke()
            root.update()
            self.assertIn((0, 0), game.board.opened)
            game.new()
            self.assertIsNone(game.board.mines)
        finally:
            root.destroy()
        with tempfile.TemporaryDirectory() as data:
            e = Engine(
                data, settings=Settings(0.1, 1, 0.2, 3, 2), initial="minesweeper"
            )
            try:
                e.action("calibrate", e.rev)
                deadline = time.monotonic() + 20
                while e.phase != "review" and time.monotonic() < deadline:
                    e.tick()
                    time.sleep(0.04)
                self.assertEqual(e.phase, "review")
                e.action("save", e.rev)
                e.action("start", e.rev)
                self.assertEqual(e.hash["result"], "match")
                e.action("freeze", e.rev)
                self.assertEqual(e.process.state(), "T")
                e.action("resume", e.rev)
                self.assertNotIn(e.process.state(), ("T", "t"))
            finally:
                e.close()

    @unittest.skipUnless(os.environ.get("DISPLAY"), "Tk 데스크톱 또는 Xvfb 필요")
    def test_viewer_holdout_workload(self):
        class DrivenViewer(ManagedProcess):
            def start_child(self, target, ready_fd):
                return subprocess.Popen(
                    [sys.executable, "-m", "tests.viewer_workload"],
                    cwd=target.cwd,
                    pass_fds=(ready_fd,),
                    env={**os.environ, "MEMWATCH_READY_FD": str(ready_fd)},
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

            def click(self, name):
                self.child.stdin.write(name + "\n")
                self.child.stdin.flush()
                if not select.select([self.child.stdout], [], [], 5)[0]:
                    raise RuntimeError("이미지 뷰어가 응답하지 않았습니다.")
                return self.child.stdout.readline().strip()

            def close(self):
                super().close()
                self.child.stdin.close()
                self.child.stdout.close()

        def ready(engine):
            deadline = time.monotonic() + 10
            while not engine.process.initialized():
                if time.monotonic() >= deadline:
                    self.fail("이미지 뷰어 준비 시간 초과")
                time.sleep(0.02)
            engine.tick()

        sizes = {
            "example": "320x200",
            "zoom": "640x400",
            "half": "160x100",
            "clear": "empty",
        }
        with tempfile.TemporaryDirectory() as data:
            e = Engine(
                data, settings=Settings(0.1, 1, 0, 2, 2), process_factory=DrivenViewer
            )
            try:
                e.action("calibrate_manual", e.rev)
                for _ in range(2):
                    ready(e)
                    for name in list(sizes) * 3:
                        self.assertEqual(e.process.click(name), sizes[name])
                        e.next_rss = 0
                        e.tick()
                    e.action("finish_run", e.rev)
                e.action("save", e.rev)
                calibration_pid = e.process.pid
                e.action("close", e.rev)
                e.action("launch", e.rev)
                ready(e)
                self.assertNotEqual(e.process.pid, calibration_pid)
                e.action("start", e.rev)
                warnings = 0
                for name in list(sizes) * 16:
                    self.assertEqual(e.process.click(name), sizes[name])
                    e.next_rss = 0
                    e.tick()
                    warnings += bool(e.issues)
                e.action("hash", e.rev)
                self.assertEqual(e.hash["result"], "match")
                self.assertEqual(e.phase, "watching")
                print(
                    f"Viewer holdout PID {e.process.pid}: 64 actions, {warnings} RSS alerts, "
                    f"{e.hash['checked']} native mappings matched."
                )
            finally:
                e.close()

    def test_registered_linux_program_uses_common_engine(self):
        import json
        from pathlib import Path
        from monitor.catalog import catalog

        with tempfile.TemporaryDirectory() as data:
            path = Path(data) / "targets.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "sleep",
                            "label": "대기 프로세스",
                            "argv": ["/bin/sleep", "60"],
                            "startup_seconds": 0.1,
                        }
                    ]
                )
            )
            engine = Engine(
                data, targets=catalog(path), settings=Settings(0.1, 1, 0, 2, 2)
            )
            try:
                engine.select("sleep", engine.rev)
                engine.action("calibrate", engine.rev)
                deadline = time.monotonic() + 8
                while engine.phase != "review" and time.monotonic() < deadline:
                    engine.tick()
                    time.sleep(0.03)
                self.assertEqual(engine.phase, "review")
                engine.action("save", engine.rev)
                engine.action("start", engine.rev)
                self.assertEqual(engine.hash["result"], "match")
                self.assertGreater(engine.last_rss["total"], 0)
                engine.action("freeze", engine.rev)
                self.assertEqual(engine.process.state(), "T")
                engine.action("resume", engine.rev)
                self.assertNotIn(engine.process.state(), ("T", "t"))
            finally:
                engine.close()
