"""Only the direct child launched by this controller can receive a signal."""

import os
import select
import signal
import subprocess
import time


class ManagedProcess:
    def __init__(self, target):
        self.target = target
        self.ready_fd = None
        self.ready = False
        write_fd = None
        if target.ready_pipe:
            self.ready_fd, write_fd = os.pipe()
        try:
            self.child = self.start_child(target, write_fd)
        except BaseException:
            self.close_pipe()
            raise
        finally:
            if write_fd is not None:
                os.close(write_fd)
        self.pid = self.child.pid
        self.born = time.monotonic()

    def start_child(self, target, write_fd):
        env = os.environ.copy()
        env.pop("MEMWATCH_READY_FD", None)
        if write_fd is not None:
            env["MEMWATCH_READY_FD"] = str(write_fd)
        return subprocess.Popen(
            target.argv,
            cwd=target.cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            pass_fds=(write_fd,) if write_fd is not None else (),
        )

    def alive(self):
        return self.child.poll() is None

    def initialized(self):
        if self.ready:
            return True
        if not self.target.ready_pipe:
            return time.monotonic() - self.born >= self.target.startup_seconds
        if select.select([self.ready_fd], [], [], 0)[0]:
            self.ready = os.read(self.ready_fd, 1) == b"1"
            if not self.ready:
                raise OSError(
                    "대상이 준비되기 전에 종료되었습니다. 대상 실행 환경을 확인하세요."
                )
            self.close_pipe()
        if not self.ready and time.monotonic() - self.born > 30:
            raise OSError(
                "프로세스 준비 신호 시간 초과. 데스크톱 화면과 터미널을 확인하세요."
            )
        return self.ready

    def close_pipe(self):
        if self.ready_fd is not None:
            os.close(self.ready_fd)
            self.ready_fd = None

    def state(self):
        if not self.alive():
            raise ProcessLookupError("대상 프로세스가 종료되었습니다.")
        with open(f"/proc/{self.pid}/status") as stream:
            for line in stream:
                if line.startswith("State:"):
                    return line.split()[1]
        raise OSError("프로세스 상태를 읽지 못했습니다.")

    def pause(self, freeze):
        if not self.alive():
            raise ProcessLookupError("대상 프로세스가 종료되었습니다.")
        self.child.send_signal(signal.SIGSTOP if freeze else signal.SIGCONT)
        for _ in range(30):
            state = self.state()
            if (state in ("T", "t")) == freeze:
                return state
            time.sleep(0.01)
        raise OSError("커널에서 시그널 처리 결과를 확인하지 못했습니다.")

    def close(self):
        self.close_pipe()
        if self.alive():
            self.child.terminate()
            try:
                self.child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.child.kill()
        self.child.wait(timeout=3)
