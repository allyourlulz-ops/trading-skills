# trading-skills

An agent skill (skills.sh / Agent Skills format) for evidence-first trading research, backtesting and risk-gated execution over MCP. It distils 16 open-source trading and quant repos into one skill (see `skills/trading-research/references/repo-evaluation.md`).

## Install
```bash
npx skills add allyourlulz-ops/trading-skills --skill trading-research    # research and validation, no order tools
npx skills add allyourlulz-ops/trading-skills --skill trading-execution   # optional: paper/live orders behind risk_check and a per-order yes or mandate
npx skills add allyourlulz-ops/trading-skills -g -a claude-code -y
```
Then add MCP servers from `skills/trading-research/assets/mcp-config.research.json` (research only) or `mcp-config.paper-execute.json` (paper orders).

## What's inside
```
skills/trading-research/
  SKILL.md                  intent guard, rules, output format, workflows
  references/               committee, data-layer, strategies, backtesting, risk-and-execution,
                            sentiment, forecasting, mcp-servers, repo-evaluation
  scripts/                  position_size.py, risk_check.py, validate_backtest.py, rule_screen.py, permutation_test.py, black_litterman.py, scorekeeper.py, crash_guard.py, rebalance.py, journal_stats.py, options_payoff.py, kelly.py, ca_tax_check.py, overfit.py, regime.py, lookahead_check.py, monkey_test.py, attribution.py, mask.py, pit_store.py, premia_signals.py, costs.py, pipeline.py, trial_ledger.py, universe.py, discover.py, factor_proxies.py, strategy_health.py (stdlib Python)
  evals/                    run_tests.py (offline script tests), trigger_evals.json, task_evals.json, tool_scenarios.json + score_tool_calls.py
  assets/                   risk-limits.json, data-routes.json, MCP configs, strategy YAML + SignalEngine templates
```

## Publish to skills.sh
Push this folder as a public GitHub repo. There's no submit step: it appears on skills.sh once people install it with `npx skills add owner/repo`. Validate first with `skills-ref validate ./skills/trading-research`.

## Before each release
```bash
python3 skills/trading-research/evals/run_tests.py     # offline script tests
uvx snyk-agent-scan@latest skills/trading-research/SKILL.md   # Snyk agent scan, run by you
```
Expect a W009 (money access) warning: execution and mandate bots live in this skill by design, behind broker-enforced paper keys, risk_check and per-order or mandate approval.

## Disclaimer
Research and education only. Not investment advice. Paper trading by default. Backtests overstate live results.


## Two skills (since v1.16.0)
- **trading-research** researches, models costs and validates. It has no order tools and no money access. `scripts/pipeline.py` runs every gate and prints READY_FOR_PAPER, PAPER_PROBE (mechanics clean, alpha unproven: paper only, at a quarter of normal size, to collect forward data) or NOT_READY. See `examples/real-data-run.md` for a run on real prices.
- **trading-execution** is optional. It places orders only after risk_check PASS and either your explicit yes or a signed mandate. It is paper first, and live needs your typed acknowledgement. Install it only if you want an agent to trade.

## v1.17.0: from rejection machine to research loop
An outside review (2026-11-24) scored the validation and safety layers 8 to 9 out of 10, and alpha generation, objective design and universe 3 to 4. This release works on the weak parts and leaves the strong ones alone:
- **Objective:** a strategy is judged against the benchmark on Sharpe and as a 30% sleeve beside it (does it lift Sharpe and cut drawdown?). Only directional strategies must also match the index's total return.
- **Promotion ladder:** PAPER_PROBE lets a strategy with clean mechanics but unproven alpha paper-trade at quarter size, so forward data can accumulate.
- **Honest trial counts:** `trial_ledger.py` logs every variant before its result is read; `--trials auto` feeds the deflated Sharpe.
- **Where the edge comes from:** references/small-capacity-edges.md (mechanism first, capacity math, published evidence) and `discover.py` (event sweeps with Benjamini-Hochberg across the whole sweep).
- **Universe:** `universe.py` builds point-in-time top-N-by-ADV membership with delisted names; cross-sectional signals need at least 100 names and two regimes.
- **Execution realism:** square-root impact, cost ladder, 3× cost stress and capacity curve in `costs.py`; part fills, borrow and locate, long-short and staggered tranches in `premia_signals.py`; per-strategy kill switch in `strategy_health.py`.
- **Correctness:** beta-matched coin-flip test, independent factor proxies, both legs of each round trip charged (v1.16.0 charged half), news as a conviction penalty instead of a veto, tiered strategy library, fast path for systematic screens.
- **Positive controls:** evals/benchmark_suite.md, run by `evals/run_tests.py`, so the gates are shown to pass a real edge and not only to fail noise.
No strategy here is shown to have an edge. These are tools to find out, honestly.
