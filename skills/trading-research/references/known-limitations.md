# Known limitations

Read this before trusting any output. Each line is a way the skills can still be wrong or bypassed.

## The risk gate
- **It stops skipped steps and edited orders, not a determined agent.** An agent that calls the broker's order tool directly never meets risk_check. The outer wall is outside these skills: paper keys that cannot reach live money, the client's per-call permission prompt, Questrade's Push Approval, IBKR's AI Instructions tab.
- **The nonce key sits on the same machine.** An agent that can read `<gate dir>/gate.key` can forge a pass. Keep the gate dir outside the project folder and deny the agent read access to it in the client's permissions.
- **portfolio.json is assembled by the agent** from broker read tools. risk_check trusts what it is given: a fabricated equity, buying power, position list or `paper: true` passes. Reconcile to the broker (`mandate.py reconcile`) and keep live keys out of reach.
- **The override acknowledgement is a convention.** The script checks the exact sentence; it cannot tell who typed it. Overrides are paper only and logged so the user can audit them.
- **Market clock and holidays come from the broker** (`portfolio.clock`). There is no holiday calendar in code.

## Sizing
- **Gap allowances are defaults, not estimates:** 5% for single stocks, 3% for ETFs, 10% for crypto (`instrument_defaults` in risk-limits.json). Set them from the instrument's own history of overnight or weekend moves.
- **Correlations and clusters are inputs.** The script does not estimate them; a missing correlation means "not clustered".
- **Options:** long premium only (risk = premium × multiplier). No short options, no spreads in the sizer, no futures.
- **FX** must be supplied with a source and time; the script will not look one up.
- Mandate limits (`mandate.example.json`) still use USD-named keys.

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
