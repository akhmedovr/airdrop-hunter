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


def test_dashboard_sort_handles_missing_evidence_timestamps():
    result = build_strategy_dashboard([
        {"title": "dated", "evidence": [{"url": "https://example.org/a",
          "checked_at": "2026-11-18T10:00:00+00:00",
          "opportunity_assessment": {"activity_mode": "unattended_node", "evidence_fresh": False}}]},
        {"title": "undated", "evidence": [{"url": "https://example.org/b",
          "opportunity_assessment": {"activity_mode": "unattended_node", "evidence_fresh": False}}]},
    ], [], [], [])
    assert len(result["tracks"]["no_capital"]) == 2


def test_galxe_quest_is_not_misclassified_as_unattended_node():
    result = build_strategy_dashboard([{
        "title": "Follow Lighthouse Storage",
        "url": "https://app.galxe.com/quest/Lighthouse/GC3K5tZeFb",
        "evidence": [{
            "source": "Galxe (sunsetting)",
            "url": "https://app.galxe.com/quest/Lighthouse/GC3K5tZeFb",
            "opportunity_assessment": {
                "activity_mode": "unattended_node",
                "required_capital_usd": None,
                "status": "blocked",
                "blockers": ["manual_action_required"],
            },
        }],
    }], [], [], [])
    assert len(result["tracks"]["no_capital"]) == 0
    assert len(result["tracks"]["unclassified"]) == 1


def test_referral_program_is_not_assumed_to_require_owner_capital():
    result = build_strategy_dashboard([{
        "title": "Aevo — Referral Program",
        "reward_description": "Referrers earn commissions from referred users' trading volume.",
        "evidence": [{
            "source": "DeFiLlama Rewards",
            "url": "https://defillama.com/protocol/aevo",
            "opportunity_assessment": {
                "activity_mode": "trading_liquidity",
                "required_capital_usd": None,
                "status": "blocked",
                "blockers": ["referrer_requirements_unknown"],
            },
        }],
    }], [], [], [])
    assert len(result["tracks"]["capital"]) == 0
    assert len(result["tracks"]["unclassified"]) == 1


def test_galxe_quest_with_explicit_staking_action_is_capital_track():
    result = build_strategy_dashboard([{
        "title": "Stake 500 USDT to unlock rewards",
        "url": "https://app.galxe.com/quest/example/123",
        "reward_description": "Stake 500 USDT and maintain the position for the campaign.",
        "evidence": [{
            "source": "Galxe",
            "url": "https://app.galxe.com/quest/example/123",
            "opportunity_assessment": {
                "activity_mode": "unattended_node",
                "required_capital_usd": None,
                "status": "blocked",
                "blockers": ["country_eligibility_not_confirmed"],
            },
        }],
    }], [], [], [])
    assert len(result["tracks"]["capital"]) == 1
