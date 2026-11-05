from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memebot.config import LAMPORTS_PER_SOL, SOL_MINT, Settings  # noqa: E402
from memebot.jupiter import Quote, QuoteError  # noqa: E402
from memebot.models import PairInfo, RugReport  # noqa: E402
from memebot.storage import Storage  # noqa: E402

NOW = 1_800_000_000  # фиксированное «сейчас» для тестов, секунды


def make_settings(**overrides) -> Settings:
    env = {"TELEGRAM_BOT_TOKEN": "x", "ADMIN_CHAT_ID": "1", "PAPER_EXTRA_SLIPPAGE_PCT": "0", "PAPER_FEE_LAMPORTS": "0"}
    env.update({k: str(v) for k, v in overrides.items()})
    return Settings.from_env(env)


def good_pair(mint: str = "MINTgood", **overrides) -> PairInfo:
    data = dict(
        mint=mint,
        symbol=mint[-4:].upper(),
        name=f"Token {mint}",
        pair_address=f"PAIR{mint}",
        dex_id="raydium",
        url=f"https://dexscreener.com/solana/PAIR{mint}",
        price_usd=0.01,
        liquidity_usd=120_000,
        volume_h24=900_000,
        volume_h1=80_000,
        mcap_usd=2_000_000,
        created_at_ms=(NOW - 48 * 3600) * 1000,
        buys_h1=400,
        sells_h1=250,
        change_m5=1.0,
        change_h1=12.0,
        change_h24=40.0,
    )
    data.update(overrides)
    return PairInfo(**data)


def clean_report(**overrides) -> RugReport:
    data = dict(
        score=5.0,
        mint_authority_known=True,
        mint_authority=None,
        freeze_authority_known=True,
        freeze_authority=None,
        lp_locked_pct=100.0,
        risks=[],
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        rugged=False,
        transfer_fee_pct=0.0,
    )
    data.update(overrides)
    return RugReport(**data)


class FakeJupiter:
    """Цена задаётся как «токенов за 1 SOL». Продажа теряет spread_pct."""

    def __init__(self):
        self.tokens_per_sol: dict[str, float] = {}
        self.spread_pct: dict[str, float] = {}
        self.fail: set[str] = set()
        self.calls: list[tuple[str, str, int]] = []

    async def quote(self, input_mint, output_mint, amount, slippage_bps):
        self.calls.append((input_mint, output_mint, amount))
        mint = output_mint if input_mint == SOL_MINT else input_mint
        if mint in self.fail:
            raise QuoteError("COULD_NOT_FIND_ANY_ROUTE")
        rate = self.tokens_per_sol[mint]
        if input_mint == SOL_MINT:
            out = int(amount / LAMPORTS_PER_SOL * rate)
        else:
            out = int(amount / rate * LAMPORTS_PER_SOL * (1 - self.spread_pct.get(mint, 0.0) / 100))
        return Quote(input_mint, output_mint, amount, out, {"inAmount": str(amount), "outAmount": str(out)})


class FakeDex:
    def __init__(self, pairs: list[PairInfo]):
        self.pairs = {p.mint: p for p in pairs}

    async def candidate_mints(self):
        return list(self.pairs)

    async def pairs_for(self, mints):
        return {m: self.pairs[m] for m in mints if m in self.pairs}


class FakeRug:
    def __init__(self, reports: dict[str, RugReport] | None = None):
        self.reports = reports or {}

    async def report(self, mint):
        if mint not in self.reports:
            raise RuntimeError("timeout")
        return self.reports[mint]


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def store(tmp_path):
    st = Storage(str(tmp_path / "test.db"), "paper")
    await st.open()
    yield st
    await st.close()
