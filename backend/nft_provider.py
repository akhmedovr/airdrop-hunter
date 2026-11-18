"""Bounded, read-only OpenSea v2 listing client.

The API key is read only from the server environment. This module does not
create keys, persist credentials, sign transactions, or submit orders.
"""
import asyncio
import os
import re
import time
from decimal import Decimal
from typing import Any

import httpx

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_CACHE_TTL_SECONDS = 60
_CACHE_MAX_ENTRIES = 100
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_semaphore = asyncio.Semaphore(3)


def _store_cache(slug: str, result: dict[str, Any]) -> None:
    """Keep the process-local cache bounded even if callers try many slugs."""
    now = time.monotonic()
    expired = [key for key, (created_at, _) in _cache.items() if now - created_at >= _CACHE_TTL_SECONDS]
    for key in expired:
        _cache.pop(key, None)
    if slug not in _cache and len(_cache) >= _CACHE_MAX_ENTRIES:
        oldest_key = min(_cache, key=lambda key: _cache[key][0])
        _cache.pop(oldest_key, None)
    _cache[slug] = (now, result)


class OpenSeaProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _normalise_listing(row: dict[str, Any], slug: str) -> dict[str, Any] | None:
    asset = row.get("asset") or {}
    price = row.get("price_per_item") or {}
    currency = str(price.get("currency") or "").strip().upper()
    raw_value = price.get("value")
    decimals = price.get("decimals")
    identifier = asset.get("identifier")
    contract = asset.get("contract")
    if not currency or raw_value is None or decimals is None or identifier is None:
        return None
    try:
        decimals_int = int(decimals)
        if decimals_int < 0 or decimals_int > 36:
            return None
        amount = Decimal(str(raw_value)) / (Decimal(10) ** decimals_int)
    except Exception:
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    chain = str(row.get("chain") or "").strip().lower()
    if not chain:
        return None
    return {
        "marketplace": "opensea",
        "collection": slug,
        "chain": chain,
        "token_id": str(identifier),
        "contract": str(contract) if contract else None,
        "currency": currency,
        "price": str(amount),
        "status": str(row.get("status") or "UNKNOWN").upper(),
        "remaining_quantity": row.get("remaining_quantity"),
        "order_created_at": row.get("order_created_at"),
        "url": f"https://opensea.io/assets/{chain}/{contract}/{identifier}" if contract else f"https://opensea.io/collection/{slug}",
    }


async def fetch_collection_best_listings(slug: str, limit: int = 50) -> dict[str, Any]:
    slug = str(slug or "").strip().lower()
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("Invalid OpenSea collection slug")
    limit = max(1, min(int(limit), 50))
    api_key = os.getenv("OPENSEA_API_KEY", "").strip()
    if not api_key:
        raise OpenSeaProviderError("OpenSea API key is not configured on the server", 503)

    cached = _cache.get(slug)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f"https://api.opensea.io/api/v2/listings/collection/{slug}/best"
    async with _semaphore:
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                response = await client.get(
                    url,
                    params={"limit": limit, "include_private_listings": "false"},
                    headers={"accept": "application/json", "x-api-key": api_key},
                )
        except httpx.TimeoutException as error:
            raise OpenSeaProviderError("OpenSea request timed out", 504) from error
        except httpx.HTTPError as error:
            raise OpenSeaProviderError("OpenSea is temporarily unreachable", 502) from error

    if response.status_code == 401:
        raise OpenSeaProviderError("OpenSea rejected the configured API key", 503)
    if response.status_code == 403:
        raise OpenSeaProviderError("OpenSea denied this API request", 503)
    if response.status_code == 429:
        raise OpenSeaProviderError("OpenSea rate limit reached; retry later", 429)
    if response.status_code >= 500:
        raise OpenSeaProviderError("OpenSea is temporarily unavailable", 502)
    if response.status_code != 200:
        raise OpenSeaProviderError(f"OpenSea returned HTTP {response.status_code}", 502)

    try:
        payload = response.json()
    except ValueError as error:
        raise OpenSeaProviderError("OpenSea returned invalid JSON", 502) from error
    rows = payload.get("listings") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise OpenSeaProviderError("OpenSea response did not contain a listings array", 502)

    listings = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or str(row.get("status") or "").upper() != "ACTIVE":
            continue
        item = _normalise_listing(row, slug)
        if not item:
            continue
        identity = (item["chain"], item["contract"], item["token_id"], item["currency"])
        if identity in seen:
            continue
        seen.add(identity)
        listings.append(item)

    result = {
        "provider": "OpenSea",
        "collection": slug,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items_seen": len(rows),
        "active_listings": len(listings),
        "listings": listings,
        "next_cursor_available": bool(payload.get("next")),
        "read_only": True,
        "notice": "OpenSea listings are indicative observations, not guaranteed executable liquidity or an arbitrage signal.",
    }
    _store_cache(slug, result)
    return result
