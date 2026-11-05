"""Запуск: python -m memebot"""
from __future__ import annotations

import asyncio
import os
import sys

from aiogram import Dispatcher
from loguru import logger

from .bot import build_router, make_bot, make_notifier
from .config import Settings
from .dexscreener import DexScreener
from .engine import Engine
from .fmt import sol
from .http import make_client
from .jupiter import Jupiter
from .rugcheck import RugCheck
from .solana_rpc import SolanaRpc
from .storage import Storage
from .trader import LiveTrader, PaperTrader
from .wallet import WalletError, load_keypair


async def main() -> int:
    settings = Settings.from_env()
    errors = settings.validate()
    if errors:
        for err in errors:
            logger.error(err)
        return 2

    keypair = None
    if settings.is_live:
        try:
            keypair = load_keypair(settings.wallet_private_key)
        except WalletError as exc:
            logger.error(str(exc))
            return 2

    data_dir = os.path.dirname(settings.db_path) or "."
    os.makedirs(data_dir, exist_ok=True)
    logger.add(os.path.join(data_dir, "memebot.log"), rotation="10 MB", retention=5)

    store = Storage(settings.db_path, settings.mode)
    await store.open()
    http = make_client()
    bot = make_bot(settings.telegram_token)
    try:
        jupiter = Jupiter(http, settings.jupiter_url, settings.jupiter_api_key)
        if keypair is not None:
            trader = LiveTrader(jupiter, SolanaRpc(http, settings.rpc_url), keypair, settings)
        else:
            trader = PaperTrader(jupiter, store, settings)

        engine = Engine(
            settings, store, DexScreener(http), RugCheck(http), jupiter, trader,
            make_notifier(bot, settings.admin_chat_id),
        )
        dp = Dispatcher()
        dp.include_router(build_router(engine, settings))

        try:
            me = await bot.get_me()
        except Exception as exc:
            logger.error("Telegram не принял TELEGRAM_BOT_TOKEN или недоступен: {}", exc)
            return 2
        try:
            balance = await trader.sol_balance()
        except Exception as exc:
            logger.error("Не удалось получить баланс (проверь SOLANA_RPC_URL): {}", exc)
            return 2

        mode = "БОЕВОЙ — реальные SOL" if settings.is_live else "бумажный — виртуальные SOL"
        logger.info("Бот @{}. Режим: {}. Баланс: {}. Кошелёк: {}", me.username, mode, sol(balance), trader.address or "—")
        logger.info("Если в Telegram ничего не пришло — открой @{} и нажми /start", me.username)
        await engine.notify(
            f"🚀 Бот запущен. Режим: <b>{mode}</b>\nБаланс: {sol(balance)}"
            + (f"\nКошелёк: <code>{trader.address}</code>" if trader.address else "")
            + "\n/help — команды",
        )

        engine_task = asyncio.create_task(engine.run(), name="engine")
        try:
            await dp.start_polling(bot, handle_signals=True)
        finally:
            engine_task.cancel()
            await asyncio.gather(engine_task, return_exceptions=True)
        return 0
    finally:
        await http.aclose()
        await store.close()
        await bot.session.close()


def run() -> None:
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    run()
