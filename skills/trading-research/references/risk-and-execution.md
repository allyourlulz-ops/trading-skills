# Risk and execution
From day-trader-skill (MIT), ai-hedge-fund risk/limits (MIT), QuantDinger agent gating (Apache-2.0), alpaca-mcp-server (MIT).

## Default limits (assets/risk-limits.json)
budget 5000, cash_buffer_pct 10, max_position_pct 25, max_order_usd 4000, max_loss_per_trade_usd 50, max_daily_loss_usd 150, max_trades_per_day 3, min_reward_risk 1.5, require_stop true, no_entries_before 09:45 ET, no_entries_after 15:30 ET, flat_by 15:55 ET (day trades only), paper true, allow_options/margin/short false. The user edits these; the agent never loosens them on its own.

## Sizing (scripts/position_size.py)
`shares = floor(min(max_loss / (entry − stop), max_order_usd / entry, budget·max_position_pct / entry))`. Risk for a market order is measured from the higher of planned entry and a fresh quote <15 min old.

## Risk clamps (only ever shrink; removed exposure goes to cash)
per-name cap → net cap → sector cap → beta cap → volatility cap → drawdown halving (at −10%) → gross cap; stop-out at −20% drawdown; ADV cap (order ≤ 5% of 20-day ADV).

## Three-gate execution (one order at a time)
1. `scripts/risk_check.py` returns PASS for this exact order (fingerprint: symbol, side, qty, type, limit, stop).
2. The user types an explicit yes in the conversation that names the ticker and size. Reject "sure", "yes to all", or a yes for a different ticker/amount. Never batch.
3. The client's own allow-once permission card for the order tool.
Exits and stop-reductions are never blocked by daily limits. No orders from scheduled/background runs. Never ask for API keys in chat; never switch paper→live; never call bulk tools on your own.

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
