"""Evidence-first autonomous opportunity triage.

This module ranks research candidates only. It never authorizes account actions,
deposits, trades, wallet signatures, claims, or transfers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SUPPORTED_COUNTRY = "RU"
ELIGIBILITY_STATES = {"eligible", "ineligible", "unknown"}
REWARD_KINDS = {"direct_token", "stablecoin", "points", "nft", "discount", "unknown"}
ACTIVITY_MODES = {
    "unattended_node", "storage_compute_bandwidth", "passive_holding",
    "manual_quests", "trading_liquidity", "social_tasks", "unknown",
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def assess_opportunity(record: dict, country: str = SUPPORTED_COUNTRY,
                       now: datetime | None = None) -> dict:
    """Return a conservative, auditable assessment from explicitly supplied evidence.

    Eligibility is never inferred from VPN/IP or absence of a restriction.
    Reward value is only monetized when marked verified and denominated in USD.
    Cost is only treated as known when marked verified and complete.
    """
    item = record or {}
    now = now or datetime.now(timezone.utc)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
    official_evidence = [
        row for row in evidence
        if isinstance(row, dict) and row.get("official") is True and row.get("url")
    ]
    checked_dates = [_parse_date(row.get("checked_at")) for row in official_evidence]
    checked_dates = [d for d in checked_dates if d]
    newest_check = max(checked_dates) if checked_dates else None
    age_days = (now - newest_check).total_seconds() / 86400 if newest_check else None
    evidence_fresh = age_days is not None and 0 <= age_days <= 14

    eligibility = str(item.get("country_eligibility", "unknown")).lower()
    if eligibility not in ELIGIBILITY_STATES:
        eligibility = "unknown"
    allowed = {str(v).upper() for v in (item.get("allowed_countries") or [])}
    denied = {str(v).upper() for v in (item.get("restricted_countries") or [])}
    country = str(country).upper()
    if country in denied:
        eligibility = "ineligible"
    elif allowed and country in allowed:
        eligibility = "eligible"
    elif allowed or denied:
        eligibility = "ineligible" if allowed and country not in allowed else "unknown"

    reward_verified = item.get("reward_value_verified") is True
    reward_usd = _number(item.get("reward_usd")) if reward_verified else None
    costs_verified = item.get("total_cost_verified") is True
    costs_complete = item.get("costs_complete") is True
    cost_usd = _number(item.get("total_cost_usd")) if costs_verified and costs_complete else None
    net_usd = round(reward_usd - cost_usd, 2) if reward_usd is not None and cost_usd is not None else None

    capital = _number(item.get("required_capital_usd"))
    lockup_days = _number(item.get("lockup_days"))
    reward_kind = str(item.get("reward_kind", "unknown")).lower()
    if reward_kind not in REWARD_KINDS:
        reward_kind = "unknown"
    mode = str(item.get("activity_mode", "unknown")).lower()
    if mode not in ACTIVITY_MODES:
        mode = "unknown"

    blockers = []
    if not official_evidence:
        blockers.append("official_evidence_missing")
    if not evidence_fresh:
        blockers.append("official_evidence_stale_or_undated")
    if not item.get("official_rules_url"):
        blockers.append("official_rules_missing")
    if eligibility != "eligible":
        blockers.append("country_eligibility_not_confirmed")
    if item.get("kyc_required") is None:
        blockers.append("kyc_requirement_unknown")
    if reward_kind in {"points", "unknown"} or reward_usd is None:
        blockers.append("realizable_reward_value_unknown")
    if cost_usd is None:
        blockers.append("complete_cost_basis_unknown")
    if mode not in {"unattended_node", "storage_compute_bandwidth"}:
        blockers.append("not_unattended_low_touch")
    if capital is None:
        blockers.append("capital_requirement_unknown")
    elif capital > 0:
        blockers.append("capital_at_risk_requires_human_review")
    if lockup_days is None:
        blockers.append("lockup_unknown")
    elif lockup_days > 0:
        blockers.append("capital_lockup_requires_human_review")
    if net_usd is not None and net_usd <= 0:
        blockers.append("non_positive_net_value")

    if blockers:
        status = "blocked"
    else:
        status = "ready_for_owner_review"

    # Priority is a research queue score, not a probability of payout.
    score = 0
    score += 20 if official_evidence else 0
    score += 10 if evidence_fresh else 0
    score += 20 if eligibility == "eligible" else 0
    score += 10 if item.get("kyc_required") is False else 0
    score += 15 if reward_usd is not None else 0
    score += 15 if cost_usd is not None else 0
    score += 10 if mode in {"unattended_node", "storage_compute_bandwidth"} else 0
    if net_usd is not None and net_usd <= 0:
        score = max(0, score - 30)

    return {
        "status": status,
        "research_priority_score": min(100, score),
        "country": country,
        "country_eligibility": eligibility,
        "official_evidence_count": len(official_evidence),
        "official_evidence_latest_checked_at": newest_check.isoformat() if newest_check else None,
        "official_evidence_age_days": round(age_days, 2) if age_days is not None else None,
        "evidence_fresh": evidence_fresh,
        "kyc_required": item.get("kyc_required"),
        "reward_kind": reward_kind,
        "reward_value_verified": reward_usd is not None,
        "reward_usd": reward_usd,
        "cost_basis_verified": cost_usd is not None,
        "total_cost_usd": cost_usd,
        "net_value_usd": net_usd,
        "required_capital_usd": capital,
        "lockup_days": lockup_days,
        "activity_mode": mode,
        "blockers": blockers,
        "execution_policy": "research_only; owner approval required for accounts, spending, signatures, claims and transfers",
        "not_a_return_forecast": True,
    }
