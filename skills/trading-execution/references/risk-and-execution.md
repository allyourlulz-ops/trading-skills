# Risk and execution
From day-trader-skill (MIT), ai-hedge-fund risk/limits (MIT), QuantDinger agent gating (Apache-2.0), alpaca-mcp-server (MIT).

## Default limits (assets/risk-limits.json)
base_currency USD (the account's), max_risk_per_trade_pct 1 of equity, max_loss_per_trade 50, max_portfolio_heat_pct 6, max_cluster_risk_pct 3 (cluster = same label or |correlation| >= 0.7), max_daily_loss 150, gap_loss_multiple 2, stop_slippage_bps 10, cash_buffer_pct 10, max_position_pct 25, max_order 4000, min_order 5, max_trades_per_day 3, min_reward_risk 1.5, require_stop true, require_data_contract true, no_entries_before 09:45, no_entries_after 15:30 (exchange sessions only; 24/7 crypto skips them), flat_by 15:55 (day trades only), paper true, allow_margin false, allow_options/margin/short false. The user edits these; the agent never loosens them on its own.

## Sizing (scripts/position_size.py; risk_check.py calls the same function)
Inputs come from the broker, not from a fixed budget: equity, buying power, positions and the clock in portfolio.json. Per unit in the base currency: r = (|entry − stop| + entry × stop_slippage_bps/1e4) × multiplier × fx; n = entry × multiplier × fx; g = (|entry − stop| + entry × gap_pct) × multiplier × fx. R = min(equity × max_risk_per_trade_pct, max_loss_per_trade, the user's requested risk) × timing multiplier. qty = floor_to_lot_step(min(R/r, gap_loss_multiple·R/g, heat room/r, cluster room/r, daily room/r, position room/n, max_order/n, buying_power·(1 − buffer)/n)); the smallest names the binding constraint. A request above a limit fails rather than being cut. Options: long premium only, risk = premium × 100. Fractional shares and crypto use the instrument's lot_step. Breakeven win rate with stop slippage c (in R): (1 + c)/(1 + R:R).

## Risk clamps (only ever shrink; removed exposure goes to cash)
per-name cap → net cap → sector cap → beta cap → volatility cap → drawdown halving (at −10%) → gross cap; stop-out at −20% drawdown; ADV cap (order ≤ 5% of 20-day ADV).

## Three-gate execution (one order at a time)
1. `scripts/risk_check.py` returns PASS for this exact order (RESIZE means set qty to `allowed_qty`, add `base_qty` with the original size, and check again) (fingerprint: symbol, side, qty, type, limit, stop).
2. The user types an explicit yes in the conversation that names the ticker and size. Reject "sure", "yes to all", or a yes for a different ticker/amount. Never batch.
3. The client's own allow-once permission card for the order tool.
Exits and stop-reductions are never blocked by daily limits. No orders from scheduled/background runs unless a signed mandate returns AUTO_OK (below). Never ask for API keys in chat; never switch paper→live; never call bulk tools on your own.

## Mandate mode: bots that trade on a standing okay
The user signs one mandate instead of saying yes to every order. `scripts/mandate.py check` replaces gate 2 for orders inside it; gate 1 (risk_check PASS for the exact order, matched by fingerprint) never goes away.

**Signing.** Copy assets/mandate.example.json to assets/mandate.json and fill it with the user, field by field: strategies (only ones that passed the permutation gates and 20+ paper sessions), symbols, asset classes, per-order and daily notional caps, orders per day, open positions, daily loss, total loss, losing-streak stop, and an expiry of at most 30 days. Mode starts as `paper`. `live` needs `live_ack` set to the exact sentence the script names, typed by the user, and a live account they switched to themselves. The agent never edits a mandate to widen it; widening is a new mandate the user signs.

**Bot loop (one order at a time):** data via MCP → strategy signal → order JSON with `strategy`, limit price and stop → `risk_check.py` (with `--context` and `--bar`) → `mandate.py check` →
- AUTO_OK: place it as a bracket/limit order with the stop attached, `mandate.py record` it, then notify the user with the fill, the reason and the day's P&L.
- NEEDS_YES: ask for the normal explicit per-order yes, with the reasons.
- HALT: place nothing new. The script writes a HALT file; tell the user why. Only the user deletes it.
After each close, `record --pnl` so the loss limits and streak stop see it. `status` gives the day's summary; a daily recap goes out at the close.

**Kill switch:** the user says stop, or `mandate.py halt --reason ...`, or `"revoked": true`. Also cancel open agent orders (not resting stops) and revoke the trade token.

**Client permissions for mandate runs:** allow `place_stock_order` (and `close_position`) only in the session or profile that runs the bot; keep `close_all_positions`, `cancel_all_orders`, options and crypto tools denied unless the mandate lists that asset class.

## Money hygiene (from finance-expert's money invariants)
- An amount is a value plus a currency; never add or compare across currencies without a recorded rate, its source and its date.
- Every order carries a `client_order_id` derived from the action (strategy, symbol, signal bar). Send it to the broker too; a retry with the same id must never fill twice. `mandate.py check` refuses a reused id.
- The mandate ledger is append-only. Correct a row by recording a reversal (`record --reverses <id>`), never by editing the file.
- Reconcile the ledger against the broker's own fills every session close: `mandate.py reconcile --broker fills.json`. Any break (a fill the ledger never saw, a quantity or price mismatch, a recorded order that never filled) writes HALT, because the loss limits are only as true as the ledger.
- Fees, FX costs, taxes and perpetual-futures funding are separate lines, never netted into P&L silently.
- Every number shown to the user is labelled: period, currency, realised or unrealised, gross or net of fees, source and as-of time.

## Alpaca client permissions
- Always allow: read-only data/account tools.
- Needs approval: `place_stock_order`, `cancel_order_by_id`, `replace_order_by_id`, `close_position`, `update_account_config`.
- Blocked: `place_option_order`, `place_crypto_order`, `close_all_positions`, `cancel_all_orders`, `exercise_options_position`, `do_not_exercise_options_position`.
Claude Code: `"permissions": {"ask": ["mcp__alpaca__place_stock_order","mcp__alpaca__close_position"], "deny": ["mcp__alpaca__close_all_positions","mcp__alpaca__cancel_all_orders"]}`.
Before an order: `get_clock` (market open?), `get_account_info` (buying power), `get_account_config` (PDT/restrictions), fresh `get_stock_latest_quote`.
Prefer limit or bracket orders with the stop attached.

## Generic gating for any trading MCP (QuantDinger pattern)
Token scopes by risk: read / write / backtest / notify / trade. Every mutating call carries a caller-generated `idempotency_key`. Require explicit `confirm_order=true`; live needs a separate `confirm_live_trading=true` plus a server flag. Keep an emergency stop that cancels agent orders and revokes trade tokens.

## Per-strategy kill switch (scripts/strategy_health.py)
The account limits do not retire a dead strategy. `strategy_kill` in risk-limits.json: RETIRE at 15% drawdown from the strategy's own peak, 90 trading days under water, or average slippage (fill vs decision price) over 25 bps; WATCH under 63 days of record. A retired strategy stops opening positions; restarting it needs a new pipeline.py verdict.

## Staged rollout (never skip a stage)
0. Paper probe: a PAPER_PROBE strategy runs on paper at a quarter of normal size (`"probe": true` in the mandate) to collect forward data, then is reviewed after 63 trading days.
1. Paper: every role runs, the executor only logs. Advance when the funnel works, logs are clean, and `monkey_test.py` and `attribution.py` have been run on the paper positions and shown to the user. ANTI_EDGE blocks advancing; LUCK or BETA_OR_STYLE must be said plainly ("this result can't be told from chance" / "this is market and style exposure"), and the user decides.
2. Small live, every order approved by hand. Advance only when net positive AFTER fees and slippage (paper fills hide both).
3. Semi-auto: auto below a small size, ask above. Advance when the logs show zero broken rules.
4. Unattended runs are out of scope for this skill (rule 7: nothing executes from a background task).
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


## Crypto order-flow context
risk_check reads an optional `orderflow` block in `--context` (from the read-only order-flow MCP; see trading-research references/mcp-servers.md): a liquidation cascade blocks new crypto entries, extreme funding paid by the order's side cuts size (holding cost and squeeze/liquidation tail, not a return signal; skipped when `crosses_settlement` is false, off with `timing.funding_gate_mode: "off"`), and a stream still warming up is ignored. Thresholds sit under `timing` in risk-limits.json.
