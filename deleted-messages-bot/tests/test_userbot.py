from types import SimpleNamespace

import userbot
from userbot import chat_type, describe_sender, media_kind, should_skip


def message(**over) -> SimpleNamespace:
    base = dict(is_private=False, is_group=False, is_channel=False)
    base.update(over)
    return SimpleNamespace(**base)


def test_тип_чата_различает_группу_и_супергруппу():
    # От этого зависит поиск удаления, пришедшего без указания чата.
    assert chat_type(message(is_private=True)) == "private"
    assert chat_type(message(is_group=True)) == "group"
    assert chat_type(message(is_group=True, is_channel=True)) == "supergroup"
    assert chat_type(message(is_channel=True)) == "channel"
    assert chat_type(message()) == "unknown"


def test_вложение_опознаётся_по_своему_типу():
    assert media_kind(message(photo=object())) == "photo"
    assert media_kind(message(document=object(), sticker=object())) == "sticker"
    assert media_kind(message(document=object(), gif=object())) == "animation"
    assert media_kind(message(document=object(), voice=object())) == "voice"
    assert media_kind(message(document=object())) == "document"
    assert media_kind(message()) is None


def test_имя_автора_собирается_из_частей():
    assert describe_sender(
        SimpleNamespace(id=1, first_name="Иван", last_name="Петров", username="ivan")
    ) == ("Иван Петров", "ivan")

    assert describe_sender(
        SimpleNamespace(id=2, first_name="Иван", last_name=None, username=None)
    ) == ("Иван", None)

    assert describe_sender(SimpleNamespace(id=3, title="Мой канал", username="chan")) == (
        "Мой канал",
        "chan",
    )

    assert describe_sender(None) == (None, None)


def test_архивный_чат_себя_не_архивирует():
    assert should_skip(-500, -500) is True
    assert should_skip(-100, -500) is False


def test_списки_чатов_учитываются(monkeypatch):
    monkeypatch.setattr(userbot, "IGNORE_CHATS", (-100,))
    assert should_skip(-100, None) is True

    monkeypatch.setattr(userbot, "IGNORE_CHATS", ())
    monkeypatch.setattr(userbot, "WATCH_CHATS", (-100,))
    assert should_skip(-100, None) is False
    assert should_skip(-200, None) is True
