import argparse
import csv
from datetime import datetime, timezone
import hmac
import io
import json
from pathlib import Path
import secrets
import signal
import sys
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from monitor.catalog import catalog
from monitor.engine import ActionError, Engine, Settings


def create_app(engine):
    app = Flask(__name__)
    app.config.update(
        TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"], MAX_CONTENT_LENGTH=4096
    )
    token = secrets.token_urlsafe(32)

    @app.before_request
    def local_host():
        if urlsplit("http://" + request.host).hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            abort(400)

    @app.after_request
    def headers(response):
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    @app.get("/")
    def home():
        return render_template("index.html", token=token)

    @app.get("/api/state")
    def state():
        return jsonify(engine.snapshot())

    @app.get("/api/mappings")
    def mappings():
        try:
            return jsonify(engine.mappings())
        except ActionError as exc:
            return jsonify(error=str(exc)), 409
        except (OSError, ValueError) as exc:
            return jsonify(error=str(exc)), 422

    @app.post("/api/action/<name>")
    def act(name):
        origin = request.headers.get("Origin")
        if origin and (
            urlsplit(origin).netloc != request.host
            or urlsplit(origin).scheme != request.scheme
        ):
            abort(403)
        provided = request.headers.get("X-Control-Token", "")
        if not provided.isascii() or not hmac.compare_digest(token, provided):
            abort(403)
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("revision"), str):
            return jsonify(error="현재 상태 식별자가 필요합니다."), 400
        try:
            if name == "select":
                engine.select(body.get("target"), body["revision"])
            else:
                engine.action(name, body["revision"])
        except ActionError as exc:
            return jsonify(error=str(exc)), 409
        except (OSError, ValueError) as exc:
            with engine.lock:
                engine.log(
                    "action_error",
                    "unknown",
                    "요청 처리 실패",
                    action=name,
                    error=str(exc),
                )
            return jsonify(error=str(exc)), 422
        return jsonify(engine.snapshot())

    def filters():
        return request.args.get("q", "")[:200], request.args.get("level", "")[:20]

    def requested_profile():
        target_id = request.args.get("target")
        with engine.lock:
            if target_id is None:
                return engine.profile
            if target_id not in engine.targets:
                abort(400)
            return engine.profile_for(engine.targets[target_id])

    @app.get("/api/events")
    def events():
        before = request.args.get("before", 0, type=int)
        if not 0 <= before <= 2**63 - 1:
            abort(400)
        with engine.lock:
            rows = engine.store.events(
                requested_profile(), *filters(), before=before, limit=51
            )
        return jsonify(events=rows[:50], more=len(rows) > 50)

    @app.get("/api/report.csv")
    def report():
        query, level = filters()
        profile = requested_profile()

        def stream():
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(
                [
                    "ID",
                    "시각(UTC)",
                    "프로필",
                    "PID",
                    "프로세스",
                    "유형",
                    "수준",
                    "내용",
                    "상세(JSON)",
                ]
            )
            yield "\ufeff" + out.getvalue()
            before = 0
            while True:
                with engine.lock:
                    page = engine.store.events(profile, query, level, before, limit=200)
                if not page:
                    break
                out.seek(0)
                out.truncate(0)
                for row in page:
                    ts = datetime.fromtimestamp(row["ts"], timezone.utc).isoformat()
                    writer.writerow(
                        [
                            row["id"],
                            ts,
                            row["profile"],
                            row["pid"],
                            row["name"],
                            row["kind"],
                            row["level"],
                            row["message"],
                            json.dumps(row["detail"], ensure_ascii=False),
                        ]
                    )
                yield out.getvalue()
                before = page[-1]["id"]

        return Response(
            stream_with_context(stream()),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=memwatch-events.csv"},
        )

    return app


def main():
    parser = argparse.ArgumentParser(description="프로세스 메모리 무결성 감시")
    parser.add_argument(
        "--demo", action="store_true", help="별도 검증 도구가 포함된 게임 실행"
    )
    parser.add_argument("--targets", type=Path, help="추가 프로그램 등록 JSON")
    parser.add_argument("--target", help="처음 선택할 등록 ID (기본 viewer)")
    parser.add_argument("--bind", choices=["127.0.0.1", "0.0.0.0"], default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--data", type=Path, default=Path(__file__).resolve().parent / "data"
    )
    parser.add_argument("--rss-seconds", type=float, default=1)
    parser.add_argument("--hash-seconds", type=float, default=10)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--settle-seconds", type=float, default=2)
    parser.add_argument("--margin", type=float, default=0.10)
    parser.add_argument("--danger", type=float, default=0.20)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error(
            "Linux의 /proc가 필요합니다. Docker의 Ubuntu 데스크톱 터미널에서 실행하세요."
        )
    if args.demo and any(
        not (Path(__file__).parent / "tests" / "build" / v / "libboard.so").is_file()
        for v in ("v1", "v2")
    ):
        parser.error("시연 모듈을 먼저 빌드하세요. python3 -m tests.build_demo")
    cfg = Settings(
        args.rss_seconds,
        args.hash_seconds,
        args.settle_seconds,
        args.samples,
        args.runs,
        args.margin,
        args.danger,
    )
    try:
        targets = catalog(args.targets, args.demo)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.target and args.target not in targets:
        parser.error("등록되지 않은 초기 대상입니다.")
    engine = Engine(args.data, args.demo, cfg, targets=targets, initial=args.target)

    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    engine.start_worker()
    try:
        create_app(engine).run(
            host=args.bind,
            port=args.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    finally:
        engine.close()


if __name__ == "__main__":
    main()
