# Portfolio care, journals and daily routines

## Crash protection (scripts/crash_guard.py)
Run before adding risk and at least weekly. It returns one exposure multiplier from three rules: volatility target (target vol / EWMA portfolio vol, capped at 1.5x), drawdown brake (0.75 at -10%, 0.50 at -20%, 0.25 at -30%), and a 12-month index trend filter (x0.5 when negative). Below 1 means cut gross exposure to that share; above 1 is permission, not an instruction, and only where the plan allows leverage. It also reports each holding's share of total risk (a 60/40 mix carries roughly 94% of its risk in stocks), inverse-vol weights, 1-day VaR/ES, and a stress test against the 1987, 2000-02, 2007-09, 2020 and 2022 S&P falls. Each rule's failure mode is in the output: say it to the user.

Crash plan (write once, with the user): max acceptable loss, size limits, the vol rule, actions at -10/-20/-30%, and what makes them add back. Free stress gauges: VIX (FRED VIXCLS), high-yield spread (BAMLH0A0HYM2), St. Louis Fed stress index (STLFSI4), 10y-2y curve (T10Y2Y), via the OpenBB `economy` / fred tools.

## Rebalancing and exposure (scripts/rebalance.py)
Drift vs target with a no-trade band (default 5 points), rebalance trades, a DCA plan that fixes underweights with new money before selling, and ETF look-through (your true single-name exposure including what sits inside funds). Every trade still goes through risk_check.

## Trade journal (scripts/journal_stats.py)
Closed trades from chat, a broker CSV or screenshots, mapped to date, symbol, side, entry, exit, planned stop, qty, fees, setup, tags. Reports win rate, expectancy in R and $, profit factor, drawdown, losing streaks, results by setup and by behaviour tag, and every rule break (no stop, risk over limit, off-plan setup, too many trades, loss past the stop). Coach on the worst tag first. Evidence over feelings.

## Forecast scorecard (scripts/scorekeeper.py)
Log every committee rating, persona call, analyst call or X account's call with `--source`. Grade after the horizon against the benchmark. The report gives hit rate, Brier score, calibration by confidence bucket, a per-source reliability ranking and the three worst misses, which feed the committee's "Lessons from prior decisions".

## Daily routines (research only)
- **Pre-market brief (before 09:30 ET):** index futures and overnight moves, the user's watchlist movers with the reason, today's earnings and macro releases with times, new filings (filings-and-flows.md), and anything that trips a risk_check gate. Sources and as-of times on every number.
- **Close recap (after 16:00 ET):** what moved and why, open positions vs plan, journal entries to add, calls to grade.
- **Macro catalyst calendar:** CPI, FOMC, payrolls, GDP, central-bank meetings for the next two weeks, with which holdings each one touches.
- **Regime check:** index vs 50/200-day MAs, VIX level and term structure, credit spread trend, crash_guard multiplier. Pick setups that fit the regime (strategies.md).
- **Watchlist alerts:** quiet when nothing is new. Cross-check any price on two sources before alerting. Mark news as confirmed (primary source) or rumour.
