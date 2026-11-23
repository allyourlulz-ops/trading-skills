# MCP servers

Prefer the smallest toolset that answers the request. Research mode never loads order tools.

## OpenBB (data layer, recommended default)
```bash
pip install openbb-mcp-server openbb
openbb-mcp --tool-discovery --allowed-categories equity,economy,news,crypto,etf,derivatives,technical,quantitative
# stdio for desktop clients:
uvx --from openbb-mcp-server --with openbb openbb-mcp --transport stdio --tool-discovery
```
```json
{"mcpServers":{"openbb":{"command":"uvx","args":["--from","openbb-mcp-server","--with","openbb","openbb-mcp","--transport","stdio","--tool-discovery"]}}}
```
- Default HTTP endpoint `http://127.0.0.1:8001/mcp`.
- `--tool-discovery` exposes `available_categories`, `available_tools`, `search_tools`, `call_tool` instead of hundreds of tools.
- Tool names mirror routes: `/equity/price/historical` → `equity_price_historical`.
- `run_pipeline` chains tools server-side so price rows never enter the model context.
- Provider keys: `~/.openbb_platform/user_settings.json`. Free: yfinance, sec, some fred/oecd/cboe.
- Lock down `install_skill` (it writes to server disk); use `server_auth` if clients are untrusted.
- Note: GitHub currently serves `OpenBB-finance/OpenBB` as `openbq-org/OpenBB`. Install from PyPI (`openbb`), not from a fork.

## Alpaca MCP v2 (US stocks/options/crypto data + paper/live execution)
Research-only (no order tools exist):
```json
{"mcpServers":{"alpaca":{"command":"uvx","args":["alpaca-mcp-server"],
 "env":{"ALPACA_API_KEY":"…","ALPACA_SECRET_KEY":"…","ALPACA_PAPER_TRADE":"true",
        "ALPACA_TOOLSETS":"account,assets,stock-data,crypto-data,options-data,news,corporate-actions"}}}}
```
Execute mode adds `trading` to `ALPACA_TOOLSETS`; keep `ALPACA_PAPER_TRADE=true` unless the user switches it themselves.
- Claude Code: `claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server --env ALPACA_API_KEY=… --env ALPACA_SECRET_KEY=…`
- Toolsets: account, trading, watchlists, assets, stock-data, crypto-data, options-data, corporate-actions, news, fixed-income-data, locates.
- v1 tools do not exist in v2; pin `alpaca-mcp-server==1.x.x` only for legacy scripts.
- No server-side confirmation and no MCP OAuth: bind to localhost, never expose publicly. Approval relies on client permissions (references/risk-and-execution.md).

## SEC EDGAR MCP (filings, XBRL financials, insider Forms 3/4/5)
`stefanoamorelli/sec-edgar-mcp`, AGPL-3.0: run it as a separate server; nothing from it is bundled here.
```json
{"mcpServers":{"sec-edgar-mcp":{"command":"docker","args":["run","-i","--rm","-e","SEC_EDGAR_USER_AGENT=Your Name (you@example.com)","stefanoamorelli/sec-edgar-mcp:latest"]}}}
```
pip/uv installs are in its docs. Read-only.

## Prediction Markets MCP (Polymarket, Kalshi, PredictIt; read-only)
`JamesANZ/prediction-market-mcp`, MIT. Tools: `get-prediction-markets`, `gather-market-movement-evidence`.
```json
{"mcpServers":{"prediction-markets":{"command":"npx","args":["-y","prediction-markets-mcp"]}}}
```

## Vibe-Trading (backtests, factor zoo, 89 skills)
```bash
pip install vibe-trading-ai && vibe-trading init
```
```json
{"mcpServers":{"vibe-trading":{"command":"vibe-trading-mcp"}}}
```
Call `list_skills` first. Tools include `get_market_data`, `backtest`, `factor_analysis`, `portfolio_risk_xray`, `options_strategy_compare`, `technical_indicators`, `get_financial_statements`, `quantlib_call`. Its live broker connectors are experimental; don't enable them from this skill.

## QuantDinger (self-hosted; heavy stack)
`pip install "quantdinger-mcp==0.6.2"`, env `QUANTDINGER_BASE_URL`, `QUANTDINGER_AGENT_TOKEN=qd_agent_…`, run `quantdinger-mcp`. 58 tools (`search_symbols`, `get_klines`, `compile_strategy_code`, `submit_backtest`, `submit_factor_benchmark`, `wait_for_job`, `place_quick_order`, `emergency_stop_trading`). Use R/B-scoped tokens only; every write needs an `idempotency_key`; poll jobs with bounded `wait_for_job`.

## daily_stock_analysis (multi-market daily dashboard)
`python -m src.mcp_server` from a configured checkout (read-only). Agent tools: `get_daily_history`, `analyze_trend`, `get_realtime_quote`, `get_sector_rankings`, `search_stock_news`, `get_stock_info`. Always pass `notify: false` / `send_notification: false`.

## tick-stock-panel (China A-shares)
`tsp-mcp-server` with `TSP_BASE`, `TSP_TOKEN`, `TSP_SCOPES` (read:market, read:analysis, run:backtest). Tools: `search_instrument`, `get_kline`, `list_strategies`, `run_backtest`. A-share rules (T+1, price limits) are modelled.

## Not usable without special access
- gs-quant: needs a Goldman Sachs institutional client id/secret. Its packaged skills (`python -m gs_quant.skills install --global`) are a good layout model only.
