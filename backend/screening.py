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
