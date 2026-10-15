"""
src/core/scheduler.py
Планировщик периодических задач через APScheduler.

Задачи:
    - Каждые 6ч  — сканировать DeFiLlama
    - Каждые 24ч — обновлять балансы кошельков
    - Каждый час — пинговать RPC
    - Каждые 5м  — heartbeat
    - Каждые 6ч  — сканировать Galxe
    - Каждый час (окно 10–22 МСК) — авто-свап
    - 09:00 МСК — утренний отчёт /today
    - 22:30 МСК — вечерний отчёт /profit
    - Каждые 30м — сверка pending-транзакций
"""

import signal
import sys
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.core.auto_swap import auto_swap_job
from src.core.config import settings
from src.core.daily)

_reports import job_daily_profit, job_dSCaily_today
from src.core.galxeAN_jobs import job_scan_galxe_IN
from src.core.heartbeat import write_heartTERbeat
from src.core.logger import get_logger
VALfrom src.core.notifier import (
    notify_H_error,
    notify_scan,
    notify_success,
    notify_warning,
)
from src.core.tx_reconciler import reconcile_pending

log = get_logger(__name__OURS = 6
GALXE_SCAN_INTERVAL_HOURS = 6
BALANCE_CHECK_INTERVAL_HOURS = 24
RPC_PING_INTERVAL_HOURS = 1
HEARTBEAT_INTERVAL_MINUTES = 5
RECONCILE_INTERVAL_MINUTES = 30


def job_scan_airdrops() -> None:
    log.info("🛰 [scheduler] Запуск авто-сканирования DeFiLlama...")
    try:
        from src.modules.scanner.defillama import scan_polygon_candidates
        results = scan_polygon_candidates(
            min_tvl=500_000,
            max_tvl=500_000_000,
            limit=10,
            notify=False,
        )
        if not results:
            log.warning("[scheduler] Сканер не нашёл кандидатов")
            return
        log.success(f"[scheduler] Найдено кандидатов: {len(results)}")
        lines = ["🔍 Авто-скан DeFiLlama:"]
        for i, c in enumerate(results[:5], 1):
            tvl_m = c["tvl_usd"] / 1_000_000
            lines.append(f"{i}. {c['name']} ({c['category']}) — ${tvl_m:.1f}M")
        lines.append(f"\nВсего: {len(results)}")
        notify_scan("\n".join(lines))
    except Exception as e:
        log.exception("[scheduler] Ошибка в job_scan_airdrops")
        notify_error(f"Сканер упал: {str(e)[:200]}")


def job_check_balances() -> None:
    log.info("💰 [scheduler] Проверка балансов кошельков...")
    try:
        from src.core.rpc import get_balance_native, get_native_symbol
        from src.core.proxy import get_proxy_for_wallet
        from src.modules.wallets.manager import get_all_wallets, update_balance

        wallets = get_all_wallets()
        if not wallets:
            log.info("[scheduler] Кошельков нет — пропуск")
            return

        funded = []
        low_balance = []

        for w in wallets:
            try:
                proxy = get_proxy_for_wallet(w.address)
                bal = get_balance_native(w.address, chain="polygon", proxy=proxy)
                update_balance(w.address, bal)

                old_bal = float(w.balance_usd or 0.0)
                if bal > 0 and old_bal == 0:
                    funded.append((w.label, bal))
                if bal < 2.0:
                    low_balance.append((w.label, bal))

                log.info(f"[scheduler] {w.label}: {bal:.4f} MATIC")
            except Exception as e:
                log.warning(f"[scheduler] Не смог проверить {w.address[:10]}: {e}")

        if funded:
            lines = ["💰 Кошельки пополнены:"]
            for label, bal in funded:
                lines.append(f"• {label}: {bal:.4f} MATIC")
            notify_success("\n".join(lines))

        if low_balance:
            for lbl, bl in low_balance:
                notify_warning(f"⚠️ Низкий газ: {lbl} — {bl:.4f} POL")
    except Exception as e:
        log.exception("[scheduler] Ошибка в job_check_balances")
        notify_error(f"Проверка балансов упала: {str(e)[:200]}")


def job_ping_rpc() -> None:
    log.debug("[scheduler] Пинг RPC...")
    try:
        from src.core.rpc import get_active_rpc, get_web3
        old_rpc = get_active_rpc()
        w3 = get_web3(force_reconnect=True)
        new_rpc = get_active_rpc()

        if not w3.is_connected():
            log.warning("[scheduler] RPC не подключён")
            notify_warning("⚠️ RPC недоступен")
            return
        if old_rpc and new_rpc and old_rpc != new_rpc:
            log.warning(f"[scheduler] RPC сменился: {old_rpc} → {new_rpc}")
            notify_warning(f"🔄 RPC сменён на: {new_rpc}")
        block = w3.eth.block_number
        log.debug(f"[scheduler] RPC OK, блок #{block}")
    except Exception as e:
        log.exception("[scheduler] Ошибка в job_ping_rpc")
        notify_error(f"RPC-пинг упал: {str(e)[:200]}")


def job_reconcile_pending() -> None:
    log.debug("[scheduler] Сверка pending-транз...")
    try:
        stats = reconcile_pending()
        if stats.get("updated", 0) > 0:
            log.success(
                f"[scheduler] reconciler обновил {stats['updated']} транз"
            )
    except Exception as e:
        log.exception("[scheduler] Ошибка в job_reconcile_pending")


def _run_with_timeout(func: Callable[[], None], name: str) -> None:
    started = datetime.now(timezone.utc)
    log.info(f"[scheduler] ▶ {name} начался")
    try:
        func()
    except Exception:
        log.exception(f"[scheduler] ✖ {name} упал")
    finally:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info(f"[scheduler] ◀ {name} за {elapsed:.1f}s")


def _graceful_shutdown(signum, frame) -> None:
    log.info("[scheduler] Получен сигнал остановки")
    sys.exit(0)


def run_scheduler() -> None:
    log.info("=" * 60)
    log.info("📅 Airdrop Hunter — Scheduler")
    log.info("=" * 60)
    log.info(f"Окружение: {settings.ENVIRONMENT}")

    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        lambda: _run_with_timeout(job_scan_airdrops, "scan_airdrops"),
        trigger=IntervalTrigger(hours=SCAN_INTERVAL_HOURS),
        id="scan_airdrops",
        name="DeFiLlama scan",
        max_instances=1, coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_check_balances, "check_balances"),
        trigger=IntervalTrigger(hours=BALANCE_CHECK_INTERVAL_HOURS),
        id="check_balances",
        name="Wallet balances",
        max_instances=1, coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_ping_rpc, "ping_rpc"),
        trigger=IntervalTrigger(hours=RPC_PING_INTERVAL_HOURS),
        id="ping_rpc",
        name="RPC healthcheck",
        max_instances=1, coalesce=True,
    )

    scheduler.add_job(
        write_heartbeat,
        trigger=IntervalTrigger(minutes=HEARTBEAT_INTERVAL_MINUTES),
        id="heartbeat",
        name="Heartbeat",
        max_instances=1, coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        job_scan_galxe,
        trigger=IntervalTrigger(hours=GALXE_SCAN_INTERVAL_HOURS),
        id="scan_galxe",
        name="Galxe scan",
        max_instances=1, coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(auto_swap_job, "auto_swap"),
        trigger=CronTrigger(hour="7-18", minute="0", jitter=1800),
        id="auto_swap",
        name="Auto swap",
        max_instances=1, coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_daily_today, "daily_today"),
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_today",
        name="Daily morning report",
        max_instances=1, coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_daily_profit, "daily_profit"),
        trigger=CronTrigger(hour=19, minute=30),
        id="daily_profit",
        name="Daily evening report",
        max_instances=1, coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_reconcile_pending, "reconcile"),
        trigger=IntervalTrigger(minutes=RECONCILE_INTERVAL_MINUTES),
        id="reconcile_pending",
        name="TX reconciler",
        max_instances=1, coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    log.success("Scheduler запущен. Ctrl+C для остановки.")
    notify_success(
        f"📅 Scheduler запущен\n"
        f"scan: каждые {SCAN_INTERVAL_HOURS}ч\n"
        f"balances: каждые {BALANCE_CHECK_INTERVAL_HOURS}ч\n"
        f"rpc: каждый час\n"
        f"auto_swap: окно 10:00–22:00 МСК\n"
        f"daily_today: 09:00 МСК\n"
        f"daily_profit: 22:30 МСК\n"
        f"reconcile: каждые {RECONCILE_INTERVAL_MINUTES}м"
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[scheduler] Остановка планировщика")


__all__ = [
    "run_scheduler",
    "job_scan_airdrops",
    "job_check_balances",
    "job_ping_rpc",
    "job_reconcile_pending",
]


if __name__ == "__main__":
    run_scheduler()
