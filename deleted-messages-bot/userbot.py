"""Режим 2: наблюдение с аккаунта пользователя.

Bot API об удалениях не сообщает, поэтому обычный бот узнаёт о них, переспрашивая
Telegram (см. app/probe.py). Протокол MTProto, на котором работают обычные
клиенты, присылает удаления сам и сразу — но для этого нужен вход в аккаунт, а не
токен бота. Этот режим ловит удаления во всех чатах аккаунта, включая личные,
и пишет в ту же базу, что и бот.

Запуск:
    pip install -r requirements-userbot.txt
    python userbot.py

Файл сессии равнозначен паролю от аккаунта: он остаётся в DATA_DIR и в
репозиторий не попадает.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app import reporter
from app.storage import SOURCE_USER, MessageRecord, db, utc_now
from app.utils.logger import logger
from config import (
    ARCHIVE_CHAT_ID,
    DOWNLOAD_MEDIA,
    IGNORE_CHATS,
    MAX_DOWNLOAD_MB,
    MEDIA_DIR,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    USERBOT_SESSION,
    WATCH_CHATS,
    WATCH_HOURS,
)

try:
    from telethon import TelegramClient, events, utils

    TELETHON_READY = True
except ImportError:  # pragma: no cover - проверяется при запуске
    TelegramClient = None  # type: ignore[assignment]
    events = None  # type: ignore[assignment]
    utils = None  # type: ignore[assignment]
    TELETHON_READY = False


def chat_type(message) -> str:
    """Тип чата в тех же словах, что у Bot API.

    Важно не перепутать супергруппу с обычной группой: удаление в личке и в
    старой группе приходит без указания чата и ищется по одному id, а каналы и
    супергруппы нумеруются отдельно и в такой поиск попадать не должны.
    """

    if getattr(message, "is_private", False):
        return "private"
    if getattr(message, "is_group", False):
        return "supergroup" if getattr(message, "is_channel", False) else "group"
    if getattr(message, "is_channel", False):
        return "channel"
    return "unknown"


def media_kind(message) -> str | None:
    """Чем является вложение. Порядок важен: гифка и стикер — тоже документы."""

    if getattr(message, "photo", None):
        return "photo"
    for attribute, kind in (
        ("video_note", "video_note"),
        ("voice", "voice"),
        ("gif", "animation"),
        ("sticker", "sticker"),
        ("video", "video"),
        ("audio", "audio"),
        ("document", "document"),
    ):
        if getattr(message, attribute, None):
            return kind
    return None


def describe_sender(sender) -> tuple[str | None, str | None]:
    if sender is None:
        return None, None

    username = getattr(sender, "username", None)
    title = getattr(sender, "title", None)
    if title:
        return title, username

    parts = [
        getattr(sender, "first_name", None) or "",
        getattr(sender, "last_name", None) or "",
    ]
    name = " ".join(part for part in parts if part).strip()
    return name or username or str(getattr(sender, "id", "")), username


def should_skip(chat_id: int, archive_chat_id: int | None) -> bool:
    if archive_chat_id is not None and chat_id == archive_chat_id:
        # Иначе клиент архивировал бы собственные отчёты.
        return True
    if chat_id in IGNORE_CHATS:
        return True
    if WATCH_CHATS and chat_id not in WATCH_CHATS:
        return True
    return False


async def build_record(message) -> MessageRecord:
    sender = None
    try:
        sender = await message.get_sender()
    except Exception:
        # Автор мог удалить аккаунт — запись всё равно нужна.
        logger.debug("Не удалось получить автора сообщения")

    name, username = describe_sender(sender)
    chat_title = None
    try:
        chat = await message.get_chat()
        chat_title = getattr(chat, "title", None) or describe_sender(chat)[0]
    except Exception:
        logger.debug("Не удалось получить название чата")

    kind = media_kind(message)
    reply_to = getattr(message, "reply_to_msg_id", None)

    return MessageRecord(
        chat_id=message.chat_id,
        message_id=message.id,
        source=SOURCE_USER,
        chat_title=chat_title,
        chat_type=chat_type(message),
        user_id=getattr(sender, "id", None),
        user_name=name,
        user_username=username,
        content_type=kind or "text",
        text=message.message or None,
        media_type=kind,
        reply_to=reply_to,
        forward_from=_describe_forward(message),
        sent_at=message.date or utc_now(),
    )


def _describe_forward(message) -> str | None:
    forward = getattr(message, "forward", None)
    if forward is None:
        return None

    for attribute in ("from_name", "chat", "sender"):
        value = getattr(forward, attribute, None)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            return describe_sender(value)[0]
    return None


async def save_media(message, record: MessageRecord) -> str | None:
    if not DOWNLOAD_MEDIA or record.media_type is None:
        return None

    size = getattr(getattr(message, "file", None), "size", None)
    if size and size > MAX_DOWNLOAD_MB * 1024 * 1024:
        logger.info(
            f"Вложение {record.media_type} больше {MAX_DOWNLOAD_MB} МБ — не скачиваю"
        )
        return None

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    extension = getattr(getattr(message, "file", None), "ext", None) or ""
    target = MEDIA_DIR / f"u{abs(record.chat_id)}-{record.message_id}{extension}"

    try:
        saved = await message.download_media(file=str(target))
    except Exception as error:
        logger.warning(f"Вложение не скачалось: {error}")
        return None

    return str(saved) if saved else None


async def report(client, row, target) -> None:
    edits = await db.edits_for(SOURCE_USER, row["chat_id"], row["message_id"])

    for chunk in reporter.render(row, edits):
        await client.send_message(target, chunk, parse_mode="html", link_preview=False)

    path = row["media_path"]
    if path and Path(path).exists():
        try:
            await client.send_file(target, path)
        except Exception as error:
            logger.warning(f"Вложение не отправилось: {error}")

    await db.mark_reported(SOURCE_USER, row["chat_id"], row["message_id"])


async def main() -> None:
    logger.info("===================================")
    logger.info("👤 Запуск наблюдения с аккаунта...")
    logger.info("===================================")

    if not TELETHON_READY:
        logger.error(
            "❌ Нет библиотеки telethon. Установите: "
            "pip install -r requirements-userbot.txt"
        )
        return

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        logger.error(
            "❌ Нужны TELEGRAM_API_ID и TELEGRAM_API_HASH — их выдают на "
            "my.telegram.org → API development tools"
        )
        return

    await db.create_tables()
    logger.info("✅ База данных готова")

    Path(USERBOT_SESSION).expanduser().parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(USERBOT_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    await client.start()
    me = await client.get_me()
    logger.success(f"✅ Вход выполнен: {describe_sender(me)[0]}")

    # Без архивного чата отчёты уходят в «Избранное» — оно всегда под рукой.
    target = ARCHIVE_CHAT_ID or "me"
    try:
        archive_chat_id = utils.get_peer_id(await client.get_entity(target))
    except Exception as error:
        logger.error(f"❌ Архивный чат недоступен: {error}")
        await client.disconnect()
        return

    logger.info(f"📨 Отчёты пойдут в чат {archive_chat_id}")

    @client.on(events.NewMessage)
    async def on_new_message(event) -> None:
        try:
            if should_skip(event.chat_id, archive_chat_id):
                return

            record = await build_record(event.message)
            inserted = await db.save_message(record, WATCH_HOURS, None)
            if not inserted:
                return

            path = await save_media(event.message, record)
            if path:
                await db.attach_media_path(
                    SOURCE_USER, record.chat_id, record.message_id, path
                )
        except Exception:
            logger.exception("Не удалось сохранить сообщение")

    @client.on(events.MessageEdited)
    async def on_edited_message(event) -> None:
        try:
            if should_skip(event.chat_id, archive_chat_id):
                return

            record = await build_record(event.message)
            inserted = await db.save_message(record, WATCH_HOURS, None)
            if inserted:
                # Первую версию мы не видели — записывать правку не к чему.
                return

            await db.record_edit(
                SOURCE_USER,
                event.chat_id,
                event.message.id,
                event.message.message or None,
                event.message.edit_date or utc_now(),
            )
        except Exception:
            logger.exception("Не удалось сохранить правку сообщения")

    @client.on(events.MessageDeleted)
    async def on_deleted_message(event) -> None:
        moment = utc_now()
        for message_id in event.deleted_ids:
            try:
                if event.chat_id is not None:
                    row = await db.get_message(SOURCE_USER, event.chat_id, message_id)
                else:
                    # В личке и старых группах Telegram не называет чат:
                    # ищем сообщение по одному его номеру.
                    row = await db.find_without_chat(SOURCE_USER, message_id)

                if row is None:
                    continue

                chat_id = row["chat_id"]
                if not await db.mark_deleted(SOURCE_USER, chat_id, message_id, moment):
                    continue

                logger.info(f"🗑 Удалено сообщение {message_id} в чате {chat_id}")

                fresh = await db.get_message(SOURCE_USER, chat_id, message_id)
                if fresh is not None:
                    await report(client, fresh, archive_chat_id)
            except Exception:
                logger.exception("Не удалось обработать удаление")

    logger.success("✅ Слежу за удалениями. Остановить — Ctrl+C")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка по требованию пользователя")
