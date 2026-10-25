from __future__ import annotations

from enum import Enum

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)


class Liveness(str, Enum):
    ALIVE = "alive"
    DELETED = "deleted"
    UNKNOWN = "unknown"
    CHAT_LOST = "chat_lost"


# Сообщения нет: Telegram не нашёл, что править.
_DELETED_MARKERS = (
    "message to edit not found",
    "message_id_invalid",
    "message id invalid",
)

# Сообщение на месте, править его боту просто не дают — чужое.
_ALIVE_MARKERS = (
    "message can't be edited",
    "message cannot be edited",
    "message is not modified",
    "there is no reply markup in the message",
    "message can't be copied",
)

# Чат недоступен целиком: проверять в нём больше нечего.
_CHAT_LOST_MARKERS = (
    "chat not found",
    "bot was kicked",
    "bot is not a member",
    "bot was blocked by the user",
    "user is deactivated",
    "peer_id_invalid",
    "chat_write_forbidden",
    "not enough rights",
    "need administrator rights",
    "group chat was upgraded",
)


def classify(error_text: str | None) -> Liveness:
    """Разобрать ответ Telegram на попытку правки.

    Неизвестный ответ считается живым сообщением: ложное «удалено» хуже
    пропущенного удаления — отчёт о сообщении, которое никто не удалял, сбивает
    с толку и его уже не отозвать.
    """

    text = (error_text or "").lower()
    if not text:
        return Liveness.UNKNOWN

    for marker in _DELETED_MARKERS:
        if marker in text:
            return Liveness.DELETED
    for marker in _ALIVE_MARKERS:
        if marker in text:
            return Liveness.ALIVE
    for marker in _CHAT_LOST_MARKERS:
        if marker in text:
            return Liveness.CHAT_LOST
    return Liveness.UNKNOWN


async def probe_message(bot: Bot, chat_id: int, message_id: int) -> Liveness:
    """Жив ли ещё этот message_id.

    Bot API не сообщает об удалениях, поэтому спрашиваем окольно: просим
    Telegram снять клавиатуру с чужого сообщения. Снять её боту не позволят
    никогда, но ответ на запрос различается — «нельзя править» у живого
    сообщения и «не найдено» у удалённого. Чужое сообщение при этом не меняется.

    Сообщения со своей клавиатурой сюда не попадают: их отбирает архиватор,
    потому что такую правку Telegram бы выполнил.
    """

    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except TelegramRetryAfter:
        # Сторож сам выдержит паузу и вернётся к этому сообщению.
        raise
    except TelegramBadRequest as error:
        return classify(error.message)
    except TelegramNotFound as error:
        verdict = classify(error.message)
        return Liveness.CHAT_LOST if verdict is Liveness.UNKNOWN else verdict
    except TelegramForbiddenError:
        return Liveness.CHAT_LOST
    except (TelegramNetworkError, TelegramServerError):
        return Liveness.UNKNOWN
    except TelegramAPIError:
        return Liveness.UNKNOWN

    # Правка прошла — сообщение на месте, но трогать его больше нельзя.
    return Liveness.ALIVE
