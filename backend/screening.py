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
    """Ensure every campaign row has the same PostgREST upsert key set."""
    normalized = dict(record or {})
    for field, default in _CAMPAIGN_DEFAULTS.items():
        normalized.setdefault(field, default.copy() if isinstance(default, list) else default)
    return normalized

def preserve_review_state(incoming: dict, existing: dict) -> dict:
    """Preserve only explicit manual decisions; refresh ordinary discovery records."""
    merged = dict(incoming or {})
    existing_status = str((existing or {}).get("status") or "").lower()
    if existing_status not in {"reviewed", "rejected", "realized"}:
        return merged
    for field in _REVIEW_FIELDS:
        if field in (existing or {}):
            merged[field] = existing[field]
    return merged
