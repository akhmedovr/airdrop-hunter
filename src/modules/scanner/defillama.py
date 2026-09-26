"""
src/modules/scanner/defillama.py
Сканер аирдроп-кандидатов через публичный API DeFiLlama.

Логика: ищем проекты на Polygon без запущенного токена, с TVL в заданном
диапазоне и категорией, которая реально раздаёт аирдропы (отсекаем CEX,
сети и prediction markets).

Использование:
    from src.modules.scanner.defillama import scan_polygon_candidates
    candidates = scan_polygon_candidates(min_tvl=1_000_000, limit=10)
"""

from typing import Any, Optional

from src.core.http import get
from src.core.logger import get_logger
from src.core.notifier import notify_scan, notify_error

log = get_logger(__name__)

DEFILLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"

# Категории DeFi-протоколов, которые МОГУТ дропать (белый список).
# Если категория тут — кандидат сохраняется.
AIRDROPABLE_CATEGORIES = {
    "dexes",
    "lending",
    "yield",
    "liquid staking",
    "bridge",
    "derivatives",
    "cdp",
    "farm",
    "launchpad",
    "onchain capital allocator",
    "yield aggregator",
    "restaking",
    "liquid restaking",
    "perpetuals",
    "options",
    "insurance",
    "algo-stables",
    "services",
    "oracle",
    "nft marketplace",
    "nft lending",
    "rwa",
}

# Категории, которые точно НЕ дропают (черный список).
# Если категория тут — кандидат отбрасывается.
NON_AIRDROP_CATEGORIES = {
    "cex",                 # централизованные биржи — не дропают
    "chain",               # это сети, не протоколы
    "prediction market",   # спорно — не наш формат
}


def _has_polygon_chain(protocol: dict[str, Any]) -> bool:
    """Проверяет, работает ли протокол на Polygon."""
    chains = protocol.get("chains") or []
    if not isinstance(chains, list):
        return False
    return any("polygon" in str(c).lower() for c in chains)


def _has_no_token(protocol: dict[str, Any]) -> bool:
    """
    Проверяет, что у протокола НЕТ запущенного токена.
    Это главный признак будущего аирдропа.
    """
    symbol = protocol.get("symbol") or ""
    return symbol.strip() in ("", "-")


def _is_potential_airdrop_category(protocol: dict[str, Any]) -> bool:
    """
    Проверяет категорию протокола.
    - Черный список → отбрасываем (CEX, chains, prediction markets)
    - Белый список → оставляем
    - Неизвестная категория → оставляем (но это может быть шум)
    """
    category = (protocol.get("category") or "").lower().strip()

    if not category:
        return False

    if category in NON_AIRDROP_CATEGORIES:
        return False

    if category in AIRDROPABLE_CATEGORIES:
        return True

    # Неизвестная категория — пропускаем, но это видно в логах
    log.debug(f"Неизвестная категория у {protocol.get('name')}: {category}")
    return True


def _is_not_dead(protocol: dict[str, Any], min_tvl: float) -> bool:
    """TVL выше порога — проект живой, не заброшен."""
    tvl = protocol.get("tvl") or 0
    return isinstance(tvl, (int, float)) and tvl >= min_tvl


def _is_not_too_big(protocol: dict[str, Any], max_tvl: float) -> bool:
    """TVL ниже потолка — не гигант, где дроп уже был."""
    tvl = protocol.get("tvl") or 0
    return isinstance(tvl, (int, float)) and tvl <= max_tvl


def _to_candidate(protocol: dict[str, Any]) -> dict[str, Any]:
    """Нормализует «сырой» ответ DeFiLlama в наш формат."""
    return {
        "name": protocol.get("name", "Unknown"),
        "slug": protocol.get("slug", ""),
        "url": protocol.get("url", ""),
        "description": (protocol.get("description") or "")[:200],
        "category": protocol.get("category", ""),
        "chains": protocol.get("chains") or [],
        "tvl_usd": float(protocol.get("tvl") or 0),
        "change_7d": protocol.get("change_7d"),
        "change_1m": protocol.get("change_1m"),
        "twitter": protocol.get("twitter"),
        "defillama_url": f"https://defillama.com/protocol/{protocol.get('slug', '')}",
    }


def fetch_all_protocols() -> Optional[list[dict[str, Any]]]:
    """
    Забирает список всех протоколов из DeFiLlama.
    Возвращает None при ошибке сети/парсинга.
    """
    log.info("Запрашиваю список протоколов из DeFiLlama...")
    response = get(DEFILLAMA_PROTOCOLS_URL)

    if response is None:
        log.error("DeFiLlama не ответил")
        return None

    if response.status_code != 200:
        log.error(f"DeFiLlama вернул код {response.status_code}")
        return None

    try:
        data = response.json()
    except Exception as e:
        log.error(f"Не смог распарсить JSON от DeFiLlama: {e}")
        return None

    if not isinstance(data, list):
        log.error(f"DeFiLlama вернул не список, а {type(data)}")
        return None

    log.info(f"Получено протоколов: {len(data)}")
    return data


def scan_polygon_candidates(
    min_tvl: float = 1_000_000,
    max_tvl: float = 500_000_000,
    limit: int = 20,
    notify: bool = True,
) -> list[dict[str, Any]]:
    """
    Ищет кандидатов на аирдроп: проекты на Polygon без токена,
    в категории из белого списка, с TVL в диапазоне [min_tvl, max_tvl].

    Args:
        min_tvl: минимальный TVL в USD
        max_tvl: максимальный TVL в USD
        limit: сколько максимум вернуть
        notify: отправлять ли отчёт в Telegram

    Returns:
        Список кандидатов (отсортирован по TVL убыв.).
    """
    protocols = fetch_all_protocols()
    if protocols is None:
        if notify:
            notify_error("Сканер DeFiLlama: не удалось получить список протоколов")
        return []

    candidates: list[dict[str, Any]] = []

    for protocol in protocols:
        if not _has_polygon_chain(protocol):
            continue
        if not _has_no_token(protocol):
            continue
        if not _is_potential_airdrop_category(protocol):
            continue
        if not _is_not_dead(protocol, min_tvl):
            continue
        if not _is_not_too_big(protocol, max_tvl):
            continue

        candidates.append(_to_candidate(protocol))

    candidates.sort(key=lambda c: c["tvl_usd"], reverse=True)
    top = candidates[:limit]

    log.success(f"Найдено кандидатов: {len(candidates)} (топ-{len(top)} отобран)")

    if notify and top:
        lines = ["🔍 Кандидаты на аирдроп (Polygon, DeFi, без токена):"]
        for i, c in enumerate(top[:5], 1):
            tvl_m = c["tvl_usd"] / 1_000_000
            lines.append(f"{i}. {c['name']} ({c['category']}) — ${tvl_m:.1f}M TVL")
        lines.append(f"\nВсего: {len(candidates)}. Топ-{len(top)} в логах.")
        notify_scan("\n".join(lines))

    return top


__all__ = [
    "fetch_all_protocols",
    "scan_polygon_candidates",
    "AIRDROPABLE_CATEGORIES",
    "NON_AIRDROP_CATEGORIES",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.modules.scanner.defillama
    log.info("Тест сканера DeFiLlama...")
    results = scan_polygon_candidates(min_tvl=500_000, limit=10, notify=True)

    if not results:
        print("❌ Кандидаты не найдены (или ошибка сети)")
    else:
        print(f"\n✅ Найдено кандидатов: {len(results)}\n")
        for i, c in enumerate(results, 1):
            tvl_m = c["tvl_usd"] / 1_000_000
            print(f"{i}. {c['name']} ({c['category']})")
            print(f"   TVL: ${tvl_m:.2f}M | 7d: {c.get('change_7d')}%")
            print(f"   {c['url']}")
            print(f"   {c['defillama_url']}")
            print()
