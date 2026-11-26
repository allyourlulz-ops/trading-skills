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

## From @DN_degen's 2026-11-23 "8 Grok agents" post (audited 2026-11-23)
The post's claims (124.9x overnight) are unverified and it ends in "comment DN"; its repo-to-role labels are cosmetic. Verdicts are on the repos themselves.

| Repo | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| kernc/backtesting.py | AGPL-3.0 | 3.5 | Lightweight backtests (backtesting.md) | Use as dependency only; post called it a honeypot checker, it isn't |
| pola-rs/polars | MIT | 3.5 | Large bar-set handling (data-layer.md) | Post called it a rug watcher |
| stefan-jansen/pyfolio-reloaded | Apache-2.0 | 3 | Tearsheets (backtesting.md) | Replaces quantopian/pyfolio |
| kevinheavey/solders | Apache-2.0 | 3 | Solana on-chain reads (onchain-memecoin.md) | Active |
| jup-ag/jupiter-quote-api-node | none listed | 2 | Swap quotes, mention only | No licence file |
| quantopian/pyfolio | Apache-2.0 | 1 | Don't use | No updates since 2023 |
| MeteoraAg/dlmm-sdk | none listed | 1 | Skip | LP tooling, not research |
| plotly/plotly.py | MIT | 1 | Skip | Charting only |
The companion article (2026-11-15) contributed the kill filter, wallet-level limits, file-based desk memory and staged rollout.

## Also worth adding (from @gusik4ever's 2026-11-20 roundup; not yet audited)
- tradermonty/claude-trading-skills: daily market check, weekly portfolio review, regime-gated swing setups.
- Jakeschincariol/trader-skill: 13F mirroring, congressional trades, screener, tax lots.
- we-promise/sure: self-hosted personal finance (out of scope for trading).
- Hithink-Tech-Org/Financial-API: China A-share data MCP (needs key).
- Skip: harry0703/MoneyPrinterTurbo (video generator, not trading).

## From quantleak.zip/open-hf (195-repo index by @zostaff; audited 2026-11-23)
The index's top "Featured" cards are the maintainer's own small memecoin/Polymarket bots; skipped. Day-trading engines checked on GitHub:

| Repo | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| nautechsystems/nautilus_trader | LGPL-3.0 | 4.5 | Intraday backtest → live with one codebase | 31.8k stars, v1.231.0; heavy setup |
| edtechre/pybroker | Apache-2.0 + Commons Clause | 4 | Walk-forward + bootstrap on minute bars | 3.7k stars, v2.0.3 (2026-11-15); has its own agent skills |
| polakowo/vectorbt | Fair-code | 3.5 | Fast parameter sweeps | Limit orders/leverage only in paid PRO |
| nkaz001/hftbacktest | MIT | 3 | Queue/latency-aware book replay | Needs L2 data; last push Dec 2025. Rechecked 2026-11-25: 5.1k stars, push 2025-12-23, no change to its use here |
| yafet-a/Jane-Street-FTTP-Trading-Bot | none | 1 | Twin-listing fair value (ADR pair) | Contest-only mock exchange; pennying and ETF conversion don't transfer to retail. Idea only, own code: scripts/interlisted.py |

## roan-maverick/MIT-trader-skill (audited 2026-11-23)
| Repo | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| roan-maverick/MIT-trader-skill | MIT code; lecture notes CC BY-NC-SA 4.0 | 4 | Rule-screen method (rule_screen.py), companion skill for quant maths | Created 2026-11-23, 3 stars; stdlib Python, Yahoo data only; 51 tests pass offline. Every file carries a "Reviewed for local use" stamp: ignore it, it proves nothing |

## aardisaputra/uchicago_case3 (reviewed 2026-11-23)
| Repo | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| aardisaputra/uchicago_case3 | none (all rights reserved) | 2 | Idea only: Black-Litterman over several analysts' views | 2022 UChicago competition bot (3rd place, simulated P&L). Colab-only; passes tau where risk aversion belongs, L2-normalises weights. Not used as code |

## udiedrichsen/stock-analysis (reviewed 2026-11-23, openclaw.army listing v5.0.0)
| Repo | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| udiedrichsen/stock-analysis | not found (no public repo located) | 2 | Event-timing gate ideas only | Yahoo-based scorer with hand-set weights summing to 130%, no backtest; keyword-based geopolitical penalties. Timing guards are the useful part. Re-reviewed 2026-11-23 (SKILL.md text): added VIX backwardation, source-backed event risk, crypto BTC drag gates, 30% concentration warning in rebalance.py; still skipped the weighted score, keyword news scan and hard-coded ticker lists |

## hft.md sources (reviewed 2026-11-23)
| Source | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| hft.md/grok-bots (235 Grok Bots) + awesome-grokbot-templates | list CC0; bots closed | 2 | Capability checklist only | Names, one-line descriptions and x.ai links; no prompts or code. Not MCP skills |
| hft.md/crash/llms.txt | none stated | 4 | crash_guard.py rules, stress data sources | Clear formulas with worked numbers and stated failure modes; reimplemented, not copied |
| stefanoamorelli/sec-edgar-mcp | AGPL-3.0 | 4 | Filings MCP server (external) | Docker config; returns SEC URLs |
| JamesANZ/prediction-market-mcp | MIT | 3 | Prediction-market data MCP (external) | Read-only; movement evidence tool |

## finance-expert skill (SKILL.md text, reviewed 2026-11-23)
| Source | License | Score | Role in this skill | Notes |
|---|---|---|---|---|
| finance-expert (money-systems skill; author and repo not given) | unknown | 4 | Money invariants for the bot ledger | Strong on ledgers, idempotency, reconciliation and labelling. Its harnesses (audit_ledger.py, money_lint.py) were not provided, so nothing was copied. Its "automation never approves" rule (M11) is why mandates are signed by the user, capped and expiring |
| Questrade MCP (official) | proprietary hosted | 4 | Canadian broker data and orders | Every change needs Push Approval on the user's phone |
| openbb-tmx | OpenBB (AGPL-3.0 platform) | 4 | TSX/TSXV data | Unofficial TMX connector, no key |
| arhancanli/canli-mcp | MIT | 3.5 | Optional cross-check for deflated Sharpe/PBO; filings and options data | Broad (hundreds of tools), new, one maintainer; nothing copied |
| bcosm/backtester-mcp | Apache-2.0 | 3.5 | Optional local validation pipeline | Small project; nothing copied |
| atilaahmettaner/tradingview-mcp | MIT | 3.5 | Screeners and walk-forward verdict, self-hosted | Hosted tier is a paid outside platform: not used |
| YichengYang-Ethan/oracle3-prediction-market-agent | Apache-2.0 | 3.5 | Prediction-market paper ledger | Trading engine not used |
| jackson-cmd/risk-aware-trading-agents (rta-bench-1) | MIT | 4 | Point-in-time news design, seed spread, beta-not-alpha checks; benchmark for bots | Headlines licensed and not shipped; ideas only, nothing copied |
| Anthropic and agentskills.io skill guidance, Snyk agent-scan docs | docs | 5 | Hub-and-routing SKILL.md, third-person description, trigger and task evals, W011 phrasing | Guidance only |
| @sopersone, "A Former WorldQuant Director Published 151 Strategies for Free" (X article, 2026-10-26) + Kakushadze & Serur, *151 Trading Strategies* (SSRN 3247865, 2018) | article code unlicensed; book free to read, not openly licensed | 3 | Live-bar gates, two-sided filter leak, dollar-neutral weights, perp funding cost | Methods only, reimplemented. Skipped: 15-min neural net (fees), tweet naive Bayes (paid X API, social opt-in rule), alpha combo (grid variants are one bet), bot skeleton (raw exchange keys, leveraged perps outside the mandate) |
| Nof1 Alpha Arena seasons 1 and 1.5 (nof1.ai / alphaarena.ai) + oaia.fun coin-flip rescoring (2026-11-06, 2026-11-10) | results public; no prompts or code published; oaia script licence not stated | 3 | Coin-flip edge test, hold-is-valid and turnover lessons, decision schema with exit plan | No winner showed edge beyond chance; nothing to copy from the models. Method reimplemented in monkey_test.py |
| FinMCP-Bench (Zhu et al., arXiv 2603.24943, 2026; DianJin/FinMCP-Bench) | dataset CC BY-NC-SA 4.0 | 3.5 | Tool-chain metrics (TP, TR, TF1, EMR) and single/multi-tool/multi-turn scenario format | Data not copied; own scenarios in evals/tool_scenarios.json, scored by evals/score_tool_calls.py |
| KTD-Fin (Zhu et al., arXiv 2605.28359, 2026) | paper only, no code released | 4 | Barra-style market/style/selection attribution and four-level ticker/date masking | Reimplemented in attribution.py and mask.py |
| HKUDS/AI-Trader | no licence file in repo (checked 2026-11-24) | 3 | Live data pipeline pattern: source routing, fallback, cooldown and backoff, merged store, anti-look-ahead reads | Ideas only, no code. Direct API pulls and the ai4trade.ai platform (copy trading, points) are outside platforms: not used |
| OctopusTakopi, "Funding Rates as a Cross-Sectional Factor in Perpetual Futures" (github.com/OctopusTakopi/funding-rate-alpha @ cf9f87c, 2026) | MIT, (c) 2026 OctopusTakopi | n/a (study; findings only) | Funding = carry, not crowding; z-score stabilises carry but predicts nothing; OI/price/cross-venue overlays fail day-matched controls; settlement capture fails; 2024+ continuation | Findings cited, no code copied. Used to reframe the risk_check funding gate as a cost/tail-risk control (v2.1.1). If code is ever copied, keep "Copyright (c) 2026 OctopusTakopi" |
