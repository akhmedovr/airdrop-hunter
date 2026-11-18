import unittest
from unittest.mock import patch

from backend.nft_provider import _normalise_listing, fetch_collection_best_listings


class NftProviderTests(unittest.TestCase):
    def test_normalizes_wei_style_price_using_decimals(self):
        row = {
            "asset": {"contract": "0xabc", "identifier": "7"},
            "chain": "ethereum",
            "status": "ACTIVE",
            "price_per_item": {"currency": "WETH", "decimals": 18, "value": "1250000000000000000"},
        }
        result = _normalise_listing(row, "demo")
        self.assertEqual(result["price"], "1.25")
        self.assertEqual(result["currency"], "WETH")
        self.assertIn("/ethereum/0xabc/7", result["url"])

    def test_rejects_missing_asset_or_price_fields(self):
        self.assertIsNone(_normalise_listing({"chain": "ethereum", "status": "ACTIVE"}, "demo"))

    def test_slug_validation_happens_before_network_call(self):
        with patch.dict("os.environ", {"OPENSEA_API_KEY": "test-key"}):
            with self.assertRaises(ValueError):
                import asyncio
                asyncio.run(fetch_collection_best_listings("../bad"))

    def test_private_keys_are_not_part_of_public_result(self):
        row = {
            "asset": {"contract": "0xabc", "identifier": "7"},
            "chain": "ethereum",
            "status": "ACTIVE",
            "price_per_item": {"currency": "ETH", "decimals": 18, "value": "1000000000000000000"},
            "protocol_data": {"signature": "must-not-be-returned"},
        }
        result = _normalise_listing(row, "demo")
        self.assertNotIn("protocol_data", result)


if __name__ == "__main__":
    unittest.main()
