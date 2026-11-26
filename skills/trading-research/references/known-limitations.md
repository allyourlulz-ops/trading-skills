# Known limitations

Read this before trusting any output. Each line is a way the skills can still be wrong or bypassed.

## The risk gate
- **It stops skipped steps and edited orders, not a determined agent.** An agent that calls the broker's order tool directly never meets risk_check. The outer wall is outside these skills: paper keys that cannot reach live money, the client's per-call permission prompt, Questrade's Push Approval, IBKR's AI Instructions tab.
- **The nonce key sits on the same machine.** An agent that can read `<gate dir>/gate.key` can forge a pass, sign a mandate or a reconcile stamp. The scripts refuse a gate dir inside the skill, its repository or the caller's project (T7), but they cannot stop an agent that can read `~/.trading-gate`: deny the agent read access to it in the client's permissions. The key and `gate-log.jsonl` share that dir (P7).
- **portfolio.json is assembled by the agent** from broker read tools. Phase 1 binds what it can: `--now` must match the broker clock's own `as_of` (T2), margin is derived from `settled_cash` (T3), exits need the positions read and its time (T3), and a mandate entry needs a reconcile whose broker equity matches the equity risk_check sized from (T5). A consistent fabrication of clock, cash, positions *and* the reconcile inputs still passes; these files are not signed by the broker. Keep live keys out of reach.
- **A paper check may replay a recorded time** (`--now` far from the machine clock gets a warning, not a fail); a live check may not. Nonce expiry always runs on the machine clock too.
- **Positions are verified for exits only.** An entry with `positions: []` still skips open-risk, heat and cluster usage of positions it does not list (register M-items, Phase 2).
- **The override acknowledgement is a convention.** The script checks the exact sentence; it cannot tell who typed it. Overrides are paper only and logged so the user can audit them.
- **Market clock and holidays come from the broker** (`portfolio.clock`). There is no holiday calendar in code.
- **Instrument specs are still caller files.** Keys are whitelisted, multiplier and session are fixed per asset class, and asset class must agree with the symbol's shape (T1, T4), but `currency` and `cluster` are taken as given, and `etf` vs `equity` is only as true as the spec that says `etf`.
- **verify_fill.py checks the fill the agent shows it.** It proves a reported fill matches the checked order; it cannot prove the agent read that fill from the broker.

## Sizing
- **Gap allowances are defaults, not estimates:** 5% for single stocks, 3% for ETFs, 10% for crypto (`instrument_defaults` in risk-limits.json). Set them from the instrument's own history of overnight or weekend moves.
- **Correlations and clusters are inputs.** The script does not estimate them; a missing correlation means "not clustered".
- **Options:** long premium only (risk = premium × multiplier). No short options, no spreads in the sizer, no futures.
- **FX** must be supplied with a source and time; the script will not look one up.
- Mandate caps are in the base currency (`max_order`, `max_daily_notional`, …); v1 `*_usd` keys are still read.
- Mandate P&L (`record --pnl`) is still self-reported; reconcile checks fills and equity, not P&L (P11).

## Data contract
- It checks what each series *declares* (source, times, adjustment, currency), not the numbers. A mislabelled series passes.

## Backtest gate (validate_backtest.py --manifest)
- Lookahead is checked on trade timestamps; whether the strategy *code* peeks is `lookahead_check.py`'s job and is separate.
- Survivorship relies on the `universe.py` result you pass in; regimes rely on the labels you pass in.
- Walk-forward checks fold structure and per-fold results; it does not re-optimise parameters inside each fold.
- The deflated Sharpe uses an approximation unless every trial's Sharpe is supplied (`trial_sharpes`).
- Train-cutoff leakage needs the model's training cutoff from the user or the model card; masking reduces, not removes, memory leakage.

## Supply chain
- Versions and hashes were read from PyPI, npm and Docker Hub on 2026-11-25. The servers were not installed or run here, and the lockfile hashes were not verified with a clean install.
- Hosted servers (Questrade, IBKR) cannot be pinned; tool-description hashes are the only check, and the lock's `tools` stay empty until the user records them.
- The injection scan in `mcp_lock.py` is a pattern list; it catches obvious instructions, not clever ones.

## Evidence
- Every test is synthetic. Nothing here has run against a live or paper broker in this repo's CI.
- Alpaca's paper/live rule was read from alpaca-mcp-server 2.4.1's source, not exercised.
- No strategy in this repo has passed the full backtest gate on real data. No edge is shown or promised.
