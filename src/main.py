"""
src/main.py
Точка входа проекта. Проверяет, что config, logger и database работают.
"""

import sys
from pathlib import Path

from src.core.config import BASE_DIR, settings
from src.core.database import get_session, init_db
from src.core.logger import get_logger


log = get_logger(__name__)


def check_database() -> bool:
    """Инициализирует БД и проверяет, что файл создался."""
    try:
        log.info("Инициализация базы данных...")
        init_db()

        db_path = BASE_DIR / "data" / "airdrop.db"
        if db_path.exists():
            size_kb = db_path.stat().st_size / 1024
            log.info(f"✅ БД создана: {db_path}")
            log.info(f"   Размер: {size_kb:.2f} KB")
            return True
        else:
            log.error(f"❌ БД не найдена: {db_path}")
            return False
    except Exception as e:
        log.error(f"❌ Ошибка инициализации БД: {e}")
        return False


def check_session() -> bool:
    """Проверяет, что сессия БД открывается."""
    try:
        with get_session() as session:
            log.info("✅ Сессия БД открыта")
        return True
    except Exception as e:
        log.error(f"❌ Ошибка сессии БД: {e}")
        return False


def main() -> int:
    """Точка входа. Проверяет все системы."""
    log.info("=" * 60)
    log.info("🚀 Airdrop Hunter — запуск")
    log.info("=" * 60)

    # --- Конфиг ---
    log.info(f"Окружение: {settings.ENVIRONMENT}")
    log.info(f"Уровень логирования: {settings.LOG_LEVEL}")
    log.info(f"RPC: {settings.POLYGON_RPC_URL}")
    log.info(f"База данных: {settings.DATABASE_URL}")

    # --- Telegram ---
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        log.info("✅ Telegram настроен")
    else:
        log.warning("⚠️ Telegram не настроен (.env пустой)")

    # --- База данных ---
    log.info("-" * 60)
    db_ok = check_database()
    session_ok = check_session()

    # --- Итог ---
    log.info("-" * 60)
    if db_ok and session_ok:
        log.success("✅ Все системы работают. Фундамент + БД готовы.")
        return 0
    else:
        log.error("❌ Есть проблемы. Смотри логи выше.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
