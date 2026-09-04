"""End-to-end tests of the offline CLI paths (no Telegram account involved)."""

import json
import sys

import pytest

from tgnames.cli import main
from tgnames.storage import STATUS_AVAILABLE, Storage


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "cli.db")


def run(args, db_path):
    return main(["--db", db_path] + args)


class TestAnalyze:
    def test_prints_a_table(self, db_path, capsys):
        assert run(["analyze", "money", "@lunar"], db_path) == 0
        out = capsys.readouterr().out
        assert "money" in out and "lunar" in out and "tier" in out

    def test_json_output_is_parsable(self, db_path, capsys):
        assert run(["analyze", "money", "--json"], db_path) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["username"] == "money" and payload[0]["valid"]

    def test_explain_shows_components(self, db_path, capsys):
        run(["analyze", "goldbank", "--explain"], db_path)
        out = capsys.readouterr().out
        assert "components:" in out and "lexical=" in out

    def test_invalid_is_hidden_unless_asked(self, db_path, capsys):
        run(["analyze", "money", "zz"], db_path)
        assert "zz" not in capsys.readouterr().out
        run(["analyze", "money", "zz", "--all"], db_path)
        assert "zz" in capsys.readouterr().out

    def test_reads_a_file(self, tmp_path, db_path, capsys):
        src = tmp_path / "in.txt"
        src.write_text("money\n@lunar\n# skip\n", encoding="utf-8")
        assert run(["analyze", "--file", str(src)], db_path) == 0
        out = capsys.readouterr().out
        assert "money" in out and "lunar" in out

    def test_no_input_is_an_error(self, db_path):
        assert run(["analyze"], db_path) == 2


class TestGenerate:
    def test_fills_the_database(self, db_path, capsys):
        assert run(["generate", "-s", "words", "-n", "10"], db_path) == 0
        assert "kept=10" in capsys.readouterr().out
        with Storage(db_path) as db:
            assert sum(db.stats().values()) == 10

    def test_keeps_the_highest_scoring(self, db_path):
        run(["generate", "-s", "words", "-n", "5", "--no-filter"], db_path)
        with Storage(db_path) as db:
            scores = [c.score for c in db.all_by_status()]
        assert scores == sorted(scores, reverse=True)
        assert min(scores) > 80  # top-5 dictionary words, not the first five

    def test_min_score_filters(self, db_path):
        run(["generate", "-s", "words", "-n", "50", "--min-score", "90"], db_path)
        with Storage(db_path) as db:
            assert all(c.score >= 90 for c in db.all_by_status())

    def test_excludes_risky_tags_by_default(self, tmp_path, db_path):
        src = tmp_path / "seed.txt"
        src.write_text("telegram\ngoldbank\n", encoding="utf-8")
        run(["generate", "-f", str(src), "--min-score", "0"], db_path)
        with Storage(db_path) as db:
            assert [c.username for c in db.all_by_status()] == ["goldbank"]

    def test_excludes_reserved_handles_by_default(self, tmp_path, db_path):
        """Five-character handles are auctioned, not given away."""
        src = tmp_path / "seed.txt"
        src.write_text("elite\ngoldbank\n", encoding="utf-8")
        run(["generate", "-f", str(src), "--min-score", "0"], db_path)
        with Storage(db_path) as db:
            assert [c.username for c in db.all_by_status()] == ["goldbank"]

    def test_min_length_filters(self, db_path):
        run(["generate", "-s", "all", "-n", "40", "--min-length", "8"], db_path)
        with Storage(db_path) as db:
            assert all(len(c.username) >= 8 for c in db.all_by_status())

    def test_no_filter_keeps_them(self, tmp_path, db_path):
        src = tmp_path / "seed.txt"
        src.write_text("telegram\ngoldbank\n", encoding="utf-8")
        run(["generate", "-f", str(src), "--min-score", "0", "--no-filter"], db_path)
        with Storage(db_path) as db:
            assert len(db.all_by_status()) == 2

    def test_is_idempotent(self, db_path):
        run(["generate", "-s", "words", "-n", "10"], db_path)
        run(["generate", "-s", "words", "-n", "10"], db_path)
        with Storage(db_path) as db:
            assert sum(db.stats().values()) == 10


class TestClaimSafety:
    def test_defaults_to_a_dry_run(self, db_path, capsys):
        assert run(["claim", "money"], db_path) == 0
        out = capsys.readouterr().out
        assert "DRY RUN" in out and "Nothing was created" in out

    def test_skips_invalid_handles(self, db_path, capsys):
        run(["claim", "zz", "money"], db_path)
        out = capsys.readouterr().out
        assert "skipping @zz" in out and "1 candidate" in out

    def test_reports_an_empty_queue(self, db_path, capsys):
        assert run(["claim"], db_path) == 0
        assert "run `scan` first" in capsys.readouterr().out


class TestReporting:
    def test_list_and_stats(self, db_path, capsys):
        run(["generate", "-s", "words", "-n", "5"], db_path)
        capsys.readouterr()
        assert run(["list"], db_path) == 0
        assert "username" in capsys.readouterr().out
        assert run(["stats"], db_path) == 0
        out = capsys.readouterr().out
        assert "candidates: 5" in out and "quota claim" in out

    def test_export_csv(self, db_path, tmp_path, capsys):
        run(["generate", "-s", "words", "-n", "3"], db_path)
        capsys.readouterr()
        out_file = tmp_path / "out.csv"
        assert run(["export", "--format", "csv", "-o", str(out_file)], db_path) == 0
        lines = out_file.read_text(encoding="utf-8").strip().splitlines()
        assert lines[0].startswith("username,score") and len(lines) == 4

    def test_export_json(self, db_path, capsys):
        run(["generate", "-s", "words", "-n", "3"], db_path)
        capsys.readouterr()
        run(["export", "--format", "json"], db_path)
        assert len(json.loads(capsys.readouterr().out)) == 3

    def test_list_filters_by_status(self, db_path, capsys):
        run(["generate", "-s", "words", "-n", "5"], db_path)
        with Storage(db_path) as db:
            db.set_status(db.all_by_status()[0].username, STATUS_AVAILABLE)
        capsys.readouterr()
        run(["list", "--status", STATUS_AVAILABLE], db_path)
        assert len(capsys.readouterr().out.strip().splitlines()) == 3  # header, rule, row


def _hide_telethon(monkeypatch):
    """Make `import telethon` fail, as it does on a machine without the dep."""
    import tgnames

    for name in [m for m in list(sys.modules) if m == "telethon" or m.startswith("telethon.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delitem(sys.modules, "tgnames.client", raising=False)
    # `from . import client` short-circuits on the cached package attribute.
    monkeypatch.delattr(tgnames, "client", raising=False)
    monkeypatch.setitem(sys.modules, "telethon", None)


class TestWithoutTelethon:
    """The offline half of the tool must run with zero dependencies."""

    @pytest.mark.parametrize("argv", [
        ["analyze", "money"],
        ["generate", "-s", "words", "-n", "3"],
        ["list"],
        ["stats"],
        ["export", "--format", "json"],
    ])
    def test_offline_commands_still_work(self, monkeypatch, db_path, argv):
        _hide_telethon(monkeypatch)
        assert run(argv, db_path) == 0

    def test_dry_run_claim_needs_no_telethon(self, monkeypatch, db_path, capsys):
        _hide_telethon(monkeypatch)
        assert run(["claim", "money"], db_path) == 0
        out = capsys.readouterr().out
        assert "DRY RUN" in out and "quota left" in out

    @pytest.mark.parametrize("argv", [
        ["scan", "-n", "1"],
        ["claim", "money", "--execute", "-y"],
        ["login"],
        ["inventory"],
    ])
    def test_online_commands_explain_the_missing_dependency(self, monkeypatch, db_path, argv):
        _hide_telethon(monkeypatch)
        with pytest.raises(SystemExit) as exc:
            run(argv, db_path)
        message = str(exc.value)
        assert "Telethon" in message and "pip install -r requirements.txt" in message
        assert "Traceback" not in message


class TestScanWeb:
    """`scan --web` must work with no api_id and no Telethon installed."""

    def _install_fake_http(self, monkeypatch, default=None, extra=None):
        from tests.test_webcheck import CONTROLS, FREE_PAGE, RICH_PAGE, FakeOpener
        import tgnames.webcheck as webcheck

        pages = dict(CONTROLS)
        pages["goldbank"] = RICH_PAGE
        pages.update(extra or {})
        opener = FakeOpener(pages, default if default is not None else FREE_PAGE)
        monkeypatch.setattr(
            webcheck.urllib.request, "build_opener", lambda *a, **k: opener
        )
        return opener

    def test_runs_without_telethon(self, monkeypatch, db_path, capsys):
        self._install_fake_http(monkeypatch)
        _hide_telethon(monkeypatch)
        run(["mark", "goldbank", "vaultpay", "--status", "new"], db_path)
        capsys.readouterr()
        assert run(["scan", "--web", "--delay", "0", "-n", "3"], db_path) == 0
        out = capsys.readouterr().out
        assert "Calibrated on 6 pages" in out
        assert "taken" in out and "no owner" in out

    def test_writes_statuses_with_provenance(self, monkeypatch, db_path, capsys):
        self._install_fake_http(monkeypatch)
        run(["mark", "goldbank", "--status", "new"], db_path)
        run(["scan", "--web", "--delay", "0", "-n", "3"], db_path)
        capsys.readouterr()
        with Storage(db_path) as db:
            row = db.get("goldbank")
            assert row.status == "taken"
            assert row.note == "via t.me page: owner visible"
            assert row.checked_at is not None

    def test_calibrate_only_checks_nothing(self, monkeypatch, db_path, capsys):
        opener = self._install_fake_http(monkeypatch)
        run(["generate", "-s", "words", "-n", "3"], db_path)
        capsys.readouterr()
        assert run(["scan", "--web", "--calibrate-only", "--delay", "0"], db_path) == 0
        assert "Calibration succeeded" in capsys.readouterr().out
        assert len(opener.requested) == 6  # controls only

    def test_refuses_when_it_cannot_calibrate(self, monkeypatch, db_path, capsys):
        from tests.test_webcheck import RICH_PAGE
        self._install_fake_http(monkeypatch, default=RICH_PAGE)
        run(["generate", "-s", "words", "-n", "3"], db_path)
        capsys.readouterr()
        assert run(["scan", "--web", "--delay", "0"], db_path) == 1
        assert "Calibration failed" in capsys.readouterr().err
        with Storage(db_path) as db:
            assert all(c.status == "new" for c in db.all_by_status())

    def test_free_pages_are_not_recorded_as_claimable(self, monkeypatch, db_path, capsys):
        """Regression: Telegram reserves short words, so 'no owner' != free.

        @elite has no owner and renders like a free page, but it is held back
        for the Fragment auction and cannot be claimed.
        """
        self._install_fake_http(monkeypatch)
        run(["mark", "elite", "--status", "new"], db_path)
        capsys.readouterr()
        run(["scan", "--web", "--delay", "0", "-n", "5", "--include-reserved"], db_path)
        out = capsys.readouterr().out
        with Storage(db_path) as db:
            row = db.get("elite")
        assert row.status == "unclaimed", "must not be recorded as available"
        assert "likely-reserved" in row.tags
        assert "not the same as claimable" in out
        assert "likely-reserved and are probably NOT free" in out

    def test_unknown_verdicts_stay_queued(self, monkeypatch, db_path, capsys):
        """An unjudgeable handle must never be recorded as available."""
        from tests.test_webcheck import STRANGE_PAGE
        self._install_fake_http(monkeypatch, extra={"vaultpay": STRANGE_PAGE})
        run(["mark", "vaultpay", "--status", "new"], db_path)
        capsys.readouterr()
        run(["scan", "--web", "--delay", "0", "-n", "3"], db_path)
        out = capsys.readouterr().out
        assert "NOT free, just unknown" in out
        with Storage(db_path) as db:
            assert db.get("vaultpay").status == "new"

    def test_throttling_stops_the_run(self, monkeypatch, db_path, capsys):
        from tests.test_webcheck import DEGRADED_PAGE
        opener = self._install_fake_http(monkeypatch)
        run(["generate", "-s", "compounds", "-n", "20"], db_path)
        capsys.readouterr()
        import tgnames.webcheck as webcheck
        real_calibrate = webcheck.WebChecker.calibrate

        def calibrate_then_degrade(self, on_sample=None):
            result = real_calibrate(self, on_sample=on_sample)
            opener.default = DEGRADED_PAGE
            opener.pages.clear()
            return result

        monkeypatch.setattr(webcheck.WebChecker, "calibrate", calibrate_then_degrade)
        assert run(["scan", "--web", "--delay", "0", "-n", "20"], db_path) == 1
        assert "Stopped:" in capsys.readouterr().err
        with Storage(db_path) as db:
            assert not [c for c in db.all_by_status() if c.status == "available"]

    def test_extra_controls_are_passed_through(self, monkeypatch, db_path, capsys):
        from tests.test_webcheck import RICH_PAGE
        opener = self._install_fake_http(monkeypatch, extra={"mine": RICH_PAGE})
        assert run(["scan", "--web", "--calibrate-only", "--delay", "0",
                    "--control", "mine"], db_path) == 0
        assert "mine" in opener.requested


class TestMark:
    def test_defaults_to_claimed(self, db_path, capsys):
        assert run(["mark", "money"], db_path) == 0
        assert "-> claimed" in capsys.readouterr().out
        with Storage(db_path) as db:
            row = db.get("money")
            assert row.status == "claimed" and row.claimed_at is not None

    def test_creates_unknown_handles(self, db_path):
        run(["mark", "goldbank", "--status", "taken"], db_path)
        with Storage(db_path) as db:
            assert db.get("goldbank").status == "taken"

    def test_updates_an_existing_row_without_duplicating(self, db_path):
        run(["generate", "-s", "words", "-n", "5"], db_path)
        with Storage(db_path) as db:
            name = db.all_by_status()[0].username
            before = len(db.all_by_status())
        run(["mark", name], db_path)
        with Storage(db_path) as db:
            assert len(db.all_by_status()) == before
            assert db.get(name).status == "claimed"

    def test_skips_invalid(self, db_path, capsys):
        run(["mark", "zz", "money"], db_path)
        out = capsys.readouterr().out
        assert "skipping @zz" in out and "1 handle(s) updated" in out

    def test_marked_handles_leave_the_scan_queue(self, db_path):
        run(["generate", "-s", "words", "-n", "5"], db_path)
        with Storage(db_path) as db:
            name = db.all_by_status()[0].username
        run(["mark", name, "--status", "skipped"], db_path)
        with Storage(db_path) as db:
            assert name not in [c.username for c in db.queue("new", 10)]

    def test_works_without_telethon(self, monkeypatch, db_path):
        _hide_telethon(monkeypatch)
        assert run(["mark", "money"], db_path) == 0


class TestRescore:
    def test_refreshes_stale_scores_and_tags(self, db_path, capsys):
        """A scoring change must be able to reach rows already stored."""
        import json
        import sqlite3

        run(["generate", "-s", "words", "-n", "5", "--no-filter"], db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("UPDATE candidates SET score=1.0, tags='[]'")
        capsys.readouterr()

        assert run(["rescore"], db_path) == 0
        assert "changed" in capsys.readouterr().out
        with Storage(db_path) as db:
            for row in db.all_by_status():
                assert row.score > 1.0
                assert row.tags

    def test_reports_newly_added_tags(self, db_path, capsys):
        import json
        import sqlite3

        run(["mark", "elite", "--status", "new"], db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("UPDATE candidates SET tags=? WHERE username='elite'",
                        (json.dumps(["premium"]),))
        capsys.readouterr()
        run(["rescore"], db_path)
        assert "+likely-reserved" in capsys.readouterr().out

    def test_works_without_telethon(self, monkeypatch, db_path):
        _hide_telethon(monkeypatch)
        run(["mark", "goldbank", "--status", "new"], db_path)
        assert run(["rescore"], db_path) == 0


class TestStatsByLength:
    def test_breaks_results_down_by_length(self, db_path, capsys):
        run(["mark", "elite", "--status", "invalid"], db_path)
        run(["mark", "goldbank", "--status", "taken"], db_path)
        run(["mark", "vaultpay", "--status", "unclaimed"], db_path)
        capsys.readouterr()
        run(["stats"], db_path)
        out = capsys.readouterr().out
        assert "checked handles by length" in out
        assert "API-confirmed" in out
        # Length 5 exhausted, length 8 still has unverified candidates.
        lines = [l.split() for l in out.splitlines() if l.strip().startswith(("5 ", "8 "))]
        by_length = {int(l[0]): l for l in lines}
        assert by_length[5][3] == "1"   # reserved
        assert by_length[8][2] == "1"   # taken
        assert by_length[8][4] == "1"   # no owner


class TestScanWebFragment:
    """A handle can be ownerless on t.me and still be on sale at Fragment."""

    def _install(self, monkeypatch, tme_extra=None, fragment_pages=None):
        from tests.test_webcheck import (
            CONTROLS, FRAGMENT_ABSENT, FRAGMENT_LISTED, FREE_PAGE, FakeOpener,
        )
        import tgnames.webcheck as webcheck

        tme = FakeOpener({**CONTROLS, **(tme_extra or {})}, FREE_PAGE)
        frag = FakeOpener(fragment_pages or {}, FRAGMENT_ABSENT)

        def build_opener(*a, **k):
            # The scan builds the t.me opener first, then the Fragment one.
            return tme if build_opener.calls.append(1) or len(build_opener.calls) == 1 else frag

        build_opener.calls = []
        monkeypatch.setattr(webcheck.urllib.request, "build_opener", build_opener)
        return tme, frag

    def test_listed_handle_becomes_purchasable(self, monkeypatch, db_path, capsys):
        from tests.test_webcheck import FRAGMENT_LISTED
        self._install(monkeypatch, fragment_pages={
            "alalal": FRAGMENT_LISTED, "vaultpay": FRAGMENT_LISTED,
        })
        run(["mark", "vaultpay", "--status", "new"], db_path)
        capsys.readouterr()
        assert run(["scan", "--web", "--delay", "0", "-n", "3",
                    "--fragment-control", "alalal"], db_path) == 0
        out = capsys.readouterr().out
        assert "for sale" in out
        with Storage(db_path) as db:
            row = db.get("vaultpay")
        assert row.status == "purchasable"
        assert "Fragment" in row.note

    def test_unlisted_handle_stays_unclaimed(self, monkeypatch, db_path, capsys):
        from tests.test_webcheck import FRAGMENT_LISTED
        self._install(monkeypatch, fragment_pages={"alalal": FRAGMENT_LISTED})
        run(["mark", "vaultpay", "--status", "new"], db_path)
        capsys.readouterr()
        run(["scan", "--web", "--delay", "0", "-n", "3",
             "--fragment-control", "alalal"], db_path)
        with Storage(db_path) as db:
            assert db.get("vaultpay").status == "unclaimed"

    def test_without_a_control_the_gap_is_stated(self, monkeypatch, db_path, capsys):
        self._install(monkeypatch)
        run(["mark", "vaultpay", "--status", "new"], db_path)
        capsys.readouterr()
        run(["scan", "--web", "--delay", "0", "-n", "3"], db_path)
        out = capsys.readouterr().out
        assert "No --fragment-control given" in out
        assert "Fragment cross-check did not run" in out

    def test_a_bad_control_disables_the_check_without_failing(
        self, monkeypatch, db_path, capsys
    ):
        from tests.test_webcheck import FRAGMENT_ABSENT
        self._install(monkeypatch, fragment_pages={"notlisted": FRAGMENT_ABSENT})
        run(["mark", "vaultpay", "--status", "new"], db_path)
        capsys.readouterr()
        assert run(["scan", "--web", "--delay", "0", "-n", "3",
                    "--fragment-control", "notlisted"], db_path) == 0
        err = capsys.readouterr().err
        assert "Fragment check unavailable" in err

    def test_listed_handles_are_labelled_for_sale_not_reserved(
        self, monkeypatch, db_path, capsys
    ):
        """The per-line label must match the verdict that was stored."""
        from tests.test_webcheck import FRAGMENT_LISTED
        self._install(monkeypatch, fragment_pages={
            "alalal": FRAGMENT_LISTED, "asasas": FRAGMENT_LISTED,
        })
        run(["mark", "asasas", "--status", "new"], db_path)
        capsys.readouterr()
        run(["scan", "--web", "--delay", "0", "-n", "3", "--include-reserved",
             "--fragment-control", "alalal"], db_path)
        line = next(l for l in capsys.readouterr().out.splitlines()
                    if "@asasas" in l)
        assert "for sale" in line and "reserved?" not in line
