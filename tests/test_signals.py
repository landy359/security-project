import os
import select
import subprocess
import sys
import unittest
from unittest.mock import patch

from monitor.target import ManagedProcess


@unittest.skipUnless(hasattr(os, "WCONTINUED"), "POSIX 자식 상태 통지 필요")
class SignalTests(unittest.TestCase):
    def test_live_child_stops_and_resumes(self):
        # Exercise production signal delivery. Off Linux, waitpid supplies the OS status.
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                "import sys\nfor line in sys.stdin: print(line.strip(),flush=True)",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        target = object.__new__(ManagedProcess)
        target.child, target.pid, target.ready_fd = process, process.pid, None
        status = "S"

        def portable_state():
            nonlocal status
            pid, event = os.waitpid(process.pid, os.WNOHANG | os.WUNTRACED | os.WCONTINUED)
            if pid and os.WIFSTOPPED(event):
                status = "T"
            elif pid and os.WIFCONTINUED(event):
                status = "S"
            return status

        reader = target.state if sys.platform.startswith("linux") else portable_state
        try:
            with patch.object(target, "state", side_effect=reader):
                self.assertIn(target.pause(True), ("T", "t"))
                process.stdin.write("ping\n")
                process.stdin.flush()
                self.assertFalse(select.select([process.stdout], [], [], 0.12)[0])
                self.assertNotIn(target.pause(False), ("T", "t"))
                self.assertTrue(select.select([process.stdout], [], [], 3)[0])
                self.assertEqual(process.stdout.readline(), "ping\n")
        finally:
            target.close()
            process.stdin.close()
            process.stdout.close()
