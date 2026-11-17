import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from reward_sources import parse_defillama_rewards_html, parse_perp_programs, parse_asentum_watch, parse_push_season3_watch, parse_flop_testnet_watch


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


if __name__ == "__main__":
    unittest.main()
