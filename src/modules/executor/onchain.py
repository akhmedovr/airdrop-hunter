"""
src/modules/executor/onchain.py
Отправка on-chain транзакций (native MATIC, ERC-20).

Возможности:
    - Отправка native (MATIC) между кошельками
    - EIP-1559 с fallback на legacy gas
    - Оценка газа с запасом 20%
    - Ожидание receipt с таймаутом
    - Уведомления в Telegram

Использование:
    from src.modules.executor.onchain import send_native
    tx_hash = send_native(from_label_or_address="farm-01",
                          to_address="0x...",
                          amount_matic=0.01)
"""

import time
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound
from web3.types import TxReceipt

from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_money, notify_success
from src.core.rpc import get_web3

log = get_logger(__name__)

# Таймаут ожидания receipt (секунды)
RECEIPT_TIMEOUT = 180

# Минимальный приоритет для Polygon (30 Gwei — стандарт)
PRIORITY_FEE_GWEI = 30


def _resolve_wallet(query: str) -> Optional[str]:
    """
    Возвращает checksum-адрес по метке или адресу.
    None если не найден.
    """
    from src.modules.wallets.manager import get_all_wallets

    # Если это уже адрес
    if query.startswith("0x") and len(query) == 42:
        return Web3.to_checksum_address(query)

    # Ищем по метке
    for w in get_all_wallets():
        if w.label.lower() == query.lower():
            return Web3.to_checksum_address(w.address)

    return None


def _estimate_gas_limit(w3: Web3, tx: dict) -> int:
    """
    Оценивает gas limit с запасом 20%.
    Fallback 21000 (стандарт для native transfer).
    """
    try:
        estimate = w3.eth.estimate_gas(tx)
        return int(estimate * 1.2)
    except Exception as e:
        log.warning(f"Не смог оценить gas limit: {e}. Fallback 21000.")
        return 21000


def _build_eip1559_fees(w3: Web3) -> dict:
    """
    Собирает EIP-1559 комиссии: maxFeePerGas + maxPriorityFeePerGas.
    Возвращает пустой dict, если сеть не поддерживает EIP-1559.
    """
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


def send_native(
    from_label_or_address: str,
    to_address: str,
    amount_matic: float,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """
    Отправляет MATIC с одного кошелька на другой.

    Args:
        from_label_or_address: метка или адрес отправителя
        to_address: адрес получателя
        amount_matic: сколько MATIC отправить
        wait: ждать ли подтверждения
        notify: уведомлять ли в Telegram

    Returns:
        tx_hash (hex string) или None при ошибке.
    """
    from src.modules.wallets.manager import get_private_key

    w3 = get_web3()

    # 1. Определяем адрес отправителя
    from_address = _resolve_wallet(from_label_or_address)
    if from_address is None:
        log.error(f"Кошелёк не найден: {from_label_or_address}")
        if notify:
            notify_error(f"Кошелёк не найден: {from_label_or_address}")
        return None

    to_address = Web3.to_checksum_address(to_address)

    # 2. Получаем приватный ключ
    private_key = get_private_key(from_address)
    if private_key is None:
        log.error(f"Не удалось расшифровать ключ для {from_address[:10]}...")
        if notify:
            notify_error("Не удалось расшифровать приватный ключ")
        return None

    # 3. Проверяем баланс
    balance_wei = w3.eth.get_balance(from_address)
    balance_matic = float(Web3.from_wei(balance_wei, "ether"))

    if balance_matic < amount_matic:
        msg = (
            f"Недостаточно MATIC: есть {balance_matic:.4f}, "
            f"нужно {amount_matic:.4f}"
        )
        log.error(msg)
        if notify:
            notify_error(msg)
        return None

    # 4. Chain ID и nonce
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(from_address, "pending")

    # 5. Собираем транзакцию
    amount_wei = w3.to_wei(amount_matic, "ether")

    tx: dict = {
        "from": from_address,
        "to": to_address,
        "value": amount_wei,
        "nonce": nonce,
        "chainId": chain_id,
    }

    # 6. EIP-1559 или legacy
    eip1559 = _build_eip1559_fees(w3)
    if eip1559:
        tx.update(eip1559)
        tx["type"] = 2
    else:
        tx["gasPrice"] = w3.eth.gas_price

    # 7. Gas limit
    tx["gas"] = _estimate_gas_limit(w3, tx)

    # 8. Подписываем
    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception("Ошибка подписи транзакции")
        if notify:
            notify_error(f"Ошибка подписи: {str(e)[:150]}")
        return None

    # 9. Отправляем
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    except Exception as e:
        log.exception("Ошибка отправки транзакции")
        if notify:
            notify_error(f"Ошибка отправки: {str(e)[:150]}")
        return None

    tx_hash_hex = tx_hash.hex()
    log.success(f"TX отправлена: {tx_hash_hex}")

    if notify:
        notify_money(
            f"💸 Отправлено {amount_matic:.4f} MATIC\n"
            f"от: {from_label_or_address}\n"
            f"куда: {to_address[:10]}...\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    # 10. Ждём receipt
    if wait:
        receipt = _wait_for_receipt(w3, tx_hash)
        if receipt is None:
            if notify:
                notify_error(
                    f"TX не подтверждена за {RECEIPT_TIMEOUT}с: "
                    f"{tx_hash_hex[:20]}..."
                )
            return tx_hash_hex

        status = receipt.get("status")
        gas_used = receipt.get("gasUsed", 0)
        effective_price = receipt.get("effectiveGasPrice", 0)
        fee_wei = gas_used * effective_price
        fee_matic = float(Web3.from_wei(fee_wei, "ether"))

        if status == 1:
            log.success(f"TX подтверждена. Комиссия: {fee_matic:.6f} MATIC")
            if notify:
                notify_success(
                    f"✅ TX подтверждена\n"
                    f"Комиссия: {fee_matic:.6f} MATIC\n"
                    f"Блок: {receipt.get('blockNumber')}"
                )
        else:
            log.error(f"TX провалена (status=0): {tx_hash_hex}")
            if notify:
                notify_error(f"❌ TX провалена: {tx_hash_hex[:20]}...")

    return tx_hash_hex


__all__ = [
    "send_native",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.modules.executor.onchain
    log.info("Тест executor/onchain — только информация, ничего не отправляем")
    w3 = get_web3()
    log.info(f"Активный chain ID: {w3.eth.chain_id}")
    log.info(f"RPC: {w3.provider.endpoint_uri}")
    log.info(f"Текущий блок: {w3.eth.block_number}")
