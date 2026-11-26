# Changelog

Earlier releases are summarised, with their sources, in NOTICE.

## 2.2.0-dev (unreleased): Phase 1, trust boundary

Both skills move to 2.2.0-dev. Register IDs are from the hardening plan; P-numbers are the Phase 0
provisional findings in docs/AUDIT.md. Tests: `skills/trading-execution/evals/trust_tests.py`.

### Fixed
- T1 (P9): `asset_class` is derived from the instrument spec and the symbol's shape (OCC option symbol, BASE/QUOTE crypto pair, exchange ticker), not taken from the order's label. Order/spec disagreement, an option symbol labelled equity, a ticker labelled crypto or option, an `etf` label without a spec saying etf, and a non-option with multiplier 100 each fail HARD with `ASSET_CLASS`. `position_size.py --asset-class` is now optional and checked the same way. Tests `T1_*`.

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
