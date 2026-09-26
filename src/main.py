"""
src/main.py
Точка входа проекта. Проверяет, что config и logger работают.
"""

import sys

from src.core.config import settings
from src.core.logger import get_logger


log = get_logger(__name__)


def main():
    """Точка входа. Проверяет окружение."""
    log.info("=" * 60)
    log.info("🚀 Airdrop Hunter — запуск")
    log.info("=" * 60)

    # Показываем загруженные настройки (без секретов!)
    log.info(f"Окружение: {settings.ENVIRONMENT}")
    log.info(f"Уровень логирования: {settings.LOG_LEVEL}")
    log.info(f"RPC: {settings.POLYGON_RPC_URL}")
    log.info(f"База данных: {settings.DATABASE_URL}")

    # Проверяем, что Telegram-токен задан
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        log.info("✅ Telegram настроен")
    else:
        log.warning("⚠️ Telegram не настроен (.env пустой)")

    log.success("✅ Все системы работают. Фундамент готов.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
