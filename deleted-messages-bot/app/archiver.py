from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import Message

from app import media as media_tools
from app.schedule import first_probe_at
from app.storage import SOURCE_BOT, MessageRecord, db, utc_now
from app.utils.logger import logger
from config import (
    ARCHIVE_CHAT_ID,
    ARCHIVE_SERVICE_MESSAGES,
    DOWNLOAD_MEDIA,
    IGNORE_CHATS,
    WATCH_CHATS,
    WATCH_HOURS,
)

router = Router(name="archiver")

# Что считается сообщением человека. Всё остальное — служебные пометки вида
# «вошёл в группу»: их пачками чистят боты-уборщики, и каждая такая чистка
# превратилась бы в отчёт об удалении.
CONTENT_TYPES = frozenset(
    {
        "text",
        "photo",
        "video",
        "animation",
        "audio",
        "voice",
        "video_note",
        "document",
        "sticker",
        "contact",
        "location",
        "venue",
        "poll",
        "dice",
        "game",
        "story",
        "paid_media",
        "invoice",
    }
)


def should_skip(
    chat_id: int,
    user_id: int | None,
    bot_id: int | None,
    content_type: str | None,
) -> bool:
    if ARCHIVE_CHAT_ID and chat_id == ARCHIVE_CHAT_ID:
        # Архивный чат не архивируется, иначе бот следил бы за своими отчётами.
        return True
    if chat_id in IGNORE_CHATS:
        return True
    if WATCH_CHATS and chat_id not in WATCH_CHATS:
        return True
    if bot_id is not None and user_id == bot_id:
        return True
    if not ARCHIVE_SERVICE_MESSAGES and content_type not in CONTENT_TYPES:
        return True
    return False


def author_name(message: Message) -> str | None:
    user = message.from_user
    if user is not None:
        return user.full_name or user.username or str(user.id)
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is not None:
        return getattr(sender_chat, "title", None) or str(sender_chat.id)
    return None


def describe_forward(message: Message) -> str | None:
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None

    user = getattr(origin, "sender_user", None)
    if user is not None:
        return user.full_name or str(user.id)

    hidden = getattr(origin, "sender_user_name", None)
    if hidden:
        return str(hidden)

    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if chat is not None:
        return getattr(chat, "title", None) or str(chat.id)

    return getattr(origin, "type", None)


def build_record(message: Message, source: str = SOURCE_BOT) -> MessageRecord:
    chat = message.chat
    user = message.from_user
    found = media_tools.extract(message)
    reply = message.reply_to_message

    return MessageRecord(
        chat_id=chat.id,
        message_id=message.message_id,
        source=source,
        chat_title=getattr(chat, "title", None) or getattr(chat, "full_name", None),
        chat_type=getattr(chat, "type", None),
        user_id=user.id if user else None,
        user_name=author_name(message),
        user_username=user.username if user else None,
        content_type=message.content_type,
        text=message.text or message.caption,
        media_file_id=found.file_id if found else None,
        media_unique_id=found.unique_id if found else None,
        media_name=found.name if found else None,
        media_type=found.kind if found else None,
        reply_to=reply.message_id if reply else None,
        forward_from=describe_forward(message),
        # Снять клавиатуру со своего сообщения Telegram позволит, а проверка
        # живости как раз просит её снять. Такие сообщения не проверяем.
        has_markup=message.reply_markup is not None,
        sent_at=message.date or utc_now(),
    )


async def _store(message: Message, bot: Bot) -> bool:
    """Сохранить сообщение. False — пропущено или уже лежит в базе."""

    me = await bot.me()
    user = message.from_user

    if should_skip(message.chat.id, user.id if user else None, me.id, message.content_type):
        return False

    record = build_record(message)
    sent_at = record.sent_at or utc_now()
    inserted = await db.save_message(
        record, WATCH_HOURS, first_probe_at(sent_at)
    )

    if inserted and DOWNLOAD_MEDIA and record.media_file_id:
        found = media_tools.extract(message)
        if found is not None:
            path = await media_tools.download(bot, found)
            if path:
                await db.attach_media_path(
                    record.source, record.chat_id, record.message_id, path
                )

    return inserted


@router.message()
@router.channel_post()
async def capture(message: Message, bot: Bot) -> None:
    try:
        await _store(message, bot)
    except Exception:
        # Упавший архиватор не должен ронять обработку остальных сообщений.
        logger.exception("Не удалось сохранить сообщение")


@router.edited_message()
@router.edited_channel_post()
async def capture_edit(message: Message, bot: Bot) -> None:
    try:
        inserted = await _store(message, bot)
        if inserted:
            # Сообщение впервые увидели уже исправленным — первой версии
            # у нас нет, и записывать правку не к чему.
            return

        me = await bot.me()
        user = message.from_user
        if should_skip(
            message.chat.id, user.id if user else None, me.id, message.content_type
        ):
            return

        await db.record_edit(
            SOURCE_BOT,
            message.chat.id,
            message.message_id,
            message.text or message.caption,
            message.edit_date,
        )
    except Exception:
        logger.exception("Не удалось сохранить правку сообщения")
