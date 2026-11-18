from strategy_dashboard import build_strategy_dashboard


def campaign(mode, capital=None, blockers=None):
    return {
        "title": mode,
        "evidence": [{
            "source": "official docs",
            "url": "https://example.org/rules",
            "checked_at": "2026-11-18T10:00:00+00:00",
            "opportunity_assessment": {
                "activity_mode": mode,
                "required_capital_usd": capital,
                "country_eligibility": "unknown",
                "status": "blocked",
                "blockers": blockers or ["eligibility_unknown"],
                "evidence_fresh": True,
            },
            "economic_assessment": {"required_capital_usd": capital},
        }],
    }


def test_separates_time_only_capital_and_unclassified_candidates():
    result = build_strategy_dashboard(
        [campaign("unattended_node", 0), campaign("trading_liquidity", None),
         campaign("manual_quests", None)],
        [], [], []
    )
    assert len(result["tracks"]["no_capital"]) == 1
    assert len(result["tracks"]["capital"]) == 1
    assert len(result["tracks"]["unclassified"]) == 1


def test_never_displays_unverified_reward_as_usd():
    result = build_strategy_dashboard([campaign("unattended_node", 0)], [], [], [])
    item = result["tracks"]["no_capital"][0]
    assert item["estimated_reward_usd"] is None
    assert item["reward_value_verified"] is False


def test_accounting_only_attributes_explicit_track_tags():
    transactions = [
        {"metadata": {"strategy_track": "capital"}, "direction": "out",
         "value_usd": 20, "fee_usd": 1, "status": "confirmed"},
        {"metadata": {}, "direction": "out", "value_usd": 999,
         "fee_usd": 5, "status": "confirmed"},
    ]
    rewards = [{
        "evidence": {"strategy_track": "capital"}, "realized_usd": 7,
        "estimated_usd": 0, "fees_usd": 0, "status": "realized",
    }]
    result = build_strategy_dashboard([], rewards, transactions, [])
    capital = result["accounting"]["capital"]
    assert capital["capital_invested_usd"] == 20
    assert capital["fees_spent_usd"] == 1
    assert capital["realized_rewards_usd"] == 7
    assert capital["realized_net_usd"] == 6
    assert result["accounting"]["unassigned_records"] == 1
