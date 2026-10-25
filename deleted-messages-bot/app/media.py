from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import MAX_DOWNLOAD_MB, MEDIA_DIR
from app.utils.logger import logger

# Порядок важен: у сообщения с видео бывает и миниатюра, но интересует видео.
_MEDIA_FIELDS = (
    "video",
    "animation",
    "audio",
    "voice",
    "video_note",
    "sticker",
    "document",
)

_FALLBACK_SUFFIX = {
    "photo": ".jpg",
    "video": ".mp4",
    "animation": ".mp4",
    "audio": ".mp3",
    "voice": ".ogg",
    "video_note": ".mp4",
    "sticker": ".webp",
    "document": ".bin",
}


@dataclass(frozen=True, slots=True)
class Media:
    file_id: str
    unique_id: str
    kind: str
    size: int | None = None
    name: str | None = None


def extract(message) -> Media | None:
    """Вытащить вложение из сообщения, если оно там есть."""

    photo = getattr(message, "photo", None)
    if photo:
        # photo — список размеров одной картинки, последний самый большой.
        best = photo[-1]
        return Media(
            file_id=best.file_id,
            unique_id=best.file_unique_id,
            kind="photo",
            size=getattr(best, "file_size", None),
        )

    for field in _MEDIA_FIELDS:
        item = getattr(message, field, None)
        if item is None or not getattr(item, "file_id", None):
            continue
        return Media(
            file_id=item.file_id,
            unique_id=item.file_unique_id,
            kind=field,
            size=getattr(item, "file_size", None),
            name=getattr(item, "file_name", None),
        )

    return None


def too_big(media: Media, max_mb: int = MAX_DOWNLOAD_MB) -> bool:
    if media.size is None:
        return False
    return media.size > max_mb * 1024 * 1024


async def download(
    bot: Bot,
    media: Media,
    directory: Path = MEDIA_DIR,
    max_mb: int = MAX_DOWNLOAD_MB,
) -> str | None:
    """Забрать файл себе. None — не получилось, остаётся только file_id.

    Имя файла строится из file_unique_id, а не из присланного имени: оно
    пришло из чата и может содержать что угодно, включая путь наружу.
    """

    if too_big(media, max_mb):
        logger.info(
            f"Вложение {media.kind} {media.size} Б больше лимита {max_mb} МБ — "
            "сохранён только file_id"
        )
        return None

    try:
        file = await bot.get_file(media.file_id)
    except TelegramAPIError as error:
        logger.warning(f"Не удалось получить ссылку на вложение: {error}")
        return None

    remote_path = getattr(file, "file_path", None)
    suffix = Path(remote_path).suffix if remote_path else ""
    if not suffix:
        suffix = _FALLBACK_SUFFIX.get(media.kind, ".bin")

    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{media.unique_id}{suffix}"

    if destination.exists() and destination.stat().st_size > 0:
        return str(destination)

    try:
        await bot.download_file(remote_path, destination=destination)
    except (TelegramAPIError, OSError) as error:
        logger.warning(f"Не удалось скачать вложение {media.kind}: {error}")
        return None

    return str(destination)
