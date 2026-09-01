"""Telegram side of the bot: availability probing and claiming via channels.

Claiming works the way Telegram itself intends it to: a public channel is
created, and the username is attached to that channel. That is the only way to
hold more than one public handle on a single account.

Two hard limits shape everything here:

* Telegram allows a limited number of *public* links per account (10 for a
  regular account, more with Premium). Once that is hit, `channels.updateUsername`
  fails with CHANNELS_ADMIN_PUBLIC_TOO_MUCH and nothing else can be claimed
  until an existing public channel is freed.
* Both channel creation and username assignment are FloodWait-protected.

Every network call goes through the rate limiter and the persistent quota.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from telethon import TelegramClient, errors, functions, types

from .config import Config
from .ratelimit import Quota, QuotaExceeded, TokenBucket
from .storage import (
    STATUS_AVAILABLE,
    STATUS_CLAIMED,
    STATUS_FAILED,
    STATUS_INVALID,
    STATUS_PURCHASABLE,
    STATUS_TAKEN,
    Storage,
)

log = logging.getLogger("tgnames.client")


class Availability(str, Enum):
    FREE = "available"
    TAKEN = "taken"
    PURCHASABLE = "purchasable"   # free, but Telegram wants it sold via Fragment
    INVALID = "invalid"
    ERROR = "error"


AVAILABILITY_TO_STATUS = {
    Availability.FREE: STATUS_AVAILABLE,
    Availability.TAKEN: STATUS_TAKEN,
    Availability.PURCHASABLE: STATUS_PURCHASABLE,
    Availability.INVALID: STATUS_INVALID,
}


@dataclass
class CheckResult:
    username: str
    availability: Availability
    detail: str = ""


@dataclass
class ClaimResult:
    username: str
    ok: bool
    channel_id: int | None = None
    detail: str = ""


class StopRun(RuntimeError):
    """Raised when the run must end: quota, flood wait, or public-link limit."""


class UsernameHunter:
    def __init__(self, config: Config, storage: Storage):
        self.cfg = config
        self.db = storage
        self.client: TelegramClient | None = None

        lim = config.limits
        self.check_bucket = TokenBucket(lim.checks_per_minute, 60.0, burst=3)
        self.check_quota = Quota(storage, "check", lim.checks_per_hour, lim.checks_per_day)
        self.claim_quota = Quota(storage, "claim", lim.claims_per_hour, lim.claims_per_day)

    # -- lifecycle ----------------------------------------------------------
    async def __aenter__(self) -> "UsernameHunter":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        self.cfg.validate_credentials()
        session = Path(self.cfg.telegram.session)
        session.parent.mkdir(parents=True, exist_ok=True)
        self.client = TelegramClient(
            str(session), self.cfg.telegram.api_id, self.cfg.telegram.api_hash
        )
        await self.client.start(phone=self.cfg.telegram.phone or None)
        me = await self.client.get_me()
        log.info("signed in as @%s (id=%s)", me.username, me.id)

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
            self.client = None

    # -- flood control ------------------------------------------------------
    async def _handle_flood(self, exc: errors.FloodWaitError, what: str) -> None:
        wait = exc.seconds
        if wait > self.cfg.limits.max_floodwait_seconds:
            self.db.log("floodwait", detail=f"{what}: {wait}s — aborting")
            raise StopRun(
                f"Telegram asked to wait {wait}s before the next {what}. "
                f"That is over max_floodwait_seconds "
                f"({self.cfg.limits.max_floodwait_seconds}); stopping. Re-run later."
            )
        log.warning("flood wait on %s: sleeping %ss", what, wait)
        self.db.log("floodwait", detail=f"{what}: sleeping {wait}s")
        await asyncio.sleep(wait + 1)

    # -- availability -------------------------------------------------------
    async def check(self, username: str) -> CheckResult:
        """Ask Telegram whether a username can be attached to a new channel."""
        assert self.client is not None, "call connect() first"
        self.check_quota.check()
        await self.check_bucket.acquire()

        while True:
            try:
                free = await self.client(
                    functions.channels.CheckUsernameRequest(
                        channel=types.InputChannelEmpty(), username=username
                    )
                )
            except errors.FloodWaitError as exc:
                await self._handle_flood(exc, "username check")
                continue
            except errors.UsernameInvalidError:
                return CheckResult(username, Availability.INVALID, "rejected by Telegram")
            except errors.UsernameOccupiedError:
                return CheckResult(username, Availability.TAKEN, "occupied")
            except errors.UsernamePurchaseAvailableError:
                return CheckResult(
                    username, Availability.PURCHASABLE, "sold via Fragment auction"
                )
            except errors.RPCError as exc:
                return CheckResult(username, Availability.ERROR, f"{type(exc).__name__}: {exc}")
            finally:
                self.check_quota.consume()

            if free:
                return CheckResult(username, Availability.FREE, "free")
            return CheckResult(username, Availability.TAKEN, "occupied")

    async def scan(self, candidates, *, on_result=None) -> dict[str, int]:
        """Check a batch of candidates and write the outcome back to the DB."""
        tally: dict[str, int] = {}
        for cand in candidates:
            try:
                result = await self.check(cand.username)
            except QuotaExceeded as exc:
                raise StopRun(str(exc)) from exc

            tally[result.availability.value] = tally.get(result.availability.value, 0) + 1
            status = AVAILABILITY_TO_STATUS.get(result.availability)
            if status:
                self.db.set_status(cand.username, status, note=result.detail, checked=True)
            else:  # transient error — leave it queued for the next run
                self.db.log("check_error", cand.username, result.detail)
            if on_result:
                on_result(cand, result)
        return tally

    # -- claiming -----------------------------------------------------------
    async def claim(self, username: str, *, dry_run: bool = True) -> ClaimResult:
        """Create a channel and attach `username` to it."""
        assert self.client is not None, "call connect() first"
        if dry_run:
            return ClaimResult(username, ok=False, detail="dry-run: nothing was created")

        self.claim_quota.check()
        title = self.cfg.channel.title_template.format(username=username)
        about = self.cfg.channel.about_template.format(username=username)

        # 1. create the channel
        while True:
            try:
                created = await self.client(
                    functions.channels.CreateChannelRequest(
                        title=title[:128], about=about[:255], broadcast=True, megagroup=False
                    )
                )
                break
            except errors.FloodWaitError as exc:
                await self._handle_flood(exc, "channel creation")
            except errors.ChannelsTooMuchError as exc:
                raise StopRun(
                    "This account is in too many channels — leave some before claiming more."
                ) from exc
            except errors.RPCError as exc:
                self.db.log("claim_error", username, f"create: {exc}")
                return ClaimResult(username, ok=False, detail=f"create failed: {exc}")

        channel = created.chats[0]
        self.claim_quota.consume()

        # 2. attach the username
        try:
            while True:
                try:
                    await self.client(
                        functions.channels.UpdateUsernameRequest(
                            channel=channel, username=username
                        )
                    )
                    break
                except errors.FloodWaitError as exc:
                    await self._handle_flood(exc, "username assignment")
        except errors.UsernameOccupiedError:
            await self._cleanup(channel)
            return ClaimResult(username, ok=False, detail="taken between check and claim")
        except errors.UsernameInvalidError:
            await self._cleanup(channel)
            return ClaimResult(username, ok=False, detail="rejected by Telegram")
        except errors.UsernamePurchaseAvailableError:
            await self._cleanup(channel)
            return ClaimResult(username, ok=False, detail="only available via Fragment")
        except errors.ChannelsAdminPublicTooMuchError as exc:
            await self._cleanup(channel)
            raise StopRun(
                "Public-link limit reached for this account. Free an existing public "
                "channel (or use Telegram Premium) before claiming more."
            ) from exc
        except errors.RPCError as exc:
            await self._cleanup(channel)
            return ClaimResult(username, ok=False, detail=f"{type(exc).__name__}: {exc}")
        except StopRun:
            # A long flood wait aborts the run; do not leave the empty channel
            # sitting on the account, it still counts against the limits.
            await self._cleanup(channel)
            raise

        log.info("claimed @%s -> channel %s", username, channel.id)
        return ClaimResult(username, ok=True, channel_id=channel.id, detail="claimed")

    async def _cleanup(self, channel) -> None:
        """Delete the placeholder channel when the username could not attach."""
        if not self.cfg.channel.delete_on_failure:
            return
        try:
            await self.client(functions.channels.DeleteChannelRequest(channel=channel))
        except errors.RPCError as exc:
            log.warning("could not delete leftover channel %s: %s", channel.id, exc)

    async def claim_batch(self, candidates, *, dry_run: bool = True, on_result=None) -> dict[str, int]:
        """Claim a batch, re-checking availability immediately before each one."""
        tally = {"claimed": 0, "failed": 0, "gone": 0, "skipped": 0}
        for i, cand in enumerate(candidates):
            try:
                self.claim_quota.check()
            except QuotaExceeded as exc:
                raise StopRun(str(exc)) from exc

            # Re-verify: the queue may be hours old.
            recheck = await self.check(cand.username)
            if recheck.availability is not Availability.FREE:
                status = AVAILABILITY_TO_STATUS.get(recheck.availability, STATUS_FAILED)
                self.db.set_status(cand.username, status, note=recheck.detail, checked=True)
                tally["gone"] += 1
                if on_result:
                    on_result(cand, ClaimResult(cand.username, False, detail=recheck.detail))
                continue

            result = await self.claim(cand.username, dry_run=dry_run)
            if dry_run:
                tally["skipped"] += 1
            elif result.ok:
                self.db.set_status(
                    cand.username, STATUS_CLAIMED, note=result.detail,
                    channel_id=result.channel_id, claimed=True,
                )
                self.db.log("claimed", cand.username, f"channel {result.channel_id}")
                tally["claimed"] += 1
            else:
                self.db.set_status(cand.username, STATUS_FAILED, note=result.detail)
                self.db.log("claim_failed", cand.username, result.detail)
                tally["failed"] += 1
            if on_result:
                on_result(cand, result)

            cooldown = self.cfg.limits.claim_cooldown_seconds
            if not dry_run and cooldown > 0 and i < len(candidates) - 1:
                await asyncio.sleep(cooldown)
        return tally

    # -- inventory ----------------------------------------------------------
    async def owned_public_channels(self) -> list[tuple[int, str, str]]:
        """(id, username, title) for every public channel this account admins."""
        assert self.client is not None, "call connect() first"
        out = []
        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, types.Channel) and entity.username and entity.creator:
                out.append((entity.id, entity.username, entity.title))
        return out
