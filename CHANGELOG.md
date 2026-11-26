# Changelog

Earlier releases are summarised, with their sources, in NOTICE.

## 2.2.0-dev (unreleased): Phase 1, trust boundary

Both skills move to 2.2.0-dev. Register IDs are from the hardening plan; P-numbers are the Phase 0
provisional findings in docs/AUDIT.md. Tests: `skills/trading-execution/evals/trust_tests.py`.

### Fixed
- T1 (P9): `asset_class` is derived from the instrument spec and the symbol's shape (OCC option symbol, BASE/QUOTE crypto pair, exchange ticker), not taken from the order's label. Order/spec disagreement, an option symbol labelled equity, a ticker labelled crypto or option, an `etf` label without a spec saying etf, and a non-option with multiplier 100 each fail HARD with `ASSET_CLASS`. `position_size.py --asset-class` is now optional and checked the same way. Tests `T1_*`.
- T2 (P1): every risk_check needs `portfolio.clock.as_of` and `source` (the broker clock's own timestamp, crypto included); `--now`, or this machine's time when it is omitted, must be within `gate.clock_tolerance_s` (new, default 120, capped at 300) of it, else HARD `CLOCK_DRIFT` / `NO_CLOCK`. The drift is reported in a new `clock` output block. A naive `--now` (no UTC offset) is refused. A live check must also be within the tolerance of the machine clock; a paper replay gets a warning. P1: nonce expiry now also runs on the gate's own wall clock from issue (`wall`, `ttl` in the gate log), so a rewound `--now` cannot reopen an expired nonce, and `token_ttl_s` is capped at 300 s. Golden change: `rc_crypto_saturday` now uses `pf_clock_sat.json` (a Saturday broker clock); repro expected.json files gain the `clock` block and the paper-replay warning. Tests `T2_*`.
- P3 (under T2): the entry window (`no_entries_before` / `no_entries_after`) and calendar dates are read in `limits.timezone`, not in whatever offset `--now` carries: 11:00 New York passed as `16:00Z` no longer fails, and 15:45 New York passed as `12:45-08:00` no longer passes. A limits timezone that cannot be loaded is bad input. `checked_at` is printed in the limits timezone. Tests `P3_*`.
- T3 (P9, P10): `uses_margin` is derived, not read from the order: a short entry, or a long whose notional exceeds the new `portfolio.settled_cash`, uses margin, so with `allow_margin: false` it fails HARD `MARGIN_OFF` even when the order says `uses_margin: false`. A missing `settled_cash` fails HARD `NO_CASH` while margin is off. The report is in a new `margin` output block. An `is_exit` order needs `portfolio.positions_source {source, as_of}` (the broker positions read) within the clock tolerance, else HARD `EXIT_UNVERIFIED`. `mandate.py check` no longer skips scope for exits (`mandate.py:130`): symbols, strategies and asset classes apply to exits, and an exit must close a position this mandate's ledger opened, else NEEDS_YES. Golden change: every `pf_*.json` gains `settled_cash`, `pf_hold_aapl.json` (and the two other fixtures with positions) gains `positions_source`, and `limits_open.json` gains `allow_margin: true` so `rc_short_allowed` still shows an allowed short (a short always borrows). Repro: the Alpaca and IBKR layers map `settled_cash` and `positions_source`; expected.json files gain them and the `margin` block. Tests `T3_*`.

## 2.1.1 (2026-11-25)

Both skills (trading-research, trading-execution) move to 2.1.1.

### Changed
- `risk_check.py` funding gate (both copies) is now a **cost and tail-risk control, not a crowding or return signal**. The warning names the paying side (longs or shorts), shows the funding as %/yr and as carry cost in bps/day, mentions squeeze/liquidation tail risk, and says it is not a return forecast. The word "crowded" is gone.
- Why: OctopusTakopi, *funding-rate-alpha* (2026, MIT; github.com/OctopusTakopi/funding-rate-alpha @ cf9f87c; findings cited, no code copied) finds raw funding measures retail orientation and carry rather than crowding, OI and price confirmation add nothing after day-matched controls, and since 2024 high funding preceded short-horizon continuation. The holding cost and the unmeasured liquidation/ADL tail still justify a mild size dampener at a far-tail level.
- `risk-limits.json` (both): `timing.funding_crowded_multiplier` renamed to `timing.funding_cost_multiplier` (0.8). The old key is still read as a fallback for one release.
- Docs: mcp-servers.md, risk-and-execution.md and the carry row in small-capacity-edges.md updated; study cited in repo-evaluation.md and NOTICE.

### Added
- `timing.funding_gate_mode`: `"cost_risk"` (default, same sizing as before) or `"off"`.
- `orderflow.crosses_settlement`: when `false` (the hold closes before the next funding print), the funding dampener is skipped with an "ignored" warning.
- Tests: both funding directions, settlement skip, off switch, warning wording, threshold boundary, legacy key fallback, cascade stacking and the size floor, and a doc check for leftover "crowded funding" wording; trading-execution checks its own limits file.
