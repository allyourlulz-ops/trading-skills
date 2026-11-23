# Source repo evaluation (researched 2026-11-23)
Score = usefulness as knowledge/tooling for an AI trading-research skill (1–5).

| Repo | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| TauricResearch/TradingAgents | Apache-2.0 | 5 | Committee workflow, judge prompt, rating scale, reflection loop | Many LLM calls per run; one ticker per run |
| HKUDS/Vibe-Trading | MIT | 5 | MCP backtests, SignalEngine contract, diagnose gates, bias checklist | Huge, fast-moving; live brokers experimental |
| OpenBB (openbb on PyPI) | Apache-2.0 | 5 | Default data MCP with tool discovery + pipelines | GitHub org currently shows as openbq-org; install from PyPI |
| alpacahq/alpaca-mcp-server | MIT | 4.5 | US data + paper/live execution | v2 rewrite; no server-side confirmation |
| virattt/ai-hedge-fund | MIT | 4 | Personas, blind mode, abstain, deterministic risk clamps | Rewritten as `aihf`; needs Financial Datasets key |
| Jakeschincariol/day-trader-skill | MIT | 4 | Three-gate execution, limits, fixed-seed replay | 1 commit, large PR backlog |
| freqtrade/freqtrade | GPL-3.0 | 4 | Crypto backtest/hyperopt, look-ahead checks | Call as CLI; don't embed GPL code |
| ZhuLinsen/daily_stock_analysis | MIT | 4 | YAML strategy format, dashboard schema, notify-off rule | China-retail TA heuristics |
| OpenByteInc/QuantDinger | Apache-2.0 (backend) | 4 | Gating model, PBO/DSR/BH-FDR validation | Very heavy stack |
| mvanhorn/last30days-skill | MIT | 3.5 | Sentiment/catalyst layer | 32 KB SKILL.md; many paid keys |
| shy3130/tick-stock-panel | MIT + PolyForm NC parts | 3.5 | A-share backtests, fetch discipline | A-shares only |
| LosaLosSantos/aurelio-finance | MIT | 3.5 | Advice-safety patterns, data traps | Personal finance, not trading |
| shiyu-coder/Kronos | MIT | 3 | Optional probabilistic forecaster | GPU; unproven alpha |
| stefan-jansen/zipline-reloaded | Apache-2.0 | 3 | Event-driven equity backtests | Maintenance-only |
| goldmansachs/gs-quant | Apache-2.0 | 2 | Skill-layout model only | Needs GS institutional credentials |
| janestreet/agent_skills | MIT | 1.5 | Description/intent-guard style | Only a Socratic tutor skill |
| quantopian/zipline | Apache-2.0 | 1 | Don't use | Dead since 2020 |

## Also worth adding (from @gusik4ever's 2026-11-20 roundup; not yet audited)
- tradermonty/claude-trading-skills: daily market check, weekly portfolio review, regime-gated swing setups.
- Jakeschincariol/trader-skill: 13F mirroring, congressional trades, screener, tax lots.
- we-promise/sure: self-hosted personal finance (out of scope for trading).
- Hithink-Tech-Org/Financial-API: China A-share data MCP (needs key).
- Skip: harry0703/MoneyPrinterTurbo (video generator, not trading).
