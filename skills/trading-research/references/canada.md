# Canada: markets, accounts, tax and rules

Use when the user trades on the TSX, TSX Venture or CSE, holds CAD, or uses a Canadian broker or registered account. Same gates as everywhere else; Canada changes the data, the accounts and the tax.

## Data (MCP-first)
- **OpenBB + `openbb-tmx`** (`pip install openbb-tmx`, no key; unofficial TMX connector): `obb.tmx.equity.historical/quote/search/screener`, `obb.tmx.etf.search` (Canadian ETFs and holdings for look-through), `obb.tmx.index.available` (S&P/TSX indices), `obb.tmx.equity.rankings` (TSX30, Venture 50), `obb.tmx.markets.trades` (time and sales with broker numbers). Look symbols up with the provider's search first; conventions differ (RY on TMX, RY.TO on Yahoo, RY:CA elsewhere).
- **Questrade MCP** (official, hosted): `claude mcp add --transport http questrade https://mcp.questrade.com/v1/brokerage/mcp`, then sign in. Accounts, balances, positions, quotes, option chains, history. 33 tools per Questrade's technical reference (checked 2026-11-24). Order tools (`create_order_instruction`, `create_option_instruction`) only create an instruction that waits for the user's Push Approval in the Questrade app, and Flows run in MANUAL_APPROVAL only, so a mandate cannot auto-trade there: the phone approval is the per-order yes. Order entry is closed 2:00 to 3:45 AM ET daily.
- **Interactive Brokers Canada** (official AI connector, `api.ibkr.com/v1/api/mcp`; 10 tools as listed in Claude's connector directory, checked 2026-11-24, none submits an order): portfolio, research and draft trade instructions; the user submits each one in an IBKR platform. Opt-in Autonomous Trading (2026-10-21) can submit inside a funded AI Partition; see trading-execution. Community IB MCP servers (e.g. `ib-mcp`, read-only) need a local TWS/IB Gateway.
- **Wealthsimple:** no account-access MCP server was found; treat as manual.
- **Filings:** SEDAR+ (sedarplus.ca) for prospectuses, MD&A, material change reports, annual information forms; SEDI (sedi.ca) for insider trades, filed within 5 calendar days. No MCP server found for either: read them with the client's fetch tool and cite the filing.
- **Macro:** Bank of Canada Valet API (no key) for the policy rate, CORRA and daily FX, e.g. `https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=5`; FRED (OpenBB `fred`) carries mirrors such as DEXCAUS. Statistics Canada for CPI and jobs (Labour Force Survey, usually the first Friday of the month).

## Market structure
- TSX and TSXV trade 9:30 to 16:00 ET, the same hours as US markets, with their own holidays (Family Day, Victoria Day, Canada Day, Civic Holiday in some years, Thanksgiving in October, Boxing Day). Check the TMX calendar before a scheduled run.
- Many large caps are interlisted (RY, TD, ENB, SHOP, CNQ). Compare the TSX and US lines in one currency before calling one cheap.
- TSXV and CSE names are small and thin: apply the ADV cap and spread checks strictly, and treat promotional news as a risk flag.
- Settlement is T+1, as in the US.

## Regulators and rules
- **CIRO** (Canadian Investment Regulatory Organization) regulates dealers and trading; **CIPF** covers client assets at member firms if a dealer fails (not market losses). Provincial securities commissions (OSC, BCSC, AMF and others) handle registration and enforcement.
- There is no US-style pattern-day-trader $25k rule; margin and short rules come from CIRO and the broker.
- Options on Canadian names trade on the Montréal Exchange; US options need US options approval at the broker.
- Polymarket and Kalshi access from Canada is restricted or unavailable in places (Ontario especially); check the user's province before any prediction-market step.

## Accounts and what they change
| Account | Gains taxed? | Notes for the skill |
|---|---|---|
| Taxable (cash/margin) | Yes, capital gains | Track ACB in CAD with `scripts/ca_tax_check.py` |
| TFSA | No | No loss deductions; frequent trading can be ruled business income; US dividends lose 15% withholding |
| RRSP / RRIF | Deferred | US-listed shares held directly are exempt from US dividend withholding under the treaty |
| FHSA | No (for a qualifying home) | Same affiliated-person rules as TFSA for superficial losses |
| RESP | Deferred | Not affiliated for superficial losses |
Contribution room is the user's own data; ask, never guess. Over-contributing to a TFSA costs 1% per month on the excess.

## Tax
- **ACB:** average cost per share in CAD across all of one person's taxable accounts, commissions in cost and out of proceeds, each USD trade at that day's Bank of Canada rate. `ca_tax_check.py` does it and lists year-end ACB per symbol.
- **Superficial loss:** selling at a loss and you or an affiliated person (spouse, a corporation either controls, your or their TFSA/RRSP/RRIF/FHSA) buys identical property within 30 days before or after, still holding it on day 30. The loss is denied and added to the rebuy's ACB, or lost outright when the rebuy is in a registered plan. Tax-loss harvesting therefore swaps into a similar but not identical holding (a different index, not the same fund in another account) and waits 31 days.
- **Tax-loss selling season:** the last trade date that settles in the calendar year (T+1) is in the last days of December; check the exact date each year.
- Capital gains go on Schedule 3; the inclusion rate is whatever applies for that tax year. Keep records 6 years. Not tax advice: hand the output to the user's accountant.

## Currency
- Every amount is a pair: value and currency. `rebalance.py` refuses mixed currencies unless `--base CAD --fx USD=<rate>` is given. Label every reported number with its currency.
- Converting CAD to USD at a broker usually costs 1.5 to 2.5%. Norbert's gambit (buy DLR.TO in CAD, journal to DLR.U.TO, sell in USD) is cheaper for larger amounts; it takes a few days and the broker has to journal the shares.
- `scripts/interlisted.py` does the arithmetic. `norbert` compares the gambit's effective USD/CAD against the broker's quoted rate (whole units, both commissions, journal fee). `buy` says which listing of an interlisted stock (RY, TD, ENB, SHOP, CNQ...) gets more shares for a CAD amount once FX is paid. `pair` prices the TSX line off the US line and checks whether the gap clears spreads, FX and commissions at executable quotes.
- Interlisted gaps are usually a few bps and closed by dealers within seconds. `pair` refuses quotes more than 5 s apart or outside both sessions. A Bank of Canada Valet rate is a daily reference, so `pair` calls any gap built on it INDICATIVE. The sell leg needs shares you already hold; never short to make it work. Treat `pair` as a cost check, not a strategy.
- Canadian-listed ETFs holding US stocks (e.g. XUS, VFV) avoid conversion but keep a layer of US withholding; US-listed ETFs in an RRSP avoid it.

## Canadian versions of the routines
- **Pre-market brief:** add S&P/TSX 60 futures (SXF), WTI and gold (heavy TSX weights in energy and materials), USD/CAD, and Bank of Canada or StatCan releases that day.
- **Filings watch:** SEDI insider buys (cluster buys still the signal), SEDAR+ material change reports, and Canadian bank earnings (late Feb, May, Aug, Nov/Dec).
- **Crash guard:** use XIU.TO or the S&P/TSX Composite as `--index`; stress-test against the TSX in 2008 and 2020 when the data MCP server returns it.
- **Rebalance:** look through all-in-one ETFs (XEQT, VEQT, XBAL, VBAL) to see true Canada / US / international weights.
