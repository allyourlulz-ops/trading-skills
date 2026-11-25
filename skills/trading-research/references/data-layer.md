# Data layer

## Fetch discipline
1. Resolve the instrument (search) → fetch by returned id/symbol. Confirm exchange, currency, and unit.
2. State as-of time with timezone for every number. Mark anything older than 1 year as possibly stale.
3. Request exact dates (e.g. yfinance `keepna=True`) and check that the requested date exists; distinguish "no data", "instrument doesn't exist", "market closed that day".
4. On an error keep the error text and whatever was already fetched; never fill gaps.
5. Before quoting an exact price/indicator, take one verified snapshot (latest quote + latest bar) and treat it as source of truth for the report.
6. Live news/social reflects *now*, even when analysing a past date. Don't use it in historical runs.
7. **Write the data contract** (`scripts/data_contract.py`) for every price behind a size or a backtest: source tool, as-of and last bar end in ISO 8601 with offset, timeframe, adjustment and currency. Adjustment policy: quotes, stops and signals used for sizing are `raw` or `split` (orders fill in raw prices; dividend-adjusted history moves the stop); backtest returns are `split_div`. No provider default is assumed: the OpenBB yfinance provider and Alpaca bars both take an adjustment argument, so pass it and record it. Alpaca's free feed is IEX only; say `feed: iex` in the source. A stale, unaligned, future-dated or offset-less series fails the gate.

## OpenBB Python equivalents
```python
from openbb import obb
obb.equity.price.historical("AAPL", provider="yfinance", start_date="2025-01-01").to_dataframe()
obb.equity.fundamental.ratios("AAPL")
obb.equity.estimates.price_target("AAPL")
obb.technical.rsi(data=df, length=14)
obb.economy.cpi(country="united_states")
```
Common MCP tools: `equity_price_historical`, `equity_price_performance`, `equity_fundamental_ratios`, `equity_fundamental_metrics`, `equity_fundamental_balance`, `equity_estimates_price_target`, `equity_compare_peers`, `news_company`, `technical_rsi`, `technical_macd`, `derivatives_options_strikes`, `economy_cpi`.

Example pipeline:
```json
{"steps":[
 {"id":"prices","tool":"equity_price_historical","arguments":{"symbol":"AAPL","provider":"yfinance","start_date":"2025-01-01"}},
 {"id":"rsi","tool":"technical_rsi","arguments":{"length":14},"inputs":{"data":"prices"}},
 {"id":"macd","tool":"technical_macd","inputs":{"data":"prices"}}],
 "outputs":["rsi","macd"]}
```

## Polars for large bar sets
Use polars (MIT) instead of pandas for tick or multi-year minute data: lazy scans (`pl.scan_parquet`) and `group_by_dynamic` for resampling. Convert to pandas only at the edge for libraries that need it.

## Solana on-chain reads
`solders` (Apache-2.0) gives typed Solana primitives for RPC reads: mint and freeze authority on a token mint, holder accounts, LP token supply. Jupiter's quote API gives swap routes and price impact. See references/onchain-memecoin.md for what to check.

## Alpaca data tools
`get_stock_snapshot`, `get_stock_bars`, `get_stock_latest_quote`, `get_most_active_stocks`, `get_market_movers`, `get_option_chain`, `get_option_snapshot` (Greeks/IV), `get_crypto_bars`, `get_crypto_latest_orderbook`, `get_news`, `get_corporate_actions`, `get_clock`, `get_calendar`. Real-time SIP data needs Alpaca's paid plan; free data may be IEX-only/delayed. Say which.

## Fundamentals
- SEC EDGAR (keyless; set `SEC_EDGAR_USER_AGENT="Name email"`): XBRL company facts, 8-Ks, Form 4. Use as-filed values for historical work.
- Congressional PTRs (House Clerk) can lag a trade by up to 45 days; treat as stale signals.

## Ticker suffixes (Yahoo convention)
`.TO` Toronto, `.V` TSX-V, `.L` London, `.HK` Hong Kong, `.T` Tokyo, `.NS` NSE India, `.SS`/`.SZ` Shanghai/Shenzhen, `.KS` Korea, `.TW` Taiwan, `BTC-USD` crypto.

## Live data pipeline (scripts/pit_store.py)
For bots and anything that runs more than once a day, keep one local point-in-time store instead of re-asking the model for prices:
1. `pit_store.py route --routes ../assets/data-routes.json --asset equity_us --state state.json` lists the asset's MCP sources in priority order, skipping any in cooldown. Edit assets/data-routes.json to the servers you installed.
2. Fetch from the first source with its MCP tool. On a 429, 5xx, timeout or auth error run `pit_store.py fail --source X --code 429` (429 cools 15 min, 5xx 2 min, doubling on repeats, cap 60 min), report it per source, and try the next one. `ok` resets a source after a good call.
3. Write the rows to a file and `pit_store.py ingest --store merged.jsonl --source X --timeframe 1d --file rows.json --routes ... --asset ...`. Symbols are normalised, a bar is closed only once its close time has passed, closed bars beat forming ones, the higher-priority source wins ties, and a close that differs by more than 0.5% between sources is kept as a conflict (`pit_store.py conflicts`) to show both, never to average.
4. Read with `pit_store.py asof --symbol X --timeframe 1d --at <decision time> --bar-out bar.json`. Only closed bars that finished on or before the decision time come back; pass `bar.json` to `risk_check.py --bar`.
Every row keeps its source and fetch time, so a quote can always be cited (rule 1). Routing, fallback, cooldown and the anti-look-ahead read are ideas from HKUDS/AI-Trader (no licence file, so no code used); its direct Alpha Vantage, yfinance and Hyperliquid pulls are replaced by your MCP servers, which keeps this skill MCP-only.

