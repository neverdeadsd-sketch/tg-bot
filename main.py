"""Точка входа: сборка бота, роутеров, middleware и запуск long polling."""
from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, ErrorEvent

import db
import texts
from config import ENV_LOADED, ENV_PATH, Config, ConfigError, load_config, setup_logging
from handlers import admin, common, order
from middlewares import ThrottlingMiddleware

logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand(command="start", description="Меню"),
    BotCommand(command="cancel", description="Отменить заявку"),
    BotCommand(command="help", description="Помощь"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="orders", description="Последние заявки"),
    BotCommand(command="order", description="Заявка по номеру"),
    BotCommand(command="export", description="Выгрузка CSV"),
]


def build_dispatcher(config: Config) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["config"] = config

    # Троттлинг ставим внешним middleware: он срабатывает до фильтров,
    # поэтому лишние апдейты не доходят даже до хендлеров.
    dispatcher.message.outer_middleware(ThrottlingMiddleware(config.throttle_message))
    dispatcher.callback_query.outer_middleware(ThrottlingMiddleware(config.throttle_callback))

    dispatcher.include_routers(
        common.system_router,  # /start и /cancel — раньше FSM-хендлеров
        admin.router,
        order.router,
        common.router,
    )

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception(
            "Необработанная ошибка в апдейте %s", event.update.update_id,
            exc_info=event.exception,
        )
        update = event.update
        with suppress(TelegramAPIError):
            if update.callback_query is not None:
                await update.callback_query.answer(texts.ERROR_GENERIC, show_alert=True)
            elif update.message is not None:
                await update.message.answer(texts.ERROR_GENERIC)
        return True

    return dispatcher


async def setup_commands(bot: Bot, config: Config) -> None:
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in config.admin_ids:
        with suppress(TelegramAPIError):
            await bot.set_my_commands(
                ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )


async def run() -> None:
    config = load_config()
    setup_logging(config.log_level)
    logger.info(
        "Конфигурация: %s (%s)", ENV_PATH,
        "файл загружен" if ENV_LOADED else "файла нет, значения взяты из переменных окружения",
    )

    db.setup(config.db_path)
    await db.init_db()

    session = AiohttpSession(timeout=config.request_timeout)
    bot = Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(dispatcher.stop_polling()))

    try:
        me = await bot.get_me()
        logger.info("Запуск @%s (id=%s), админы: %s", me.username, me.id, config.admin_ids)
        await setup_commands(bot, config)
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


def main() -> None:
    try:
        asyncio.run(run())
    except ConfigError as error:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        logging.error("Ошибка конфигурации: %s", error)
        raise SystemExit(1) from error
    except (KeyboardInterrupt, SystemExit):
        logger.info("Выход по сигналу")


if __name__ == "__main__":
    main()
