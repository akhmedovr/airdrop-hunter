"""Tests for conservative reward-task screening and review-state preservation."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from screening import classify_automation_fit, normalize_campaign_record, preserve_review_state, should_create_review_task


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

    def test_campaign_records_are_normalized_for_bulk_upsert(self):
        defillama = normalize_campaign_record({"title": "A", "source_id": "1"})
        galxe = normalize_campaign_record({"title": "B", "source_id": "2", "deadline": None})
        self.assertEqual(set(defillama), set(galxe))
        self.assertEqual(defillama["region_restrictions"], [])
        self.assertEqual(defillama["cost_estimate_usd"], 0)
        self.assertIsNone(defillama["estimated_reward_usd"])

    def test_unreviewed_discovery_data_is_refreshed(self):
        incoming = {
            "status": "discovered",
            "reward_description": "Fresh API evidence",
            "ai_summary": "Fresh summary",
        }
        existing = {
            "status": "discovered",
            "reward_description": "Stale generic description",
            "ai_summary": "Stale summary",
        }
        merged = preserve_review_state(incoming, existing)
        self.assertEqual(merged["reward_description"], "Fresh API evidence")
        self.assertEqual(merged["ai_summary"], "Fresh summary")

    def test_expired_campaign_state_is_not_overwritten_by_stale_api_status(self):
        incoming = {"status": "discovered", "reward_description": "Generic API text"}
        existing = {"status": "expired", "reward_description": "Page confirmed ended"}
        merged = preserve_review_state(incoming, existing)
        self.assertEqual(merged["status"], "expired")
        self.assertEqual(merged["reward_description"], "Page confirmed ended")

    def test_manual_review_state_survives_new_discovery_data(self):
        incoming = {
            "url": "https://example.org/quest",
            "status": "discovered",
            "eligibility": "unknown",
            "deadline": None,
            "reward_description": "Unverified candidate",
            "evidence": [{"checked_at": "new"}],
        }
        existing = {
            "status": "reviewed",
            "eligibility": "unknown",
            "deadline": "2026-11-21T23:00:00Z",
            "reward_description": "Verified raffle, not guaranteed",
            "ai_summary": "Manual review details",
        }

        merged = preserve_review_state(incoming, existing)
        self.assertEqual(merged["status"], "reviewed")
        self.assertEqual(merged["deadline"], "2026-11-21T23:00:00Z")
        self.assertEqual(merged["reward_description"], "Verified raffle, not guaranteed")
        self.assertEqual(merged["ai_summary"], "Manual review details")
        self.assertEqual(merged["evidence"], [{"checked_at": "new"}])


    def test_node_rewards_are_classified_as_setup_then_monitoring(self):
        result = classify_automation_fit({
            "title": "AIOZ DePIN node rewards",
            "reward_description": "Run a node and provide storage and bandwidth for AIOZ rewards.",
        })
        self.assertEqual(result["mode"], "node_uptime")
        self.assertEqual(result["user_action"], "initial_setup_then_monitoring")

    def test_active_trading_is_low_automation_fit(self):
        result = classify_automation_fit({
            "title": "Perp DEX points",
            "reward_description": "Points accrue from trading volume and liquidity.",
        })
        self.assertEqual(result["fit"], "low")
        self.assertEqual(result["capital_mode"], "trading_or_liquidity_capital")

    def test_manual_quests_are_low_automation_fit(self):
        result = classify_automation_fit({
            "title": "Season 3 daily quests",
            "reward_description": "Daily check-in and social tasks.",
        })
        self.assertEqual(result["mode"], "manual_quests")

    def test_holding_program_is_not_marked_as_no_risk(self):
        result = classify_automation_fit({
            "title": "Stablecoin points",
            "reward_description": "Earn points from holding a stablecoin balance.",
        })
        self.assertEqual(result["mode"], "passive_holding_or_vault")
        self.assertIn("peg", result["reason"])

    def test_normalizer_attaches_automation_assessment_to_evidence(self):
        normalized = normalize_campaign_record({
            "title": "Validator node",
            "reward_description": "Run a validator node.",
            "evidence": [{"source": "official"}],
        })
        assessment = normalized["evidence"][0]["automation_assessment"]
        self.assertEqual(assessment["mode"], "node_uptime")
        self.assertIn("Automation fit (heuristic): medium", normalized["ai_summary"])


if __name__ == "__main__":
    unittest.main()
