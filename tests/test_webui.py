"""Integration tests for the local app: a real server on an ephemeral port.

The security properties matter most here. This server can drive the user's
Telegram account, and it listens on a port any page in their browser can reach,
so the token check and the Origin rejection are tested as carefully as the data.
"""

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from tgnames.config import Config
from tgnames.scoring import analyze_many
from tgnames.storage import Storage
from tgnames.webui.server import App, Handler
from http.server import ThreadingHTTPServer


@pytest.fixture()
def server(tmp_path):
    db_path = str(tmp_path / "ui.db")
    with Storage(db_path) as db:
        db.upsert_many(analyze_many(["goldbank", "vaultpay", "elite", "tonpayhq"]),
                       source="test")
        db.set_status("goldbank", "taken", note="via t.me page: owner visible",
                      checked=True)
        db.set_status("vaultpay", "unclaimed", note="via t.me page: no owner visible",
                      checked=True)

    cfg = Config()
    app = App(cfg, db_path)
    handler = type("Bound", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield app, httpd.server_address[1], db_path
    httpd.shutdown()
    httpd.server_close()


def request(port, path, method="GET", token=None, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    head = dict(headers or {})
    if token:
        head["X-Token"] = token
    payload = None
    if body is not None:
        payload = json.dumps(body)
        head["Content-Type"] = "application/json"
    conn.request(method, path, payload, head)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        return response.status, json.loads(raw)
    except json.JSONDecodeError:
        return response.status, raw


class TestSecurity:
    def test_api_needs_the_token(self, server):
        _, port, _ = server
        assert request(port, "/api/stats")[0] == 403

    def test_a_wrong_token_is_refused(self, server):
        _, port, _ = server
        assert request(port, "/api/stats", token="nope")[0] == 403

    def test_cross_site_requests_are_refused(self, server):
        """A browser sets Origin on cross-site calls; same-origin GETs have none."""
        app, port, _ = server
        status, _ = request(port, "/api/stats", token=app.token,
                            headers={"Origin": "https://evil.example"})
        assert status == 403

    def test_writes_need_the_token_too(self, server):
        _, port, _ = server
        status, _ = request(port, "/api/mark", "POST",
                            body={"usernames": ["goldbank"], "status": "claimed"})
        assert status == 403

    def test_the_page_itself_needs_no_token(self, server):
        _, port, _ = server
        status, body = request(port, "/")
        assert status == 200 and b"tgnames" in body

    def test_static_assets_are_served(self, server):
        _, port, _ = server
        assert request(port, "/app.css")[0] == 200
        assert request(port, "/app.js")[0] == 200

    @pytest.mark.parametrize("path", [
        "/../../etc/passwd", "/../tgnames/config.py", "/nope.txt",
    ])
    def test_paths_outside_the_asset_directory_are_refused(self, server, path):
        _, port, _ = server
        assert request(port, path)[0] == 404

    def test_unknown_api_route(self, server):
        app, port, _ = server
        assert request(port, "/api/nope", token=app.token)[0] == 404


class TestData:
    def test_stats(self, server):
        app, port, _ = server
        status, data = request(port, "/api/stats", token=app.token)
        assert status == 200
        assert data["total"] == 4
        assert data["counts"]["taken"] == 1
        lengths = {row["length"]: row for row in data["byLength"]}
        assert lengths[8]["taken"] == 1 and lengths[8]["unknown"] == 1
        assert "compounds" in data["strategies"]

    def test_candidates_are_ranked(self, server):
        app, port, _ = server
        _, data = request(port, "/api/candidates", token=app.token)
        scores = [i["score"] for i in data["items"]]
        assert scores == sorted(scores, reverse=True)

    def test_candidates_filter_by_status(self, server):
        app, port, _ = server
        _, data = request(port, "/api/candidates?status=taken", token=app.token)
        assert [i["username"] for i in data["items"]] == ["goldbank"]

    def test_candidates_search_and_length(self, server):
        app, port, _ = server
        _, data = request(port, "/api/candidates?q=vault", token=app.token)
        assert [i["username"] for i in data["items"]] == ["vaultpay"]
        _, data = request(port, "/api/candidates?minLength=8", token=app.token)
        assert all(i["length"] >= 8 for i in data["items"])

    def test_analyze(self, server):
        app, port, _ = server
        _, data = request(port, "/api/analyze?u=%40goldvault", token=app.token)
        assert data["result"]["username"] == "goldvault"
        assert set(data["result"]["components"]) == {
            "length", "charset", "lexical", "pattern", "phonetic"}

    def test_analyze_reports_invalid_handles(self, server):
        app, port, _ = server
        _, data = request(port, "/api/analyze?u=zz", token=app.token)
        assert data["result"]["valid"] is False

    def test_mark_updates_the_database(self, server):
        app, port, db_path = server
        status, data = request(port, "/api/mark", "POST", token=app.token,
                               body={"usernames": ["goldbank"], "status": "claimed"})
        assert status == 200 and data["updated"] == ["goldbank"]
        with Storage(db_path) as db:
            row = db.get("goldbank")
        assert row.status == "claimed" and row.claimed_at

    def test_mark_creates_unknown_handles(self, server):
        app, port, db_path = server
        request(port, "/api/mark", "POST", token=app.token,
                body={"usernames": ["brandnewname"], "status": "skipped"})
        with Storage(db_path) as db:
            assert db.get("brandnewname").status == "skipped"

    def test_mark_ignores_invalid_handles(self, server):
        app, port, _ = server
        _, data = request(port, "/api/mark", "POST", token=app.token,
                          body={"usernames": ["zz"], "status": "claimed"})
        assert data["updated"] == []


class TestJobs:
    def _wait(self, app, port, timeout=25):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, data = request(port, "/api/job", token=app.token)
            if not data["busy"]:
                return data["job"]
            time.sleep(0.15)
        raise AssertionError("job did not finish")

    def test_generate_runs_and_fills_the_database(self, server):
        app, port, db_path = server
        status, _ = request(port, "/api/generate", "POST", token=app.token,
                            body={"strategy": "words", "limit": 10, "minLength": 7})
        assert status == 200
        job = self._wait(app, port)
        assert job["state"] == "finished"
        with Storage(db_path) as db:
            names = [c.username for c in db.all_by_status()]
        assert len(names) > 4
        assert all(len(n) >= 7 for n in names if n not in
                   ("goldbank", "vaultpay", "elite", "tonpayhq"))

    def test_only_one_job_at_a_time(self, server):
        app, port, _ = server
        request(port, "/api/generate", "POST", token=app.token,
                body={"strategy": "all", "limit": 50})
        status, data = request(port, "/api/generate", "POST", token=app.token,
                               body={"strategy": "words", "limit": 5})
        # Either the first is still running (409) or it already finished (200).
        assert status in (200, 409)
        if status == 409:
            assert "already running" in data["error"]
        self._wait(app, port)

    def test_rescore_reports_progress(self, server):
        app, port, _ = server
        request(port, "/api/rescore", "POST", token=app.token, body={})
        job = self._wait(app, port)
        assert job["state"] == "finished"
        assert "re-scored" in job["message"]

    def test_a_failing_scan_is_reported_not_swallowed(self, server, monkeypatch):
        """A checker that cannot calibrate must surface as a failed job."""
        import tgnames.webcheck as webcheck

        def boom(self, on_sample=None):
            raise webcheck.CalibrationError("pages look identical")

        monkeypatch.setattr(webcheck.WebChecker, "calibrate", boom)
        app, port, _ = server
        request(port, "/api/scan", "POST", token=app.token, body={"limit": 1})
        job = self._wait(app, port)
        assert job["state"] == "failed"
        assert "identical" in job["error"]
