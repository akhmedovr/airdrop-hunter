"""
src/core/daily_reports.py
Ежедневные отчёты в Telegram: утро (план) и вечер (итог).

Джобы регистрируются в scheduler.py:
    - job_daily_today:  06:00 UTC = 09:00 МСК
    - job_daily_profit: 19:30 UTC = 22:30 МСК
"""

from datetime import datetime, timedelta, timezone

from src.core.database import SessionLocal, Transaction, Wallet
from src.core.logger import get_logger
from src.core.notifier import notify_scan
from src.core.planner import (
    format_progress,
    format_today,
    get_progress,
    get_today_tasks,
)

log = get_logger(__name__)


def job_daily_today() -> None:
    """Утренний отчёт: план задач на сегодня."""
    log.info("[daily_reports] Утренний отчёт...")
    try:
        tasks = get_today_tasks(limit=5)
        body = format_today(tasks)
        text = f"☀️ <b>Доброе утро!</b>\n\n{body}"
        notify_scan(text)
        log.success(f"[daily_reports] Утренний отчёт отправлен ({len(tasks)} задач)")
    except Exception as e:
        log.exception("[daily_reports] job_daily_today упал")
        # не шлём error — это не критично, просто лог


def job_daily_profit() -> None:
    """Вечерний отчёт: сводка за день + прогресс."""
    log.info("[daily_reports] Вечерний отчёт...")
    try:
        # 1. Свапы за сегодня (UTC)
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        with SessionLocal() as s:
            txs_today = list(
                s.query(Transaction)
                .filter(Transaction.created_at >= today_start)
                .all()
            )

        swaps_today = [t for t in txs_today if t.tx_type == "swap"]
        swaps_ok = [t for t in swaps_today if t.status == "success"]
        gas_today = sum(float(t.gas_usd or 0.0) for t in txs_today)

        # 2. Прогресс по кампаниям
        progress = get_progress()
        bs = progress.get("by_status", {})
        total_tasks = progress.get("total_tasks", 0)
        done = bs.get("completed", 0)

        # 3. Формат
        lines = [
            "🌙 <b>Итог дня</b>",
            "",
            f"Свапов сегодня: {len(swaps_ok)}/{len(swaps_today)}",
            f"Транзакций всего: {len(txs_today)}",
            f"Газ за день: {gas_today:.4f} MATIC",
            "",
            f"📊 Прогресс: {done}/{total_tasks}",
        ]

        notify_scan("\n".join(lines))
        log.success("[daily_reports] Вечерний отчёт отправлен")
    except Exception as e:
        log.exception("[daily_reports] job_daily_profit упал")


__all__ = [
    "job_daily_today",
    "job_daily_profit",
]
