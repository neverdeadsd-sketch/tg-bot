import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
)

from app.probe import Liveness, classify, probe_message


class FakeBot:
    """Заменяет Bot: запоминает вызов и отдаёт заданный ответ."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    async def edit_message_reply_markup(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return True


def bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=object(), message=text)


def test_сообщения_нет():
    assert classify("Bad Request: message to edit not found") is Liveness.DELETED
    assert classify("Bad Request: MESSAGE_ID_INVALID") is Liveness.DELETED


def test_сообщение_на_месте():
    assert classify("Bad Request: message can't be edited") is Liveness.ALIVE
    assert classify("Bad Request: message is not modified") is Liveness.ALIVE
    assert (
        classify("Bad Request: there is no reply markup in the message")
        is Liveness.ALIVE
    )


def test_чат_потерян():
    assert classify("Bad Request: chat not found") is Liveness.CHAT_LOST
    assert classify("Forbidden: bot was kicked from the supergroup chat") is Liveness.CHAT_LOST
    assert classify("Bad Request: not enough rights to manage messages") is Liveness.CHAT_LOST


def test_незнакомый_ответ_считается_живым_сообщением():
    # Ложное «удалено» хуже пропущенного удаления: отчёт уже не отозвать.
    assert classify("Bad Request: something brand new") is Liveness.UNKNOWN
    assert classify("") is Liveness.UNKNOWN
    assert classify(None) is Liveness.UNKNOWN


async def test_проверка_не_меняет_чужое_сообщение():
    bot = FakeBot(bad_request("Bad Request: message can't be edited"))
    assert await probe_message(bot, -100, 5) is Liveness.ALIVE
    # Клавиатура запрашивается пустой — Telegram такую правку чужого
    # сообщения отклоняет, менять там нечего.
    assert bot.calls == [{"chat_id": -100, "message_id": 5, "reply_markup": None}]


async def test_удалённое_сообщение_опознаётся():
    bot = FakeBot(bad_request("Bad Request: message to edit not found"))
    assert await probe_message(bot, -100, 5) is Liveness.DELETED


async def test_запрет_доступа_снимает_чат_с_проверки():
    bot = FakeBot(TelegramForbiddenError(method=object(), message="Forbidden"))
    assert await probe_message(bot, -100, 5) is Liveness.CHAT_LOST


async def test_не_найдено_без_подробностей_считается_потерей_чата():
    bot = FakeBot(TelegramNotFound(method=object(), message="Not Found"))
    assert await probe_message(bot, -100, 5) is Liveness.CHAT_LOST


async def test_сетевая_ошибка_ничего_не_решает():
    bot = FakeBot(TelegramNetworkError(method=object(), message="timeout"))
    assert await probe_message(bot, -100, 5) is Liveness.UNKNOWN


async def test_просьба_подождать_уходит_наружу():
    # Паузу держит сторож — он один знает про остальные проверки в очереди.
    bot = FakeBot(TelegramRetryAfter(method=object(), message="flood", retry_after=7))
    with pytest.raises(TelegramRetryAfter):
        await probe_message(bot, -100, 5)


async def test_успешная_правка_значит_сообщение_живо():
    assert await probe_message(FakeBot(), -100, 5) is Liveness.ALIVE
