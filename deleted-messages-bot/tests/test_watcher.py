from datetime import timedelta
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app import reporter, storage, watcher
from app.limiter import RateLimiter
from app.storage import SOURCE_BOT, MessageRecord, utc_now

ARCHIVE = -555


def bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=object(), message=text)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeBot:
    """Отвечает на проверки заранее заданным исходом и копит отправленное."""

    def __init__(self, outcomes: dict[int, object] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.sent: list[tuple[int, str]] = []
        self.media: list[tuple[int, object]] = []
        self.send_error: Exception | None = None

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        outcome = self.outcomes.get(message_id, "alive")
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "deleted":
            raise bad_request("Bad Request: message to edit not found")
        if outcome == "chat_lost":
            raise bad_request("Bad Request: chat not found")
        raise bad_request("Bad Request: message can't be edited")

    async def send_message(self, chat_id, text, **kwargs):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.media.append((chat_id, photo))
        return SimpleNamespace(message_id=0)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_DIR", tmp_path / "media")
    database = storage.Database(str(tmp_path / "archive.db"))
    await database.create_tables()
    monkeypatch.setattr(watcher, "db", database)
    monkeypatch.setattr(reporter, "ARCHIVE_CHAT_ID", ARCHIVE)
    return database


@pytest.fixture
def limiter():
    clock = Clock()
    return RateLimiter(rate=50, burst=50, clock=clock, sleep=clock.sleep)


async def save(store, message_id: int, chat_id: int = -100, **over) -> None:
    """Сохранить сообщение так, чтобы проверка была уже просрочена."""

    now = utc_now()
    base = dict(
        chat_id=chat_id,
        message_id=message_id,
        chat_title="Рабочий чат",
        chat_type="supergroup",
        user_id=7,
        user_name="Иван",
        user_username="ivan",
        content_type="text",
        text=f"сообщение {message_id}",
        sent_at=now - timedelta(minutes=1),
    )
    base.update(over)
    await store.save_message(MessageRecord(**base), 48, now - timedelta(seconds=30))


async def test_удаление_замечено_и_отчёт_ушёл(store, limiter):
    await save(store, 1)
    bot = FakeBot({1: "deleted"})

    assert await watcher._probe_due(bot, limiter) == 1
    await watcher._flush_reports(bot)

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["deleted_at"] is not None
    assert row["reported_at"] is not None

    assert len(bot.sent) == 1
    target, text = bot.sent[0]
    assert target == ARCHIVE
    assert "Удалённое сообщение" in text
    assert "сообщение 1" in text


async def test_живое_сообщение_остаётся_в_очереди(store, limiter):
    await save(store, 1)
    bot = FakeBot({1: "alive"})

    await watcher._probe_due(bot, limiter)

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["deleted_at"] is None
    assert row["probe_count"] == 1
    # Проверка перенесена вперёд, сообщение из наблюдения не выпало.
    assert row["next_probe_at"] > storage.to_iso(utc_now())


async def test_об_одном_удалении_отчитываются_один_раз(store, limiter):
    await save(store, 1)
    bot = FakeBot({1: "deleted"})

    await watcher._probe_due(bot, limiter)
    await watcher._flush_reports(bot)
    await watcher._probe_due(bot, limiter)
    await watcher._flush_reports(bot)

    assert len(bot.sent) == 1


async def test_потерянный_чат_снимается_целиком(store, limiter):
    await save(store, 1)
    await save(store, 2)
    await save(store, 3, chat_id=-200)
    bot = FakeBot({1: "chat_lost"})

    await watcher._probe_due(bot, limiter)

    # Первая же неудача снимает с проверки весь чат, а не одно сообщение.
    for message_id in (1, 2):
        row = await store.get_message(SOURCE_BOT, -100, message_id)
        assert row["next_probe_at"] is None

    other = await store.get_message(SOURCE_BOT, -200, 3)
    assert other["next_probe_at"] is not None


async def test_просьба_подождать_прерывает_пачку(store, limiter):
    await save(store, 1)
    await save(store, 2)
    bot = FakeBot(
        {1: TelegramRetryAfter(method=object(), message="flood", retry_after=30)}
    )

    assert await watcher._probe_due(bot, limiter) == 0
    # Пауза общая: следующие проверки тоже подождут.
    assert limiter.paused_for > 30

    # Ни одно сообщение не потеряно — оба снова в очереди.
    assert len(await store.due_probes(10)) == 2


async def test_неотправленный_отчёт_пробуют_снова(store, limiter):
    await save(store, 1)
    bot = FakeBot({1: "deleted"})
    bot.send_error = bad_request("Bad Request: chat not found")

    await watcher._probe_due(bot, limiter)
    await watcher._flush_reports(bot)

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["deleted_at"] is not None
    # Отчёт не доставлен — значит и не отмечен отправленным.
    assert row["reported_at"] is None
    assert len(await store.pending_reports()) == 1

    bot.send_error = None
    await watcher._flush_reports(bot)

    assert len(bot.sent) == 1
    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["reported_at"] is not None


async def test_вложение_уходит_вслед_за_отчётом(store, limiter):
    await save(store, 1, content_type="photo", media_file_id="AgAC", media_type="photo")
    bot = FakeBot({1: "deleted"})

    await watcher._probe_due(bot, limiter)
    await watcher._flush_reports(bot)

    assert bot.media == [(ARCHIVE, "AgAC")]


async def test_правки_попадают_в_отчёт(store, limiter):
    await save(store, 1)
    await store.record_edit(SOURCE_BOT, -100, 1, "исправленный текст", utc_now())
    bot = FakeBot({1: "deleted"})

    await watcher._probe_due(bot, limiter)
    await watcher._flush_reports(bot)

    joined = "\n".join(text for _, text in bot.sent)
    assert "исправленный текст" in joined


async def test_без_архивного_чата_отчёт_остаётся_в_базе(store, limiter, monkeypatch):
    monkeypatch.setattr(reporter, "ARCHIVE_CHAT_ID", 0)
    await save(store, 1)
    bot = FakeBot({1: "deleted"})

    await watcher._probe_due(bot, limiter)
    await watcher._flush_reports(bot)

    assert bot.sent == []
    row = await store.get_message(SOURCE_BOT, -100, 1)
    # Запись помечена обработанной: достать её можно командой /recent.
    assert row["deleted_at"] is not None
    assert row["reported_at"] is not None


async def test_недоступный_чат_не_опрашивается_повторно_в_пачке(store, limiter):
    for message_id in (1, 2, 3):
        await save(store, message_id)
    await save(store, 4, chat_id=-200)

    bot = FakeBot({1: "chat_lost"})
    # Три сообщения мёртвого чата — один запрос вместо трёх, плюс живой чат.
    assert await watcher._probe_due(bot, limiter) == 2
