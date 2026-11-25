# trading-skills

Two agent skills (skills.sh / Agent Skills format) for evidence-first trading research over MCP. `trading-research` finds candidate edges, models costs and capacity, and validates them; it has no order tools. `trading-execution` (optional) places paper or live orders behind risk checks and your approval. Built from 16+ open-source trading and quant repos and published research (see `skills/trading-research/references/repo-evaluation.md` and `NOTICE`).

Current version: trading-research 1.18.0, trading-execution 1.1.0. No strategy here is shown to have an edge. These are tools for finding out honestly.

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
  references/               committee, data-layer, strategies (tiered A/B/C), backtesting, documented-edges,
                            small-capacity-edges, regime-and-news, risk-and-execution, sentiment, forecasting,
                            options, filings-and-flows, prediction-markets, portfolio-and-routines, canada,
                            onchain-memecoin, mcp-servers, repo-evaluation
  examples/                 real-data-run.md (10 ETFs, 2017-2026, every gate shown)
  scripts/                  position_size.py, risk_check.py, validate_backtest.py, rule_screen.py, permutation_test.py, black_litterman.py, scorekeeper.py, crash_guard.py, rebalance.py, journal_stats.py, options_payoff.py, kelly.py, ca_tax_check.py, interlisted.py, overfit.py, regime.py, lookahead_check.py, monkey_test.py, attribution.py, mask.py, pit_store.py, premia_signals.py, costs.py, pipeline.py, trial_ledger.py, universe.py, discover.py, factor_proxies.py, strategy_health.py (stdlib Python)
  evals/                    run_tests.py (offline script tests + positive-control suite), benchmark_suite.md, trigger_evals.json, task_evals.json, tool_scenarios.json + score_tool_calls.py
  assets/                   risk-limits.json, data-routes.json, MCP configs, strategy YAML + SignalEngine templates
skills/trading-execution/
  SKILL.md                  order rules, per-order yes, signed mandates, broker notes (Alpaca, Questrade, IBKR)
  scripts/                  mandate.py, risk_check.py, position_size.py, strategy_health.py (shared scripts byte-identical with research)
  assets/                   mandate.example.json, risk-limits.json, mcp-config.paper-execute.json
```

## How a strategy moves
1. **Find:** documented premia (`premia_signals.py`) or small-capacity event edges (`discover.py`); every idea must name who loses and why.
2. **Count:** every variant goes in `trial_ledger.py` before its result is read.
3. **Test:** point-in-time universe (`universe.py`), costs with impact and capacity (`costs.py`), then `pipeline.py`.
4. **Verdict:** NOT_READY (a mechanical gate failed), PAPER_PROBE (mechanics clean, alpha unproven: paper only, at quarter size), or READY_FOR_PAPER.
5. **Run and retire:** paper through trading-execution; `strategy_health.py` retires a strategy that stops working. Live money always needs your own keys and typed acknowledgement.

## Publish to skills.sh
Push this folder as a public GitHub repo. There's no submit step: it appears on skills.sh once people install it with `npx skills add owner/repo`. Validate first with `skills-ref validate ./skills/trading-research`.

## Before each release
```bash
python3 skills/trading-research/evals/run_tests.py     # offline script tests + positive controls
python3 skills/trading-execution/evals/run_tests.py    # execution checks
uvx snyk-agent-scan@latest skills/trading-research/SKILL.md    # Snyk agent scan, run by you
uvx snyk-agent-scan@latest skills/trading-execution/SKILL.md
```
trading-research has no money access. A W009 (money access) warning is expected only on trading-execution, which is optional and gated by broker-enforced paper keys, risk_check, and a per-order yes or a signed mandate.

## Disclaimer
Research and education only. Not investment advice. Paper trading by default. Backtests overstate live results, and published premia shrink after publication.


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
