"""Read-only Magic Eden Solana collection listings adapter.

Uses the public, unauthenticated API only. No instruction, signing, order,
purchase, wallet or transaction endpoints are called.
"""
import asyncio
import os
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

_BASE_URL = "https://api-mainnet.magiceden.dev/v2"
_SYMBOL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_CACHE_TTL_SECONDS = 60
_CACHE_MAX_ENTRIES = 100
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


class MagicEdenProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _normalise_listing(row: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    token = row.get("token") or {}
    mint = str(row.get("tokenMint") or token.get("mintAddress") or "").strip()
    source = str(row.get("listingSource") or "").strip().upper()
    expiry = row.get("expiry")
    if not mint or not source or expiry is None:
        return None
    try:
        expiry_value = Decimal(str(expiry))
        if not expiry_value.is_finite():
            return None
        if expiry_value > 0 and expiry_value <= Decimal(str(time.time())):
            return None
    except (InvalidOperation, TypeError, ValueError):
        return None

    price_info = row.get("priceInfo") or {}
    sol = price_info.get("solPrice") or {}
    spl = price_info.get("splPrice") or {}
    amount_info = sol if sol.get("rawAmount") is not None else spl
    if amount_info.get("rawAmount") is None or amount_info.get("decimals") is None:
        return None
    try:
        decimals = int(amount_info["decimals"])
        if decimals < 0 or decimals > 18:
            return None
        amount = Decimal(str(amount_info["rawAmount"])) / (Decimal(10) ** decimals)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None

    currency = "SOL" if amount_info is sol else "SPL:" + str(amount_info.get("address") or "").strip()
    if currency == "SPL:":
        return None
    return {
        "provider": "Magic Eden API",
        "marketplace": source,
        "listing_source": source,
        "chain": "solana",
        "collection": symbol,
        "token_id": mint,
        "currency": currency,
        "price": str(amount),
        "expiry": int(expiry_value),
        "seller": str(row.get("seller") or ""),
        "url": f"https://magiceden.io/item-details/{mint}",
    }


def _store_cache(symbol: str, result: dict[str, Any]) -> None:
    now = time.monotonic()
    expired = [key for key, (created, _) in _CACHE.items() if now - created >= _CACHE_TTL_SECONDS]
    for key in expired:
        _CACHE.pop(key, None)
    if symbol not in _CACHE and len(_CACHE) >= _CACHE_MAX_ENTRIES:
        oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
        _CACHE.pop(oldest, None)
    _CACHE[symbol] = (now, result)


async def fetch_collection_listings(symbol: str, limit: int = 100) -> dict[str, Any]:
    global _LAST_REQUEST_AT
    symbol = str(symbol or "").strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("Invalid Magic Eden collection symbol")
    if os.getenv("MAGICEDEN_API_ENABLED", "").strip().lower() != "true":
        raise MagicEdenProviderError("Magic Eden integration is disabled pending terms and geographic eligibility review", 503)
    limit = max(1, min(int(limit), 100))
    cached = _CACHE.get(symbol)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{_BASE_URL}/collections/{symbol}/listings"
    params = {
        "offset": 0,
        "limit": limit,
        "sort": "listPrice",
        "sort_direction": "asc",
        "listingAggMode": "true",
        "paymentMints": "ALL",
    }
    async with _REQUEST_LOCK:
        delay = 0.55 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                response = await client.get(url, params=params, headers={"accept": "application/json"})
        except httpx.TimeoutException as error:
            raise MagicEdenProviderError("Magic Eden request timed out", 504) from error
        except httpx.HTTPError as error:
            raise MagicEdenProviderError("Magic Eden is temporarily unreachable", 502) from error
        finally:
            _LAST_REQUEST_AT = time.monotonic()

    if response.status_code == 400:
        raise MagicEdenProviderError("Magic Eden rejected the collection symbol", 404)
    if response.status_code == 429:
        raise MagicEdenProviderError("Magic Eden rate limit reached; retry later", 429)
    if response.status_code >= 500:
        raise MagicEdenProviderError("Magic Eden is temporarily unavailable", 502)
    if response.status_code != 200:
        raise MagicEdenProviderError(f"Magic Eden returned HTTP {response.status_code}", 502)
    try:
        rows = response.json()
    except ValueError as error:
        raise MagicEdenProviderError("Magic Eden returned invalid JSON", 502) from error
    if not isinstance(rows, list):
        raise MagicEdenProviderError("Magic Eden response was not a listings array", 502)

    listings = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _normalise_listing(row, symbol)
        if not item:
            continue
        identity = (item["token_id"], item["currency"], item["listing_source"])
        if identity in seen:
            continue
        seen.add(identity)
        listings.append(item)

    result = {
        "provider": "Magic Eden API",
        "collection": symbol,
        "chain": "solana",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items_seen": len(rows),
        "active_listings": len(listings),
        "listings": listings,
        "aggregated_marketplaces": True,
        "read_only": True,
        "notice": "Aggregated Solana listings. Listing source is provider metadata; displayed offers are not guaranteed executable liquidity.",
        "attribution": "Data by Magic Eden",
        "limit": limit,
        "more_may_exist": len(rows) >= limit,
    }
    _store_cache(symbol, result)
    return result
