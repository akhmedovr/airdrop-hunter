import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from reward_sources import parse_defillama_rewards_html, parse_defillama_rewards_payload, parse_perp_programs, parse_asentum_watch, parse_push_season3_watch, parse_flop_testnet_watch, parse_aioz_depin_watch, parse_acurast_processor_watch


class RewardSourceParserTests(unittest.TestCase):
    def test_defillama_rewards_only_live_reward_types(self):
        html = """
        <table><tbody>
        <tr>
          <td><a href="https://defillama.com/protocol/example">Example</a> Points Season</td>
          <td>Earn points for referrals</td><td>Points</td><td>Live</td><td>From Nov 2026</td>
          <td><a href="https://affiliate.example/ref">Open</a></td>
        </tr>
        <tr>
          <td><a href="https://defillama.com/protocol/ended">Ended</a></td>
          <td>Earn points</td><td>Points</td><td>Ended</td><td>Oct 2026</td><td></td>
        </tr>
        <tr>
          <td><a href="https://defillama.com/protocol/rebate">Rebate</a></td>
          <td>Fee discount</td><td>Rebate</td><td>Live</td><td></td><td></td>
        </tr>
        </tbody></table>
        """
        rows = parse_defillama_rewards_html(
            html, checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_name"], "Example")
        self.assertEqual(rows[0]["url"], "https://defillama.com/protocol/example")
        self.assertIn("not independently verified", rows[0]["reward_description"])

    def test_perp_programs_filter_to_fresh_hand_checked_active_rows(self):
        payload = {
            "generated_at": "2026-11-09T03:38:36Z",
            "programs": [
                {
                    "name": "Example", "curated": True, "verification": "hand-checked",
                    "checked_at": "2026-11-09", "stale": False,
                    "docs": ["https://docs.example/rewards"],
                    "program": {"status": "active", "name": "Points", "conversion_stated": "no"},
                    "token": {"status": "none"}, "notes": "Trading activity earns points."
                },
                {
                    "name": "Stale", "curated": True, "verification": "hand-checked",
                    "checked_at": "2026-09-01", "stale": True,
                    "docs": ["https://docs.example/stale"],
                    "program": {"status": "active"}
                },
                {
                    "name": "Unverified", "curated": False, "verification": "auto-imported",
                    "checked_at": "2026-11-09", "stale": False,
                    "docs": ["https://docs.example/unknown"],
                    "program": {"status": "active"}
                },
            ]
        }
        rows = parse_perp_programs(
            payload, checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_name"], "Example")
        self.assertIn("not cash", rows[0]["reward_description"])

    def test_perp_feed_older_than_max_age_is_rejected(self):
        payload = {"generated_at": "2026-01-01T00:00:00Z", "programs": []}
        rows = parse_perp_programs(
            payload, checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc)
        )
        self.assertEqual(rows, [])

    def test_asentum_watch_requires_official_incentivized_testnet_and_allocation(self):
        rows = parse_asentum_watch("<body>Incentivized Testnet is live</body>", "<body>Phase 3 Incentivized Testnet 60M ASE</body>", checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertIn("60M ASE", rows[0]["reward_description"])
        self.assertIn("eligibility", rows[0]["reward_description"])

    def test_asentum_watch_rejects_missing_allocation(self):
        self.assertEqual(parse_asentum_watch("<body>Incentivized Testnet live</body>", "<body>Phase 3 rewards</body>"), [])

    def test_push_watch_is_not_a_guaranteed_reward(self):
        rows = parse_push_season3_watch("<body>Season 3 Daily Check-In Spin</body>", "<body>Season 3 reward program</body>", checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertIn("not published", rows[0]["reward_description"])

    def test_flop_watch_requires_provisional_launch_date(self):
        rows = parse_flop_testnet_watch("<body>Public testnet target 2026-11-24 validator requirements</body>", "<body>FLOP public testnet</body>", checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertIn("No server rental", rows[0]["reward_description"])

    def test_asentum_ecosystem_xp_is_separate_and_not_cash(self):
        rows = parse_asentum_watch("<body>Incentivized Testnet is live</body>", "<body>Phase 3 Incentivized Testnet 60M ASE</body>", "<body>Every partner earns XP 18 XP actions 16 daily quests</body>", checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 2)
        self.assertIn("individual XP-to-ASE conversion", rows[1]["reward_description"])

    def test_push_watch_detects_client_rendered_season_metadata(self):
        rows = parse_push_season3_watch("<html><head><meta property='og:title' content='Push Rewards S3'></head><body>1 FREE Spin/Day</body></html>", "<body>Push Rewards Program</body>", checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertIn("Exact Season 3 allocation", rows[0]["reward_description"])


    def test_defillama_api_keeps_live_published_verified_rewards(self):
        payload = [{"verification":"Verified","visitor_benefit":"Earn points from real use.","reward_types":["Points","Airdrop"],"visibility":"Public","program_id":"p1","protocol":"Example Protocol","publish_status":"Published","last_verified":"2026-11-10","source_url":"https://example.org/rewards | https://example.org/terms","lifecycle":"Live","summary":"Earn points from eligible activity.","project_path":"/protocol/example"}]
        rows = parse_defillama_rewards_payload(payload, checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://defillama.com/protocol/example")
        self.assertIn("Third-party directory lead only", rows[0]["reward_description"])

    def test_defillama_api_rejects_ended_draft_hidden_and_stale_rows(self):
        base = {"verification":"Verified","reward_types":["Points"],"visibility":"Public","publish_status":"Published","last_verified":"2026-11-10","protocol":"Example","source_url":"https://example.org","lifecycle":"Live"}
        ended = dict(base, program_id="ended", end_date="2026-11-01")
        draft = dict(base, program_id="draft", publish_status="Draft")
        hidden = dict(base, program_id="hidden", visibility="Hidden")
        stale = dict(base, program_id="stale", last_verified="2026-01-01")
        self.assertEqual(parse_defillama_rewards_payload([ended,draft,hidden,stale], checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc)), [])

    def test_defillama_api_ignores_referral_only_and_non_live_rows(self):
        payload = [{"protocol":"Example","reward_types":["Commission"],"publish_status":"Published","lifecycle":"Live"},{"protocol":"Example 2","reward_types":["Points"],"publish_status":"Published","lifecycle":"Season Gap"}]
        self.assertEqual(parse_defillama_rewards_payload(payload, checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc)), [])


    def test_acurast_watch_separates_network_pool_from_per_device_reward(self):
        rewards = """
        <body>Base Benchmark Rewards. Independent of their participation in Staked Compute.
        856.164 ACU per epoch. roughly every 1.5 hours.</body>
        """
        provider = "<body>Processor Lite. iPhone 8 or newer. iOS 16+.</body>"
        faq = "<body>Fees are typically minimal, usually around 0.0013 ACU per transaction.</body>"
        rows = parse_acurast_processor_watch(
            rewards, provider, faq,
            checked_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reward_kind"], "direct_token")
        self.assertEqual(rows[0]["required_capital_usd"], 0)
        self.assertIsNone(rows[0]["evidence"][0]["per_device_reward"])
        self.assertIn("NOT the reward per phone", rows[0]["reward_description"])
        self.assertEqual(rows[0]["country_eligibility"], "unknown")
        self.assertIsNone(rows[0]["kyc_required"])

    def test_acurast_watch_rejects_missing_no_stake_or_fee_evidence(self):
        rewards = "<body>Base Benchmark Rewards 856.164 ACU per epoch</body>"
        provider = "<body>Processor Lite iPhone 8 or newer</body>"
        faq = "<body>Fees unknown</body>"
        self.assertEqual(parse_acurast_processor_watch(rewards, provider, faq), [])

    def test_aioz_depin_watch_requires_reward_and_resource_signals(self):
        rows = parse_aioz_depin_watch(
            "<body>Rewarded in AIOZ tokens. Minimum withdrawal is 1 AIOZ.</body>",
            "<body>50 GB free storage. Stable 20 Mbps network.</body>",
            checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("not an airdrop", rows[0]["reward_description"])
        self.assertIn("No revenue estimate", rows[0]["ai_summary"])

    def test_aioz_depin_watch_rejects_missing_resource_requirements(self):
        rows = parse_aioz_depin_watch(
            "<body>Rewarded in AIOZ tokens. Minimum withdrawal is 1 AIOZ.</body>",
            "<body>Low resource node.</body>",
            checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
