"""
src/modules/wallets/security.py
Шифрование и расшифровка приватных ключей через Fernet.

Приватные ключи НИКОГДА не хранятся в открытом виде.
Ключ шифрования берётся из .env (WALLET_ENCRYPTION_KEY).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings
from src.core.logger import get_logger


log = get_logger(__name__)


def _derive_fernet_key(secret: str) -> bytes:
    """
    Преобразует произвольную строку из .env в валидный Fernet-ключ.
    Fernet требует 32 байта в URL-safe base64.
    Используем SHA-256 для нормализации.
    """
    if not secret:
        raise ValueError(
            "WALLET_ENCRYPTION_KEY не задан в .env. "
            "Сгенерируй: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


# Инициализация Fernet
try:
    _FERNET = Fernet(_derive_fernet_key(settings.WALLET_ENCRYPTION_KEY))
except ValueError as e:
    log.warning(f"Шифрование недоступно: {e}")
    _FERNET = None


def encrypt_private_key(private_key: str) -> str:
    """
    Шифрует приватный ключ.
    Возвращает строку (base64), пригодную для хранения в БД.
    """
    if _FERNET is None:
        raise RuntimeError("Шифрование не настроено. Проверь WALLET_ENCRYPTION_KEY.")
    if not private_key:
        raise ValueError("Пустой приватный ключ")
    encrypted = _FERNET.encrypt(private_key.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_private_key(encrypted_key: str) -> str:
    """
    Расшифровывает приватный ключ.
    Возвращает исходную строку.
    """
    if _FERNET is None:
        raise RuntimeError("Шифрование не настроено. Проверь WALLET_ENCRYPTION_KEY.")
    if not encrypted_key:
        raise ValueError("Пустой зашифрованный ключ")
    try:
        decrypted = _FERNET.decrypt(encrypted_key.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        log.error("Не удалось расшифровать ключ: неверный WALLET_ENCRYPTION_KEY")
        raise


def is_encryption_ready() -> bool:
    """Проверяет, что шифрование настроено."""
    return _FERNET is not None


__all__ = [
    "encrypt_private_key",
    "decrypt_private_key",
    "is_encryption_ready",
]
