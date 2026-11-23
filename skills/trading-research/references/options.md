# Options (research only by default)

`allow_options` is false in assets/risk-limits.json. Research, paper and payoff work is fine; live orders need the user to change that limit themselves.

## Data
Alpaca MCP `options-data` toolset (chains, quotes, greeks) or OpenBB `derivatives` category. Record spot, IV, expiry and as-of time with every idea.

## Tools
- `scripts/options_payoff.py`: any multi-leg position (spreads, condors, covered calls, cash-secured puts, stock legs): net credit/debit, max profit and loss (flags unlimited), breakevens, probability of profit at the given IV, net greeks, P&L table at expiry.
- `scripts/risk_check.py --context`: earnings blackout and market-stress gates apply to the underlying.

## Playbooks
- **Defined-risk only:** verticals, iron condors, covered calls, cash-secured puts. No naked short calls.
- **Put credit spreads (45-60 DTE):** liquid names and ETFs, short strike near 0.20-0.30 delta, width sized so max loss passes risk_check, take profit around 50% of credit, close or roll at 21 DTE.
- **Wheel:** sell cash-secured puts only on names the user would own at the strike; if assigned, sell covered calls above cost basis. Cash must cover 100 x strike.
- **Event filter:** no new short-premium positions through earnings; close before major macro releases (CPI, FOMC, payrolls) unless the event is the trade.
- **IV context:** compare IV with its 1-year range (IV rank) and with recent realised vol before calling premium rich or cheap.
- **Same-day (0DTE):** only setups that passed the permutation gates with worst-case fills; stop the setup when its live hit rate drops below the backtest's lower bound.

## Readouts the user may ask for
Most active strikes, put/call volume, open interest walls, skew, and dealer gamma estimates. Label gamma and flow reads as estimates: the data cannot see who is long or short.
