"""Фабрики callback_data. Держим коды короткими: лимит Telegram — 64 байта."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="m"):
    """Главное меню: order | examples | pricing | question | home."""
    action: str


class OrderCB(CallbackData, prefix="o"):
    """Шаги заявки.

    action: pick | feat | done | skip | back | cancel | phone | uname |
            submit | edit | field | restart
    value: код варианта или имя шага (для field)
    """
    action: str
    value: str = ""


class AdminCB(CallbackData, prefix="a"):
    """Кнопки под админской карточкой: take | reject."""
    action: str
    order_id: int


class PageCB(CallbackData, prefix="p"):
    """Пагинация /orders."""
    page: int
