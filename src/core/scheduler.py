"""
src/core/scheduler.py
Планировщик периодических задач через APScheduler.
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
from src.core.daily_reports import job_daily_profit
from src.core.daily_reports import job_daily_today
from src.core.galxe_jobs import job_scan_galxe
from src.core.heartbeat import write_heartbeat
from src.core.logger import get_logger
from src.core.notifier import notify_error
from src.core.notifier import notify_scan
from src.core.notifier import notify_success
from src.core.notifier import notify_warning
from src.core.tx_reconciler import reconcile_pending

log = get_logger(__name__)

SCAN_INTERVAL_HOURS = 6
GALXE_SCAN_INTERVAL_HOURS = 6
BALANCE_CHECK_INTERVAL_HOURS = 24
RPC_PING_INTERVAL_HOURS = 1
HEARTBEAT_INTERVAL_MINUTES = 5
RECONCILE_INTERVAL_MINUTES = 30


def job_scan_airdrops() -> None:
    log.info("[scheduler] DeFiLlama scan")
    try:
        from src.modules.scanner.defillama import scan_polygon_candidates
        results = scan_polygon_candidates(
            min_tvl=500_000,
            max_tvl=500_000_000,
            limit=10,
            notify=False,
        )
        if not results:
            return
        lines = ["Auto-scan DeFiLlama:"]
        for i, c in enumerate(results[:5], 1):
            tvl_m = c["tvl_usd"] / 1_000_000
            lines.append(
                f"{i}. {c['name']} ({c['category']}) - ${tvl_m:.1f}M"
            )
        lines.append(f"\nVsego: {len(results)}")
        notify_scan("\n".join(lines))
    except Exception as e:
        log.exception("[scheduler] scan_airdrops error")
        notify_error(f"Scanner fall: {str(e)[:200]}")


def job_check_balances() -> None:
    log.info("[scheduler] Balance check")
    try:
        from src.core.rpc import get_balance_native
        from src.core.proxy import get_proxy_for_wallet
        from src.modules.wallets.manager import get_all_wallets
        from src.modules.wallets.manager import update_balance

        wallets = get_all_wallets()
        if not wallets:
            return

        funded = []
        low = []

        for w in wallets:
            try:
                proxy = get_proxy_for_wallet(w.address)
                bal = get_balance_native(
                    w.address, chain="polygon", proxy=proxy
                )
                update_balance(w.address, bal)
                old = float(w.balance_usd or 0.0)
                if bal > 0 and old == 0:
                    funded.append((w.label, bal))
                if bal < 2.0:
                    low.append((w.label, bal))
                log.info(f"[scheduler] {w.label}: {bal:.4f} MATIC")
            except Exception as e:
                log.warning(f"[scheduler] {w.address[:10]} err: {e}")

        if funded:
            lines = ["Wallets popolneny:"]
            for label, bal in funded:
                lines.append(f"- {label}: {bal:.4f} MATIC")
            notify_success("\n".join(lines))

        if low:
            for lbl, bl in low:
                notify_warning(f"Low gas: {lbl} - {bl:.4f} POL")
    except Exception as e:
        log.exception("[scheduler] check_balances error")
        notify_error(f"Balance check fall: {str(e)[:200]}")


def job_ping_rpc() -> None:
    log.debug("[scheduler] Ping RPC")
    try:
        from src.core.rpc import get_active_rpc, get_web3
        old_rpc = get_active_rpc()
        w3 = get_web3(force_reconnect=True)
        new_rpc = get_active_rpc()

        if not w3.is_connected():
            notify_warning("RPC nedostupen")
            return
        if old_rpc and new_rpc and old_rpc != new_rpc:
            log.warning(f"[scheduler] RPC changed: {old_rpc} -> {new_rpc}")
            notify_warning(f"RPC smenen: {new_rpc}")
        block = w3.eth.block_number
        log.debug(f"[scheduler] RPC OK, block #{block}")
    except Exception as e:
        log.exception("[scheduler] ping_rpc error")
        notify_error(f"RPC ping fall: {str(e)[:200]}")


def job_reconcile_pending() -> None:
    log.debug("[scheduler] Reconcile pending")
    try:
        stats = reconcile_pending()
        if stats.get("updated", 0) > 0:
            log.success(
                f"[scheduler] reconciler updated {stats['updated']} tx"
            )
    except Exception as e:
        log.exception("[scheduler] reconcile error")


def _run_with_timeout(func: Callable[[], None], name: str) -> None:
    started = datetime.now(timezone.utc)
    log.info(f"[scheduler] >> {name} start")
    try:
        func()
    except Exception:
        log.exception(f"[scheduler] xx {name} crashed")
    finally:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info(f"[scheduler] << {name} done in {elapsed:.1f}s")


def _graceful_shutdown(signum, frame) -> None:
    log.info("[scheduler] Shutdown signal")
    sys.exit(0)


def run_scheduler() -> None:
    log.info("=" * 60)
    log.info("Airdrop Hunter - Scheduler")
    log.info("=" * 60)

    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        lambda: _run_with_timeout(job_scan_airdrops, "scan_airdrops"),
        trigger=IntervalTrigger(hours=SCAN_INTERVAL_HOURS),
        id="scan_airdrops",
        name="DeFiLlama scan",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_check_balances, "check_balances"),
        trigger=IntervalTrigger(hours=BALANCE_CHECK_INTERVAL_HOURS),
        id="check_balances",
        name="Wallet balances",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_ping_rpc, "ping_rpc"),
        trigger=IntervalTrigger(hours=RPC_PING_INTERVAL_HOURS),
        id="ping_rpc",
        name="RPC healthcheck",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        write_heartbeat,
        trigger=IntervalTrigger(minutes=HEARTBEAT_INTERVAL_MINUTES),
        id="heartbeat",
        name="Heartbeat",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        job_scan_galxe,
        trigger=IntervalTrigger(hours=GALXE_SCAN_INTERVAL_HOURS),
        id="scan_galxe",
        name="Galxe scan",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(auto_swap_job, "auto_swap"),
        trigger=CronTrigger(hour="7-18", minute="0", jitter=1800),
        id="auto_swap",
        name="Auto swap",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_daily_today, "daily_today"),
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_today",
        name="Daily morning",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_daily_profit, "daily_profit"),
        trigger=CronTrigger(hour=19, minute=30),
        id="daily_profit",
        name="Daily evening",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        lambda: _run_with_timeout(job_reconcile_pending, "reconcile"),
        trigger=IntervalTrigger(minutes=RECONCILE_INTERVAL_MINUTES),
        id="reconcile_pending",
        name="TX reconciler",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    log.success("Scheduler started")
    notify_success(
        f"Scheduler started\n"
        f"scan: {SCAN_INTERVAL_HOURS}h\n"
        f"balances: {BALANCE_CHECK_INTERVAL_HOURS}h\n"
        f"rpc: 1h\n"
        f"auto_swap: 10-22 MSK\n"
        f"daily_today: 09 MSK\n"
        f"daily_profit: 22:30 MSK\n"
        f"reconcile: {RECONCILE_INTERVAL_MINUTES}m"
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[scheduler] Stop")


__all__ = ["run_scheduler"]


if __name__ == "__main__":
    run_scheduler()
