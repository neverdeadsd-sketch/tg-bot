import pytest
from conftest import NOW, clean_report, good_pair, make_settings

from memebot.config import TOKEN_2022_PROGRAM
from memebot.filters import check_pair, check_rug, roundtrip_loss_pct
from memebot.models import Position, Risk
from memebot.strategy import decide_exit

S = make_settings()


def test_good_pair_passes():
    assert check_pair(good_pair(), S, NOW * 1000) == []


def test_pair_rejections():
    cases = {
        "ликвидность": dict(liquidity_usd=10_000),
        "объём 24ч": dict(volume_h24=1_000),
        "капитализация": dict(mcap_usd=100_000),
        "слишком свежий": dict(created_at_ms=(NOW - 3600) * 1000),
        "неизвестен возраст": dict(created_at_ms=None),
        "сделок за час": dict(buys_h1=10, sells_h1=5),
        "покупок/продаж": dict(buys_h1=200, sells_h1=300),
        "вертикальный памп": dict(change_h1=150),
        "рост за час": dict(change_h1=-5),
        "падает прямо сейчас": dict(change_m5=-8),
    }
    for expected, override in cases.items():
        reasons = check_pair(good_pair(**override), S, NOW * 1000)
        assert any(expected in r for r in reasons), (expected, reasons)


def test_clean_report_passes():
    assert check_rug(clean_report(), S) == []


def test_rug_rejections():
    cases = {
        "mint authority не отозван": dict(mint_authority="Auth111"),
        "нет данных о mint": dict(mint_authority_known=False),
        "freeze authority не отозван": dict(freeze_authority="Auth111"),
        "оценка риска": dict(score=80),
        "нет оценки": dict(score=None),
        "заблокировано": dict(lp_locked_pct=10),
        "неизвестно, заблокирована": dict(lp_locked_pct=None),
        "rugged": dict(rugged=True),
        "Token-2022": dict(token_program=TOKEN_2022_PROGRAM),
        "комиссия за перевод": dict(transfer_fee_pct=5),
        "RugCheck: Top 10 holders": dict(risks=[Risk("Top 10 holders high ownership", "danger")]),
    }
    for expected, override in cases.items():
        reasons = check_rug(clean_report(**override), S)
        assert any(expected in r for r in reasons), (expected, reasons)


def test_warn_level_risk_is_not_blocking():
    assert check_rug(clean_report(risks=[Risk("Low amount of LP Providers", "warn")]), S) == []


def test_roundtrip_loss():
    assert roundtrip_loss_pct(1000, 950) == pytest.approx(5.0)
    assert roundtrip_loss_pct(0, 0) == 100.0


def _pos(**kw) -> Position:
    data = dict(
        id=1, mode="paper", mint="M", symbol="M", name="", url="", status="open", opened_at=NOW,
        closed_at=None, entry_lamports=1_000, token_amount=100, token_remaining=100, decimals=6,
        realized_lamports=0, last_value_lamports=1_000, peak_total_lamports=1_000,
    )
    data.update(kw)
    return Position(**data)


def test_no_exit_in_normal_range():
    assert decide_exit(_pos(last_value_lamports=1_100, peak_total_lamports=1_100), NOW + 60, S) is None


def test_stop_loss():
    d = decide_exit(_pos(last_value_lamports=740), NOW + 60, S)
    assert d and d.fraction == 1.0 and "стоп-лосс" in d.reason


def test_take_profit_sells_half_once():
    d = decide_exit(_pos(last_value_lamports=2_000, peak_total_lamports=2_000), NOW + 60, S)
    assert d and d.fraction == 0.5 and "тейк-профит" in d.reason
    assert decide_exit(_pos(last_value_lamports=2_000, peak_total_lamports=2_000, tp_done=True), NOW + 60, S) is None


def test_trailing_stop_after_activation():
    # пик +50%, сейчас +15% — откат больше 20% от пика
    d = decide_exit(_pos(last_value_lamports=1_150, peak_total_lamports=1_500), NOW + 60, S)
    assert d and d.fraction == 1.0 and "трейлинг" in d.reason
    # пик всего +20% — трейлинг ещё не включился
    assert decide_exit(_pos(last_value_lamports=950, peak_total_lamports=1_200), NOW + 60, S) is None


def test_trailing_counts_realized_part():
    # после тейк-профита: выведено 1000, остаток стоит 700, пик был 2000 → откат 15% — держим
    p = _pos(realized_lamports=1_000, last_value_lamports=700, peak_total_lamports=2_000, tp_done=True)
    assert decide_exit(p, NOW + 60, S) is None
    p.last_value_lamports = 500  # откат 25% → продаём остаток
    assert decide_exit(p, NOW + 60, S).fraction == 1.0


def test_max_hold_time():
    d = decide_exit(_pos(), NOW + 25 * 3600, S)
    assert d and "время удержания" in d.reason
