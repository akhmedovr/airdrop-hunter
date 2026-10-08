"""
src/core/http.py
Общий HTTP-клиент для всех модулей проекта.

Возможности:
    - Единые таймауты
    - Retry при сетевых сбоях (tenacity)
    - Поддержка прокси (per-request или общий PROXY_URL из .env)
    - Рандомизация User-Agent (anti-Sybil)
    - Логирование без утечки секретов

Использование:
    from src.core.http import get, post

    # Напрямую (или через общий PROXY_URL из .env)
    response = get("https://api.example.com/data")

    # Через конкретный прокси кошелька
    from src.core.proxy import get_proxy_for_label
    proxy = get_proxy_for_label("farm-01")
    response = get("https://api.example.com/data", proxy=proxy)
"""

import random
from typing import Any, Optional

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

# Реалистичные User-Agent'ы (Chrome/Firefox на разных ОС)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Таймауты (секунды): connect, read, write, pool
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)


def _random_user_agent() -> str:
    """Возвращает случайный User-Agent."""
    return random.choice(USER_AGENTS)


def _build_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Собирает заголовки с случайным User-Agent."""
    headers = {
        "User-Agent": _random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra:
        headers.update(extra)
    return headers


def _build_client(
    headers: dict[str, str],
    proxy: Optional[str] = None,
) -> httpx.Client:
    """
    Создаёт httpx-клиент.
    proxy: если задан — использовать именно его.
           иначе — использовать settings.PROXY_URL (если задан).
    """
    kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": DEFAULT_TIMEOUT,
        "follow_redirects": True,
    }

    effective_proxy = proxy or settings.PROXY_URL
    if effective_proxy:
        kwargs["proxy"] = effective_proxy
        log.debug(f"HTTP через прокси: {_mask_url(effective_proxy)}")

    return httpx.Client(**kwargs)


def _safe_url(url: str) -> str:
    """Обрезает URL для логов (без query-параметров)."""
    return url.split("?")[0][:100]


def _mask_url(url: str) -> str:
    """Маскирует пароль в URL."""
    try:
        if "@" not in url:
            return url[:60]
        prefix, host_part = url.rsplit("@", 1)
        if ":" in prefix:
            scheme_user, _password = prefix.rsplit(":", 1)
            return f"{scheme_user}:***@{host_part}"
        return url[:60]
    except Exception:
        return "***"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=False,
)
def get(
    url: str,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    proxy: Optional[str] = None,
) -> Optional[httpx.Response]:
    """
    GET-запрос с retry (3 попытки, экспоненциальная задержка 2-15 сек).

    Args:
        url: адрес
        params: query-параметры
        headers: доп. заголовки
        proxy: URL прокси (если None — берётся settings.PROXY_URL)

    Returns:
        httpx.Response или None.
    """
    safe = _safe_url(url)
    try:
        with _build_client(_build_headers(headers), proxy=proxy) as client:
            log.debug(f"GET {safe}")
            response = client.get(url, params=params)
            log.debug(f"GET {safe} -> {response.status_code}")
            return response
    except (httpx.TimeoutException, httpx.NetworkError):
        log.warning(f"Сетевая ошибка на {safe}, retry...")
        raise
    except httpx.HTTPError as e:
        log.error(f"HTTP-ошибка на {safe}: {e}")
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=False,
)
def post(
    url: str,
    json: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    proxy: Optional[str] = None,
) -> Optional[httpx.Response]:
    """
    POST-запрос с retry.

    Args:
        url: адрес
        json: тело в JSON
        data: тело в form-urlencoded
        headers: доп. заголовки
        proxy: URL прокси (если None — берётся settings.PROXY_URL)

    Returns:
        httpx.Response или None.
    """
    safe = _safe_url(url)
    try:
        with _build_client(_build_headers(headers), proxy=proxy) as client:
            log.debug(f"POST {safe}")
            response = client.post(url, json=json, data=data)
            log.debug(f"POST {safe} -> {response.status_code}")
            return response
    except (httpx.TimeoutException, httpx.NetworkError):
        log.warning(f"Сетевая ошибка на {safe}, retry...")
        raise
    except httpx.HTTPError as e:
        log.error(f"HTTP-ошибка на {safe}: {e}")
        return None


__all__ = [
    "get",
    "post",
    "USER_AGENTS",
    "DEFAULT_TIMEOUT",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.core.http
    log.info("Тест HTTP-клиента...")

    # 1. Напрямую
    r = get("https://api.github.com/zen")
    if r and r.status_code == 200:
        print(f"✅ Direct HTTP OK. Ответ: {r.text}")
    else:
        print(f"❌ Direct HTTP failed")

    # 2. Через прокси farm-01
    from src.core.proxy import get_proxy_for_label
    proxy = get_proxy_for_label("farm-01")
    if proxy:
        r2 = get("https://api.ipify.org/", proxy=proxy)
        if r2 and r2.status_code == 200:
            print(f"✅ Proxy HTTP OK. IP: {r2.text}")
        else:
            print(f"❌ Proxy HTTP failed")
    else:
        print("⚠️ Прокси для farm-01 не задан")
