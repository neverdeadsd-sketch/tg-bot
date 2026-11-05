"""Минимальный JSON-RPC клиент Solana: балансы, отправка и подтверждение транзакций."""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx

COMMITMENT = "confirmed"


class RpcError(Exception):
    pass


@dataclass
class TokenAccount:
    address: str
    program: str
    amount: int
    decimals: int
    lamports: int = 0  # рента, которая вернётся при закрытии аккаунта


class SolanaRpc:
    def __init__(self, http: httpx.AsyncClient, url: str, retry_delay: float = 1.0):
        self.http = http
        self.url = url
        self.retry_delay = retry_delay

    async def call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last = ""
        for attempt in range(4):
            try:
                resp = await self.http.post(self.url, json=payload)
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue
            try:
                data = resp.json()
            except ValueError as exc:
                raise RpcError(f"{method}: не JSON (HTTP {resp.status_code})") from exc
            if data.get("error"):
                err = data["error"]
                message = err.get("message") if isinstance(err, dict) else err
                raise RpcError(f"{method}: {message}")
            return data.get("result")
        raise RpcError(f"{method}: RPC недоступен ({last})")

    async def get_balance(self, pubkey: str) -> int:
        result = await self.call("getBalance", [pubkey, {"commitment": COMMITMENT}])
        return int(result["value"])

    async def token_accounts(self, owner: str, mint: str) -> list[TokenAccount]:
        result = await self.call(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": COMMITMENT}],
        )
        accounts: list[TokenAccount] = []
        for item in result.get("value") or []:
            account = item.get("account") or {}
            info = ((account.get("data") or {}).get("parsed") or {}).get("info") or {}
            amount = info.get("tokenAmount") or {}
            accounts.append(
                TokenAccount(
                    address=item["pubkey"],
                    program=account.get("owner", ""),
                    amount=int(amount.get("amount") or 0),
                    decimals=int(amount.get("decimals") or 0),
                    lamports=int(account.get("lamports") or 0),
                )
            )
        return accounts

    async def token_balance(self, owner: str, mint: str) -> tuple[int, int | None]:
        accounts = await self.token_accounts(owner, mint)
        decimals = accounts[0].decimals if accounts else None
        return sum(a.amount for a in accounts), decimals

    async def latest_blockhash(self) -> tuple[str, int]:
        result = await self.call("getLatestBlockhash", [{"commitment": COMMITMENT}])
        value = result["value"]
        return value["blockhash"], int(value["lastValidBlockHeight"])

    async def block_height(self) -> int:
        return int(await self.call("getBlockHeight", [{"commitment": COMMITMENT}]))

    async def send_raw(self, raw_tx: bytes) -> str:
        encoded = base64.b64encode(raw_tx).decode()
        return await self.call(
            "sendTransaction",
            [encoded, {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}],
        )

    async def signature_status(self, signature: str) -> dict[str, Any] | None:
        result = await self.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": False}])
        values = result.get("value") or [None]
        return values[0]

    async def send_and_confirm(
        self,
        raw_tx: bytes,
        last_valid_height: int | None,
        *,
        timeout: float = 75.0,
        poll: float = 2.0,
        resend_every: float = 4.0,
    ) -> tuple[str, str]:
        """Отправляет транзакцию и ждёт подтверждения, переотправляя её, пока она действительна.

        Возвращает (подпись, статус): confirmed | failed: <ошибка> | expired | timeout.
        """
        signature = await self.send_raw(raw_tx)
        started = last_send = time.monotonic()
        while time.monotonic() - started < timeout:
            await asyncio.sleep(poll)
            try:
                status = await self.signature_status(signature)
            except RpcError:
                status = None
            if status:
                if status.get("err"):
                    return signature, f"failed: {status['err']}"
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return signature, "confirmed"
            if last_valid_height is not None:
                try:
                    if await self.block_height() > last_valid_height:
                        return signature, "expired"
                except RpcError:
                    pass
            if time.monotonic() - last_send >= resend_every:
                last_send = time.monotonic()
                try:
                    await self.send_raw(raw_tx)
                except RpcError:
                    pass
        return signature, "timeout"
