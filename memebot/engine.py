"""Главный цикл: поиск кандидатов, проверки, покупка, слежение за позициями, выход."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from loguru import logger

from .config import SOL_MINT, Settings
from .filters import check_pair, check_rug, pair_score, roundtrip_loss_pct
from .fmt import esc, pct, signed_sol, sol, tx_link, usd
from .jupiter import Jupiter, QuoteError
from .models import PairInfo, Position, RugReport
from .storage import Storage
from .strategy import decide_exit
from .trader import TradeError, Trader

Buttons = list[tuple[str, str]]
Notify = Callable[[str, Buttons | None], Awaitable[None]]

QUOTE_FAILURE_ALERT = 4
DUST_FRACTION = 0.001  # остаток меньше 0.1% от покупки считаем пылью


class DexSource(Protocol):
    async def candidate_mints(self) -> list[str]: ...
    async def pairs_for(self, mints: list[str]) -> dict[str, PairInfo]: ...


class RugSource(Protocol):
    async def report(self, mint: str) -> RugReport: ...


@dataclass
class Verdict:
    pair: PairInfo
    reasons: list[str] = field(default_factory=list)
    passed_filters: bool = False
    deep_checked: bool = False
    ok: bool = False
    roundtrip_loss: float | None = None


class Engine:
    def __init__(
        self,
        settings: Settings,
        store: Storage,
        dex: DexSource,
        rug: RugSource,
        jupiter: Jupiter,
        trader: Trader,
        notify: Notify,
        clock: Callable[[], float] = time.time,
    ):
        self.s = settings
        self.store = store
        self.dex = dex
        self.rug = rug
        self.jup = jupiter
        self.trader = trader
        self._notify = notify
        self.clock = clock
        self.trade_lock = asyncio.Lock()
        self._signaled: dict[str, int] = {}
        self._alerted: set[str] = set()
        self._sell_failures: dict[int, int] = {}

    # ------------------------------------------------------------------ утилиты
    def now(self) -> int:
        return int(self.clock())

    async def notify(self, text: str, buttons: Buttons | None = None) -> None:
        try:
            await self._notify(text, buttons)
        except Exception as exc:  # Telegram не должен ронять торговлю
            logger.warning("Не удалось отправить сообщение: {}", exc)

    async def _alert_once(self, key: str, text: str) -> None:
        if key not in self._alerted:
            self._alerted.add(key)
            await self.notify(text)

    def _day_start(self) -> int:
        now = self.now()
        return now - now % 86400

    # ------------------------------------------------------------------ риск
    async def paused_reason(self) -> str | None:
        return await self.store.get_kv("paused")

    async def pause(self, reason: str) -> None:
        await self.store.set_kv("paused", reason)

    async def resume(self) -> None:
        """Снимает паузу. Если пауза была из-за общего лимита убытка, лимит отсчитывается заново."""
        if await self.store.get_kv("paused_total_loss"):
            stats = await self.store.stats()
            await self.store.set_kv("loss_baseline", str(stats["pnl"]))
            await self.store.del_kv("paused_total_loss")
        await self.store.del_kv("paused")

    async def total_pnl_since_baseline(self) -> int:
        stats = await self.store.stats()
        baseline = int(await self.store.get_kv("loss_baseline") or 0)
        return stats["pnl"] - baseline

    async def daily_pnl(self) -> int:
        """Реализованный результат за сегодня (UTC) плюс текущие убытки открытых позиций."""
        realized = await self.store.realized_pnl_since(self._day_start())
        open_losses = sum(min(0, p.total_value - p.entry_lamports) for p in await self.store.open_positions())
        return realized + open_losses

    async def buy_block_reason(self) -> str | None:
        """Почему сейчас нельзя открывать новые позиции (None — можно)."""
        paused = await self.paused_reason()
        if paused:
            return f"пауза: {paused}"

        total = await self.total_pnl_since_baseline()
        if total <= -self.s.max_total_loss_lamports:
            reason = f"общий убыток {signed_sol(total)} достиг лимита MAX_TOTAL_LOSS_SOL"
            await self.pause(reason)
            await self.store.set_kv("paused_total_loss", "1")
            await self.notify(
                f"🛑 Торговля остановлена: {reason}.\n"
                "Открытые позиции продолжаю вести. Новые покупки — только после /resume "
                "(лимит убытка тогда начнёт считаться заново)."
            )
            return reason

        daily = await self.daily_pnl()
        if daily <= -self.s.max_daily_loss_lamports:
            await self._alert_once(
                f"daily:{self._day_start()}",
                f"⏸ Дневной лимит убытка: {signed_sol(daily)}. Новых покупок до 00:00 UTC не будет, "
                "открытые позиции продолжаю вести.",
            )
            return "дневной лимит убытка"

        open_count = len(await self.store.open_positions())
        if open_count >= self.s.max_open_positions:
            return f"открыто {open_count}/{self.s.max_open_positions} позиций"

        balance = await self.trader.sol_balance()
        need = self.s.buy_amount_lamports + self.s.min_sol_reserve_lamports
        if balance < need:
            await self._alert_once(
                f"balance:{self._day_start()}",
                f"💸 Мало SOL на кошельке: {sol(balance)}, нужно хотя бы {sol(need)} "
                "(сумма покупки + резерв на комиссии).",
            )
            return f"мало SOL ({sol(balance)})"
        return None

    # ------------------------------------------------------------------ отбор
    async def evaluate(self, *, use_cooldowns: bool = True) -> list[Verdict]:
        now = self.now()
        await self.store.purge_cooldowns(now)
        mints = await self.dex.candidate_mints()
        held = {p.mint for p in await self.store.open_positions()}

        fresh: list[str] = []
        for mint in mints:
            if mint in held:
                continue
            if use_cooldowns:
                if await self.store.in_cooldown(mint, now):
                    continue
                last = await self.store.last_opened_at(mint)
                if last is not None and now - last < self.s.rebuy_cooldown_hours * 3600:
                    continue
            fresh.append(mint)
        if not fresh:
            return []

        pairs = await self.dex.pairs_for(fresh)
        verdicts: list[Verdict] = []
        for mint in fresh:
            pair = pairs.get(mint)
            if pair is None:
                if use_cooldowns:
                    await self.store.set_cooldown(mint, now + self.s.reject_cooldown_min * 60, "нет пула")
                continue
            reasons = check_pair(pair, self.s, now * 1000)
            verdicts.append(Verdict(pair=pair, reasons=reasons, passed_filters=not reasons))

        verdicts.sort(key=lambda v: (not v.passed_filters, -pair_score(v.pair)))
        checked = 0
        for verdict in verdicts:
            if not verdict.passed_filters:
                continue
            if checked >= self.s.deep_checks_per_scan:
                break
            checked += 1
            await self.deep_check(verdict)
        return verdicts

    async def deep_check(self, verdict: Verdict) -> None:
        """RugCheck + проверка «купить и сразу продать» через реальные котировки Jupiter.

        Второе ловит honeypot (продать нельзя), скрытые налоги и слишком тонкую ликвидность.
        """
        verdict.deep_checked = True
        mint = verdict.pair.mint
        try:
            report = await self.rug.report(mint)
        except Exception as exc:
            verdict.reasons.append(f"RugCheck недоступен: {exc}")
            return
        verdict.reasons.extend(check_rug(report, self.s))
        if verdict.reasons:
            return
        try:
            buy_quote = await self.jup.quote(SOL_MINT, mint, self.s.buy_amount_lamports, self.s.buy_slippage_bps)
            sell_quote = await self.jup.quote(mint, SOL_MINT, buy_quote.out_amount, self.s.sell_slippage_bps)
        except QuoteError as exc:
            verdict.reasons.append(f"Jupiter: {exc}")
            return
        loss = roundtrip_loss_pct(buy_quote.in_amount, sell_quote.out_amount)
        verdict.roundtrip_loss = loss
        if loss > self.s.max_roundtrip_loss_pct:
            verdict.reasons.append(
                f"купить и сразу продать — минус {loss:.1f}% > {self.s.max_roundtrip_loss_pct:g}% "
                "(налог, тонкая ликвидность или honeypot)"
            )
            return
        verdict.ok = True

    # ------------------------------------------------------------------ цикл сканирования
    async def scan_once(self) -> int:
        """Один проход поиска. Возвращает число открытых позиций."""
        if await self.buy_block_reason():
            return 0
        verdicts = await self.evaluate(use_cooldowns=True)
        now = self.now()
        bought = 0
        for v in verdicts:
            mint = v.pair.mint
            if v.ok:
                if not self.s.auto_buy:
                    await self._send_signal(v)
                    continue
                if bought >= self.s.max_buys_per_scan or await self.buy_block_reason():
                    break
                try:
                    await self.open_position(v.pair)
                    bought += 1
                except Exception as exc:
                    logger.exception("Покупка {} не удалась", v.pair.symbol)
                    await self.notify(f"❌ Не удалось купить {esc(v.pair.symbol)}: {esc(str(exc))}")
                    await self.store.set_cooldown(mint, now + self.s.rug_reject_cooldown_min * 60, "ошибка покупки")
            elif v.deep_checked:
                await self.store.set_cooldown(mint, now + self.s.rug_reject_cooldown_min * 60, v.reasons[0])
            elif not v.passed_filters:
                await self.store.set_cooldown(mint, now + self.s.reject_cooldown_min * 60, v.reasons[0])
        return bought

    async def _send_signal(self, v: Verdict) -> None:
        now = self.now()
        last = self._signaled.get(v.pair.mint)
        if last is not None and now - last < self.s.rebuy_cooldown_hours * 3600:
            return
        self._signaled[v.pair.mint] = now
        await self.notify(
            "📡 Сигнал: " + self._pair_line(v.pair)
            + f"\nПотери на «купить-продать»: {v.roundtrip_loss:.1f}%"
            + f"\n<code>{v.pair.mint}</code>",
            [(f"🟢 Купить на {sol(self.s.buy_amount_lamports)}", f"buy:{v.pair.mint}")],
        )

    @staticmethod
    def _pair_line(p: PairInfo) -> str:
        return (
            f'<b>{esc(p.symbol)}</b> ({esc(p.name)}) — <a href="{esc(p.url)}">график</a>\n'
            f"Капитализация {usd(p.mcap_usd)} · ликвидность {usd(p.liquidity_usd)} · "
            f"объём 24ч {usd(p.volume_h24)} · за час {p.change_h1:+.1f}%"
        )

    # ------------------------------------------------------------------ сделки
    async def open_position(self, pair: PairInfo) -> Position:
        async with self.trade_lock:
            result = await self.trader.buy(pair.mint, self.s.buy_amount_lamports)
            now = self.now()
            pos = await self.store.create_position(pair, result.lamports_spent, result.token_amount, result.decimals, now)
            await self.store.add_trade(pos.id, "buy", now, -result.lamports_spent, result.token_amount, result.signature, "вход")
        s = self.s
        await self.notify(
            ("🟢 Куплено " if s.is_live else "📝 [бумага] Куплено ") + self._pair_line(pair)
            + f"\nПотрачено: {sol(result.lamports_spent)} {tx_link(result.signature)}"
            + f"\nВыход: стоп −{s.stop_loss_pct:g}% · тейк +{s.take_profit_pct:g}% "
            f"(продам {s.take_profit_sell_fraction:.0%}) · трейлинг {s.trailing_stop_pct:g}% после +{s.trailing_activate_pct:g}% "
            f"· максимум {s.max_hold_hours:g} ч",
            [("🔴 Продать", f"sell:{pos.id}")],
        )
        return pos

    async def sell_position(self, position_id: int, fraction: float, reason: str) -> Position:
        async with self.trade_lock:
            pos = await self.store.get_position(position_id)
            if pos is None or pos.status != "open":
                raise TradeError("позиция не найдена или уже закрыта")
            full = fraction >= 0.999
            basis = await self.trader.held_amount(pos.mint, pos.token_remaining) if full else pos.token_remaining
            amount = basis if full else int(basis * fraction)
            now = self.now()

            if amount <= 0:
                if not full:
                    raise TradeError("нечего продавать")
                # Токенов в кошельке нет — закрываем позицию как есть.
                await self._close(pos, now, f"{reason}; токенов в кошельке нет")
                await self.notify(f"⚠️ {esc(pos.symbol)}: токенов в кошельке не найдено, позиция закрыта.")
                return pos

            result = await self.trader.sell(pos.mint, amount, self.s.sell_slippage_bps)

            remaining = max(0, basis - result.token_sold)
            pos.realized_lamports += result.lamports_received
            if not full:
                pos.tp_done = True
            await self.store.add_trade(pos.id, "sell", now, result.lamports_received, result.token_sold, result.signature, reason)

            dust = remaining <= pos.token_amount * DUST_FRACTION
            if full and dust:
                pos.token_remaining = remaining
                await self.trader.cleanup(pos.mint)  # возвращает залог за аккаунт, это не прибыль
                await self._close(pos, now, reason)
            else:
                pos.last_value_lamports = int(pos.last_value_lamports * remaining / basis) if basis else 0
                pos.token_remaining = remaining
                await self.store.update_position(pos)

        head = "💰" if (pos.pnl_lamports or 0) > 0 or (not full and result.lamports_received > 0) else "🔴"
        if pos.status == "closed":
            text = (
                f"{head} Продано всё: <b>{esc(pos.symbol)}</b> — {esc(reason)}\n"
                f"Получено: {sol(result.lamports_received)} {tx_link(result.signature)}\n"
                f"Итог позиции: <b>{signed_sol(pos.pnl_lamports or 0)}</b> ({pct((pos.pnl_lamports or 0) / pos.entry_lamports)})"
            )
        else:
            text = (
                f"{head} Продано {fraction:.0%}: <b>{esc(pos.symbol)}</b> — {esc(reason)}\n"
                f"Получено: {sol(result.lamports_received)} {tx_link(result.signature)}\n"
                f"Всего выведено: {sol(pos.realized_lamports)} из вложенных {sol(pos.entry_lamports)}. Остаток веду дальше."
            )
        await self.notify(text, None if pos.status == "closed" else [("🔴 Продать остаток", f"sell:{pos.id}")])
        return pos

    async def _close(self, pos: Position, now: int, reason: str) -> None:
        pos.status = "closed"
        pos.closed_at = now
        pos.close_reason = reason
        pos.last_value_lamports = 0
        pos.pnl_lamports = pos.realized_lamports - pos.entry_lamports
        await self.store.update_position(pos)

    # ------------------------------------------------------------------ слежение
    async def monitor_once(self) -> None:
        for pos in await self.store.open_positions():
            try:
                await self._check_position(pos)
            except Exception:
                logger.exception("Ошибка при проверке позиции {}", pos.id)

    async def _check_position(self, pos: Position) -> None:
        try:
            quote = await self.jup.quote(pos.mint, SOL_MINT, pos.token_remaining, self.s.sell_slippage_bps)
        except QuoteError as exc:
            pos.quote_failures += 1
            await self.store.update_position(pos)
            if pos.quote_failures == QUOTE_FAILURE_ALERT:
                await self.notify(
                    f"⚠️ {esc(pos.symbol)}: {QUOTE_FAILURE_ALERT} раза подряд нет цены продажи ({esc(str(exc))}). "
                    "Возможно, ликвидность вытащили (rug).",
                    [("🔴 Попробовать продать", f"sell:{pos.id}")],
                )
            return

        pos.quote_failures = 0
        pos.last_value_lamports = quote.out_amount
        pos.peak_total_lamports = max(pos.peak_total_lamports, pos.total_value)
        await self.store.update_position(pos)

        decision = decide_exit(pos, self.now(), self.s)
        if decision:
            try:
                await self.sell_position(pos.id, decision.fraction, decision.reason)
                self._sell_failures.pop(pos.id, None)
            except Exception as exc:
                logger.exception("Продажа позиции {} не удалась", pos.id)
                count = self._sell_failures.get(pos.id, 0) + 1
                self._sell_failures[pos.id] = count
                if count in (1, 10, 50):
                    await self.notify(
                        f"❌ Не удалось продать {esc(pos.symbol)} ({esc(decision.reason)}), попытка {count}: "
                        f"{esc(str(exc))}\nПробую снова на каждой проверке.",
                        [("🔴 Продать вручную", f"sell:{pos.id}")],
                    )

    async def reconcile(self) -> None:
        """При старте сверяет открытые позиции с реальным кошельком."""
        if not self.s.is_live:
            return
        for pos in await self.store.open_positions():
            held = await self.trader.held_amount(pos.mint, pos.token_remaining)
            if held <= 0:
                await self._close(pos, self.now(), "токенов нет в кошельке (продано вне бота?)")
                await self.notify(f"ℹ️ {esc(pos.symbol)}: токенов в кошельке нет — позиция закрыта.")
            elif held != pos.token_remaining:
                pos.token_remaining = held
                await self.store.update_position(pos)

    # ------------------------------------------------------------------ ручное управление
    async def manual_buy(self, mint: str) -> Position:
        block = await self.buy_block_reason()
        if block:
            raise TradeError(block)
        if any(p.mint == mint for p in await self.store.open_positions()):
            raise TradeError("этот токен уже куплен")
        pairs = await self.dex.pairs_for([mint])
        pair = pairs.get(mint)
        if pair is None:
            raise TradeError("пул на Solana не найден")
        verdict = Verdict(pair=pair, passed_filters=True)
        await self.deep_check(verdict)  # защитные проверки обязательны и при ручной покупке
        if not verdict.ok:
            raise TradeError("; ".join(verdict.reasons))
        return await self.open_position(pair)

    async def sell_all(self) -> list[str]:
        results = []
        for pos in await self.store.open_positions():
            try:
                done = await self.sell_position(pos.id, 1.0, "продажа всего вручную")
                results.append(f"{done.symbol}: {signed_sol(done.pnl_lamports or 0)}")
            except Exception as exc:
                results.append(f"{pos.symbol}: ошибка — {exc}")
        return results

    # ------------------------------------------------------------------ запуск
    async def run(self) -> None:
        try:
            await self.reconcile()
        except Exception as exc:
            logger.exception("Сверка позиций с кошельком не удалась")
            await self.notify(f"⚠️ Не удалось сверить позиции с кошельком: {esc(str(exc))}")
        await asyncio.gather(
            self._loop(self.scan_once, self.s.scan_interval_sec, "поиск"),
            self._loop(self.monitor_once, self.s.monitor_interval_sec, "слежение"),
        )

    async def _loop(self, step: Callable[[], Awaitable[object]], interval: int, name: str) -> None:
        errors = 0
        while True:
            try:
                await step()
                errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors += 1
                logger.exception("Цикл «{}»: ошибка #{}", name, errors)
                if errors in (3, 30):
                    await self.notify(f"⚠️ Цикл «{name}» падает {errors} раз подряд: {esc(str(exc))}")
            delay = interval if errors == 0 else min(interval * 2 ** min(errors, 5), 600)
            await asyncio.sleep(delay)
