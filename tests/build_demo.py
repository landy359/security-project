"""Build two ordinary Linux shared objects for the optional validation target."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def build():
    if not sys.platform.startswith("linux"):
        raise SystemExit("Linux 컨테이너에서 빌드하세요.")
    for version in (1, 2):
        out = ROOT / "build" / f"v{version}" / "libboard.so"
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "cc",
                "-shared",
                "-fPIC",
                "-O2",
                "-Wl,-z,now",
                f"-DBOARD_VERSION={version}",
                str(ROOT / "board_version.c"),
                "-o",
                str(out.with_suffix(".new")),
            ],
            check=True,
        )
        out.with_suffix(".new").replace(out)
    print("시연 모듈 v1, v2 빌드 완료")


if __name__ == "__main__":
    build()
