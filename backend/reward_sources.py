"""Conservative parsers for public reward-program directories.

Directory entries are discovery leads only. They never prove user eligibility,
a token allocation, or monetary value.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from urllib.parse import urlparse


DEFILLAMA_REWARDS_URL = "https://defillama.com/rewards"
DEFILLAMA_REWARDS_API_URL = "https://api.llama.fi/rewards"
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
                "costs and current availability are not independently verified."
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


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data and data.strip():
            self.parts.append(data.strip())


def _visible_text(html):
    parser = _VisibleTextParser()
    parser.feed(html or "")
    return " ".join(" ".join(parser.parts).split())


def parse_asentum_watch(homepage_html, growth_html, ecosystem_html='', checked_at=None):
    home = _visible_text(homepage_html).lower()
    growth = _visible_text(growth_html).lower()
    if not any(term in home for term in ("incentivized testnet", "incentivised testnet")):
        return []
    if not any(term in growth for term in ("60m", "60,000,000")):
        return []
    if "phase 3" not in growth and "phase 3" not in home:
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    records = [{
        "title": "Asentum — incentivized validator testnet",
        "project_name": "Asentum",
        "url": "https://www.asentum.com/docs/investors/growth-fund",
        "chain": "Asentum testnet",
        "reward_description": (
            "Official pages describe a 60M ASE (6% supply) Phase 3 incentivized-testnet operator allocation. "
            "Personal payout, current phase qualification and Russian-resident eligibility are unconfirmed. "
            "500 ASE is only the minimum self-bond; the committee cutoff can be higher. "
            "No token purchase or VPS rental is authorized."
        ),
        "confidence": 0.45,
        "evidence": [{
            "source": "Asentum official watchlist",
            "source_url": "https://www.asentum.com/roadmap",
            "growth_fund_url": "https://www.asentum.com/docs/investors/growth-fund",
            "checked_at": now.isoformat(),
            "signals": ["incentivized testnet", "60M ASE allocation", "Phase 3"],
        }],
        "ai_summary": (
            "Watchlist only. The roadmap describes the incentivized testnet as live, while the Growth Fund "
            "labels the 60M ASE operator allocation Phase 3. Resolve this phase mismatch and obtain written "
            "eligibility and payout clarification before validator setup."
        ),
        "anti_sybil_notes": (
            "No location evasion, duplicate validators, fake activity or borrowed identity. "
            "Never expose validator private keys. Audit infrastructure before installation."
        ),
    }]
    ecosystem = _visible_text(ecosystem_html).lower()
    if "xp actions" in ecosystem and "daily quests" in ecosystem and "every partner" in ecosystem:
        records.append({
            "title": "Asentum — ecosystem XP and daily quests",
            "project_name": "Asentum",
            "url": "https://www.asentum.com/ecosystem",
            "chain": "Asentum testnet",
            "reward_description": (
                "Official ecosystem page lists 6 partners, 18 XP actions and 16 daily quests. "
                "Users receive 3 daily quests (check-in plus two drawn from the pool); actions are verified on-chain. "
                "XP contributes to the airdrop, but the individual XP-to-ASE conversion and personal payout are not published. "
                "Some actions involve swaps, liquidity, token launches, prediction markets or games. "
                "Manual/testnet activity only; do not use real funds or paid boosts."
            ),
            "confidence": 0.55,
            "evidence": [{"source": "Asentum official ecosystem", "source_url": "https://www.asentum.com/ecosystem", "checked_at": now.isoformat(), "signals": ["6 ecosystem partners", "18 XP actions", "16 daily quests", "3 daily quests per account"]}],
            "ai_summary": "XP activity requires a linked native wallet and on-chain signatures. Use only no-cost testnet actions; exclude betting, gambling, liquidity and any activity requiring real ASE purchases.",
            "anti_sybil_notes": "One genuine account and wallet only. No automation of fake engagement, multi-accounting or repeat transactions beyond published daily caps.",
        })
    return records


def parse_push_season3_watch(portal_html, blog_html, checked_at=None):
    portal = _visible_text(portal_html).lower()
    portal_raw = (portal_html or "").lower()
    blog = _visible_text(blog_html).lower()
    season_live = "season 3" in portal or "push rewards s3" in portal_raw or "push chain rewards s3" in portal_raw
    if not season_live:
        return []
    if "season 3" not in blog and "push rewards program" not in blog:
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return [{
        "title": "Push Chain — Season 3 rewards",
        "project_name": "Push Chain",
        "url": "https://portal.push.org/rewards",
        "chain": "Push Chain testnet",
        "reward_description": (
            "Official portal advertises Season 3, daily check-in/spins and app quests. "
            "Exact Season 3 allocation, points conversion and individual payout are not published. "
            "Free/manual watchlist only; exclude paid quests, prediction apps and deposits."
        ),
        "confidence": 0.35,
        "evidence": [{
            "source": "Push Chain official watchlist",
            "source_url": "https://portal.push.org/rewards",
            "blog_url": "https://push.org/blog/push-rewards-program/",
            "checked_at": now.isoformat(),
            "signals": ["Season 3", "daily check-in/spin"],
        }],
        "ai_summary": (
            "An active campaign portal does not guarantee a token payout. Russia is not named in the reviewed "
            "restricted-jurisdiction list, but this is not a legal guarantee; current terms and applicable law "
            "must be checked before connecting an account."
        ),
        "anti_sybil_notes": (
            "No fake social engagement, automated account farming, referral abuse or multi-accounting. "
            "Do not automate user-facing quests unless an official API explicitly permits it."
        ),
    }]


def parse_flop_testnet_watch(docs_html, testnet_html, checked_at=None):
    docs = _visible_text(docs_html).lower()
    testnet = _visible_text(testnet_html).lower()
    if "testnet" not in docs or "validator" not in docs or "testnet" not in testnet:
        return []
    if not any(term in docs for term in ("2026-11-24", "november 24, 2026", "24 november 2026")):
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return [{
        "title": "FLOP Network — validator testnet watch",
        "project_name": "FLOP Network",
        "url": "https://docs.flop.network/docs/testnet-and-timeline",
        "chain": "FLOP testnet",
        "reward_description": (
            "Official documentation lists a provisional public-testnet target of 24 November 2026. "
            "Validator requirements are hardware-intensive (provisionally 8+ cores, 64 GB RAM and 2–4 TB NVMe). "
            "No server rental or paid compute is justified under the current RUB 5,000 budget."
        ),
        "confidence": 0.3,
        "evidence": [{
            "source": "FLOP Network official watchlist",
            "source_url": "https://docs.flop.network/docs/testnet-and-timeline",
            "testnet_url": "https://flop.finance/testnet/",
            "checked_at": now.isoformat(),
            "signals": ["provisional 2026-11-24 testnet target", "validator participation"],
        }],
        "ai_summary": (
            "Future watch item, not yet actionable. Re-check actual public launch and final validator requirements "
            "after the target date. No hardware rental or compute purchase."
        ),
        "anti_sybil_notes": "No artificial activity or duplicate identities. Do not purchase compute or rent hardware without approval.",
    }]


def parse_defillama_rewards_payload(payload, checked_at=None, max_age_days=120, limit=150):
    """Parse the official DeFiLlama rewards JSON feed into unverified discovery leads."""
    if not isinstance(payload, list):
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    wanted = {"points", "airdrop", "cashback", "prize pool", "trading rewards", "signup bonus"}
    records = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        lifecycle = str(item.get("lifecycle") or "").strip().lower()
        publish_status = str(item.get("publish_status") or "").strip().lower()
        visibility = str(item.get("visibility") or "public").strip().lower()
        reward_types = [str(value).strip() for value in (item.get("reward_types") or []) if str(value).strip()]
        if lifecycle != "live" or publish_status != "published" or visibility == "hidden":
            continue
        if not any(value.lower() in wanted for value in reward_types):
            continue
        verified_at = _as_utc(item.get("last_verified"))
        age_days = (now - verified_at).total_seconds() / 86400 if verified_at else None
        if age_days is not None and age_days > max_age_days:
            continue
        end_at = _as_utc(item.get("end_date"))
        if end_at and end_at.date() < now.date():
            continue
        start_at = _as_utc(item.get("start_date"))
        if start_at and start_at.date() > now.date():
            continue
        protocol = str(item.get("protocol") or "").strip()
        if not protocol:
            continue
        program_name = str(item.get("program_name") or "Rewards program").strip()
        title = f"{protocol} — {program_name}"
        project_path = str(item.get("project_path") or "").strip()
        source_urls = [value.strip() for value in str(item.get("source_url") or "").split("|") if value.strip().startswith("https://")]
        url = f"https://defillama.com{project_path}" if project_path.startswith("/protocol/") else (source_urls[0] if source_urls else DEFILLAMA_REWARDS_URL)
        key = (str(item.get("program_id") or "").lower(), url.lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        visitor_benefit = str(item.get("visitor_benefit") or "Not stated")
        summary = str(item.get("summary") or "Not stated")
        referrer_benefit = str(item.get("referrer_benefit") or "Not stated")
        verification = str(item.get("verification") or "Unknown")
        last_verified = str(item.get("last_verified") or "Not stated")
        confidence = 0.32 if verification.lower() == "verified" else 0.18
        if age_days is None or age_days > 45:
            confidence = min(confidence, 0.22)
        if visibility != "public":
            confidence = min(confidence, 0.15)
        records.append({
            "title": title[:220],
            "project_name": protocol[:120],
            "url": url,
            "chain": None,
            "reward_description": (
                f"DeFiLlama API lists this program as {lifecycle}. Reward types: {', '.join(reward_types)}. "
                f"Visitor benefit: {visitor_benefit}. Program summary: {summary}. "
                f"Referral benefit: {referrer_benefit}. Verification: {verification}; last verified: {last_verified}. "
                "Third-party directory lead only; this does not establish current official eligibility, "
                "token conversion, or an individual payout. Check the project's own rules before action."
            )[:1800],
            "confidence": confidence,
            "evidence": [{
                "source": "DeFiLlama Rewards API (third-party index)",
                "source_url": DEFILLAMA_REWARDS_API_URL,
                "directory_url": DEFILLAMA_REWARDS_URL,
                "checked_at": now.isoformat(),
                "program_id": item.get("program_id"),
                "verification": verification,
                "publish_status": publish_status,
                "visibility": visibility,
                "lifecycle": lifecycle,
                "reward_types": reward_types,
                "last_verified": last_verified,
                "official_source_urls": source_urls,
            }],
            "ai_summary": (
                "Discovery lead from DeFiLlama's structured public rewards index, not an official project confirmation. "
                "Eligibility, country restrictions, KYC, token conversion and payout are unknown until the project's "
                "own terms are checked. Trading, deposits, staking, liquidity, volume or card-spend may create costs "
                "and losses; do not perform them solely to farm points."
            ),
            "anti_sybil_notes": "Official project rules, KYC, geography and anti-Sybil terms not yet checked; no multi-accounting or fake referrals.",
        })
        if len(records) >= max(1, min(int(limit), 200)):
            break
    return records

def parse_aioz_depin_watch(cli_html, gui_html, checked_at=None):
    cli = _visible_text(cli_html).lower()
    gui = _visible_text(gui_html).lower()
    if "rewarded in aioz tokens" not in cli and "rewarded in aioz tokens" not in gui:
        return []
    if "1 aioz" not in cli:
        return []
    if "50 gb" not in gui and "50 gb" not in cli:
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return [{
        "title": "AIOZ DePIN — direct token rewards for node resources",
        "project_name": "AIOZ Network",
        "url": "https://docs.aioz.network/aioz-depin/depin-app/depin-cli",
        "chain": "AIOZ Network",
        "reward_description": (
            "AIOZ's official DePIN CLI rewards contributors in AIOZ tokens for verified storage, bandwidth, "
            "delivery, transcoding and AI work. The GUI baseline is at least 50 GB free storage and a stable "
            "20 Mbps connection; there is no enforced uptime minimum, but more online time increases the chance "
            "of receiving tasks. The CLI reports task-specific earnings; minimum withdrawal is 1 AIOZ. "
            "No fixed reward rate or expected monthly income is published. This is direct DePIN work, not an airdrop."
        ),
        "confidence": 0.5,
        "evidence": [{
            "source": "AIOZ official DePIN documentation",
            "cli_url": "https://docs.aioz.network/aioz-depin/depin-app/depin-cli",
            "gui_url": "https://docs.aioz.network/aioz-depin/depin-app/gui-cli",
            "checked_at": now.isoformat(),
            "signals": ["verified-work token rewards", "50 GB storage baseline", "20 Mbps network baseline", "1 AIOZ minimum withdrawal"],
        }],
        "ai_summary": (
            "Potential unattended token-reward node only if spare, already-paid infrastructure meets requirements. "
            "No revenue estimate is available, so do not rent a new VPS or buy hardware. First run a monitored "
            "7-day pilot on isolated existing infrastructure and compare actual AIOZ earned against incremental "
            "server, bandwidth and storage costs. Russian-resident eligibility was not established in the reviewed docs."
        ),
        "anti_sybil_notes": (
            "Use one dedicated key per CLI instance and keep the mnemonic/private key offline encrypted. "
            "Never paste keys into chat. Do not use experimental auto-update in production without a controlled update process. "
            "Multiple instances behind one public IP share task assignments and can reduce rewards."
        ),
    }]


def parse_acurast_processor_watch(rewards_html, provider_html, faq_html, network_html='', checked_at=None):
    """Track Acurast's no-stake base compute pool without inventing per-device earnings."""
    rewards = _visible_text(rewards_html).lower()
    provider = _visible_text(provider_html).lower()
    faq = _visible_text(faq_html).lower()
    required_signals = (
        "base benchmark rewards",
        "independent of their participation in staked compute",
        "856.164 acu per epoch",
    )
    if not all(signal in rewards for signal in required_signals):
        return []
    if "processor lite" not in provider or "iphone 8 or newer" not in provider:
        return []
    if "0.0013 acu per transaction" not in faq:
        return []
    now = (checked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    network_text = _visible_text(network_html)
    active_1_5h_match = (
        re.search(r'"1\.5h"\s*:\s*([\d,]+)', network_text, re.IGNORECASE)
        or re.search(r"1\.5h Active\s+([\d,]+)", network_text, re.IGNORECASE)
    )
    active_24h_match = (
        re.search(r'"24h"\s*:\s*([\d,]+)', network_text, re.IGNORECASE)
        or re.search(r"24h Active\s+([\d,]+)", network_text, re.IGNORECASE)
    )
    active_1_5h = int(active_1_5h_match.group(1).replace(",", "")) if active_1_5h_match else None
    active_24h = int(active_24h_match.group(1).replace(",", "")) if active_24h_match else None
    updated_match = re.search(r'"last_updated"\s*:\s*"([^"]+)"', network_text)
    dashboard_updated_at = None
    if updated_match:
        try:
            dashboard_updated_at = datetime.fromisoformat(updated_match.group(1).replace("Z", "+00:00"))
            if (now - dashboard_updated_at.astimezone(timezone.utc)).total_seconds() > 6 * 3600:
                active_1_5h = active_24h = None
                dashboard_updated_at = None
        except ValueError:
            dashboard_updated_at = None
    network_pool_month = 856.164 * 16 * 30
    equal_share_1_5h = round(network_pool_month / active_1_5h, 4) if active_1_5h else None
    equal_share_24h = round(network_pool_month / active_24h, 4) if active_24h else None
    heartbeat_fee_scenario = round(0.0013 * 48 * 30, 4)
    estimate_text = (
        f"Community dashboard equal-share baseline: {equal_share_24h}–{equal_share_1_5h} ACU/month "
        f"using 24h/1.5h active counts {active_24h}/{active_1_5h}. This is an arithmetic benchmark, "
        "not a personal payout forecast; actual allocation depends on benchmark scores and pool weights."
        if equal_share_1_5h and equal_share_24h else
        "No current active-device count was available, so per-device earnings cannot be estimated."
    )
    dashboard_evidence = []
    if active_1_5h or active_24h:
        dashboard_evidence.append({
            "source": "Acurast Analytics community dashboard (linked by Acurast)",
            "official": False,
            "url": "https://acurast.online/",
            "checked_at": now.isoformat(),
            "dashboard_updated_at": dashboard_updated_at.isoformat() if dashboard_updated_at else None,
            "active_processors_1_5h": active_1_5h,
            "active_processors_24h": active_24h,
            "network_base_pool_acu_per_epoch": 856.164,
            "epochs_per_day_assumption": 16,
            "equal_share_acu_month_1_5h": equal_share_1_5h,
            "equal_share_acu_month_24h": equal_share_24h,
            "heartbeat_fee_scenario_acu_month": heartbeat_fee_scenario,
            "fee_scenario_assumption": "48 transactions/day at 0.0013 ACU each; docs do not state that every heartbeat is a separate transaction",
        })
    return [{
        "title": "Acurast — no-stake smartphone compute rewards",
        "project_name": "Acurast",
        "url": "https://docs.acurast.com/processors/rewards/",
        "chain": "Acurast Mainnet",
        "reward_kind": "direct_token",
        "activity_mode": "unattended_node",
        "country_eligibility": "unknown",
        "kyc_required": None,
        "required_capital_usd": 0,
        "lockup_days": 0,
        "reward_value_verified": False,
        "cost_estimate_verified": False,
        "costs_complete": False,
        "reward_description": (
            "Official Acurast documentation confirms a Base Benchmark Rewards pool distributed to phone "
            "compute providers independently of staking. The documented network-wide pool is 856.164 ACU "
            "per epoch (about 1.5 hours), shared across benchmark pools and all competing providers. "
            "This is NOT the reward per phone. The individual share depends on benchmark scores and the "
            "active provider pool. "
            f"{estimate_text} Processor Lite supports iOS 16+ and Android 12+; existing compatible hardware "
            "can be used without buying a node. The FAQ reports network transaction fees around 0.0013 ACU each. "
            f"A 48-heartbeat/day fee scenario would be {heartbeat_fee_scenario} ACU/month, but docs do not confirm "
            "one transaction per heartbeat. Wallet funding/fee coverage, Russian-resident eligibility and KYC "
            "are not confirmed. No staking is required for the base pool."
        ),
        "confidence": 0.55,
        "official_rules_url": "https://acurast.com/terms-conditions/",
        "evidence": [{
            "source": "Acurast official processor rewards and onboarding documentation",
            "official": True,
            "url": "https://docs.acurast.com/processors/rewards/",
            "source_url": "https://docs.acurast.com/processors/rewards/",
            "provider_url": "https://docs.acurast.com/processors/become-compute-provider/",
            "faq_url": "https://docs.acurast.com/faq/",
            "terms_url": "https://acurast.com/terms-conditions/",
            "checked_at": now.isoformat(),
            "signals": [
                "856.164 ACU network-wide base pool per epoch",
                "base pool independent of staking",
                "Processor Lite supports iOS 16+ and Android 12+",
                "approximately 0.0013 ACU per network transaction",
            ],
            "per_device_reward": None,
            "monthly_reward_estimate": None,
            "country_eligibility": "unknown",
            "kyc_required": None,
        }] + dashboard_evidence,
        "ai_summary": (
            "Best current no-stake hardware-fit lead, not approved for participation yet. "
            f"{estimate_text} A fee scenario of 48 transactions/day at 0.0013 ACU each is "
            f"{heartbeat_fee_scenario} ACU/month, but the docs do not explicitly equate every heartbeat to one transaction. "
            "A compatible existing phone may contribute compute without buying hardware or staking. Verify "
            "Russian-resident eligibility and initial fee coverage before onboarding. Do not use VPN or false "
            "residency details. Do not buy ACU to start."
        ),
        "anti_sybil_notes": (
            "One genuine processor identity per actual device. Do not clone identities, use device farms, "
            "spoof location or bypass KYC/geo-controls. Never share recovery phrases or private keys."
        ),
    }]
