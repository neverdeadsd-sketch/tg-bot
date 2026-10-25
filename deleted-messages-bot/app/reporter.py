from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import FSInputFile, LinkPreviewOptions

from app.storage import SOURCE_USER, from_iso
from app.utils.logger import logger
from config import ARCHIVE_CHAT_ID

TEXT_LIMIT = 4096

# Сколько прошлых версий текста показывать: больше — и отчёт перестают читать.
MAX_EDITS_SHOWN = 5

_SEND_METHOD = {
    "photo": "send_photo",
    "video": "send_video",
    "animation": "send_animation",
    "audio": "send_audio",
    "voice": "send_voice",
    "video_note": "send_video_note",
    "sticker": "send_sticker",
    "document": "send_document",
}

_KIND_NAMES = {
    "photo": "фото",
    "video": "видео",
    "animation": "GIF",
    "audio": "аудио",
    "voice": "голосовое",
    "video_note": "видеосообщение",
    "sticker": "стикер",
    "document": "файл",
}

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def human_delta(seconds: float) -> str:
    total = int(max(seconds, 0))
    if total < 60:
        return f"{total} с"

    minutes = total // 60
    if minutes < 60:
        return f"{minutes} мин"

    hours = minutes // 60
    if hours < 24:
        rest = minutes % 60
        return f"{hours} ч {rest} мин" if rest else f"{hours} ч"

    days = hours // 24
    rest_hours = hours % 24
    return f"{days} д {rest_hours} ч" if rest_hours else f"{days} д"


def format_moment(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    return moment.strftime("%d.%m.%Y %H:%M:%S UTC")


def describe_chat(row) -> str:
    title = row["chat_title"]
    chat_id = row["chat_id"]
    if title:
        return f"{html.escape(str(title))} (<code>{chat_id}</code>)"
    return f"<code>{chat_id}</code>"


def describe_author(row) -> str:
    name = row["user_name"]
    username = row["user_username"]
    user_id = row["user_id"]

    if not any((name, username, user_id)):
        # У постов в канале автора нет — подписывает сам канал.
        return "канал"

    parts: list[str] = []
    if name:
        parts.append(html.escape(str(name)))
    tail: list[str] = []
    if username:
        tail.append(f"@{html.escape(str(username))}")
    if user_id:
        tail.append(f"<code>{user_id}</code>")
    if tail:
        parts.append("(" + ", ".join(tail) + ")")
    return " ".join(parts)


def _media_note(row) -> str | None:
    kind = row["media_type"]
    if not kind:
        return None

    label = _KIND_NAMES.get(kind, str(kind))
    name = row["media_name"]
    suffix = f" — {html.escape(str(name))}" if name else ""

    if row["media_path"]:
        return f"<b>Вложение:</b> {label}{suffix} (файл сохранён)"
    if row["media_file_id"]:
        return f"<b>Вложение:</b> {label}{suffix} (только ссылка Telegram)"
    return None


def _safe_cut(text: str, limit: int) -> int:
    """Где разрезать текст, чтобы не разорвать мнемонику вроде &quot;."""

    if len(text) <= limit:
        return len(text)

    cut = text.rfind("\n", 0, limit + 1)
    if cut <= 0:
        cut = limit

    # Мнемоника не длиннее десятка символов: если резать пришлось внутри неё,
    # отступаем к её началу.
    amp = text.rfind("&", max(0, cut - 12), cut)
    if amp != -1 and ";" not in text[amp:cut]:
        cut = amp

    return max(cut, 1)


def _chunks(header: str, body: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Собрать сообщения не длиннее лимита Telegram.

    Теги живут только в заголовке, тело — экранированный текст без разметки,
    поэтому разрез по телу не может оставить незакрытый тег.
    """

    head = header.rstrip()[:limit]
    if not body:
        return [head]

    out: list[str] = []
    budget = limit - len(head) - 2

    if budget < 200:
        # Заголовок занял почти всё сообщение — текст пойдёт следующим.
        out.append(head)
        rest = body
    else:
        cut = _safe_cut(body, budget)
        out.append(f"{head}\n\n{body[:cut]}")
        rest = body[cut:]

    while rest:
        rest = rest.lstrip("\n")
        if not rest:
            break
        cut = _safe_cut(rest, limit)
        out.append(rest[:cut])
        rest = rest[cut:]

    return out


def render(row, edits: Sequence = ()) -> list[str]:
    """Отчёт об удалённом сообщении, нарезанный под лимит Telegram."""

    sent_at = from_iso(row["sent_at"])
    deleted_at = from_iso(row["deleted_at"])

    lines = ["🗑 <b>Удалённое сообщение</b>", ""]
    lines.append(f"<b>Чат:</b> {describe_chat(row)}")
    lines.append(f"<b>Автор:</b> {describe_author(row)}")
    lines.append(f"<b>Отправлено:</b> {format_moment(sent_at)}")

    if deleted_at:
        tail = ""
        if sent_at:
            delta = human_delta((deleted_at - sent_at).total_seconds())
            tail = f" (через {delta} после отправки)"
        # Bot API об удалениях не сообщает: бот замечает пропажу при очередной
        # проверке, так что это время обнаружения, а не самого удаления. У
        # наблюдения с аккаунта время точное — его присылает Telegram.
        label = "Удалено" if row["source"] == SOURCE_USER else "Замечено удалённым"
        lines.append(f"<b>{label}:</b> {format_moment(deleted_at)}{tail}")

    content_type = row["content_type"]
    if content_type and content_type != "text":
        lines.append(f"<b>Тип:</b> {html.escape(str(content_type))}")

    if row["reply_to"]:
        lines.append(f"<b>Ответ на сообщение:</b> <code>{row['reply_to']}</code>")

    if row["forward_from"]:
        lines.append(f"<b>Переслано от:</b> {html.escape(str(row['forward_from']))}")

    note = _media_note(row)
    if note:
        lines.append(note)

    lines.append(f"<b>id сообщения:</b> <code>{row['message_id']}</code>")

    text = row["text"]
    if not text:
        lines.append("")
        lines.append("<i>Текста в сообщении не было.</i>")

    messages = _chunks("\n".join(lines), html.escape(text) if text else "")

    shown = list(edits)[-MAX_EDITS_SHOWN:]
    if shown:
        total = len(edits)
        title = f"✏️ <b>Версии до удаления: {total}</b>"
        if total > len(shown):
            title += f" (показаны последние {len(shown)})"
        pieces: list[str] = []
        for item in shown:
            moment = from_iso(item["edited_at"])
            stamp = moment.strftime("%d.%m %H:%M:%S") if moment else "—"
            body = item["text"] or "(без текста)"
            pieces.append(f"[{stamp}]\n{html.escape(body)}")
        messages.extend(_chunks(title, "\n\n".join(pieces)))

    return messages


async def send_media(bot: Bot, row, chat_id: int) -> None:
    """Переслать сохранённое вложение следом за отчётом."""

    kind = row["media_type"]
    if not kind:
        return

    source: FSInputFile | str | None = None
    path = row["media_path"]
    if path and Path(path).exists():
        source = FSInputFile(path, filename=row["media_name"] or None)
    elif row["media_file_id"]:
        # Файла у себя нет — надежда на то, что Telegram ещё отдаёт его по
        # старой ссылке. После удаления это работает не всегда.
        source = row["media_file_id"]

    if source is None:
        return

    method_name = _SEND_METHOD.get(kind, "send_document")
    argument = kind if method_name != "send_document" or kind == "document" else "document"
    method = getattr(bot, method_name, None)
    if method is None:
        method, argument = bot.send_document, "document"

    try:
        await method(chat_id=chat_id, **{argument: source})
    except TelegramRetryAfter:
        raise
    except (TelegramAPIError, OSError) as error:
        logger.warning(f"Вложение не отправилось: {error}")
        await bot.send_message(
            chat_id,
            "⚠️ Вложение к сообщению выше недоступно: "
            f"{html.escape(str(error))}",
            link_preview_options=_NO_PREVIEW,
        )


async def deliver(bot: Bot, row, edits: Sequence = (), chat_id: int | None = None) -> bool:
    """Отправить отчёт в архивный чат. False — не вышло, попробуем позже."""

    target = chat_id if chat_id is not None else ARCHIVE_CHAT_ID
    if not target:
        # Архивного чата нет: сообщение уже лежит в базе, доставать его
        # оттуда командой /recent.
        return True

    for chunk in render(row, edits):
        await bot.send_message(target, chunk, link_preview_options=_NO_PREVIEW)

    await send_media(bot, row, target)
    return True
