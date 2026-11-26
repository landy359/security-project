"""Trusted launch configurations. Only a registered ID crosses the web API."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Target:
    id: str
    label: str
    argv: tuple[str, ...]
    cwd: Path
    exercise: str
    namespace: str
    ready_pipe: bool = False
    startup_seconds: float = 0
    aliases: tuple[tuple[str, str], ...] = ()


def catalog(config=None, demo=False):
    viewer = Target(
        "viewer",
        "이미지 뷰어",
        (sys.executable, "image_viewer.py"),
        ROOT,
        "예제를 열고 확대·축소한 뒤 닫으세요. 평소 사용하는 이미지도 열어 보세요.",
        "viewer",
        True,
    )
    game = Target(
        "minesweeper",
        "지뢰찾기",
        (sys.executable, "minesweeper.py"),
        ROOT,
        "칸 열기, 깃발 표시, 새 게임을 실행하세요.",
        "game",
        True,
    )
    targets = {t.id: t for t in (viewer, game)}
    if demo:
        aliases = tuple(
            (
                str(ROOT / "tests" / "build" / v / "libboard.so"),
                "[시연 모듈] libboard.so",
            )
            for v in ("v1", "v2")
        )
        targets["demo"] = Target(
            "demo",
            "무결성 시연용 지뢰찾기",
            (sys.executable, "-m", "tests.demo_game"),
            ROOT,
            game.exercise
            + " 기준 측정 중에는 부하와 모듈 교체 버튼을 사용하지 마세요.",
            "demo",
            True,
            aliases=aliases,
        )
    if config is None:
        return targets
    path = Path(config).resolve()
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("등록 설정에는 대상 목록(JSON 배열)이 필요합니다.")
    for row in records:
        if not isinstance(row, dict) or set(row) - {
            "id",
            "label",
            "argv",
            "cwd",
            "exercise",
            "startup_seconds",
        }:
            raise ValueError("대상 설정 필드를 확인하세요.")
        name = row.get("id")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name)
            or name in targets
            or name == "demo"
        ):
            raise ValueError(f"잘못되었거나 중복된 대상 ID: {name!r}")
        label, args = row.get("label"), row.get("argv")
        if (
            not isinstance(label, str)
            or not label.strip()
            or not isinstance(args, list)
            or not args
            or not all(isinstance(a, str) and "\0" not in a for a in args)
            or not Path(args[0]).is_absolute()
        ):
            raise ValueError(
                f"{name}: 이름과 절대 실행 경로로 시작하는 argv 배열이 필요합니다."
            )
        delay = row.get("startup_seconds", 2)
        if type(delay) not in (int, float) or not 0 <= delay <= 120:
            raise ValueError(f"{name}: startup_seconds는 0~120초입니다.")
        directory = row.get("cwd", ".")
        hint = row.get("exercise", "측정 중에 이 프로그램을 평소처럼 사용하세요.")
        if not isinstance(directory, str) or not isinstance(hint, str):
            raise ValueError(f"{name}: cwd와 exercise는 문자열이어야 합니다.")
        cwd = (path.parent / directory).resolve()
        if not cwd.is_dir():
            raise ValueError(f"{name}: 작업 폴더가 없습니다: {cwd}")
        definition = json.dumps([args, str(cwd), delay], ensure_ascii=False).encode()
        key = hashlib.sha256(definition).hexdigest()[:24]
        targets[name] = Target(
            name,
            label,
            tuple(args),
            cwd,
            hint,
            f"registered/{name}/{key}",
            startup_seconds=delay,
        )
    return targets
