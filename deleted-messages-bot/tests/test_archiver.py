from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import archiver
from app.archiver import build_record, describe_forward, should_skip

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def message(**over) -> SimpleNamespace:
    base = dict(
        message_id=10,
        chat=SimpleNamespace(id=-100, type="supergroup", title="Рабочий чат"),
        from_user=SimpleNamespace(id=7, full_name="Иван Петров", username="ivan"),
        content_type="text",
        text="привет",
        caption=None,
        reply_to_message=None,
        reply_markup=None,
        date=NOW,
        edit_date=None,
        forward_origin=None,
        sender_chat=None,
        photo=None,
        video=None,
        animation=None,
        audio=None,
        voice=None,
        video_note=None,
        sticker=None,
        document=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def чистые_настройки(monkeypatch):
    monkeypatch.setattr(archiver, "ARCHIVE_CHAT_ID", 0)
    monkeypatch.setattr(archiver, "IGNORE_CHATS", ())
    monkeypatch.setattr(archiver, "WATCH_CHATS", ())
    monkeypatch.setattr(archiver, "ARCHIVE_SERVICE_MESSAGES", False)


def test_обычное_сообщение_архивируется():
    assert should_skip(-100, 7, 999, "text") is False


def test_архивный_чат_себя_не_архивирует(monkeypatch):
    # Иначе бот следил бы за своими же отчётами и отчитывался о них снова.
    monkeypatch.setattr(archiver, "ARCHIVE_CHAT_ID", -500)
    assert should_skip(-500, 7, 999, "text") is True


def test_свои_сообщения_пропускаются():
    assert should_skip(-100, 999, 999, "text") is True


def test_чат_из_чёрного_списка(monkeypatch):
    monkeypatch.setattr(archiver, "IGNORE_CHATS", (-100,))
    assert should_skip(-100, 7, 999, "text") is True


def test_белый_список_отсекает_остальные(monkeypatch):
    monkeypatch.setattr(archiver, "WATCH_CHATS", (-100,))
    assert should_skip(-100, 7, 999, "text") is False
    assert should_skip(-200, 7, 999, "text") is True


def test_служебные_сообщения_не_архивируются(monkeypatch):
    # Их пачками чистят боты-уборщики — вышел бы поток пустых отчётов.
    assert should_skip(-100, 7, 999, "new_chat_members") is True
    assert should_skip(-100, 7, 999, "pinned_message") is True

    monkeypatch.setattr(archiver, "ARCHIVE_SERVICE_MESSAGES", True)
    assert should_skip(-100, 7, 999, "new_chat_members") is False


def test_запись_собирается_из_сообщения():
    record = build_record(message())

    assert record.chat_id == -100
    assert record.message_id == 10
    assert record.chat_title == "Рабочий чат"
    assert record.user_id == 7
    assert record.user_name == "Иван Петров"
    assert record.user_username == "ivan"
    assert record.text == "привет"
    assert record.sent_at == NOW
    assert record.has_markup is False


def test_подпись_идёт_в_текст():
    record = build_record(message(text=None, caption="подпись к фото", content_type="photo"))
    assert record.text == "подпись к фото"


def test_вложение_попадает_в_запись():
    photo = SimpleNamespace(file_id="AgAC", file_unique_id="uniq", file_size=2048)
    record = build_record(message(content_type="photo", text=None, photo=[photo]))

    assert record.media_file_id == "AgAC"
    assert record.media_unique_id == "uniq"
    assert record.media_type == "photo"


def test_сообщение_со_своей_клавиатурой_помечается():
    # Такие не проверяем: пустую клавиатуру Telegram снял бы по-настоящему.
    record = build_record(message(reply_markup=SimpleNamespace()))
    assert record.has_markup is True


def test_пост_канала_подписан_каналом():
    record = build_record(
        message(
            from_user=None,
            chat=SimpleNamespace(id=-100, type="channel", title="Мой канал"),
            sender_chat=SimpleNamespace(id=-100, title="Мой канал"),
        )
    )

    assert record.user_id is None
    assert record.user_name == "Мой канал"


def test_ответ_запоминается():
    record = build_record(message(reply_to_message=SimpleNamespace(message_id=5)))
    assert record.reply_to == 5


def test_источник_пересылки_читается():
    assert (
        describe_forward(
            message(
                forward_origin=SimpleNamespace(
                    type="user", sender_user=SimpleNamespace(id=1, full_name="Пётр")
                )
            )
        )
        == "Пётр"
    )
    assert (
        describe_forward(
            message(forward_origin=SimpleNamespace(type="hidden_user", sender_user_name="Скрытый"))
        )
        == "Скрытый"
    )
    assert (
        describe_forward(
            message(
                forward_origin=SimpleNamespace(
                    type="channel", chat=SimpleNamespace(id=-1, title="Канал"), message_id=3
                )
            )
        )
        == "Канал"
    )
    assert describe_forward(message()) is None


class FakeBot:
    def __init__(self, bot_id: int = 999) -> None:
        self.bot_id = bot_id

    async def me(self):
        return SimpleNamespace(id=self.bot_id, username="archive_bot")


@pytest.fixture
async def store(tmp_path, monkeypatch):
    from app import storage

    monkeypatch.setattr(storage, "MEDIA_DIR", tmp_path / "media")
    database = storage.Database(str(tmp_path / "archive.db"))
    await database.create_tables()
    monkeypatch.setattr(archiver, "db", database)
    monkeypatch.setattr(archiver, "DOWNLOAD_MEDIA", False)
    return database


async def test_сообщение_доходит_до_базы(store):
    assert await archiver._store(message(), FakeBot()) is True

    row = await store.get_message("bot", -100, 10)
    assert row is not None
    assert row["text"] == "привет"
    assert row["user_name"] == "Иван Петров"
    # Сообщение сразу встаёт в очередь на проверку.
    assert row["next_probe_at"] is not None


async def test_повторный_приём_не_создаёт_дубль(store):
    bot = FakeBot()
    assert await archiver._store(message(), bot) is True
    assert await archiver._store(message(), bot) is False


async def test_пропущенное_сообщение_в_базу_не_попадает(store, monkeypatch):
    monkeypatch.setattr(archiver, "IGNORE_CHATS", (-100,))

    assert await archiver._store(message(), FakeBot()) is False
    assert await store.get_message("bot", -100, 10) is None


async def test_правка_сохраняется_не_затирая_первую_версию(store):
    bot = FakeBot()
    await archiver.capture(message(), bot)
    await archiver.capture_edit(message(text="исправленный текст"), bot)

    row = await store.get_message("bot", -100, 10)
    assert row["text"] == "привет"

    edits = await store.edits_for("bot", -100, 10)
    assert [edit["text"] for edit in edits] == ["исправленный текст"]


async def test_правка_незнакомого_сообщения_сохраняется_как_сообщение(store):
    # Бота перезапустили, первой версии он не видел — записывать правку не к чему.
    await archiver.capture_edit(message(text="уже исправленное"), FakeBot())

    row = await store.get_message("bot", -100, 10)
    assert row is not None
    assert row["text"] == "уже исправленное"
    assert await store.edits_for("bot", -100, 10) == []


async def test_падение_архиватора_не_ломает_обработку(store, monkeypatch):
    # Обработчик ловит всё: иначе одно странное сообщение остановило бы поток.
    async def взрыв(*args, **kwargs):
        raise RuntimeError("что-то пошло не так")

    monkeypatch.setattr(archiver, "_store", взрыв)
    await archiver.capture(message(), FakeBot())
