"""Когда выходить из позиции.

Все пороги считаются по полной стоимости позиции: SOL, уже полученные с частичных продаж,
плюс сколько дали бы за оставшиеся токены прямо сейчас (по реальной котировке продажи).
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .fmt import pct
from .models import Position


@dataclass
class ExitDecision:
    fraction: float  # доля оставшихся токенов к продаже, 1.0 — всё
    reason: str


def decide_exit(pos: Position, now: int, s: Settings) -> ExitDecision | None:
    entry = pos.entry_lamports
    if entry <= 0:
        return None
    total = pos.total_value
    multiple = total / entry
    peak = max(pos.peak_total_lamports, total)

    if multiple <= 1 - s.stop_loss_pct / 100:
        return ExitDecision(1.0, f"стоп-лосс ({pct(multiple - 1)})")

    if (now - pos.opened_at) / 3600 >= s.max_hold_hours:
        return ExitDecision(1.0, f"истекло время удержания {s.max_hold_hours:g} ч ({pct(multiple - 1)})")

    if peak / entry >= 1 + s.trailing_activate_pct / 100 and total <= peak * (1 - s.trailing_stop_pct / 100):
        drawdown = 1 - total / peak
        return ExitDecision(1.0, f"трейлинг-стоп: откат {drawdown * 100:.0f}% от пика ({pct(multiple - 1)})")

    if not pos.tp_done and multiple >= 1 + s.take_profit_pct / 100:
        return ExitDecision(s.take_profit_sell_fraction, f"тейк-профит ({pct(multiple - 1)})")

    return None
