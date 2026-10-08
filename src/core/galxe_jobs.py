"""
src/core/galxe_jobs.py
Scheduler job: авто-скан Galxe.
"""

from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_scan

log = get_logger(__name__)


def job_scan_galxe() -> None:
    """Сканирует Galxe на активные квесты, шлёт топ-5 в Telegram."""
    log.info("[scheduler] Запуск сканирования Galxe...")
    try:
        from src.modules.scanner.galxe import fetch_active_quests

        quests = fetch_active_quests(limit=15, notify=False)

        if not quests:
            log.warning("[scheduler] Galxe: активных не найдено")
            return

        log.success(f"[scheduler] Galxe: {len(quests)}")

        lines = ["Активные квесты Galxe:"]
        for i, q in enumerate(quests[:5], 1):
            lines.append(f"{i}. {q['name']}")
            lines.append(f"    {q['url']}")
        lines.append(f"Всего: {len(quests)}")
        notify_scan("\n".join(lines))

    except Exception as e:
        log.exception("[scheduler] Ошибка в job_scan_galxe")
        notify_error(f"Galxe scanner упал: {str(e)[:200]}")
