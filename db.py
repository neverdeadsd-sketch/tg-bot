"""Слой доступа к SQLite через aiosqlite.

Хранит заявки и вопросы. Путь к БД задаётся один раз через `setup()`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

logger = logging.getLogger(__name__)

_db_path: Path | None = None

DAY = 86_400
WEEK = 7 * DAY

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    username    TEXT,
    full_name   TEXT,
    bot_type    TEXT NOT NULL,
    sphere      TEXT NOT NULL,
    features    TEXT,
    budget      TEXT NOT NULL,
    deadline    TEXT NOT NULL,
    description TEXT,
    contact     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TEXT NOT NULL,
    created_ts  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user_ts ON orders(user_id, created_ts);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(created_ts DESC);

CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    full_name  TEXT,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_ts INTEGER NOT NULL
);
"""

ORDER_COLUMNS = (
    "id", "user_id", "username", "full_name", "bot_type", "sphere", "features",
    "budget", "deadline", "description", "contact", "status", "created_at",
)


def setup(path: Path) -> None:
    global _db_path
    _db_path = path


def _path() -> Path:
    if _db_path is None:
        raise RuntimeError("db.setup(path) не вызван до работы с базой")
    return _db_path


async def init_db() -> None:
    async with aiosqlite.connect(_path()) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.executescript(SCHEMA)
        await conn.commit()
    logger.info("База готова: %s", _path())


def _now() -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="seconds"), int(now.timestamp())


def to_local(created_at: str) -> str:
    """ISO-время в UTC -> строка в локальной зоне процесса (TZ из окружения)."""
    try:
        dt = datetime.fromisoformat(created_at)
    except ValueError:
        return created_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


async def create_order(
    *,
    user_id: int,
    username: str | None,
    full_name: str,
    bot_type: str,
    sphere: str,
    features: str,
    budget: str,
    deadline: str,
    description: str | None,
    contact: str,
) -> tuple[int, str]:
    """Создаёт заявку, возвращает (id, created_at в UTC ISO)."""
    created_at, created_ts = _now()
    async with aiosqlite.connect(_path()) as conn:
        cursor = await conn.execute(
            """
            INSERT INTO orders (user_id, username, full_name, bot_type, sphere,
                                features, budget, deadline, description, contact,
                                status, created_at, created_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (user_id, username, full_name, bot_type, sphere, features, budget,
             deadline, description, contact, created_at, created_ts),
        )
        await conn.commit()
        return int(cursor.lastrowid), created_at


async def count_orders_last_day(user_id: int) -> int:
    """Сколько заявок пользователь оставил за последние 24 часа."""
    since = int(time.time()) - DAY
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND created_ts >= ?",
            (user_id, since),
        ) as cursor:
            row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def get_stats() -> dict[str, Any]:
    now = int(time.time())
    async with aiosqlite.connect(_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM orders WHERE created_ts >= ?) AS day,
                (SELECT COUNT(*) FROM orders WHERE created_ts >= ?) AS week,
                (SELECT COUNT(*) FROM orders)                       AS total
            """,
            (now - DAY, now - WEEK),
        ) as cursor:
            row = await cursor.fetchone()
        async with conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status"
        ) as cursor:
            by_status = {r["status"]: r["cnt"] for r in await cursor.fetchall()}
    return {
        "day": row["day"] if row else 0,
        "week": row["week"] if row else 0,
        "total": row["total"] if row else 0,
        "by_status": by_status,
    }


async def count_orders() -> int:
    async with aiosqlite.connect(_path()) as conn:
        async with conn.execute("SELECT COUNT(*) FROM orders") as cursor:
            row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def list_orders(limit: int, offset: int) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            f"SELECT {', '.join(ORDER_COLUMNS)} FROM orders "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


async def get_order(order_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            f"SELECT {', '.join(ORDER_COLUMNS)} FROM orders WHERE id = ?",
            (order_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def set_status(order_id: int, status: str) -> dict[str, Any] | None:
    """Меняет статус только у заявки в статусе 'new'; иначе None."""
    async with aiosqlite.connect(_path()) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "UPDATE orders SET status = ? WHERE id = ? AND status = 'new'",
            (status, order_id),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            return None
        async with conn.execute(
            f"SELECT {', '.join(ORDER_COLUMNS)} FROM orders WHERE id = ?",
            (order_id,),
        ) as inner:
            row = await inner.fetchone()
    return _row_to_dict(row) if row else None


async def all_orders() -> list[dict[str, Any]]:
    async with aiosqlite.connect(_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            f"SELECT {', '.join(ORDER_COLUMNS)} FROM orders ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


async def create_question(
    *, user_id: int, username: str | None, full_name: str, text: str
) -> int:
    created_at, created_ts = _now()
    async with aiosqlite.connect(_path()) as conn:
        cursor = await conn.execute(
            "INSERT INTO questions (user_id, username, full_name, text, created_at, created_ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, text, created_at, created_ts),
        )
        await conn.commit()
    return int(cursor.lastrowid)


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    data["created_at_local"] = to_local(data["created_at"])
    return data


def rows_to_csv(rows: Iterable[dict[str, Any]]) -> bytes:
    """CSV с BOM и разделителем «;» — чтобы Excel открывал без плясок."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([
        "id", "created_at_utc", "created_at_local", "user_id", "username",
        "full_name", "bot_type", "sphere", "features", "budget", "deadline",
        "description", "contact", "status",
    ])
    for row in rows:
        writer.writerow([
            row["id"], row["created_at"], row["created_at_local"], row["user_id"],
            row["username"] or "", row["full_name"] or "", row["bot_type"],
            row["sphere"], row["features"] or "", row["budget"], row["deadline"],
            (row["description"] or "").replace("\n", " "), row["contact"], row["status"],
        ])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
