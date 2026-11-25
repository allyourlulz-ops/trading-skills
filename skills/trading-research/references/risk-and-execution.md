# Risk limits and staged rollout
Orders, mandates and broker permissions live in the separate `trading-execution` skill (install it only if you want the agent to place paper or live orders). This skill places no orders.
From day-trader-skill (MIT), ai-hedge-fund risk/limits (MIT), QuantDinger agent gating (Apache-2.0), alpaca-mcp-server (MIT).

## Default limits (assets/risk-limits.json)
budget 5000, cash_buffer_pct 10, max_position_pct 25, max_order_usd 4000, max_loss_per_trade_usd 50, max_daily_loss_usd 150, max_trades_per_day 3, min_reward_risk 1.5, require_stop true, no_entries_before 09:45 ET, no_entries_after 15:30 ET, flat_by 15:55 ET (day trades only), paper true, allow_margin false. In this research skill allow_short and allow_options are true so proposals and backtests can use short legs and defined-risk options; trading-execution keeps both false until the user turns them on and a signed mandate names them. max_adv_pct 1 for single names, 5 for index ETFs and large caps (max_adv_pct_liquid). Borrow needs a locate and a fee at or under 1,500 bps a year. The user edits these; the agent never loosens them on its own.

## Sizing (scripts/position_size.py)
`shares = floor(min(max_loss / (entry − stop), max_order_usd / entry, budget·max_position_pct / entry))`. Risk for a market order is measured from the higher of planned entry and a fresh quote <15 min old.

## Risk clamps (only ever shrink; removed exposure goes to cash)
per-name cap → net cap → sector cap → beta cap → volatility cap → drawdown halving (at −10%) → gross cap; stop-out at −20% drawdown; ADV cap (order ≤ 1% of 20-day ADV for single names, 5% for liquid ETFs; larger orders part-fill over days, as `premia_signals.py --volumes` simulates).

## Money hygiene (from finance-expert's money invariants)
- An amount is a value plus a currency; never add or compare across currencies without a recorded rate, its source and its date.
- Order ids, the append-only ledger and broker reconciliation: see trading-execution.
- Fees, FX costs, taxes and perpetual-futures funding are separate lines, never netted into P&L silently.
- Every number shown to the user is labelled: period, currency, realised or unrealised, gross or net of fees, source and as-of time.

## Per-strategy kill switch (scripts/strategy_health.py)
The account stop at −20% does not retire a dead strategy. Each strategy has its own limits (`strategy_kill` in risk-limits.json): RETIRE at a 15% drawdown, 90 trading days under water, or average slippage over 25 bps; WATCH under 63 days of record or at under half the expected Sharpe. A retired strategy goes back to research and needs a fresh pipeline verdict.

## Staged rollout (never skip a stage)
0. Paper probe (PAPER_PROBE from pipeline.py): paper only, a quarter of normal size, to collect forward data. Review after 63 trading days with strategy_health.py and re-run the pipeline on backtest plus paper.
1. Paper: every role runs, the executor only logs. Advance when the funnel works, logs are clean, and `monkey_test.py` and `attribution.py` have been run on the paper positions and shown to the user. ANTI_EDGE blocks advancing; LUCK or BETA_OR_STYLE must be said plainly ("this result can't be told from chance" / "this is market and style exposure"), and the user decides.
2. Small live, every order approved by hand. Advance only when net positive AFTER fees and slippage (paper fills hide both).
3. Semi-auto: auto below a small size, ask above. Advance when the logs show zero broken rules.
4. Unattended runs are out of scope (rule 7: nothing executes from a background task).
Scale by at most +50% at a time, re-reviewing weekly. One good week is a sample, not a strategy. Change one rule per week so you know which one worked.

## Regulatory note
Pattern-day-trader rules and margin requirements change; check the broker's current account config (`get_account_config`) rather than assuming a rule.

## Live-bar gates (risk_check.py --bar)
Pass the last bar the signal was computed on: `{"timeframe":"1h","last_bar_open":"2026-11-23T14:00:00+00:00","closed":true}`, with a timezone offset.
- **Unfinished bar:** `closed` not true → BLOCK. Exchanges return the still-forming bar as the last row; drop it before computing the signal, or the bot trades on data the backtest never saw.
- **Frozen feed:** last bar closed more than `timing.max_stale_bars` bars ago (default 3) → BLOCK. An exchange or MCP feed that stops updating looks like a flat market.
- **Clock mismatch:** a bar marked closed that has not closed yet → BLOCK.
Missing `--bar` is a warning, not a block, for one-off orders; bots always pass it. Idea from @sopersone's bot skeleton (X, 2026-10-26); own code.

## Event-timing gates (risk_check.py --context)
Before a new entry, pull a small context from the data MCP server (earnings calendar, last close history, VIX, GLD/TLT/UUP 5-day change) into `context.json` and pass `--context`. Thresholds live under `timing` in assets/risk-limits.json.
- **Earnings blackout:** next earnings within 14 days → BLOCK new entries (set `earnings_blackout_action` to `warn` only if the user asks). Unknown date → warning; treat it as inside the blackout until checked.
- **Post-earnings spike:** up more than 15% within 7 days after earnings → "may be priced in", size ×0.7.
- **Overbought:** RSI(14) > 70 and within 5% of the 52-week high (buys) → size ×0.8.
- **Market stress:** VIX > 30 → size ×0.7.
- **Risk-off:** GLD ≥ +2%, TLT ≥ +1% and UUP ≥ +1% over 5 days together → size ×0.7.
- **VIX backwardation:** VIX above VIX3M (`vix3m` in context) → size ×0.8.
- **Event risk:** `event_risk` entries, each with a primary-source URL (wire report, government statement, company 8-K) and `exposure` direct (×0.7) or sector (×0.85). Entries without a URL are ignored: keyword hits on headlines are not evidence.
- **Crypto BTC drag:** BTC down 10%+ in 5 days and the coin's 30-day correlation with BTC ≥ 0.7 → size ×0.7.
Multipliers compound, floor 0.25, and can only shrink a trade. Exits are never blocked by these gates. Thresholds are heuristics from udiedrichsen/stock-analysis, not backtested; test them with permutation_test.py before trusting them as signals.

