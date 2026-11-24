# trading-skills

An agent skill (skills.sh / Agent Skills format) for evidence-first trading research, backtesting and risk-gated execution over MCP. It distils 16 open-source trading and quant repos into one skill (see `skills/trading-research/references/repo-evaluation.md`).

## Install
```bash
npx skills add allyourlulz-ops/trading-skills            # any agent supported by the skills CLI
npx skills add allyourlulz-ops/trading-skills -g -a claude-code -y
```
Then add MCP servers from `skills/trading-research/assets/mcp-config.research.json` (research only) or `mcp-config.paper-execute.json` (paper orders).

## What's inside
```
skills/trading-research/
  SKILL.md                  intent guard, rules, output format, workflows
  references/               committee, data-layer, strategies, backtesting, risk-and-execution,
                            sentiment, forecasting, mcp-servers, repo-evaluation
  scripts/                  position_size.py, risk_check.py, validate_backtest.py, rule_screen.py, permutation_test.py, black_litterman.py, scorekeeper.py, crash_guard.py, rebalance.py, journal_stats.py, options_payoff.py, kelly.py, mandate.py, ca_tax_check.py, overfit.py, regime.py, lookahead_check.py, monkey_test.py, attribution.py, mask.py, pit_store.py (stdlib Python)
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
