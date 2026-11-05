"""Общий HTTP-запрос с повторами при 429/5xx и сетевых сбоях."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=10.0),
        headers={"User-Agent": "memebot/0.1", "Accept": "application/json"},
    )


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    backoff: float = 1.5,
) -> Any:
    last = ""
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(backoff * (attempt + 1))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last = f"HTTP {resp.status_code}"
            await asyncio.sleep(backoff * (attempt + 1))
            continue
        if resp.status_code != 200:
            raise HttpError(f"HTTP {resp.status_code} от {url}", resp.status_code)
        try:
            return resp.json()
        except ValueError as exc:
            raise HttpError(f"Не JSON от {url}") from exc
    raise HttpError(f"{url} недоступен: {last}")
