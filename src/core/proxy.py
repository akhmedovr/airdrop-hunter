"""
src/core/proxy.py
Управление прокси для каждого кошелька.

Каждый farming-кошелёк работает через свой прокси (своя страна) —
защита от Sybil-детекторов аирдроп-проектов.

Использование:
    from src.core.proxy import get_proxy_for_wallet, get_proxy_for_label

    # Через адрес кошелька
    proxy_url = get_proxy_for_wallet("0xAd7d...")

    # Или через метку
    proxy_url = get_proxy_for_label("farm-01")

    # Статус всех прокси
    from src.core.proxy import proxy_status
    print(proxy_status())
"""

from typing import Optional

import time

from src.core.config import settings
from src.core.logger import get_logger
from src.core.notifier import notify_warning

log = get_logger(__name__)

_last_alert_time: dict = {}
ALERT_COOLDOWN_SEC = 3600


def _maybe_alert(label: str) -> None:
    now = time.time()
    last = _last_alert_time.get(label, 0)
    if now - last > ALERT_COOLDOWN_SEC:
        notify_warning(f"⚠️ Прокси для {label} не задан — работаем с серверного IP (Sybil-риск!)")
        _last_alert_time[label] = now


def _proxy_map() -> dict[str, str]:
    """
    Возвращает словарь {label: proxy_url}.
    Только те прокси, что заданы в .env (не None).
    """
    proxies: dict[str, str] = {}
    for label, url in (
        ("farm-01", settings.PROXY_FARM_01),
        ("farm-02", settings.PROXY_FARM_02),
        ("farm-03", settings.PROXY_FARM_03),
    ):
        if url:
            proxies[label] = url.strip()
    return proxies


def get_proxy_for_label(label: str) -> Optional[str]:
    """
    Возвращает URL прокси по метке кошелька.
    None если для кошелька прокси не задан (работаем напрямую).
    """
    proxies = _proxy_map()
    url = proxies.get(label.lower())
    if url:
        log.debug(f"Прокси для {label}: {_mask_proxy(url)}")
    else:
        log.warning(f"Прокси для {label} не задан — работаем напрямую")
        _maybe_alert(label)
    return url


def get_proxy_for_wallet(address: str) -> Optional[str]:
    """
    Возвращает URL прокси по адресу кошелька.
    Ищет метку кошелька в БД и возвращает соответствующий прокси.
    """
    from sqlalchemy import select
    from src.core.database import get_session, Wallet

    with get_session() as session:
        wallet = session.execute(
            select(Wallet).where(Wallet.address == address)
        ).scalar_one_or_none()

    if wallet is None:
        log.warning(f"Кошелёк {address[:10]}... не найден в БД")
        return None

    return get_proxy_for_label(wallet.label)


def proxy_status() -> dict:
    """
    Показывает какие прокси настроены.
    Удобно для команды /status в Telegram.
    """
    proxies = _proxy_map()
    result: dict = {
        "total_configured": len(proxies),
        "labels": sorted(proxies.keys()),
    }
    for label, url in proxies.items():
        result[label] = _mask_proxy(url)
    return result


def _mask_proxy(url: str) -> str:
    """
    Маскирует пароль в URL прокси для логов.
    http://user:password@host:port → http://user:***@host:port
    """
    try:
        if "@" not in url:
            return url
        prefix, host_part = url.rsplit("@", 1)
        if ":" in prefix:
            scheme_user, _password = prefix.rsplit(":", 1)
            return f"{scheme_user}:***@{host_part}"
        return url
    except Exception:
        return "***"


__all__ = [
    "get_proxy_for_label",
    "get_proxy_for_wallet",
    "proxy_status",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.core.proxy
    log.info("Тест proxy.py — проверка конфигурации")
    status = proxy_status()
    print(f"Настроено прокси: {status['total_configured']}")
    print(f"Метки: {status['labels']}")
    for label in status["labels"]:
        print(f"  {label}: {status[label]}")
