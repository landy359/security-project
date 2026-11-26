"""6×6 지뢰찾기. 감시 서버와 독립적으로 실행할 수도 있다."""

import os
import random
import tkinter as tk
from tkinter import ttk


class Board:
    size, count = 6, 6

    def __init__(self):
        self.cells = [(r, c) for r in range(self.size) for c in range(self.size)]
        self.mines = None
        self.opened, self.flagged = set(), set()
        self.result = None

    def neighbors(self, cell):
        r, c = cell
        return [
            (i, j)
            for i in range(max(0, r - 1), min(self.size, r + 2))
            for j in range(max(0, c - 1), min(self.size, c + 2))
            if (i, j) != cell
        ]

    def number(self, cell):
        return len(set(self.neighbors(cell)) & self.mines)

    def flag(self, cell):
        if self.result or cell in self.opened:
            return
        if cell in self.flagged:
            self.flagged.remove(cell)
        elif len(self.flagged) < self.count:
            self.flagged.add(cell)

    def open(self, cell):
        if self.result or cell in self.flagged or cell in self.opened:
            return
        if self.mines is None:
            self.mines = set(random.sample([p for p in self.cells if p != cell], self.count))
        if cell in self.mines:
            self.result = "패배"
            return
        pending = [cell]
        while pending:
            p = pending.pop()
            if p in self.opened or p in self.flagged:
                continue
            self.opened.add(p)
            if self.number(p) == 0:
                pending.extend(self.neighbors(p))
        if len(self.opened) == len(self.cells) - self.count:
            self.result = "승리"


class GameWindow:
    def __init__(self, root):
        self.root = root
        root.title("지뢰찾기 · 6 × 6")
        wrapper = ttk.Frame(root, padding=16)
        wrapper.grid()
        self.status = ttk.Label(wrapper)
        self.status.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))
        self.buttons = {}
        self.board = Board()
        for p in self.board.cells:
            button = tk.Button(wrapper, width=3, height=2, command=lambda p=p: self.click(p))
            button.grid(row=p[0] + 1, column=p[1], padx=1, pady=1, sticky="nsew")
            button.bind("<Button-3>", lambda ev, p=p: self.click(p, flag=True))
            button.bind("<Control-Button-1>", lambda ev, p=p: self.click(p, flag=True))
            self.buttons[p] = button
        ttk.Label(wrapper, text=f"PID {os.getpid()}").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )
        ttk.Button(wrapper, text="새 게임", command=self.new).grid(
            row=7, column=3, columnspan=3, sticky="e", pady=(12, 0)
        )
        self.render()

    def new(self):
        self.board = Board()
        self.render()

    def click(self, p, flag=False):
        if flag:
            self.board.flag(p)
        else:
            self.board.open(p)
        self.render()
        return "break"

    def render(self):
        board = self.board
        self.status.configure(
            text=f"{board.result or '지뢰찾기'}   ·   남은 깃발 {board.count-len(board.flagged)}"
        )
        for p, button in self.buttons.items():
            opened = p in board.opened
            value = ""
            if board.result and p in board.mines:
                value = "●"
            elif p in board.flagged:
                value = "⚑"
            elif opened:
                value = str(board.number(p) or "")
            button.configure(
                text=value,
                relief="sunken" if opened else "raised",
                background="#dae4de" if opened else "#f3f6f4",
            )


def run(extra=None):
    root = tk.Tk()
    GameWindow(root)
    if extra:
        extra(root)
    root.update_idletasks()
    fd = os.environ.pop("MEMWATCH_READY_FD", None)
    if fd is not None:
        with os.fdopen(int(fd), "wb") as ready:
            ready.write(b"1")
    root.mainloop()


if __name__ == "__main__":
    run()
