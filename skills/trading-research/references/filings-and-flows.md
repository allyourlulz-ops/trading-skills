# Filings and flows (research only)

Watch what insiders, funds, politicians and the SEC record, not what people post. Facts only; every item carries its filing URL and filed date.

## Sources (all through MCP servers)
- **SEC EDGAR MCP** (`stefanoamorelli/sec-edgar-mcp`, AGPL-3.0, run as its own server, not bundled): CIK lookup, 10-K/10-Q/8-K retrieval and section extraction, XBRL financials, Form 3/4/5 insider transactions; every response includes the SEC URL. Config in mcp-servers.md. SEC requires a User-Agent with a name and email.
- **OpenBB** `sec` provider (free): filings lists, insider trading, 13F institutional holdings, failures-to-deliver. Use `search_tools("insider")`, `search_tools("13f")`, `search_tools("ftd")` with `--tool-discovery` rather than guessing route names.
- **Congressional trades (STOCK Act):** no free first-party MCP server was verified. Use the House and Senate disclosure sites through a browser or fetch tool if the client has one, and treat third-party trackers as unverified. Disclosures can lag the trade by up to 45 days.

## Nightly watchlist routine
1. For each watchlist ticker, list filings since the last run: 8-K (item numbers), 10-Q/10-K, S-1/S-3/424B (dilution), SC 13D/13G (5%+ holders), Form 4.
2. Form 4: keep open-market purchases (code P) and sales (S); ignore grants (A), option exercises (M) and tax withholding (F). Flag cluster buys (3+ insiders within 30 days) and any officer/director buy of $1M+.
3. 13F (quarterly, 45 days late): report new positions, exits and changes over 25% for funds the user names. Never present 13F as current positioning.
4. Short interest and FTDs: short interest lags about two weeks; FTD spikes are a settlement fact, not proof of manipulation.
5. Output: one line per item (date, ticker, form, what changed, URL). Quiet when nothing is new; say "no new filings" in one line.

## Rules
- A filing is a fact; what it means is a view and goes through the committee.
- Insider selling is weak evidence (taxes, diversification). Clustered open-market buying is the stronger signal, still not a trade by itself.
- Pass dated catalysts (earnings, 8-K events, lockup expiries) into risk_check `--context`.
