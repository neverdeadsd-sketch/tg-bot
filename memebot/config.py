"""Настройки бота. Всё берётся из переменных окружения (файл .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

LAMPORTS_PER_SOL = 1_000_000_000
SOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def _str(env: Mapping[str, str], name: str, default: str = "") -> str:
    value = env.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _str(env, name, str(default)).replace(",", ".")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: ожидалось число, получено {raw!r}") from exc


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _str(env, name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: ожидалось целое число, получено {raw!r}") from exc


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _str(env, name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on", "да"}


def _sol(env: Mapping[str, str], name: str, default: float) -> int:
    return int(round(_float(env, name, default) * LAMPORTS_PER_SOL))


@dataclass(frozen=True)
class Settings:
    # Telegram и доступы
    telegram_token: str
    admin_chat_id: int
    mode: str  # "paper" — виртуальные деньги, "live" — реальные сделки
    auto_buy: bool
    wallet_private_key: str
    rpc_url: str
    jupiter_url: str
    jupiter_api_key: str
    db_path: str

    # Размер сделок и риск
    buy_amount_lamports: int
    max_open_positions: int
    max_buys_per_scan: int
    max_daily_loss_lamports: int
    max_total_loss_lamports: int
    min_sol_reserve_lamports: int
    buy_slippage_bps: int
    sell_slippage_bps: int
    priority_fee_max_lamports: int
    priority_level: str
    paper_start_lamports: int
    paper_fee_lamports: int
    paper_extra_slippage_pct: float

    # Фильтры отбора
    min_liquidity_usd: float
    min_volume_h24_usd: float
    min_mcap_usd: float
    max_mcap_usd: float
    min_pair_age_hours: float
    max_pair_age_hours: float
    min_txns_h1: int
    min_buy_sell_ratio_h1: float
    min_price_change_h1: float
    max_price_change_h1: float
    min_price_change_m5: float
    max_rugcheck_score: float
    min_lp_locked_pct: float
    allow_token2022: bool
    max_roundtrip_loss_pct: float

    # Выход из позиции
    take_profit_pct: float
    take_profit_sell_fraction: float
    trailing_activate_pct: float
    trailing_stop_pct: float
    stop_loss_pct: float
    max_hold_hours: float

    # Циклы
    scan_interval_sec: int
    monitor_interval_sec: int
    deep_checks_per_scan: int
    reject_cooldown_min: int
    rug_reject_cooldown_min: int
    rebuy_cooldown_hours: int

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            from dotenv import load_dotenv

            load_dotenv()
            env = os.environ

        jupiter_key = _str(env, "JUPITER_API_KEY")
        default_jupiter = (
            "https://api.jup.ag/swap/v1" if jupiter_key else "https://lite-api.jup.ag/swap/v1"
        )
        admin_raw = _str(env, "ADMIN_CHAT_ID", "0")

        return cls(
            telegram_token=_str(env, "TELEGRAM_BOT_TOKEN"),
            admin_chat_id=int(admin_raw) if admin_raw.lstrip("-").isdigit() else 0,
            mode=_str(env, "TRADING_MODE", "paper").lower(),
            auto_buy=_bool(env, "AUTO_BUY", True),
            wallet_private_key=_str(env, "WALLET_PRIVATE_KEY"),
            rpc_url=_str(env, "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            jupiter_url=_str(env, "JUPITER_API_URL", default_jupiter),
            jupiter_api_key=jupiter_key,
            db_path=_str(env, "DATABASE_PATH", "data/memebot.db"),
            buy_amount_lamports=_sol(env, "BUY_AMOUNT_SOL", 0.05),
            max_open_positions=_int(env, "MAX_OPEN_POSITIONS", 3),
            max_buys_per_scan=_int(env, "MAX_BUYS_PER_SCAN", 1),
            max_daily_loss_lamports=_sol(env, "MAX_DAILY_LOSS_SOL", 0.15),
            max_total_loss_lamports=_sol(env, "MAX_TOTAL_LOSS_SOL", 0.5),
            min_sol_reserve_lamports=_sol(env, "MIN_SOL_RESERVE", 0.03),
            buy_slippage_bps=_int(env, "BUY_SLIPPAGE_BPS", 300),
            sell_slippage_bps=_int(env, "SELL_SLIPPAGE_BPS", 800),
            priority_fee_max_lamports=_int(env, "PRIORITY_FEE_MAX_LAMPORTS", 300_000),
            priority_level=_str(env, "PRIORITY_LEVEL", "high"),
            paper_start_lamports=_sol(env, "PAPER_START_SOL", 1.0),
            paper_fee_lamports=_int(env, "PAPER_FEE_LAMPORTS", 100_000),
            paper_extra_slippage_pct=_float(env, "PAPER_EXTRA_SLIPPAGE_PCT", 1.0),
            min_liquidity_usd=_float(env, "MIN_LIQUIDITY_USD", 50_000),
            min_volume_h24_usd=_float(env, "MIN_VOLUME_H24_USD", 150_000),
            min_mcap_usd=_float(env, "MIN_MCAP_USD", 500_000),
            max_mcap_usd=_float(env, "MAX_MCAP_USD", 30_000_000),
            min_pair_age_hours=_float(env, "MIN_PAIR_AGE_HOURS", 12),
            max_pair_age_hours=_float(env, "MAX_PAIR_AGE_HOURS", 720),
            min_txns_h1=_int(env, "MIN_TXNS_H1", 100),
            min_buy_sell_ratio_h1=_float(env, "MIN_BUY_SELL_RATIO_H1", 1.1),
            min_price_change_h1=_float(env, "MIN_PRICE_CHANGE_H1", 3),
            max_price_change_h1=_float(env, "MAX_PRICE_CHANGE_H1", 60),
            min_price_change_m5=_float(env, "MIN_PRICE_CHANGE_M5", -3),
            max_rugcheck_score=_float(env, "MAX_RUGCHECK_SCORE", 30),
            min_lp_locked_pct=_float(env, "MIN_LP_LOCKED_PCT", 90),
            allow_token2022=_bool(env, "ALLOW_TOKEN2022", False),
            max_roundtrip_loss_pct=_float(env, "MAX_ROUNDTRIP_LOSS_PCT", 6),
            take_profit_pct=_float(env, "TAKE_PROFIT_PCT", 100),
            take_profit_sell_fraction=_float(env, "TAKE_PROFIT_SELL_FRACTION", 0.5),
            trailing_activate_pct=_float(env, "TRAILING_ACTIVATE_PCT", 30),
            trailing_stop_pct=_float(env, "TRAILING_STOP_PCT", 20),
            stop_loss_pct=_float(env, "STOP_LOSS_PCT", 25),
            max_hold_hours=_float(env, "MAX_HOLD_HOURS", 24),
            scan_interval_sec=_int(env, "SCAN_INTERVAL_SEC", 60),
            monitor_interval_sec=_int(env, "MONITOR_INTERVAL_SEC", 15),
            deep_checks_per_scan=_int(env, "DEEP_CHECKS_PER_SCAN", 5),
            reject_cooldown_min=_int(env, "REJECT_COOLDOWN_MIN", 20),
            rug_reject_cooldown_min=_int(env, "RUG_REJECT_COOLDOWN_MIN", 180),
            rebuy_cooldown_hours=_int(env, "REBUY_COOLDOWN_HOURS", 24),
        )

    def validate(self) -> list[str]:
        """Возвращает список ошибок конфигурации (пустой — всё в порядке)."""
        errors: list[str] = []
        if not self.telegram_token:
            errors.append("TELEGRAM_BOT_TOKEN не задан (получить у @BotFather)")
        if self.admin_chat_id == 0:
            errors.append("ADMIN_CHAT_ID не задан (свой id можно узнать у @userinfobot)")
        if self.mode not in {"paper", "live"}:
            errors.append("TRADING_MODE должен быть paper или live")
        if self.is_live and not self.wallet_private_key:
            errors.append("Для TRADING_MODE=live нужен WALLET_PRIVATE_KEY отдельного кошелька")
        if self.buy_amount_lamports <= 0:
            errors.append("BUY_AMOUNT_SOL должен быть больше 0")
        if self.max_open_positions < 1:
            errors.append("MAX_OPEN_POSITIONS должен быть не меньше 1")
        if not 0 < self.take_profit_sell_fraction <= 1:
            errors.append("TAKE_PROFIT_SELL_FRACTION должен быть в диапазоне (0, 1]")
        if not 0 < self.stop_loss_pct < 100:
            errors.append("STOP_LOSS_PCT должен быть в диапазоне (0, 100)")
        if not 0 < self.trailing_stop_pct < 100:
            errors.append("TRAILING_STOP_PCT должен быть в диапазоне (0, 100)")
        if self.priority_level not in {"medium", "high", "veryHigh"}:
            errors.append("PRIORITY_LEVEL: medium, high или veryHigh")
        for name, bps in (("BUY_SLIPPAGE_BPS", self.buy_slippage_bps), ("SELL_SLIPPAGE_BPS", self.sell_slippage_bps)):
            if not 1 <= bps <= 5000:
                errors.append(f"{name} должен быть от 1 до 5000 (это 0.01%–50%)")
        return errors
