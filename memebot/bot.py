"""Telegram-интерфейс: уведомления и команды управления. Слушается только ADMIN_CHAT_ID."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Settings
from .engine import Buttons, Engine
from .fmt import esc, pct, signed_sol, sol, usd

HELP = """<b>Команды</b>
/status — режим, баланс, результат
/positions — открытые позиции
/history — последние закрытые сделки
/scan — что бот видит прямо сейчас (без покупок)
/buy <code>адрес_токена</code> — купить вручную (защитные проверки всё равно делаются)
/sell <code>номер</code> — продать позицию
/sellall — продать всё
/pause, /resume — остановить или продолжить новые покупки
/settings — текущие лимиты и фильтры"""


def make_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))


def keyboard(buttons: Buttons | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data)] for text, data in buttons]
    )


def make_notifier(bot: Bot, chat_id: int):
    async def notify(text: str, buttons: Buttons | None = None) -> None:
        await bot.send_message(chat_id, text, reply_markup=keyboard(buttons))

    return notify


async def status_text(engine: Engine) -> str:
    s = engine.s
    mode = "💰 <b>боевой</b> (реальные SOL)" if s.is_live else "📝 <b>бумажный</b> (виртуальные SOL, реальные цены)"
    paused = await engine.paused_reason()
    block = await engine.buy_block_reason()
    state = f"⏸ пауза: {esc(paused)}" if paused else ("▶️ ищу токены" if not block else f"▶️ работаю, покупки пока нет: {esc(block)}")
    balance = await engine.trader.sol_balance()
    positions = await engine.store.open_positions()
    in_positions = sum(p.last_value_lamports for p in positions)
    stats = await engine.store.stats()
    winrate = f"{stats['wins'] / stats['closed']:.0%}" if stats["closed"] else "—"
    lines = [
        f"Режим: {mode}",
        f"Автопокупка: {'включена' if s.auto_buy else 'выключена — присылаю сигналы с кнопкой'}",
        f"Состояние: {state}",
        f"Свободно: {sol(balance)}",
        f"Открыто позиций: {len(positions)}/{s.max_open_positions} (сейчас стоят ~{sol(in_positions)})",
        f"Сегодня: {signed_sol(await engine.daily_pnl())}",
        f"Всего: {signed_sol(stats['pnl'])} за {stats['closed']} сделок, в плюс {winrate}",
    ]
    if engine.trader.address:
        lines.append(f"Кошелёк: <code>{engine.trader.address}</code>")
    return "\n".join(lines)


def position_line(p, now: int) -> str:
    hours = (now - p.opened_at) / 3600
    return (
        f"#{p.id} <b>{esc(p.symbol)}</b> — {pct(p.multiple - 1)} · вложено {sol(p.entry_lamports)}, "
        f"стоит ~{sol(p.total_value)} · {hours:.1f} ч · <a href=\"{esc(p.url)}\">график</a>"
    )


def build_router(engine: Engine, settings: Settings) -> Router:
    router = Router()
    admin = settings.admin_chat_id
    router.message.filter(F.from_user.id == admin)
    router.callback_query.filter(F.from_user.id == admin)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def cmd_start(message: Message) -> None:
        await message.answer(await status_text(engine) + "\n\n" + HELP)

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        await message.answer(await status_text(engine))

    @router.message(Command("positions"))
    async def cmd_positions(message: Message) -> None:
        positions = await engine.store.open_positions()
        if not positions:
            await message.answer("Открытых позиций нет.")
            return
        now = engine.now()
        await message.answer(
            "\n".join(position_line(p, now) for p in positions),
            reply_markup=keyboard([(f"🔴 Продать #{p.id} {p.symbol}", f"sell:{p.id}") for p in positions]),
        )

    @router.message(Command("history"))
    async def cmd_history(message: Message) -> None:
        closed = await engine.store.closed_positions(10)
        if not closed:
            await message.answer("Закрытых сделок пока нет.")
            return
        lines = [
            f"#{p.id} <b>{esc(p.symbol)}</b> {signed_sol(p.pnl_lamports or 0)} "
            f"({pct((p.pnl_lamports or 0) / p.entry_lamports)}) — {esc(p.close_reason or '')}"
            for p in closed
        ]
        await message.answer("\n".join(lines))

    @router.message(Command("scan"))
    async def cmd_scan(message: Message) -> None:
        await message.answer("🔎 Сканирую, это займёт до минуты…")
        try:
            verdicts = await engine.evaluate(use_cooldowns=False)
        except Exception as exc:
            await message.answer(f"Не удалось: {esc(str(exc))}")
            return
        if not verdicts:
            await message.answer("Кандидатов нет.")
            return
        lines = []
        for v in verdicts[:12]:
            mark = "✅" if v.ok else ("🟡" if v.passed_filters and not v.deep_checked else "❌")
            why = "все проверки пройдены" if v.ok else ("прошёл фильтры, глубокая проверка не дошла" if not v.reasons else "; ".join(v.reasons[:2]))
            lines.append(f"{mark} <b>{esc(v.pair.symbol)}</b> {usd(v.pair.mcap_usd)} — {esc(why)}")
        passed = sum(1 for v in verdicts if v.ok)
        await message.answer(f"Проверено {len(verdicts)}, подходят: {passed}\n\n" + "\n".join(lines))

    @router.message(Command("buy"))
    async def cmd_buy(message: Message, command: CommandObject) -> None:
        mint = (command.args or "").strip()
        if not mint:
            await message.answer("Укажи адрес токена: /buy <code>адрес</code>")
            return
        await message.answer("Проверяю и покупаю…")
        try:
            await engine.manual_buy(mint)
        except Exception as exc:
            await message.answer(f"Не куплено: {esc(str(exc))}")

    @router.message(Command("sell"))
    async def cmd_sell(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip().lstrip("#")
        if not arg.isdigit():
            await message.answer("Укажи номер позиции из /positions, например /sell 3")
            return
        try:
            await engine.sell_position(int(arg), 1.0, "продано вручную")
        except Exception as exc:
            await message.answer(f"Не продано: {esc(str(exc))}")

    @router.message(Command("sellall"))
    async def cmd_sellall(message: Message) -> None:
        count = len(await engine.store.open_positions())
        if not count:
            await message.answer("Открытых позиций нет.")
            return
        await message.answer(
            f"Продать все {count} позиций по рынку?",
            reply_markup=keyboard([("Да, продать всё", "sellall:yes")]),
        )

    @router.message(Command("pause"))
    async def cmd_pause(message: Message) -> None:
        await engine.pause("остановлено командой /pause")
        await message.answer("⏸ Новые покупки остановлены. Открытые позиции продолжаю вести (стопы работают).")

    @router.message(Command("resume"))
    async def cmd_resume(message: Message) -> None:
        await engine.resume()
        await message.answer("▶️ Продолжаю.\n\n" + await status_text(engine))

    @router.message(Command("settings"))
    async def cmd_settings(message: Message) -> None:
        s = settings
        await message.answer(
            "<b>Деньги</b>\n"
            f"Покупка: {sol(s.buy_amount_lamports)} · позиций максимум {s.max_open_positions}\n"
            f"Дневной лимит убытка: {sol(s.max_daily_loss_lamports)} · общий: {sol(s.max_total_loss_lamports)}\n"
            f"Резерв на комиссии: {sol(s.min_sol_reserve_lamports)}\n"
            f"Проскальзывание: покупка {s.buy_slippage_bps / 100:g}%, продажа {s.sell_slippage_bps / 100:g}%\n\n"
            "<b>Выход</b>\n"
            f"Стоп-лосс −{s.stop_loss_pct:g}% · тейк-профит +{s.take_profit_pct:g}% (продаю {s.take_profit_sell_fraction:.0%})\n"
            f"Трейлинг {s.trailing_stop_pct:g}% от пика после +{s.trailing_activate_pct:g}% · максимум {s.max_hold_hours:g} ч\n\n"
            "<b>Фильтры</b>\n"
            f"Ликвидность ≥ {usd(s.min_liquidity_usd)} · объём 24ч ≥ {usd(s.min_volume_h24_usd)}\n"
            f"Капитализация {usd(s.min_mcap_usd)}–{usd(s.max_mcap_usd)} · возраст {s.min_pair_age_hours:g}–{s.max_pair_age_hours:g} ч\n"
            f"Рост за час {s.min_price_change_h1:+g}%…{s.max_price_change_h1:+g}% · сделок за час ≥ {s.min_txns_h1}\n"
            f"RugCheck ≤ {s.max_rugcheck_score:g} · ликвидность заблокирована ≥ {s.min_lp_locked_pct:g}% · "
            f"потери купить-продать ≤ {s.max_roundtrip_loss_pct:g}%\n\n"
            "Меняются в файле .env, после правки перезапусти бота."
        )

    @router.callback_query(F.data.startswith("sell:"))
    async def cb_sell(callback: CallbackQuery) -> None:
        await callback.answer("Продаю…")
        try:
            await engine.sell_position(int(callback.data.split(":", 1)[1]), 1.0, "продано вручную")
        except Exception as exc:
            await callback.message.answer(f"Не продано: {esc(str(exc))}")

    @router.callback_query(F.data.startswith("buy:"))
    async def cb_buy(callback: CallbackQuery) -> None:
        await callback.answer("Проверяю и покупаю…")
        try:
            await engine.manual_buy(callback.data.split(":", 1)[1])
        except Exception as exc:
            await callback.message.answer(f"Не куплено: {esc(str(exc))}")

    @router.callback_query(F.data == "sellall:yes")
    async def cb_sellall(callback: CallbackQuery) -> None:
        await callback.answer("Продаю всё…")
        results = await engine.sell_all()
        await callback.message.answer("Готово:\n" + "\n".join(esc(r) for r in results) if results else "Открытых позиций не было.")

    return router
