"""Standalone Tk image viewer used as an ordinary monitoring target."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path


class Viewer:
    def __init__(self, root):
        self.root = root
        root.title("이미지 뷰어")
        self.original = self.preview = None
        self.name = ""
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        for label, action in (
            ("열기", self.open_file),
            ("예제 열기", self.example),
            ("원본", lambda: self.display(1)),
            ("2배 확대", lambda: self.display(2)),
            ("절반 크기", lambda: self.display(0.5)),
            ("닫기", self.clear),
        ):
            ttk.Button(bar, text=label, command=action).pack(side="left", padx=2)
        self.canvas = tk.Canvas(
            root, width=640, height=400, bg="#25313b", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.status = ttk.Label(root, padding=8)
        self.status.pack(fill="x")
        self.clear()

    def example(self):
        width, height = 320, 200
        rgb = bytes(
            value
            for y in range(height)
            for x in range(width)
            for value in (x * 255 // width, y * 255 // height, 140)
        )
        self.original = tk.PhotoImage(
            data=f"P6\n{width} {height}\n255\n".encode() + rgb, format="PPM"
        )
        self.name = "색상 그라데이션"
        self.display(1)

    def open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("이미지", "*.png *.gif *.ppm *.pgm")]
        )
        if not path:
            return
        try:
            image = tk.PhotoImage(file=path)
        except tk.TclError as exc:
            messagebox.showerror("이미지 열기 실패", str(exc))
            return
        self.original, self.name = image, Path(path).name
        self.display(1)

    def display(self, scale):
        if self.original is None:
            return
        if scale == 1:
            self.preview = self.original
        elif scale == 2:
            self.preview = self.original.zoom(2)
        else:
            self.preview = self.original.subsample(2)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.preview)
        self.status.configure(
            text=f"{self.name} · {self.preview.width()} × {self.preview.height()} · {scale:.0%}"
        )

    def clear(self):
        self.canvas.delete("all")
        self.original = self.preview = None
        self.status.configure(text="이미지를 열거나 예제를 선택하세요.")


if __name__ == "__main__":
    root = tk.Tk()
    Viewer(root)
    root.update_idletasks()
    descriptor = os.environ.pop("MEMWATCH_READY_FD", None)
    if descriptor is not None:
        with os.fdopen(int(descriptor), "wb") as pipe:
            pipe.write(b"1")
    root.mainloop()
