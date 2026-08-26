"""Клавиатуры админа: действия по заявке и пагинация списка."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import AdminCB, PageCB


def order_actions(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔧 Взять в работу", callback_data=AdminCB(action="take", order_id=order_id))
    builder.button(text="❌ Отклонить", callback_data=AdminCB(action="reject", order_id=order_id))
    builder.adjust(2)
    return builder.as_markup()


def pagination(page: int, pages: int) -> InlineKeyboardMarkup | None:
    if pages <= 1:
        return None
    row: list[InlineKeyboardButton] = []
    if page > 1:
        row.append(
            InlineKeyboardButton(text="⬅️", callback_data=PageCB(page=page - 1).pack())
        )
    if page < pages:
        row.append(
            InlineKeyboardButton(text="➡️", callback_data=PageCB(page=page + 1).pack())
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])
