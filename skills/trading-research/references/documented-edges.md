# Documented edges: strategies with published post-cost evidence

These are the strongest public claims of positive expectancy after costs we could find, each with its source. They are evidence from the past, not a guarantee. Quote the figure, the period, the basis (gross, net of costs, net of fees, simulated or live) and the source every time. Signals: `scripts/premia_signals.py`.

## The claims, as published
| Strategy | Claim | Basis | Source |
|---|---|---|---|
| Size, value, momentum (long-short equity factors) | Survive trading costs at large size. Break-even fund size, US: size $103bn, value $83bn, momentum $52bn; global $156bn, $190bn, $89bn. Value plus momentum combined: $100bn US, $177bn global | Costs measured on about $1 trillion of a large manager's live trades (AQR), 19 developed markets, 1998 to 2011, applied to factor returns | Frazzini, Israel and Moskowitz, "Trading Costs of Asset Pricing Anomalies", AQR working paper, 5 Dec 2012. A later version gives US break-evens of $275bn, $214bn and $56bn |
| Short-term reversal | Does not survive costs above $9bn in the US or $13bn globally | Same live cost data | Same paper |
| Low-turnover anomalies (one-sided turnover under 50% a month) | Most generate significant net spreads when built to cut costs; size, value and profitability have the most capacity | Effective bid-ask spread costs (small trader), US equities | Novy-Marx and Velikov, "A Taxonomy of Anomalies and Their Trading Costs", Review of Financial Studies 29(1), 2016 |
| Buy/hold spread | The most effective cost cut: stricter rule to enter a position than to keep it | Same | Same |
| Time-series momentum (trend following across futures) | 1880 to 2013: 14.9% a year gross, 11.2% a year after simulated costs and 2/20 fees, 9.7% volatility, Sharpe 0.77 net. 2000 to 2013: 7.9% a year net | Simulated, not a live fund. Costs estimated, futures roll costs not included | Hurst, Ooi and Pedersen, "A Century of Evidence on Trend-Following Investing", Journal of Portfolio Management 44(1), 2017 |

## What happens after the paper (quote this with any claim above)
- 97 published predictors: returns 26% lower out of sample and 58% lower after publication (McLean and Pontiff, Journal of Finance 71(1), 2016).
- After costs and after publication, the average cost-mitigated anomaly earned about 13 bps a month, or 4 bps depending on how it is averaged (Chen and Velikov, "Accounting for the Anomaly Zoo: a Trading Cost Perspective", 2019 working paper).
- No live retail track record is included here. Every figure above is a factor or simulated return, not an account anyone can audit. Treat a seller's "live track record" as unverified until it comes with broker statements or on-chain transactions and passes `monkey_test.py` and `attribution.py`.

## How to use them
1. Pick a premium and its signal: `premia_signals.py --signal mom12_1|lowvol|tsmom` on MCP closes. Use the universe as it stood on each date.
2. Keep turnover low: the default buy/hold band enters at the top 20% and holds until the name falls below the top 40%. Monthly rebalance only.
3. Backtest net of your own costs (commission, spread, borrow, funding as separate lines) through `validate_backtest.py`, `permutation_test.py` and `overfit.py`. Then paper trade (risk-and-execution.md staged rollout).
4. Expect less than the paper: plan on about half the published premium (the 58% post-publication fall) and long losing stretches. Momentum has crashed in sharp rebounds; value lagged for years at a time.
5. Report returns with buy-and-hold beside them, and run `attribution.py`. A factor premium will show up as style, not selection alpha, which is the point: you are being paid for a known exposure.
