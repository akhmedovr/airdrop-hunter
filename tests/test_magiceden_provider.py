import unittest
from unittest.mock import patch

from backend.magiceden_provider import (
    _normalise_listing,
    MagicEdenProviderError,
    fetch_collection_listings,
    _CACHE,
    _CACHE_MAX_ENTRIES,
    _store_cache,
)


class MagicEdenProviderTests(unittest.TestCase):
    def test_normalizes_sol_price_from_raw_amount_and_decimals(self):
        row = {
            "tokenMint": "MintAddress123",
            "listingSource": "TENSOR_LISTING",
            "expiry": -1,
            "priceInfo": {"solPrice": {"rawAmount": "1250000000", "decimals": 9, "address": "So111"}},
        }
        item = _normalise_listing(row, "demo")
        self.assertEqual(item["price"], "1.25")
        self.assertEqual(item["currency"], "SOL")
        self.assertEqual(item["marketplace"], "TENSOR_LISTING")

    def test_normalizes_spl_currency_by_mint_address(self):
        row = {
            "tokenMint": "MintAddress123",
            "listingSource": "M2",
            "expiry": -1,
            "priceInfo": {"splPrice": {"rawAmount": "2500000", "decimals": 6, "address": "UsdcMint"}},
        }
        item = _normalise_listing(row, "demo")
        self.assertEqual(item["price"], "2.5")
        self.assertEqual(item["currency"], "SPL:UsdcMint")

    def test_rejects_expired_or_incomplete_listing(self):
        self.assertIsNone(_normalise_listing({"tokenMint": "x", "listingSource": "M2", "expiry": 1}, "demo"))
        self.assertIsNone(_normalise_listing({"tokenMint": "x", "listingSource": "M2", "expiry": -1}, "demo"))

    def test_live_provider_is_disabled_until_terms_and_geography_review(self):
        import asyncio
        with patch.dict("os.environ", {"MAGICEDEN_API_ENABLED": ""}):
            with self.assertRaises(MagicEdenProviderError) as error:
                asyncio.run(fetch_collection_listings("demo"))
        self.assertEqual(error.exception.status_code, 503)

    def test_cache_is_bounded(self):
        _CACHE.clear()
        for index in range(_CACHE_MAX_ENTRIES + 3):
            _store_cache(f"symbol-{index}", {"index": index})
        self.assertEqual(len(_CACHE), _CACHE_MAX_ENTRIES)
        self.assertNotIn("symbol-0", _CACHE)
        self.assertIn("symbol-102", _CACHE)
        _CACHE.clear()


if __name__ == "__main__":
    unittest.main()
