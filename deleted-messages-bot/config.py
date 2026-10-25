import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "да"}


def _ids(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "")
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return tuple(out)


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Куда присылать удалённые сообщения. Этот чат сам не архивируется, иначе бот
# начал бы следить за своими же отчётами.
ARCHIVE_CHAT_ID = _int("ARCHIVE_CHAT_ID")

# Кому разрешены команды бота в личке. Пусто — команды не отвечают никому:
# архив чужих сообщений не должен быть открыт для всех желающих.
ADMIN_IDS = _ids("ADMIN_IDS")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "").strip() or str(DATA_DIR / "archive.db")
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "").strip() or DATA_DIR / "media")

# file_id продолжает работать и после удаления сообщения, но гарантии на это
# нет: единственный надёжный способ сохранить вложение — забрать файл сразу.
DOWNLOAD_MEDIA = _bool("DOWNLOAD_MEDIA", True)

# Bot API отдаёт боту файлы не больше 20 МБ, просить больше бессмысленно.
MAX_DOWNLOAD_MB = min(_int("MAX_DOWNLOAD_MB", 20), 20)

# Сколько часов после отправки бот проверяет, жив ли текст. Почти все удаления
# случаются в первые минуты, а бесконечная проверка — это трата лимитов.
WATCH_HOURS = _int("WATCH_HOURS", 48)

# Проверок в секунду. Лимиты Telegram считаются по отправкам, но запас лучше
# держать: при 2/с бот успевает обойти десятки тысяч сообщений в сутки.
PROBE_RATE = _float("PROBE_RATE", 2.0)
PROBE_BATCH = _int("PROBE_BATCH", 40)

# Сколько дней хранить архив. 0 — не удалять ничего.
KEEP_DAYS = _int("KEEP_DAYS", 0)

# Служебные сообщения («вошёл в группу», «сменилось название») боты-уборщики
# чистят пачками, и каждая такая чистка стала бы отчётом об удалении.
ARCHIVE_SERVICE_MESSAGES = _bool("ARCHIVE_SERVICE_MESSAGES", False)

# Если список не пуст — бот архивирует только эти чаты.
WATCH_CHATS = _ids("WATCH_CHATS")
IGNORE_CHATS = _ids("IGNORE_CHATS")

# Режим 2 (userbot.py): api_id и api_hash берутся на my.telegram.org.
TELEGRAM_API_ID = _int("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
USERBOT_SESSION = os.getenv("USERBOT_SESSION", "").strip() or str(DATA_DIR / "userbot")
