"""GeckoTerminal: трендовые пулы Solana как дополнительный источник кандидатов.

DexScreener в основном отдаёт токены, которые платят за продвижение, — это чаще всего мелочь.
Трендовые пулы GeckoTerminal дают токены покрупнее. Метрики всё равно берутся из DexScreener,
отсюда нужны только адреса. Публичный API, ключ не нужен, лимит ~30 запросов в минуту.
"""
from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from .config import SOL_MINT
from .http import HttpError, get_json

BASE_URL = "https://api.geckoterminal.com/api/v2"
PREFIX = "solana_"
PAGES = 2

# SOL и стейблкоины кандидатами не бывают.
SKIP = {
    SOL_MINT,
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}


def parse_trending(payload: Any) -> list[str]:
    mints: dict[str, None] = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    for pool in data or []:
        try:
            token_id = pool["relationships"]["base_token"]["data"]["id"]
        except (KeyError, TypeError):
            continue
        if isinstance(token_id, str) and token_id.startswith(PREFIX):
            mint = token_id[len(PREFIX) :]
            if mint and mint not in SKIP:
                mints.setdefault(mint, None)
    return list(mints)


class GeckoTerminal:
    def __init__(self, http: httpx.AsyncClient, base_url: str = BASE_URL):
        self.http = http
        self.base = base_url.rstrip("/")

    async def trending_mints(self) -> list[str]:
        result: dict[str, None] = {}
        for page in range(1, PAGES + 1):
            try:
                payload = await get_json(
                    self.http,
                    f"{self.base}/networks/solana/trending_pools",
                    params={"page": page},
                    retries=2,
                )
            except HttpError as exc:
                logger.warning("GeckoTerminal trending, страница {}: {}", page, exc)
                break
            for mint in parse_trending(payload):
                result.setdefault(mint, None)
        return list(result)
