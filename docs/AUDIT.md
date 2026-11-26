# Phase 0 audit: trading-skills v2.1.1

Audited on 2026-11-26 from the local tree at `2a5b243` (mirrors remote `main` `9e89620`, v2.1.1).
Paths are relative to the repo root. `exec/` = `skills/trading-execution/`, `res/` =
`skills/trading-research/`. Line numbers are for v2.1.1, before any Phase 0 file was added.
Phase 0 changes no shipped script under `scripts/`; nothing here is fixed yet.

Scratch reproductions (not shipped): `work/phase0/suspicions.py` and its output, outside the repo
in the project workspace. Each result quoted below was produced by running the real scripts.

---

## 1. Inventory

### 1.1 trading-execution scripts (`exec/scripts/`)

| Script | Purpose | Called by | Trusts | Emits |
|---|---|---|---|---|
| `risk_check.py` (shared) | Hard pre-trade gate for one order; issues the nonce | Agent per `exec/SKILL.md` §1.1, §2; research dry runs; `evals/repro.py` | order.json, portfolio.json, limits file, contract, instrument, bar, context, `--now`, `--gate-dir`, override reason/ack (all caller-supplied files) | JSON verdict, reasons, sizing, `limits_used`, nonce; appends `gate-log.jsonl` / `overrides.jsonl`. Exit 0/1/2 |
| `position_size.py` (shared) | Portfolio-aware sizing; `size()` is called by risk_check | risk_check (`:294`); agent for `size-it` | portfolio (equity, buying power, positions, fx, correlations, today), limits, instrument spec | qty, binding constraint, all constraints, risk/notional per unit |
| `gate.py` (shared) | Nonce issue/verify (HMAC over the nonce body), override log | risk_check (`:357`), preview (`:117`), mandate (`:127`) | `gate.key` and `gate-log.jsonl` in the gate dir; order JSON; limits path; `--now` | nonce string; OPEN/CLOSED; appends used/issued rows |
| `data_contract.py` (shared) | Declared-metadata check of each data series (offsets, staleness, adjustment, currency) | risk_check (`:273`) | Whatever the contract declares (it never sees the numbers) | OK / INVALID / STALE / UNALIGNED / POLICY |
| `mcp_lock.py` (shared) | Pin check of an MCP config against the lock; tool-description hash/drift/injection scan | CI (`ci.yml` last step); agent per `exec/SKILL.md` §1.11 | The lock file; a tools/list JSON the user saved | PINNED/UNPINNED; OK/UNRECORDED/DRIFT/SUSPECT |
| `strategy_health.py` (shared) | Per-strategy kill switch (drawdown, under-water days, slippage) | Agent after each close (`exec/SKILL.md` §2) | strat equity CSV, fills CSV (expected vs fill price) | KEEP/WATCH/RETIRE |
| `preview.py` | Last step before the order tool: mode from MCP config, verifies and consumes the nonce, prints MODE first | Agent (`exec/SKILL.md` §1.1); repro.py | MCP config, lock (`mode` for non-Alpaca servers), order, risk result or `--nonce`, limits path, gate dir, `--now` | Preview lines (first line = mode), gate OPEN/CLOSED; marks nonce used |
| `mandate.py` | Standing mandate: check/record/status/halt/reconcile | Agent for bots (`exec/SKILL.md` §2) | mandate.json (unsigned file), ledger.jsonl (self-written), risk result + nonce, order, broker fills JSON, `--now` | AUTO_OK/NEEDS_YES/HALT; ledger rows; HALT file |

### 1.2 trading-research scripts (`res/scripts/`), beyond the shared six

All are run by the agent as routed by `res/SKILL.md`; none touches the network.

| Script | Purpose | Trusts | Emits |
|---|---|---|---|
| `validate_backtest.py` | Flag mode (stats report) and `--manifest` rigor mode (fail-closed promotion gate) | Manifest JSON and every artifact it names (equity curves, turnover, trades, regimes, folds, trials, trial_sharpes, universe dict, costs, llm_in_loop, masked) | pass/fail + per-check status, metrics |
| `costs.py` | Gross → net returns with cost lines, ladder, ×1/×2/×3 stress, capacity | gross CSV (`ret`, `turnover`, optional `adv_frac`, `sigma`, `short`, `trades`), costs.json (no validation) | net CSV + equity CSV, JSON summary |
| `pipeline.py` | Runs costs → validate_backtest → PBO → externally supplied result JSONs, one ladder verdict | Its inputs plus lookahead/permutation/universe result JSONs passed by path (`:132`) | NOT_READY / PAPER_PROBE / READY_FOR_PAPER |
| `engine.py` | Minimal backtest engine whose output is a manifest | bars CSV, user signal module | manifest + artifacts |
| `overfit.py` | PBO, DSR, CPCV | variants CSV, trial count / ledger | JSON stats |
| `trial_ledger.py` | Append-only variant ledger (`--trials auto`) | ledger JSONL (self-written) | trial counts |
| `rule_screen.py`, `discover.py`, `permutation_test.py`, `monkey_test.py`, `lookahead_check.py` | Edge screens: BH-FDR, sweeps, permutations, coin-flip, look-ahead rerun | trades / events / prices CSV; `lookahead_check` runs a user command | JSON verdicts |
| `universe.py`, `pit_store.py` | Universe breadth/survivorship verdict; point-in-time bar store with source fallback | membership CSVs; MCP-fetched rows written to files | JSON verdict; merged JSONL store |
| `premia_signals.py`, `factor_proxies.py`, `attribution.py`, `regime.py`, `crash_guard.py`, `rebalance.py`, `black_litterman.py`, `kelly.py`, `options_payoff.py`, `interlisted.py`, `ca_tax_check.py`, `journal_stats.py`, `scorekeeper.py`, `mask.py` | Signals, attribution, regime, sizing helpers, payoff, Canada tools, journal and forecast scoring, masking | User/MCP-fetched CSV/JSON files | JSON reports |

### 1.3 Eval and CI tooling

| File | Purpose |
|---|---|
| `res/evals/run_tests.py` | 161 offline checks plus the 16 manifest golden cases |
| `res/evals/golden/run_golden.py`, `cases.json`, `make_fixtures.py` | Golden runner for validate_backtest manifests |
| `exec/evals/run_tests.py` | compile + `--help` for each script, byte identity of the six shared scripts, mandate probes, funding gate, golden runner; **Phase 0 adds** repro and recorder checks |
| `exec/evals/golden/run_golden.py`, `cases.json`, `fixtures/` | 62 golden cases for position_size, risk_check, gate, preview, data_contract, mcp_lock |
| `.github/stdlib_guard.py` | Fails on any non-stdlib import (Phase 0: evals/*.py stems now count as local modules) |
| `.github/workflows/ci.yml` | ruff F,E9 (0.8.4) + stdlib guard + both run_tests + pin check, on py3.9 and 3.12 (ubuntu-22.04). **Phase 0 adds** a `repro` job |

### 1.4 Reference files and assets

`res/references/` (20 files) is prose read by the agent; none is executed. Its one-line map is in
the earlier untracked `audit.md` §1 and still holds at v2.1.1 except where scripts changed.
`exec/references/known-limitations.md` and `risk-and-execution.md` describe the gate; the first is
the honest list of what the gate does not stop (`:6-10`, `:20`, `:24-30`).
Assets: `risk-limits.json` (two copies, **not** byte-identical, and not checked by run_tests:
`cmp` differs at byte 391, by design, research allows shorts/options for proposals),
`mcp-lock.json`, `mcp-config.*.json`, `assets/locks/*.txt` (uv hash-locked requirements),
`mandate.example.json`.

---

## 2. Trust table

"Verified how" is what the code checks today. "Bypassable how" is what an agent (or a caller) can
do without editing any shipped script.

| Input | Source | Verified how | Bypassable how |
|---|---|---|---|
| order.`asset_class` | Agent-written order.json | Default `equity` (`risk_check.py:224`); OPTIONS_OFF / CRYPTO_OFF only if declared (`:235-238`) | Declare `equity` for anything; session, multiplier and gap then come from the equity defaults or from instrument.json |
| order.`qty` | order.json | `qty > 0` (`:222`); `qty <= sized max` (`:303`); bound into fingerprint (`gate.py:40-42`) | Not by itself; via inflated sizing inputs (portfolio, instrument) |
| order.`side` | order.json | buy/sell only (`:178-182`); SHORT_OFF (`:256-257`) | `is_exit` path |
| order.`is_exit` | order.json | Must reduce a position listed in portfolio.positions (`:185-195`) | Fabricate a position in portfolio.json; exits skip every entry limit (`:251-254`); mandate skips all scope checks for exits (`mandate.py:130`) |
| order.`uses_margin` | order.json | MARGIN_OFF only when the flag is truthy (`:239`) | Omit the flag |
| order prices (`limit_price`, `est_price`, `stop_price`, `target_price`) | order.json | `px > 0` (`:261`); stop on the losing side (`position_size.py:144-146`); no check against the contract's quote value | Any limit price; the contract only proves a quote series was *declared* (`data_contract.py` reads metadata, never prices) |
| order.`risk_pct` / `risk_amount` | order.json | Can only lower the risk budget (`position_size.py:155-170`); above cap → reason | n/a (it is a limiter) |
| `--now` | CLI of risk_check, preview, gate, mandate | Parsed only (`risk_check.py:337`; `gate.py:70-77`; `mandate.py:69`) | Rewind it: an expired nonce reopens (repro: `verify at now+1h` CLOSED, `--now` rewound OPEN); data staleness is measured from it (`risk_check.py:272`); the entry window reads its offset, not `limits.timezone` (`:207`) |
| portfolio.`equity`, `buying_power` | Agent-assembled from broker reads | `> 0` / present (`position_size.py:125-127`, `:200-201`) | Any number (`known-limitations.md:8`) |
| portfolio.`positions` | Agent-assembled | Shape only (`position_size.py:100-107`) | Omit positions → no heat/cluster/position usage; invent one → `is_exit` passes |
| portfolio.`paper` | Agent-assembled | Must exist and match `--mode` (`risk_check.py:241-247`) | Set it; preview's mode comes from the MCP config instead (`preview.py:109`), which is the real check for Alpaca |
| portfolio.`today.*` | Agent-assembled | Read as numbers (`risk_check.py:288-292`; `position_size.py:182-186`) | Zero them |
| portfolio.`clock` | Agent-assembled (`get_clock`) | `is_open` and a non-empty `source` string (`risk_check.py:201-206`) | Write `{"is_open": true, "source": "x"}`; or skip the session gate entirely via instrument `session: "24x7"` |
| instrument.json | Caller file | `multiplier`, `lot_step`, `min_qty` > 0 (`position_size.py:94-96`); otherwise `spec.update(given)` (`:92`) | `{"session": "24x7"}` on an equity skips MARKET_CLOSED (repro: pf_closed → pass); `{"multiplier": 0.01}` sizes AAPL at 5263 shares and passes |
| Limits file | `--limits` (default `assets/risk-limits.json`, `risk_check.py:43`, `:329`) | Content hash in the nonce (`gate.py:98`), compared at verify if a path is given (`:132`) | Pass any permissive file to risk_check and the same file to preview; `gate.py verify` without `--limits` skips the check (`:132`, `:153`) |
| Data contract | Caller file | Declared fields, offsets, staleness vs gate clock, adjustment policy (`data_contract.py:51-108`); quote series for this symbol (`risk_check.py:276-278`) | Declare fresh timestamps; `source` is free text (`known-limitations.md:20`) |
| Bar | Caller file, optional | Only if given or `require_bar` (`risk_check.py:279-283`); default `require_bar: false` | Omit it (warning only, `:57-59`) |
| Context | Caller file, optional | Staleness, earnings, VIX etc. (`timing_gates`, `:83-161`) | Omit it (warning only for equity, `:88-91`); omit `next_earnings_date` (warning, `:97-98`) |
| Mandate file | `assets/mandate.json` or `--mandate` | Dates ≤30 days, live_ack sentence, caps, scope (`mandate.py:75-160`) | It carries no signature: edit symbols/caps and the same order is AUTO_OK (repro: TSLA NEEDS_YES → AUTO_OK after edit) |
| Mandate ledger | Self-written JSONL (`record`, `--pnl` self-reported, `mandate.py:173-189`) | Append-only by convention | Omit losing rows; `reconcile` compares qty/price only, not P&L (`:204-233`) |
| Gate dir / gate.key | `--gate-dir`, `$TRADING_GATE_DIR`, `~/.trading-gate` (`gate.py:45-48`) | Created 0700, key 0600 (`:47`, `:54`) | Point it anywhere, including inside the project (accepted); read the key, MAC a nonce, append one `issued` row to `gate-log.jsonl` in the same dir → OPEN (repro) |
| Nonce | Echoed by agent | MAC, log membership, not used, not expired, fingerprint, limits, mode, verdict (`gate.py:114-145`) | Via `--now` and key/log access above |
| MCP tool descriptions | tools/list JSON saved by user/client | Hash vs lock; regex injection scan of description and property descriptions (`mcp_lock.py:50-54`, `:98-117`) | Every shipped lock has `tools: {}` → verify can only say UNRECORDED (or SUSPECT); tool *results* are not scanned at all; scan misses names, enums, nested schemas |
| MCP config mode | `mcp-config*.json` | Alpaca: literal `"true"`/`"false"` only (`preview.py:41-48`) | Non-Alpaca servers: mode is read from the lock entry's `mode` (`:49-51`); preview does not run check-config |
| Manifest: equity curves | Files named in manifest | Dated, increasing, ≥95% date overlap, ≥30 common dates (`validate_backtest.py:217-245`) | Paths are joined to the manifest dir but absolute paths are allowed (`:181`; it opened `/etc/hostname`); no hash binds artifacts to an engine run |
| Manifest: turnover | File | Consistency: net == gross − 2·turnover·cost (`:308-312`) | Under-report turnover and net together |
| Manifest: regimes | Label file | ≥2 regimes with ≥63 periods, labels present (`:364-388`) | Self-labelled |
| Manifest: trials | Integer | ≥1 (`:341-347`) | `trial_sharpes` with 2 entries replaces trials (`:118-120`): `trials: 100000` fails, adding `trial_sharpes: [0.05, 0.0501]` passes (repro) |
| Manifest: trial_sharpes | List | Length ≥2 → cross-trial variance | Supply near-equal values → SR0 ≈ 0 |
| Manifest: folds | List | test after train, no overlap, ≥3, half positive (`:316-340`) | Self-defined boundaries; no re-optimisation check (`known-limitations.md:25`) |
| Manifest: universe / llm_in_loop / masked | Self-declared | `verdict == "OK"` and `includes_delisted` (`:296`); booleans (`:393-409`) | Declare them |
| costs.json | Caller file | None: `dict(DEF, **json)` (`costs.py:88`) | Negative `slippage_bps` makes net > gross (repro: gross 0.001 → net 0.0029); missing `adv_frac`/`sigma` → impact 0 (`:62`) |
| gross.csv turnover / adv_frac / sigma | Caller file | Parsed (`costs.py:54`) | Under-report |

---

## 3. The four suspicions

**(a) "gate.py hashes the limits path, not its contents."** **Refuted as stated.**
`file_sha8` reads the file's bytes (`gate.py:60-63`). The 8-hex hash is a field of the nonce body
(`:98`), so the MAC covers it (`:99`), and verify recomputes it from the file (`:132`). It is
**not** in the order fingerprint, which hashes the order JSON only (`:40-42`). Reproduction:
nonce `lim` = `de832bc8` = `file_sha8(limits)`; after raising `max_loss_per_trade` in the file,
verify with the path → CLOSED "risk-limits file changed since the check". Residual weaknesses:
verify skips the comparison when no limits path is passed (`:132`; `gate.py verify --limits` is
optional, `:153`), so the same edited file opens with no `--limits`; a missing file at issue time
yields `nolimits` (`:61-62`); and the hash binds *a* file, not *the* shipped file (risk_check
accepts any `--limits`, `risk_check.py:329`). preview and mandate always pass a limits path
(default `assets/risk-limits.json`, `preview.py:93`, `mandate.py:256`).

**(b) "The default gate_dir resolves into the project root."** **Default refuted; inside-project
confirmed possible.** `gate_dir()` is `--gate-dir` or `$TRADING_GATE_DIR` or
`~/.trading-gate` (`gate.py:45-48`). Nothing checks where it points. Reproduction:
`TRADING_GATE_DIR=skills/trading-execution/assets/.phase0-gate-probe risk_check.py ...` → exit 0,
`gate.key` created inside the repo. With that key a forged nonce fails only on log membership
("nonce not in gate-log.jsonl", `:124-125`); appending one `{"event":"issued"}` row to the
same dir's log makes it OPEN. `known-limitations.md:7` says to keep the dir outside the project; it
is advice, not enforced.

**(c) "mandate.py check re-validates field scope, or only the signature?"** **It re-validates
scope; there is no signature at all.** For entries it checks symbols, strategy, asset class,
shorts, per-order and daily notional, orders per day, stop and open positions
(`mandate.py:130-160`), and verifies the gate nonce for this order and the mandate's mode
without consuming it (`:121-129`). The mandate itself is a plain JSON file; the word "signed" in
the docs (`:3`) means "agreed field by field with the user". Reproduction: TSLA not in symbols →
NEEDS_YES; same order after adding TSLA to mandate.json → AUTO_OK. Scope is checked against
self-reported order fields (`strategy`, `asset_class`, `paper`, `:91-94`, `:134-137`), and an
`is_exit: true` order skips every scope check (`:130`); with a PASS nonce for it, TSLA
`is_exit` → AUTO_OK. (risk_check would have required a held position, but that comes from
portfolio.json.)

**(d) "mcp_lock.py verify vs recorded hashes; is `tools` empty?"** **Confirmed.** `tools` is
`{}` for every server in both locks: execution `openbb`, `alpaca`; research `openbb`, `alpaca`,
`vibe-trading`, `orderflow`. With no recorded hashes verify returns UNRECORDED (`mcp_lock.py:110-111`),
exit 2, so it can never say OK on the shipped locks. Reproduction: shipped lock + golden
`tools_clean.json` → UNRECORDED exit 2; golden `lock_recorded.json` → OK exit 0; injected
descriptions → SUSPECT (the scan result is checked before the empty check, `:108-111`).

---

## 4. Baseline (before Phase 0 additions)

| Suite | Python 3.12.16 | Python 3.9.25 (`uvx --python 3.9`) |
|---|---|---|
| `res/evals/run_tests.py` | 161 PASS, 0 FAIL, "all passed" | 161 PASS, 0 FAIL, "all passed" |
| `res/evals/golden/run_golden.py` | 16/16 | 16/16 |
| `exec/evals/run_tests.py` | 30 PASS, 0 FAIL, "all passed" | 30 PASS, 0 FAIL, "all passed" |
| `exec/evals/golden/run_golden.py` | 62/62 | 62/62 |
| `uvx ruff check --select F,E9 --target-version py39 skills .github` | All checks passed | |
| `.github/stdlib_guard.py` | stdlib only: ok | |

After Phase 0 (this branch): `exec/evals/run_tests.py` 39 PASS, 0 FAIL, 62/62 golden,
7/7 repro (5 ok, 2 skipped slots), "all passed" on 3.12 and 3.9; research unchanged (161 + 16/16);
ruff (latest and 0.8.4) clean on `skills .github`; stdlib guard ok on 3.12 and 3.9.

---

## 5. Audit register

The claim text for T1-T9, M1-M11, B1-B10, S1-S6 and C1-C5 is in the phase plan, which did **not**
reach this run (it is not in the repo, the project files or the earlier audit). Only the IDs whose
subject is known are assessed. Where the user reported a spot-check status, it is listed as
reported and marked **not independently verified**.

| ID | Subject | Status | Evidence |
|---|---|---|---|
| T1 | (claim text not received) | confirmed (user spot-check; not independently verified) | — |
| T2-T5 | (claim text not received) | not assessed | — |
| T6 | Limits hash bound to the gate | refuted (contents are hashed and MAC-covered; not in the fingerprint; skipped without a path) | `gate.py:60-63`, `:98-99`, `:132`, `:40-42`, `:153`; §3(a) |
| T7 | Gate dir location | partial: default refuted; inside-project accepted, nothing stops it | `gate.py:45-48`; `risk_check.py:329`; §3(b) |
| T8-T9 | (claim text not received) | not assessed | — |
| M1, M2 | (claim text not received) | confirmed (user spot-check; not independently verified) | — |
| M3-M11 | (claim text not received) | not assessed | — |
| B1 | (claim text not received) | confirmed (user spot-check; not independently verified) | — |
| B2 | (claim text not received) | not assessed | — |
| B3 | (claim text not received) | partial (user spot-check; not independently verified) | — |
| B4-B10 | (claim text not received) | not assessed | — |
| S1 | (claim text not received) | confirmed (user spot-check; not independently verified) | — |
| S2-S6 | (claim text not received) | not assessed | — |
| C1-C5 | (claim text not received) | not assessed | — |
| A1 | Committee scoring / calibration (Phase 6). Claim tested: scored, but nothing acts on the score | partial | `res/scripts/scorekeeper.py` logs/grades/Brier/calibration (`res/SKILL.md:113`); no script reads its output to weight or veto views; Black-Litterman confidence is self-reported (`res/scripts/black_litterman.py` `--views`) |
| A2 | Real-data evidence (Phase 7). Claim tested: no real-data evidence in tests | confirmed | Only `res/examples/real-data-run.md`; all golden and repro fixtures are hand-written; both recorders unrun |
| A3 | Point-in-time data layer (Phase 8) | partial | `res/scripts/pit_store.py` (as-of reads, no forming bars); `data_contract.py` checks declarations only (`exec/references/known-limitations.md:20`) |
| A4 | Tags / release notes (Phase 10) | partial | `CHANGELOG.md` present; no tags locally (`git tag`) or on GitHub (`GET /repos/allyourlulz-ops/trading-skills/tags` returned `[]` on 2026-11-26); no GitHub releases checked |
| A5 | npx pinning + routing tests (Phase 10) | partial | npx `pkg@X` and `github:repo#<40-hex>` pinning enforced (`mcp_lock.py:75-84`; `mcp-servers.md:60`, `:66`); trigger/task evals are not run in CI (`res/evals/run_tests.py:4`) |
| A6 | CODEOWNERS / second reviewer / clean-install pins (Phase 10) | confirmed (gap) | No `CODEOWNERS` in `.github/`; hash-locked requirements exist (`assets/locks/*.txt`) but were never clean-installed (`known-limitations.md:30`) |
| A7 | Options long premium only (unassigned, from external audit) | confirmed (the constraint holds) | `position_size.py:137-140`; `risk_check.py:235-236`; exec limits `allow_options: false` |
| A8 | Black-Litterman only (unassigned, from external audit) | confirmed (descriptive: BL is the only multi-name optimiser) | `res/SKILL.md:68`; `res/scripts/rebalance.py` targets weights, no optimisation |
| A9 | Execution quality (Phase 9) | partial | Slippage vs budget in `strategy_health.py:8-14`; reconcile price tolerance `mandate.py:221-223`; no fill-vs-quote TCA, no partial-fill model in exec; repro's fill is at the limit price |
| A10 | Docs (unassigned, from external audit) | partial | `known-limitations.md` omits P1-P4 and P8 below |

### 5.1 Provisional findings (NOT register IDs; flagged for mapping)

| ID | Finding | Evidence |
|---|---|---|
| P1 | `--now` is caller-controlled everywhere: nonce expiry, data staleness and the entry window all follow it | `risk_check.py:337`, `:272`; `gate.py:128`; `preview.py:117`; `mandate.py:69`; §2 |
| P2 | instrument.json overrides session, multiplier, gap: equity `session: "24x7"` skips MARKET_CLOSED; `multiplier: 0.01` passes 5263 AAPL shares | `position_size.py:92`; `risk_check.py:199-200` |
| P3 | Entry window compares `--now`'s own clock time, not the limits timezone: 11:00 ET passed as `16:00Z` fails "no entries after 15:30" (and a late-ET time in UTC could pass) | `risk_check.py:207`, `:336-339` |
| P4 | Two `trial_sharpes` override `trials`: 100000 trials FAIL → PASS | `validate_backtest.py:118-120`, `:344` |
| P5 | costs.json is not validated: negative costs raise net above gross | `costs.py:88`, `:51-62` |
| P6 | Manifest artifact paths are not confined to the manifest's folder | `validate_backtest.py:181` |
| P7 | gate.key and gate-log.jsonl share one dir; key + one appended row = OPEN | `gate.py:51-57`, `:124` |
| P8 | Non-Alpaca preview mode comes from the lock's `mode` field; preview never runs check-config; no IBKR config/lock is shipped | `preview.py:49-51` |
| P9 | `uses_margin` and `asset_class` are self-declared | `risk_check.py:224`, `:239` |
| P10 | Exits trust portfolio.positions; mandate skips scope for exits | `risk_check.py:185-195`, `:251-254`; `mandate.py:130` |
| P11 | Mandate P&L comes from a self-written ledger with self-reported `--pnl`; mandate `now` is naive local time | `mandate.py:98-111`, `:182-183`, `:69` |
| P12 | Mandate ledger and HALT default inside the skill folder | `mandate.py:249`, `:61-62`, `:38` |
| P13 | The two `risk-limits.json` copies differ and nothing checks they differ only where intended | `cmp` at byte 391; not in `exec/evals/run_tests.py:19` |

---

## 6. Brokers: Alpaca paper and IBKR paper

IBKR paper is now a supported option next to Alpaca paper (Canadians cannot open Alpaca
accounts). `exec/evals/repro.py` has a simulated broker layer selected by `meta.broker`:
`alpaca_paper` (Alpaca Trading API v2: `/v2/account`, `/v2/clock`, `/v2/positions`) or
`ibkr_paper` (IBKR Client Portal Web API: `/portfolio/accounts`, `/portfolio/{accountId}/summary`,
`/portfolio/{accountId}/positions/0`).

- **IBKR's paper calls need a logged-in Client Portal Gateway session** on the user's machine
  (the session lives in the gateway; there is no API key a CI runner could hold). **CI can
  therefore only replay recorded or synthetic IBKR responses**; it can never call IBKR.
  `exec/evals/record_ibkr.py` exists for the user to run locally: GET only, local https gateway
  only, refuses any account id not starting with `DU` (IBKR paper), redacts every account id and the
  account names. It has not been run.
- The Web API has no single market-clock call, so the IBKR fixture supplies `meta.clock` with its
  source. Deriving it from the exchange schedule endpoint is not implemented (its response shape was
  not verified here).
- Paper is proven differently per broker: Alpaca by the host the responses came from
  (`paper-api.alpaca.markets`), IBKR by the `DU` account prefix, which redaction keeps.
- Alpaca paper responses can be recorded in CI by the manual `.github/workflows/paper-live.yml`
  (secrets `ALPACA_PAPER_KEY`, `ALPACA_PAPER_SECRET`; GET only; nothing committed back).
- Buying power: both layers prefer the cash-style figure (`non_marginable_buying_power`,
  `availablefunds`) because the limits keep margin off. Day P&L: Alpaca's `equity − last_equity`
  is counted as realised when negative (it includes unrealised P&L: the conservative side).
  Both are judgement calls, flagged here.
- The IBKR and Alpaca response shapes in `exec/evals/repro/synthetic/` were written from the
  public API documentation as remembered, not checked against a live response. Field names may
  differ in detail; the first real recording will tell.

## 7. What Phase 0 added (no shipped script changed)

- `docs/AUDIT.md` (this file).
- `exec/evals/repro.py`: replay of portfolio → order → risk_check → preview → simulated fill,
  diff vs expected.json, `--bless`, `--require-recorded`, temp gate dir outside the repo.
- `exec/evals/repro/` fixtures and README. **All committed fixtures are synthetic**:
  `pass_paper_buy`, `pass_paper_buy_alpaca`, `pass_paper_buy_ibkr_tsx`, `hard_fail_too_big`,
  `soft_fail_override`. The two `paper-broker/` slots hold no recordings yet.
- `exec/evals/record_alpaca.py`, `exec/evals/record_ibkr.py` (not run).
- `exec/evals/run_tests.py`: runs repro and offline checks of both recorders.
- `.github/workflows/ci.yml`: new `repro` job (py3.9 and 3.12, ubuntu-22.04); existing job unchanged.
- `.github/workflows/paper-live.yml`: manual Alpaca paper record-and-replay.
- `.github/stdlib_guard.py`: evals/*.py stems count as local imports.

## 8. Not done or unverified in Phase 0

- Register claims T1-T9, M1-M11, B1-B10, S1-S6, C1-C5: text not received; see §5.
- No recorder was run; no real broker response exists in the repo.
- GitHub releases (as opposed to tags) were not checked (A4).
