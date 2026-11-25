# Small-capacity edges: where a small book has the advantage

The premia in documented-edges.md are the most crowded trades there are: their capacity is measured in tens of billions. A $5,000 to $500,000 book has one structural advantage over a large fund, and it is **capacity**. It can trade names and events where a large fund's own trading costs eat the edge. This file lists those places, with the published evidence for each.

## The one question, before any compute
**Who is on the other side, and why are they forced to lose?** Write the answer in the strategy contract (`mechanism:`) before you backtest. No mechanism, no compute. A pattern with no forced or uninformed counterparty is a Tier C candidate (strategies.md), however good its backtest looks. `discover.py` flags a survivor with no mechanism as NO_MECHANISM and does not pass it to backtest.

## Capacity is the whole moat
Square-root market impact (Almgren, Thum, Hauptmann and Li, "Direct Estimation of Equity Market Impact", Risk 2005; Toth et al., "Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets", Physical Review X 2011):

    cost (bps) ≈ ½ × spread (bps) + k × σ_daily × √(Q / ADV) × 10,000

Q is the order size and ADV the average daily volume, both in dollars, and k is roughly 1. At σ_daily = 1.5% and k = 1, before the half-spread:

| Q / ADV | Impact |
|---|---|
| 0.1% | 4.7 bps |
| 1% | 15 bps |
| 5% | 34 bps |

On a name trading $20M a day, a 5% position is $250 at a $5,000 book (0.00125% of ADV, about 0.5 bps) and $2.5M at a $50M book (12.5% of ADV, about 53 bps, and more than a day's safe volume). A 4 bps edge per trade is free to the first and dead to the second. `costs.py` charges this impact when the gross file has `adv_frac` and `sigma` columns. Its `capacity` output shows the same strategy at 10×, 100× and 1,000× the capital, so you can see where the edge dies. `premia_signals.py --volumes` simulates part fills at `max_adv_pct` of ADV. Fit k to your own fills once you have 30 or more (`strategy_health.py` measures slippage).

## Where to look
Tier: B means a published mechanism, still to be proven on your own data; C means no peer-reviewed evidence found. No row is Tier A, because none has published post-cost returns at retail size. Every row still goes through `pipeline.py`.

| Edge | Who loses, and why they must | Evidence | Capacity and costs | MCP data route | Tier |
|---|---|---|---|---|---|
| Index adds and deletes, reconstitution (Russell, S&P, MSCI) | Index funds must trade on a known date at the close, whatever the price | Shleifer (JF 1986); Harris and Gurel (JF 1986); Madhavan (FAJ 2003) on the Russell reconstitution; Petajisto (J. Empirical Finance 2011). Patel and Welch (RAPS 2017) found the S&P 500 inclusion effect has largely gone | Low, and front-run once the change is announced. Wide closing prints | Provider announcements (quote the URL); prices and volume via OpenBB | B (S&P adds: decayed) |
| Tax-loss-selling rebound, December into January | Taxable holders sell losers before year end for the deduction, not on value | Roll (JPM 1983); Reinganum (JFE 1983) | Low; mostly small, illiquid losers. Dated, so it can be planned | OpenBB prices; the losers screen is your own code | B |
| Post-earnings drift in thinly covered names | Investors under-react to news few people are paid to read | Bernard and Thomas (JAR 1989); Hirshleifer, Lim and Teoh (JF 2009) on distraction. Chordia et al. (FAJ 2009) found the drift sits in illiquid stocks and costs absorb much of it; Martineau (Critical Finance Review 2022) found it gone in large caps since 2006 and, more recently, in microcaps too | Low: 15 to 40 bps spreads where it lives. Size it with costs.py impact | SEC EDGAR MCP (8-K item 2.02 acceptance time); OpenBB earnings, estimates and prices | B |
| Passive liquidity provision in illiquid names (short-term reversal) | Impatient traders pay to trade now; whoever supplies the liquidity is paid | Nagel, "Evaporating Liquidity" (RFS 2012): reversal returns are liquidity-provision returns and rise when liquidity is scarce. Frazzini, Israel and Moskowitz (2012): reversal dies above about $9bn | Very low. You earn the spread only with limit orders, and get filled most when you are wrong (adverse selection) | Alpaca or broker quotes; needs intraday bars | B |
| Borrow-fee extremes and squeezes | Short sellers forced to cover by recalls and rising fees | D'Avolio (JFE 2002); Engelberg, Reed and Ringgenberg, "Short-Selling Risk" (JF 2018); Drechsler and Drechsler (NBER 2014): high-fee stocks earn low returns, but the fee takes most of the short side | Very low; locate risk. Long squeezes are lottery tickets | Alpaca `locates` toolset or IBKR borrow data; FINRA short interest (filings-and-flows.md) | B (short side), C (squeeze longs) |
| Defined-risk single-name options: earnings IV crush, skew | Hedgers and lottery buyers overpay for options; the variance risk premium | Carr and Wu, "Variance Risk Premiums" (RFS 2009); Goyal and Saretto (JFE 2009); Dubinsky, Johannes, Kaeck and Seeger (RFS 2019) on earnings announcement risk. Bryzgalova, Pavlova and Sikorskaya (JF 2023) found retail option buyers lose on average; Beckmeyer, Branger and Gayda (2023 WP) found the same for 0DTE | A few contracts are fine; spreads and pin risk dominate. Only defined-risk structures (options.md) | Alpaca `options-data`; canli-mcp Cboe delayed chains | B (selling premium, defined risk), C (buying 0DTE) |
| Crypto funding and basis carry | Leveraged directional traders pay to hold perpetual longs | Schmeling, Schrimpf and Todorov, "Crypto Carry" (BIS Working Paper 1087, 2023); He, Manela, Ross and von Wachter, "Fundamentals of Perpetual Futures" (2022 WP) | Medium; exchange, custody and funding-flip risk. Funding is a cost line in costs.py | Exchange data through an MCP server you install (mcp-servers.md); none ships here | B |
| Token unlock calendars | Early holders sell on a schedule | No peer-reviewed study found | Tiny to medium; thin books | On-chain reads (onchain-memecoin.md) | C |
| On-chain LP, new pairs, points | Snipers and farmers, but often you are the one who loses | Loesch et al., "Impermanent Loss in Uniswap v3" (2021): most LPs lost money net of impermanent loss; Qin, Zhou and Gervais, "Quantifying Blockchain Extractable Value" (IEEE S&P 2022) | Tiny; rug and MEV risk (onchain-memecoin.md kill filter) | On-chain reads | C |

## How to work one
1. Write the mechanism. Then write the event definition with its **public time**: a filing's acceptance timestamp, not its period end. Enter at the next bar after that time.
2. Sweep variants with `discover.py`: event, threshold, direction and horizon. It logs every variant to the trial ledger and runs Benjamini-Hochberg across the whole sweep.
3. Backtest the survivors on a point-in-time universe (`universe.py`), with costs.py impact columns and `--trials auto`.
4. `pipeline.py`. PAPER_PROBE is the normal outcome for a real small edge: paper trade it at a quarter of normal size to collect forward data, then check it with `strategy_health.py`.
5. Never assume a published effect still exists. Most rows above have a decay paper; quote it with the claim.
