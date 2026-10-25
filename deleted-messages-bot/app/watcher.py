from __future__ import annotations

import asyncio
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app import reporter
from app.limiter import RateLimiter
from app.probe import Liveness, probe_message
from app.schedule import next_probe_at
from app.storage import db, from_iso, utc_now
from app.utils.logger import logger
from config import KEEP_DAYS, PROBE_BATCH, PROBE_RATE

# Нечего проверять — столько ждать до следующего взгляда в очередь.
IDLE_SLEEP = 10

# Как часто подчищать старые записи.
PURGE_EVERY = 3600

_task: asyncio.Task | None = None


async def start(bot: Bot) -> None:
    global _task

    if _task is not None and not _task.done():
        return

    _task = asyncio.create_task(_run(bot), name="deleted-watcher")
    logger.info(
        f"🔍 Сторож удалений запущен: до {PROBE_RATE} проверок/с, "
        f"пачками по {PROBE_BATCH}"
    )


async def stop() -> None:
    global _task

    if _task is None:
        return

    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    finally:
        _task = None


async def _run(bot: Bot) -> None:
    limiter = RateLimiter(PROBE_RATE)
    last_purge = time.monotonic()

    while True:
        try:
            checked = await _probe_due(bot, limiter)
            await _flush_reports(bot)
            await db.expire_watches()

            if KEEP_DAYS > 0 and time.monotonic() - last_purge >= PURGE_EVERY:
                removed = await db.purge_older_than(KEEP_DAYS)
                last_purge = time.monotonic()
                if removed:
                    logger.info(f"🧹 Удалено старых записей: {removed}")

            if checked == 0:
                await asyncio.sleep(IDLE_SLEEP)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Сторож удалений споткнулся, продолжаю")
            await asyncio.sleep(IDLE_SLEEP)


async def _probe_due(bot: Bot, limiter: RateLimiter) -> int:
    """Обойти очередь проверок. Возвращает, сколько сообщений посмотрели."""

    rows = await db.due_probes(PROBE_BATCH)
    if not rows:
        return 0

    seen = 0
    lost_chats: set[int] = set()

    for row in rows:
        if row["chat_id"] in lost_chats:
            # Чат уже признан недоступным в этой же пачке: его сообщения сняты
            # с проверки, и спрашивать о них Telegram незачем. Без этого
            # ответ по следующему сообщению вернул бы чат в очередь.
            continue

        await limiter.acquire()

        try:
            verdict = await probe_message(bot, row["chat_id"], row["message_id"])
        except TelegramRetryAfter as error:
            wait = float(getattr(error, "retry_after", 5) or 5)
            limiter.pause(wait + 1)
            logger.warning(
                f"Telegram просит подождать {wait:.0f} с — остальные проверки позже"
            )
            break

        seen += 1

        if verdict is Liveness.DELETED:
            fresh = await db.mark_deleted(
                row["source"], row["chat_id"], row["message_id"]
            )
            if fresh:
                logger.info(
                    f"🗑 Удалено сообщение {row['message_id']} в чате {row['chat_id']}"
                )
            continue

        if verdict is Liveness.CHAT_LOST:
            lost_chats.add(row["chat_id"])
            stopped = await db.stop_probing_chat(row["chat_id"])
            logger.warning(
                f"Чат {row['chat_id']} недоступен — снято с проверки сообщений: "
                f"{stopped}"
            )
            continue

        sent_at = from_iso(row["sent_at"]) or utc_now()
        await db.schedule_probe(
            row["source"], row["chat_id"], row["message_id"], next_probe_at(sent_at)
        )

    return seen


async def _flush_reports(bot: Bot) -> None:
    """Разослать отчёты. Отдельный шаг: падение между «заметил» и «сообщил»
    иначе стоило бы сообщения насовсем."""

    for row in await db.pending_reports(limit=10):
        try:
            delivered = await reporter.deliver(
                bot, row, await db.edits_for(row["source"], row["chat_id"], row["message_id"])
            )
        except TelegramRetryAfter as error:
            wait = float(getattr(error, "retry_after", 5) or 5)
            logger.warning(f"Отчёты притормозим на {wait:.0f} с")
            await asyncio.sleep(min(wait + 1, 60))
            return
        except (TelegramAPIError, OSError) as error:
            # Запись остаётся неотправленной и попадёт в следующий круг.
            logger.error(f"Отчёт об удалении не доставлен: {error}")
            continue

        if delivered:
            await db.mark_reported(row["source"], row["chat_id"], row["message_id"])
