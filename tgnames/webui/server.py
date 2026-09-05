"""A small local web server for the desktop UI.

Standard library only, like the rest of the keyless path: the machine this runs
on may have no working pip at all.

It binds to the loopback interface and requires a token that is minted at
startup and handed to the page through its URL. Without that, any web page the
user happens to visit could reach this server through localhost and drive their
account, so the token is checked on every API call and the Origin header is
rejected when present — a browser sends one on cross-site requests but not on
same-origin GETs of the page itself.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import generator, storage
from ..config import Config, load as load_config
from ..jobs_glue import run_generate, run_rescore, run_scan
from ..scoring import analyze, analyze_many
from ..storage import Storage
from .jobs import JobRunner

STATIC_DIR = Path(__file__).resolve().parent / "static"


class App:
    """Everything a request handler needs, built once at startup."""

    def __init__(self, config: Config, db_path: str):
        self.config = config
        self.db_path = db_path
        self.token = secrets.token_urlsafe(24)
        self.jobs = JobRunner()
        self._db_lock = threading.Lock()

    def db(self) -> Storage:
        # SQLite connections are not shareable across threads, so each request
        # opens its own; the lock keeps writers from colliding.
        return Storage(self.db_path)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def api_stats(app: App, _query, _body) -> dict:
    from ..ratelimit import Quota

    with app.db() as db:
        counts = db.stats()
        rows = db.all_by_status(None, 1000000)
        checked = [c for c in rows if c.status in (
            storage.STATUS_AVAILABLE, storage.STATUS_UNCLAIMED,
            storage.STATUS_TAKEN, storage.STATUS_PURCHASABLE, storage.STATUS_INVALID)]

        by_length: dict[int, dict[str, int]] = {}
        for row in checked:
            bucket = by_length.setdefault(
                len(row.username),
                {"taken": 0, "reserved": 0, "unknown": 0, "free": 0},
            )
            if row.status == storage.STATUS_TAKEN:
                bucket["taken"] += 1
            elif row.status in (storage.STATUS_PURCHASABLE, storage.STATUS_INVALID):
                bucket["reserved"] += 1
            elif row.status == storage.STATUS_UNCLAIMED:
                bucket["unknown"] += 1
            elif row.status == storage.STATUS_AVAILABLE:
                bucket["free"] += 1

        lim = app.config.limits
        check_left = Quota(db, "check", lim.checks_per_hour, lim.checks_per_day).remaining()
        claim_left = Quota(db, "claim", lim.claims_per_hour, lim.claims_per_day).remaining()
        events = [dict(e) for e in db.recent_events(12)]

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "byLength": [{"length": k, **v} for k, v in sorted(by_length.items())],
        "quota": {
            "check": {"hour": check_left[0], "day": check_left[1],
                      "hourMax": lim.checks_per_hour, "dayMax": lim.checks_per_day},
            "claim": {"hour": claim_left[0], "day": claim_left[1],
                      "hourMax": lim.claims_per_hour, "dayMax": lim.claims_per_day},
        },
        "events": events,
        "db": app.db_path,
        "strategies": list(generator.STRATEGIES) + ["all"],
    }


def api_candidates(app: App, query, _body) -> dict:
    status = (query.get("status") or [""])[0] or None
    search = (query.get("q") or [""])[0].strip().lower()
    sort = (query.get("sort") or ["score"])[0]
    limit = min(int((query.get("limit") or ["300"])[0]), 2000)
    min_len = int((query.get("minLength") or ["0"])[0])
    tag = (query.get("tag") or [""])[0]

    with app.db() as db:
        rows = db.all_by_status(status, 1000000)

    items = []
    for row in rows:
        if search and search not in row.username:
            continue
        if min_len and len(row.username) < min_len:
            continue
        if tag and tag not in row.tags:
            continue
        items.append({
            "username": row.username, "score": row.score, "tier": row.tier,
            "band": row.value_band, "status": row.status, "tags": row.tags,
            "source": row.source, "note": row.note or "",
            "length": len(row.username), "channelId": row.channel_id,
        })

    keys = {
        "score": lambda i: (-i["score"], i["username"]),
        "length": lambda i: (i["length"], -i["score"]),
        "name": lambda i: i["username"],
        "status": lambda i: (i["status"], -i["score"]),
    }
    items.sort(key=keys.get(sort, keys["score"]))
    return {"items": items[:limit], "matched": len(items)}


def api_analyze(app: App, query, _body) -> dict:
    raw = (query.get("u") or [""])[0]
    if not raw.strip():
        return {"result": None}
    return {"result": analyze(raw).as_dict()}


def api_mark(app: App, _query, body) -> dict:
    names = body.get("usernames") or []
    status = body.get("status") or storage.STATUS_CLAIMED
    note = body.get("note") or "marked in the app"
    updated = []
    with app.db() as db:
        for raw in names:
            v = analyze(raw)
            if not v.valid:
                continue
            if db.get(v.username) is None:
                db.upsert_many([v], source="manual")
            db.set_status(v.username, status, note=note, checked=True,
                          claimed=status == storage.STATUS_CLAIMED)
            db.log("mark", v.username, status)
            updated.append(v.username)
    return {"updated": updated}


def api_job(app: App, _query, _body) -> dict:
    return {"job": app.jobs.snapshot(), "busy": app.jobs.busy}


def api_job_stop(app: App, _query, _body) -> dict:
    return {"stopping": app.jobs.request_stop()}


def api_generate(app: App, _query, body) -> dict:
    app.jobs.start("generate", lambda job, stop: run_generate(app, body, job, stop))
    return {"started": True}


def api_scan(app: App, _query, body) -> dict:
    app.jobs.start("scan", lambda job, stop: run_scan(app, body, job, stop))
    return {"started": True}


def api_rescore(app: App, _query, body) -> dict:
    app.jobs.start("rescore", lambda job, stop: run_rescore(app, body, job, stop))
    return {"started": True}


GET_ROUTES = {
    "/api/stats": api_stats,
    "/api/candidates": api_candidates,
    "/api/analyze": api_analyze,
    "/api/job": api_job,
}
POST_ROUTES = {
    "/api/mark": api_mark,
    "/api/generate": api_generate,
    "/api/scan": api_scan,
    "/api/rescore": api_rescore,
    "/api/job/stop": api_job_stop,
}


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "tgnames"
    app: App

    def log_message(self, fmt, *args):  # quieter than the default
        pass

    # -- helpers ------------------------------------------------------------
    def _send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self, query) -> bool:
        # A cross-site request carries Origin; a same-origin page load does not.
        if self.headers.get("Origin"):
            return False
        token = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(token, self.app.token)

    def _serve_static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # -- verbs --------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path.startswith("/api/"):
            if not self._authorised(query):
                self._send_json({"error": "unauthorised"}, 403)
                return
            route = GET_ROUTES.get(parsed.path)
            if not route:
                self._send_json({"error": "not found"}, 404)
                return
            try:
                self._send_json(route(self.app, query, None))
            except Exception as exc:
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorised(query):
            self._send_json({"error": "unauthorised"}, 403)
            return
        route = POST_ROUTES.get(parsed.path)
        if not route:
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "bad json"}, 400)
            return
        try:
            self._send_json(route(self.app, query, body))
        except RuntimeError as exc:
            self._send_json({"error": str(exc)}, 409)
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def serve(config: Config, db_path: str, port: int = 8765,
          open_browser: bool = True, host: str = "127.0.0.1") -> None:
    app = App(config, db_path)
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{httpd.server_address[1]}/?t={app.token}"

    print("tgnames is running.")
    print(f"  {url}")
    print("  The link contains a one-time key for this session — keep it to yourself.")
    print("  Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
