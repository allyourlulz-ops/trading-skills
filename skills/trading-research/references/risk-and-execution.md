# Risk and execution
From day-trader-skill (MIT), ai-hedge-fund risk/limits (MIT), QuantDinger agent gating (Apache-2.0), alpaca-mcp-server (MIT).

## Default limits (assets/risk-limits.json)
budget 5000, cash_buffer_pct 10, max_position_pct 25, max_order_usd 4000, max_loss_per_trade_usd 50, max_daily_loss_usd 150, max_trades_per_day 3, min_reward_risk 1.5, require_stop true, no_entries_before 09:45 ET, no_entries_after 15:30 ET, flat_by 15:55 ET (day trades only), paper true, allow_options/margin/short false. The user edits these; the agent never loosens them on its own.

## Sizing (scripts/position_size.py)
`shares = floor(min(max_loss / (entry − stop), max_order_usd / entry, budget·max_position_pct / entry))`. Risk for a market order is measured from the higher of planned entry and a fresh quote <15 min old.

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

**Bot loop (one order at a time):** data via MCP → strategy signal → order JSON with `strategy`, limit price and stop → `risk_check.py` (with `--context`) → `mandate.py check` →
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
- Fees, FX costs and taxes are separate lines, never netted into P&L silently.
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

## Staged rollout (never skip a stage)
1. Paper: every role runs, the executor only logs. Advance when the funnel works and logs are clean.
2. Small live, every order approved by hand. Advance only when net positive AFTER fees and slippage (paper fills hide both).
3. Semi-auto: auto below a small size, ask above. Advance when the logs show zero broken rules.
4. Unattended runs are out of scope for this skill (rule 7: nothing executes from a background task).
Scale by at most +50% at a time, re-reviewing weekly. One good week is a sample, not a strategy. Change one rule per week so you know which one worked.

## Regulatory note
Pattern-day-trader rules and margin requirements change; check the broker's current account config (`get_account_config`) rather than assuming a rule.

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

