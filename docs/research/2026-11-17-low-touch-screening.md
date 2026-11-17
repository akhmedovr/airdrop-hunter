# Airdrop Hunter — Low-touch opportunity screening
Date: 2026-11-17

## Production scanner status

The production scanner completed successfully after the source expansion and parser repair.

- Total discovered campaign records: **177**
- DeFiLlama protocol API: 25
- Galxe: 41
- DeFiLlama Rewards JSON API: 93
- PerpDEX Points Index: 19
- Asentum: 2
- Push Chain Season 3: 1
- FLOP testnet: 1
- AIOZ DePIN: 1
- Source errors: **0**
- Latest run status: succeeded
- Authorized spend: **RUB 0**
- Budget ceiling: RUB 5,000

DeFiLlama Rewards previously returned HTTP 200 with no parseable rows because the HTML page is client-rendered. The scanner now uses the structured official API endpoint `https://api.llama.fi/rewards`, filtering to Live + Published programs, excluding hidden/ended/stale records, and preserving verification age. These remain third-party directory leads until official project terms are checked.

The scanner now attaches a heuristic automation assessment to campaign evidence and the AI summary:
- `node_uptime`: can run after setup, but hardware, uptime and reward rate must be checked;
- `passive_holding_or_vault`: may accrue while holding assets, but capital remains exposed to issuer, peg, contract and withdrawal risk;
- `manual_quests`: recurring user actions or wallet signatures;
- `active_trading_or_liquidity`: low fit for the low-touch strategy;
- `unknown`: insufficient details.

This is triage only, not legal eligibility or reward verification.

## Low-touch shortlist

### 1. AIOZ DePIN — best technical fit if existing infrastructure is suitable

Official docs:
- https://docs.aioz.network/aioz-depin/depin-app/depin-cli
- https://docs.aioz.network/aioz-depin/depin-app/gui-cli
- https://docs.aioz.network/aioz-depin/depin-app/overview

- Direct AIOZ token rewards for verified storage, delivery/bandwidth, transcoding and AI work; this is **not an airdrop**.
- Desktop baseline: at least 50 GB free storage and a stable 20 Mbps connection. The CLI can run on Linux servers.
- Minimum withdrawal: 1 AIOZ.
- No fixed reward rate or monthly income estimate is published. No enforced uptime minimum, but more online time increases task opportunities.
- Multiple instances behind one public IP share task assignments; one dedicated key per instance is required.
- Russian-resident eligibility was not established in the docs reviewed.

Decision: only a 7-day pilot on an already-paid, isolated VPS with sufficient spare disk, bandwidth and CPU. Do not rent a new server or purchase hardware. Before installation, inspect current services and resource headroom. Do not share wallet keys or mnemonics.

### 2. Asentum validator testnet — possible unattended node, weak reward certainty

Official docs:
- https://www.asentum.com/nodes
- https://www.asentum.com/docs/getting-started/install-vps
- https://www.asentum.com/docs/investors/growth-fund
- https://www.asentum.com/docs/reference/disclosures
- https://explorer.asentum.com/validators

- Official Growth Fund docs describe a 60M ASE (6% supply) Phase 3 operator allocation.
- Minimum testnet self-bond is 500 ASE; the docs say the installer can obtain test ASE from the faucet.
- Committee has 100 signing seats; the 500 ASE minimum does not guarantee selection. Current explorer snapshots show a higher stake cutoff and hundreds of active validators.
- VPS planning target: 4 CPU cores, 4 GB RAM and 80 GB disk; block storage can grow around 1–2 GB/day.
- Unbonding is approximately 30 days.
- Exact personal payout, current phase qualification and Russian-resident eligibility remain unconfirmed.

Decision: no ASE purchase and no new VPS. Re-check the current committee cutoff, phase qualification, installer provenance and written country eligibility before considering a node.

### 3. FLOP Network — monitor only

Official docs:
- https://docs.flop.network/docs/testnet-and-timeline
- https://flop.finance/testnet/

The public testnet target was 24 November 2026, provisional. Validator requirements were provisionally 8+ CPU cores, 64 GB RAM and 2–4 TB NVMe. This does not fit the current RUB 5,000 budget. Do not rent hardware.

### 4. Push Chain Season 3 — free/manual only

Official docs:
- https://push.org/tos/
- https://portal.push.org/rewards
- https://push.org/blog/push-rewards-program/

The portal advertises Season 3, daily check-in/spins and app quests. Exact S3 allocation and individual points conversion are not published. Some quests involve stablecoin minting or other on-chain app activity. The reviewed terms do not name Russia in the restricted-jurisdiction list, but this is not a legal guarantee. Do not use deposits, betting apps, fake engagement or multi-accounting.

Decision: watchlist only; not autonomous.

## DeFiLlama passive/holding leads — screened out for now

- **GAIB:** current Yield Boost material indicates a USD 300 minimum; above this project's total RUB 5,000 ceiling. Exclude.
- **Strike Finance:** liquidity-provider program requires capital and exposes the deposit to trading/market/withdrawal risks; current stated minimums exceed the budget. Exclude.
- **Unitas:** UP token has already launched; current points do not establish a new guaranteed airdrop. Exclude until a new explicit allocation is announced.
- **Theo:** points are not a guaranteed token or cash payout. Exclude.
- **Ethena:** Season 6 ended on 30 September 2026. Exclude.
- **IPOR Fusion:** current app says providing liquidity and staking are disabled; previous liquidity mining concluded. Exclude.
- **Hylo / Huma / other vault points:** require further official eligibility, live-program and risk checks; no deposit approved.
- **Noon:** points appear to convert into monthly NOON rewards, but current app access is denied from the current session and public terms reviewed did not settle Russia eligibility. Do not attempt to bypass the block; monitor only until the project clarifies eligibility.

## Capital and execution policy

- Total user budget ceiling: RUB 5,000.
- Current authorized spend: RUB 0.
- No deposit, token purchase, leverage, LP, paid server, contract approval or wallet signature without separate user confirmation.
- Prefer existing infrastructure and free testnet assets.
- No VPN/location falsification, borrowed identities, duplicate accounts or KYC evasion.
- Never paste seed phrases or private keys into chat or repository secrets.

## Operational limitation

The GitHub, Railway and Supabase integrations can manage the Airdrop Hunter code and production service. They do not provide SSH access to the user's separate Reg.ru/Aeza VPS. Therefore AIOZ/Asentum installation cannot be safely performed until a secure server-access method is explicitly available and the VPS capacity is verified.

Last screened: 2026-11-17. Re-check live terms, tokenomics, region eligibility and reward rates before any action.
