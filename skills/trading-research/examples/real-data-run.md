# Worked run on real prices (2026-11-24, re-run for v1.17.0)

Published premia from references/documented-edges.md, run end to end on real daily data, net of costs, through `pipeline.py`. It shows what the gates do with ordinary strategies. **This 10-ETF set is for illustration only.** Ten correlated ETFs are far too few to judge a cross-sectional signal (backtesting.md, Universe), so `--cross-sectional` stops momentum and low volatility at NOT_READY on that ground alone. The rest of the output is shown because it is instructive.

## Data
- 10 ETFs: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, GLD, DBC, VNQ. Adjusted daily closes (dividends and splits) from Yahoo Finance, the same feed OpenBB's `yfinance` provider returns. 2,513 common trading days, 2016-11-25 to 2026-11-24 (US close, America/New_York). In normal use, pull them with OpenBB MCP `equity.price.historical`. Raw prices are not shipped here.
- Trading period: 2017-11-29 to 2026-11-24 (2,259 days, 8.96 years). The signal uses closes through t−2 and trades at the t−1 close. Three staggered tranches, each rebalanced every 21 trading days. Buy/hold band: enter in the top 30%, hold until a name leaves the top 50%.
- Costs (`costs.json`): 0 commission, 2 bps spread, 3 bps slippage, 50 bps a year to borrow shorts, charged on both legs of each round trip. v1.16.0 charged one leg, so its cost figures were half what they should have been.
- Benchmark: SPY buy-and-hold over the same days, total return +214.0%, Sharpe 0.77, max drawdown −33.7%. Attribution: SPY as the market factor. Trial ledger: 4 variants.

## Commands
```
trial_ledger.py log --id mom12_1 --family premia      # once per variant, before reading its result
premia_signals.py --prices closes.csv --signal mom12_1 --enter 0.3 --keep 0.5 --tranches 3 --backtest mom12_1
pipeline.py --gross mom12_1_gross.csv --costs costs.json --benchmark bench.csv --family premia \
            --positions mom12_1_positions.csv --group day --weights mom12_1_weights.csv --prices closes.csv \
            --factors factors.csv --cross-sectional
```

## Results (USD, net of costs unless marked)
| Signal | Gross a year | Net a year | Costs, bps a year | Net at 3× costs | Sharpe | Max drawdown | Deflated Sharpe | Beta | Benchmark tests failed | Coin flip: direction / exposure held equal | Attribution | Sharpe by regime: calm, normal, stressed | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12-1 momentum, long only | 9.48% | 9.35% | 11.1 | 9.11% | 0.67 | −22.7% | 0.82 | 0.68 | risk-adjusted, marginal, directional | 98.9th / 64.0th pct | BETA_OR_STYLE | −0.05, 1.20, 0.75 | NOT_READY (universe) |
| Low volatility, long only | 6.66% | 6.61% | 4.3 | 6.52% | 0.73 | −23.0% | 0.87 | 0.31 | risk-adjusted, directional | 97.8th / 26.1st pct | BETA_OR_STYLE | 0.58, 1.17, 0.63 | NOT_READY (universe) |
| Trend (TSMOM, 10% vol target) | 0.90% | 0.68% | 21.6 | 0.25% | 0.15 | −15.3% | 0.27 | 0.14 | risk-adjusted, marginal | 72.1st pct / n.a. (holds every name) | BETA_OR_STYLE | 0.04, 1.00, −0.50 | PAPER_PROBE |
| 12-1 momentum, long-short | 0.79% | 0.42% | 36.3 | −0.30% | 0.10 | −16.9% | 0.22 | 0.11 | risk-adjusted, marginal | 67.6th / 36.1st pct | BETA_OR_STYLE | −0.13, 0.26, −0.01 | NOT_READY (3× costs, universe) |

## What the run taught (folded into the skill)
1. **The coin-flip test read beta as skill.** Long-only momentum beat 98.9% of the direction monkeys. With weights and exposure held equal and only the names random (`--mode beta_matched`), it sat at the 64th percentile: no selection skill. Low volatility fell to the 26th, because the random names were mostly equities and it held bonds.
2. **The objective matters.** Low volatility trails SPY by 136 points of total return, yet a 70/30 SPY/low-vol mix had a higher Sharpe (0.81 vs 0.77) and a smaller drawdown (−27.5% vs −33.7%). The old gate called that a failure. The marginal test now says it adds to the book. It still fails the risk-adjusted test, and on 10 ETFs it cannot be judged at all.
3. **The short leg was the missing half, and on 10 ETFs it is noise.** Long-short momentum made 0.4% a year net and went negative at 3× costs. That is the universe, not the premium: the papers rank thousands of names.
4. **The probe exists for cases like trend.** Its mechanics are clean but its alpha is unproven, so it may paper-trade at a quarter of normal size to gather forward data. It is not a recommendation: Sharpe 0.15 and losses in stressed markets in this sample.
5. **Costs were understated by half before v1.17.0.** They still did not decide these results.

Reproduce it with your own MCP data before relying on any figure here.
