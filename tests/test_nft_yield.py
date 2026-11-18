import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from nft_yield import get_nft_yield_opportunities


def test_feed_has_no_unverified_buy_recommendations():
    feed = get_nft_yield_opportunities()
    assert feed["country"] == "RU"
    assert feed["budget_rub"] == 5000
    assert feed["summary"]["total"] == len(feed["items"])
    assert feed["summary"]["buy_recommendations"] == 0
    assert all(item["buy_allowed"] is False for item in feed["items"])


def test_points_and_devnet_are_not_monetized():
    feed = get_nft_yield_opportunities()
    rally = next(item for item in feed["items"] if item["id"] == "rally-wingston")
    nfi = next(item for item in feed["items"] if item["id"] == "nfi-staking-devnet")
    assert rally["reward_asset"] == "RLP (Rally Points)"
    assert rally["reward_value"] is None
    assert "не подтверждённый ликвидный токен" in rally["reward_type"]
    assert nfi["network"] == "Solana Devnet"
    assert nfi["reward_value"] is None


def test_every_candidate_has_source_and_review_reason():
    feed = get_nft_yield_opportunities(country="RU", budget_rub=5000)
    for item in feed["items"]:
        assert item["official_url"].startswith("https://")
        assert item["checked_at"]
        assert item["why_not_buy"]
        assert item["country"] == "RU"
        assert item["budget_limit_rub"] == 5000



def test_hens_is_flagged_as_manual_high_risk_not_passive_buy():
    feed = get_nft_yield_opportunities()
    hens = next(item for item in feed["items"] if item["id"] == "hens-farm")
    assert hens["reward_asset"] == "HEGG + GLD"
    assert "5 HEGG/день" in hens["reward_rate"]
    assert "ежеднев" in hens["why_not_buy"]
    assert hens["capital_rub"] is None
    assert hens["buy_allowed"] is False
