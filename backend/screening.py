"""Conservative screening rules for discovery, automation and economic gating."""
import re

_CASH_RE = re.compile(r"(?:\$\s*\d|\b(?:usdt|usdc|usd|eth|btc)\b)", re.IGNORECASE)
_REWARD_RE = re.compile(r"\b(?:win|reward|raffle|giveaway|earn|prize|payout)\b", re.IGNORECASE)
_HIGH_COST_RE = re.compile(
    r"\b(?:buy|purchase|stake|deposit|trade|trading|volume|mine|mining|gpu|hold|invest|liquidity)\b",
    re.IGNORECASE,
)


def should_create_review_task(campaign: dict, source_name: str) -> bool:
    """Queue only Galxe titles that suggest cash rewards without explicit costly actions."""
    if not str(source_name or "").lower().startswith("galxe"):
        return False
    title = str((campaign or {}).get("title") or "")
    return bool(title.strip() and not _HIGH_COST_RE.search(title) and
                _CASH_RE.search(title) and _REWARD_RE.search(title))


_AUTOMATION_NODE_RE = re.compile(r"\b(?:validator|node|depin|storage|bandwidth|compute)\b", re.IGNORECASE)
_AUTOMATION_TRADE_RE = re.compile(r"\b(?:perp|perpetual|trading|trade volume|market making|liquidity|swap|leverage|borrow)\b", re.IGNORECASE)
_AUTOMATION_MANUAL_RE = re.compile(r"\b(?:quest|check.in|daily spin|retweet|social task|discord task|manual task)\b", re.IGNORECASE)
_AUTOMATION_HOLD_RE = re.compile(r"\b(?:holding|hold|balance|deposit|stake|vault|tvl)\b", re.IGNORECASE)


def classify_automation_fit(campaign: dict) -> dict:
    """Heuristic triage only; not proof of eligibility, income or safety."""
    item = campaign or {}
    text = " ".join(str(item.get(key) or "") for key in ("title", "reward_description")).lower()
    # Repeated financial activity and recurring manual actions override a node keyword.
    if _AUTOMATION_TRADE_RE.search(text):
        return {"mode": "active_trading_or_liquidity", "fit": "low",
                "user_action": "repeated_financial_activity", "capital_mode": "trading_or_liquidity_capital",
                "reason": "Points depend on trades, volume, liquidity or leveraged/borrowed positions; not passive."}
    if _AUTOMATION_MANUAL_RE.search(text):
        return {"mode": "manual_quests", "fit": "low",
                "user_action": "manual_or_wallet_signatures", "capital_mode": "none_or_network_fees",
                "reason": "Requires recurring manual tasks, account actions or wallet signatures."}
    if _AUTOMATION_NODE_RE.search(text):
        return {"mode": "node_uptime", "fit": "medium",
                "user_action": "initial_setup_then_monitoring", "capital_mode": "hardware_or_existing_server",
                "reason": "Can run unattended after setup, but needs suitable hardware, uptime and verified reward economics."}
    if _AUTOMATION_HOLD_RE.search(text):
        return {"mode": "passive_holding_or_vault", "fit": "medium",
                "user_action": "initial_deposit_then_hold", "capital_mode": "deposit_or_staked_assets",
                "reason": "May accrue while assets are held, but capital is exposed to issuer, peg, smart-contract and withdrawal risks."}
    return {"mode": "unknown", "fit": "unknown", "user_action": "not_assessed", "capital_mode": "unknown",
            "reason": "Insufficient activity details; requires manual review."}


def assess_economic_gate(campaign: dict, automation: dict | None = None) -> dict:
    """Return a fail-closed investment gate. Missing evidence is never treated as zero cost."""
    item = campaign or {}
    automation = automation or classify_automation_fit(item)
    eligibility = str(item.get("eligibility") or "unknown").strip().lower()
    rules_url = item.get("official_rules_url")
    reward = item.get("estimated_reward_usd")
    cost = item.get("cost_estimate_usd")
    capital = item.get("required_capital_usd")
    try:
        reward = float(reward) if reward is not None else None
    except (TypeError, ValueError):
        reward = None
    try:
        cost = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost = None
    try:
        capital = float(capital) if capital is not None else None
    except (TypeError, ValueError):
        capital = None

    net = round(reward - cost, 2) if reward is not None and cost is not None else None
    blockers = []
    if eligibility != "eligible":
        blockers.append("eligibility_not_confirmed")
    if not rules_url:
        blockers.append("official_rules_missing")
    if reward is None:
        blockers.append("reward_value_unknown")
    if cost is None:
        blockers.append("total_cost_unknown")
    if automation.get("fit") not in {"medium", "high"}:
        blockers.append("not_low_touch")
    if net is not None and net <= 0:
        blockers.append("non_positive_net_reward")

    # Capital lockup and smart-contract/counterparty risk require separate explicit review.
    if capital is not None and capital > 0:
        blockers.append("capital_at_risk_requires_human_review")
    if not blockers:
        gate = "eligible_for_human_approval"
    else:
        gate = "blocked_pending_evidence"
    return {
        "gate": gate,
        "eligibility": eligibility,
        "official_rules_present": bool(rules_url),
        "estimated_reward_usd": reward,
        "estimated_cost_usd": cost,
        "estimated_net_reward_usd": net,
        "required_capital_usd": capital,
        "capital_at_risk": capital is not None and capital > 0,
        "automation_fit": automation.get("fit", "unknown"),
        "blockers": blockers,
        "execution_policy": "no_deposits_trades_wallet_signatures_or_claims_without_explicit_owner_approval",
        "note": "Research estimate only; no reward or payout is guaranteed.",
    }


_REVIEW_FIELDS = (
    "status", "eligibility", "deadline", "official_rules_url", "confidence",
    "estimated_reward_usd", "region_restrictions", "kyc_required",
    "anti_sybil_notes", "cost_estimate_usd", "reward_description", "ai_summary",
)

_CAMPAIGN_DEFAULTS = {
    "deadline": None,
    "official_rules_url": None,
    "confidence": None,
    "estimated_reward_usd": None,
    "region_restrictions": [],
    "kyc_required": None,
    "anti_sybil_notes": None,
    "cost_estimate_usd": None,
    "reward_description": None,
    "ai_summary": None,
}


def normalize_campaign_record(record: dict) -> dict:
    """Normalize bulk-upsert fields and attach automation/economic assessments to JSON evidence."""
    normalized = dict(record or {})
    for field, default in _CAMPAIGN_DEFAULTS.items():
        normalized.setdefault(field, default.copy() if isinstance(default, list) else default)
    automation = classify_automation_fit(normalized)
    economics = assess_economic_gate(normalized, automation)
    evidence = normalized.get("evidence")
    if isinstance(evidence, list):
        normalized["evidence"] = [
            {**entry, "automation_assessment": automation, "economic_assessment": economics}
            if isinstance(entry, dict) else entry
            for entry in evidence
        ]
    summary = str(normalized.get("ai_summary") or "").strip()
    marker = "Economic gate (conservative):"
    if marker not in summary:
        blockers = ", ".join(economics["blockers"]) or "none"
        note = (f"{marker} {economics['gate']} | automation={automation['fit']} | "
                f"net_estimate_usd={economics['estimated_net_reward_usd']} | blockers={blockers}. "
                "Unknown values are not assumed to be zero.")
        normalized["ai_summary"] = (summary + " " + note).strip()
    return normalized


def preserve_review_state(incoming: dict, existing: dict) -> dict:
    """Preserve explicit manual decisions; refresh ordinary discovery records."""
    merged = dict(incoming or {})
    existing_status = str((existing or {}).get("status") or "").lower()
    if existing_status not in {"reviewed", "rejected", "realized", "expired"}:
        return merged
    for field in _REVIEW_FIELDS:
        if field in (existing or {}):
            merged[field] = existing[field]
    return merged
