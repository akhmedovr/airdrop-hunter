"""Conservative parsers for public reward-program directories.

Directory entries are discovery leads only. They never prove user eligibility,
a token allocation, or monetary value.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse


DEFILLAMA_REWARDS_URL = "https://defillama.com/rewards"
PERPDEX_DATA_URL = "https://perpdexairdrops.com/data/programs.json"
_PERPDEX_LICENSE = "CC BY 4.0"


def _as_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class _RewardsTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"text": "", "links": []}
        elif tag == "a" and self.cell is not None:
            self.anchor = {"href": attrs.get("href"), "text": ""}

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data
            if self.anchor is not None:
                self.anchor["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            if self.cell is not None and self.anchor.get("href"):
                self.cell["links"].append(self.anchor)
            self.anchor = None
        elif tag == "td" and self.cell is not None:
            self.cell["text"] = " ".join(self.cell["text"].split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
            self.cell = None
            self.anchor = None


def parse_defillama_rewards_html(html, checked_at=None, limit=120):
    """Parse only Live rows with meaningful rewards; keep them as unverified leads."""
    parser = _RewardsTableParser()
    parser.feed(html or "")
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    wanted = ("points", "airdrop", "cashback", "prize pool", "trading rewards", "signup bonus")
    records = []
    seen = set()
    for cells in parser.rows:
        if len(cells) < 6:
            continue
        project_cell, description_cell, type_cell, status_cell, dates_cell, _link_cell = cells[:6]
        reward_type = type_cell["text"]
        if "live" not in status_cell["text"].lower():
            continue
        if not any(term in reward_type.lower() for term in wanted):
            continue
        protocol_link = next(
            (link for link in project_cell["links"]
             if "defillama.com" in urlparse(link["href"]).netloc
             and "/protocol/" in urlparse(link["href"]).path),
            None,
        )
        if not protocol_link:
            continue
        project_name = protocol_link["text"].strip() or project_cell["text"].split()[0]
        title = project_cell["text"].strip() or project_name
        url = protocol_link["href"].split("?")[0]
        key = (url.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "title": title[:220],
            "project_name": project_name[:120],
            "url": url,
            "chain": None,
            "reward_description": (
                f"DeFiLlama Rewards directory lists this program as Live. "
                f"Reward type: {reward_type}. Directory description: "
                f"{description_cell['text'] or 'Not stated'}. "
                f"Dates shown: {dates_cell['text'] or 'Not stated'}. "
                "Third-party directory lead only; official rules, eligibility, "
                "costs and current availability have not been independently verified."
            )[:1800],
            "confidence": 0.25,
            "evidence": [{
                "source": "DeFiLlama Rewards directory (third-party index)",
                "source_url": DEFILLAMA_REWARDS_URL,
                "checked_at": now.isoformat(),
                "observed_status": status_cell["text"],
                "reward_type": reward_type,
                "dates": dates_cell["text"],
                "directory_description": description_cell["text"],
                "protocol_url": url,
            }],
            "ai_summary": (
                "Discovery lead from DeFiLlama's public rewards directory. "
                "This is not an official project confirmation and does not prove "
                "eligibility or a payout. Verify the project's own terms before "
                "any action. Trading, deposits, staking, liquidity, volume or "
                "card-spend requirements may create costs and losses; do not "
                "perform them solely to farm points."
            ),
            "anti_sybil_notes": "Official rules, KYC, geography and anti-Sybil terms not yet checked.",
        })
        if len(records) >= max(1, min(int(limit), 150)):
            break
    return records


def parse_perp_programs(payload, checked_at=None, max_age_days=30):
    """Parse recently hand-checked active points programs; never treat points as cash."""
    if not isinstance(payload, dict):
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated = _as_utc(payload.get("generated_at"))
    if not generated or (now - generated).total_seconds() > max_age_days * 86400:
        return []
    records = []
    for item in payload.get("programs") or []:
        if not isinstance(item, dict):
            continue
        program = item.get("program") or {}
        checked = _as_utc(item.get("checked_at"))
        docs = [url for url in (item.get("docs") or []) if isinstance(url, str) and url.startswith("https://")]
        if not (
            item.get("curated") is True
            and item.get("verification") == "hand-checked"
            and not item.get("stale", False)
            and str(program.get("status") or "").lower() == "active"
            and checked
            and (now - checked).total_seconds() <= max_age_days * 86400
            and docs
        ):
            continue
        name = str(item.get("name") or "").strip()
        program_name = str(program.get("name") or "Points program").strip()
        if not name:
            continue
        token = item.get("token") or {}
        token_status = str(token.get("status") or "unknown")
        conversion = str(program.get("conversion_stated") or "unknown")
        cadence = str(program.get("cadence") or "Not published")
        pool = str(program.get("pool") or "Not published")
        end = str(program.get("end") or "Not published")
        notes = str(item.get("notes") or "")
        chains = item.get("chains") or []
        official_url = docs[0]
        records.append({
            "title": f"{name} — {program_name}"[:220],
            "project_name": name[:120],
            "url": official_url,
            "chain": ", ".join(str(x) for x in chains[:4]) or None,
            "reward_description": (
                f"Points program listed active by a hand-checked directory. "
                f"Season: {program.get('season') or 'Not stated'}. "
                f"Cadence: {cadence}. Pool: {pool}. End: {end}. "
                f"Token status: {token_status} ({token.get('symbol') or 'no symbol'}). "
                f"Official-doc conversion status: {conversion}; "
                f"{program.get('conversion_note') or 'No conversion details published'}. "
                "Points are not cash and no personal payout is guaranteed."
            )[:1800],
            "confidence": 0.55,
            "evidence": [{
                "source": "PerpDEX Airdrops directory (hand-checked official-doc index)",
                "source_url": PERPDEX_DATA_URL,
                "license": _PERPDEX_LICENSE,
                "checked_at": checked.isoformat(),
                "generated_at": generated.isoformat(),
                "verification": item.get("verification"),
                "official_docs": docs,
                "official_evidence": item.get("evidence") or [],
                "tvl_usd": item.get("tvl_usd"),
                "max_leverage": item.get("max_leverage"),
            }],
            "ai_summary": (
                f"{notes} "
                "This is a points program, not guaranteed income. Most perp venues "
                "weight trading, fees, open interest or liquidity; participation can "
                "lose capital and incur fees. Do not trade, borrow, stake or deposit "
                "solely for points. Token conversion and personal eligibility must "
                "be checked in the current official terms."
            )[:2500],
            "anti_sybil_notes": (
                "The directory links official terms. Trading/LP may require capital "
                "and incur fees; follow the venue's Sybil and integrity rules. "
                "No multi-accounting, wash trading or artificial volume."
            ),
        })
    return records
