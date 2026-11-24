# Research committee
Adapted from TradingAgents (Apache-2.0, TauricResearch), ai-hedge-fund (MIT, virattt), Vibe-Trading investment_committee (MIT, HKUDS), aurelio-finance (MIT).

## Pipeline
```
snapshot → [technical | fundamentals | news-macro | sentiment] (parallel)
        → bull ⇄ bear (1–2 rounds) → research manager (plan)
        → trader (proposal) → aggressive ⇄ neutral ⇄ conservative (1 round)
        → portfolio manager (final rating) → log for settlement
```
Use a fast model for analysts/debaters/trader and the strongest model for the two managers.

## Analyst prompts (condensed)
**Technical.** Call the verified snapshot first. Choose ≤8 complementary, non-redundant indicators from: close_50_sma, close_200_sma, close_10_ema, macd, macds, macdh, rsi, boll, boll_ub, boll_lb, atr, vwma (not both rsi and stochrsi). Report trend, dated support/resistance, ATR, volume confirmation. Never claim a bounce without dated prices.

**Fundamentals.** As-filed figures (EDGAR first). Revenue/EPS growth, margins, FCF, balance sheet, valuation vs history and peers. Date every figure.

**News/macro.** Company news last 7–14 days, earnings date, guidance, plus macro (rates, inflation, sector). Each catalyst with a date.

**Sentiment.** StockTwits/Reddit/X/Polymarket via references/sentiment.md. Per-source status. Sentiment is a noisy contrarian-capable signal, never decisive alone.

## Researchers
Bull: strongest evidence-based case, quantified upside, catalyst calendar (next 1–3 months), target from three angles (multiple, DCF-lite, technical), and the main risk to the bull case.
Bear: the mirror; must directly rebut the bull's numbers.

## Research manager (judge)
"Conflict alone is not a reason to Hold. Commit to the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced. Weigh the arguments on their merits, independent of speaking order." Output an investment plan with thesis, evidence, invalidation.

## Trader
`{action: Buy|Hold|Sell, reasoning, entry_price, stop_loss, target, position_sizing_note}`. Entry/stop are absolute prices grounded in ATR and dated levels, never percentages.

## Risk debate
Aggressive (upside capture), conservative (capital preservation, tail risk, liquidity), neutral (balance). Each must reference the trader's exact numbers.

## Portfolio manager
Output first line `Rating: <Buy|Overweight|Hold|Underweight|Sell>`, then conviction, confidence, horizon, rationale, and "Lessons from prior decisions" applied. If output can't be parsed → `REVIEW`.

## Portfolio context
Pass the real book: `{cash, currency, positions:[{ticker, quantity, average_price}]}`. An empty positions list means flat; no portfolio means unknown. Consider concentration, correlation, and existing exposure before rating.

## Investor personas (optional analyst layer)
Each persona returns strict JSON `{"signal":"bullish|bearish|neutral","confidence":0-100,"reasoning":"..."}` with the rule: "Reason ONLY from the data provided. Treat the most recent filing date shown as the present day. Do not invent numbers. If the data is insufficient, go neutral."
Confidence rubric: 90–100 exceptional, 70–89 solid, 40–69 mixed, 10–39 weak.
- **Buffett** (long-only, ~252d): circle of competence, durable moat, management, financial strength, margin of safety, long-term prospects.
- **Munger** (long-only): quality at fair price, inversion — what would make this fail?
- **Graham** (long-only): net-net/defensive criteria, P/E × P/B ≤ 22.5, earnings stability, dividend record.
- **Lynch** (long/short): category (stalwart, fast grower, cyclical, turnaround), PEG, story you can explain in two sentences.
- **Druckenmiller** (long/short, ~126d): rate of change and inflection, what's priced in, liquidity/macro, asymmetric setups.
- **PEAD quant**: post-earnings drift after 8-K results, 4-day window, 60-day horizon.
If a persona's call fails, it **abstains** (no vote); never default to neutral silently. Blend by conviction × weight; long-only bearish views reduce exposure but can't create shorts.

## Blind mode (historical tests)
Withhold ticker, company name, industry, dates and dollar values; express size as a market-cap percentile. Stops the model "remembering" the future.

## Bias checklist before concluding (Vibe-Trading research-discipline)
- Leader bias: did you look at small/mid caps and suppliers?
- Language bias: for JP/KR/TW/CN names, check local-language sources.
- Narrative bias: read the financials, not the theme label.
- Confirmation bias: cite ≥1 disconfirming data point (Munger inversion).
- Recency bias: date every number; flag >1 year old.

## Advice safety (aurelio-finance)
Recommendations appear only as structured items with `reason`, `based_on`, `unknowns`, max 3 per answer. Sizing comes from code, within the user's investable cash after an emergency reserve (default 6 months of essential expenses if the user gives none). Upgrade conviction only with 2+ independent confirming sources.

## Extra analyst seats (optional)
- **Filings seat:** new 8-K/10-Q/Form 4/13D facts since the last call (filings-and-flows.md).
- **Alt-data seat:** spending, app/web traffic, hiring and pricing signals vs peers, each with its source and lag; label proxies as proxies.
- **KPI data room:** 5-year / 20-quarter financials with a link to each source document, as filed.
- **Devil's advocate:** writes the case against first, then a one-line verdict; mandatory before any execute step.

## From views to a portfolio (scripts/black_litterman.py)
When the committee rates several names, don't size each in isolation. Write each rating as a view (`{"ticker":…,"conviction":-1..1,"confidence":0-100}`, or `{"long":…,"short":…}` for a pair; several analysts may view the same name) and run Black-Litterman: it starts from the market-implied returns, moves toward each view in proportion to its confidence, and returns target weights (`--long-only`, `--max-weight`). Abstaining personas send no view. A view the committee is unsure of barely moves the result, by design. Target weights then go through position_size.py and risk_check.py per order. Prices come from the data MCP server; the script itself makes no network calls.

**Dollar-neutral book (`--neutral --ridge 1e-4`).** For a long/short basket that should earn on the gaps between names, not on the market: max-Sharpe weights subject to Σw = 0, w ∝ C⁻¹E − C⁻¹1·(1ᵀC⁻¹E)/(1ᵀC⁻¹1), scaled to Σ|w| = 1 (Kakushadze & Serur, *151 Trading Strategies*, 2018, section 3.18; own code). E is the Black-Litterman posterior, so views still drive it. The ridge steadies the inverse when names move together. `--max-weight` scales the whole book down rather than clipping one name, so the book stays neutral. Needs shorting (allow_short in risk-limits.json, borrow or perp funding as a cost). Check: net exposure ≈ 0 in the output, beta to the benchmark near zero in the backtest, and daily turnover after fees. In a crash correlations go to 1 and the spread can vanish. Pick the universe as it stood on each date; today's top 10 coins is survivorship bias.

