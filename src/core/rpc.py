"""
src/core/rpc.py
Web3-провайдер для работы с блокчейном. Мультичейн.

Возможности:
    - Мультичейн: polygon / base / linea
    - Singleton Web3-инстанс (кэшируется по chain + прокси)
    - Автоматический fallback между несколькими RPC
    - Хелперы: баланс, nonce, gas price
    - Поддержка прокси (per-wallet)

Использование:
    from src.core.rpc import get_web3, get_balance_native

    # Polygon (по умолчанию)
    w3 = get_web3()
    balance = get_balance_native("0x...", chain="polygon")

    # Base
    w3 = get_web3(chain="base")
    balance = get_balance_native("0x...", chain="base")

    # Через прокси кошелька
    from src.core.proxy import get_proxy_for_wallet
    proxy = get_proxy_for_wallet("0xAd7d...")
    balance = get_balance_native("0xAd7d...", chain="polygon", proxy=proxy)

Обратная совместимость:
    get_balance_matic(addr, proxy=...) — алиас для polygon.
"""

from typing import Optional

from web3 import Web3
from web3.exceptions import Web3Exception
from web3.middleware import ExtraDataToPOAMiddleware

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)


# ============================================================
# Конфигурация сетей
# ============================================================

CHAINS: dict[str, dict] = {
    "polygon": {
        "chain_id": 137,
        "native_symbol": "MATIC",  # отображаем как MATIC для совместимости
        "poa": True,  # Polygon использует POA
        "fallback": [
            "https://polygon.llamarpc.com",
            "https://rpc.ankr.com/polygon",
            "https://polygon-bor-rpc.publicnode.com",
            "https://1rpc.io/matic",
        ],
    },
    "base": {
        "chain_id": 8453,
        "native_symbol": "ETH",
        "poa": False,  # Base — OP-stack, POA не нужен
        "fallback": [
            "https://base.llamarpc.com",
            "https://base-rpc.publicnode.com",
            "https://1rpc.io/base",
            "https://base.blockpi.network/v1/rpc/public",
        ],
    },
    "linea": {
        "chain_id": 59144,
        "native_symbol": "ETH",
        "poa": True,  # Linea использует POA (sequencer)
        "fallback": [
            "https://rpc.linea.build",
            "https://linea-rpc.publicnode.com",
            "https://1rpc.io/linea",
        ],
    },
}

DEFAULT_CHAIN = "polygon"


# Алиас для обратной совместимости с импортами старого кода
FALLBACK_POLYGON_RPCS = CHAINS["polygon"]["fallback"]


# Кэш Web3-инстансов: ключ = f"{chain}::{proxy or '__direct__'}"
_web3_cache: dict[str, Web3] = {}
# Активный RPC per chain (для /status)
_active_rpc: dict[str, Optional[str]] = {}


# ============================================================
# Внутренние хелперы
# ============================================================

def _get_chain_config(chain: str) -> dict:
    """Возвращает конфиг сети или бросает ValueError."""
    if chain not in CHAINS:
        raise ValueError(
            f"Неизвестная сеть: {chain}. "
            f"Доступные: {list(CHAINS.keys())}"
        )
    return CHAINS[chain]


def _build_rpc_list(chain: str) -> list[str]:
    """Собирает список RPC для сети: основной из .env + fallback."""
    cfg = _get_chain_config(chain)

    if chain == "polygon":
        primary = settings.POLYGON_RPC_URL
    elif chain == "base":
        primary = settings.BASE_RPC_URL
    elif chain == "linea":
        primary = settings.LINEA_RPC_URL
    else:
        primary = ""

    rpcs = [primary] + cfg["fallback"]

    seen: set[str] = set()
    result: list[str] = []
    for rpc in rpcs:
        if rpc and rpc not in seen:
            seen.add(rpc)
            result.append(rpc)
    return result


def _try_connect(
    rpc_url: str,
    chain: str,
    proxy: Optional[str] = None,
) -> Optional[Web3]:
    """
    Пробует подключиться к одному RPC.
    Если задан proxy — все запросы идут через него.
    """
    cfg = _get_chain_config(chain)
    try:
        request_kwargs: dict = {"timeout": 10}
        if proxy:
            request_kwargs["proxies"] = {"http": proxy, "https": proxy}

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs=request_kwargs))

        # POA middleware нужен для Polygon, Linea. Base — не нужен.
        if cfg["poa"]:
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if w3.is_connected():
            block = w3.eth.block_number
            proxy_info = " via proxy" if proxy else ""
            log.success(
                f"RPC [{chain}] подключён: {rpc_url}{proxy_info} | "
                f"блок #{block}"
            )
            return w3

        log.warning(f"RPC [{chain}] не отвечает: {rpc_url}")
        return None
    except Exception as e:
        log.warning(f"Ошибка подключения к [{chain}] {rpc_url}: {e}")
        return None


# ============================================================
# Публичное API
# ============================================================

def get_web3(
    chain: str = DEFAULT_CHAIN,
    force_reconnect: bool = False,
    proxy: Optional[str] = None,
) -> Web3:
    """
    Возвращает Web3-инстанс для указанной сети.

    Кэшируется по (chain, proxy): для каждого прокси — свой Web3.

    Args:
        chain: "polygon" | "base" | "linea"
        force_reconnect: переподключиться заново (для is_rpc_alive)
        proxy: URL прокси (None = без прокси)

    Returns:
        Web3-инстанс.

    Raises:
        RuntimeError: если ни один RPC не отвечает.
    """
    _get_chain_config(chain)  # валидация chain

    cache_key = f"{chain}::{proxy or '__direct__'}"

    if cache_key in _web3_cache and not force_reconnect:
        return _web3_cache[cache_key]

    proxy_label = " (через прокси)" if proxy else ""
    log.info(f"Ищу рабочий RPC [{chain}]{proxy_label}...")

    for rpc_url in _build_rpc_list(chain):
        w3 = _try_connect(rpc_url, chain, proxy=proxy)
        if w3 is not None:
            _web3_cache[cache_key] = w3
            if not proxy:
                _active_rpc[chain] = rpc_url
            return w3

    raise RuntimeError(
        f"Ни один RPC [{chain}] не отвечает. "
        f"Проверь {chain.upper()}_RPC_URL в .env и интернет."
    )


def get_active_rpc(chain: str = DEFAULT_CHAIN) -> Optional[str]:
    """Возвращает URL активного RPC для сети (без прокси)."""
    return _active_rpc.get(chain)


def is_rpc_alive(chain: str = DEFAULT_CHAIN) -> bool:
    """Проверяет, что активный RPC сети жив."""
    try:
        get_web3(chain=chain, force_reconnect=True)
        return True
    except RuntimeError:
        return False


def get_balance_wei(
    address: str,
    chain: str = DEFAULT_CHAIN,
    proxy: Optional[str] = None,
) -> int:
    """Баланс адреса в wei (нативная валюта сети)."""
    w3 = get_web3(chain=chain, proxy=proxy)
    checksum = Web3.to_checksum_address(address)
    return w3.eth.get_balance(checksum)


def get_balance_native(
    address: str,
    chain: str = DEFAULT_CHAIN,
    proxy: Optional[str] = None,
) -> float:
    """Баланс адреса в нативной валюте (float): POL, ETH и т.д."""
    wei = get_balance_wei(address, chain=chain, proxy=proxy)
    return float(Web3.from_wei(wei, "ether"))


def get_balance_matic(
    address: str,
    proxy: Optional[str] = None,
) -> float:
    """Алиас для polygon — обратная совместимость."""
    return get_balance_native(address, chain="polygon", proxy=proxy)


def get_nonce(
    address: str,
    chain: str = DEFAULT_CHAIN,
    proxy: Optional[str] = None,
) -> int:
    """Следующий nonce для адреса в сети."""
    w3 = get_web3(chain=chain, proxy=proxy)
    checksum = Web3.to_checksum_address(address)
    return w3.eth.get_transaction_count(checksum)


def get_gas_price_gwei(
    chain: str = DEFAULT_CHAIN,
    proxy: Optional[str] = None,
) -> float:
    """Текущая gas price в Gwei для сети."""
    w3 = get_web3(chain=chain, proxy=proxy)
    gas_price_wei = w3.eth.gas_price
    return float(Web3.from_wei(gas_price_wei, "gwei"))


def get_chain_id(chain: str = DEFAULT_CHAIN) -> int:
    """chain_id сети (из конфига, без запроса к RPC)."""
    return CHAINS[chain]["chain_id"]


def get_native_symbol(chain: str = DEFAULT_CHAIN) -> str:
    """Символ нативной валюты сети: POL, ETH."""
    return CHAINS[chain]["native_symbol"]


def clear_cache() -> None:
    """Очищает кэш Web3-инстансов. Полезно при отладке."""
    _web3_cache.clear()
    _active_rpc.clear()


__all__ = [
    "CHAINS",
    "DEFAULT_CHAIN",
    "FALLBACK_POLYGON_RPCS",
    "get_web3",
    "get_active_rpc",
    "is_rpc_alive",
    "get_balance_wei",
    "get_balance_native",
    "get_balance_matic",
    "get_nonce",
    "get_gas_price_gwei",
    "get_chain_id",
    "get_native_symbol",
    "clear_cache",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.core.rpc
    log.info("Тест RPC-провайдера...")

    for chain in ("polygon", "base", "linea"):
        print(f"\n=== {chain.upper()} ===")
        try:
            w3 = get_web3(chain=chain)
            block = w3.eth.block_number
            gas = get_gas_price_gwei(chain=chain)
            print(f"✅ RPC работает")
            print(f"   Endpoint: {get_active_rpc(chain=chain)}")
            print(f"   Блок: {block}")
            print(f"   Gas price: {gas:.4f} Gwei")
            print(f"   Native: {get_native_symbol(chain=chain)}")
            print(f"   Chain ID: {get_chain_id(chain=chain)}")
        except Exception as e:
            print(f"❌ {chain}: {e}")
