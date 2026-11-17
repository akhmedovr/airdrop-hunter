# Autonomous Airdrop / Rewards Opportunities — 2026-11-17

Scope: Russian tax resident; capital ceiling RUB 5,000; preference for unattended operation with owner approvals only. This is a research snapshot, not legal advice or an instruction to deposit funds.

## Executive decision

1. **Asentum — priority for technical feasibility check.** The official docs describe a Phase 3 incentivized-testnet allocation of 60,000,000 ASE (6% of supply) for operators running validators. The validator's 500 ASE testnet bond is funded by the project's installer/faucet; no purchase is described as necessary. This is closer to a persistent, automatable node operation than a click-to-earn campaign. However, reward formula per operator, exact payout timing, Russia-specific eligibility, and current production readiness still require confirmation. Do not buy ASE.
2. **Push Chain Season 3 — low-cost secondary candidate, not autonomous.** Official terms last updated 2025-10-25 enumerate restricted citizenship/residency jurisdictions and do not name Russia or Russian residents. This is not a legal guarantee; terms can change and applicable law still applies. The portal shows daily check-ins/spins and on-chain app quests. Tokenomics page proposes 10% of supply for airdrops, but no exact S3 allocation or expected per-user value is published. Manual interaction and possible transaction costs make it less suitable for the owner's near-zero-time requirement.
3. **FLOP Network — monitor, do not fund.** Testnet target is 2026-11-24, provisional. Validator selection uses uptime, block production, accuracy, latency and geographic spread; no published weighting yet. Provisional validator hardware is 8+ cores, 64 GB RAM, 2–4 TB NVMe and redundant 1 Gbps. This is outside the current RUB 5,000 budget. A miner requires a GPU with 16 GB+ VRAM and verified inference work. Do not rent hardware before final specs and testnet opening are confirmed.

## Candidate details

### Asentum

Official sources:
- https://www.asentum.com/nodes
- https://www.asentum.com/docs/getting-started/install-vps
- https://www.asentum.com/docs/investors/growth-fund
- https://www.asentum.com/docs/investors/staking-rewards
- https://www.asentum.com/docs/reference/disclosures
- https://explorer.asentum.com/faucet

Verified from current official documentation:
- Incentivized testnet is live; project homepage says it has been live since 2026-09-17.
- The growth-fund page assigns 6% / 60M ASE to Phase 3 incentivized-testnet operators; says rewards are earned by validators who bond testnet ASE, produce blocks and remain online, with real ASE proportional to participation at TGE.
- Validator docs specify 500 test ASE minimum self-bond. The installer requests 505 ASE from the faucet and bonds 500 automatically. No delegation is live.
- Committee has 100 signing seats: 50 largest stakes and 50 selected by stake-weighted lottery. 500 ASE makes an operator a candidate, not a guarantee of a signing seat.
- VPS installer page states Ubuntu 22.04+, minimum 2 cores / 4 GB RAM / 40 GB SSD; node page recommends 4 cores / 4 GB / 40 GB SSD and says 80 GB recommended. Block store grows around 1–2 GB/day. For planning use the more conservative 4-core, 4-GB, 80-GB target until current docs are reconciled.
- Unbonding is approximately 30 days at target block time.
- The public disclosures state ASE is already live as ERC-20 and that market price/liquidity are not guaranteed. CertiK token-contract audit was described as in progress in the disclosure page.

Risks / unknowns:
- No official Russia-specific eligibility statement found in the pages reviewed. General regulatory-compliance language applies; do not assume eligibility is guaranteed.
- No precise operator payout formula or estimate is published for the testnet allocation.
- Public docs contain a timing/model distinction: the testnet pool is described as paying real ASE proportional to participation at TGE, while validator staking-reward docs also describe a separate mainnet block subsidy. Do not conflate testnet rewards with mainnet staking APR.
- A validator private key is generated on the server. Never share it; never run the same key on two machines. Do not run the remote installer until its script/binary provenance and current VPS capacity are checked.

Decision: **keep as first candidate; no capital purchase.** Next technical check: inspect the user's existing VPS specifications and disk headroom without disrupting existing services; inspect the installer script and validator binary release provenance; verify dashboard XP/validator status and ask the project support whether a Russian tax resident can receive Phase 3 rewards.

### Push Chain Season 3

Official sources:
- https://push.org/tos/
- https://portal.push.org/rewards
- https://push.org/blog/push-rewards-program/
- https://push.org/knowledge/tokenomics/

Verified:
- Terms last updated 2025-10-25 list restricted jurisdictions in section 17.1. Russia is not named in the list, but terms also require compliance with applicable law and allow the list to change.
- Portal currently presents Season 3, daily check-in, a free daily spin, rare passes, social tasks, and app quests.
- Season 3 points unlock eligibility for a reward drop at mainnet launch; rare/shiny passes may unlock further benefits.
- Tokenomics page proposes 10% of total PC supply for airdrops to past and present Push Protocol users and new users/creators/developers/ecosystem partners.

Risks / unknowns:
- No exact Season 3 allocation, points-to-token conversion, or per-user reward estimate published in sources reviewed.
- Some quests involve liquidity, swaps, games or prediction apps; exclude paid gambling/prediction and any task requiring a deposit until separately reviewed.
- Do not automate fake social engagement, referrals, or Sybil activity. Daily check-in and app actions remain user-facing/manual unless the project provides an expressly permitted API.

Decision: **watchlist / free-only if access is lawful and account terms permit.** Do not allocate the RUB 5,000 budget.

### FLOP Network

Official sources:
- https://docs.flop.network/docs/testnet-and-timeline
- https://flop.finance/testnet/

Verified:
- As of 2026-11-14, public testnet was targeted for 2026-11-24, subject to readiness; this is provisional, not proof that the network has launched.
- Validator stake is sponsored by the network; no purchase required for testnet stake.
- Validator ranking considers uptime, block production, accuracy, latency and geographic spread; the weighting rubric was not yet published.
- Validator hardware is provisionally 8+ CPU cores, 64 GB RAM, 4 TB NVMe (2 TB minimum), 1 Gbps redundant connection.
- Miner requires GPU with 16 GB+ VRAM; reward is based on verified inference compute, not idle hardware.
- Agent activity requires purchasing compute; not passive and not appropriate for current budget.

Decision: **monitor only; no rental or deposit.** Re-check after actual testnet launch and final validator rubric.

### Excluded / deprioritized

- **GenLayer:** official points terms say points have no monetary value and no guaranteed conversion; KYC may be required. Airdrop registration appears closed in current third-party tracking. Do not treat points as expected income.
- **AXIS Robotics:** terms prohibit bots/scripts for task completion; points have no guaranteed cash value and token distribution is discretionary. The separate community sale explicitly lists Russia as restricted. Not suitable for unattended participation.
- **Generic perp DEX points:** excluded from passive strategy because they require trading/volume/open interest and expose capital to fees, slippage and liquidation risk.
- **StandX DUSD:** excluded due to shutdown/withdrawal/earn-program changes reported in current official notices; do not deposit.

## Budget policy

- Total ceiling: RUB 5,000.
- Current authorized spend: RUB 0.
- No token purchases, deposits, staking, LP, trading, paid servers, contract approvals or on-chain signatures without a separate owner confirmation.
- Prefer free faucets, testnet credits and existing infrastructure.
- If a server is required, first reuse an existing VPS only if it meets resource and security requirements and does not interfere with Airdrop Hunter or other services.
- Never use VPN or false location data to evade eligibility restrictions; do not use borrowed identities, accounts or KYC.

## Next actions for Airdrop Hunter

1. Add Asentum as a high-priority validator-reward source with explicit fields: testnet/live status, testnet bond source, hardware requirements, uptime requirement, reward pool, reward formula certainty, jurisdiction/KYC status, and last verified timestamp.
2. Add Push Chain Season 3 as a low-cost/manual watchlist source; do not auto-complete quests or interact with game/prediction apps.
3. Add FLOP as a scheduled watch item with a launch-date recheck on/after 2026-11-24; do not classify it as active until public testnet launch is verified.
4. Add exclusion reasons for GenLayer, AXIS, high-risk perp programs and StandX so they are not repeatedly rediscovered as actionable candidates.
5. Do not create a task marked ready/actionable until official rules, current eligibility and the actual reward mechanism have been checked.

Last researched: 2026-11-17. Recheck official sources before any action; terms, dates, tokenomics and eligibility can change.
