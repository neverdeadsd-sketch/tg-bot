"""Конфигурация приложения: читается из .env, валидируется на старте."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
# override=True: файл проекта важнее переменных окружения. Иначе забытый в системе
# BOT_TOKEN от другого бота молча перебьёт .env, и запустится не тот бот.
ENV_LOADED = load_dotenv(ENV_PATH, override=True)


class ConfigError(RuntimeError):
    """Некорректная или неполная конфигурация."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должен быть целым числом, получено: {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError as exc:
        raise ConfigError(f"{name} должен быть числом, получено: {raw!r}") from exc


def _parse_admin_ids(raw: str | None) -> tuple[int, ...]:
    if not raw or not raw.strip():
        raise ConfigError("ADMIN_ID не задан. Укажите его в .env (см. .env.example).")
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_ID содержит не число: {chunk!r}") from exc
    if not ids:
        raise ConfigError("ADMIN_ID не содержит ни одного идентификатора.")
    return tuple(ids)


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    db_path: Path
    log_level: str
    max_orders_per_day: int
    throttle_callback: float
    throttle_message: float
    request_timeout: int
    orders_page_size: int

    @property
    def admin_id(self) -> int:
        """Основной админ (первый в списке)."""
        return self.admin_ids[0]

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


def load_config() -> Config:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан. Укажите его в .env (см. .env.example).")
    if ":" not in token:
        raise ConfigError("BOT_TOKEN выглядит некорректно: ожидается формат 123456:AA...")

    db_path = Path(os.getenv("DB_PATH") or "data/bot.db")
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_ID")),
        db_path=db_path,
        log_level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
        max_orders_per_day=_env_int("MAX_ORDERS_PER_DAY", 3),
        throttle_callback=_env_float("THROTTLE_CALLBACK", 0.4),
        throttle_message=_env_float("THROTTLE_MESSAGE", 0.5),
        request_timeout=_env_int("REQUEST_TIMEOUT", 60),
        orders_page_size=_env_int("ORDERS_PAGE_SIZE", 10),
    )


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
