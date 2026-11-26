"""Drive ordinary image viewer actions over a test-only pipe on Linux/X11."""

import os
import sys
import tkinter as tk

from image_viewer import Viewer


def main():
    root = tk.Tk()
    app = Viewer(root)

    def handle_command(stream, mask):
        name = stream.readline().strip()
        if not name:
            root.quit()
            return
        if name == "example":
            app.example()
        elif name == "zoom":
            app.display(2)
        elif name == "half":
            app.display(0.5)
        elif name == "clear":
            app.clear()
        else:
            raise ValueError(name)
        root.update_idletasks()
        size = (
            f"{app.preview.width()}x{app.preview.height()}" if app.preview else "empty"
        )
        print(size, flush=True)

    root.createfilehandler(sys.stdin, tk.READABLE, handle_command)
    root.update_idletasks()
    with os.fdopen(int(os.environ.pop("MEMWATCH_READY_FD")), "wb") as pipe:
        pipe.write(b"1")
    root.mainloop()


if __name__ == "__main__":
    main()
