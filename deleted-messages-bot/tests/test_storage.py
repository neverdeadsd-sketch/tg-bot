from datetime import datetime, timedelta, timezone

import pytest

from app import storage
from app.storage import SOURCE_BOT, SOURCE_USER, MessageRecord, to_iso

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_DIR", tmp_path / "media")
    database = storage.Database(str(tmp_path / "archive.db"))
    await database.create_tables()
    return database


def record(message_id: int = 1, chat_id: int = -100, **over) -> MessageRecord:
    base = dict(
        chat_id=chat_id,
        message_id=message_id,
        chat_title="Рабочий чат",
        chat_type="supergroup",
        user_id=7,
        user_name="Иван",
        user_username="ivan",
        content_type="text",
        text="привет",
        sent_at=NOW,
    )
    base.update(over)
    return MessageRecord(**base)


async def test_время_переживает_запись_и_чтение():
    assert storage.from_iso(to_iso(NOW)) == NOW
    assert storage.from_iso(None) is None
    assert storage.from_iso("не дата") is None


async def test_повторная_запись_не_создаёт_дубль(store):
    assert await store.save_message(record(), 48, NOW) is True
    assert await store.save_message(record(), 48, NOW) is False


async def test_повтор_не_оживляет_удалённое(store):
    await store.save_message(record(), 48, NOW)
    await store.mark_deleted(SOURCE_BOT, -100, 1, NOW)

    assert await store.save_message(record(), 48, NOW) is False

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["deleted_at"] is not None


async def test_проверка_ждёт_своего_времени(store):
    await store.save_message(record(), 48, NOW + timedelta(seconds=45))

    assert await store.due_probes(10, now=NOW) == []
    assert len(await store.due_probes(10, now=NOW + timedelta(seconds=60))) == 1


async def test_сообщение_со_своей_клавиатурой_не_проверяется(store):
    # Пустую клавиатуру Telegram снял бы по-настоящему, испортив сообщение.
    await store.save_message(record(has_markup=True), 48, NOW)
    assert await store.due_probes(10, now=NOW + timedelta(minutes=1)) == []


async def test_истёкшее_наблюдение_выпадает_из_очереди(store):
    await store.save_message(record(), 0, NOW)
    later = NOW + timedelta(minutes=1)

    assert await store.due_probes(10, now=later) == []
    assert await store.expire_watches(now=later) == 1

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["next_probe_at"] is None


async def test_перенос_проверки_считает_попытки(store):
    await store.save_message(record(), 48, NOW)
    await store.schedule_probe(SOURCE_BOT, -100, 1, NOW + timedelta(minutes=5))

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["probe_count"] == 1
    assert row["next_probe_at"] == to_iso(NOW + timedelta(minutes=5))


async def test_удаление_замечается_однажды(store):
    await store.save_message(record(), 48, NOW)

    assert await store.mark_deleted(SOURCE_BOT, -100, 1, NOW) is True
    # Второй раз отчёт отправлять не нужно.
    assert await store.mark_deleted(SOURCE_BOT, -100, 1, NOW) is False


async def test_отчёт_ждёт_отправки_до_подтверждения(store):
    await store.save_message(record(), 48, NOW)
    await store.mark_deleted(SOURCE_BOT, -100, 1, NOW)

    assert len(await store.pending_reports()) == 1

    await store.mark_reported(SOURCE_BOT, -100, 1)
    assert await store.pending_reports() == []


async def test_правки_хранятся_по_порядку_и_не_дублируются(store):
    await store.save_message(record(), 48, NOW)

    first = NOW + timedelta(minutes=1)
    second = NOW + timedelta(minutes=2)
    await store.record_edit(SOURCE_BOT, -100, 1, "второй вариант", first)
    await store.record_edit(SOURCE_BOT, -100, 1, "второй вариант", first)
    await store.record_edit(SOURCE_BOT, -100, 1, "третий вариант", second)

    edits = await store.edits_for(SOURCE_BOT, -100, 1)
    assert [e["text"] for e in edits] == ["второй вариант", "третий вариант"]

    row = await store.get_message(SOURCE_BOT, -100, 1)
    # Первая версия остаётся на месте — ради неё всё и затевалось.
    assert row["text"] == "привет"
    assert row["edited_at"] == to_iso(second)


async def test_поиск_только_по_удалённым(store):
    await store.save_message(record(1, text="секретный договор"), 48, NOW)
    await store.save_message(record(2, text="обычное сообщение"), 48, NOW)
    await store.mark_deleted(SOURCE_BOT, -100, 1, NOW)

    assert len(await store.search_deleted("ДОГОВОР")) == 1
    assert await store.search_deleted("обычное") == []


async def test_проценты_в_запросе_ищутся_как_текст(store):
    await store.save_message(record(1, text="скидка 50% на всё"), 48, NOW)
    await store.mark_deleted(SOURCE_BOT, -100, 1, NOW)

    assert len(await store.search_deleted("50%")) == 1
    assert await store.search_deleted("%_%") == []


async def test_потерянный_чат_снимается_с_проверки_целиком(store):
    await store.save_message(record(1), 48, NOW)
    await store.save_message(record(2), 48, NOW)
    await store.save_message(record(3, chat_id=-200), 48, NOW)

    assert await store.stop_probing_chat(-100) == 2
    assert len(await store.due_probes(10, now=NOW + timedelta(minutes=1))) == 1


async def test_удаление_в_личке_ищется_по_одному_id(store):
    # Такое удаление Telegram присылает userbot без указания чата.
    await store.save_message(
        record(555, chat_id=7, chat_type="private", source=SOURCE_USER), 48, NOW
    )
    await store.save_message(
        record(555, chat_id=-100, chat_type="supergroup", source=SOURCE_USER), 48, NOW
    )

    found = await store.find_without_chat(SOURCE_USER, 555)
    assert found is not None
    # Супергруппа нумеруется отдельно и в такой поиск попасть не должна.
    assert found["chat_id"] == 7

    assert await store.find_without_chat(SOURCE_USER, 999) is None


async def test_путь_к_вложению_дописывается(store):
    await store.save_message(record(media_file_id="AgAC", media_type="photo"), 48, NOW)
    await store.attach_media_path(SOURCE_BOT, -100, 1, "/data/media/x.jpg")

    row = await store.get_message(SOURCE_BOT, -100, 1)
    assert row["media_path"] == "/data/media/x.jpg"


async def test_сводка(store):
    await store.save_message(record(1), 48, NOW)
    await store.save_message(record(2, chat_id=-200), 48, NOW)
    await store.mark_deleted(SOURCE_BOT, -100, 1, NOW)
    await store.record_edit(SOURCE_BOT, -200, 2, "правка", NOW)

    numbers = await store.stats()
    assert numbers["saved"] == 2
    assert numbers["deleted"] == 1
    assert numbers["chats"] == 2
    assert numbers["edits"] == 1


async def test_чистка_уносит_и_правки(store):
    old = NOW - timedelta(days=40)
    await store.save_message(record(1, sent_at=old), 48, old)
    await store.record_edit(SOURCE_BOT, -100, 1, "старая правка", old)
    await store.save_message(record(2), 48, NOW)

    assert await store.purge_older_than(30) == 1
    assert await store.get_message(SOURCE_BOT, -100, 1) is None
    assert await store.edits_for(SOURCE_BOT, -100, 1) == []
    assert await store.get_message(SOURCE_BOT, -100, 2) is not None


async def test_нулевой_срок_хранения_ничего_не_удаляет(store):
    await store.save_message(record(1, sent_at=NOW - timedelta(days=400)), 48, NOW)
    assert await store.purge_older_than(0) == 0
    assert await store.get_message(SOURCE_BOT, -100, 1) is not None


async def test_поиск_не_зависит_от_регистра_в_кириллице(store):
    # lower() внутри SQLite кириллицу не трогает, поэтому приведённую копию
    # текста считает Python.
    await store.save_message(record(1, text="Договор на Поставку"), 48, NOW)
    await store.mark_deleted(SOURCE_BOT, -100, 1, NOW)

    for query in ("договор", "ДОГОВОР", "ДоГоВоР", "поставку"):
        assert len(await store.search_deleted(query)) == 1, query
