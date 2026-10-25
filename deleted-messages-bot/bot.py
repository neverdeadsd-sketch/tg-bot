import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from app import watcher
from app.archiver import router as archiver_router
from app.handlers.commands import router as commands_router
from app.storage import db
from app.utils.logger import logger
from config import ADMIN_IDS, ARCHIVE_CHAT_ID, BOT_TOKEN


async def main() -> None:
    logger.info("===================================")
    logger.info("🗃  Запуск архива удалённых сообщений...")
    logger.info("===================================")

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не указан в файле .env")
        return

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    try:
        await db.create_tables()
        logger.info("✅ База данных готова")

        # Команды подключаются первыми: архиватор принимает любое сообщение,
        # и после него до команд дело бы не дошло.
        dp.include_router(commands_router)
        dp.include_router(archiver_router)

        me = await bot.get_me()
        logger.success(f"✅ Бот @{me.username} подключён к Telegram")

        if not me.can_read_all_group_messages:
            logger.warning(
                "⚠️ У бота включён режим приватности: в группах он видит только "
                "команды. Отключить у @BotFather: /setprivacy → Disable, затем "
                "заново добавить бота в чат"
            )

        if not ARCHIVE_CHAT_ID:
            logger.warning(
                "⚠️ ARCHIVE_CHAT_ID не задан: удалённые сообщения будут "
                "копиться в базе, смотреть их командой /recent"
            )

        if not ADMIN_IDS:
            logger.warning(
                "⚠️ ADMIN_IDS пуст: команды бота не ответят никому"
            )

        await watcher.start(bot)

        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    except TelegramNetworkError as error:
        logger.error(
            "❌ Не удалось подключиться к Telegram API. "
            f"Проверьте интернет на сервере: {error}"
        )

    except Exception:
        logger.exception("❌ Ошибка при запуске бота")

    finally:
        await watcher.stop()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка бота пользователем")
