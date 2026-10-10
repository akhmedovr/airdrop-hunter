"""
src/core/notifier.py
Отправка уведомлений в Telegram через Bot API.

Использование:
    from src.core.notifier import notify_success, notify_error, notify_money
    notify_success("Кошелёк создан: 0x1234...")
"""

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

# Эмодзи для типов сообщений
EMOJI = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "money": "💰",
    "rocket": "🚀",
    "scan": "🔍",
    "task": "📋",
}


def is_notifier_ready() -> bool:
    """Проверяет, настроены ли токен и chat_id в .env."""
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    reraise=False,
)
def _send_raw(text: str) -> bool:
    """
    Низкоуровневая отправка в Telegram.

    Сначала пробует с parse_mode=HTML (для <b>, <code> и т.д.).
    Если Telegram вернул 400 (невалидный HTML) — отправляет как plain text.
    Retry 3 раза только при сетевых ошибках (не при 4xx).
    """
    url = f"{TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    def _try_send(payload: dict) -> httpx.Response:
        with httpx.Client(timeout=10.0) as client:
            return client.post(url, json=payload)

    # Попытка 1: с HTML-разметкой
    payload_html = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    resp = _try_send(payload_html)

    if resp.status_code == 400:
        log.warning(
            f"_send_raw: HTML отклонён ({resp.text[:120]}), пробую plain text"
        )
        payload_plain = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        }
        resp = _try_send(payload_plain)

    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        log.error(f"Telegram API ответил ошибкой: {data}")
        return False

    return True


def send_message(text: str, level: str = "info") -> bool:
    """
    Отправляет текстовое сообщение в Telegram.

    Args:
        text: текст сообщения
        level: info | success | warning | error | money | rocket | scan | task
    """
    if not is_notifier_ready():
        log.warning(
            f"Notifier не настроен, сообщение не отправлено: {text[:80]}"
        )
        return False

    emoji = EMOJI.get(level, "")
    full_text = f"{emoji} {text}" if emoji else text

    success = _send_raw(full_text)

    preview = full_text[:100].replace("\n", " ")
    log.debug(f"Telegram отправлено [{level}]: {preview}")

    return success


# --- Удобные обёртки ---

def notify_info(text: str) -> bool:
    return send_message(text, level="info")


def notify_success(text: str) -> bool:
    return send_message(text, level="success")


def notify_warning(text: str) -> bool:
    return send_message(text, level="warning")


def notify_error(text: str) -> bool:
    return send_message(text, level="error")


def notify_money(text: str) -> bool:
    return send_message(text, level="money")


def notify_scan(text: str) -> bool:
    return send_message(text, level="scan")


def notify_startup() -> bool:
    """Приветственное сообщение о запуске бота."""
    return send_message(
        f"Airdrop Hunter запущен\n"
        f"Окружение: {settings.ENVIRONMENT}\n"
        f"RPC: {settings.POLYGON_RPC_URL}",
        level="rocket",
    )


__all__ = [
    "is_notifier_ready",
    "send_message",
    "notify_info",
    "notify_success",
    "notify_warning",
    "notify_error",
    "notify_money",
    "notify_scan",
    "notify_startup",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.core.notifier
    log.info("Тест notifier — отправляю сообщение в Telegram...")
    ok = notify_startup()
    if ok:
        print("✅ Сообщение отправлено. Проверь Telegram.")
    else:
        print("❌ Не удалось отправить. Проверь .env и логи.")
