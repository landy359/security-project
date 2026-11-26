"""Optional validation game. Controls only its own allocation and packaged plugins."""

import ctypes
import mmap
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from minesweeper import run

BUILD = Path(__file__).resolve().parent / "build"


class Plugin:
    def __init__(self):
        self.loader = ctypes.CDLL(None)
        self.loader.dlopen.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.loader.dlopen.restype = ctypes.c_void_p
        self.loader.dlclose.argtypes = [ctypes.c_void_p]
        self.loader.dlclose.restype = ctypes.c_int
        self.handle = None
        self.version = None
        self.select(1)

    def select(self, version):
        if version not in (1, 2):
            raise ValueError("정의되지 않은 시연 버전")
        if self.version == version:
            return
        path = BUILD / f"v{version}" / "libboard.so"
        handle = self.loader.dlopen(os.fsencode(path), os.RTLD_NOW | os.RTLD_LOCAL)
        if not handle:
            raise OSError(
                "시연 모듈을 열 수 없습니다. python3 -m tests.build_demo 를 먼저 실행하세요."
            )
        if self.handle and self.loader.dlclose(self.handle) != 0:
            self.loader.dlclose(handle)
            raise OSError("기존 모듈을 해제하지 못했습니다.")
        self.handle, self.version = handle, version


class Workload:
    step = 256 * 1024
    max_blocks = 256

    def __init__(self):
        self.blocks = []

    def add(self, count):
        for _ in range(min(count, self.max_blocks - len(self.blocks))):
            block = mmap.mmap(
                -1,
                self.step,
                flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
            )
            for p in range(0, self.step, mmap.PAGESIZE):
                block[p] = 1
            self.blocks.append(block)

    def reset(self):
        while self.blocks:
            self.blocks.pop().close()


def controls(root):
    box = tk.Toplevel(root)
    box.title("기능 검증 · 지뢰찾기")
    panel = ttk.Frame(box, padding=14)
    panel.grid()
    plugin, memory = Plugin(), Workload()
    status = ttk.Label(panel)
    status.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    def show():
        status.configure(
            text=f"추가 RSS 부하 {len(memory.blocks)/4:g} MiB / 64 MiB   ·   모듈 v{plugin.version}"
        )

    def change(count):
        memory.add(count) if count else memory.reset()
        show()

    def switch(version):
        plugin.select(version)
        show()

    for i, (label, count) in enumerate([("+0.25 MiB", 1), ("+1 MiB", 4), ("+8 MiB", 32)]):
        ttk.Button(panel, text=label, command=lambda n=count: change(n)).grid(row=1, column=i)
    ttk.Button(panel, text="메모리 해제", command=lambda: change(0)).grid(row=2, column=0)
    ttk.Button(panel, text="v2로 교체", command=lambda: switch(2)).grid(row=2, column=1)
    ttk.Button(panel, text="v1 복원", command=lambda: switch(1)).grid(row=2, column=2)
    show()


if __name__ == "__main__":
    run(controls)
