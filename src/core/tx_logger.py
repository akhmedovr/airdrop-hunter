"""
src/core/tx_logger.py
Единая точка логирования транзакций в БД.

Зачем: analytics/pnl.py считает газ, ROI и прибыль. Для этого нужно,
чтобы каждая отправленная транзакция (approve, transfer, swap, send)
падала в таблицу Transaction. Модуль даёт две функции:

    - log_transaction(...)          — создать запись (status=pending)
    - update_transaction_status(...) — обновить после receipt

Интеграция (пример):
    from src.core.tx_logger import log_transaction, update_transaction_status

    tx_hash = _sign_and_send(...)
    log_transaction(
        wallet_address=owner,
        tx_hash=tx_hash,
        tx_type="approve",
        token_from=None,
        token_to=info["symbol"],
        amount_from=None,
        amount_to=amount,
        chain="polygon",
    )

    # после получения receipt
    update_transaction_status(tx_hash, status="success", gas_native=fee_matic)
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from src.core.database import Transaction, Wallet, get_session
from src.core.logger import get_logger

log = get_logger(__name__)


def _resolve_wallet_id(session, wallet_address: str) -> Optional[int]:
    """Находит wallet_id по адресу. None, если кошелёк не в БД."""
    if not wallet_address:
        return None
    wallet = session.execute(
        select(Wallet).where(Wallet.address == wallet_address)
    ).scalar_one_or_none()
    return wallet.id if wallet else None


def log_transaction(
    wallet_address: str,
    tx_hash: str,
    tx_type: str,
    token_from: Optional[str] = None,
    token_to: Optional[str] = None,
    amount_from: Optional[float] = None,
    amount_to: Optional[float] = None,
    gas_usd: float = 0.0,
    chain: str = "polygon",
    status: str = "pending",
) -> Optional[Transaction]:
    """
    Создаёт запись о транзакции.

    tx_type: swap | approve | transfer | send | receive | bridge
    status:  pending | success | failed

    Возвращает созданную Transaction или None при ошибке.
    Никогда не бросает исключение — логирование не должно ломать основной поток.
    """
    try:
        with get_session() as session:
            wallet_id = _resolve_wallet_id(session, wallet_address)
            if wallet_id is None:
                log.warning(
                    f"tx_logger: кошелёк {wallet_address[:10]}... не в БД, "
                    f"транзакция не записана ({tx_type} {tx_hash[:12]}...)"
                )
                return None

            tx = Transaction(
                wallet_id=wallet_id,
                tx_hash=tx_hash,
                chain=chain,
                tx_type=tx_type,
                token_from=token_from,
                token_to=token_to,
                amount_from=amount_from,
                amount_to=amount_to,
                gas_usd=gas_usd,
                status=status,
            )
            session.add(tx)
            session.commit()
            session.refresh(tx)

            log.debug(
                f"tx_logger: записана {tx_type} {tx_hash[:12]}... "
                f"({wallet_address[:10]}..., status={status})"
            )
            return tx
    except Exception as e:
        log.error(f"tx_logger: не смог записать транзакцию {tx_hash[:12]}...: {e}")
        return None


def update_transaction_status(
    tx_hash: str,
    status: str,
    gas_usd: Optional[float] = None,
) -> bool:
    """
    Обновляет статус транзакции по tx_hash.

    status: pending | success | failed
    gas_usd: если задан — обновит поле gas_usd в БД.

    Возвращает True, если запись найдена и обновлена.
    Никогда не бросает исключение.
    """
    if not tx_hash:
        return False

    try:
        with get_session() as session:
            tx = session.execute(
                select(Transaction).where(Transaction.tx_hash == tx_hash)
            ).scalar_one_or_none()

            if tx is None:
                log.warning(f"tx_logger: {tx_hash[:12]}... не найдена в БД")
                return False

            tx.status = status
            if gas_usd is not None:
                tx.gas_usd = gas_usd
            session.commit()

            log.debug(f"tx_logger: {tx_hash[:12]}... → {status}")
            return True
    except Exception as e:
        log.error(f"tx_logger: не смог обновить {tx_hash[:12]}...: {e}")
        return False


__all__ = [
    "log_transaction",
    "update_transaction_status",
]
