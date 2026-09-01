import pytest

from tgnames.ratelimit import Quota, QuotaExceeded
from tgnames.scoring import analyze_many
from tgnames.storage import (
    STATUS_AVAILABLE,
    STATUS_CLAIMED,
    STATUS_INVALID,
    STATUS_NEW,
    Storage,
)


@pytest.fixture()
def db(tmp_path):
    with Storage(tmp_path / "test.db") as store:
        yield store


def test_upsert_counts_only_new_rows(db):
    values = analyze_many(["money", "lunar", "goldbank"])
    assert db.upsert_many(values, source="test") == 3
    assert db.upsert_many(values, source="test") == 0
    assert sum(db.stats().values()) == 3


def test_invalid_candidates_are_stored_as_invalid(db):
    db.upsert_many(analyze_many(["money", "zz"]), source="test")
    assert db.stats()[STATUS_INVALID] == 1


def test_queue_is_ordered_by_score(db):
    db.upsert_many(analyze_many(["money", "goldbanking", "lunar"]), source="test")
    queue = db.queue(STATUS_NEW, limit=10)
    assert [c.username for c in queue] == sorted(
        [c.username for c in queue], key=lambda u: -db.get(u).score
    )
    assert queue[0].username == "money"


def test_queue_respects_min_score(db):
    db.upsert_many(analyze_many(["money", "goldbanking"]), source="test")
    assert [c.username for c in db.queue(STATUS_NEW, 10, min_score=85.0)] == ["money"]


def test_queue_excludes_tags(db):
    db.upsert_many(analyze_many(["money", "telegram"]), source="test")
    names = [c.username for c in db.queue(STATUS_NEW, 10, min_score=0, exclude_tags=("reserved",))]
    assert "telegram" not in names


def test_status_transitions_are_persisted(db):
    db.upsert_many(analyze_many(["money"]), source="test")
    db.set_status("money", STATUS_AVAILABLE, note="free", checked=True)
    assert db.get("money").status == STATUS_AVAILABLE
    assert db.get("money").checked_at is not None

    db.set_status("money", STATUS_CLAIMED, channel_id=555, claimed=True)
    row = db.get("money")
    assert row.status == STATUS_CLAIMED and row.channel_id == 555 and row.claimed_at


def test_events_are_logged(db):
    db.log("claimed", "money", "channel 1")
    events = db.recent_events(5)
    assert events[0]["kind"] == "claimed" and events[0]["username"] == "money"


def test_meta_roundtrip(db):
    assert db.get_meta("missing", "fallback") == "fallback"
    db.set_meta("k", "v")
    db.set_meta("k", "v2")
    assert db.get_meta("k") == "v2"


class TestQuota:
    def test_blocks_at_hourly_limit(self, db):
        quota = Quota(db, "claim", per_hour=2, per_day=10)
        for _ in range(2):
            quota.check()
            quota.consume()
        with pytest.raises(QuotaExceeded) as exc:
            quota.check()
        assert exc.value.window == "hourly"

    def test_blocks_at_daily_limit(self, db):
        quota = Quota(db, "claim", per_hour=100, per_day=1)
        quota.check()
        quota.consume()
        with pytest.raises(QuotaExceeded) as exc:
            quota.check()
        assert exc.value.window == "daily"

    def test_survives_a_restart(self, tmp_path):
        path = tmp_path / "quota.db"
        with Storage(path) as store:
            Quota(store, "claim", 5, 5).consume()
        with Storage(path) as store:
            assert Quota(store, "claim", 5, 5).remaining() == (4, 4)
