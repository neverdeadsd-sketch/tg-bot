"""SQLite: позиции, сделки, кулдауны токенов и флаги состояния.

Количество токенов хранится текстом: у некоторых мемкоинов оно не влезает в 64-битное число.
Бумажные и боевые позиции хранятся раздельно (колонка mode) и не смешиваются в статистике.
"""
from __future__ import annotations

from typing import Any

import aiosqlite

from .models import PairInfo, Position

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    mint TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    opened_at INTEGER NOT NULL,
    closed_at INTEGER,
    entry_lamports INTEGER NOT NULL,
    token_amount TEXT NOT NULL,
    token_remaining TEXT NOT NULL,
    decimals INTEGER,
    realized_lamports INTEGER NOT NULL DEFAULT 0,
    last_value_lamports INTEGER NOT NULL DEFAULT 0,
    peak_total_lamports INTEGER NOT NULL DEFAULT 0,
    tp_done INTEGER NOT NULL DEFAULT 0,
    quote_failures INTEGER NOT NULL DEFAULT 0,
    close_reason TEXT,
    pnl_lamports INTEGER
);
CREATE INDEX IF NOT EXISTS idx_positions_mode_status ON positions(mode, status);
CREATE INDEX IF NOT EXISTS idx_positions_mint ON positions(mint);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    mode TEXT NOT NULL,
    side TEXT NOT NULL,
    ts INTEGER NOT NULL,
    lamports INTEGER NOT NULL,
    token_amount TEXT NOT NULL,
    signature TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS cooldowns (
    mint TEXT PRIMARY KEY,
    until INTEGER NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _position(row: aiosqlite.Row) -> Position:
    return Position(
        id=row["id"],
        mode=row["mode"],
        mint=row["mint"],
        symbol=row["symbol"],
        name=row["name"],
        url=row["url"],
        status=row["status"],
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
        entry_lamports=row["entry_lamports"],
        token_amount=int(row["token_amount"]),
        token_remaining=int(row["token_remaining"]),
        decimals=row["decimals"],
        realized_lamports=row["realized_lamports"],
        last_value_lamports=row["last_value_lamports"],
        peak_total_lamports=row["peak_total_lamports"],
        tp_done=bool(row["tp_done"]),
        quote_failures=row["quote_failures"],
        close_reason=row["close_reason"],
        pnl_lamports=row["pnl_lamports"],
    )


class Storage:
    def __init__(self, path: str, mode: str):
        self.path = path
        self.mode = mode
        self.db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        await self.db.commit()

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    @property
    def _db(self) -> aiosqlite.Connection:
        if self.db is None:
            raise RuntimeError("Storage.open() не вызван")
        return self.db

    # ---- kv ----
    def _key(self, key: str) -> str:
        return f"{self.mode}:{key}"

    async def get_kv(self, key: str) -> str | None:
        async with self._db.execute("SELECT value FROM kv WHERE key = ?", (self._key(key),)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_kv(self, key: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (self._key(key), value),
        )
        await self._db.commit()

    async def del_kv(self, key: str) -> None:
        await self._db.execute("DELETE FROM kv WHERE key = ?", (self._key(key),))
        await self._db.commit()

    # ---- позиции ----
    async def create_position(
        self, pair: PairInfo, entry_lamports: int, token_amount: int, decimals: int | None, now: int
    ) -> Position:
        cur = await self._db.execute(
            """INSERT INTO positions(mode, mint, symbol, name, url, opened_at, entry_lamports,
                   token_amount, token_remaining, decimals, last_value_lamports, peak_total_lamports)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.mode, pair.mint, pair.symbol, pair.name, pair.url, now, entry_lamports,
                str(token_amount), str(token_amount), decimals, entry_lamports, entry_lamports,
            ),
        )
        await self._db.commit()
        position = await self.get_position(cur.lastrowid)
        assert position is not None
        return position

    async def update_position(self, p: Position) -> None:
        await self._db.execute(
            """UPDATE positions SET status = ?, closed_at = ?, token_remaining = ?, decimals = ?,
                   realized_lamports = ?, last_value_lamports = ?, peak_total_lamports = ?, tp_done = ?,
                   quote_failures = ?, close_reason = ?, pnl_lamports = ?
               WHERE id = ?""",
            (
                p.status, p.closed_at, str(p.token_remaining), p.decimals, p.realized_lamports,
                p.last_value_lamports, p.peak_total_lamports, int(p.tp_done), p.quote_failures,
                p.close_reason, p.pnl_lamports, p.id,
            ),
        )
        await self._db.commit()

    async def get_position(self, position_id: int) -> Position | None:
        async with self._db.execute(
            "SELECT * FROM positions WHERE id = ? AND mode = ?", (position_id, self.mode)
        ) as cur:
            row = await cur.fetchone()
        return _position(row) if row else None

    async def open_positions(self) -> list[Position]:
        async with self._db.execute(
            "SELECT * FROM positions WHERE mode = ? AND status = 'open' ORDER BY id", (self.mode,)
        ) as cur:
            rows = await cur.fetchall()
        return [_position(r) for r in rows]

    async def closed_positions(self, limit: int = 10) -> list[Position]:
        async with self._db.execute(
            "SELECT * FROM positions WHERE mode = ? AND status = 'closed' ORDER BY closed_at DESC, id DESC LIMIT ?",
            (self.mode, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_position(r) for r in rows]

    async def last_opened_at(self, mint: str) -> int | None:
        async with self._db.execute(
            "SELECT MAX(opened_at) AS ts FROM positions WHERE mode = ? AND mint = ?", (self.mode, mint)
        ) as cur:
            row = await cur.fetchone()
        return row["ts"] if row and row["ts"] is not None else None

    async def realized_pnl_since(self, ts: int) -> int:
        async with self._db.execute(
            "SELECT COALESCE(SUM(pnl_lamports), 0) AS pnl FROM positions WHERE mode = ? AND status = 'closed' AND closed_at >= ?",
            (self.mode, ts),
        ) as cur:
            row = await cur.fetchone()
        return int(row["pnl"])

    async def stats(self) -> dict[str, Any]:
        async with self._db.execute(
            """SELECT COUNT(*) AS n, COALESCE(SUM(pnl_lamports), 0) AS pnl,
                      COALESCE(SUM(CASE WHEN pnl_lamports > 0 THEN 1 ELSE 0 END), 0) AS wins,
                      COALESCE(SUM(entry_lamports), 0) AS invested
               FROM positions WHERE mode = ? AND status = 'closed'""",
            (self.mode,),
        ) as cur:
            row = await cur.fetchone()
        return {"closed": row["n"], "pnl": int(row["pnl"]), "wins": row["wins"], "invested": int(row["invested"])}

    # ---- сделки ----
    async def add_trade(
        self, position_id: int, side: str, ts: int, lamports: int, token_amount: int, signature: str | None, reason: str
    ) -> None:
        await self._db.execute(
            "INSERT INTO trades(position_id, mode, side, ts, lamports, token_amount, signature, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (position_id, self.mode, side, ts, lamports, str(token_amount), signature, reason),
        )
        await self._db.commit()

    # ---- кулдауны ----
    async def set_cooldown(self, mint: str, until: int, reason: str) -> None:
        await self._db.execute(
            "INSERT INTO cooldowns(mint, until, reason) VALUES (?, ?, ?) "
            "ON CONFLICT(mint) DO UPDATE SET until = excluded.until, reason = excluded.reason",
            (mint, until, reason),
        )
        await self._db.commit()

    async def in_cooldown(self, mint: str, now: int) -> bool:
        async with self._db.execute("SELECT until FROM cooldowns WHERE mint = ?", (mint,)) as cur:
            row = await cur.fetchone()
        return bool(row and row["until"] > now)

    async def purge_cooldowns(self, now: int) -> None:
        await self._db.execute("DELETE FROM cooldowns WHERE until <= ?", (now,))
        await self._db.commit()
