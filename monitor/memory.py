"""Linux smaps and read-only integrity measurements. RSS values are in KiB."""

from collections import Counter
from dataclasses import dataclass
import hashlib
import os
import re

HEADER = re.compile(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S{4})\s+([0-9a-f]+)\s+\S+\s+(\d+)\s*(.*)$")
REGIONS = ("code", "heap", "stack", "anon", "other", "total")


@dataclass
class Mapping:
    start: int
    end: int
    perms: str
    offset: int
    inode: int
    path: str
    rss: int | None = None

    @property
    def region(self):
        if "x" in self.perms:
            return "code"
        if self.path == "[heap]":
            return "heap"
        if self.path == "[stack]" or self.path.startswith("[stack:"):
            return "stack"
        if not self.path or self.path.startswith(("[anon:", "[anon_shmem:")):
            return "anon"
        return "other"


def parse_smaps(lines):
    rows = []
    for line in lines:
        match = HEADER.match(line.rstrip("\n"))
        if match:
            start, end, perms, offset, inode, path = match.groups()
            rows.append(
                Mapping(int(start, 16), int(end, 16), perms, int(offset, 16), int(inode), path)
            )
        elif rows and line.startswith("Rss:"):
            rows[-1].rss = int(line.split()[1])
    if not rows or any(row.rss is None for row in rows):
        raise OSError("smaps에서 완전한 RSS 정보를 읽지 못했습니다.")
    return rows


def read_maps(pid):
    with open(f"/proc/{pid}/smaps", encoding="utf-8", errors="replace") as src:
        return parse_smaps(src)


def read_exec_maps(pid):
    rows = []
    with open(f"/proc/{pid}/maps", encoding="utf-8", errors="replace") as src:
        for line in src:
            match = HEADER.match(line.rstrip("\n"))
            if match:
                start, end, perms, offset, inode, path = match.groups()
                if "x" in perms:
                    rows.append(
                        Mapping(
                            int(start, 16), int(end, 16), perms, int(offset, 16), int(inode), path
                        )
                    )
    return rows


def rss_totals(rows):
    result = dict.fromkeys(REGIONS, 0)
    for row in rows:
        result[row.region] += row.rss
        result["total"] += row.rss
    return result


def fingerprints(pid, rows, aliases=None):
    """Return complete region digests, measurement errors, and excluded mappings."""
    aliases = aliases or {}
    digests, errors, excluded = {}, [], []
    regions = []
    for row in rows:
        if "x" not in row.perms:
            continue
        if not row.inode or not row.path.startswith("/"):
            excluded.append(row.path or "(anonymous executable)")
            continue
        path = aliases.get(row.path, row.path)
        length = row.end - row.start
        key = f"{path} | {row.offset:#x} | {length:#x} | {row.perms}"
        regions.append((key, row))
    counts = Counter(key for key, row in regions)
    with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
        for key, row in regions:
            if counts[key] != 1 or not row.perms.startswith("r") or "w" in row.perms:
                errors.append(f"매핑 식별 또는 읽기 권한 확인 필요 · {key}")
                continue
            try:
                digest = hashlib.sha256()
                position = row.start
                while position < row.end:
                    size = min(256 * 1024, row.end - position)
                    block = os.pread(mem.fileno(), size, position)
                    if len(block) != size:
                        raise OSError("부분 읽기")
                    digest.update(block)
                    position += size
                digests[key] = digest.hexdigest()
            except (OSError, OverflowError) as exc:
                errors.append(f"{key} · {exc}")
    if not digests:
        errors.append("검증할 수 있는 파일 기반 실행 매핑이 없습니다.")
    return {"digests": digests, "errors": sorted(set(errors)), "excluded": sorted(excluded)}


def compare(expected, reading):
    actual = reading["digests"]
    changes = [
        {"region": key, "expected": expected[key], "actual": actual[key]}
        for key in sorted(expected.keys() & actual.keys())
        if expected[key] != actual[key]
    ]
    missing = sorted(expected.keys() - actual.keys())
    added = sorted(actual.keys() - expected.keys())
    result = "match"
    if missing or added or reading["errors"] or not expected:
        result = "unknown"
    if changes:
        result = "mismatch"
    return {
        "result": result,
        "changes": changes,
        "missing": missing,
        "added": added,
        "errors": reading["errors"],
        "excluded": reading["excluded"],
        "checked": len(actual),
    }
