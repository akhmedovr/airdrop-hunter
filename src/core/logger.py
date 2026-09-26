"""
src/core/logger.py
Настроенный loguru: консоль + файл с ротацией.
"""

import sys
from pathlib import Path

from loguru import logger

from src.core.config import BASE_DIR, settings


# Папка для логов
LOG_DIR = BASE_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Убираем стандартный обработчик loguru
logger.remove()

# --- Консоль (цветной вывод) ---
logger.add(
    sys.stdout,
    level=settings.LOG_LEVEL,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    colorize=True,
)

# --- Файл (с ротацией) ---
logger.add(
    LOG_DIR / "airdrop-hunter_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line} | "
        "{message}"
    ),
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    encoding="utf-8",
    enqueue=True,
    backtrace=True,
    diagnose=True,
)


def get_logger(name: str = __name__):
    """Возвращает logger с привязкой к модулю."""
    return logger.bind(module=name)


__all__ = ["logger", "get_logger"]
