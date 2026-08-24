"""Клавиатуры шагов заявки."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import texts
from callbacks import MenuCB, OrderCB
from keyboards.common import nav_row

# Сколько кнопок в ряд на каждом шаге. Больше двух не ставим никогда.
ROW_WIDTH: dict[str, int] = {
    "bot_type": 1,
    "sphere": 2,
    "features": 1,
    "budget": 1,
    "deadline": 1,
}


def _finish(builder: InlineKeyboardBuilder, *, with_back: bool) -> InlineKeyboardMarkup:
    markup = builder.as_markup()
    markup.inline_keyboard.append(nav_row(with_back=with_back))
    return markup


def choice(step: str, selected: str | None = None, *, with_back: bool = True) -> InlineKeyboardMarkup:
    """Одиночный выбор. Уже выбранный вариант помечаем галочкой."""
    builder = InlineKeyboardBuilder()
    for code, label in texts.CATALOGS[step]:
        mark = " ✓" if code == selected else ""
        builder.button(text=f"{label}{mark}", callback_data=OrderCB(action="pick", value=code))
    builder.adjust(ROW_WIDTH.get(step, 1))
    return _finish(builder, with_back=with_back)


def features(selected: list[str], *, with_back: bool = True) -> InlineKeyboardMarkup:
    """Мультивыбор с галочками + «Готово»."""
    builder = InlineKeyboardBuilder()
    for code, label in texts.FEATURES:
        mark = "✅" if code in selected else "▫️"
        builder.button(text=f"{mark} {label}", callback_data=OrderCB(action="feat", value=code))
    builder.adjust(ROW_WIDTH["features"])
    markup = builder.as_markup()
    markup.inline_keyboard.append([
        InlineKeyboardButton(
            text=f"✅ Готово ({len(selected)})", callback_data=OrderCB(action="done").pack()
        )
    ])
    markup.inline_keyboard.append(nav_row(with_back=with_back))
    return markup


def description(*, with_back: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data=OrderCB(action="skip"))
    builder.adjust(1)
    return _finish(builder, with_back=with_back)


def contact(username: str | None, *, with_back: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if username:
        builder.button(text=f"📎 Отправить @{username}", callback_data=OrderCB(action="uname"))
    builder.button(text="📱 Ввести телефон", callback_data=OrderCB(action="phone"))
    builder.adjust(1)
    return _finish(builder, with_back=with_back)


def text_input(*, with_back: bool = True) -> InlineKeyboardMarkup:
    """Шаг со свободным вводом: только навигация."""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append(nav_row(with_back=with_back))
    return markup


def confirm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Отправить", callback_data=OrderCB(action="submit"))
    builder.button(text="✏️ Изменить", callback_data=OrderCB(action="edit"))
    builder.button(text="✖️ Отменить", callback_data=OrderCB(action="cancel"))
    builder.adjust(2, 1)
    return builder.as_markup()


def edit_menu(steps: tuple[str, ...]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for step in steps:
        builder.button(
            text=texts.STEP_TITLES[step], callback_data=OrderCB(action="field", value=step)
        )
    builder.adjust(2)
    markup = builder.as_markup()
    markup.inline_keyboard.append([
        InlineKeyboardButton(
            text="⬅️ К проверке", callback_data=OrderCB(action="back").pack()
        )
    ])
    return markup


def limit_reached() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Задать вопрос", callback_data=MenuCB(action="question"))
    builder.button(text="⬅️ В меню", callback_data=MenuCB(action="home"))
    builder.adjust(2)
    return builder.as_markup()
