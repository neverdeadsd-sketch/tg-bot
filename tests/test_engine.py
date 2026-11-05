from conftest import NOW, Clock, FakeDex, FakeJupiter, FakeRug, clean_report, good_pair, make_settings

from memebot.config import LAMPORTS_PER_SOL
from memebot.engine import Engine
from memebot.trader import PaperTrader

SOL = LAMPORTS_PER_SOL
RATE = 1_000_000_000  # токенов (в минимальных единицах) за 1 SOL


class Harness:
    def __init__(self, store, pairs, reports=None, **settings):
        self.s = make_settings(**settings)
        self.store = store
        self.jup = FakeJupiter()
        for p in pairs:
            self.jup.tokens_per_sol[p.mint] = RATE
            self.jup.spread_pct[p.mint] = 1.0
        self.dex = FakeDex(pairs)
        self.rug = FakeRug(reports if reports is not None else {p.mint: clean_report() for p in pairs})
        self.clock = Clock()
        self.messages: list[tuple[str, list | None]] = []
        self.trader = PaperTrader(self.jup, store, self.s)
        self.engine = Engine(self.s, store, self.dex, self.rug, self.jup, self.trader, self.notify, clock=self.clock)

    async def notify(self, text, buttons=None):
        self.messages.append((text, buttons))

    def set_price_multiple(self, mint, multiple):
        self.jup.tokens_per_sol[mint] = RATE / multiple

    def texts(self):
        return "\n".join(t for t, _ in self.messages)


async def test_scan_buys_good_token_in_paper_mode(store):
    h = Harness(store, [good_pair("AAA")])
    assert await h.engine.scan_once() == 1
    [pos] = await store.open_positions()
    assert pos.mint == "AAA"
    assert pos.entry_lamports == h.s.buy_amount_lamports
    assert pos.token_amount == int(h.s.buy_amount_lamports / SOL * RATE)
    assert await h.trader.sol_balance() == h.s.paper_start_lamports - h.s.buy_amount_lamports
    assert "Куплено" in h.texts()
    assert h.messages[-1][1] == [("🔴 Продать", f"sell:{pos.id}")]


async def test_scan_rejects_scam_signs(store):
    pairs = [good_pair("MINTAUTH"), good_pair("HONEYPOT"), good_pair("NOROUTE"), good_pair("NORUG"), good_pair("THINLIQ", liquidity_usd=5_000)]
    reports = {
        "MINTAUTH": clean_report(mint_authority="Evil111"),
        "HONEYPOT": clean_report(),
        "NOROUTE": clean_report(),
        "THINLIQ": clean_report(),
    }
    h = Harness(store, pairs, reports)
    h.jup.spread_pct["HONEYPOT"] = 60.0
    h.jup.fail.add("NOROUTE")
    assert await h.engine.scan_once() == 0
    assert await store.open_positions() == []
    for mint in ("MINTAUTH", "HONEYPOT", "NOROUTE", "NORUG", "THINLIQ"):
        assert await store.in_cooldown(mint, NOW), mint


async def test_dry_scan_reports_reasons_without_buying(store):
    h = Harness(store, [good_pair("AAA"), good_pair("BAD", mcap_usd=50_000)])
    verdicts = await h.engine.evaluate(use_cooldowns=False)
    by_mint = {v.pair.mint: v for v in verdicts}
    assert by_mint["AAA"].ok and by_mint["AAA"].roundtrip_loss is not None
    assert not by_mint["BAD"].passed_filters and "капитализация" in by_mint["BAD"].reasons[0]
    assert await store.open_positions() == []


async def test_respects_position_limits(store):
    h = Harness(store, [good_pair(m) for m in ("A1", "A2", "A3")], MAX_OPEN_POSITIONS=2, MAX_BUYS_PER_SCAN=5)
    assert await h.engine.scan_once() == 2
    assert len(await store.open_positions()) == 2
    assert await h.engine.scan_once() == 0


async def test_one_buy_per_scan_by_default(store):
    h = Harness(store, [good_pair(m) for m in ("A1", "A2")])
    assert await h.engine.scan_once() == 1


async def test_take_profit_then_trailing_stop(store):
    h = Harness(store, [good_pair("AAA")])
    await h.engine.scan_once()
    [pos] = await store.open_positions()

    h.set_price_multiple("AAA", 2.2)  # +120% → тейк-профит, продаём половину
    await h.engine.monitor_once()
    [pos] = await store.open_positions()
    assert pos.tp_done
    assert pos.token_remaining == pos.token_amount - pos.token_amount // 2
    assert pos.realized_lamports > pos.entry_lamports  # вложенное уже вернули
    assert "Продано 50%" in h.texts()

    h.set_price_multiple("AAA", 1.2)  # глубокий откат от пика → продаём остаток
    await h.engine.monitor_once()
    assert await store.open_positions() == []
    [closed] = await store.closed_positions()
    assert closed.pnl_lamports > 0
    assert "трейлинг" in closed.close_reason
    assert await h.trader.sol_balance() > h.s.paper_start_lamports


async def test_stop_loss_and_daily_limit(store):
    h = Harness(store, [good_pair("AAA"), good_pair("BBB")], MAX_DAILY_LOSS_SOL="0.01")
    await h.engine.scan_once()
    [pos] = await store.open_positions()
    h.set_price_multiple(pos.mint, 0.5)
    await h.engine.monitor_once()
    [closed] = await store.closed_positions()
    assert closed.pnl_lamports < 0 and "стоп-лосс" in closed.close_reason

    # дневной лимит убытка превышен — новых покупок нет
    assert await h.engine.scan_once() == 0
    assert "Дневной лимит" in h.texts()

    # на следующий день покупки снова разрешены
    h.clock.now += 86400
    assert await h.engine.scan_once() == 1


async def test_total_loss_limit_pauses_and_resume_resets_it(store):
    h = Harness(store, [good_pair("AAA"), good_pair("BBB")], MAX_TOTAL_LOSS_SOL="0.01", MAX_DAILY_LOSS_SOL="10")
    await h.engine.scan_once()
    [pos] = await store.open_positions()
    h.set_price_multiple(pos.mint, 0.5)
    await h.engine.monitor_once()

    assert await h.engine.scan_once() == 0
    assert "общий убыток" in (await h.engine.paused_reason())
    assert "Торговля остановлена" in h.texts()

    await h.engine.resume()
    assert await h.engine.paused_reason() is None
    assert await h.engine.scan_once() == 1


async def test_no_rebuy_of_same_token_within_cooldown(store):
    h = Harness(store, [good_pair("AAA")])
    await h.engine.scan_once()
    [pos] = await store.open_positions()
    await h.engine.sell_position(pos.id, 1.0, "тест")
    h.clock.now += 3600
    assert await h.engine.scan_once() == 0
    h.clock.now += 24 * 3600
    assert await h.engine.scan_once() == 1


async def test_signals_mode_waits_for_button(store):
    h = Harness(store, [good_pair("AAA")], AUTO_BUY="false")
    assert await h.engine.scan_once() == 0
    assert await store.open_positions() == []
    text, buttons = h.messages[-1]
    assert "Сигнал" in text and buttons[0][1] == "buy:AAA"
    # повторный скан не спамит тем же сигналом
    await h.engine.scan_once()
    assert sum("Сигнал" in t for t, _ in h.messages) == 1

    pos = await h.engine.manual_buy("AAA")
    assert pos.mint == "AAA"


async def test_manual_buy_still_runs_safety_checks(store):
    h = Harness(store, [good_pair("EVIL")], {"EVIL": clean_report(freeze_authority="Evil111")})
    try:
        await h.engine.manual_buy("EVIL")
    except Exception as exc:
        assert "freeze authority" in str(exc)
    else:
        raise AssertionError("купил токен с freeze authority")


async def test_alert_when_sell_quote_disappears(store):
    h = Harness(store, [good_pair("AAA")])
    await h.engine.scan_once()
    h.jup.fail.add("AAA")
    for _ in range(5):
        await h.engine.monitor_once()
    assert sum("нет цены продажи" in t for t, _ in h.messages) == 1


async def test_failed_auto_sell_is_retried_and_reported_once(store):
    h = Harness(store, [good_pair("AAA")])
    await h.engine.scan_once()
    h.set_price_multiple("AAA", 0.5)

    calls = {"n": 0}
    real_sell = h.trader.sell

    async def flaky_sell(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("blockhash expired")
        return await real_sell(*args, **kwargs)

    h.trader.sell = flaky_sell
    await h.engine.monitor_once()
    await h.engine.monitor_once()
    assert len(await store.open_positions()) == 1
    assert sum("Не удалось продать" in t for t, _ in h.messages) == 1
    await h.engine.monitor_once()
    assert await store.open_positions() == []


async def test_sell_all(store):
    h = Harness(store, [good_pair(m) for m in ("A1", "A2")], MAX_BUYS_PER_SCAN=2)
    await h.engine.scan_once()
    results = await h.engine.sell_all()
    assert len(results) == 2
    assert await store.open_positions() == []


async def test_telegram_layer_builds_and_renders(store):
    from memebot.bot import HELP, build_router, keyboard, status_text

    h = Harness(store, [good_pair("AAA")])
    await h.engine.scan_once()
    router = build_router(h.engine, h.s)
    assert router.message.handlers and router.callback_query.handlers
    text = await status_text(h.engine)
    assert "бумажный" in text and "Открыто позиций: 1/3" in text
    assert keyboard([("a", "b")]).inline_keyboard[0][0].callback_data == "b"
    assert "/sellall" in HELP
