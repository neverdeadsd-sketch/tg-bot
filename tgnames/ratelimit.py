"""Rate limiting.

Two layers, both mandatory:

* a token bucket that spaces individual API calls inside one run;
* persistent hourly/daily quotas in SQLite, so restarting the process cannot
  be used to bypass them.

Telegram punishes bursts with FloodWait, and creating public channels is one
of the most aggressively limited actions there is. The defaults are
deliberately conservative.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from .storage import Storage


def _hour_bucket(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y%m%d%H")


def _day_bucket(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y%m%d")


class QuotaExceeded(RuntimeError):
    def __init__(self, name: str, window: str, limit: int):
        super().__init__(f"{name}: {window} quota of {limit} reached")
        self.name = name
        self.window = window
        self.limit = limit


class TokenBucket:
    """Simple async rate limiter: `rate` operations per `per` seconds."""

    def __init__(self, rate: float, per: float = 60.0, burst: int = 1):
        self.rate = max(rate, 0.001)
        self.per = per
        self.capacity = max(1, burst)
        self._tokens = float(self.capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(
                    float(self.capacity), self._tokens + elapsed * (self.rate / self.per)
                )
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                await asyncio.sleep(deficit * (self.per / self.rate))


class Quota:
    """Persistent hourly + daily counter pair."""

    def __init__(self, storage: Storage, name: str, per_hour: int, per_day: int):
        self.storage = storage
        self.name = name
        self.per_hour = per_hour
        self.per_day = per_day

    def remaining(self) -> tuple[int, int]:
        used_h = self.storage.counter(f"{self.name}_h", _hour_bucket())
        used_d = self.storage.counter(f"{self.name}_d", _day_bucket())
        return max(0, self.per_hour - used_h), max(0, self.per_day - used_d)

    def check(self) -> None:
        left_h, left_d = self.remaining()
        if left_d <= 0:
            raise QuotaExceeded(self.name, "daily", self.per_day)
        if left_h <= 0:
            raise QuotaExceeded(self.name, "hourly", self.per_hour)

    def consume(self, n: int = 1) -> None:
        self.storage.bump(f"{self.name}_h", _hour_bucket(), n)
        self.storage.bump(f"{self.name}_d", _day_bucket(), n)
