from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from config import DATABASE_PATH, MEDIA_DIR

# Нумерация сообщений своя у каждого аккаунта: id из Bot API и id того же
# сообщения у userbot не совпадают. Поэтому источник входит в ключ.
SOURCE_BOT = "bot"
SOURCE_USER = "user"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    # Строка всегда одной длины — тогда сравнение дат в SQL работает как
    # обычное сравнение текста и индекс по next_probe_at остаётся рабочим.
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def fold(text: str | None) -> str | None:
    """Привести текст к виду, в котором регистр не мешает поиску.

    casefold из Python знает про кириллицу, а одноимённая функция SQLite —
    только про латиницу.
    """

    return text.casefold() if text else None


def from_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(slots=True)
class MessageRecord:
    """Сообщение в том виде, в каком его увидел бот."""

    chat_id: int
    message_id: int
    source: str = SOURCE_BOT
    chat_title: str | None = None
    chat_type: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    user_username: str | None = None
    content_type: str | None = None
    text: str | None = None
    media_file_id: str | None = None
    media_unique_id: str | None = None
    media_path: str | None = None
    media_name: str | None = None
    media_type: str | None = None
    reply_to: int | None = None
    forward_from: str | None = None
    has_markup: bool = False
    sent_at: datetime | None = None


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or DATABASE_PATH

    def connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    async def create_tables(self) -> None:
        parent = Path(self.path).expanduser().parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

        async with self.connect() as db:
            # Архиватор и сторож пишут одновременно; без WAL второй получал бы
            # "database is locked" на каждой пачке проверок.
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages(
                    source          TEXT    NOT NULL DEFAULT 'bot',
                    chat_id         INTEGER NOT NULL,
                    message_id      INTEGER NOT NULL,
                    chat_title      TEXT,
                    chat_type       TEXT,
                    user_id         INTEGER,
                    user_name       TEXT,
                    user_username   TEXT,
                    content_type    TEXT,
                    text            TEXT,
                    text_lower      TEXT,
                    media_file_id   TEXT,
                    media_unique_id TEXT,
                    media_path      TEXT,
                    media_name      TEXT,
                    media_type      TEXT,
                    reply_to        INTEGER,
                    forward_from    TEXT,
                    has_markup      INTEGER NOT NULL DEFAULT 0,
                    sent_at         TEXT    NOT NULL,
                    saved_at        TEXT    NOT NULL,
                    edited_at       TEXT,
                    deleted_at      TEXT,
                    reported_at     TEXT,
                    next_probe_at   TEXT,
                    watch_until     TEXT,
                    probe_count     INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (source, chat_id, message_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS edits(
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    source     TEXT    NOT NULL DEFAULT 'bot',
                    chat_id    INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    text       TEXT,
                    edited_at  TEXT    NOT NULL
                )
                """
            )
            # Очередь проверок выбирается по next_probe_at и только среди живых
            # сообщений — частичный индекс не хранит остальные.
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_probe
                ON messages(next_probe_at) WHERE deleted_at IS NULL
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_deleted ON messages(deleted_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, sent_at)"
            )
            # userbot получает удаление в личке без указания чата — остаётся
            # искать сообщение по одному id.
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_msgid ON messages(message_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_edits_message ON edits(source, chat_id, message_id)"
            )
            await db.commit()

    # --- запись ---

    async def save_message(
        self,
        record: MessageRecord,
        watch_hours: int,
        first_probe_at: datetime | None,
    ) -> bool:
        """Сохранить сообщение. False — такое уже лежит в базе."""

        now = utc_now()
        sent_at = record.sent_at or now
        watch_until = sent_at + timedelta(hours=watch_hours)

        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                """
                INSERT INTO messages(
                    source, chat_id, message_id, chat_title, chat_type,
                    user_id, user_name, user_username, content_type, text,
                    text_lower, media_file_id, media_unique_id, media_path,
                    media_name, media_type, reply_to, forward_from, has_markup,
                    sent_at, saved_at, next_probe_at, watch_until
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source, chat_id, message_id) DO NOTHING
                """,
                (
                    record.source,
                    record.chat_id,
                    record.message_id,
                    record.chat_title,
                    record.chat_type,
                    record.user_id,
                    record.user_name,
                    record.user_username,
                    record.content_type,
                    record.text,
                    fold(record.text),
                    record.media_file_id,
                    record.media_unique_id,
                    record.media_path,
                    record.media_name,
                    record.media_type,
                    record.reply_to,
                    record.forward_from,
                    int(record.has_markup),
                    to_iso(sent_at),
                    to_iso(now),
                    to_iso(first_probe_at) if first_probe_at else None,
                    to_iso(watch_until),
                ),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def attach_media_path(
        self, source: str, chat_id: int, message_id: int, path: str
    ) -> None:
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                UPDATE messages SET media_path = ?
                WHERE source = ? AND chat_id = ? AND message_id = ?
                """,
                (path, source, chat_id, message_id),
            )
            await db.commit()

    async def record_edit(
        self,
        source: str,
        chat_id: int,
        message_id: int,
        text: str | None,
        edited_at: datetime | None = None,
    ) -> None:
        """Сохранить новую версию текста, не затирая первую."""

        moment = to_iso(edited_at or utc_now())
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            # Одна и та же правка приходит повторно при перезапуске бота —
            # дважды её писать не нужно.
            cursor = await db.execute(
                """
                SELECT 1 FROM edits
                WHERE source = ? AND chat_id = ? AND message_id = ?
                  AND edited_at = ? AND IFNULL(text, '') = IFNULL(?, '')
                """,
                (source, chat_id, message_id, moment, text),
            )
            if await cursor.fetchone():
                return
            await db.execute(
                """
                INSERT INTO edits(source, chat_id, message_id, text, edited_at)
                VALUES (?,?,?,?,?)
                """,
                (source, chat_id, message_id, text, moment),
            )
            await db.execute(
                """
                UPDATE messages SET edited_at = ?
                WHERE source = ? AND chat_id = ? AND message_id = ?
                """,
                (moment, source, chat_id, message_id),
            )
            await db.commit()

    # --- очередь проверок ---

    async def due_probes(
        self, limit: int, now: datetime | None = None
    ) -> list[aiosqlite.Row]:
        moment = to_iso(now or utc_now())
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM messages
                WHERE deleted_at IS NULL
                  AND next_probe_at IS NOT NULL
                  AND next_probe_at <= ?
                  AND watch_until > ?
                  AND has_markup = 0
                ORDER BY next_probe_at
                LIMIT ?
                """,
                (moment, moment, limit),
            )
            return list(await cursor.fetchall())

    async def schedule_probe(
        self, source: str, chat_id: int, message_id: int, next_at: datetime
    ) -> None:
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                UPDATE messages
                SET next_probe_at = ?, probe_count = probe_count + 1
                WHERE source = ? AND chat_id = ? AND message_id = ?
                """,
                (to_iso(next_at), source, chat_id, message_id),
            )
            await db.commit()

    async def stop_probing(self, source: str, chat_id: int, message_id: int) -> None:
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                UPDATE messages SET next_probe_at = NULL
                WHERE source = ? AND chat_id = ? AND message_id = ?
                """,
                (source, chat_id, message_id),
            )
            await db.commit()

    async def stop_probing_chat(self, chat_id: int) -> int:
        """Бота выгнали из чата — проверять там больше нечего."""

        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                """
                UPDATE messages SET next_probe_at = NULL
                WHERE chat_id = ? AND deleted_at IS NULL AND next_probe_at IS NOT NULL
                """,
                (chat_id,),
            )
            await db.commit()
            return cursor.rowcount

    async def expire_watches(self, now: datetime | None = None) -> int:
        moment = to_iso(now or utc_now())
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                """
                UPDATE messages SET next_probe_at = NULL
                WHERE deleted_at IS NULL
                  AND next_probe_at IS NOT NULL
                  AND watch_until <= ?
                """,
                (moment,),
            )
            await db.commit()
            return cursor.rowcount

    # --- удаления ---

    async def mark_deleted(
        self,
        source: str,
        chat_id: int,
        message_id: int,
        deleted_at: datetime | None = None,
    ) -> bool:
        """True — удаление замечено впервые, об этом ещё никто не знает."""

        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            cursor = await db.execute(
                """
                UPDATE messages
                SET deleted_at = ?, next_probe_at = NULL
                WHERE source = ? AND chat_id = ? AND message_id = ?
                  AND deleted_at IS NULL
                """,
                (to_iso(deleted_at or utc_now()), source, chat_id, message_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def pending_reports(self, limit: int = 20) -> list[aiosqlite.Row]:
        """Удалённое, о чём ещё не отчитались: падение между двумя шагами
        не должно стоить сообщения."""

        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM messages
                WHERE deleted_at IS NOT NULL AND reported_at IS NULL
                ORDER BY deleted_at
                LIMIT ?
                """,
                (limit,),
            )
            return list(await cursor.fetchall())

    async def mark_reported(self, source: str, chat_id: int, message_id: int) -> None:
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                UPDATE messages SET reported_at = ?
                WHERE source = ? AND chat_id = ? AND message_id = ?
                """,
                (to_iso(utc_now()), source, chat_id, message_id),
            )
            await db.commit()

    # --- чтение ---

    async def get_message(
        self, source: str, chat_id: int, message_id: int
    ) -> aiosqlite.Row | None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM messages
                WHERE source = ? AND chat_id = ? AND message_id = ?
                """,
                (source, chat_id, message_id),
            )
            return await cursor.fetchone()

    async def find_without_chat(
        self, source: str, message_id: int
    ) -> aiosqlite.Row | None:
        """Удаление в личке приходит без указания чата. В личных чатах и старых
        группах id уникален в пределах аккаунта, поэтому поиск по одному id
        однозначен — каналы и супергруппы нумеруются отдельно и исключены."""

        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM messages
                WHERE source = ? AND message_id = ? AND deleted_at IS NULL
                  AND IFNULL(chat_type, '') NOT IN ('channel', 'supergroup')
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                (source, message_id),
            )
            return await cursor.fetchone()

    async def edits_for(
        self, source: str, chat_id: int, message_id: int
    ) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT text, edited_at FROM edits
                WHERE source = ? AND chat_id = ? AND message_id = ?
                ORDER BY id
                """,
                (source, chat_id, message_id),
            )
            return list(await cursor.fetchall())

    async def recent_deleted(
        self, limit: int = 10, chat_id: int | None = None
    ) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            if chat_id is None:
                cursor = await db.execute(
                    """
                    SELECT * FROM messages WHERE deleted_at IS NOT NULL
                    ORDER BY deleted_at DESC LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT * FROM messages
                    WHERE deleted_at IS NOT NULL AND chat_id = ?
                    ORDER BY deleted_at DESC LIMIT ?
                    """,
                    (chat_id, limit),
                )
            return list(await cursor.fetchall())

    async def search_deleted(
        self, query: str, limit: int = 10
    ) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            # Сравнение идёт по заранее приведённой копии текста: lower()
            # внутри SQLite работает только с латиницей и «Договор» по запросу
            # «договор» не находил. instr вместо LIKE — чтобы проценты и
            # подчёркивания в запросе искались как обычные символы.
            cursor = await db.execute(
                """
                SELECT * FROM messages
                WHERE deleted_at IS NOT NULL
                  AND instr(IFNULL(text_lower, ''), ?) > 0
                ORDER BY deleted_at DESC LIMIT ?
                """,
                (fold(query) or "", limit),
            )
            return list(await cursor.fetchall())

    async def stats(self) -> dict[str, int]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*),
                    SUM(deleted_at IS NOT NULL),
                    SUM(deleted_at IS NULL AND next_probe_at IS NOT NULL),
                    SUM(edited_at IS NOT NULL),
                    COUNT(DISTINCT chat_id)
                FROM messages
                """
            )
            row = await cursor.fetchone()
            cursor = await db.execute("SELECT COUNT(*) FROM edits")
            edits_row = await cursor.fetchone()

        return {
            "saved": row[0] or 0,
            "deleted": row[1] or 0,
            "watched": row[2] or 0,
            "edited": row[3] or 0,
            "chats": row[4] or 0,
            "edits": edits_row[0] or 0,
        }

    async def purge_older_than(self, days: int) -> int:
        """Удалить старые записи вместе с их правками. 0 — ничего не чистить."""

        if days <= 0:
            return 0

        cutoff = to_iso(utc_now() - timedelta(days=days))
        async with self.connect() as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                DELETE FROM edits WHERE (source, chat_id, message_id) IN (
                    SELECT source, chat_id, message_id FROM messages WHERE sent_at < ?
                )
                """,
                (cutoff,),
            )
            cursor = await db.execute(
                "DELETE FROM messages WHERE sent_at < ?", (cutoff,)
            )
            await db.commit()
            return cursor.rowcount


db = Database()
