"""Мелкие помощники: валидация ввода и работа с «якорным» сообщением."""
from __future__ import annotations

import logging
import re
from html import escape
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, User

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+?\d[\d\s\-().]{6,20}$")
DESCRIPTION_LIMIT = 1000
QUESTION_LIMIT = 1000
CUSTOM_LIMIT = 64


def clean_text(raw: str) -> str:
    """Схлопывает пробелы и режет управляющие символы."""
    text = raw.replace("\r", "\n").strip()
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def validate_text(raw: str, *, min_len: int = 3, max_len: int = DESCRIPTION_LIMIT) -> tuple[str | None, str | None]:
    """Возвращает (значение, код ошибки: 'short' | 'long')."""
    text = clean_text(raw)
    if len(text) < min_len:
        return None, "short"
    if len(text) > max_len:
        return None, "long"
    return text, None


def normalize_phone(raw: str) -> str | None:
    """+7 999 123-45-67 -> +79991234567. None, если не похоже на телефон."""
    text = raw.strip()
    if not PHONE_RE.match(text):
        return None
    digits = re.sub(r"\D", "", text)
    if not 10 <= len(digits) <= 15:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits


def user_line(user: User) -> str:
    """Ссылка на пользователя для админской карточки."""
    name = escape(user.full_name)
    handle = f" @{user.username}" if user.username else ""
    return f'<a href="tg://user?id={user.id}">{name}</a>{handle} (<code>{user.id}</code>)'


async def edit_or_send(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Редактирует сообщение вместо отправки нового; вернёт актуальный message_id.

    Если сообщение удалено, слишком старое или недоступно — отправит новое.
    """
    if message_id:
        try:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            return message_id
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return message_id
            logger.debug("Не удалось отредактировать %s: %s", message_id, error)

    message = await bot.send_message(
        chat_id, text, reply_markup=markup, disable_web_page_preview=True
    )
    return message.message_id


async def show(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Один экран сценария: правим «якорное» сообщение, а не шлём новое."""
    data = await state.get_data()
    message_id = await edit_or_send(bot, chat_id, data.get("anchor_id"), text, markup)
    if message_id != data.get("anchor_id"):
        await state.update_data(anchor_id=message_id)


async def set_anchor(state: FSMContext, message_id: int) -> None:
    await state.update_data(anchor_id=message_id)


async def drop_user_message(bot: Bot, chat_id: int, message_id: int) -> None:
    """Убирает сообщение пользователя, чтобы диалог оставался в одном экране."""
    try:
        await bot.delete_message(chat_id, message_id)
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        logger.debug("Не удалось удалить сообщение %s: %s", message_id, error)
