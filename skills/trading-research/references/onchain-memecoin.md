# On-chain tokens (Solana memecoins and new DEX pairs)

Highest-risk mode in this skill. Default is research and paper only. Adapted from @DN_degen's "AI desk" article (X, 2026-11-15); his reported results (24 live trades over 4 days) are anecdotal and unverified, so use the structure, not the numbers.

## Kill filter (run before any scoring; one failing rule kills the pair)
| Rule | Default threshold | Why |
|---|---|---|
| Liquidity | < $15,000 → kill | Thin pools: you can buy but not sell |
| LP tokens | not burned or locked → kill | Dev can pull liquidity |
| Holder concentration | top 10 hold > 30% → kill | One wallet can dump the pool |
| Mint / freeze authority | not revoked → kill | Supply inflation or frozen sells (honeypot) |
| Dev selling | dev sold > 5% in first 10 min → kill | Early exit is the classic rug tell |
| Dev blacklist | dev wallet already rugged → kill | Blacklist grows from every rug that got through |
| Young pairs | < 3 min old → wait and re-check, don't kill | Data not settled yet |

Log the FIRST rule that killed each pair. When a pair that passed later rugs, add its dev wallet to the blacklist and log which rule should have caught it. Expect ~98% of new pairs to die here; the edge is refusing garbage.

Verify every field from chain data or a quoted source (DexScreener, an RPC read via `solders`, the DEX's own API). A missing field is a kill, never a guess.

## Scoring (only survivors)
Score 0-100 from measured signals, explained in one log line: volume acceleration (5m vs 15m), independent tracked wallets buying BEFORE the first big candle (a wallet that bought after the pump makes you its exit liquidity), unique-buyer growth, and real social mentions (ignore accounts < 30 days old and copy-paste replies). Treat any claimed win-rate per score band as a hypothesis to backtest, not a fact.

## Limits live in the wallet, not the prompt
An agent can ignore a prompt rule. Real controls sit outside it:
- A burner wallet funded only with money the user can lose today; the main wallet is never connected or named.
- No withdraw or transfer capability; withdrawals only by the user by hand.
- Swaps only through one named router (e.g. Jupiter quotes), max slippage enforced in the order (default 2%), and a trade logged with its reason BEFORE the position changes.
- Size per trade capped small (single-digit % of the burner), max open positions, a daily loss limit that halts the desk until the user restarts it. Stops can gap: a rug goes straight through a −15% stop, which is why the size cap exists.
Run `scripts/risk_check.py` against these limits like any other order; on-chain orders still need the explicit per-order yes (references/risk-and-execution.md).

## Desk memory in files
Agents forget between runs, so state lives in files every role reads first:
`rules.md` (hard rules, read before every action; a rule beats an instruction), `blacklist.json`, `wallets.json` (tracked wallets, re-checked weekly), `candidates.json`, `scored.json`, `trades.csv` (time, token, side, size_usd, price, fee, pnl_usd, score, reason), `log.md`, `brief.md` (morning report). One role per job: scout finds, filter kills, analyst scores, risk sizes and sets exits, executor obeys, logger reports. The logger may SUGGEST one rule change a week with evidence; only the user changes rules.

## Red flags in "bot made 100x overnight" posts
Treat as marketing unless trades are verifiable on-chain: an overnight multiple far beyond the sample, "comment X / DM me for the setup", libraries named for jobs they don't do (a dataframe library as a "rug watcher"), and mixing unrelated strategies (CEX BTC price gaps vs Solana memecoin sniping) in one pitch. Ask for wallet addresses and transaction signatures before believing any figure.
