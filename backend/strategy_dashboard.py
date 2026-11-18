"""Pure projection and accounting helpers for the two-track strategy dashboard."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float:
    try:
        number = float(value)
        return number if number >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _assessment(campaign: dict) -> tuple[dict, dict, dict]:
    evidence = campaign.get("evidence") if isinstance(campaign.get("evidence"), list) else []
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        opportunity = entry.get("opportunity_assessment")
        economics = entry.get("economic_assessment")
        automation = entry.get("automation_assessment")
        if isinstance(opportunity, dict) or isinstance(economics, dict) or isinstance(automation, dict):
            return (
                opportunity if isinstance(opportunity, dict) else {},
                economics if isinstance(economics, dict) else {},
                automation if isinstance(automation, dict) else {},
            )
    return {}, {}, {}


def _project(campaign: dict) -> tuple[str, dict]:
    opportunity, economics, automation = _assessment(campaign)
    mode = str(opportunity.get("activity_mode") or "").lower()
    if not mode:
        mode = str(automation.get("mode") or "").lower()
    if mode == "node_uptime":
        mode = "unattended_node"
    if mode == "active_trading_or_liquidity":
        mode = "trading_liquidity"
    if mode == "passive_holding_or_vault":
        mode = "passive_holding"

    required = opportunity.get("required_capital_usd")
    if required is None:
        required = economics.get("required_capital_usd")
    required_number = None if required is None else _number(required)

    evidence = campaign.get("evidence") if isinstance(campaign.get("evidence"), list) else []
    primary = next((row for row in evidence if isinstance(row, dict) and row.get("url")), {})
    source_name = str(primary.get("source") or "").lower()
    campaign_url = str(campaign.get("url") or "").lower()
    is_manual_quest = source_name.startswith("galxe") or "app.galxe.com/quest/" in campaign_url

    # Quest-directory records are manual account actions, never unattended node work.
    # Unknown hardware and operating costs remain visible as blockers.
    if is_manual_quest:
        track = "unclassified"
    elif mode in {"unattended_node", "storage_compute_bandwidth"} and (required_number is None or required_number == 0):
        track = "no_capital"
    elif mode in {"passive_holding", "trading_liquidity"} or (required_number is not None and required_number > 0):
        track = "capital"
    else:
        track = "unclassified"
    checked_at = opportunity.get("official_evidence_latest_checked_at") or primary.get("checked_at")
    reward_verified = opportunity.get("reward_value_verified") is True or economics.get("reward_value_verified") is True
    reward_value = opportunity.get("reward_usd")
    if reward_value is None:
        reward_value = economics.get("estimated_reward_usd")
    cost_verified = opportunity.get("cost_basis_verified") is True or economics.get("costs_complete") is True
    cost_value = opportunity.get("total_cost_usd")
    if cost_value is None:
        cost_value = economics.get("estimated_cost_usd")

    item = {
        "id": campaign.get("id"),
        "title": campaign.get("title") or campaign.get("project_name") or "Без названия",
        "project_name": campaign.get("project_name"),
        "url": campaign.get("url"),
        "official_url": campaign.get("official_rules_url") or primary.get("url") or primary.get("source_url"),
        "source": primary.get("source") or "Источник не указан",
        "chain": campaign.get("chain"),
        "status": campaign.get("status") or "discovered",
        "assessment_status": opportunity.get("status") or "not_assessed",
        "country_eligibility": opportunity.get("country_eligibility") or campaign.get("eligibility") or "unknown",
        "kyc_required": campaign.get("kyc_required", opportunity.get("kyc_required")),
        "activity_mode": mode or "unknown",
        "reward_kind": opportunity.get("reward_kind") or "unknown",
        "reward_value_verified": reward_verified,
        "estimated_reward_usd": _number(reward_value) if reward_verified and reward_value is not None else None,
        "cost_verified": cost_verified,
        "cost_estimate_usd": _number(cost_value) if cost_verified and cost_value is not None else None,
        "required_capital_usd": required_number,
        "lockup_days": opportunity.get("lockup_days"),
        "evidence_fresh": opportunity.get("evidence_fresh"),
        "checked_at": checked_at,
        "blockers": opportunity.get("blockers") or economics.get("blockers") or [],
        "reward_description": campaign.get("reward_description"),
        "ai_summary": campaign.get("ai_summary"),
    }
    return track, item


def _track_accounting(track: str, rewards: list[dict], transactions: list[dict]) -> dict:
    invested = fees = realized = 0.0
    accrued = 0.0
    attributed = 0
    for row in transactions:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if metadata.get("strategy_track") != track:
            continue
        attributed += 1
        status = str(row.get("status") or "").lower()
        if status not in {"failed", "reverted", "cancelled"}:
            direction = str(row.get("direction") or "").lower()
            if direction in {"out", "outgoing", "deposit", "send"}:
                invested += _number(row.get("value_usd"))
            fees += _number(row.get("fee_usd"))
    for row in rewards:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        if evidence.get("strategy_track") != track:
            continue
        attributed += 1
        realized += _number(row.get("realized_usd"))
        if str(row.get("status") or "").lower() in {"claimable", "earned", "accrued"}:
            accrued += _number(row.get("estimated_usd"))
        fees += _number(row.get("fees_usd"))
    return {
        "capital_invested_usd": round(invested, 2),
        "fees_spent_usd": round(fees, 2),
        "accrued_rewards_usd": round(accrued, 2),
        "realized_rewards_usd": round(realized, 2),
        "realized_net_usd": round(realized - fees, 2),
        "attributed_records": attributed,
    }


def build_strategy_dashboard(campaigns: list[dict], rewards: list[dict],
                             transactions: list[dict], runs: list[dict]) -> dict:
    tracks = {"no_capital": [], "capital": [], "unclassified": []}
    for campaign in campaigns:
        track, item = _project(campaign)
        tracks[track].append(item)

    for items in tracks.values():
        items.sort(key=lambda item: (
            bool(item.get("evidence_fresh")),
            item.get("assessment_status") == "ready_for_owner_review",
            str(item.get("checked_at") or ""),
        ), reverse=True)

    no_capital = _track_accounting("no_capital", rewards, transactions)
    capital = _track_accounting("capital", rewards, transactions)
    attributed = no_capital["attributed_records"] + capital["attributed_records"]
    unassigned = max(0, len(rewards) + len(transactions) - attributed)
    latest_run = runs[0] if runs else None
    return {
        "tracks": tracks,
        "counts": {key: len(value) for key, value in tracks.items()},
        "accounting": {
            "no_capital": no_capital,
            "capital": capital,
            "attributed_records": attributed,
            "unassigned_records": unassigned,
            "accounting_policy": "Only explicitly tagged strategy_track records are attributed; no inferred allocation.",
        },
        "last_scan": latest_run,
        "campaigns_total": len(campaigns),
        "rewards_total": len(rewards),
        "transactions_total": len(transactions),
    }
