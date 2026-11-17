"""Tests for conservative reward-task screening."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from screening import should_create_review_task


class ScreeningTests(unittest.TestCase):
    def test_defillama_protocols_are_watchlist_only(self):
        self.assertFalse(should_create_review_task({"title": "Lagoon"}, "DeFiLlama"))

    def test_cash_raffle_is_sent_for_manual_review(self):
        self.assertTrue(should_create_review_task(
            {"title": "Meet Midnight. Win your share of $1,500!"},
            "Galxe",
        ))

    def test_cash_giveaway_is_sent_for_manual_review(self):
        self.assertTrue(should_create_review_task(
            {"title": "Daily $USDT giveaway"},
            "Galxe",
        ))

    def test_points_and_oat_are_not_cash_reward_tasks(self):
        self.assertFalse(should_create_review_task(
            {"title": "100 XP Early Supporter Quest"},
            "Galxe",
        ))
        self.assertFalse(should_create_review_task(
            {"title": "Claim your 99X airdrop"},
            "Galxe",
        ))

    def test_capital_and_hardware_actions_are_excluded(self):
        for title in (
            "Buy $500 SPX and win rewards",
            "Stake $500 to win 100 USDT",
            "Trade $100 to share a $10,000 prize",
            "Mine PRL with your GPU — earn 2 USDT",
        ):
            with self.subTest(title=title):
                self.assertFalse(should_create_review_task({"title": title}, "Galxe"))

    def test_unknown_source_is_not_sent_to_queue(self):
        self.assertFalse(should_create_review_task(
            {"title": "Win 50 USDT"},
            "Unknown source",
        ))


if __name__ == "__main__":
    unittest.main()
