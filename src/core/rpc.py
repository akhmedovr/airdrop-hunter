"""
src/core/rpc.py
Web3-провайдер для работы с блокчейном.

Возможности:
    - Singleton Web3-инстанс (кэшируется по прокси)
    - Автоматический fallback между несколькими RPC
    - Хелперы: баланс, nonce, gas price, проверка соединения
    - Поддержка прокси (per-wallet)

Использование:
    from src.core.rpc import get_web3, get_balance_matic

    # Напрямую (общий IP сервера)
    w3 = get_web3()
    balance = get_balance_matic("0x...")

    # Через прокси кошелька
    from src.core.proxy import get_proxy_for_wallet
    proxy = get_proxy_for_wallet("0xAd7d...")
    balance = get_balance_matic("0xAd7d...", proxy=proxy)
"""

from typing import Optional

from web3 import Web3
from web3.exceptions import Web3Exception
from web3.middleware import ExtraDataToPOAMiddleware

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)

# Публичные Polygon RPC (fallback).
FALLBACK_POLYGON_RPCS = [
    "https://polygon.llamarpc.com",
    "https://rpc.ankr.com/polygon",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]

# Кэш Web3-инстансов: ключ — proxy URL или "__direct__"
_web3_cache: dict[str, Web3] = {}
_active_rpc: Optional[str] = None


def _build_rpc_list() -> list[str]:
    """Собирает список RPC: сначала из .env, потом fallback."""
    rpcs = [settings.POLYGON_RPC_URL] + FALLBACK_POLYGON_RPCS
    seen = set()
    result = []
    for rpc in rpcs:
        if rpc and rpc not in seen:
            seen.add(rpc)
            result.append(rpc)
    return result


def _try_connect(rpc_url: str, proxy: Optional[str] = None) -> Optional[Web3]:
    """
    Пробует подключиться к одному RPC.
    Если задан proxy — все запросы идут через него.
    """
    try:
        request_kwargs: dict = {"timeout": 10}
        if proxy:
            request_kwargs["proxies"] = {"http": proxy, "https": proxy}

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs=request_kwargs))
        # POA-middleware для Polygon (extraData 105 байт)
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if w3.is_connected():
            block = w3.eth.block_number
            proxy_info = " via proxy" if proxy else ""
            log.success(f"RPC подключён: {rpc_url}{proxy_info} | блок #{block}")
            return w3
        log.warning(f"RPC не отвечает: {rpc_url}")
        return None
    except Exception as e:
        log.warning(f"Ошибка подключения к {rpc_url}: {e}")
        return None


def get_web3(force_reconnect: bool = False, proxy: Optional[str] = None) -> Web3:
    """
    Возвращает Web3-инстанс.
    Кэшируется по прокси: для каждого прокси — свой Web3.

    Args:
        force_reconnect: переподключиться заново (для is_rpc_alive)
        proxy: URL прокси (None = без прокси)

    Returns:
        Web3-инстанс.

    Raises:
        RuntimeError: если ни один RPC не отвечает.
    """
    global _active_rpc

    cache_key = proxy or "__direct__"

    if cache_key in _web3_cache and not force_reconnect:
        return _web3_cache[cache_key]

    proxy_label = " (через прокси)" if proxy else ""
    log.info(f"Ищу рабочий RPC endpoint{proxy_label}...")

    for rpc_url in _build_rpc_list():
        w3 = _try_connect(rpc_url, proxy=proxy)
        if w3 is not None:
            _web3_cache[cache_key] = w3
            if not proxy:
                _active_rpc = rpc_url
            return w3

    raise RuntimeError(
        "Ни один RPC не отвечает. Проверь POLYGON_RPC_URL в .env и интернет."
    )


def get_active_rpc() -> Optional[str]:
    """Возвращает URL активного RPC (без прокси)."""
    return _active_rpc


def is_rpc_alive() -> bool:
    """
    Проверяет, что активный RPC жив.
    force_reconnect=True гарантирует реальную попытку соединения.
    """
    try:
        get_web3(force_reconnect=True)
        return True
    except RuntimeError:
        return False


def get_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    """Баланс адреса в wei."""
    w3 = get_web3(proxy=proxy)
    checksum = Web3.to_checksum_address(address)
    return w3.eth.get_balance(checksum)


def get_balance_matic(address: str, proxy: Optional[str] = None) -> float:
    """Баланс адреса в MATIC/POL (float)."""
    wei = get_balance_wei(address, proxy=proxy)
    return float(Web3.from_wei(wei, "ether"))


def get_nonce(address: str, proxy: Optional[str] = None) -> int:
    """Следующий nonce для адреса."""
    w3 = get_web3(proxy=proxy)
    checksum = Web3.to_checksum_address(address)
    return w3.eth.get_transaction_count(checksum)


def get_gas_price_gwei(proxy: Optional[str] = None) -> float:
    """Текущая gas price в Gwei."""
    w3 = get_web3(proxy=proxy)
    gas_price_wei = w3.eth.gas_price
    return float(Web3.from_wei(gas_price_wei, "gwei"))


def clear_cache() -> None:
    """Очищает кэш Web3-инстансов. Полезно при отладке."""
    global _active_rpc
    _web3_cache.clear()
    _active_rpc = None


__all__ = [
    "get_web3",
    "get_active_rpc",
    "is_rpc_alive",
    "get_balance_wei",
    "get_balance_matic",
    "get_nonce",
    "get_gas_price_gwei",
    "clear_cache",
    "FALLBACK_POLYGON_RPCS",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.core.rpc
    log.info("Тест RPC-провайдера...")

    try:
        # 1. Напрямую
        w3 = get_web3()
        block = w3.eth.block_number
        gas = get_gas_price_gwei()
        print("✅ RPC (напрямую)")
        print(f"   Активный endpoint: {get_active_rpc()}")
        print(f"   Блок: {block}")
        print(f"   Gas price: {gas:.2f} Gwei")

        # 2. Через прокси farm-01
        from src.core.proxy import get_proxy_for_label
        proxy = get_proxy_for_label("farm-01")
        if proxy:
            w3p = get_web3(proxy=proxy)
            block_p = w3p.eth.block_number
            print(f"✅ RPC (через прокси farm-01)")
            print(f"   Блок: {block_p}")
        else:
            print("⚠️ Прокси для farm-01 не задан")

    except RuntimeError as e:
        print(f"❌ {e}")
