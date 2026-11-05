"""DexScreener: откуда брать кандидатов и рыночные метрики пулов.

Публичный API, ключ не нужен. Лимиты: ~60 запросов/мин на списки бустов и профилей,
~300 запросов/мин на данные пулов.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable

import httpx
from loguru import logger

from .http import HttpError, get_json
from .models import PairInfo

BASE_URL = "https://api.dexscreener.com"
CHAIN = "solana"

# Списки, из которых собираем кандидатов. Бусты — это платное продвижение на DexScreener,
# поэтому сами по себе они ничего не гарантируют: дальше идут жёсткие фильтры.
CANDIDATE_PATHS = (
    "/token-boosts/top/v1",
    "/token-boosts/latest/v1",
    "/token-profiles/latest/v1",
)


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_pair(data: dict[str, Any]) -> PairInfo | None:
    try:
        base = data["baseToken"]
        volume = data.get("volume") or {}
        change = data.get("priceChange") or {}
        txns_h1 = (data.get("txns") or {}).get("h1") or {}
        pair_address = data.get("pairAddress") or ""
        created = data.get("pairCreatedAt")
        return PairInfo(
            mint=base["address"],
            symbol=base.get("symbol") or "?",
            name=base.get("name") or "",
            pair_address=pair_address,
            dex_id=data.get("dexId") or "",
            url=data.get("url") or f"https://dexscreener.com/{CHAIN}/{pair_address}",
            price_usd=_f(data.get("priceUsd")),
            liquidity_usd=_f((data.get("liquidity") or {}).get("usd")),
            volume_h24=_f(volume.get("h24")),
            volume_h1=_f(volume.get("h1")),
            mcap_usd=_f(data.get("marketCap") or data.get("fdv")),
            created_at_ms=int(created) if created else None,
            buys_h1=int(txns_h1.get("buys") or 0),
            sells_h1=int(txns_h1.get("sells") or 0),
            change_m5=_f(change.get("m5")),
            change_h1=_f(change.get("h1")),
            change_h24=_f(change.get("h24")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def best_pairs(raw_pairs: Iterable[dict[str, Any]], wanted: set[str]) -> dict[str, PairInfo]:
    """Для каждого токена оставляет пул с наибольшей ликвидностью, где токен — базовый."""
    best: dict[str, PairInfo] = {}
    for raw in raw_pairs:
        if not isinstance(raw, dict) or raw.get("chainId") != CHAIN:
            continue
        pair = parse_pair(raw)
        if pair is None or pair.mint not in wanted:
            continue
        current = best.get(pair.mint)
        if current is None or pair.liquidity_usd > current.liquidity_usd:
            best[pair.mint] = pair
    return best


class DexScreener:
    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str = BASE_URL,
        extra_sources: list[Callable[[], Awaitable[list[str]]]] | None = None,
    ):
        self.http = http
        self.base = base_url.rstrip("/")
        self.extra_sources = extra_sources or []

    async def candidate_mints(self) -> list[str]:
        seen: dict[str, None] = {}
        for source in self.extra_sources:
            try:
                for mint in await source():
                    seen.setdefault(mint, None)
            except Exception as exc:  # дополнительный источник не должен ломать поиск
                logger.warning("Источник кандидатов {}: {}", getattr(source, "__qualname__", source), exc)
        for path in CANDIDATE_PATHS:
            try:
                items = await get_json(self.http, self.base + path)
            except HttpError as exc:
                logger.warning("DexScreener {}: {}", path, exc)
                continue
            if isinstance(items, dict):
                items = [items]
            for item in items or []:
                if isinstance(item, dict) and item.get("chainId") == CHAIN and item.get("tokenAddress"):
                    seen.setdefault(item["tokenAddress"], None)
        return list(seen)

    async def pairs_for(self, mints: list[str]) -> dict[str, PairInfo]:
        result: dict[str, PairInfo] = {}
        for i in range(0, len(mints), 30):
            chunk = mints[i : i + 30]
            joined = ",".join(chunk)
            try:
                data = await get_json(self.http, f"{self.base}/tokens/v1/{CHAIN}/{joined}")
            except HttpError as exc:
                if exc.status != 404:
                    raise
                # Старый эндпоинт на случай, если новый переименуют.
                data = await get_json(self.http, f"{self.base}/latest/dex/tokens/{joined}")
            raw_pairs = data.get("pairs") if isinstance(data, dict) else data
            result.update(best_pairs(raw_pairs or [], set(chunk)))
        return result
