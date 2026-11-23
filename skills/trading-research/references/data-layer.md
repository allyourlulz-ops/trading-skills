# Data layer

## Fetch discipline
1. Resolve the instrument (search) → fetch by returned id/symbol. Confirm exchange, currency, and unit.
2. State as-of time with timezone for every number. Mark anything older than 1 year as possibly stale.
3. Request exact dates (e.g. yfinance `keepna=True`) and check that the requested date exists; distinguish "no data", "instrument doesn't exist", "market closed that day".
4. On an error keep the error text and whatever was already fetched; never fill gaps.
5. Before quoting an exact price/indicator, take one verified snapshot (latest quote + latest bar) and treat it as source of truth for the report.
6. Live news/social reflects *now*, even when analysing a past date. Don't use it in historical runs.

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

## Alpaca data tools
`get_stock_snapshot`, `get_stock_bars`, `get_stock_latest_quote`, `get_most_active_stocks`, `get_market_movers`, `get_option_chain`, `get_option_snapshot` (Greeks/IV), `get_crypto_bars`, `get_crypto_latest_orderbook`, `get_news`, `get_corporate_actions`, `get_clock`, `get_calendar`. Real-time SIP data needs Alpaca's paid plan; free data may be IEX-only/delayed. Say which.

## Fundamentals
- SEC EDGAR (keyless; set `SEC_EDGAR_USER_AGENT="Name email"`): XBRL company facts, 8-Ks, Form 4. Use as-filed values for historical work.
- Congressional PTRs (House Clerk) can lag a trade by up to 45 days; treat as stale signals.

## Ticker suffixes (Yahoo convention)
`.TO` Toronto, `.V` TSX-V, `.L` London, `.HK` Hong Kong, `.T` Tokyo, `.NS` NSE India, `.SS`/`.SZ` Shanghai/Shenzhen, `.KS` Korea, `.TW` Taiwan, `BTC-USD` crypto.
