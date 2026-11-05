"""Данные, которыми обмениваются модули."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PairInfo:
    """Самый ликвидный пул токена по данным DexScreener."""

    mint: str
    symbol: str
    name: str
    pair_address: str
    dex_id: str
    url: str
    price_usd: float
    liquidity_usd: float
    volume_h24: float
    volume_h1: float
    mcap_usd: float
    created_at_ms: int | None
    buys_h1: int
    sells_h1: int
    change_m5: float
    change_h1: float
    change_h24: float

    def age_hours(self, now_ms: int) -> float | None:
        if not self.created_at_ms:
            return None
        return (now_ms - self.created_at_ms) / 3_600_000


@dataclass
class Risk:
    name: str
    level: str
    description: str = ""


@dataclass
class RugReport:
    score: float | None
    mint_authority_known: bool
    mint_authority: str | None
    freeze_authority_known: bool
    freeze_authority: str | None
    lp_locked_pct: float | None
    risks: list[Risk] = field(default_factory=list)
    token_program: str | None = None
    rugged: bool = False
    transfer_fee_pct: float = 0.0


@dataclass
class Position:
    id: int
    mode: str
    mint: str
    symbol: str
    name: str
    url: str
    status: str
    opened_at: int
    closed_at: int | None
    entry_lamports: int
    token_amount: int
    token_remaining: int
    decimals: int | None
    realized_lamports: int = 0
    last_value_lamports: int = 0
    peak_total_lamports: int = 0
    tp_done: bool = False
    quote_failures: int = 0
    close_reason: str | None = None
    pnl_lamports: int | None = None

    @property
    def total_value(self) -> int:
        """Сколько SOL уже получено с продаж + сколько дали бы за остаток сейчас."""
        return self.realized_lamports + self.last_value_lamports

    @property
    def multiple(self) -> float:
        return self.total_value / self.entry_lamports if self.entry_lamports else 0.0
