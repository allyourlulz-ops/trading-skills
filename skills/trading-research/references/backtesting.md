# Backtesting

## Choose an engine
| Need | Engine |
|---|---|
| Multi-market, quick, agent-written | Vibe-Trading `backtest` (MCP) with the SignalEngine contract |
| Crypto, rigorous, optimisation | freqtrade CLI (GPL-3.0; call as a tool, don't embed code) |
| US equity, event-driven, teaching | zipline-reloaded (original quantopian/zipline is dead) |
| China A-shares (T+1, limits) | tick-stock-panel `run_backtest` |
| Factors / overfitting stats | QuantDinger `submit_factor_benchmark` or Vibe-Trading `alpha bench` |

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

## Validation (run scripts/validate_backtest.py)
Report all of:
- CAGR, Sharpe, Sortino, max drawdown + duration, win rate, profit factor, expectancy, trade count.
- Buy-and-hold over the same window ("market change") and the delta.
- Mean-trade t-test p-value (optimistic: trades aren't i.i.d.).
- Bootstrap 95% CI of Sharpe.
- Deflated Sharpe ratio given the number of variants tried (multiple testing).
- Walk-forward (≥5 windows) and a final out-of-sample holdout with frozen parameters.
- Costs: spread bps, commission, square-root impact `k·σ_daily·sqrt(order/ADV)`.
- Reproducibility log: strategy version/hash, symbols, dates, price basis (adjusted?), costs, seed, data snapshot.
State plainly: "Backtests overstate live results."

## Fixed-seed session replay (day-trader-skill Time Machine)
For an intraday plan: build a pool of the last 60 days of 5-min sessions as OHLC ratios to prior close, resample same-time-of-day bars (±2), stop checked before target (a bar touching both = stop), seed 19, 10,000 paths. Refuse with <20 sessions. Verdict vs break-even win rate 1/(1+R): within 5 pts "coin flip", 5–15 "leans", >15 "strongly".
