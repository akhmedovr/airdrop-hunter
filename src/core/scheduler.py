"""
src/core/scheduler.py
Планировщик периодических задач через APScheduler.

Задачи:
    - Каждые N часов — сканировать DeFiLlama на новые аирдроп-кандидаты
    - Каждые 24 часа — обновлять балансы кошельков
    - Каждый час — пинговать RPC (защита от простоя)

Запуск:
    python -m src.core.scheduler
"""

import signal
import sys
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.core.config import settings
from src.core.logger import get_logger
from src.core.notifier import (
    notify_error,
    notify_scan,
    notify_success,
    notify_warning,
)

log = get_logger(__name__)

# Интервалы задач (в часах). Можно будет вынести в .env позже.
SCAN_INTERVAL_HOURS = 6
BALANCE_CHECK_INTERVAL_HOURS = 24
RPC_PING_INTERVAL_HOURS = 1


# --- Задачи ---

def job_scan_airdrops() -> None:
    """
    Сканирует DeFiLlama на кандидатов.
    Отправляет топ-5 в Telegram (если есть результат).
    """
    log.info("📡 [scheduler] Запуск авто-сканирования DeFiLlama...")
    try:
        from src.modules.scanner.defillama import scan_polygon_candidates

        results = scan_polygon_candidates(
            min_tvl=500_000,
            max_tvl=500_000_000,
            limit=10,
            notify=False,  # сами отправим — чтобы избежать дубля
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
    """
    Обновляет балансы всех farming-кошельков.
    Если у кошелька появились MATIC — присылает уведомление.
    """
    log.info("💰 [scheduler] Проверка балансов кошельков...")
    try:
        from src.core.rpc import get_balance_matic
        from src.modules.wallets.manager import (
            get_all_wallets,
            update_balance,
        )

        wallets = get_all_wallets()
        if not wallets:
            log.info("[scheduler] Кошельков нет — пропуск")
            return

        funded: list[tuple[str, float]] = []

        for w in wallets:
            try:
                bal = get_balance_matic(w.address)
                update_balance(w.address, bal)

                # Если баланс раньше был 0, а теперь есть — это важно
                old_bal = float(w.balance_usd or 0.0)
                if bal > 0 and old_bal == 0:
                    funded.append((w.label, bal))

                log.info(f"[scheduler] {w.label}: {bal:.4f} MATIC")
            except Exception as e:
                log.warning(f"[scheduler] Не смог проверить {w.address[:10]}: {e}")

        if funded:
            lines = ["💰 Кошельки пополнены:"]
            for label, bal in funded:
                lines.append(f"• {label}: {bal:.4f} MATIC")
            notify_success("\n".join(lines))

    except Exception as e:
        log.exception("[scheduler] Ошибка в job_check_balances")
        notify_error(f"Проверка балансов упала: {str(e)[:200]}")


def job_ping_rpc() -> None:
    """
    Проверяет, что активный RPC жив. Если нет — пробует переподключиться.
    При смене endpoint'а — уведомление.
    """
    log.debug("[scheduler] Пинг RPC...")
    try:
        from src.core.rpc import get_active_rpc, get_web3

        old_rpc = get_active_rpc()
        w3 = get_web3(force_reconnect=True)  # принудительно ищем живой
        new_rpc = get_active_rpc()

        if not w3.is_connected():
            log.warning("[scheduler] RPC не подключён")
            notify_warning("⚠️ RPC недоступен")
            return

        if old_rpc and new_rpc and old_rpc != new_rpc:
            log.warning(f"[scheduler] RPC сменился: {old_rpc} → {new_rpc}")
            notify_warning(f"🔀 RPC сменён на: {new_rpc}")

        block = w3.eth.block_number
        log.debug(f"[scheduler] RPC OK, блок #{block}")

    except Exception as e:
        log.exception("[scheduler] Ошибка в job_ping_rpc")
        notify_error(f"RPC-пинг упал: {str(e)[:200]}")


# --- Оркестрация ---

def _run_with_timeout(func: Callable[[], None], name: str) -> None:
    """
    Обёртка для запуска задач. Ловит все исключения,
    чтобы одна упавшая задача не убила scheduler.
    """
    started = datetime.now(timezone.utc)
    log.info(f"[scheduler] ▶ {name} начался")
    try:
        func()
    except Exception:
        log.exception(f"[scheduler] ✖ {name} упал с исключением")
    finally:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info(f"[scheduler] ◀ {name} завершён за {elapsed:.1f}s")


def _graceful_shutdown(signum, frame) -> None:
    """Обработчик SIGINT/SIGTERM — корректное завершение."""
    log.info("[scheduler] Получен сигнал остановки, завершаю...")
    sys.exit(0)


def run_scheduler() -> None:
    """Запускает BlockingScheduler со всеми задачами."""
    log.info("=" * 60)
    log.info("🗓  Airdrop Hunter — Scheduler")
    log.info("=" * 60)
    log.info(f"Окружение: {settings.ENVIRONMENT}")
    log.info(
        f"Интервалы: scan={SCAN_INTERVAL_HOURS}ч, "
        f"balances={BALANCE_CHECK_INTERVAL_HOURS}ч, "
        f"rpc_ping={RPC_PING_INTERVAL_HOURS}ч"
    )

    # Обработка SIGINT/SIGTERM (Ctrl+C, pm2 stop)
    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    scheduler = BlockingScheduler(timezone="UTC")

    # Задача 1: сканирование аирдропов
    scheduler.add_job(
        lambda: _run_with_timeout(job_scan_airdrops, "scan_airdrops"),
        trigger=IntervalTrigger(hours=SCAN_INTERVAL_HOURS),
        id="scan_airdrops",
        name="DeFiLlama scan",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # запустить сразу при старте
    )

    # Задача 2: проверка балансов
    scheduler.add_job(
        lambda: _run_with_timeout(job_check_balances, "check_balances"),
        trigger=IntervalTrigger(hours=BALANCE_CHECK_INTERVAL_HOURS),
        id="check_balances",
        name="Wallet balances",
        max_instances=1,
        coalesce=True,
    )

    # Задача 3: пинг RPC
    scheduler.add_job(
        lambda: _run_with_timeout(job_ping_rpc, "ping_rpc"),
        trigger=IntervalTrigger(hours=RPC_PING_INTERVAL_HOURS),
        id="ping_rpc",
        name="RPC healthcheck",
        max_instances=1,
        coalesce=True,
    )

    log.success("Scheduler запущен. Ctrl+C для остановки.")
    notify_success(
        f"🗓 Scheduler запущен\n"
        f"scan: каждые {SCAN_INTERVAL_HOURS}ч\n"
        f"balances: каждые {BALANCE_CHECK_INTERVAL_HOURS}ч\n"
        f"rpc: каждый час"
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
]


if __name__ == "__main__":
    run_scheduler()
