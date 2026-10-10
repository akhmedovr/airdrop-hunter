"""
src/modules/wallets/manager.py
Управление кошельками: генерация, импорт, баланс, БД.
"""

from typing import Optional

from eth_account import Account
from sqlalchemy import select
from web3 import Web3

from src.core.database import Wallet, get_session
from src.core.logger import get_logger
from src.core.proxy import get_proxy_for_wallet
from src.core.rpc import get_web3
from src.modules.wallets.security import (
    decrypt_private_key,
    encrypt_private_key,
    is_encryption_ready,
)


log = get_logger(__name__)


# ============================================================
# WEB3
# ============================================================
# Web3-подключение берётся из src.core.rpc — единая точка с
# fallback между RPC и поддержкой per-wallet прокси.
# Локальную реализацию здесь не держим, чтобы не палить IP сервера.

def get_matic_balance(address: str) -> float:
    """Возвращает баланс MATIC (нативного токена Polygon).

    Запрос идёт через прокси, привязанный к кошельку.
    """
    try:
        proxy = get_proxy_for_wallet(address)
        w3 = get_web3(proxy=proxy)
        balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
        return float(w3.from_wei(balance_wei, "ether"))
    except Exception as e:
        log.error(f"Ошибка получения баланса для {address[:10]}...: {e}")
        return 0.0


# ============================================================
# ГЕНЕРАЦИЯ И ИМПОРТ
# ============================================================

def generate_wallet(label: str = "farming", wallet_type: str = "farming") -> dict:
    """
    Генерирует новый кошелёк.
    Возвращает dict c address и private_key (в открытом виде — только для показа пользователю!).
    """
    Account.enable_unaudited_hdwallet_features()
    acct = Account.create()
    return {
        "address": acct.address,
        "private_key": acct.key.hex(),
        "label": label,
        "wallet_type": wallet_type,
    }


def import_wallet(private_key: str, label: str = "imported", wallet_type: str = "farming") -> dict:
    """Импортирует существующий кошелёк по приватному ключу."""
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    acct = Account.from_key(private_key)
    return {
        "address": acct.address,
        "private_key": private_key,
        "label": label,
        "wallet_type": wallet_type,
    }


# ============================================================
# СОХРАНЕНИЕ В БД
# ============================================================

def save_wallet(
    address: str,
    private_key: str,
    label: str = "wallet",
    wallet_type: str = "farming",
) -> Optional[Wallet]:
    """
    Сохраняет кошелёк в БД. Приватный ключ шифруется.
    Если адрес уже есть — возвращает существующую запись.
    """
    if not is_encryption_ready():
        log.error("Шифрование не настроено. Проверь WALLET_ENCRYPTION_KEY в .env")
        return None

    with get_session() as session:
        existing = session.execute(
            select(Wallet).where(Wallet.address == address)
        ).scalar_one_or_none()

        if existing:
            log.info(f"Кошелёк уже в БД: {address[:10]}...")
            return existing

        encrypted = encrypt_private_key(private_key)

        wallet = Wallet(
            address=address,
            label=label,
            wallet_type=wallet_type,
            encrypted_key=encrypted,
            is_active=True,
        )
        session.add(wallet)
        session.commit()
        session.refresh(wallet)
        log.success(f"Сохранён кошелёк: {label} | {address[:10]}...")
        return wallet


# ============================================================
# ЗАГРУЗКА ИЗ БД
# ============================================================

def get_all_wallets(wallet_type: Optional[str] = None) -> list[Wallet]:
    """Возвращает список кошельков (можно фильтровать по типу)."""
    with get_session() as session:
        stmt = select(Wallet)
        if wallet_type:
            stmt = stmt.where(Wallet.wallet_type == wallet_type)
        return list(session.execute(stmt).scalars().all())


def get_wallet_by_address(address: str) -> Optional[Wallet]:
    """Возвращает кошелёк по адресу."""
    with get_session() as session:
        return session.execute(
            select(Wallet).where(Wallet.address == address)
        ).scalar_one_or_none()


def get_private_key(address: str) -> Optional[str]:
    """Расшифровывает и возвращает приватный ключ по адресу."""
    wallet = get_wallet_by_address(address)
    if not wallet or not wallet.encrypted_key:
        return None
    try:
        return decrypt_private_key(wallet.encrypted_key)
    except Exception as e:
        log.error(f"Не удалось расшифровать ключ для {address[:10]}...: {e}")
        return None


def update_balance(address: str, balance: float) -> None:
    """Обновляет сохранённый баланс кошелька."""
    with get_session() as session:
        wallet = session.execute(
            select(Wallet).where(Wallet.address == address)
        ).scalar_one_or_none()
        if wallet:
            wallet.balance_usd = balance
            session.commit()


# ============================================================
# УТИЛИТЫ
# ============================================================

def wallets_summary() -> dict:
    """Возвращает сводку по всем кошелькам."""
    wallets = get_all_wallets()
    return {
        "total": len(wallets),
        "farming": len([w for w in wallets if w.wallet_type == "farming"]),
        "cold": len([w for w in wallets if w.wallet_type == "cold"]),
        "active": len([w for w in wallets if w.is_active]),
    }


__all__ = [
    "generate_wallet",
    "import_wallet",
    "save_wallet",
    "get_all_wallets",
    "get_wallet_by_address",
    "get_private_key",
    "get_matic_balance",
    "get_web3",
    "update_balance",
    "wallets_summary",
]
