"""
src/core/tx_reconciler.py
Сверка pending-транзакций с блокчейном.

Проблема: если receipt не получен за RECEIPT_TIMEOUT, транза
остаётся в status='pending' навсегда — хотя реально уже прошла.

Решение: джоб scheduler каждые 30 минут проверяет pending-транзы
и обновляет статус (success/failed) + газ.
"""

from datetime import datetime, timedelta
from typing import Optional

from src.core.database import SessionLocal, Transaction
from src.core.logger import get_logger
from src.core.rpc import CHAINS, get_web3
from src.core.tx_logger import update_transaction_status


log = get_logger(__name__)


# Через сколько после создания транзы начинать сверку (сек)
MIN_AGE_SECONDS = 300   # 5 минут

# Через сколько после создания считать транзу безнадёжной (сек)
GIVE_UP_AFTER_HOURS = 6


def _check_receipt(chain: str, tx_hash: str) -> Optional[dict]:
    """
    Возвращает dict {status: int, block: int, gas_used: int,
    eff_price: int} или None если receipt ещё не доступен.
    """
    if chain not in CHAINS:
        log.warning(f"tx_reconciler: неизвестная сеть {chain}")
        return None

    try:
        w3 = get_web3(chain=chain)
        r = w3.eth.get_transaction_receipt(tx_hash)
        return {
            "status": int(r.get("status", 0)),
            "block": int(r.get("blockNumber", 0)),
            "gas_used": int(r.get("gasUsed", 0)),
            "eff_price": int(r.get("effectiveGasPrice", 0)),
        }
    except Exception:
        return None


def reconcile_pending() -> dict:
    """
    Сверяет все pending-транзы старше MIN_AGE_SECONDS с блокчейном.

    Возвращает dict со статистикой: {checked, updated, still_pending, failed_giveup}.
    """
    stats = {"checked": 0, "updated": 0, "still_pending": 0, "giveup": 0}

    cutoff = datetime.utcnow() - timedelta(seconds=MIN_AGE_SECONDS)
    giveup_cutoff = datetime.utcnow() - timedelta(hours=GIVE_UP_AFTER_HOURS)

    with SessionLocal() as s:
        txs = s.query(Transaction).filter(
            Transaction.status == "pending"
        ).all()
        candidates = [t for t in txs if t.created_at and t.created_at < cutoff]

    if not candidates:
        log.debug("tx_reconciler: pending-транз нет")
        return stats

    log.info(f"tx_reconciler: на сверку {len(candidates)} pending-транз")

    for tx in candidates:
        stats["checked"] += 1
        h = tx.tx_hash
        chain = tx.chain or "polygon"

        if not h:
            log.warning(f"tx_reconciler: id={tx.id} без tx_hash → failed")
            update_transaction_status(h, status="failed")
            stats["updated"] += 1
            continue

        receipt = _check_receipt(chain, h)

        if receipt is None:
            # Ещё не нашли receipt
            if tx.created_at and tx.created_at < giveup_cutoff:
                log.warning(
                    f"tx_reconciler: id={tx.id} {h[:20]}… "
                    f"висит > {GIVE_UP_AFTER_HOURS}ч → failed"
                )
                update_transaction_status(h, status="failed")
                stats["giveup"] += 1
                stats["updated"] += 1
            else:
                stats["still_pending"] += 1
            continue

        # Есть receipt
        new_status = "success" if receipt["status"] == 1 else "failed"
        gas_native = (
            receipt["gas_used"] * receipt["eff_price"]
        ) / 1e18

        log.info(
            f"tx_reconciler: id={tx.id} {h[:20]}… → {new_status} "
            f"(block={receipt['block']}, gas={gas_native:.8f})"
        )
        update_transaction_status(
            h, status=new_status, gas_usd=gas_native
        )
        stats["updated"] += 1

    log.success(
        f"tx_reconciler: сверено {stats['checked']}, "
        f"обновлено {stats['updated']}, "
        f"ещё pending {stats['still_pending']}, "
        f"give-up {stats['giveup']}"
    )
    return stats


__all__ = ["reconcile_pending"]
