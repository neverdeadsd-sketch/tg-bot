"""Tests for the Telegram layer, with the API mocked out.

No account, no network: a fake client returns whatever the test needs so the
error mapping, flood handling and cleanup paths can all be exercised.
"""

import pytest
from telethon import errors, functions, types

from tgnames.client import Availability, StopRun, UsernameHunter
from tgnames.config import Config
from tgnames.scoring import analyze_many
from tgnames.storage import (
    STATUS_AVAILABLE,
    STATUS_CLAIMED,
    STATUS_FAILED,
    STATUS_NEW,
    STATUS_TAKEN,
    Storage,
)


class FakeClient:
    """Stands in for TelegramClient; replays a scripted list of outcomes."""

    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request)
        if not self.outcomes:
            raise AssertionError(f"unexpected request: {type(request).__name__}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(request)
        return outcome

    def called(self, request_type) -> int:
        return sum(1 for c in self.calls if isinstance(c, request_type))


def make_channel(channel_id: int = 4242):
    channel = types.Channel(
        id=channel_id, title="@test", photo=None, date=None,
        creator=True, left=False, broadcast=True, verified=False,
        megagroup=False, restricted=False, signatures=False, min=False,
        scam=False, has_link=False, has_geo=False, slowmode_enabled=False,
        access_hash=1, username=None, restriction_reason=None,
        admin_rights=None, banned_rights=None, default_banned_rights=None,
        participants_count=None,
    )
    return types.Updates(
        updates=[], users=[], chats=[channel], date=None, seq=0
    )


@pytest.fixture()
def env(tmp_path):
    cfg = Config()
    cfg.telegram.api_id = 1
    cfg.telegram.api_hash = "x"
    cfg.limits.checks_per_minute = 10000  # do not slow the tests down
    cfg.limits.claim_cooldown_seconds = 0
    cfg.limits.max_floodwait_seconds = 60
    store = Storage(tmp_path / "t.db")
    yield cfg, store
    store.close()


def hunter_with(env, outcomes):
    cfg, store = env
    hunter = UsernameHunter(cfg, store)
    hunter.client = FakeClient(outcomes)
    return hunter, store


class TestCheck:
    async def test_free(self, env):
        hunter, _ = hunter_with(env, [True])
        assert (await hunter.check("money")).availability is Availability.FREE

    async def test_occupied_by_boolean(self, env):
        hunter, _ = hunter_with(env, [False])
        assert (await hunter.check("money")).availability is Availability.TAKEN

    @pytest.mark.parametrize("error,expected", [
        (errors.UsernameOccupiedError(request=None), Availability.TAKEN),
        (errors.UsernameInvalidError(request=None), Availability.INVALID),
        (errors.UsernamePurchaseAvailableError(request=None), Availability.PURCHASABLE),
    ])
    async def test_error_mapping(self, env, error, expected):
        hunter, _ = hunter_with(env, [error])
        assert (await hunter.check("money")).availability is expected

    async def test_unexpected_rpc_error_is_not_fatal(self, env):
        hunter, _ = hunter_with(env, [errors.RPCError(request=None, message="boom")])
        assert (await hunter.check("money")).availability is Availability.ERROR

    async def test_short_floodwait_is_retried(self, env):
        flood = errors.FloodWaitError(request=None)
        flood.seconds = 0
        hunter, _ = hunter_with(env, [flood, True])
        result = await hunter.check("money")
        assert result.availability is Availability.FREE
        assert hunter.client.called(functions.channels.CheckUsernameRequest) == 2

    async def test_long_floodwait_stops_the_run(self, env):
        flood = errors.FloodWaitError(request=None)
        flood.seconds = 9999
        hunter, _ = hunter_with(env, [flood])
        with pytest.raises(StopRun, match="9999"):
            await hunter.check("money")

    async def test_quota_is_consumed(self, env):
        hunter, _ = hunter_with(env, [True, True])
        before = hunter.check_quota.remaining()[0]
        await hunter.check("money")
        assert hunter.check_quota.remaining()[0] == before - 1


class TestScan:
    async def test_writes_statuses_back(self, env):
        cfg, store = env
        store.upsert_many(analyze_many(["money", "lunar"]), source="test")
        hunter, _ = hunter_with(env, [True, errors.UsernameOccupiedError(request=None)])
        queue = store.queue(STATUS_NEW, 2)
        tally = await hunter.scan(queue)
        assert tally == {"available": 1, "taken": 1}
        statuses = {c.username: c.status for c in store.all_by_status()}
        assert statuses["money"] == STATUS_AVAILABLE
        assert statuses["lunar"] == STATUS_TAKEN
        assert store.get("money").checked_at is not None

    async def test_transient_error_leaves_the_candidate_queued(self, env):
        cfg, store = env
        store.upsert_many(analyze_many(["money"]), source="test")
        hunter, _ = hunter_with(env, [errors.RPCError(request=None, message="boom")])
        await hunter.scan(store.queue(STATUS_NEW, 1))
        assert store.get("money").status == STATUS_NEW

    async def test_exhausted_quota_stops_the_run(self, env):
        cfg, store = env
        cfg.limits.checks_per_hour = 0
        store.upsert_many(analyze_many(["money"]), source="test")
        hunter = UsernameHunter(cfg, store)
        hunter.client = FakeClient([True])
        with pytest.raises(StopRun):
            await hunter.scan(store.queue(STATUS_NEW, 1))


class TestClaim:
    async def test_dry_run_touches_nothing(self, env):
        hunter, _ = hunter_with(env, [])
        result = await hunter.claim("money", dry_run=True)
        assert not result.ok and hunter.client.calls == []

    async def test_successful_claim(self, env):
        hunter, _ = hunter_with(env, [make_channel(777), True])
        result = await hunter.claim("money", dry_run=False)
        assert result.ok and result.channel_id == 777
        assert hunter.client.called(functions.channels.CreateChannelRequest) == 1
        assert hunter.client.called(functions.channels.UpdateUsernameRequest) == 1

    async def test_username_lost_mid_flight_deletes_the_channel(self, env):
        hunter, _ = hunter_with(env, [
            make_channel(), errors.UsernameOccupiedError(request=None), True,
        ])
        result = await hunter.claim("money", dry_run=False)
        assert not result.ok
        assert hunter.client.called(functions.channels.DeleteChannelRequest) == 1

    async def test_public_link_limit_stops_the_run(self, env):
        hunter, _ = hunter_with(env, [
            make_channel(), errors.ChannelsAdminPublicTooMuchError(request=None), True,
        ])
        with pytest.raises(StopRun, match="Public-link limit"):
            await hunter.claim("money", dry_run=False)
        assert hunter.client.called(functions.channels.DeleteChannelRequest) == 1

    async def test_cleanup_can_be_disabled(self, env):
        cfg, _ = env
        cfg.channel.delete_on_failure = False
        hunter, _ = hunter_with(env, [
            make_channel(), errors.UsernameInvalidError(request=None),
        ])
        await hunter.claim("money", dry_run=False)
        assert hunter.client.called(functions.channels.DeleteChannelRequest) == 0

    async def test_claim_quota_blocks(self, env):
        cfg, store = env
        cfg.limits.claims_per_day = 0
        hunter = UsernameHunter(cfg, store)
        hunter.client = FakeClient([])
        from tgnames.ratelimit import QuotaExceeded
        with pytest.raises(QuotaExceeded):
            await hunter.claim("money", dry_run=False)


class TestClaimBatch:
    async def test_rechecks_before_claiming(self, env):
        cfg, store = env
        store.upsert_many(analyze_many(["money"]), source="test")
        store.set_status("money", STATUS_AVAILABLE)
        # Re-check says it is gone -> no channel is created.
        hunter, _ = hunter_with(env, [errors.UsernameOccupiedError(request=None)])
        tally = await hunter.claim_batch(store.queue(STATUS_AVAILABLE, 1), dry_run=False)
        assert tally["gone"] == 1 and tally["claimed"] == 0
        assert store.get("money").status == STATUS_TAKEN
        assert hunter.client.called(functions.channels.CreateChannelRequest) == 0

    async def test_records_a_successful_claim(self, env):
        cfg, store = env
        store.upsert_many(analyze_many(["money"]), source="test")
        store.set_status("money", STATUS_AVAILABLE)
        hunter, _ = hunter_with(env, [True, make_channel(999), True])
        tally = await hunter.claim_batch(store.queue(STATUS_AVAILABLE, 1), dry_run=False)
        assert tally["claimed"] == 1
        row = store.get("money")
        assert row.status == STATUS_CLAIMED and row.channel_id == 999 and row.claimed_at

    async def test_records_a_failed_claim(self, env):
        cfg, store = env
        store.upsert_many(analyze_many(["money"]), source="test")
        store.set_status("money", STATUS_AVAILABLE)
        hunter, _ = hunter_with(env, [
            True, make_channel(), errors.RPCError(request=None, message="nope"), True,
        ])
        tally = await hunter.claim_batch(store.queue(STATUS_AVAILABLE, 1), dry_run=False)
        assert tally["failed"] == 1
        assert store.get("money").status == STATUS_FAILED

    async def test_dry_run_batch_creates_nothing(self, env):
        cfg, store = env
        store.upsert_many(analyze_many(["money"]), source="test")
        store.set_status("money", STATUS_AVAILABLE)
        hunter, _ = hunter_with(env, [True])
        tally = await hunter.claim_batch(store.queue(STATUS_AVAILABLE, 1), dry_run=True)
        assert tally["skipped"] == 1
        assert hunter.client.called(functions.channels.CreateChannelRequest) == 0


class TestFloodCleanup:
    async def test_flood_abort_removes_the_placeholder_channel(self, env):
        flood = errors.FloodWaitError(request=None)
        flood.seconds = 9999
        hunter, _ = hunter_with(env, [make_channel(), flood, True])
        with pytest.raises(StopRun):
            await hunter.claim("money", dry_run=False)
        assert hunter.client.called(functions.channels.DeleteChannelRequest) == 1
