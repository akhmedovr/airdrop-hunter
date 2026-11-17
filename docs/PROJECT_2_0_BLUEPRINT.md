# Airdrop Hunter 2.0 — implementation blueprint

## Product goal

A private, single-owner, mobile-first Progressive Web App (PWA) for discovering legitimate Web3 reward opportunities, evaluating their economics, planning work, tracking completion and recording realized rewards.

The app is the primary interface. Telegram is not a notification channel for version 2.0.

## User experience

- Installable on iPhone from Safari using Add to Home Screen.
- Dashboard: opportunity count, today's plan, progress, spend, claimable rewards and realized P&L.
- Opportunity detail: official source links, eligibility, country/KYC restrictions, deadline, task list, evidence, cost estimate, risk score and confidence.
- Task board: discovered → reviewed → eligible / unknown / ineligible → planned → in progress → completed → claimable → claimed → realized.
- Notification inbox with unread count, filters, deduplication and history.
- Optional iOS Web Push after installation to the Home Screen and explicit permission. In-app notification history remains the source of truth.
- Wallet page is read-only: public addresses, balances, activity and claim events. No seed phrase or private key input.

## System architecture

1. PWA frontend — Next.js/React, mobile-first, manifest, service worker and responsive UI.
2. Authentication and database — a dedicated Supabase project, one-owner allowlist, PostgreSQL and Row Level Security (RLS) on every exposed table.
3. Application API and workers — a dedicated Railway project; Python API and background worker. Existing Python scanners can be reused after audit.
4. AI agent — OpenAI Responses API with narrowly scoped function tools. The agent can read and write application records, search approved sources, score opportunities, draft plans and create notification events.
5. Data sources — official project announcements and quest pages first; DeFiLlama for protocol context; one EVM data provider (Etherscan V2 or Alchemy) for read-only wallet activity; CoinGecko for market context when needed.
6. Push delivery — Web Push with VAPID keys from the backend. Store only subscription endpoints and public keys encrypted/appropriately protected; never expose VAPID private key to the browser.
7. Scheduling — existing APScheduler can be reused inside the worker; do not add a second scheduler until there is a demonstrated need.

## Autonomy policy

### May run without approval

- Discover campaigns and read public official documentation.
- Extract tasks, deadlines and eligibility conditions.
- Check public wallet balances and transactions.
- Estimate gas, fees, liquidity and token market context.
- Detect duplicate campaigns, changed rules, deadlines and claim windows.
- Rank opportunities, create a daily plan and update internal progress based on verified evidence.
- Send in-app notifications and iOS Web Push.

### Requires explicit user action

- Connect or authenticate an account.
- Follow, post, like, comment, join a community or submit personal information.
- Complete any action that represents the user's identity or consent.
- Sign messages, approve token spend, bridge, swap, stake, transfer or claim on-chain.
- Pay a fee, purchase access or subscribe.

### Never do

- Request, store or expose seed phrases or private keys to the PWA/AI agent.
- Bypass KYC, geo restrictions, CAPTCHA, anti-bot or anti-Sybil controls.
- Use multiple accounts or proxy rotation to evade platform rules.
- Claim estimated points or hypothetical token values as realized profit.
- Execute an on-chain write from an AI decision alone.

## Opportunity scoring

Each opportunity must have separate fields for:
- evidence quality and source freshness;
- eligibility confidence, including country and KYC;
- expected reward range and whether reward is confirmed;
- direct fees, gas, bridge costs and time required;
- liquidity, vesting, claimability and payout restrictions;
- deadline and operational risk.

The score is a prioritization aid, not a promise of return. If eligibility or reward terms cannot be verified, the status must be unknown, not eligible.

## Core data domains

- profiles — one allowed owner.
- wallets — public addresses and chain metadata only.
- sources — official source URL, retrieval time and content hash.
- campaigns — project, platform, country/KYC rules, reward terms, dates and evidence.
- tasks — task type, instructions, external URL, risk, estimated cost and approval requirement.
- task_events — audit trail of status changes and evidence.
- wallet_snapshots — read-only balances and timestamps.
- transactions — observed on-chain transactions and actual fees.
- rewards — points, claimable rewards, claimed tokens and realized proceeds kept distinct.
- notifications — in-app inbox, category, priority, dedupe key, read state and timestamps.
- push_subscriptions — device subscription data, owner-scoped and revocable.
- agent_runs — inputs, tool calls, source citations, output and errors for auditability.

All owner data is protected with RLS. Privileged service credentials remain server-side only.

## Notifications

- The app inbox is authoritative and persists every notification.
- Push is a delivery mechanism, not the only record.
- Deduplicate by event type + campaign/task/wallet + meaningful state transition.
- Priorities: critical (claim/deadline/security), high (new high-confidence opportunity), normal (scan summary), low (routine heartbeat).
- User can turn categories on/off and set quiet hours.
- No Telegram notification delivery in version 2.0.

## Migration and rollout

### Phase 0 — safety and repository
- Disable scheduled autonomous swaps and legacy Telegram notifications by default.
- Audit legacy transaction, approval, proxy and CAPTCHA paths.
- Make the GitHub repository private before adding deployment configuration or any sensitive integration metadata.
- Keep the current branch isolated until reviewed.

### Phase 1 — foundation
- Create separate Supabase and Railway projects, not reusing CLIPFORGE.
- Add single-owner auth, RLS schema, API health check and secrets management.
- Add PWA shell, manifest, service worker and notification inbox.

### Phase 2 — discovery and AI
- Replace stale/unsupported integrations with current official sources.
- Add campaign ingestion, source snapshots, evidence-backed eligibility and scoring.
- Add AI tools for search, score, plan, progress and report generation.

### Phase 3 — wallet and reward accounting
- Add read-only wallet tracking.
- Separate estimated, pending, claimable, claimed and realized rewards.
- Add fee accounting and net P&L.

### Phase 4 — push and production hardening
- Enable iOS Web Push after Home Screen installation and permission.
- Add monitoring, backups, rate limits, audit logs, retry policy and security review.
- Run end-to-end tests before production rollout.

## Known legacy issues to address

- src/core/auto_swap.py previously selected random token pairs and could submit swaps with up to 5% slippage. Its scheduler entry has been removed and a default-off guard added.
- Legacy notifier.py sent messages to Telegram. Outbound Telegram notifications are now default-off; PWA notification delivery is a new subsystem and is not yet deployed.
- Legacy planner contains hard-coded Polygon and Galxe tasks. These must be reviewed and migrated; do not treat them as currently valid earning opportunities.
- Galxe Quest is being sunset; do not use it as a source for new campaigns.
- DeFiLlama's old free yield-pool endpoints are not part of this scanner (the current protocol list endpoint is used), but yield-based scoring must use the current supported API plan if later added.

## Deployment blockers

- The repository is currently public. The connected GitHub tools available in this session can create branches, commits and pull requests, but cannot change repository visibility. The owner must switch it to private in GitHub Settings before production secrets or private app data are added.
- A separate Supabase project requires choosing an organization and confirming any quoted nonzero cost.
- A separate Railway project/service may incur usage charges; create and deploy only after reviewing the workspace and estimated cost.
- OpenAI API and VAPID credentials must be supplied/configured as server-side secrets. ChatGPT subscription does not include OpenAI API usage.
