# Backtesting

## Choose an engine
| Need | Engine |
|---|---|
| Multi-market, quick, agent-written | Vibe-Trading `backtest` (MCP) with the SignalEngine contract |
| Crypto, rigorous, optimisation | freqtrade CLI (GPL-3.0; call as a tool, don't embed code) |
| US equity, event-driven, teaching | zipline-reloaded (original quantopian/zipline is dead) |
| China A-shares (T+1, limits) | tick-stock-panel `run_backtest` |
| Intraday equities/crypto, same code backtest → paper → live | NautilusTrader (LGPL-3.0, `pip install nautilus_trader`) |
| Intraday ML rules, walk-forward on minute bars, Alpaca data | PyBroker (`pip install lib-pybroker`; Apache-2.0 + Commons Clause) |
| Sweeping thousands of parameter combos fast | vectorbt community edition (`pip install vectorbt`; Fair-code licence) |
| Scalping / market making where queue position and latency matter | HftBacktest (MIT, `pip install hftbacktest`; needs L2 book + trade ticks) |
| Factors / overfitting stats | QuantDinger `submit_factor_benchmark` or Vibe-Trading `alpha bench` |

### Lightweight Python options
- **backtesting.py** (kernc/backtesting.py, AGPL-3.0): quick single-asset OHLCV backtests with `Backtest(df, Strategy, cash=..., commission=...)` and `bt.optimize(...)`. Run it as a separate dependency; don't copy its code into this skill (AGPL). Treat `optimize` output as in-sample until it passes the validation below.
- **pyfolio-reloaded** (stefan-jansen, Apache-2.0): tearsheets from a returns series (`pf.create_returns_tear_sheet(returns, benchmark_rets=...)`). The original quantopian/pyfolio has had no updates since 2023; use the reloaded fork.

### Day-trading engines (audited 2026-11-23)
- **NautilusTrader**: Rust core, Python strategies, nanosecond event-driven sim on quote/trade ticks, bars and order books; the same strategy class runs live through adapters (IBKR, Binance, Bybit, Databento and more). Its docs list backtest-vs-live differences (venue, timing, reconciliation); read them before trusting a fill. Best choice when a strategy will go to paper/live. Heavier to set up. Use as a dependency (LGPL).
- **PyBroker**: NumPy/Numba engine with built-in walk-forward (`strategy.walkforward(timeframe='1m', windows=5, train_size=0.5)`) and bootstrap metrics, so it covers rule 8 and the validation gates natively. Pulls Alpaca, Yahoo or AKShare data. Ships its own Agent Skills. Commons Clause: don't resell it.
- **vectorbt**: fastest way to grid-search signals on intraday bars. Grids find noise: count every combination tried and pass it as `--trials` to `scripts/validate_backtest.py` (Deflated Sharpe). Community edition lacks limit orders and leverage (PRO, paid); treat its fills as market-at-close approximations.
- **HftBacktest**: only when the edge lives in the book (order-book imbalance, quoting). Models feed and order latency plus queue position from full L2 + trade data; bar data won't do. Python backtests; its live bot (Binance Futures, Bybit) is Rust-only and out of scope.

Day-trading realism checklist (any engine): commission AND spread AND slippage per side; no fills inside the bar you signalled on; minute data has gaps and halts, so report them; account for the open/close auctions; check the US pattern-day-trader rule and broker margin before sizing. For minute-bar equity curves pass `--periods 98280` (252 × 390) to the validator, or resample to daily first.

## Vibe-Trading SignalEngine contract
```python
class SignalEngine:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        # per code: signal in [-1.0, 1.0]; 1 long, 0 flat, -1 short
```
```json
{"source":"auto","codes":["AAPL"],"start_date":"2016-01-01","end_date":"2026-01-01",
 "warmup_bars":200,"interval":"1D","initial_cash":100000,"commission":0.001,"engine":"daily",
 "validation":{"monte_carlo":{"n_simulations":1000},"bootstrap":{"n_bootstrap":1000,"confidence":0.95},"walk_forward":{"n_windows":5}}}
```
- The engine already fills a signal at t on the t+1 open: **never `.shift(1)` yourself**.
- Declare `warmup_bars`; don't backdate `start_date`.
- Default window 10 years. Never hard-code dates or symbols inside the engine.
Template: assets/signal_engine_template.py.

## freqtrade workflow (dry-run only)
```bash
freqtrade create-userdir --userdir user_data
freqtrade new-config --config user_data/config.json      # dry_run: true
freqtrade download-data --exchange binance --pairs BTC/USDT ETH/USDT --timeframes 5m 1h --timerange 20240101-
freqtrade backtesting --strategy MyStrat --timeframe 1h --timeframe-detail 5m --timerange 20250101-20250701 --breakdown month
freqtrade lookahead-analysis --strategy MyStrat
freqtrade recursive-analysis --strategy MyStrat
freqtrade hyperopt --hyperopt-loss SharpeHyperOptLossDaily --strategy MyStrat --spaces buy sell roi stoploss -e 500 --early-stop 100 --random-state 42
freqtrade backtesting --strategy MyStrat --timerange 20250701-       # out-of-sample, frozen params
```
Strategy = `IStrategy` (INTERFACE_VERSION 3) with `populate_indicators`, `populate_entry_trend` (`enter_long`), `populate_exit_trend` (`exit_long`), plus `minimal_roi`, `stoploss`, `timeframe`, `startup_candle_count`. Hyperopt params: `IntParameter`, `DecimalParameter`, `CategoricalParameter`, `BooleanParameter`. Never run `freqtrade trade` with real keys from this skill.
Fill assumptions to state: entry at next open, no slippage inside the bar, stop checked before ROI, low before high.

## zipline-reloaded
```python
from zipline import run_algorithm
perf = run_algorithm(start=pd.Timestamp('2018-01-01'), end=pd.Timestamp('2024-01-01'),
    initialize=initialize, handle_data=handle_data, capital_base=100_000,
    data_frequency='daily', bundle='my-csv-bundle', benchmark_returns=spy_returns)
```
CLI needs `--no-benchmark` or `--benchmark-symbol`. The Quandl WIKI bundle ends in 2018; use a CSV bundle for current data.

## Hard gates (Vibe-Trading backtest-diagnose)
Fail and fix if any is true: run exited non-zero; metrics or equity file missing; NaN in equity; **zero trades**; first trade >2 years after start; average capital use <50% when the strategy should be invested; position still open at the end unreported; excess return implausible (check the benchmark series and look-ahead). Ignore provider rate-limit errors (retry, don't rewrite code). **Max 3 repair iterations**, then report.

## Screening many rules at once (run scripts/rule_screen.py)
Method adapted from roan-maverick/MIT-trader-skill's strategy hunter (MIT code, built on MIT OCW 18.S096). Use it before backtesting any single rule in depth, whenever you are choosing among variants (dip depths, lookbacks, holding periods).
1. **Pooled event study.** For every symbol and every day a rule fires (entries at least one holding period apart), record the h-day return in the trade's direction minus that symbol's ordinary h-day return minus round-trip costs (default 10 bps a side). That is the rule's excess per trade, not its raw return.
2. **Cluster by week.** A market selloff fires a dip rule on 40 stocks at once: one bet, not 40. Average excess per entry week and take the t-stat over weeks.
3. **Split by date.** First 70% of history is in-sample; the last 30% plays no part in discovery.
4. **Control false discoveries.** Benjamini-Hochberg at 10% on the in-sample one-sided p-values across EVERY variant tried; report the Bonferroni bar too. Each new variant raises the bar for all of them.
5. **Approve** only a BH discovery with ≥30 in-sample trades AND ≥10 out-of-sample trades with positive excess and t ≥ 1. A discovery that dies out of sample is FAILED_OOS, the classic overfit.
6. **If nothing is approved, stand down** and say so plainly. On liquid US stocks simple rules usually fail out of sample; that is the screen working.
Feed survivors into the full backtest + `scripts/validate_backtest.py --trials auto` (the trial ledger counts every variant screened). Pass `--tried N` when some variants produced no trades, so they still count in the correction; `discover.py` does this for you. For the maths behind each step, the companion `mit-trader` skill's lecture notes (CC BY-NC-SA 4.0, not bundled here) map them to 18.S096 lectures.

## Ablation (one rule at a time)
Build a strategy up from its base signal, adding one filter per run and logging the equity, drawdown and trade count each time. Keep a filter only if it improves out-of-sample results by more than noise; log every run in the trial ledger. A filter that only helps in-sample is curve-fitting.

## Permutation gates (run scripts/permutation_test.py)
Optimisation always finds something, even in noise. These gates ask whether the optimised result beats the same optimisation run on shuffled price paths (same start, end and bar-return distribution, every real pattern destroyed). Pull closes through the data MCP server (OpenBB `equity_price_historical`, Alpaca stock/crypto bars, CCXT), save `date,close` to CSV, then run locally. No outside platform is needed.
- **Measure every bar.** Position is 1, -1 or 0 on each bar; score bar returns (profit factor), not per-trade results.
- **Gate 1, in-sample:** optimise on ~4 years. Mediocre here is worse everywhere else; too perfect usually means a leak.
- **Gate 2, in-sample permutation:** `--mode insample --perms 1000`. Pass at p < 0.01. Run before touching walk-forward data, so failed ideas never see it.
- **Plateau check** (same run): a real edge keeps most of its score one grid step away (`PLATEAU`); a `SPIKE` is a lucky setting, reject it. A plateau alone proves nothing: noise can be flat too.
- **Gate 3, walk-forward:** re-optimise on the trailing window (`--train`, e.g. 1008 daily bars), trade the next `--test` bars (e.g. 21), roll forward. Worse than in-sample is normal; it must still be worth trading.
- **Gate 4, walk-forward permutation:** `--mode walkforward`; only bars after the first training window are shuffled. Pass at p < 0.05 with ~1 year out of sample, p < 0.01 with 2+ years. Slow: start with `--perms 200`, confirm finalists at 1000.
- Testing 100 ideas against the same walk-forward year and keeping the best overfits it anyway. Log every idea in the trial ledger (`scripts/trial_ledger.py`).
- A strategy that passes all four earns a paper account, then the staged rollout in risk-and-execution.md. Re-run Gate 4 weekly on new data; anything that starts failing goes back to research.
Method: Timothy Masters' permutation testing for trading systems, as laid out in a @rohonchain article (2026-11-11). Reimplemented here from the description; the article's platform pitch is not part of this skill.

## The gate: validate_backtest.py --manifest (fail closed)
One manifest names every input; any missing input is a fail, never a skip. Ten checks, each pass or fail:
alignment (dates parse, strictly increasing, gross/net/benchmark/turnover share 95% of dates; no positional pairing), lookahead (every entry on a later bar than its signal), same_bar (a bar that touched both stop and target is booked as the stop), survivorship (single instrument, or a `universe.py` OK that includes delisted names), costs (fees and slippage both declared; net = gross − 2 × turnover × bps within 0.1 bp a period), walk_forward (≥ 3 ordered, non-overlapping test folds after their train windows; half or more with net Sharpe > 0), deflated_sharpe (≥ 0.95 at the declared trial count; exact cross-trial form when `trial_sharpes` is given, else the estimation-variance approximation, labelled), cost_sweep (net Sharpe and return > 0 at 1×, 2× and 3× costs), regimes (≥ 2 regimes with 63+ periods; no regime supplies more than all of the return), train_cutoff (LLM in the loop: no test period on or before the model's training cutoff unless masked with `mask.py`; no LLM: not applicable, stated). `scripts/engine.py` writes manifest-ready gross, net, turnover and trades files with next-bar fills and stop-first bars; its engine/market-rules split follows HKUDS/Vibe-Trading's SignalEngine and BaseEngine design (studied; no code or dependencies used). Golden fixtures for each failure: `evals/golden/`.

## Statistics report (validate_backtest.py flag mode, used by pipeline.py)
Not the gate; its output says `"rigor": "not checked"`. Report all of:
- CAGR, Sharpe, Sortino, max drawdown + duration, win rate, profit factor, expectancy, trade count.
- Buy-and-hold over the same window ("market change") and the delta.
- **Benchmark test that fits the sleeve** (in the verdict): net Sharpe above the benchmark's; a 70/30 benchmark/strategy mix with a higher Sharpe AND a smaller drawdown than the benchmark alone (does it add to the book?); and total return at least the benchmark's only for directional sleeves (auto: |beta| ≥ 0.3). A market-neutral sleeve at Sharpe 1.6, 8% a year, is not asked to beat a 13% index. `--sleeve` overrides the auto choice; say why.
- Trials from the ledger (`--trials auto`). A hand-typed count is flagged; no ledger is flagged louder.
- Mean-trade t-test p-value (optimistic: trades aren't i.i.d.).
- Bootstrap 95% CI of Sharpe.
- Deflated Sharpe ratio given the number of variants tried (multiple testing).
- Walk-forward (≥5 windows) and a final out-of-sample holdout with frozen parameters.
- Costs: spread bps, commission, square-root impact `k·σ_daily·sqrt(order/ADV)` (`costs.py`, with `adv_frac` and `sigma` columns), the cost multiples (it must stay above zero at 3× costs), the cost ladder and the capacity curve.
- Reproducibility log: strategy version/hash, symbols, dates, price basis (adjusted?), costs, seed, data snapshot.
State plainly: "Backtests overstate live results."

## Overfitting gates for a family of variants (run scripts/overfit.py)
Read this section when more than one variant, parameter set or rule was tried. Pass the whole family, losers included.
- `overfit.py pbo --returns variants.csv --blocks 10`: probability of backtest overfitting (combinatorially symmetric cross-validation). PBO <= 0.20 PASS, <= 0.50 CAUTION, else FAIL. A negative `is_to_oos_slope` means the better a variant looked in sample, the worse it did out of sample.
- `overfit.py dsr --returns variants.csv`: deflated Sharpe for the in-sample best (or `--pick NAME`), with the expected best Sharpe from luck alone for this many trials. Promote only at DSR >= 0.95.
- `overfit.py cpcv --n ROWS --groups 6 --test-groups 2 --horizon H --embargo 0.01`: combinatorial purged cross-validation folds. Train rows whose label window (`--horizon` bars) overlaps a test block are purged, and an embargo follows each test block. Use for any model that is fitted, not just thresholded.
- A variant is promotable only when it clears the hard gates, the permutation gates, PBO and DSR, and still beats buy-and-hold after costs. Methods: Bailey, Borwein, Lopez de Prado and Zhu (2014); Bailey and Lopez de Prado (2014); Lopez de Prado (2018). Own stdlib implementation.
- Optional local cross-checks (user installs, see mcp-servers.md): canli-mcp and backtester-mcp report deflated Sharpe and PBO too. When they disagree with overfit.py by more than rounding, show both and treat the result as unverified.

## Edge or exposure?
A long-only book in a bull market beats most coin-flip monkeys on beta alone (examples/real-data-run.md: momentum at the 98.9th percentile on direction, 64th with exposure held equal). Use `monkey_test.py --mode beta_matched --weights W --prices P`: same weights, dates and net exposure, random names. It isolates selection from beta. Read it with attribution.
 (run scripts/monkey_test.py and scripts/attribution.py)
A good return can come from being in a rising market, from a style that happened to win, or from luck. Run both checks on paper or backtest results before calling anything an edge:
1. **Coin-flip test** (`monkey_test.py --positions positions.csv`): 2,048 monkeys keep every position at the same times and sizes and flip a coin for the side. EDGE needs the real result to beat all but one of them; ANTI_EDGE means the calls were reliably wrong; LUCK is everything between. Use `--group day` when a day's trades are one bet. This only tests direction; timing and size are held fixed. In Alpha Arena season 1.5 (Nof1, 19 Nov to 3 Dec 2025), the account inferred as the winner, Grok 4.20, was +32.5% yet sat at the 82.6th percentile of its monkeys, and none of the 32 accounts cleared the bar (oaia.fun, 10 Nov 2026; wallet labels inferred).
2. **Attribution** (`attribution.py --returns port.csv --factors factors.csv`): splits return into market, style (size, momentum, value, low volatility, quality) and selection. SELECTION_ALPHA needs selection t >= 2, information ratio >= 0.5 a year and > 52% of days positive; otherwise BETA_OR_STYLE, which a cheap ETF mix would have matched. Use independent factor proxies (`factor_proxies.py`: mkt SPY; size IWM, momentum MTUM, low volatility USMV, quality QUAL, value VLUE, each minus SPY). Factors built from the strategy's own universe on its own rebalance day share its noise and leave a day-of-week artifact; if you must build them, stagger their rebalance day away from the strategy's (`premia_signals.py --tranches`); `--window 60` refits on a trailing window so no future betas leak in. KTD-Fin (arXiv 2605.28359, 2026) found LLM agents on CSI300 were mostly "style harvesters" with negative selection alpha despite high returns.
3. **Masked replay for LLM strategies** (`mask.py mask --level blinded`): replace tickers with `asset_NNN` and dates with `day_+N` before the model sees the data, unmask its tool arguments with the key, and re-mask the results. Compare bright vs blinded runs: a strategy whose edge disappears under masking was recalling history, not reasoning. Run `mask.py check` on every prompt file; LEAK blocks the run. News text is not masked by the script; leave it out of blinded runs.
Report all three next to buy-and-hold. LUCK or BETA_OR_STYLE is a valid, honest result (rule 8).

## Point-in-time and leakage checklist
Read before trusting any historical result, and before any result that uses news, fundamentals or an LLM's judgement.
1. **News timestamps to the minute.** Join each headline at the minute it was published and trade at the next bar's open. A headline published after the close is not tradable at that close (rta-bench-1 design, jackson-cmd/risk-aware-trading-agents, MIT).
2. **Model memory.** An LLM may remember what happened after its training data. Run the period blind (tickers and dates masked, references/committee.md) and score periods before and after the model's training cutoff separately. A result that only works before the cutoff is memory, not skill.
3. **Seeds.** One LLM-agent run is an anecdote: the rta-bench-1 paper found two runs differing only by seed ended 5.2 points apart on average. Use at least 3 seeds and report the spread.
4. **Beta, not alpha.** Report return minus the benchmark's and the regression beta; most LLM agents in that study earned market beta.
5. **Survivorship.** The universe is what existed on each date, delisted names included.
6. **Restatements.** Fundamentals as first filed, not as later restated (SEC EDGAR filing dates; SEDAR+ in Canada).
7. **Corporate actions.** Split- and dividend-adjusted prices for returns, unadjusted for any price-level rule.
8. **Fills.** Next-bar entry, spread plus fees plus slippage, and size capped by recent volume.
9. **Two-sided filters.** The Hodrick-Prescott filter, centred moving averages, Savitzky-Golay, wavelet or Fourier smoothing, and min/max or z-score scaling all use future bars when run over the whole history, which makes a backtest look far better than it is. Refit on a trailing window at every bar and keep only its last point; take scaling statistics from the training window only. `lookahead_check.py` catches the whole-history version (it is in evals/run_tests.py as a test case). The end point of a trailing HP filter is its least stable part, and that is the point you trade on.
10. **Labels with a horizon.** A target like P(t+T)/P(t) − 1 is unknown for the last T bars of a training window; drop them, and purge with `overfit.py cpcv --horizon T` for fitted models.
11. **Perpetual funding.** Any crypto perpetual position, long or short, pays or receives funding at the venue's interval (often 8 hours; some contracts settle every 1 to 4 hours, so read it from the venue). Cost per interval = position notional × funding rate; longs pay when the rate is positive, shorts when negative. Use the historical funding series from the data MCP server, report it as its own cost line next to fees, and never assume zero. Spot positions have no funding but may have borrow costs for shorts.

## Fixed-seed session replay (day-trader-skill Time Machine)
For an intraday plan: build a pool of the last 60 days of 5-min sessions as OHLC ratios to prior close, resample same-time-of-day bars (±2), stop checked before target (a bar touching both = stop), seed 19, 10,000 paths. Refuse with <20 sessions. Verdict vs break-even win rate 1/(1+R): within 5 pts "coin flip", 5–15 "leans", >15 "strongly".

## Universe (run scripts/universe.py)
- **No cross-sectional signal is judged on fewer than 100 point-in-time names, delisted included.** Ranking ten correlated ETFs is close to a coin toss, so the gates look harsh when they are really under-powered. `pipeline.py --cross-sectional` needs a `universe.py` result and stops on TOO_NARROW.
- Default universe: top 1,000 US names by 20-day average dollar volume, membership recomputed on each rebalance date from rows before it. Feed `PREFIX_members.csv` to `premia_signals.py --universe`.
- **Survivorship:** the panel must hold names that later delisted, merged or were renamed. SURVIVORSHIP_SUSPECT means none left the panel, so the source probably dropped dead names. Free price feeds often do; SEC EDGAR filings list delisted issuers and their tickers, so pull those names' history where the price tool still has it, and say plainly what is missing. Delisting returns are usually missing too (Shumway 1997); a delisted holding exits at its last close.
- The 10-ETF set in examples/ is for macro and regime illustration only.
- **Two regimes at least.** `pipeline.py` splits net returns by benchmark volatility tercile (calm, normal, stressed: a VIX-tercile proxy) or by your own `--regimes` file (for example yield-curve state from Bank of Canada Valet or FRED through an MCP tool). It must make money in at least two regimes with 126 or more days each, or be declared regime-conditional (`--regime-conditional LABEL`) and run only in that regime.

## Promotion ladder (scripts/pipeline.py)
- **NOT_READY:** a mechanical gate failed (hard gates, look-ahead LEAK, PBO, permutation, net Sharpe at or below zero at 3× costs, ANTI_EDGE, TOO_NARROW universe).
- **PAPER_PROBE:** mechanics clean, alpha unproven (deflated Sharpe under 0.95, a benchmark test failed, LUCK, BETA_OR_STYLE, one regime, or a confirming gate not run). Paper trade at a quarter of normal size to buy forward data: the only unbiased sample you will ever get. Without a probe, a skill that never promotes never learns anything. Review with `strategy_health.py` after 63 trading days, then re-run the pipeline on backtest plus paper.
- **READY_FOR_PAPER:** every gate ran and passed, including the look-ahead and permutation results passed in.
- Live money is always the user's call, in trading-execution, after paper.

## Positive controls (evals/benchmark_suite.md)
The gates are checked against strategies with known answers: noise must fail, a strong premium at 3× costs must pass, a leak must be caught, a SPY clone must read BETA_OR_STYLE, and a market-neutral Sharpe 1.6 sleeve must pass without beating SPY. If any lands wrong, the gates are miscalibrated; fix them before trusting a verdict. `evals/run_tests.py` runs the suite.
