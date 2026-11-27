import copy
from collections import deque
from dataclasses import dataclass
import platform
import sys
import threading
import time
import uuid

from .memory import compare, fingerprints, read_exec_maps, read_maps, rss_totals
from .policy import classify, limits
from .storage import Store
from .catalog import catalog
from .target import ManagedProcess


class ActionError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    rss_seconds: float = 1
    hash_seconds: float = 10
    settle_seconds: float = 2
    samples_per_run: int = 12
    runs: int = 3
    margin: float = 0.10
    danger: float = 0.20

    def __post_init__(self):
        if not (
            0.1 <= self.rss_seconds <= 60
            and 1 <= self.hash_seconds <= 600
            and 0 <= self.settle_seconds <= 60
            and 2 <= self.samples_per_run <= 300
            and 2 <= self.runs <= 10
            and 0 < self.margin <= 2
            and 0 < self.danger <= 2
        ):
            raise ValueError("측정 주기·횟수 또는 여유 비율이 범위를 벗어났습니다.")


class Engine:
    def __init__(
        self,
        directory,
        demo=False,
        settings=None,
        process_factory=ManagedProcess,
        *,
        targets=None,
        initial=None,
    ):
        self.cfg = settings or Settings()
        self.targets = catalog(demo=demo) if targets is None else targets
        self.selected = self.targets[initial or ("demo" if demo else "viewer")]
        self.store = Store(directory)
        self.base = self.store.profile(self.profile)
        self.make_process = process_factory
        self.lock = threading.RLock()
        self.process = None
        self.phase = "idle"
        self.rev = uuid.uuid4().hex
        self.history = deque(maxlen=240)
        self.hash_alerts = deque(maxlen=60)
        self.last_rss = self.hash = self.started = self.rss_error = None
        self.kernel_state = None
        self.freeze_reason = None
        self.unverified_checks = 0
        self.issues = {}
        self.allowed = False
        self.cal = self.candidate = None
        self.next_rss = self.next_hash = 0
        self.shutdown = threading.Event()
        self.worker = None

    def profile_for(self, target):
        return f"{target.namespace}/{platform.machine()}/{sys.implementation.cache_tag}"

    @property
    def profile(self):
        return self.profile_for(self.selected)

    def select(self, target_id, revision):
        with self.lock:
            if revision != self.rev or self.phase != "idle":
                raise ActionError("대상을 종료한 뒤 현재 화면에서 다시 선택하세요.")
            if not isinstance(target_id, str) or target_id not in self.targets:
                raise ActionError("등록된 대상 ID가 필요합니다.")
            target = self.targets[target_id]
            baseline = self.store.profile(self.profile_for(target))
            self.selected, self.base = target, baseline
            self.reset_readings()
            self.bump()

    def bump(self):
        self.rev = uuid.uuid4().hex

    def log(self, kind, level, message, **data):
        self.store.log(
            self.profile,
            self.process.pid if self.process else None,
            kind,
            level,
            message,
            target_name=self.selected.id,
            **data,
        )

    def reset_readings(self):
        self.last_rss = self.hash = self.started = self.rss_error = None
        self.kernel_state = None
        self.freeze_reason = None
        self.unverified_checks = 0
        self.history.clear()
        self.hash_alerts.clear()
        self.issues, self.allowed = {}, False

    def launch(self):
        self.reset_readings()
        self.process = self.make_process(self.selected)
        self.phase = "starting"
        self.bump()
        self.log("launch", "info", "대상 프로세스 실행")

    def close_process(self, reason):
        if self.process:
            self.process.close()
            self.log("exit", "info", reason)
        self.process = None
        self.phase = "idle"
        self.cal = self.candidate = None
        self.reset_readings()
        self.bump()

    def measure(self):
        return rss_totals(read_maps(self.process.pid))

    def mappings(self):
        with self.lock:
            if not self.process or not self.process.alive():
                raise ActionError("실행 중인 대상 프로세스가 없습니다.")
            return {
                "pid": self.process.pid,
                "ts": time.time(),
                "mappings": [
                    {
                        "region": row.region,
                        "start": hex(row.start),
                        "end": hex(row.end),
                        "perms": row.perms,
                        "rss": row.rss,
                        "path": row.path or "(anonymous)",
                    }
                    for row in read_maps(self.process.pid)
                ],
            }

    def read_hashes(self):
        pid = self.process.pid
        before = read_exec_maps(pid)
        reading = fingerprints(pid, before, dict(self.selected.aliases))
        if before != read_exec_maps(pid):
            raise OSError("검사 도중 실행 매핑 구성이 바뀌어 다음 주기에 재확인합니다.")
        return reading

    def check_hash(self, reason):
        try:
            reading = self.read_hashes()
            expected = dict(self.base["hashes"])
            optional = self.base.get("optional_hashes", {})
            expected.update(
                {k: optional[k] for k in optional.keys() & reading["digests"].keys()}
            )
            report = compare(expected, reading)
        except (OSError, ValueError) as exc:
            report = {
                "result": "unknown",
                "errors": [str(exc)],
                "changes": [],
                "added": [],
                "missing": [],
                "excluded": [],
                "checked": 0,
            }
        previous = self.hash and self.hash["result"]
        result = report["result"]
        self.unverified_checks = self.unverified_checks + 1 if result == "unknown" else 0
        retry = result == "unknown" and self.phase == "watching" and self.unverified_checks <= 2
        report.update(
            ts=time.time(), reason=reason, retry=retry,
            consecutive_unverified=self.unverified_checks,
        )
        if result != "match":
            self.allowed = False
        self.hash = report
        level = {"unknown": "unknown", "mismatch": "danger", "match": "ok"}[result]
        self.log(
            "hash",
            level,
            {
                "match": "코드 해시 일치",
                "unknown": "코드 검사 미확인",
                "mismatch": "코드 해시 불일치",
            }[result],
            **report,
        )
        delay = min(2, self.cfg.hash_seconds) if retry else self.cfg.hash_seconds
        self.next_hash = time.monotonic() + delay
        if self.unverified_checks == 3:
            self.log("hash_unverified", "warning", "코드 검증 3회 연속 미확인", **report)
        if result == "mismatch":
            if self.phase == "frozen":
                if self.freeze_reason != "코드 해시 불일치":
                    self.freeze_reason = "코드 해시 불일치"
                    self.bump()
            else:
                self.hash_alerts.append(report["ts"])
                self.freeze("코드 해시 불일치")
        if result != previous:
            self.bump()
        return result

    def freeze(self, reason):
        try:
            verified_state = self.process.pause(True)
        except OSError as exc:
            self.log(
                "freeze_failed",
                "unknown",
                "동결 확인 실패",
                reason=reason,
                error=str(exc),
            )
            raise
        self.phase = "frozen"
        self.freeze_reason = reason
        self.kernel_state = verified_state
        self.allowed = False
        self.bump()
        self.log(
            "freeze",
            "danger",
            "대상 동결 확인",
            reason=reason,
            signal="SIGSTOP",
            kernel_state=verified_state,
            approved=False if reason == "사용자 동결" and self.issues else None,
        )

    def update_rss(self):
        current = self.measure()
        before = {k: v["level"] for k, v in self.issues.items()}
        issues = classify(current, self.base["bounds"])
        after = {k: v["level"] for k, v in issues.items()}
        self.issues = issues
        self.last_rss = current
        severity = (
            "danger" if "danger" in after.values() else ("warning" if issues else "ok")
        )
        self.history.append({"ts": time.time(), "rss": current, "level": severity})
        if self.rss_error:
            self.log("rss_restore", "info", "RSS 측정 복구")
            self.rss_error = None
        if before != after:
            self.allowed = False
            self.bump()
            self.log(
                "rss",
                severity,
                "RSS 경고 상태 변경" if issues else "RSS 정상 복귀",
                regions=issues,
                previous=before,
                rss=current,
            )
        return any(
            v == "danger" and before.get(k) != "danger" for k, v in after.items()
        )

    def begin_calibration(self, manual=False):
        if self.process:
            self.close_process("정상 기준 측정을 위해 이전 프로세스 종료")
        self.launch()
        self.cal = {
            "runs": 0,
            "count": 0,
            "low": {},
            "high": {},
            "manual": manual,
            "digests": None,
            "optional": {},
            "hash_at": 0,
            "n": 0,
            "ready_at": None,
        }
        self.phase = "calibrating"
        self.log(
            "calibrate",
            "info",
            "정상 기준 측정 시작",
            runs=self.cfg.runs,
            manual=manual,
        )
        self.next_rss = 0

    def calibration_hash(self):
        read = self.read_hashes()
        if read["errors"] or not read["digests"]:
            raise OSError("정상 기준 해시 확보 실패 · " + " / ".join(read["errors"]))
        if self.cal["digests"] is None:
            self.cal["digests"] = read["digests"]
        expected = dict(self.cal["digests"])
        optional = self.cal["optional"]
        observed = read["digests"]
        # A trusted calibration may load additional libraries while exercising the app.
        # Required startup mappings remain required in every reading.
        extra = observed.keys() - expected.keys()
        expected.update({k: optional.get(k, observed[k]) for k in extra})
        report = compare(expected, read)
        self.log(
            "calibration_hash",
            "ok" if report["result"] == "match" else "unknown",
            "정상 실행 간 코드 기준 비교",
            optional_present=sorted(extra),
            **report,
        )
        if report["result"] != "match":
            raise OSError(
                "정상 실행 간 코드 구성이 달라 측정을 중단했습니다. 로그를 확인하세요."
            )
        optional.update({k: observed[k] for k in extra})
        self.cal["hash_at"] = time.monotonic() + self.cfg.hash_seconds

    def calibration_step(self, now):
        cal = self.cal
        if not self.process.initialized():
            return
        if cal["ready_at"] is None:
            cal["ready_at"] = now + self.cfg.settle_seconds
        if now < max(cal["ready_at"], self.next_rss):
            return
        if cal["n"] == 0 or now >= cal["hash_at"]:
            self.calibration_hash()
        rss = self.measure()
        self.last_rss = rss
        for key, value in rss.items():
            cal["low"][key] = min(cal["low"].get(key, value), value)
            cal["high"][key] = max(cal["high"].get(key, value), value)
        cal["count"] += 1
        cal["n"] += 1
        self.next_rss = now + self.cfg.rss_seconds
        if not cal["manual"] and cal["n"] >= self.cfg.samples_per_run:
            self.finish_run()

    def finish_run(self):
        cal = self.cal
        self.calibration_hash()
        cal["runs"] += 1
        self.log(
            "calibration_run",
            "info",
            "정상 실행 표본 수집 완료",
            run=cal["runs"],
            samples=cal["n"],
        )
        if cal["runs"] < self.cfg.runs:
            self.process.close()
            self.log("exit", "info", "다음 정상 실행 측정을 위해 프로세스 종료")
            self.process = None
            self.launch()
            self.phase = "calibrating"
            cal.update(n=0, ready_at=None)
            return
        self.candidate = {
            "created": time.time(),
            "runs": cal["runs"],
            "samples": cal["count"],
            "manual": cal["manual"],
            "bounds": limits(
                (cal["low"], cal["high"]), self.cfg.margin, self.cfg.danger
            ),
            "hashes": cal["digests"],
            "optional_hashes": cal["optional"],
            "margin": self.cfg.margin,
            "danger_ratio": self.cfg.danger,
        }
        self.phase, self.cal = "review", None
        self.bump()

    def action(self, action, revision):
        with self.lock:
            if revision != self.rev:
                raise ActionError(
                    "대상 또는 경고 상태가 바뀌었습니다. 현재 상태를 다시 확인하세요."
                )
            if self.process and not self.process.alive():
                self.close_process("대상 종료 확인")
                raise ActionError("선택된 대상 프로세스가 종료되었습니다.")
            if action == "launch" and self.phase == "idle":
                self.launch()
            elif action == "close" and self.process:
                self.close_process("사용자가 프로세스 종료")
            elif action in ("calibrate", "calibrate_manual") and self.phase in (
                "idle",
                "ready",
                "review",
            ):
                self.begin_calibration(manual=action == "calibrate_manual")
            elif (
                action == "finish_run"
                and self.phase == "calibrating"
                and self.cal["manual"]
            ):
                if self.cal["n"] < self.cfg.samples_per_run:
                    raise ActionError("최소 표본 수를 채운 뒤 이번 실행을 완료하세요.")
                try:
                    self.finish_run()
                except (OSError, ValueError):
                    self.close_process("기준 측정 중단 · 기존 기준 유지")
                    raise
            elif action == "save" and self.phase == "review":
                self.store.save_profile(
                    self.profile, self.process.pid, self.candidate, self.selected.id
                )
                self.base, self.candidate, self.phase = self.candidate, None, "ready"
            elif action == "start" and self.phase == "ready" and self.base:
                self.phase, self.started = "watching", time.time()
                self.history.clear()
                self.hash_alerts.clear()
                self.log("start", "info", "감시 시작")
                self.next_rss = self.next_hash = 0
                self.unverified_checks = 0
                self.tick()
            elif action == "stop" and self.phase == "watching":
                self.phase, self.started, self.allowed = "ready", None, False
                self.issues = {}
                self.log("stop", "info", "사용자가 감시 중지")
            elif action == "hash" and self.phase in ("watching", "frozen"):
                self.check_hash("수동 검사")
            elif (
                action == "approve"
                and self.phase == "watching"
                and self.issues
                and all(issue["level"] == "warning" for issue in self.issues.values())
                and not self.allowed
            ):
                revision_before = self.rev
                urgent = self.update_rss()
                if self.rev != revision_before:
                    self.log(
                        "approval_stale", "info", "경고 변경으로 이전 승인 요청 만료"
                    )
                    if urgent:
                        self.check_hash("위험 초과")
                    raise ActionError("현재 경고가 변경되었습니다. 다시 확인하세요.")
                self.log(
                    "approval_request",
                    "info",
                    "사용자 임시 허용 요청",
                    regions=self.issues,
                    requested=True,
                )
                result = self.check_hash("사용자 허용")
                self.allowed = result == "match"
                self.log(
                    "approval_result",
                    "info"
                    if self.allowed
                    else "danger"
                    if result == "mismatch"
                    else "unknown",
                    "이번 경고 임시 허용" if self.allowed else "임시 허용 보류",
                    approved=self.allowed,
                    hash_result=result,
                    regions=self.issues,
                )
            elif action == "freeze" and self.phase == "watching":
                self.freeze("사용자 동결")
            elif action in ("resume", "force_resume") and self.phase == "frozen":
                forced = action == "force_resume"
                integrity_hold = self.freeze_reason == "코드 해시 불일치"
                if not forced and integrity_hold and self.check_hash("재개 전 검사") != "match":
                    self.log("resume_blocked", "warning", "재개 보류 · 코드 검증 필요",
                             hash_result=self.hash["result"])
                    raise ActionError("코드 검사가 일치해야 일반 재개할 수 있습니다.")
                last_result = self.hash and self.hash["result"]
                self.kernel_state = self.process.pause(False)
                self.phase = "watching"
                self.next_rss = self.next_hash = 0
                self.freeze_reason = None
                self.unverified_checks = 0
                # Demo controls run in the stopped process and need time to restore v1.
                demo_grace = 10 if forced and self.selected.id == "demo" else 0
                self.log(
                    "force_resume" if forced else "resume",
                    "warning" if forced else "info",
                    "사용자가 강제 재개" if forced else "사용자가 재개",
                    signal="SIGCONT",
                    prior_hash_result=last_result,
                    demo_restore_seconds=demo_grace,
                    kernel_state=self.kernel_state,
                )
                if demo_grace:
                    self.next_hash = time.monotonic() + demo_grace
                else:
                    self.check_hash("강제 재개 직후 검사" if forced else "재개 직후 검사")
            else:
                raise ActionError("현재 상태에서 실행할 수 없는 작업입니다.")
            self.bump()

    def tick(self):
        if not self.process:
            return
        if not self.process.alive():
            self.log(
                "process_end",
                "warning",
                "프로세스 종료 감지",
                phase=self.phase,
                exit_code=self.process.child.returncode,
            )
            self.close_process("감시 대상 해제")
            return
        now = time.monotonic()
        self.kernel_state = self.process.state()
        if self.phase == "starting" and self.process.initialized():
            self.phase = "ready"
            self.bump()
        elif self.phase == "calibrating":
            self.calibration_step(now)
        elif self.phase == "watching":
            urgent = False
            if now >= self.next_rss:
                self.next_rss = now + self.cfg.rss_seconds
                try:
                    urgent = self.update_rss()
                except (ValueError, OSError) as exc:
                    if self.rss_error != str(exc):
                        self.log(
                            "rss_error", "unknown", "RSS 측정 실패", error=str(exc)
                        )
                        self.bump()
                    self.rss_error = str(exc)
                    self.last_rss, self.allowed = None, False
            if urgent or now >= self.next_hash:
                self.check_hash("위험 초과" if urgent else "주기 검사")
        elif self.phase == "frozen" and self.kernel_state not in ("t", "T"):
            self.log("external_resume", "warning", "외부 재개 감지 · 즉시 해시 검사")
            self.phase = "watching"
            self.freeze_reason = None
            self.bump()
            self.check_hash("외부 재개")

    def run(self):
        last_fault = None
        while not self.shutdown.wait(0.1):
            with self.lock:
                try:
                    self.tick()
                    last_fault = None
                except (OSError, ValueError) as exc:
                    if last_fault != str(exc):
                        self.log(
                            "error",
                            "unknown",
                            "측정 또는 프로세스 제어 오류",
                            error=str(exc),
                        )
                    last_fault = str(exc)
                    if self.phase in ("starting", "calibrating"):
                        self.close_process("준비 또는 기준 측정 중단 · 기존 기준 유지")

    def start_worker(self):
        self.worker = threading.Thread(target=self.run, name="memwatch", daemon=True)
        self.worker.start()

    def close(self):
        self.shutdown.set()
        if self.worker:
            self.worker.join(timeout=5)
        with self.lock:
            self.close_process("감시 서버 종료")
            self.store.db.close()

    def snapshot(self):
        with self.lock:
            base = self.base or {}
            cal = self.cal
            return copy.deepcopy(
                {
                    "revision": self.rev,
                    "profile": self.profile,
                    "demo": self.selected.id == "demo",
                    "target": {
                        "id": self.selected.id,
                        "label": self.selected.label,
                        "exercise": self.selected.exercise,
                    },
                    "targets": [
                        {"id": t.id, "label": t.label} for t in self.targets.values()
                    ],
                    "phase": self.phase,
                    "freeze_reason": self.freeze_reason,
                    "pid": self.process.pid if self.process else None,
                    "kernel": self.kernel_state,
                    "started": self.started,
                    "rss": self.last_rss,
                    "rss_error": self.rss_error,
                    "issues": self.issues,
                    "allowed": self.allowed,
                    "hash": self.hash,
                    "bounds": base.get("bounds"),
                    "base_time": base.get("created"),
                    "base_runs": base.get("runs"),
                    "base_samples": base.get("samples"),
                    "history": list(self.history),
                    "hash_alerts": list(self.hash_alerts),
                    "candidate": self.candidate and self.candidate["bounds"],
                    "calibration": {
                        "run": cal["runs"] + 1,
                        "n": cal["n"],
                        "manual": cal["manual"],
                    }
                    if cal
                    else None,
                    "settings": vars(self.cfg),
                    "checked_regions": len(base.get("hashes", {})),
                    "optional_regions": len(base.get("optional_hashes", {})),
                    "candidate_optional": sorted(self.candidate["optional_hashes"])
                    if self.candidate
                    else [],
                }
            )
