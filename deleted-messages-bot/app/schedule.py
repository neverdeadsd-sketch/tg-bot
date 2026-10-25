from __future__ import annotations

from datetime import datetime, timedelta

from app.storage import utc_now

# Пары «возраст сообщения меньше чем» — «проверять раз в столько секунд».
# Почти все удаления приходятся на первые минуты после отправки: сразу жмут
# «удалить» из-за опечатки или передумав. Дальше интерес к сообщению падает,
# и частые проверки только жгут лимиты Telegram.
PROBE_LADDER: tuple[tuple[float | None, int], ...] = (
    (10 * 60, 45),
    (2 * 3600, 5 * 60),
    (24 * 3600, 30 * 60),
    (None, 3 * 3600),
)

# Задержка первой проверки: раньше смысла нет, сообщение только пришло.
FIRST_PROBE_DELAY = 45


def probe_interval(age_seconds: float) -> int:
    """Через сколько секунд проверять сообщение такого возраста."""

    age = max(age_seconds, 0.0)
    for limit, interval in PROBE_LADDER:
        if limit is None or age < limit:
            return interval
    return PROBE_LADDER[-1][1]


def next_probe_at(sent_at: datetime, now: datetime | None = None) -> datetime:
    """Когда проверять сообщение в следующий раз."""

    moment = now or utc_now()
    age = (moment - sent_at).total_seconds()
    return moment + timedelta(seconds=probe_interval(age))


def first_probe_at(sent_at: datetime, now: datetime | None = None) -> datetime:
    moment = now or utc_now()
    return max(moment, sent_at) + timedelta(seconds=FIRST_PROBE_DELAY)
