from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Ведро с токенами: не больше `rate` проверок в секунду.

    Часы и сон передаются извне — иначе тест такого класса идёт в реальном
    времени и либо тормозит, либо врёт.
    """

    def __init__(
        self,
        rate: float,
        burst: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.rate = max(rate, 0.05)
        self.burst = max(burst if burst is not None else self.rate, 1.0)
        self._clock = clock
        self._sleep = sleep
        self._tokens = self.burst
        self._updated = clock()
        self._blocked_until = 0.0

    def pause(self, seconds: float) -> None:
        """Telegram ответил 429 — переждать для всех проверок сразу."""

        self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    @property
    def paused_for(self) -> float:
        return max(0.0, self._blocked_until - self._clock())

    async def acquire(self) -> None:
        while True:
            now = self._clock()

            if now < self._blocked_until:
                await self._sleep(self._blocked_until - now)
                continue

            elapsed = max(0.0, now - self._updated)
            self._updated = now
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            await self._sleep((1.0 - self._tokens) / self.rate)
