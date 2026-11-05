"""Форматирование чисел и ссылок для сообщений в Telegram."""
from __future__ import annotations

import html

from .config import LAMPORTS_PER_SOL


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def sol(lamports: int) -> str:
    return f"{lamports / LAMPORTS_PER_SOL:.4f} SOL"


def signed_sol(lamports: int) -> str:
    return f"{lamports / LAMPORTS_PER_SOL:+.4f} SOL"


def pct(fraction: float) -> str:
    """0.123 -> +12.3%"""
    return f"{fraction * 100:+.1f}%"


def usd(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def tx_link(signature: str | None) -> str:
    if not signature:
        return ""
    return f'<a href="https://solscan.io/tx/{signature}">транзакция</a>'
