from __future__ import annotations

import html
import json

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from app.storage import db, from_iso, utc_now
from app.utils.logger import logger
from config import (
    ADMIN_IDS,
    ARCHIVE_CHAT_ID,
    DOWNLOAD_MEDIA,
    KEEP_DAYS,
    PROBE_RATE,
    WATCH_HOURS,
)

router = Router(name="commands")

MESSAGE_LIMIT = 4000


class IsAdmin(BaseFilter):
    """Архив чужих сообщений открыт только тем, кто указан в ADMIN_IDS.

    Пустой список означает «никому»: лучше молчащие команды, чем бот, который
    по /recent показывает переписку любому желающему.
    """

    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        return bool(ADMIN_IDS) and user is not None and user.id in ADMIN_IDS


HELP_TEXT = """
🗃 <b>Архив удалённых сообщений</b>

Бот запоминает всё, что видит в чатах, и сообщает, когда сообщение исчезает.

<b>Команды</b>
/stats — сколько всего сохранено
/recent [N] — последние удалённые (по умолчанию 5)
/find текст — поиск по удалённым
/export [N] — выгрузка в JSON
/id — узнать id этого чата

<b>Как подключить чат</b>
1. Добавьте бота в группу.
2. У @BotFather: /setprivacy → Disable — иначе бот видит только команды.
3. В канал добавьте бота администратором.
""".strip()


def summary(row) -> str:
    deleted_at = from_iso(row["deleted_at"])
    stamp = deleted_at.strftime("%d.%m %H:%M") if deleted_at else "—"
    who = row["user_name"] or "канал"
    chat = row["chat_title"] or row["chat_id"]

    text = (row["text"] or "").strip()
    if not text:
        text = f"({row['content_type'] or 'без текста'})"
    if len(text) > 300:
        text = text[:300] + "…"

    return (
        f"🗑 <b>{stamp}</b> · {html.escape(str(chat))} · {html.escape(str(who))}\n"
        f"{html.escape(text)}"
    )


async def send_blocks(message: Message, title: str, blocks: list[str]) -> None:
    """Отправить список записей, укладываясь в лимит одного сообщения."""

    if not blocks:
        await message.answer(f"{title}\n\nПока пусто.")
        return

    current = title
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) > MESSAGE_LIMIT:
            await message.answer(current)
            current = block
        else:
            current = candidate

    if current:
        await message.answer(current)


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    user = message.from_user
    lines = [
        f"<b>Этот чат:</b> <code>{message.chat.id}</code>",
        f"<b>Тип:</b> {message.chat.type}",
    ]
    if user is not None:
        lines.append(f"<b>Вы:</b> <code>{user.id}</code>")
    lines.append("")
    lines.append("Этот id годится для ARCHIVE_CHAT_ID или WATCH_CHATS.")
    await message.answer("\n".join(lines))


@router.message(Command("start", "help"), IsAdmin(), F.chat.type == "private")
async def show_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("stats"), IsAdmin(), F.chat.type == "private")
async def show_stats(message: Message) -> None:
    numbers = await db.stats()
    archive = f"<code>{ARCHIVE_CHAT_ID}</code>" if ARCHIVE_CHAT_ID else "не задан"

    await message.answer(
        "📊 <b>Архив</b>\n\n"
        f"Сохранено сообщений: <b>{numbers['saved']}</b>\n"
        f"Из них удалено: <b>{numbers['deleted']}</b>\n"
        f"Под наблюдением сейчас: <b>{numbers['watched']}</b>\n"
        f"С правками: <b>{numbers['edited']}</b> (версий: {numbers['edits']})\n"
        f"Чатов: <b>{numbers['chats']}</b>\n\n"
        "⚙️ <b>Настройки</b>\n"
        f"Архивный чат: {archive}\n"
        f"Наблюдение: {WATCH_HOURS} ч после отправки\n"
        f"Частота проверок: {PROBE_RATE}/с\n"
        f"Вложения: {'скачиваются' if DOWNLOAD_MEDIA else 'только file_id'}\n"
        f"Хранение: {f'{KEEP_DAYS} дн.' if KEEP_DAYS else 'без ограничения'}"
    )


@router.message(Command("recent"), IsAdmin(), F.chat.type == "private")
async def show_recent(message: Message, command: CommandObject) -> None:
    limit = 5
    if command.args:
        try:
            limit = max(1, min(int(command.args.split()[0]), 20))
        except ValueError:
            pass

    rows = await db.recent_deleted(limit=limit)
    await send_blocks(
        message, f"🗑 <b>Последние удалённые: {len(rows)}</b>", [summary(r) for r in rows]
    )


@router.message(Command("find"), IsAdmin(), F.chat.type == "private")
async def find_deleted(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer("Что искать? Например: <code>/find договор</code>")
        return

    rows = await db.search_deleted(query, limit=15)
    await send_blocks(
        message,
        f"🔎 <b>Найдено по «{html.escape(query)}»: {len(rows)}</b>",
        [summary(r) for r in rows],
    )


@router.message(Command("export"), IsAdmin(), F.chat.type == "private")
async def export_deleted(message: Message, command: CommandObject) -> None:
    limit = 200
    if command.args:
        try:
            limit = max(1, min(int(command.args.split()[0]), 2000))
        except ValueError:
            pass

    rows = await db.recent_deleted(limit=limit)
    if not rows:
        await message.answer("Выгружать пока нечего.")
        return

    payload = []
    for row in rows:
        item = dict(row)
        # Приведённая копия текста нужна только поиску внутри базы.
        item.pop("text_lower", None)
        item["edits"] = [
            dict(edit)
            for edit in await db.edits_for(
                row["source"], row["chat_id"], row["message_id"]
            )
        ]
        payload.append(item)

    dump = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    name = f"deleted-{utc_now().strftime('%Y%m%d-%H%M%S')}.json"

    await message.answer_document(
        BufferedInputFile(dump, filename=name),
        caption=f"Выгружено записей: {len(payload)}",
    )
    logger.info(f"Выгрузка архива: {len(payload)} записей")
