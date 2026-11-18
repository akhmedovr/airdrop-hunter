# Airdrop Hunter 3.0 — Product and Revenue Strategy

Status: internal product strategy, 18 November 2026. All prices and conversion assumptions below are hypotheses, not validated market facts.

## Product thesis

Airdrop Hunter should become a research and decision-support service for Web3 participants. The customer does not pay for a list of token names; they pay to reduce wasted time, avoid bad participation decisions, and monitor a portfolio of opportunities from one place.

Core promise: **every opportunity has a source, a checked date, eligibility status, cost model, risk flags, and a clear next action**.

Never present points, XP, TVL, token allocations, prize pools, estimated rewards, or unclaimed tokens as realized income.

## Product modules

1. Opportunity Radar — official airdrops, testnets, points, rewards and incentive programs.
2. Capital Analysis — deposits, staking, LP and trading incentives with principal risk, lockups, fees and downside scenarios.
3. NFT Research — mint/whitelist/reward campaigns and verified collection facts.
4. NFT Market Monitor — cross-market listing comparisons, order freshness, currency normalization, marketplace fees, royalties, gas, liquidity and net spread. Initially read-only.
5. Web3 Work — bounties, grants, bug bounties and paid contributor tasks.
6. Portfolio & Evidence — user-controlled watchlists, wallet read-only tracking, claims, realized rewards, expenses and audit trail.

## Trust rules (non-negotiable)

- Each claim links to an official source or is explicitly labelled third-party.
- Display checked_at, source freshness, confidence and unresolved blockers.
- Geography and KYC are first-class eligibility fields; never suggest bypassing restrictions.
- Distinguish expected, claimable, claimed and realized rewards.
- Every cost estimate states what is included and what is unknown.
- No transaction signing, token approvals, deposits or trades in the initial product.
- No fabricated profitability scores, backtests or user earnings.
- User data is tenant-scoped; secrets never reach the browser or logs.

## Revenue model hypothesis

Use a free tier to prove utility, then charge for saved time and monitoring depth rather than gating basic safety.

| Tier | Hypothesis | Included |
| --- | ---: | --- |
| Free | 0 | Public discovery, limited watchlist, manual refresh, evidence and risk labels |
| Plus | 299 ₽/month | Larger watchlist, daily monitoring, alerts, export and personal task queue |
| Pro | 599 ₽/month | Faster refresh where provider limits permit, advanced filters, multi-chain portfolio and detailed cost models |
| Research | 999 ₽/month | Advanced opportunity history, custom alerts, comparison tools and research exports |

These are initial pricing experiments only. Do not enable checkout until provider costs, taxes, payment processing, refund handling, sanctions/geography, privacy and consumer rules are reviewed for the operator's actual jurisdiction. No payment provider is selected yet.

Optional rewarded advertising can be tested only after a reliable free quota exists. It must be opt-in, clearly labelled, and never required to access safety or eligibility information. No forced watermark.

## Customer and distribution

Initial target: active individual Web3 researchers and small communities who already monitor several ecosystems and feel pain from fragmented sources. Do not start with institutions or promise trading alpha.

Acquisition experiments:
- Public weekly research digest with sources and explicit expired/blocked labels.
- Free public opportunity pages that rank by evidence quality, not speculative upside.
- Short educational clips explaining how to reject bad campaigns and calculate net returns.
- Community feedback and transparent changelog.
- Referral rewards only after anti-fraud and unit economics are understood.

## Validation gates before monetization

1. Run a private pilot with real users and measure repeat weekly use.
2. Track source error rate, stale-record rate, false-positive rate, and time-to-review.
3. Interview users about which recurring workflow they would pay to remove.
4. Test price sensitivity with a waitlist or non-binding pricing page before charging.
5. Calculate per-user variable costs (API, compute, storage, support, notifications).
6. Require gross margin headroom before paid launch; set provider quotas and abuse controls.
7. Verify legal/payment availability for target markets before collecting money.

## Architecture gates

- Current app is owner-oriented. Before opening public registration, audit OWNER_EMAIL, every authenticated route, scheduled jobs, RLS policies, profile bootstrap and tenant scoping.
- Implement tenant-aware quotas and provider caching; do not call third-party APIs once per user when one cached public observation can serve many users.
- Keep provider API keys server-side in secret environment variables.
- Add a provider adapter interface, per-provider timeouts, bounded pagination, retries with backoff, circuit breakers and explicit 429 handling.
- Store immutable source observations and normalized records separately.
- Add automated tests for auth isolation, currency conversion, decimal scaling, duplicate listings, stale orders, API failures, RLS and billing state transitions.
- Billing must be entitlement-driven and server-verified; never trust a browser-side plan flag.

## Current release gates

- NFT pricing engine is a calculation foundation, not a live arbitrage scanner.
- OpenSea API requires an API key. Do not create one or add a secret without explicit operator approval.
- No second-marketplace provider is integrated yet; cross-market opportunities cannot be asserted.
- Supabase NFT migration is additive and remains unapplied until endpoint and RLS tests are complete.
- No paid subscriptions or ad network are configured.
- Production remains the existing private dashboard until multi-tenant security review is complete.
