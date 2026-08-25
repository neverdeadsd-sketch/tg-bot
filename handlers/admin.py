"""Админские команды и действия по заявкам."""
from __future__ import annotations

import asyncio
import logging
import math

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message, InlineKeyboardMarkup

import db
import texts
from callbacks import AdminCB, PageCB
from config import Config
from keyboards import admin as kb

logger = logging.getLogger(__name__)
router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, config: Config) -> bool:
        user = event.from_user
        return config.is_admin(user.id if user else None)


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# --------------------------------------------------------------------------
# Отправка админам с ретраями: сеть и лимиты Telegram не должны терять заявку
# --------------------------------------------------------------------------
async def notify_admins(
    bot: Bot,
    config: Config,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    attempts: int = 3,
) -> bool:
    delivered = False
    for admin_id in config.admin_ids:
        for attempt in range(attempts):
            try:
                await bot.send_message(admin_id, text, reply_markup=markup)
                delivered = True
                break
            except TelegramRetryAfter as error:
                logger.warning("Лимит Telegram, ждём %s с", error.retry_after)
                await asyncio.sleep(error.retry_after)
            except (TelegramNetworkError, asyncio.TimeoutError) as error:
                delay = 2 ** attempt
                logger.warning("Сеть недоступна (%s), повтор через %s с", error, delay)
                await asyncio.sleep(delay)
            except TelegramForbiddenError:
                logger.error("Админ %s не запускал бота — уведомление не доставлено", admin_id)
                break
            except TelegramAPIError:
                logger.exception("Не удалось уведомить админа %s", admin_id)
                break
    return delivered


async def notify_user(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramForbiddenError:
        logger.info("Пользователь %s заблокировал бота", user_id)
    except TelegramAPIError:
        logger.exception("Не удалось уведомить пользователя %s", user_id)


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------
@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    data = await db.get_stats()
    await message.answer(
        texts.stats(data["day"], data["week"], data["total"],
                    data["by_status"], data["by_source"])
    )


async def _render_orders(page: int, config: Config) -> tuple[str, InlineKeyboardMarkup | None]:
    total = await db.count_orders()
    if total == 0:
        return texts.ORDERS_EMPTY, None
    size = config.orders_page_size
    pages = max(1, math.ceil(total / size))
    page = min(max(page, 1), pages)
    rows = await db.list_orders(limit=size, offset=(page - 1) * size)
    return texts.orders_page(rows, page, pages, total), kb.pagination(page, pages)


@router.message(Command("orders"))
async def cmd_orders(message: Message, config: Config) -> None:
    text, markup = await _render_orders(1, config)
    await message.answer(text, reply_markup=markup)


@router.callback_query(PageCB.filter())
async def paginate_orders(
    callback: CallbackQuery, callback_data: PageCB, config: Config
) -> None:
    text, markup = await _render_orders(callback_data.page, config)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.message(Command("order"))
async def cmd_order(message: Message, command: CommandObject) -> None:
    raw = (command.args or "").strip().lstrip("#№")
    if not raw.isdigit():
        await message.answer(texts.ORDER_USAGE)
        return
    row = await db.get_order(int(raw))
    if row is None:
        await message.answer(texts.ORDER_NOT_FOUND)
        return
    markup = kb.order_actions(row["id"]) if row["status"] == "new" else None
    await message.answer(texts.order_card(row), reply_markup=markup)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    rows = await db.all_orders()
    if not rows:
        await message.answer(texts.EXPORT_EMPTY)
        return
    payload = db.rows_to_csv(rows)
    document = BufferedInputFile(payload, filename="orders.csv")
    await message.answer_document(document, caption=texts.export_caption(len(rows)))


# --------------------------------------------------------------------------
# Кнопки под карточкой заявки
# --------------------------------------------------------------------------
@router.callback_query(AdminCB.filter(F.action.in_({"take", "reject"})))
async def change_status(
    callback: CallbackQuery, callback_data: AdminCB, bot: Bot
) -> None:
    status = "in_work" if callback_data.action == "take" else "rejected"
    row = await db.set_status(callback_data.order_id, status)
    if row is None:
        await callback.answer(texts.STATUS_ALREADY, show_alert=True)
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
        return

    admin_name = callback.from_user.full_name if callback.from_user else "админ"
    if callback.message:
        base = callback.message.html_text
        await callback.message.edit_text(
            base + texts.admin_status_footer(status, admin_name), reply_markup=None
        )
    await notify_user(bot, row["user_id"], texts.user_status_changed(row["id"], status))
    await callback.answer(texts.STATUS_LABELS[status])
    logger.info("Заявка %s -> %s (админ %s)", row["id"], status, callback.from_user.id)
