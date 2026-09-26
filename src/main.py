"""
src/main.py
Точка входа. Проверяет config, logger, database, wallet security.
"""

import sys

from src.core.config import BASE_DIR, settings
from src.core.database import get_session, init_db
from src.core.logger import get_logger
from src.modules.wallets.manager import (
    generate_wallet,
    get_all_wallets,
    save_wallet,
    wallets_summary,
)
from src.modules.wallets.security import (
    decrypt_private_key,
    encrypt_private_key,
    is_encryption_ready,
)


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
        log.error(f"❌ БД не найдена: {db_path}")
        return False
    except Exception as e:
        log.error(f"❌ Ошибка инициализации БД: {e}")
        return False


def check_session() -> bool:
    """Проверяет, что сессия БД открывается."""
    try:
        with get_session():
            log.info("✅ Сессия БД открыта")
        return True
    except Exception as e:
        log.error(f"❌ Ошибка сессии БД: {e}")
        return False


def check_encryption() -> bool:
    """Проверяет, что шифрование работает."""
    if not is_encryption_ready():
        log.error("❌ Шифрование не настроено. Проверь WALLET_ENCRYPTION_KEY в .env")
        return False

    try:
        test_key = "0x" + "a" * 64
        encrypted = encrypt_private_key(test_key)
        decrypted = decrypt_private_key(encrypted)

        if decrypted == test_key:
            log.info("✅ Шифрование работает (Fernet)")
            return True
        log.error("❌ Расшифровка не совпадает с оригиналом")
        return False
    except Exception as e:
        log.error(f"❌ Ошибка шифрования: {e}")
        return False


def check_wallets() -> bool:
    """Проверяет генерацию и сохранение кошелька."""
    try:
        # Генерируем новый кошелёк
        wallet_data = generate_wallet(label="test-wallet", wallet_type="farming")
        log.info(f"Сгенерирован кошелёк: {wallet_data['address']}")

        # Сохраняем в БД (приватный ключ шифруется)
        saved = save_wallet(
            address=wallet_data["address"],
            private_key=wallet_data["private_key"],
            label=wallet_data["label"],
            wallet_type=wallet_data["wallet_type"],
        )

        if saved:
            log.info(f"✅ Кошелёк сохранён в БД: {saved.address[:10]}...")
            summary = wallets_summary()
            log.info(f"   Всего кошельков: {summary['total']} | farming: {summary['farming']}")
            return True
        log.error("❌ Не удалось сохранить кошелёк")
        return False
    except Exception as e:
        log.error(f"❌ Ошибка работы с кошельком: {e}")
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

    # --- Шифрование ---
    log.info("-" * 60)
    encryption_ok = check_encryption()

    # --- Кошельки ---
    log.info("-" * 60)
    wallets_ok = check_wallets() if encryption_ok else False

    # --- Итог ---
    log.info("-" * 60)
    if db_ok and session_ok and encryption_ok and wallets_ok:
        log.success("✅ Все системы работают. БД + Шифрование + Кошельки готовы.")
        return 0

    log.error("❌ Есть проблемы. Смотри логи выше.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
