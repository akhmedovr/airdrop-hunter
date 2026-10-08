"""
src/core/backup_telegram.py
Отправляет последний бэкап из ~/backups/ в Telegram.

Запуск (из cron или вручную):
    python -m src.core.backup_telegram
"""

import glob
import os
import sys
from pathlib import Path

import httpx

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
BACKUP_DIR = Path("/root/backups")
def _find_latest_backup() -> Path:
    """Находит самый свежий backup_*.tar.gz.enc. Кидает FileNotFoundError если нет."""
    pattern = str(BACKUP_DIR / "backup_*.tar.gz.enc")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"Нет бэкапов в {BACKUP_DIR}")
    files.sort(key=os.path.getmtime, reverse=True)
    return Path(files[0])


def send_backup() -> bool:
    """Отправляет свежий бэкап в Telegram. Возвращает True/False."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы")
        return False

    try:
        archive = _find_latest_backup()
    except FileNotFoundError as e:
        log.error(str(e))
        return False

    size_kb = archive.stat().st_size / 1024
    log.info(f"Отправляю бэкап: {archive.name} ({size_kb:.1f} КБ)")

    url = f"{TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendDocument"

    try:
        with open(archive, "rb") as f:
            files = {"document": (archive.name, f, "application/gzip")}
            data = {"chat_id": settings.TELEGRAM_CHAT_ID, "caption": f"🗄 Бэкап Airdrop Hunter: {archive.name}"}
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, data=data, files=files)
                response.raise_for_status()
                result = response.json()
    except Exception as e:
        log.exception(f"Ошибка отправки в Telegram: {e}")
        return False

    if not result.get("ok"):
        log.error(f"Telegram ответил ошибкой: {result}")
        return False

    log.success(f"Бэкап отправлен: {archive.name}")
    return True


if __name__ == "__main__":
    ok = send_backup()
    sys.exit(0 if ok else 1)
