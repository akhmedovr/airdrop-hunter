# Autonomous Opportunity Engine

## Purpose
The engine turns discovered campaigns into an evidence-backed research queue. It is intentionally conservative: unknown eligibility, missing official rules, stale evidence, unknown reward value, incomplete costs, capital lockups, or recurring manual work block a candidate.

## Current implementation
- Country eligibility is explicit. For the current owner profile, the default evaluation country is RU.
- A country allowlist excludes countries not named. A restriction list overrides a positive eligibility flag.
- Only fresh official evidence (checked within 14 days) counts toward evidence readiness.
- Points are not converted into cash value. A points program remains speculative until a defensible, independently verified USD conversion exists.
- Costs are only known when both `total_cost_verified` and `costs_complete` are true.
- Only unattended node / storage / compute / bandwidth work can pass the low-touch activity gate.
- Capital requirements and lockups always require owner review.
- The result is a research status, not authorization to create accounts, deposit funds, trade, sign, claim, or transfer.

## Integration contract
Call `assess_opportunity(campaign, country="RU")` after discovery and attach the returned object to the campaign evidence or a dedicated assessment column. Do not overwrite manual review fields. The API integration is deliberately separate from discovery ingestion so it can be rolled out and tested independently.

## Next integration steps
1. Map existing campaign evidence into the explicit fields required by the engine.
2. Add a scheduled re-assessment job and persist assessment history.
3. Add a UI queue for `ready_for_owner_review` candidates, with evidence links and blockers.
4. Add read-only reward and wallet reconciliation.
5. Keep all account login, spending, wallet signatures, claims, and transfers behind explicit owner approval.
