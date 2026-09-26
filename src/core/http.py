"""
src/core/http.py
Общий HTTP-клиент для всех модулей проекта.

Возможности:
    - Единые таймауты (читаются из config)
    - Retry при сетевых сбоях (tenacity)
    - Поддержка прокси (из PROXY_URL в .env)
    - Рандомизация User-Agent (anti-Sybil)
    - Логирование запросов без утечки секретов

Использование:
    from src.core.http import get, post

    response = get("https://api.example.com/data")
    if response:
        print(response.json())
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

# Реалистичные User-Agent'ы (Chrome/Firefox на разных ОС).
# Используем, чтобы запросы выглядели как от браузера, а не от скрипта.
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Таймауты (секунды): connect, read, write, pool
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)


def _random_user_agent() -> str:
    """Возвращает случайный User-Agent из списка."""
    return random.choice(USER_AGENTS)


def _build_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Собирает заголовки запроса с случайным User-Agent."""
    headers = {
        "User-Agent": _random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra:
        headers.update(extra)
    return headers


def _build_client(headers: dict[str, str]) -> httpx.Client:
    """Создаёт httpx-клиент с нужными настройками."""
    kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": DEFAULT_TIMEOUT,
        "follow_redirects": True,
    }

    # Если в .env указан прокси — используем
    if settings.PROXY_URL:
        kwargs["proxies"] = settings.PROXY_URL
        log.debug(f"HTTP-запрос через прокси: {settings.PROXY_URL[:20]}...")

    return httpx.Client(**kwargs)


def _safe_url(url: str) -> str:
    """
    Обрезает URL для логов.
    Убирает query-параметры (могут содержать токены/API-ключи).
    """
    return url.split("?")[0][:100]


# --- Публичные функции с retry ---

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
) -> Optional[httpx.Response]:
    """
    GET-запрос с retry (3 попытки, экспоненциальная задержка 2-15 сек).

    Args:
        url: адрес запроса
        params: query-параметры
        headers: дополнительные заголовки

    Returns:
        httpx.Response или None при исчерпании попыток/ошибке.
    """
    safe = _safe_url(url)
    try:
        with _build_client(_build_headers(headers)) as client:
            log.debug(f"GET {safe}")
            response = client.get(url, params=params)
            log.debug(f"GET {safe} -> {response.status_code}")
            return response
    except (httpx.TimeoutException, httpx.NetworkError):
        # tenacity перехватит и попробует снова
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
) -> Optional[httpx.Response]:
    """
    POST-запрос с retry.

    Args:
        url: адрес запроса
        json: тело в формате JSON
        data: тело в формате form-urlencoded
        headers: дополнительные заголовки

    Returns:
        httpx.Response или None.
    """
    safe = _safe_url(url)
    try:
        with _build_client(_build_headers(headers)) as client:
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

    # Публичный endpoint без авторизации — проверяем, что сеть работает
    r = get("https://api.github.com/zen")
    if r and r.status_code == 200:
        print(f"✅ HTTP работает. Ответ GitHub: {r.text}")
    else:
        print(f"❌ HTTP не работает. Код: {r.status_code if r else 'None'}")
