"""SQLite persistence for the candidate queue, claims and rate-limit counters.

State survives restarts on purpose: the check and claim quotas below are what
keep the bot inside Telegram's limits, so they must not reset when the process
does.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Candidate lifecycle.
STATUS_NEW = "new"                  # scored, never checked
STATUS_AVAILABLE = "available"      # free right now
STATUS_TAKEN = "taken"              # occupied by someone else
STATUS_PURCHASABLE = "purchasable"  # free but only via Fragment auction
STATUS_INVALID = "invalid"          # Telegram rejects the string
STATUS_CLAIMED = "claimed"          # we own it through a channel
STATUS_FAILED = "failed"            # claim attempt failed
STATUS_SKIPPED = "skipped"          # deliberately excluded

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    username     TEXT PRIMARY KEY,
    score        REAL NOT NULL DEFAULT 0,
    tier         TEXT NOT NULL DEFAULT 'F',
    value_band   TEXT NOT NULL DEFAULT '-',
    tags         TEXT NOT NULL DEFAULT '[]',
    source       TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL DEFAULT 'new',
    note         TEXT,
    channel_id   INTEGER,
    created_at   REAL NOT NULL,
    checked_at   REAL,
    claimed_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_status_score ON candidates(status, score DESC);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    kind      TEXT NOT NULL,
    username  TEXT,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS counters (
    name    TEXT NOT NULL,
    bucket  TEXT NOT NULL,
    value   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, bucket)
);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


@dataclass
class Candidate:
    username: str
    score: float
    tier: str
    value_band: str
    tags: list[str]
    source: str
    status: str
    note: str | None = None
    channel_id: int | None = None
    created_at: float = 0.0
    checked_at: float | None = None
    claimed_at: float | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Candidate":
        return cls(
            username=row["username"],
            score=row["score"],
            tier=row["tier"],
            value_band=row["value_band"],
            tags=json.loads(row["tags"] or "[]"),
            source=row["source"],
            status=row["status"],
            note=row["note"],
            channel_id=row["channel_id"],
            created_at=row["created_at"],
            checked_at=row["checked_at"],
            claimed_at=row["claimed_at"],
        )


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # -- candidates ---------------------------------------------------------
    def upsert_many(self, valuations, source: str = "manual") -> int:
        """Insert scored candidates, refreshing the score of existing rows.

        Returns the number of rows that were new.
        """
        now = time.time()
        with self._tx() as conn:
            for v in valuations:
                status = STATUS_NEW if v.valid else STATUS_INVALID
                conn.execute(
                    """INSERT INTO candidates
                         (username, score, tier, value_band, tags, source, status, note, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(username) DO UPDATE SET
                         score=excluded.score, tier=excluded.tier,
                         value_band=excluded.value_band, tags=excluded.tags""",
                    (v.username, v.score, v.tier, v.value_band, json.dumps(v.tags),
                     source, status, v.error, now),
                )
        # rowcount is unreliable for upserts, so count the fresh rows instead.
        return self.count_where("created_at >= ?", (now,))

    def count_where(self, where: str, params=()) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) c FROM candidates WHERE {where}", params).fetchone()
        return row["c"]

    def get(self, username: str) -> Candidate | None:
        row = self.conn.execute("SELECT * FROM candidates WHERE username=?", (username,)).fetchone()
        return Candidate.from_row(row) if row else None

    def queue(self, status: str, limit: int, min_score: float = 0.0,
              exclude_tags: tuple[str, ...] = ()) -> list[Candidate]:
        """Highest-scoring candidates in a given state."""
        rows = self.conn.execute(
            """SELECT * FROM candidates
               WHERE status=? AND score >= ?
               ORDER BY score DESC, length(username) ASC
               LIMIT ?""",
            (status, min_score, limit * 4 if exclude_tags else limit),
        ).fetchall()
        out = []
        for row in rows:
            cand = Candidate.from_row(row)
            if exclude_tags and set(cand.tags) & set(exclude_tags):
                continue
            out.append(cand)
            if len(out) >= limit:
                break
        return out

    def set_status(self, username: str, status: str, *, note: str | None = None,
                   channel_id: int | None = None, checked: bool = False,
                   claimed: bool = False) -> None:
        now = time.time()
        sets = ["status=?"]
        params: list = [status]
        if note is not None:
            sets.append("note=?")
            params.append(note)
        if channel_id is not None:
            sets.append("channel_id=?")
            params.append(channel_id)
        if checked:
            sets.append("checked_at=?")
            params.append(now)
        if claimed:
            sets.append("claimed_at=?")
            params.append(now)
        params.append(username)
        with self._tx() as conn:
            conn.execute(f"UPDATE candidates SET {', '.join(sets)} WHERE username=?", params)

    def stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM candidates GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    def all_by_status(self, status: str | None = None, limit: int = 1000) -> list[Candidate]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM candidates WHERE status=? ORDER BY score DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM candidates ORDER BY score DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Candidate.from_row(r) for r in rows]

    # -- events -------------------------------------------------------------
    def log(self, kind: str, username: str | None = None, detail: str = "") -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO events (ts, kind, username, detail) VALUES (?,?,?,?)",
                (time.time(), kind, username, detail),
            )

    def recent_events(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # -- counters (persistent quotas) ---------------------------------------
    def bump(self, name: str, bucket: str, delta: int = 1) -> int:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO counters (name, bucket, value) VALUES (?,?,?)
                   ON CONFLICT(name, bucket) DO UPDATE SET value = value + excluded.value""",
                (name, bucket, delta),
            )
        return self.counter(name, bucket)

    def counter(self, name: str, bucket: str) -> int:
        row = self.conn.execute(
            "SELECT value FROM counters WHERE name=? AND bucket=?", (name, bucket)
        ).fetchone()
        return row["value"] if row else 0

    # -- meta ---------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
