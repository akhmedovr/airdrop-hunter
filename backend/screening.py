"""Conservative screening rules for the manual reward-review queue.

This module intentionally does not mark rewards as verified. It only decides
whether a discovered Galxe title deserves a human review task.
"""
import re

_CASH_RE = re.compile(r"(?:\$\s*\d|\b(?:usdt|usdc|usd|eth|btc)\b)", re.IGNORECASE)
_REWARD_RE = re.compile(r"\b(?:win|reward|raffle|giveaway|earn|prize|payout)\b", re.IGNORECASE)
_HIGH_COST_RE = re.compile(
    r"\b(?:buy|purchase|stake|deposit|trade|trading|volume|mine|mining|gpu|hold|invest|liquidity)\b",
    re.IGNORECASE,
)


def should_create_review_task(campaign: dict, source_name: str) -> bool:
    """Return True only for Galxe titles that suggest cash rewards without an explicit high-cost action."""
    if not str(source_name or "").lower().startswith("galxe"):
        return False

    title = str((campaign or {}).get("title") or "")
    if not title.strip() or _HIGH_COST_RE.search(title):
        return False

    return bool(_CASH_RE.search(title) and _REWARD_RE.search(title))




_AUTOMATION_NODE_RE = re.compile(r"\b(?:validator|node|depin|storage|bandwidth|compute)\\b", re.IGNORECASE)
_AUTOMATION_TRADE_RE = re.compile(r"\b(?:perp|perpetual|trading|trade volume|market making|liquidity|swap|leverage|borrow)\\b", re.IGNORECASE)
_AUTOMATION_MANUAL_RE = re.compile(r"\b(?:quest|check.in|daily spin|retweet|social task|discord task|manual task)\\b", re.IGNORECASE)
_AUTOMATION_HOLD_RE = re.compile(r"\b(?:holding|hold|balance|deposit|stake|vault|tvl)\\b", re.IGNORECASE)


def classify_automation_fit(campaign: dict) -> dict:
    """Heuristic triage for the user's low-touch preference; never an eligibility or reward guarantee."""
    item = campaign or {}
    text = " ".join(str(item.get(key) or "") for key in ("title", "reward_description", "ai_summary")).lower()
    if _AUTOMATION_NODE_RE.search(text):
        return {
            "mode": "node_uptime",
            "fit": "medium",
            "user_action": "initial_setup_then_monitoring",
            "capital_mode": "hardware_or_existing_server",
            "reason": "Can run unattended after setup, but needs suitable hardware, uptime and reward-rate verification.",
        }
    if _AUTOMATION_TRADE_RE.search(text):
        return {
            "mode": "active_trading_or_liquidity",
            "fit": "low",
            "user_action": "repeated_financial_activity",
            "capital_mode": "trading_or_liquidity_capital",
            "reason": "Points depend on trades, volume, liquidity or leveraged/borrowed positions; not passive.",
        }
    if _AUTOMATION_MANUAL_RE.search(text):
        return {
            "mode": "manual_quests",
            "fit": "low",
            "user_action": "manual_or_wallet_signatures",
            "capital_mode": "none_or_network_fees",
            "reason": "Requires recurring manual tasks, account actions or wallet signatures.",
        }
    if _AUTOMATION_HOLD_RE.search(text):
        return {
            "mode": "passive_holding_or_vault",
            "fit": "medium",
            "user_action": "initial_deposit_then_hold",
            "capital_mode": "deposit_or_staked_assets",
            "reason": "May accrue while assets are held, but capital is exposed to issuer, peg, smart-contract and withdrawal risks.",
        }
    return {
        "mode": "unknown",
        "fit": "unknown",
        "user_action": "not_assessed",
        "capital_mode": "unknown",
        "reason": "Insufficient activity details; requires manual review.",
    }


_REVIEW_FIELDS = (
    "status",
    "eligibility",
    "deadline",
    "official_rules_url",
    "confidence",
    "estimated_reward_usd",
    "region_restrictions",
    "kyc_required",
    "anti_sybil_notes",
    "cost_estimate_usd",
    "reward_description",
    "ai_summary",
)



_CAMPAIGN_DEFAULTS = {
    "deadline": None,
    "official_rules_url": None,
    "confidence": None,
    "estimated_reward_usd": None,
    "region_restrictions": [],
    "kyc_required": None,
    "anti_sybil_notes": None,
    "cost_estimate_usd": 0,
    "reward_description": None,
    "ai_summary": None,
}


def normalize_campaign_record(record: dict) -> dict:
    """Normalize a campaign and attach a cautious automation-fit triage note."""
    normalized = dict(record or {})
    for field, default in _CAMPAIGN_DEFAULTS.items():
        normalized.setdefault(field, default.copy() if isinstance(default, list) else default)
    assessment = classify_automation_fit(normalized)
    evidence = normalized.get("evidence")
    if isinstance(evidence, list):
        normalized["evidence"] = [
            {**entry, "automation_assessment": assessment} if isinstance(entry, dict) else entry
            for entry in evidence
        ]
    summary = str(normalized.get("ai_summary") or "").strip()
    marker = "Automation fit (heuristic):"
    if marker not in summary:
        note = (
            f"{marker} {assessment['fit']} | mode={assessment['mode']} | "
            f"user_action={assessment['user_action']} | capital={assessment['capital_mode']}. "
            f"{assessment['reason']}"
        )
        normalized["ai_summary"] = (summary + " " + note).strip()
    return normalized

def preserve_review_state(incoming: dict, existing: dict) -> dict:
    """Preserve only explicit manual decisions; refresh ordinary discovery records."""
    merged = dict(incoming or {})
    existing_status = str((existing or {}).get("status") or "").lower()
    if existing_status not in {"reviewed", "rejected", "realized", "expired"}:
        return merged
    for field in _REVIEW_FIELDS:
        if field in (existing or {}):
            merged[field] = existing[field]
    return merged
