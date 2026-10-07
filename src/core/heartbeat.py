"""
src/core/heartbeat.py
Health-check для бота: два режима.

1) Write mode (по умолчанию) — записывает текущий timestamp в файл.
   Запускается из scheduler каждые 5 минут.

2) Check mode (--check) — проверяет timestamp.
   Если файл старше STALE_AFTER_MINUTES — уведомление в TG.
   Запускается из cron каждые 5 минут.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.core.logger import get_logger

log = get_logger(__name__)

HEARTBEAT_FILE = Path("/root/airdrop-hunter/data/heartbeat.txt")
STALE_AFTER_SECONDS = 15 * 60  # 15 минут
def write_heartbeat() -> None:
    """Записывает текущий timestamp в файл heartbeat."""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).timestamp()
    HEARTBEAT_FILE.write_text(str(ts))
    log.debug(f"Heartbeat updated: {ts}")


def check_heartbeat() -> bool:
    """Проверяет heartbeat. True если свежий, False если устарел/отсутствует."""
    if not HEARTBEAT_FILE.exists():
        log.error("Heartbeat файл не существует!")
        return False

    try:
        last_ts = float(HEARTBEAT_FILE.read_text().strip())
    except Exception as e:
        log.error(f"Не могу прочитать heartbeat: {e}")
        return False

    age = time.time() - last_ts
    log.info(f"Heartbeat возраст: {age:.0f} сек ({age/60:.1f} мин)")

    if age > STALE_AFTER_SECONDS:
        log.error(f"Heartbeat устарел на {age/60:.1f} мин (лимит {STALE_AFTER_SECONDS/60:.0f} мин)")
        return False

    return True


if __name__ == "__main__":
    if "--check" in sys.argv:
        ok = check_heartbeat()
        if not ok:
            from src.core.notifier import notify_error
            notify_error(f"⚠️ Bot завис! Heartbeat устарел >15 мин. Требуется рестарт.")
            sys.exit(1)
        sys.exit(0)
    else:
        write_heartbeat()
        sys.exit(0)
