"""Клавиатуры главного меню и общие навигационные ряды."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import MenuCB, OrderCB


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Оставить заявку", callback_data=MenuCB(action="order"))
    builder.button(text="💼 Примеры работ", callback_data=MenuCB(action="examples"))
    builder.button(text="💰 Цены и сроки", callback_data=MenuCB(action="pricing"))
    builder.button(text="💬 Задать вопрос", callback_data=MenuCB(action="question"))
    # Первая кнопка — целевая, поэтому одна в ряду; остальные по две.
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def info_screen() -> InlineKeyboardMarkup:
    """Экран «Примеры»/«Цены»: сразу даём путь к заявке и назад в меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Оставить заявку", callback_data=MenuCB(action="order"))
    builder.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    builder.adjust(1, 1)
    return builder.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    return builder.as_markup()


def question_screen() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    return builder.as_markup()


def after_order() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💼 Примеры работ", callback_data=MenuCB(action="examples"))
    builder.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    builder.adjust(2)
    return builder.as_markup()


def nav_row(*, with_back: bool = True) -> list[InlineKeyboardButton]:
    """Нижний ряд шага: «Назад» + «Отмена» — максимум две кнопки."""
    row = []
    if with_back:
        row.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=OrderCB(action="back").pack()
            )
        )
    row.append(
        InlineKeyboardButton(
            text="✖️ Отмена", callback_data=OrderCB(action="cancel").pack()
        )
    )
    return row
