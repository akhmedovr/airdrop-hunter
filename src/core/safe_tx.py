"""
src/core/safe_tx.py
Отправка подписанных транзакций с retry.

Проблема: RPC может моргнуть во время send_raw_transaction.
Решение: 3 попытки с exponential backoff для сетевых ошибок.

Использование:
    from src.core.safe_tx import safe_send
    tx_hash = safe_send(w3, signed)   # бросает RuntimeError при провале
"""

from typing import Any

from hexbytes import HexBytes
from requests.exceptions import ConnectionError, HTTPError, Timeout
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.logger import get_logger

log = get_logger(__name__)

# Типы исключений, при которых retry имеет смысл (сетевые проблемы)
RETRYABLE_ERRORS = (ConnectionError, Timeout, HTTPError)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    reraise=True,
)
def _try_send(w3: Any, raw_tx: bytes) -> HexBytes:
    """Одна попытка отправки. Retry-обёртка выше."""
    return w3.eth.send_raw_transaction(raw_tx)


def safe_send(w3: Any, signed_tx: Any) -> HexBytes:
    """
    Отправляет подписанную транзакцию с retry.

    Args:
        w3: Web3-инстанс
        signed_tx: результат Account.sign_transaction() (имеет .raw_transaction)

    Returns:
        HexBytes — hash отправленной транзакции.

    Raises:
        RuntimeError: если все 3 попытки провалились из-за сетевых ошибок.
    """
    raw = signed_tx.raw_transaction
    try:
        tx_hash = _try_send(w3, raw)
        log.debug(f"TX отправлена: {tx_hash.hex()[:20]}...")
        return tx_hash
    except RETRYABLE_ERRORS as e:
        log.error(f"Не удалось отправить TX после 3 попыток: {e}")
        raise RuntimeError(f"TX send failed after retries: {e}") from e


__all__ = ["safe_send", "RETRYABLE_ERRORS"]
