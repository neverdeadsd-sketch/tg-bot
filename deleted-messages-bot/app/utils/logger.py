from pathlib import Path

from loguru import logger

Path("logs").mkdir(exist_ok=True)

logger.remove()

logger.add(
    sink=lambda msg: print(msg, end=""),
    level="INFO",
    colorize=True,
    format=(
        "<green>{time:HH:mm:ss}</green> | <level>{level}</level> | "
        "<cyan>{message}</cyan>"
    ),
)

logger.add(
    "logs/bot.log",
    level="INFO",
    rotation="10 MB",
    retention="30 days",
    encoding="utf-8",
    enqueue=True,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)
