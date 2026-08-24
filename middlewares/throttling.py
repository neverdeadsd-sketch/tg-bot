"""Простой антифлуд: не чаще одного события в N секунд от одного user_id."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

import texts

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate: float = 0.4, cleanup_after: int = 3600) -> None:
        self.rate = rate
        self.cleanup_after = cleanup_after
        self._last: dict[int, float] = {}
        self._last_cleanup = time.monotonic()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        self._cleanup(now)

        previous = self._last.get(user.id)
        if previous is not None and now - previous < self.rate:
            logger.debug("Троттлинг для user_id=%s", user.id)
            await self._reject(event)
            return None

        self._last[user.id] = now
        return await handler(event, data)

    async def _reject(self, event: TelegramObject) -> None:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(texts.TOO_FAST, show_alert=False)
            except TelegramBadRequest:
                pass
        elif isinstance(event, Message):
            # Сообщения просто игнорируем: отвечать на флуд — тоже флуд.
            pass

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self.cleanup_after:
            return
        threshold = now - self.cleanup_after
        self._last = {uid: ts for uid, ts in self._last.items() if ts > threshold}
        self._last_cleanup = now
