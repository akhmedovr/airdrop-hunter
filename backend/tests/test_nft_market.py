import unittest
from decimal import Decimal

from nft_market import Listing, screen_cross_market_opportunity


class NftMarketTests(unittest.TestCase):
    def test_listing_requires_positive_price(self):
        with self.assertRaises(ValueError):
            Listing.from_api({
                "marketplace": "opensea", "chain": "ethereum",
                "collection": "demo", "token_id": "1",
                "currency": "ETH", "price": "0",
            })

    def test_profitable_candidate_requires_evidence_gates(self):
        result = screen_cross_market_opportunity(
            "1.0", "1.2",
            marketplace_sell_fee_pct="2.5",
            royalty_pct="0",
            gas_cost="0.01",
            same_asset_verified=True,
            liquidity_verified=True,
            buy_marketplace="market-a",
            sell_marketplace="market-b",
            min_net_margin_pct="5",
        )
        self.assertTrue(result.eligible_for_review)
        self.assertGreater(result.estimated_net, Decimal("0"))

    def test_missing_liquidity_blocks_candidate(self):
        result = screen_cross_market_opportunity(
            "1", "1.5",
            same_asset_verified=True,
            liquidity_verified=False,
            buy_marketplace="market-a",
            sell_marketplace="market-b",
        )
        self.assertFalse(result.eligible_for_review)
        self.assertTrue(any("liquidity" in reason.lower() for reason in result.reasons))

    def test_same_marketplace_is_not_cross_market_arbitrage(self):
        result = screen_cross_market_opportunity(
            "1", "1.5",
            same_asset_verified=True,
            liquidity_verified=True,
            buy_marketplace="market-a",
            sell_marketplace="market-a",
        )
        self.assertFalse(result.eligible_for_review)

    def test_negative_costs_rejected(self):
        with self.assertRaises(ValueError):
            screen_cross_market_opportunity("1", "2", gas_cost="-0.01")


if __name__ == "__main__":
    unittest.main()
