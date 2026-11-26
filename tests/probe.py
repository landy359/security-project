"""Headless integration target. Commands affect only this validation process."""

import os
import sys
from tests.demo_game import Plugin, Workload


def main():
    plugin, memory = Plugin(), Workload()
    with os.fdopen(int(os.environ["MEMWATCH_READY_FD"]), "wb") as ready:
        ready.write(b"1")
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "add":
            memory.add(1)
        elif cmd == "release":
            memory.reset()
        elif cmd == "v2":
            plugin.select(2)
        elif cmd == "v1":
            plugin.select(1)
        else:
            break
        print("OK", flush=True)


if __name__ == "__main__":
    main()
