"""
src/modules/executor/erc20.py
Работа с ERC-20 токенами: балансы, approve, transfer. Мультичейн.

Поддерживаемые сети: polygon | base | linea

Базовые операции:
    - get_token_info(token, chain)               — symbol/decimals/name
    - get_token_balance(addr, token, chain)      — баланс токена
    - get_allowance(owner, spender, token, chain) — текущий allowance
    - approve(spender, token, amount, chain)     — разрешить тратить токены
    - transfer_token(token, to, amount, chain)   — отправить токены

Все транзакции подписываются приватным ключом из БД (расшифровка Fernet)
и логируются в таблицу Transaction (см. src.core.tx_logger).

Использование:
    from src.modules.executor.erc20 import get_token_balance, approve

    # Polygon (по умолчанию)
    bal = get_token_balance("0x...", USDC_POLYGON)

    # Base
    bal = get_token_balance("0x...", USDC_BASE, chain="base")
"""

import time
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound
from web3.types import TxReceipt

from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_money, notify_success
from src.core.proxy import get_proxy_for_wallet
from src.core.rpc import (
    DEFAULT_CHAIN,
    get_chain_id,
    get_native_symbol,
    get_web3,
)
from src.core.safe_tx import safe_send
from src.core.tx_logger import log_transaction, update_transaction_status


log = get_logger(__name__)


# ============================================================
# Известные токены по сетям
# ============================================================

TOKENS: dict[str, dict[str, str]] = {
    "polygon": {
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    },
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "USDT": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",
        "WETH": "0x4200000000000000000000000000000000000006",
        "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    },
    "linea": {
        "USDC": "0x176211869cA2b568f2A7D4EE941E073a821EE1ff",
        "USDT": "0xA219439258ca9da29E9Cc4cE5596924745e12B93",
        "WETH": "0xe5D7C2a44FfDDf6b295A15c148167daaAf5Cf34f",
    },
}


# Минимальный ERC-20 ABI: то, что реально нужно
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]

MAX_UINT256 = 2**256 - 1

RECEIPT_TIMEOUT = 180
PRIORITY_FEE_GWEI = 30


# ============================================================
# Чтение
# ============================================================

def get_token_info(
    token_address: str,
    chain: str = DEFAULT_CHAIN,
    proxy: Optional[str] = None,
) -> Optional[dict]:
    """
    Возвращает {address, symbol, decimals, name} или None.
    Кэшируется в памяти процесса.
    """
    cache_key = f"{chain}::{token_address}"
    if cache_key in _TOKEN_CACHE:
        return _TOKEN_CACHE[cache_key]

    try:
        w3 = get_web3(chain=chain, proxy=proxy)
        token = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )
        info = {
            "address": Web3.to_checksum_address(token_address),
            "symbol": token.functions.symbol().call(),
            "decimals": token.functions.decimals().call(),
            "name": token.functions.name().call(),
        }
        _TOKEN_CACHE[cache_key] = info
        return info
    except Exception as e:
        log.error(f"Не смог получить info токена {chain}/{token_address}: {e}")
        return None


# Простой in-memory кэш (symbol/decimals не меняются)
_TOKEN_CACHE: dict[str, dict] = {}


def get_token_balance(
    wallet_address: str,
    token_address: str,
    chain: str = DEFAULT_CHAIN,
) -> Optional[float]:
    """
    Баланс ERC-20 токена в человеческих единицах.
    Запрос идёт через прокси, привязанный к кошельку.
    """
    proxy = get_proxy_for_wallet(wallet_address)

    info = get_token_info(token_address, chain=chain, proxy=proxy)
    if info is None:
        return None

    try:
        w3 = get_web3(chain=chain, proxy=proxy)
        token = w3.eth.contract(
            address=info["address"],
            abi=ERC20_ABI,
        )
        raw = token.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        return raw / (10 ** info["decimals"])
    except Exception as e:
        log.error(f"Не смог получить баланс {chain}/{token_address}: {e}")
        return None


def get_allowance(
    owner: str,
    spender: str,
    token_address: str,
    chain: str = DEFAULT_CHAIN,
) -> Optional[float]:
    """
    Текущий allowance: сколько spender может тратить токенов owner.
    Запрос идёт через прокси, привязанный к owner.
    """
    proxy = get_proxy_for_wallet(owner)

    info = get_token_info(token_address, chain=chain, proxy=proxy)
    if info is None:
        return None

    try:
        w3 = get_web3(chain=chain, proxy=proxy)
        token = w3.eth.contract(address=info["address"], abi=ERC20_ABI)
        raw = token.functions.allowance(
            Web3.to_checksum_address(owner),
            Web3.to_checksum_address(spender),
        ).call()
        return raw / (10 ** info["decimals"])
    except Exception as e:
        log.error(f"Не смог получить allowance {chain}: {e}")
        return None


# ============================================================
# Вспомогательные
# ============================================================

def _resolve_wallet(query: str) -> Optional[str]:
    """Метка или адрес → checksum-адрес."""
    from src.modules.wallets.manager import get_all_wallets

    if query.startswith("0x") and len(query) == 42:
        return Web3.to_checksum_address(query)
    for w in get_all_wallets():
        if w.label.lower() == query.lower():
            return Web3.to_checksum_address(w.address)
    return None


def _build_eip1559_fees(w3: Web3) -> dict:
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    if base_fee is None:
        return {}
    priority = w3.to_wei(PRIORITY_FEE_GWEI, "gwei")
    return {
        "maxFeePerGas": base_fee * 2 + priority,
        "maxPriorityFeePerGas": priority,
    }


def _sign_and_send(
    w3: Web3,
    from_address: str,
    tx: dict,
    private_key: str,
    notify: bool,
    action_name: str,
) -> Optional[str]:
    """Подписывает и отправляет транзакцию. Возвращает tx_hash hex или None."""
    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception(f"Ошибка подписи ({action_name})")
        if notify:
            notify_error(f"Ошибка подписи: {str(e)[:150]}")
        return None

    try:
        tx_hash = safe_send(w3, signed)
    except Exception as e:
        log.exception(f"Ошибка отправки ({action_name})")
        if notify:
            notify_error(f"Ошибка отправки: {str(e)[:150]}")
        return None

    return tx_hash.hex()


def _wait_receipt(w3: Web3, tx_hash_hex: str) -> Optional[TxReceipt]:
    tx_hash = bytes.fromhex(tx_hash_hex.replace("0x", ""))
    started = time.time()
    while time.time() - started < RECEIPT_TIMEOUT:
        try:
            return w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            time.sleep(3)
        except Exception as e:
            log.warning(f"Ошибка ожидания receipt: {e}")
            time.sleep(3)
    return None


def _notify_receipt(
    receipt: Optional[TxReceipt],
    tx_hash_hex: str,
    action_name: str,
    chain: str,
    notify: bool,
) -> bool:
    """Обновляет статус в БД и уведомляет."""
    native = get_native_symbol(chain)

    if receipt is None:
        update_transaction_status(tx_hash_hex, status="failed")
        if notify:
            notify_error(f"TX не подтверждена за {RECEIPT_TIMEOUT}c ({action_name})")
        return False

    if receipt.get("status") == 1:
        gas_used = receipt.get("gasUsed", 0)
        eff_price = receipt.get("effectiveGasPrice", 0)
        fee_native = float(Web3.from_wei(gas_used * eff_price, "ether"))

        update_transaction_status(
            tx_hash_hex,
            status="success",
            gas_usd=fee_native,  # поле исторически называется gas_usd, хранит native
        )

        log.success(
            f"{action_name} [{chain}] OK. Комиссия: {fee_native:.8f} {native}"
        )
        if notify:
            notify_success(
                f"✅ {action_name} [{chain}]\n"
                f"Комиссия: {fee_native:.8f} {native}\n"
                f"Блок: {receipt.get('blockNumber')}"
            )
        return True
    else:
        update_transaction_status(tx_hash_hex, status="failed")
        log.error(f"{action_name} [{chain}] провалена: {tx_hash_hex}")
        if notify:
            notify_error(f"❌ {action_name} провалена: {tx_hash_hex[:20]}...")
        return False


# ============================================================
# Approve
# ============================================================

def approve(
    owner_label_or_address: str,
    spender: str,
    token_address: str,
    amount: Optional[float] = None,
    chain: str = DEFAULT_CHAIN,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """
    Approve: разрешить spender тратить токены owner.

    Args:
        owner_label_or_address: метка или адрес владельца
        spender: адрес контракта, которому разрешаем
        token_address: адрес ERC-20 токена
        amount: сумма в человеческих единицах. None = unlimited.
        chain: сеть
        wait: ждать ли receipt
        notify: уведомлять ли

    Returns:
        tx_hash hex или None.
    """
    from src.modules.wallets.manager import get_private_key

    info = get_token_info(token_address, chain=chain)
    if info is None:
        return None

    owner = _resolve_wallet(owner_label_or_address)
    if owner is None:
        if notify:
            notify_error(f"Кошелёк не найден: {owner_label_or_address}")
        return None

    proxy = get_proxy_for_wallet(owner)
    w3 = get_web3(chain=chain, proxy=proxy)

    spender = Web3.to_checksum_address(spender)

    private_key = get_private_key(owner)
    if private_key is None:
        if notify:
            notify_error("Не удалось расшифровать ключ")
        return None

    balance = get_token_balance(owner, token_address, chain=chain)
    if balance is None or balance <= 0:
        msg = f"Нет токенов {info['symbol']} на {owner_label_or_address} [{chain}]"
        log.warning(msg)
        if notify:
            notify_error(msg)
        return None

    current = get_allowance(owner, spender, token_address, chain=chain)
    target_amount = (
        amount if amount is not None
        else float(MAX_UINT256 / 10 ** info["decimals"])
    )

    if current is not None and current >= target_amount:
        log.info(f"Allowance [{chain}] уже достаточен: {current:.4f} {info['symbol']}")
        if notify:
            notify_success(
                f"ℹ️ Allowance [{chain}] уже достаточен для {info['symbol']}\n"
                f"Текущий: {current:.4f}"
            )
        return None

    token = w3.eth.contract(address=info["address"], abi=ERC20_ABI)

    if amount is None:
        approve_value = MAX_UINT256
        amount_str = "unlimited"
    else:
        approve_value = int(amount * (10 ** info["decimals"]))
        amount_str = f"{amount} {info['symbol']}"

    nonce = w3.eth.get_transaction_count(owner, "pending")
    chain_id = w3.eth.chain_id

    tx = token.functions.approve(spender, approve_value).build_transaction({
        "from": owner,
        "nonce": nonce,
        "chainId": chain_id,
        "gas": 100_000,
    })

    eip1559 = _build_eip1559_fees(w3)
    if eip1559:
        tx.update(eip1559)
        tx["type"] = 2
    else:
        tx["gasPrice"] = w3.eth.gas_price

    log.info(f"Approve [{chain}] {amount_str} для {spender[:10]}...")

    tx_hash_hex = _sign_and_send(
        w3, owner, tx, private_key, notify,
        f"Approve {info['symbol']}",
    )
    if tx_hash_hex is None:
        return None

    log_transaction(
        wallet_address=owner,
        tx_hash=tx_hash_hex,
        tx_type="approve",
        token_to=info["symbol"],
        amount_to=amount,
        chain=chain,
    )

    if notify:
        notify_money(
            f"📤 Approve [{chain}] отправлен\n"
            f"Токен: {info['symbol']}\n"
            f"Сумма: {amount_str}\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    if wait:
        receipt = _wait_receipt(w3, tx_hash_hex)
        _notify_receipt(
            receipt, tx_hash_hex, f"Approve {info['symbol']}", chain, notify
        )

    return tx_hash_hex


# ============================================================
# Transfer
# ============================================================

def transfer_token(
    from_label_or_address: str,
    token_address: str,
    to_address: str,
    amount: float,
    chain: str = DEFAULT_CHAIN,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """Отправляет ERC-20 токены с одного кошелька на другой."""
    from src.modules.wallets.manager import get_private_key

    info = get_token_info(token_address, chain=chain)
    if info is None:
        return None

    from_addr = _resolve_wallet(from_label_or_address)
    if from_addr is None:
        if notify:
            notify_error(f"Кошелёк не найден: {from_label_or_address}")
        return None

    proxy = get_proxy_for_wallet(from_addr)
    w3 = get_web3(chain=chain, proxy=proxy)

    to_addr = Web3.to_checksum_address(to_address)

    private_key = get_private_key(from_addr)
    if private_key is None:
        if notify:
            notify_error("Не удалось расшифровать ключ")
        return None

    balance = get_token_balance(from_addr, token_address, chain=chain)
    if balance is None or balance < amount:
        msg = (
            f"Недостаточно {info['symbol']} [{chain}]: есть "
            f"{balance or 0}, нужно {amount}"
        )
        if notify:
            notify_error(msg)
        return None

    token = w3.eth.contract(address=info["address"], abi=ERC20_ABI)
    amount_raw = int(amount * (10 ** info["decimals"]))

    nonce = w3.eth.get_transaction_count(from_addr, "pending")
    chain_id = w3.eth.chain_id

    tx = token.functions.transfer(to_addr, amount_raw).build_transaction({
        "from": from_addr,
        "nonce": nonce,
        "chainId": chain_id,
        "gas": 100_000,
    })

    eip1559 = _build_eip1559_fees(w3)
    if eip1559:
        tx.update(eip1559)
        tx["type"] = 2
    else:
        tx["gasPrice"] = w3.eth.gas_price

    log.info(f"Transfer [{chain}] {amount} {info['symbol']} → {to_addr[:10]}...")

    tx_hash_hex = _sign_and_send(
        w3, from_addr, tx, private_key, notify,
        f"Transfer {info['symbol']}",
    )
    if tx_hash_hex is None:
        return None

    log_transaction(
        wallet_address=from_addr,
        tx_hash=tx_hash_hex,
        tx_type="transfer",
        token_from=info["symbol"],
        amount_from=amount,
        chain=chain,
    )

    if notify:
        notify_money(
            f"💸 Transfer [{chain}] {amount} {info['symbol']}\n"
            f"Куда: {to_addr[:10]}...\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    if wait:
        receipt = _wait_receipt(w3, tx_hash_hex)
        _notify_receipt(
            receipt, tx_hash_hex, f"Transfer {info['symbol']}", chain, notify
        )

    return tx_hash_hex


__all__ = [
    "TOKENS",
    "get_token_info",
    "get_token_balance",
    "get_allowance",
    "approve",
    "transfer_token",
    "ERC20_ABI",
    "MAX_UINT256",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.modules.executor.erc20
    log.info("Тест erc20 — только чтение")

    # USDC info по всем трём сетям
    for chain in ("polygon", "base", "linea"):
        usdc = TOKENS[chain]["USDC"]
        info = get_token_info(usdc, chain=chain)
        if info:
            print(f"✅ [{chain}] USDC: {info['symbol']} | {info['decimals']} dec")
        else:
            print(f"❌ [{chain}] USDC: не смог получить info")

    # Баланс USDC на farm-01
    from src.modules.wallets.manager import get_all_wallets
    wallets = get_all_wallets()
    if wallets:
        addr = wallets[0].address
        bal = get_token_balance(addr, TOKENS["polygon"]["USDC"], chain="polygon")
        print(f"USDC баланс [polygon] {addr[:10]}...: {bal}")
    else:
        print("(кошельков нет)")
