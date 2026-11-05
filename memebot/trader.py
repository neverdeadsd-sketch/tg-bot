"""Исполнение сделок: бумажное (виртуальные SOL) и боевое (реальный кошелёк)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from loguru import logger
from solders.keypair import Keypair

from .config import SOL_MINT, Settings
from .jupiter import Jupiter
from .solana_rpc import SolanaRpc
from .storage import Storage
from .wallet import build_close_accounts_tx, sign_swap_transaction


class TradeError(Exception):
    pass


@dataclass
class BuyResult:
    token_amount: int
    lamports_spent: int
    signature: str | None
    decimals: int | None
    status: str
    rent_lamports: int = 0  # залог за новый токен-аккаунт, вернётся при его закрытии


@dataclass
class SellResult:
    lamports_received: int
    token_sold: int
    signature: str | None
    status: str


class Trader(Protocol):
    address: str | None

    async def sol_balance(self) -> int: ...
    async def buy(self, mint: str, lamports: int) -> BuyResult: ...
    async def sell(self, mint: str, token_amount: int, slippage_bps: int) -> SellResult: ...
    async def held_amount(self, mint: str, fallback: int) -> int: ...
    async def cleanup(self, mint: str) -> int: ...


class PaperTrader:
    """Сделки по реальным котировкам Jupiter, но без транзакций. Баланс виртуальный.

    Чтобы результат не выглядел лучше реальности, к каждой сделке добавляется комиссия сети
    (PAPER_FEE_LAMPORTS) и дополнительное проскальзывание (PAPER_EXTRA_SLIPPAGE_PCT).
    """

    address: str | None = None

    def __init__(self, jupiter: Jupiter, store: Storage, settings: Settings):
        self.jup = jupiter
        self.store = store
        self.s = settings

    async def sol_balance(self) -> int:
        value = await self.store.get_kv("paper_balance")
        if value is None:
            await self.store.set_kv("paper_balance", str(self.s.paper_start_lamports))
            return self.s.paper_start_lamports
        return int(value)

    async def _set_balance(self, lamports: int) -> None:
        await self.store.set_kv("paper_balance", str(lamports))

    def _haircut(self, amount: int) -> int:
        return int(amount * (1 - self.s.paper_extra_slippage_pct / 100))

    async def buy(self, mint: str, lamports: int) -> BuyResult:
        balance = await self.sol_balance()
        spent = lamports + self.s.paper_fee_lamports
        if spent > balance:
            raise TradeError("не хватает виртуальных SOL")
        quote = await self.jup.quote(SOL_MINT, mint, lamports, self.s.buy_slippage_bps)
        await self._set_balance(balance - spent)
        return BuyResult(self._haircut(quote.out_amount), spent, None, None, "paper")

    async def sell(self, mint: str, token_amount: int, slippage_bps: int) -> SellResult:
        quote = await self.jup.quote(mint, SOL_MINT, token_amount, slippage_bps)
        received = self._haircut(quote.out_amount) - self.s.paper_fee_lamports
        await self._set_balance(await self.sol_balance() + received)
        return SellResult(received, token_amount, None, "paper")

    async def held_amount(self, mint: str, fallback: int) -> int:
        return fallback

    async def cleanup(self, mint: str) -> int:
        return 0


class LiveTrader:
    """Реальные сделки через Jupiter с подписью ключом из WALLET_PRIVATE_KEY.

    Итог каждой сделки берётся из изменения балансов кошелька, а не из котировки,
    поэтому учтены все комиссии и реальное проскальзывание. Залог за токен-аккаунт
    (~0.002 SOL) в стоимость покупки не входит: бот возвращает его после продажи.
    """

    def __init__(self, jupiter: Jupiter, rpc: SolanaRpc, keypair: Keypair, settings: Settings):
        self.jup = jupiter
        self.rpc = rpc
        self.kp = keypair
        self.s = settings
        self.address: str | None = str(keypair.pubkey())

    async def sol_balance(self) -> int:
        return await self.rpc.get_balance(self.address)

    async def _swap(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> tuple[str, str]:
        quote = await self.jup.quote(input_mint, output_mint, amount, slippage_bps)
        tx_b64, last_valid = await self.jup.swap_transaction(
            quote, self.address, self.s.priority_fee_max_lamports, self.s.priority_level
        )
        raw, _ = sign_swap_transaction(tx_b64, self.kp)
        return await self.rpc.send_and_confirm(raw, last_valid)

    async def _balances(self, mint: str) -> tuple[int, int, int | None]:
        sol = await self.rpc.get_balance(self.address)
        tokens, decimals = await self.rpc.token_balance(self.address, mint)
        return sol, tokens, decimals

    async def _settle(self, mint: str, sol_before: int, tok_before: int, want_token_increase: bool):
        """RPC иногда отдаёт старый баланс сразу после подтверждения — перечитываем несколько раз."""
        sol_after, tok_after, decimals = await self._balances(mint)
        for _ in range(3):
            changed = tok_after > tok_before if want_token_increase else tok_after < tok_before
            if changed:
                break
            await asyncio.sleep(2)
            sol_after, tok_after, decimals = await self._balances(mint)
        return sol_after, tok_after, decimals

    async def buy(self, mint: str, lamports: int) -> BuyResult:
        accounts_before = {a.address for a in await self.rpc.token_accounts(self.address, mint)}
        sol_before, tok_before, _ = await self._balances(mint)
        signature, status = await self._swap(SOL_MINT, mint, lamports, self.s.buy_slippage_bps)
        sol_after, tok_after, decimals = await self._settle(mint, sol_before, tok_before, True)
        received = tok_after - tok_before
        if received <= 0:
            raise TradeError(f"покупка не прошла ({status}), подпись {signature}")
        # Залог за новый токен-аккаунт — не расход: он вернётся, когда бот закроет аккаунт после продажи.
        rent = sum(
            a.lamports for a in await self.rpc.token_accounts(self.address, mint) if a.address not in accounts_before
        )
        return BuyResult(received, sol_before - sol_after - rent, signature, decimals, status, rent)

    async def sell(self, mint: str, token_amount: int, slippage_bps: int) -> SellResult:
        sol_before, tok_before, _ = await self._balances(mint)
        amount = min(token_amount, tok_before)
        if amount <= 0:
            raise TradeError("в кошельке нет этих токенов")
        signature, status = await self._swap(mint, SOL_MINT, amount, slippage_bps)
        sol_after, tok_after, _ = await self._settle(mint, sol_before, tok_before, False)
        sold = tok_before - tok_after
        if sold <= 0:
            raise TradeError(f"продажа не прошла ({status}), подпись {signature}")
        return SellResult(sol_after - sol_before, sold, signature, status)

    async def held_amount(self, mint: str, fallback: int) -> int:
        amount, _ = await self.rpc.token_balance(self.address, mint)
        return amount

    async def cleanup(self, mint: str) -> int:
        """Закрывает пустые токен-аккаунты, возвращая ренту (~0.002 SOL за аккаунт)."""
        try:
            empty = [a for a in await self.rpc.token_accounts(self.address, mint) if a.amount == 0]
            if not empty:
                return 0
            before = await self.rpc.get_balance(self.address)
            blockhash, last_valid = await self.rpc.latest_blockhash()
            raw, _ = build_close_accounts_tx(self.kp, [(a.address, a.program) for a in empty], blockhash)
            _, status = await self.rpc.send_and_confirm(raw, last_valid)
            after = await self.rpc.get_balance(self.address)
            if status != "confirmed":
                logger.warning("Закрытие токен-аккаунтов {}: {}", mint, status)
            return max(0, after - before)
        except Exception as exc:  # возврат ренты не критичен, сделку не ломаем
            logger.warning("Не удалось закрыть токен-аккаунты {}: {}", mint, exc)
            return 0
