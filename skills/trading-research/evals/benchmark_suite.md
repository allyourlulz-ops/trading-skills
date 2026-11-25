# Positive-control benchmark suite

Every test strategy used to be one that should fail, so nobody could tell whether the bar was calibrated or merely brutal. These fixtures have known answers. `python3 evals/run_tests.py` builds each one on synthetic data (9 years, 2,268 days, benchmark at exactly 13% a year and 18% volatility) and runs it through `scripts/pipeline.py` with a 5-trial ledger, PBO variants, factors, positions and look-ahead and permutation results.

| Fixture | Must produce | What a wrong answer means |
| --- | --- | --- |
| Pure noise, turnover 5% a day | NOT_READY, deflated Sharpe < 0.5 | Gates pass noise: everything downstream is noise |
| Strong premium (8% a year, 5% volatility, Sharpe about 1.6) at **3× costs** | READY_FOR_PAPER | Gates too harsh: nothing real can ever pass |
| Same premium with a look-ahead LEAK result | NOT_READY (hard reason: lookahead) | Leaks get through |
| Long-only SPY clone | attribution BETA_OR_STYLE, not READY_FOR_PAPER | Beta is sold as skill |
| Market-neutral Sharpe 1.6, 8% a year, at 1× costs | READY_FOR_PAPER **without** beating SPY's total return | The objective is wrong for hedged sleeves |

Also in run_tests.py: `lookahead_check.py` catches a rule that reads tomorrow's close and a two-sided smoother (tests 6 and 7); `monkey_test.py --mode beta_matched` calls random long-only picks in a rising market LUCK (test 23); `discover.py` finds a planted post-event drift and rejects a planted no-effect event (test 25).

If any fixture lands wrong, the gate is miscalibrated: fix it before trusting any verdict, and add the failing case here.
