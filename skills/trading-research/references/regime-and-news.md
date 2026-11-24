# Regime playbook, verified news and benchmark lessons (distilled 2026-11-24)
Read for `analyse`, `screen`, `portfolio` and every `bot` mandate. Ideas from the top performers on two public benchmarks; all code here is our own.

## Where the ideas come from
- **rta-bench-1** (jackson-cmd/risk-aware-trading-agents, MIT, v0.8.0). Its best LLM after training cutoff, Claude Haiku 4.5, made +7.2% in 2026 against SPY's +12.1%. LLMs trading alone earned beta, not alpha. The best performer in the same project was its rule-based `risk_aware` agent: 2026-01-02 to 2026-11-11 with news, +15.9% against SPY's +12.1%, Sharpe 1.70 against 0.77, max drawdown -5.3% against -8.9%. Over 2018 to 2026 it trailed SPY (10.4% a year against 14.1%) but fell about half as far (-18.2% against -33.7%). Figures as published by the project; survivorship-biased large-cap list.
- **FinSkillBench** (arXiv 2610.03564, Oct 2026). Curated skills raised scores from 0.366 to 0.528; skills an agent wrote for itself added 0.005. Executable tools alone added 0.195, documents alone 0.056, and stacking long documents on tools cost turns.

## 1. Regime first (run scripts/regime.py)
| Regime | Trigger | Buys | Discretionary sells | Size |
|---|---|---|---|---|
| risk_on | SPY above a rising EMA50 and EMA200, VIX < 20, most sectors above EMA200 | pullbacks, breakouts, quality dips | take profit, trend exits | 100% |
| neutral | none of the others | EMA support, mean reversion, quality dips | take profit | 75% |
| uncertain | FOMC within 2 days, CPI or jobs report tomorrow, VIX 20-30, fear gauge < 35, SPY below a falling EMA50 | EMA100/EMA200 support only | none: hold | 50% |
| risk_off | VIX >= 30, VIX above VIX3M with SPY below EMA200, or credit stress (HYG lagging IEF) | quality dips, broad ETFs, small tranches | none: hold | 35% |

The size column multiplies the size from position_size.py; risk clamps may only shrink it. Inputs come from the data MCP server with as-of times; the macro calendar comes from official release schedules.

## 2. Standing book rules (bots and portfolio mode)
- Cash floor: cash plus a T-bill ETF never below 30% of equity. This is why the agent lagged SPY in bull years and fell half as far in crashes; tell the user that trade-off before they sign a mandate.
- Tranches: build each position 50% / 25% / 25%. A later tranche needs a deeper support touch or a winning position.
- Quality gate for dip buys: revenue growth, margins, free cash flow, leverage and EPS beats from as-filed data. No gate pass, no dip buy.
- No panic selling: in uncertain or risk_off regimes, hold. Forced exits only on a red flag the company itself confirms (its own 8-K or press release) or the mandate's hard stop.
- Kill switch and halt: the HALT file in mandate mode.

## 3. Verified news
- A story counts only for the company it names.
- Confirmed = two independent outlets, or the company's own press release or SEC filing. One news API is one source.
- A red flag on a confirmed story blocks new buys. Only the company's own filing, or its release confirming what independent outlets reported first, can force a sale.
- A denial clears the story it refutes.
- In backtests a headline exists from the minute it was published; orders fill at the next open.
- In that project's 2026 test, a sentiment filter made five standard swing strategies slightly worse. News is a veto and a risk flag here, not an entry signal, unless rule_screen.py and permutation_test.py say otherwise.

## 4. The LLM's role in a bot
- The model proposes a view; code sizes it. In mandate mode the model may move conviction by at most ±0.15, or veto a buy. It cannot create a trade, add a symbol or change a limit.
- Every prompt and reply goes in the journal with the decision it touched.

## 5. Testing any strategy (scripts/lookahead_check.py)
- Run `lookahead_check.py --prices closes.csv --cmd "python3 strat.py --prices {prices}"`. It replaces every bar after several cut dates with a random path and checks that no decision on or before a cut changes. LEAK blocks promotion.
- Strategy code must not hard-code dates or tickers (both leak the future), read files other than its inputs, or touch the network.
- Score LLM-driven strategies only on periods after the model's training cutoff, with at least 3 seeds, against SPY and equal weight.

## 6. Skill-design lessons applied here (FinSkillBench)
- Numbers go through scripts, not through the model. Pass file paths and let the script read full-precision inputs; a matrix retyped by a model changes the answer.
- Compliance is checked against the signed mandate file itself (`mandate.py check` reads assets/mandate.json), never against the agent's own restatement. In the benchmark's nine-stage desk test, an agent that parsed a mandate into its own words built near-optimal books that broke the mandate 33 times out of 33 while every internal check reported success.
- Keep reference files short and load only the one the task needs; extra reading competes with doing.
