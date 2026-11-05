"""RugCheck: проверка токена на типичные признаки скама."""
from __future__ import annotations

from typing import Any

import httpx

from .http import get_json
from .models import Risk, RugReport

BASE_URL = "https://api.rugcheck.xyz/v1"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _authority(data: dict[str, Any], key: str) -> tuple[bool, str | None]:
    """(известно ли значение, адрес authority или None если отозван)."""
    if key in data:
        return True, data[key] or None
    token = data.get("token")
    if isinstance(token, dict) and key in token:
        return True, token[key] or None
    return False, None


def _main_market_lp_locked(markets: list[Any]) -> float | None:
    """Процент заблокированной ликвидности в самом крупном пуле."""
    best_pct: float | None = None
    best_usd = -1.0
    any_pct: list[float] = []
    for market in markets:
        lp = market.get("lp") if isinstance(market, dict) else None
        if not isinstance(lp, dict):
            continue
        locked = _num(lp.get("lpLockedPct"))
        if locked is None:
            continue
        any_pct.append(locked)
        usd = (_num(lp.get("baseUSD")) or 0.0) + (_num(lp.get("quoteUSD")) or 0.0)
        if usd > best_usd:
            best_usd, best_pct = usd, locked
    if best_usd > 0:
        return best_pct
    return max(any_pct) if any_pct else None


def parse_report(data: dict[str, Any]) -> RugReport:
    mint_known, mint_auth = _authority(data, "mintAuthority")
    freeze_known, freeze_auth = _authority(data, "freezeAuthority")

    lp_locked = _num(data.get("lpLockedPct"))
    if lp_locked is None:
        lp_locked = _main_market_lp_locked(data.get("markets") or [])

    risks = [
        Risk(
            name=str(r.get("name") or ""),
            level=str(r.get("level") or "").lower(),
            description=str(r.get("description") or ""),
        )
        for r in data.get("risks") or []
        if isinstance(r, dict)
    ]
    fee = data.get("transferFee")
    transfer_fee = _num(fee.get("pct")) if isinstance(fee, dict) else None

    return RugReport(
        score=_num(data.get("score_normalised")),
        mint_authority_known=mint_known,
        mint_authority=mint_auth,
        freeze_authority_known=freeze_known,
        freeze_authority=freeze_auth,
        lp_locked_pct=lp_locked,
        risks=risks,
        token_program=data.get("tokenProgram"),
        rugged=bool(data.get("rugged")),
        transfer_fee_pct=transfer_fee or 0.0,
    )


class RugCheck:
    def __init__(self, http: httpx.AsyncClient, base_url: str = BASE_URL):
        self.http = http
        self.base = base_url.rstrip("/")

    async def report(self, mint: str) -> RugReport:
        data = await get_json(self.http, f"{self.base}/tokens/{mint}/report")
        if not isinstance(data, dict):
            raise ValueError("неожиданный ответ RugCheck")
        return parse_report(data)
