# Initial reward triage — 2026-11-17

## Scope

The first successful automated scan returned 66 records:
- 25 DeFiLlama protocol records.
- 41 Galxe campaign records.

These are discovery signals, not 66 verified airdrops.

## Findings

### DeFiLlama — watchlist only

The 25 records describe protocols with Polygon TVL and no listed token symbol. DeFiLlama's protocol listing does not establish an airdrop, points program, reward allocation, eligibility, or claim date. They remain in the campaign database as `discovered`, but their generic review tasks were removed from the active task queue.

### Galxe — screened

Eight campaigns were confirmed ended from their campaign pages and marked `expired`:
- Asterium — $50 raffle (ended 2026-10-31).
- Pilot Partners — USDT raffle (ended 2026-11-04).
- Travala AVA Smart Program (ended 2026-11-01).
- Endorphina — Discord/USDC raffle (ended 2026-10-30).
- M.EDGE Genesis Tester (ended 2026-11-04; OAT is non-cash).
- TapeOcean testnet campaign (page showed ended).
- Sonic Meme Race (ended 2026-10-30; also required a deposit and at least $1 of trading).
- ZCrypto $100 campaign (page showed ended).

Five campaigns remain in the manual review queue. Their rewards are raffles or capped promotional rewards, not guaranteed income:

| Campaign | Publicly displayed reward | Deadline shown on page | Key conditions / caveat |
|---|---:|---|---|
| Midnight Nightforce | $1,500 pool; page shows $30 per winner | 2026-11-21 18:00 GMT-5 | Discord role, activity for at least one day, community call survey; Nightforce application is reviewed separately and is not guaranteed |
| Asterium — Back to the Future | 5 winners × $5 USDT | 2026-11-29 14:00 GMT-5 | Follow X, join official Telegram, like the announcement |
| Asterium — Think Gold | $50 USDT raffle | No end date visible in retrieved page | Re-check campaign is still active before spending time |
| Bond — boosted pools | $5 USDT raffle + 125 Galxe Points | 2026-12-04 13:00 GMT-5 | X and Discord social tasks; do not provide liquidity for this Galxe quest |
| Coincamps — Read & Earn | Maximum 9.3723 USDT, shown as raffle | 2026-12-31 10:59 GMT-5 | Daily reading and social tasks; payout formula, withdrawal rules and odds were not confirmed |

Official campaign pages:
- [Midnight Nightforce](https://app.galxe.com/quest/QxTCYB6zFnNRaMwvNFGpLA/GCojBtZ4LA)
- [Asterium $25 raffle](https://app.galxe.com/quest/Asterium/GCv2HtZpst)
- [Asterium Think Gold](https://app.galxe.com/quest/Asterium/GCuPbtZ1Z3)
- [Bond boosted pools](https://app.galxe.com/quest/9Tz5eRWfWGEuTFUgcNAAbk/GCCCHtZLpm)
- [Coincamps Read & Earn](https://app.galxe.com/quest/Coincamps/GCUMBtZjzn)

Galxe's official sunset notice: [Galxe is integrating into Gravity](https://help.galxe.com/en/articles/18361711-galxe-is-integrating-into-gravity-what-you-need-to-know). Participation in existing quests ends 2026-12-05; reward claims end 2026-12-15.

## Database changes

- 8 campaigns marked `expired`.
- 5 campaigns marked `reviewed`, while eligibility remains `unknown`.
- 61 generic tasks moved to `skipped` with screening notes.
- 5 low-capital cash-reward candidates remain `todo`, ordered by deadline and priority.
- No campaign was marked eligible, claimable, or realized.

## Limitations and next work

- The scan's Galxe GraphQL feed supplies names and an `Active` flag, but the current ingestion path does not reliably persist each page's end date, reward mechanics, or required credentials. This caused expired and non-cash campaigns to enter the queue.
- The five remaining items still require a user-side check of account eligibility and live campaign state. Raffle prizes are not expected income.
- Next engineering step: improve Galxe ingestion so campaign end times, reward type, and required actions are captured before task creation; keep protocol/TVL signals in a separate watchlist.
- No deposits, swaps, trades, wallet approvals, paid subscriptions, or claims were executed.
