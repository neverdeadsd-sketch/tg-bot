"""Jupiter Swap API: котировки и готовые транзакции обмена.

Jupiter — агрегатор: сам ищет лучшую цену по Raydium, Orca, Meteora, PumpSwap и другим DEX.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


class QuoteError(Exception):
    """Котировку получить не удалось (нет маршрута, токен не торгуется, API недоступен)."""


class SwapError(Exception):
    """Jupiter не собрал транзакцию обмена."""


@dataclass
class Quote:
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    raw: dict[str, Any]


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class Jupiter:
    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str = "", retry_delay: float = 1.0):
        self.http = http
        self.base = base_url.rstrip("/")
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.retry_delay = retry_delay

    async def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> Quote:
        if amount <= 0:
            raise QuoteError("нулевая сумма")
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps),
            "swapMode": "ExactIn",
            "restrictIntermediateTokens": "true",
        }
        last = ""
        for attempt in range(3):
            try:
                resp = await self.http.get(f"{self.base}/quote", params=params, headers=self.headers)
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            data = _json(resp)
            if resp.status_code != 200 or "outAmount" not in data:
                reason = data.get("error") or data.get("errorCode") or f"HTTP {resp.status_code}"
                raise QuoteError(str(reason))
            return Quote(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=int(data["inAmount"]),
                out_amount=int(data["outAmount"]),
                raw=data,
            )
        raise QuoteError(f"Jupiter недоступен: {last}")

    async def swap_transaction(
        self,
        quote: Quote,
        user_pubkey: str,
        priority_fee_max_lamports: int,
        priority_level: str,
    ) -> tuple[str, int | None]:
        """Возвращает (транзакция base64, lastValidBlockHeight)."""
        body = {
            "quoteResponse": quote.raw,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": {
                "priorityLevelWithMaxLamports": {
                    "maxLamports": priority_fee_max_lamports,
                    "priorityLevel": priority_level,
                }
            },
        }
        try:
            resp = await self.http.post(f"{self.base}/swap", json=body, headers=self.headers)
        except httpx.HTTPError as exc:
            raise SwapError(f"{type(exc).__name__}: {exc}") from exc
        data = _json(resp)
        tx = data.get("swapTransaction")
        if resp.status_code != 200 or not tx:
            raise SwapError(str(data.get("error") or f"HTTP {resp.status_code}"))
        height = data.get("lastValidBlockHeight")
        return tx, int(height) if height is not None else None
