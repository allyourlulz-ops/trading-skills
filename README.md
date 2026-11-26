# trading-skills

Two agent skills (skills.sh / Agent Skills format) for evidence-first trading research over MCP, built so an agent cannot plausibly talk itself into a bad trade. `trading-research` analyses, sizes and validates; it has no order tools. `trading-execution` (optional) places paper or live orders behind a nonce-enforced risk gate and your approval. Target markets: US and Canadian stocks and ETFs, spot crypto. Execution broker: Alpaca (paper by default); Questrade and IBKR draft orders you approve in their own apps.

Current version: trading-research 2.1.0, trading-execution 2.1.0. No strategy here is shown to have an edge. These are tools for finding out honestly.

## Install
```bash
npx skills add allyourlulz-ops/trading-skills --skill trading-research    # research, sizing and validation, no order tools
npx skills add allyourlulz-ops/trading-skills --skill trading-execution   # optional: paper/live orders behind the gate
```
MCP servers (you run these; the agent never installs anything): the pinned configs are `skills/trading-research/assets/mcp-config.research.json` and `skills/trading-execution/assets/mcp-config.paper-execute.json`. Versions and hashes are in each skill's `assets/mcp-lock.json`, full hashed dependency locks in `assets/locks/`. Check a config before use:
```bash
python3 skills/trading-execution/scripts/mcp_lock.py check-config --config <your config>
```
Scripts are stdlib Python 3.9+, no pip installs, no network calls.

## Three modes, resolved before any tool call
| You say | Mode | What happens |
|---|---|---|
| "should I buy NVDA?" | should-i | analysis and a rating; no quantity, no order tool |
| "size 2% risk on NVDA" | size-it | `position_size.py` on your broker portfolio; quantity plus the binding constraint |
| "size and place 2% risk on NVDA" | place-it | `risk_check.py` (sizing inside) → nonce → `preview.py` (mode on line 1) → your yes → order |
Anything ambiguous gets one question: "Analyse, size, or place?"

## The gate
`risk_check.py` returns `{verdict: pass|fail, reasons[], limits_used{}, sizing{}, nonce}`. The nonce is HMAC-signed, single-use, expires in 5 minutes, and binds the exact order (every field), the limits file and the mode. `preview.py` must echo it before the order tool; a fail, a reused or altered nonce, or an unclear Alpaca mode closes the gate. There is no silent resize: an order above the computed size fails with the size it would allow. Overrides need `--override "reason"` plus your exact acknowledgement sentence, work only on paper and only for soft reasons, and are logged.

Sizing handles risk per trade from the stop, gap risk beyond the stop, portfolio heat, correlation clusters, daily loss, position and order caps, buying power, contract multipliers, FX, fractional shares and 24/7 crypto, and names the constraint that binds.

`validate_backtest.py --manifest` is the backtest gate: alignment, lookahead, same-bar fills, survivorship, fees and slippage, walk-forward, deflated Sharpe at the trial count, a 1-3x cost sweep, regime breakdown and train-cutoff leakage. Any missing input fails.

## Known limitations
The full list is in `skills/trading-execution/references/known-limitations.md`. The ones that matter most:
- The gate stops skipped steps and orders edited after the check. It does not stop an agent that calls the broker's order tool directly, or one that can read the gate key. Paper keys, the client's per-call permission prompt and broker-side approval (Questrade Push Approval, IBKR's instruction tab) are the real wall.
- risk_check trusts the portfolio file the agent assembles from broker reads. Reconcile with the broker.
- The data contract checks what each series declares, not the numbers in it.
- Gap allowances (5% stocks, 3% ETFs, 10% crypto) are defaults to replace with your instruments' own history. Correlations are inputs.
- Pins were read from package indexes on 2026-11-25 and not installed here. The lock hashes were not verified with a clean install. Hosted servers can't be pinned, only their tool descriptions hashed.
- All tests are synthetic. Nothing has run against a broker in CI, and no strategy here has passed the full gate on real data.

## Provenance
| Reference (section) | Source | Licence; how used |
|---|---|---|
| committee.md: analyst pipeline, debate, PM | TauricResearch/TradingAgents; virattt/ai-hedge-fund; HKUDS/Vibe-Trading investment_committee; aurelio-finance | Apache-2.0 / MIT; adapted prompts |
| committee.md: Black-Litterman | aardisaputra/uchicago_case3 | no licence; idea only, own code |
| strategies.md | daily_stock_analysis | MIT; YAML format |
| backtesting.md: engine picker | NautilusTrader, PyBroker, vectorbt, HftBacktest, backtesting.py, zipline-reloaded, freqtrade | various; freqtrade GPL via CLI only |
| backtesting.md: SignalEngine, hard gates, scripts/engine.py design | HKUDS/Vibe-Trading | MIT; design studied, no code or dependencies |
| backtesting.md: rule screen | roan-maverick/MIT-trader-skill | method; own code |
| backtesting.md: permutation gates | @rohonchain article | method; own code |
| backtesting.md: PBO, DSR, CPCV | Bailey, Borwein, López de Prado and Zhu (2014); Bailey and López de Prado (2014) | papers |
| data-layer.md, scripts/pit_store.py | OpenBB; alpaca-mcp-server; HKUDS/AI-Trader | MCP use; AI-Trader has no licence, idea only |
| risk-and-execution.md | day-trader-skill; ai-hedge-fund; QuantDinger; finance-expert money invariants | MIT / Apache-2.0; ideas |
| regime-and-news.md | jackson-cmd/risk-aware-trading-agents; FinSkillBench; Nof1 Alpha Arena, oaia.fun | MIT; papers and public results |
| sentiment.md | mvanhorn/last30days-skill | MIT; optional, pinned commit |
| forecasting.md | Kronos | MIT |
| onchain-memecoin.md | @DN_degen article | ideas only |
| filings-and-flows.md, idea-sourcing.md | stefanoamorelli/sec-edgar-mcp; Jakeschincariol/trader-skill | AGPL-3.0 separate server; MIT design studied |
| options.md (IBKR module) | staskh/trading_skills | MIT; field list and delayed-data handling studied |
| prediction-markets.md | JamesANZ/prediction-market-mcp; Oracle3 | MIT / Apache-2.0; MCP use |
| canada.md | Questrade MCP reference; IBKR connector page; openbb-tmx; CRA T4037; yafet-a/Jane-Street-FTTP-Trading-Bot | docs; the bot has no licence, idea only |
| documented-edges.md | Frazzini, Israel and Moskowitz (2012); Novy-Marx and Velikov (2016); Hurst, Ooi and Pedersen (2017); McLean and Pontiff (2016); Chen and Velikov (2019) | cited figures |
| small-capacity-edges.md | papers listed in NOTICE (v1.17.0) | cited |
| trading-execution preview.py layout | reddygopalkrishna/trading-skills | MIT plus a trading disclaimer; layout only. Its confirmation-prompt gate was not copied |
| mcp-servers.md | each server's own repository | pinned in mcp-lock.json |

## Before each release (CI runs the same)
```bash
python3 skills/trading-research/evals/run_tests.py     # script tests, positive controls, 16 golden backtest-gate cases
python3 skills/trading-execution/evals/run_tests.py    # 62 golden cases: sizing, gate, nonce, preview, data contract, MCP lock
ruff check --select F,E9 --target-version py39 skills  # lint (CI installs ruff; shipped scripts stay stdlib)
uvx snyk-agent-scan@latest skills/trading-research/SKILL.md    # run by you
uvx snyk-agent-scan@latest skills/trading-execution/SKILL.md
```
`.github/workflows/ci.yml` runs lint, a stdlib-only import guard, both suites on Python 3.9 and 3.12, and the pinned-config check. To make it "no test, no merge", turn on branch protection for main requiring the `test` job (a repo setting).

## Disclaimer
Research and education only. Not investment advice. Paper trading by default. Backtests overstate live results, and published premia shrink after publication.

