# Idea sourcing (optional, off by default)

Use only when the user asks for leads from disclosures or screens. Output is a list of research leads with filing URLs and dates, never a trade, a size or an order. Every lead then goes through `analyse` (should-i) and, if it gets that far, the full backtest gate.

Design studied from Jakeschincariol/trader-skill (MIT): free public sources, a SEC User-Agent, one alert per filing, flags for holdings the user already owns. No code is copied, and this skill reads the sources through MCP servers rather than its scripts.

| Lead | Source (through an MCP server or the user's client) | Fields to keep | Catch |
|---|---|---|---|
| House member trades | House Clerk periodic transaction reports (yearly index, then each PTR) | member, owner (self, spouse, joint, dependent), ticker, buy or sell, option strike and expiry, trade date, amount range, days to disclose | Up to 45 days late by rule; amounts are ranges; a late filing is old news |
| Senate trades | efdsearch.senate.gov (manual, behind a terms page) | same as above | Not machine-friendly; quote the page |
| Fund holdings | SEC 13F-HR through `sec-edgar-mcp` | filer, CUSIP, ticker, weight, period end, filed date | 45 days after quarter end; long US equity only; no shorts |
| Insider buys and sells | Form 4 through `sec-edgar-mcp` | insider, role, transaction code (P = open-market buy), shares, price, filed time | Codes other than P and S are mostly not signals (grants, exercises, tax) |
| Fundamental screens | SEC XBRL company facts through `sec-edgar-mcp` or OpenBB | as-filed values with their filed dates | Restated values leak the future; use as-filed |

Rules
- Off until asked. Nothing here runs on a schedule unless the user sets one.
- Each lead carries its filing URL and filed date; the trade date is not when the market learned it.
- A lead is a reason to research, not to buy. Disclosure-copying has no documented post-cost edge here (references/documented-edges.md lists none), so say that with any lead.
