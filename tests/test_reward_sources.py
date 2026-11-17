import unittest
from datetime import datetime, timezone
from reward_sources import parse_defillama_rewards_html, parse_perp_programs


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


if __name__ == "__main__":
    unittest.main()
