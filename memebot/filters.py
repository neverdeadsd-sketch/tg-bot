"""Правила отбора токенов. Каждая функция возвращает список причин отказа:
пустой список — токен прошёл проверку."""
from __future__ import annotations

from .config import TOKEN_2022_PROGRAM, Settings
from .fmt import usd
from .models import PairInfo, RugReport


def check_pair(p: PairInfo, s: Settings, now_ms: int) -> list[str]:
    reasons: list[str] = []
    if p.liquidity_usd < s.min_liquidity_usd:
        reasons.append(f"ликвидность {usd(p.liquidity_usd)} < {usd(s.min_liquidity_usd)}")
    if p.volume_h24 < s.min_volume_h24_usd:
        reasons.append(f"объём 24ч {usd(p.volume_h24)} < {usd(s.min_volume_h24_usd)}")
    if p.mcap_usd < s.min_mcap_usd:
        reasons.append(f"капитализация {usd(p.mcap_usd)} < {usd(s.min_mcap_usd)}")
    elif p.mcap_usd > s.max_mcap_usd:
        reasons.append(f"капитализация {usd(p.mcap_usd)} > {usd(s.max_mcap_usd)}")

    age = p.age_hours(now_ms)
    if age is None:
        reasons.append("неизвестен возраст пула")
    elif age < s.min_pair_age_hours:
        reasons.append(f"пулу {age:.1f} ч < {s.min_pair_age_hours:g} ч (слишком свежий)")
    elif age > s.max_pair_age_hours:
        reasons.append(f"пулу {age:.0f} ч > {s.max_pair_age_hours:g} ч")

    txns = p.buys_h1 + p.sells_h1
    if txns < s.min_txns_h1:
        reasons.append(f"сделок за час {txns} < {s.min_txns_h1}")
    ratio = p.buys_h1 / max(p.sells_h1, 1)
    if ratio < s.min_buy_sell_ratio_h1:
        reasons.append(f"покупок/продаж за час {ratio:.2f} < {s.min_buy_sell_ratio_h1:g}")

    if p.change_h1 < s.min_price_change_h1:
        reasons.append(f"рост за час {p.change_h1:+.1f}% < {s.min_price_change_h1:+g}%")
    elif p.change_h1 > s.max_price_change_h1:
        reasons.append(f"рост за час {p.change_h1:+.1f}% > {s.max_price_change_h1:+g}% (поздно, вертикальный памп)")
    if p.change_m5 < s.min_price_change_m5:
        reasons.append(f"падает прямо сейчас: {p.change_m5:+.1f}% за 5 мин")
    return reasons


def check_rug(r: RugReport, s: Settings) -> list[str]:
    reasons: list[str] = []
    if r.rugged:
        reasons.append("RugCheck пометил токен как rugged")
    if not r.mint_authority_known:
        reasons.append("нет данных о mint authority")
    elif r.mint_authority:
        reasons.append("mint authority не отозван — можно допечатать токены")
    if not r.freeze_authority_known:
        reasons.append("нет данных о freeze authority")
    elif r.freeze_authority:
        reasons.append("freeze authority не отозван — твои токены могут заморозить")
    if r.score is None:
        reasons.append("нет оценки риска RugCheck")
    elif r.score > s.max_rugcheck_score:
        reasons.append(f"оценка риска RugCheck {r.score:g} > {s.max_rugcheck_score:g}")
    if r.lp_locked_pct is None:
        reasons.append("неизвестно, заблокирована ли ликвидность")
    elif r.lp_locked_pct < s.min_lp_locked_pct:
        reasons.append(f"заблокировано {r.lp_locked_pct:.0f}% ликвидности < {s.min_lp_locked_pct:g}%")
    if r.transfer_fee_pct > 0:
        reasons.append(f"комиссия за перевод токена {r.transfer_fee_pct:g}%")
    if r.token_program == TOKEN_2022_PROGRAM and not s.allow_token2022:
        reasons.append("токен на Token-2022 (возможны скрытые ограничения)")
    for risk in r.risks:
        if risk.level == "danger":
            reasons.append(f"RugCheck: {risk.name}")
    return reasons


def roundtrip_loss_pct(lamports_in: int, lamports_back: int) -> float:
    """Сколько процентов теряется, если купить и сразу продать."""
    if lamports_in <= 0:
        return 100.0
    return (1 - lamports_back / lamports_in) * 100


def pair_score(p: PairInfo) -> float:
    """Чем выше — тем активнее торгуется токен относительно своей ликвидности."""
    if p.liquidity_usd <= 0:
        return 0.0
    ratio = p.buys_h1 / max(p.sells_h1, 1)
    return p.volume_h1 / p.liquidity_usd * min(ratio, 3.0)
