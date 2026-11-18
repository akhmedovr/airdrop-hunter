import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from opportunity_engine import assess_opportunity


class OpportunityEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        self.valid = {
            "official_rules_url": "https://project.example/rules",
            "evidence": [{
                "official": True,
                "url": "https://project.example/docs/rewards",
                "checked_at": self.now.isoformat(),
            }],
            "country_eligibility": "eligible",
            "allowed_countries": ["RU"],
            "kyc_required": False,
            "reward_kind": "direct_token",
            "reward_value_verified": True,
            "reward_usd": 25,
            "total_cost_verified": True,
            "costs_complete": True,
            "total_cost_usd": 2,
            "required_capital_usd": 0,
            "lockup_days": 0,
            "activity_mode": "unattended_node",
        }

    def test_complete_verified_low_touch_candidate_can_reach_owner_review(self):
        result = assess_opportunity(self.valid, now=self.now)
        self.assertEqual(result["status"], "ready_for_owner_review")
        self.assertEqual(result["net_value_usd"], 23)
        self.assertEqual(result["country_eligibility"], "eligible")
        self.assertEqual(result["research_priority_score"], 100)

    def test_unknown_values_never_become_zero(self):
        result = assess_opportunity({"official_rules_url": "https://x.example"})
        self.assertIsNone(result["reward_usd"])
        self.assertIsNone(result["total_cost_usd"])
        self.assertIsNone(result["net_value_usd"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("complete_cost_basis_unknown", result["blockers"])

    def test_russian_restriction_blocks_even_if_record_says_eligible(self):
        item = dict(self.valid, restricted_countries=["RU"])
        result = assess_opportunity(item, country="RU", now=self.now)
        self.assertEqual(result["country_eligibility"], "ineligible")
        self.assertIn("country_eligibility_not_confirmed", result["blockers"])

    def test_allowlist_excludes_russia(self):
        item = dict(self.valid, allowed_countries=["US", "GB"])
        result = assess_opportunity(item, country="RU", now=self.now)
        self.assertEqual(result["country_eligibility"], "ineligible")

    def test_old_official_evidence_blocks(self):
        old = self.now - timedelta(days=30)
        item = dict(self.valid, evidence=[{
            "official": True, "url": "https://project.example/docs",
            "checked_at": old.isoformat(),
        }])
        result = assess_opportunity(item, now=self.now)
        self.assertFalse(result["evidence_fresh"])
        self.assertIn("official_evidence_stale_or_undated", result["blockers"])

    def test_points_are_not_treated_as_cash(self):
        item = dict(self.valid, reward_kind="points", reward_value_verified=True, reward_usd=100)
        result = assess_opportunity(item, now=self.now)
        self.assertIsNone(result["reward_usd"])
        self.assertIn("realizable_reward_value_unknown", result["blockers"])

    def test_trading_or_manual_work_does_not_pass_low_touch_gate(self):
        for mode in ("trading_liquidity", "manual_quests", "social_tasks"):
            result = assess_opportunity(dict(self.valid, activity_mode=mode), now=self.now)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("not_unattended_low_touch", result["blockers"])

    def test_capital_and_lockup_require_human_review(self):
        result = assess_opportunity(
            dict(self.valid, required_capital_usd=100, lockup_days=30), now=self.now
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("capital_at_risk_requires_human_review", result["blockers"])
        self.assertIn("capital_lockup_requires_human_review", result["blockers"])

    def test_missing_kyc_is_unknown_not_false(self):
        item = dict(self.valid)
        item["kyc_required"] = None
        result = assess_opportunity(item, now=self.now)
        self.assertIn("kyc_requirement_unknown", result["blockers"])

    def test_no_action_is_authorized_by_assessment(self):
        result = assess_opportunity(self.valid, now=self.now)
        self.assertIn("owner approval required", result["execution_policy"])
        self.assertTrue(result["not_a_return_forecast"])


if __name__ == "__main__":
    unittest.main()


    def test_agent_usage_is_low_touch_but_not_reward_approved(self):
        item = dict(self.valid, activity_mode="agent_usage", reward_kind="unknown",
                    reward_value_verified=False, reward_usd=None,
                    country_eligibility="unknown", required_capital_usd=0)
        result = assess_opportunity(item, now=self.now)
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("not_unattended_low_touch", result["blockers"])
        self.assertIn("country_eligibility_not_confirmed", result["blockers"])
        self.assertIn("realizable_reward_value_unknown", result["blockers"])
