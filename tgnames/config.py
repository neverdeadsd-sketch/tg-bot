"""Configuration: TOML file overlaid with environment variables."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULT_CONFIG_PATHS = ("config.toml", "config.example.toml")


@dataclass
class TelegramConfig:
    api_id: int = 0
    api_hash: str = ""
    phone: str = ""
    session: str = "sessions/tgnames"


@dataclass
class LimitsConfig:
    # Availability probing: cheap, but still an API call.
    checks_per_minute: float = 20.0
    checks_per_hour: int = 400
    checks_per_day: int = 3000
    # Channel creation: heavily restricted by Telegram. Keep this low.
    claims_per_hour: int = 5
    claims_per_day: int = 20
    # A FloodWait longer than this aborts the run instead of sleeping.
    max_floodwait_seconds: int = 300
    # Pause between claims, on top of the quotas (seconds).
    claim_cooldown_seconds: float = 45.0


@dataclass
class ChannelConfig:
    """How the holding channel is created for a claimed username."""

    title_template: str = "@{username}"
    about_template: str = "Reserved."
    # Keep the channel private-but-named? Telegram requires a public username
    # here, so the channel is public by definition; this only controls whether
    # we leave a description behind.
    delete_on_failure: bool = True


@dataclass
class SelectionConfig:
    min_score: float = 60.0
    # Never touch handles carrying these tags.
    exclude_tags: list[str] = field(
        default_factory=lambda: [
            "reserved", "reserved-part", "risky", "noise", "likely-reserved",
        ]
    )


@dataclass
class Config:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    db: str = "data/tgnames.db"

    def as_dict(self) -> dict:
        return asdict(self)

    def validate_credentials(self) -> None:
        if not self.telegram.api_id or not self.telegram.api_hash:
            raise SystemExit(
                "Telegram credentials are missing.\n"
                "Get api_id/api_hash at https://my.telegram.org (API development tools), then\n"
                "either export TG_API_ID / TG_API_HASH or fill in config.toml."
            )


def _merge(dc, data: dict):
    for key, value in (data or {}).items():
        if hasattr(dc, key):
            setattr(dc, key, value)
    return dc


def load(path: str | None = None) -> Config:
    cfg = Config()

    chosen = None
    if path:
        chosen = Path(path)
        if not chosen.exists():
            raise SystemExit(f"config file not found: {path}")
    else:
        for candidate in DEFAULT_CONFIG_PATHS:
            if Path(candidate).exists():
                chosen = Path(candidate)
                break

    if chosen:
        raw = tomllib.loads(chosen.read_text(encoding="utf-8"))
        _merge(cfg.telegram, raw.get("telegram"))
        _merge(cfg.limits, raw.get("limits"))
        _merge(cfg.channel, raw.get("channel"))
        _merge(cfg.selection, raw.get("selection"))
        if "db" in raw:
            cfg.db = raw["db"]

    # .env-style variables win over the file.
    _load_dotenv()
    if os.getenv("TG_API_ID"):
        cfg.telegram.api_id = int(os.environ["TG_API_ID"])
    if os.getenv("TG_API_HASH"):
        cfg.telegram.api_hash = os.environ["TG_API_HASH"]
    if os.getenv("TG_PHONE"):
        cfg.telegram.phone = os.environ["TG_PHONE"]
    if os.getenv("TG_SESSION"):
        cfg.telegram.session = os.environ["TG_SESSION"]
    if os.getenv("TGNAMES_DB"):
        cfg.db = os.environ["TGNAMES_DB"]
    return cfg


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env reader — avoids a dependency on python-dotenv."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)
