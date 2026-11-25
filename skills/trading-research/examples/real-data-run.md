# Worked run on real prices (2026-11-24)

Three published premia from references/documented-edges.md, run end to end on real daily data, net of costs, through `pipeline.py`. All three came out NOT_READY, which is the result. It shows what the gates do with ordinary strategies.

## Data
- 10 ETFs: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, GLD, DBC, VNQ. Adjusted daily closes (dividends and splits) from Yahoo Finance, the same feed OpenBB's `yfinance` provider returns. 2,513 common trading days, 2016-11-25 to 2026-11-24 (US close, America/New_York). In normal use, pull them with OpenBB MCP `equity.price.historical`. Raw prices are not shipped here.
- Trading period: 2017-11-28 to 2026-11-24 (8.96 years; the first year is the signal lookback). Rebalanced every 21 trading days, buy/hold band entering at the top 30% and holding until a name leaves the top 50%.
- Costs (`costs.json`): 0 commission, 2 bps spread, 3 bps slippage, 50 bps a year to borrow shorts.
- Benchmark: SPY buy-and-hold over the same days. Attribution: SPY as the market factor only.

## Commands
```
premia_signals.py --prices closes.csv --signal mom12_1 --enter 0.3 --keep 0.5 --backtest mom12_1
pipeline.py --gross mom12_1_gross.csv --costs costs.json --benchmark bench.csv --trials 3 \
            --positions mom12_1_positions.csv --group day --factors factors.csv
```
`--trials 3` because three signals were tried. Deflated Sharpe counts that.

## Results (USD, net of costs unless marked)
| Signal | Gross a year | Net a year | Costs, bps a year | Sharpe | Max drawdown | Deflated Sharpe | Total, net | SPY total | Coin-flip | Market beta | Share of return from market | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12-1 momentum | 9.70% | 9.64% | 5.9 | 0.67 | −22.6% | 0.87 | +127.1% | +213.8% | LUCK, 98.8th pct | 0.68 | 96% | NOT_READY |
| Low volatility | 6.72% | 6.69% | 2.1 | 0.74 | −23.1% | 0.91 | +77.9% | +213.8% | LUCK, 98.6th pct | 0.31 | 65% | NOT_READY |
| Trend (TSMOM, 10% vol target) | 1.39% | 1.21% | 17.5 | 0.23 | −11.5% | 0.43 | +10.9% | +213.8% | LUCK, 81.3rd pct | 0.12 | 125% | NOT_READY |

All three failed `validate_backtest` (WEAK: deflated Sharpe under 0.95 and below buy-and-hold) and came out BETA_OR_STYLE. Selection t-stats were 0.16, 0.99 and −0.19.

## What the run taught (folded into the skill)
1. **The coin-flip test reads beta as skill on a long-only book.** Momentum beat 98.8% of the monkeys, yet 96% of its return was market exposure. A monkey goes short half the time in a rising market. `monkey_test.py` and backtesting.md now say so. Always read it next to `attribution.py`.
2. **Costs were small; turnover was the lever.** At about 1.45 one-way turnovers a year, a 5 bps one-way cost took 6 bps a year from momentum. Borrow was most of trend's 17.5 bps. Costs did not decide these results; the bull market in SPY did.
3. **On a 10-ETF universe, ten years, these premia did not beat SPY.** That agrees with the decay figures in documented-edges.md. It is not a test of the papers, which used thousands of stocks or futures.

Reproduce it with your own MCP data before relying on any figure here.
