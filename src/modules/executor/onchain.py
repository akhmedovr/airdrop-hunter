"""
src/modules/executor/onchain.py
Отправка on-chain транзакций (нативная валюта: POL/ETH). Мультичейн.

Возможности:
    - Отправка native между кошельками (polygon / base / linea)
    - EIP-1559 с fallback на legacy gas
    - Оценка газа с запасом 20%
    - Ожидание receipt с таймаутом
    - Логирование в БД (tx_logger)
    - Уведомления в Telegram

Использование:
    from src.modules.executor.onchain import send_native

    # Polygon (по умолчанию)
    tx_hash = send_native(
        from_label_or_address="farm-01",
        to_address="0x...",
        amount_native=0.01,
    )

    # Base
    tx_hash = send_native(
        from_label_or_address="farm-01",
        to_address="0x...",
        amount_native=0.001,
        chain="base",
    )
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
    get_native_symbol,
    get_web3,
)
from src.core.safe_tx import safe_send
from src.core.tx_logger import log_transaction, update_transaction_status


log = get_logger(__name__)

# Минимальный резерв газа (в нативной валюте), чтобы не уйти в минус
MIN_GAS_RESERVE_NATIVE = 0.001

# Таймаут ожидания receipt (секунды)
RECEIPT_TIMEOUT = 180

# Минимальный приоритет (30 Gwei — стандарт)
PRIORITY_FEE_GWEI = 30


# ============================================================
# Вспомогательные
# ============================================================

def _resolve_wallet(query: str) -> Optional[str]:
    """Возвращает checksum-адрес по метке или адресу. None если не найден."""
    from src.modules.wallets.manager import get_all_wallets

    if query.startswith("0x") and len(query) == 42:
        return Web3.to_checksum_address(query)

    for w in get_all_wallets():
        if w.label.lower() == query.lower():
            return Web3.to_checksum_address(w.address)

    return None


def _estimate_gas_limit(w3: Web3, tx: dict) -> int:
    """Оценивает gas limit с запасом 20%. Fallback 21000."""
    try:
        estimate = w3.eth.estimate_gas(tx)
        return int(estimate * 1.2)
    except Exception as e:
        log.warning(f"Не смог оценить gas limit: {e}. Fallback 21000.")
        return 21000


def _build_eip1559_fees(w3: Web3) -> dict:
    """Собирает EIP-1559 комиссии. Пустой dict, если сеть не поддерживает."""
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    if base_fee is None:
        return {}

    priority = w3.to_wei(PRIORITY_FEE_GWEI, "gwei")
    max_fee = base_fee * 2 + priority

    return {
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority,
    }


def _wait_for_receipt(
    w3: Web3,
    tx_hash: bytes,
    timeout: int = RECEIPT_TIMEOUT,
) -> Optional[TxReceipt]:
    """Ждёт receipt с таймаутом. None если не дождались."""
    started = time.time()
    while time.time() - started < timeout:
        try:
            return w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            time.sleep(3)
        except Exception as e:
            log.warning(f"Ошибка при ожидании receipt: {e}")
            time.sleep(3)
    return None


# ============================================================
# Основная функция
# ============================================================

def send_native(
    from_label_or_address: str,
    to_address: str,
    amount_native: float,
    chain: str = DEFAULT_CHAIN,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """
    Отправляет native (POL/ETH) с одного кошелька на другой.

    Args:
        from_label_or_address: метка или адрес отправителя
        to_address: адрес получателя
        amount_native: сколько native отправить
        chain: сеть (polygon | base | linea)
        wait: ждать ли подтверждения
        notify: уведомлять ли в Telegram

    Returns:
        tx_hash (hex string) или None при ошибке.
    """
    from src.modules.wallets.manager import get_private_key

    native_sym = get_native_symbol(chain)

    # 1. Определяем адрес отправителя
    from_address = _resolve_wallet(from_label_or_address)
    if from_address is None:
        log.error(f"Кошелёк не найден: {from_label_or_address}")
        if notify:
            notify_error(f"Кошелёк не найден: {from_label_or_address}")
        return None

    # 2. Прокси для кошелька + Web3 в нужной сети
    proxy = get_proxy_for_wallet(from_address)
    w3 = get_web3(chain=chain, proxy=proxy)

    to_address = Web3.to_checksum_address(to_address)

    # 3. Приватный ключ
    private_key = get_private_key(from_address)
    if private_key is None:
        log.error(f"Не удалось расшифровать ключ для {from_address[:10]}...")
        if notify:
            notify_error("Не удалось расшифровать приватный ключ")
        return None

    # 4. Проверяем баланс
    balance_wei = w3.eth.get_balance(from_address)
    balance_native = float(Web3.from_wei(balance_wei, "ether"))

    if balance_native < amount_native + MIN_GAS_RESERVE_NATIVE:
        msg = (
            f"Недостаточно {native_sym} [{chain}]: есть {balance_native:.6f}, "
            f"нужно {amount_native:.6f} (+ {MIN_GAS_RESERVE_NATIVE} на газ)"
        )
        log.error(msg)
        if notify:
            notify_error(msg)
        return None

    # 5. Chain ID и nonce
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(from_address, "pending")

    # 6. Собираем транзакцию
    amount_wei = w3.to_wei(amount_native, "ether")

    tx: dict = {
        "from": from_address,
        "to": to_address,
        "value": amount_wei,
        "nonce": nonce,
        "chainId": chain_id,
    }

    # 7. EIP-1559 или legacy
    eip1559 = _build_eip1559_fees(w3)
    if eip1559:
        tx.update(eip1559)
        tx["type"] = 2
    else:
        tx["gasPrice"] = w3.eth.gas_price

    # 8. Gas limit
    tx["gas"] = _estimate_gas_limit(w3, tx)

    # 9. Подписываем
    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception("Ошибка подписи транзакции")
        if notify:
            notify_error(f"Ошибка подписи: {str(e)[:150]}")
        return None

    # 10. Отправляем
    try:
        tx_hash = safe_send(w3, signed)
    except Exception as e:
        log.exception("Ошибка отправки транзакции")
        if notify:
            notify_error(f"Ошибка отправки: {str(e)[:150]}")
        return None

    tx_hash_hex = tx_hash.hex()
    log.success(f"[{chain}] TX отправлена: {tx_hash_hex}")

    # 11. Логируем в БД (status=pending)
    log_transaction(
        wallet_address=from_address,
        tx_hash=tx_hash_hex,
        tx_type="send",
        token_from=native_sym,
        amount_from=amount_native,
        chain=chain,
    )

    if notify:
        notify_money(
            f"💸 Отправлено [{chain}]\n"
            f"{amount_native:.6f} {native_sym}\n"
            f"от: {from_label_or_address}\n"
            f"куда: {to_address[:10]}...\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    # 12. Ждём receipt
    if wait:
        receipt = _wait_for_receipt(w3, tx_hash)
        if receipt is None:
            update_transaction_status(tx_hash_hex, status="failed")
            if notify:
                notify_error(
                    f"TX не подтверждена за {RECEIPT_TIMEOUT}c: "
                    f"{tx_hash_hex[:20]}..."
                )
            return tx_hash_hex

        status = receipt.get("status")
        gas_used = receipt.get("gasUsed", 0)
        effective_price = receipt.get("effectiveGasPrice", 0)
        fee_wei = gas_used * effective_price
        fee_native = float(Web3.from_wei(fee_wei, "ether"))

        if status == 1:
            update_transaction_status(
                tx_hash_hex, status="success", gas_usd=fee_native
            )
            log.success(
                f"[{chain}] TX подтверждена. Комиссия: {fee_native:.8f} {native_sym}"
            )
            if notify:
                notify_success(
                    f"✅ TX подтверждена [{chain}]\n"
                    f"Комиссия: {fee_native:.8f} {native_sym}\n"
                    f"Блок: {receipt.get('blockNumber')}"
                )
        else:
            update_transaction_status(tx_hash_hex, status="failed")
            log.error(f"[{chain}] TX провалена (status=0): {tx_hash_hex}")
            if notify:
                notify_error(f"❌ TX провалена: {tx_hash_hex[:20]}...")

    return tx_hash_hex


# Обратная совместимость: старое имя аргумента amount_matic
def send_native_legacy(
    from_label_or_address: str,
    to_address: str,
    amount_matic: float,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """Алиас для обратной совместимости со старым именем amount_matic."""
    return send_native(
        from_label_or_address=from_label_or_address,
        to_address=to_address,
        amount_native=amount_matic,
        chain="polygon",
        wait=wait,
        notify=notify,
    )


__all__ = [
    "send_native",
    "send_native_legacy",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.modules.executor.onchain
    log.info("Тест executor/onchain — только чтение")

    for chain in ("polygon", "base", "linea"):
        try:
            w3 = get_web3(chain=chain)
            native = get_native_symbol(chain)
            print(
                f"✅ [{chain}] chain_id={w3.eth.chain_id} | "
                f"блок={w3.eth.block_number} | native={native}"
            )
        except Exception as e:
            print(f"❌ [{chain}]: {e}")
