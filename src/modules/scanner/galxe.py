"""
src/modules/scanner/galxe.py
Сканер активных квестов Galxe через публичный GraphQL API.

Galxe API работает без токена — читаем публичные данные активных кампаний.

Возможности:
    - fetch_active_quests()  — топ-N активных квестов
    - Уведомления в Telegram

Использование:
    from src.modules.scanner.galxe import fetch_active_quests
    quests = fetch_active_quests(limit=20)
"""

from typing import Any, Optional

from src.core.http import post as http_post
from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_scan

log = get_logger(__name__)

GALXE_API = "https://graphigo.prd.galaxy.eco/query"
GALXE_APP = "https://app.galxe.com/quest"

LIST_TYPES = ["Newest", "Trending"]

_QUERY = """
query GetCampaigns($first: Int!, $listType: ListType) {
  campaigns(input: {first: $first, listType: $listType}) {
    list {
      id
      name
      status
      space {
        alias
      }
    }
  }
}
""".strip()


def _fetch_by_type(list_type: str, limit: int = 20) -> list[dict[str, Any]]:
    """Запрашивает кампании одного listType (Newest или Trending)."""
    payload = {
        "query": _QUERY,
        "variables": {"first": limit, "listType": list_type},
    }

    response = http_post(GALXE_API, json=payload)
    if response is None:
        log.error(f"Galxe: нет ответа (listType={list_type})")
        return []

    if response.status_code != 200:
        log.error(f"Galxe HTTP {response.status_code}: {response.text[:200]}")
        return []

    try:
        data = response.json()
    except Exception as e:
        log.error(f"Galxe: не-JSON ответ: {e}")
        return []

    if "errors" in data:
        log.error(f"Galxe GraphQL errors: {data['errors']}")
        return []

    try:
        raw = data["data"]["campaigns"]["list"]
    except (KeyError, TypeError) as e:
        log.error(f"Galxe: неожиданная структура ответа: {e}")
        return []

    result: list[dict[str, Any]] = []
    for item in raw:
        camp_id = item.get("id")
        name = item.get("name")
        status = item.get("status")
        space = item.get("space") or {}
        slug = space.get("alias") or ""

        if not camp_id or not name:
            continue

        if slug:
            url = f"{GALXE_APP}/{slug}/{camp_id}"
        else:
            url = f"{GALXE_APP}/{camp_id}"

        result.append({
            "id": camp_id,
            "name": name,
            "status": status,
            "slug": slug,
            "url": url,
            "source": "galxe",
            "list_type": list_type,
        })

    return result


def fetch_active_quests(limit: int = 20, notify: bool = False) -> list[dict[str, Any]]:
    """Забирает активные квесты Galxe (Newest + Trending)."""
    log.info(f"Сканер Galxe: запрашиваю квесты (limit={limit} на listType)")

    all_quests: dict[str, dict[str, Any]] = {}

    for list_type in LIST_TYPES:
        quests = _fetch_by_type(list_type, limit=limit)
        log.info(f"Galxe [{list_type}]: получено {len(quests)}")
        for q in quests:
            if q["id"] not in all_quests:
                all_quests[q["id"]] = q

    active = [q for q in all_quests.values() if q["status"] == "Active"]
    log.success(f"Galxe: активных уникальных квестов — {len(active)}")

    if notify and active:
        lines = ["🎯 Активные квесты Galxe:"]
        for i, q in enumerate(active[:5], 1):
            lines.append(f"{i}. {q['name']}")
            lines.append(f"    {q['url']}")
        lines.append(f"\nВсего: {len(active)}")
        notify_scan("\n".join(lines))

    return active


__all__ = [
    "fetch_active_quests",
    "GALXE_API",
    "GALXE_APP",
]


if __name__ == "__main__":
    log.info("Тест сканера Galxe...")
    quests = fetch_active_quests(limit=10, notify=False)

    if not quests:
        print("❌ Квестов не найдено")
    else:
        print(f"\n✅ Найдено активных квестов: {len(quests)}\n")
        for i, q in enumerate(quests[:10], 1):
            print(f"{i}. {q['name']}")
            print(f"   {q['url']}")
            print()
