from datetime import datetime, timedelta, timezone

from app.schedule import (
    FIRST_PROBE_DELAY,
    PROBE_LADDER,
    first_probe_at,
    next_probe_at,
    probe_interval,
)


def test_молодое_сообщение_проверяется_часто():
    assert probe_interval(0) == 45
    assert probe_interval(9 * 60) == 45


def test_интервал_растёт_вместе_с_возрастом():
    intervals = [probe_interval(age) for age in (0, 11 * 60, 3 * 3600, 5 * 86400)]
    assert intervals == sorted(intervals)
    assert intervals == [45, 300, 1800, 10800]


def test_границы_лестницы_не_проваливаются():
    for limit, interval in PROBE_LADDER:
        if limit is None:
            continue
        assert probe_interval(limit - 1) == interval
        assert probe_interval(limit) != interval or interval == PROBE_LADDER[-1][1]


def test_отрицательный_возраст_не_ломает_расчёт():
    # Часы сервера могут отстать от времени, которое прислал Telegram.
    assert probe_interval(-120) == 45


def test_следующая_проверка_в_будущем():
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    sent = now - timedelta(minutes=1)
    assert next_probe_at(sent, now) == now + timedelta(seconds=45)


def test_первая_проверка_не_раньше_отправки():
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    # Сообщение из будущего: время на сервере Telegram опережает наше.
    sent = now + timedelta(seconds=30)
    assert first_probe_at(sent, now) == sent + timedelta(seconds=FIRST_PROBE_DELAY)
