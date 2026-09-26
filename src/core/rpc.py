"""
src/core/rpc.py
Web3-провайдер для работы с блокчейном.

Возможности:
    - Singleton Web3-инстанс (не пересоздаём на каждый вызов)
    - Автоматический fallback между несколькими RPC endpoints
    - Хелперы: баланс, nonce, gas price, проверка соединения

Использование:
    from src.core.rpc import get_web3, get_balance, is_rpc_alive

    w3 = get_web3()
    balance_wei = w3.eth.get_balance("0x...")
"""

from typing import Optional

from web3 import Web3
from web3.exceptions import Web3Exception

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)

# Публичные Polygon RPC (fallback).
# Первым в списке всегда идёт тот, что в .env (POLYGON_RPC_URL).
# Остальные — резервные, если основной упал.
FALLBACK_POLYGON_RPCS = [
    "https://polygon.llamarpc.com",
    "https://rpc.ankr.com/polygon",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]

# Singleton — один Web3-инстанс на процесс
_web3_instance: Optional[Web3] = None
_active_rpc: Optional[str] = None


def _build_rpc_list() -> list[str]:
    """
    Собирает список RPC: сначала из .env, потом fallback.
    Убирает дубликаты, сохраняя порядок.
    """
    rpcs = [settings.POLYGON_RPC_URL] + FALLBACK_POLYGON_RPCS
    seen = set()
    result = []
    for rpc in rpcs:
        if rpc and rpc not in seen:
            seen.add(rpc)
            result.append(rpc)
    return result


def _try_connect(rpc_url: str) -> Optional[Web3]:
    """
    Пробует подключиться к одному RPC.
    Возвращает Web3-инстанс если соединение живо, иначе None.
    """
    try:
        w3 = Web3(Web3.HTTPProvider(
            rpc_url,
            request_kwargs={"timeout": 10},
        ))
        if w3.is_connected():
            block = w3.eth.block_number
            log.success(f"RPC подключён: {rpc_url} | блок #{block}")
            return w3
        log.warning(f"RPC не отвечает: {rpc_url}")
        return None
    except Exception as e:
        log.warning(f"Ошибка подключения к {rpc_url}: {e}")
        return None


def get_web3(force_reconnect: bool = False) -> Web3:
    """
    Возвращает singleton Web3-инстанс.
    При force_reconnect=True — переподключается (полезно если RPC упал).

    Проходит по списку RPC, пока не найдёт живой.
    Кидает RuntimeError если ни один не отвечает.
    """
    global _web3_instance, _active_rpc

    if _web3_instance is not None and not force_reconnect:
        return _web3_instance

    log.info("Ищу рабочий RPC endpoint...")
    for rpc_url in _build_rpc_list():
        w3 = _try_connect(rpc_url)
        if w3 is not None:
            _web3_instance = w3
            _active_rpc = rpc_url
            return w3

    raise RuntimeError(
        "Ни один RPC не отвечает. Проверь POLYGON_RPC_URL в .env и интернет."
    )


def get_active_rpc() -> Optional[str]:
    """Возвращает URL активного RPC (или None если ещё не подключались)."""
    return _active_rpc


def is_rpc_alive() -> bool:
    """Проверяет, что активный RPC жив. Если нет — пробует переподключиться."""
    try:
        w3 = get_web3(force_reconnect=True)
        return w3.is_connected()
    except RuntimeError:
        return False


def get_balance_wei(address: str) -> int:
    """Возвращает баланс адреса в wei (1 MATIC = 10^18 wei)."""
    w3 = get_web3()
    checksum = Web3.to_checksum_address(address)
    return w3.eth.get_balance(checksum)


def get_balance_matic(address: str) -> float:
    """Возвращает баланс адреса в MATIC (float)."""
    wei = get_balance_wei(address)
    return float(Web3.from_wei(wei, "ether"))


def get_nonce(address: str) -> int:
    """Возвращает следующий nonce для адреса (число уже отправленных tx)."""
    w3 = get_web3()
    checksum = Web3.to_checksum_address(address)
    return w3.eth.get_transaction_count(checksum)


def get_gas_price_gwei() -> float:
    """Возвращает текущую gas price в Gwei."""
    w3 = get_web3()
    gas_price_wei = w3.eth.gas_price
    return float(Web3.from_wei(gas_price_wei, "gwei"))


__all__ = [
    "get_web3",
    "get_active_rpc",
    "is_rpc_alive",
    "get_balance_wei",
    "get_balance_matic",
    "get_nonce",
    "get_gas_price_gwei",
    "FALLBACK_POLYGON_RPCS",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.core.rpc
    log.info("Тест RPC-провайдера...")

    try:
        w3 = get_web3()
        block = w3.eth.block_number
        gas = get_gas_price_gwei()
        print(f"✅ RPC работает")
        print(f"   Активный endpoint: {get_active_rpc()}")
        print(f"   Текущий блок: {block}")
        print(f"   Gas price: {gas:.2f} Gwei")

        # Тест баланса первого кошелька (если есть)
        from src.modules.wallets.manager import get_all_wallets
        wallets = get_all_wallets()
        if wallets:
            addr = wallets[0].address
            bal = get_balance_matic(addr)
            print(f"   Баланс {addr[:10]}...: {bal:.4f} MATIC")
        else:
            print("   (кошельков в БД нет — пропускаю проверку баланса)")

    except RuntimeError as e:
        print(f"❌ {e}")
