#!/usr/bin/env python3
"""Per-strategy kill switch: is a paper or live strategy still alive? Stdlib only, no network.

Usage:
  strategy_health.py --equity strat_equity.csv [--fills fills.csv] [--limits risk-limits.json]
                     [--expected-sharpe 0.8] [--periods 252] [--currency USD]
strat_equity.csv  date,value: this strategy's own paper or live equity (one sleeve, not the account)
fills.csv         date,side,expected_price,fill_price,qty: expected = the price the strategy decided on
                  (signal close or limit), fill = the broker's fill. Slippage is signed against you.
limits: "strategy_kill" in risk-limits.json, defaults
  {"max_dd_pct": 15, "under_water_days": 90, "slippage_budget_bps": 25, "min_days": 63}
Verdict:
  RETIRE  drawdown from peak beyond max_dd_pct, or under water longer than under_water_days, or average
          slippage above slippage_budget_bps (the costs the backtest assumed are not the costs you pay)
  WATCH   fewer than min_days of record, or live Sharpe below half of --expected-sharpe
  KEEP    otherwise
The account-level loss limits in risk_check.py still apply; this retires one strategy that has stopped
working before it drags the account to those limits. A retired strategy goes back to research, and
restarting it needs a fresh pipeline.py verdict.
"""
import argparse, csv, json, math, statistics as S

DEF = {"max_dd_pct": 15, "under_water_days": 90, "slippage_budget_bps": 25, "min_days": 63}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--equity", required=True); ap.add_argument("--fills"); ap.add_argument("--limits")
    ap.add_argument("--expected-sharpe", type=float); ap.add_argument("--periods", type=int, default=252)
    ap.add_argument("--currency", default="USD")
    a = ap.parse_args()
    L = dict(DEF, **(json.load(open(a.limits)).get("strategy_kill", {}) if a.limits else {}))
    eq = [(r["date"], float(r["value"])) for r in csv.DictReader(open(a.equity, newline="")) if r.get("value")]
    if len(eq) < 2:
        raise SystemExit("need at least 2 equity rows")
    peak, mdd, uw, uw_max = eq[0][1], 0.0, 0, 0
    for _, v in eq:
        if v >= peak:
            peak, uw = v, 0
        else:
            uw += 1
        mdd = min(mdd, v / peak - 1); uw_max = max(uw_max, uw)
    cur_dd = eq[-1][1] / peak - 1
    rets = [eq[i][1] / eq[i - 1][1] - 1 for i in range(1, len(eq)) if eq[i - 1][1]]
    sd = S.stdev(rets) if len(rets) > 1 else 0
    sharpe = S.mean(rets) / sd * math.sqrt(a.periods) if sd else 0.0
    slip = None
    if a.fills:
        num = den = 0.0
        for r in csv.DictReader(open(a.fills, newline="")):
            e, fpx, q = float(r["expected_price"]), float(r["fill_price"]), abs(float(r["qty"]))
            sign = 1 if str(r["side"]).lower() in ("buy", "long", "cover") else -1
            num += sign * (fpx - e) / e * 1e4 * e * q; den += e * q
        slip = num / den if den else None
    retire, watch = [], []
    if -mdd * 100 > L["max_dd_pct"]:
        retire.append(f"drawdown {mdd:.1%} beyond {L['max_dd_pct']}%")
    if uw > L["under_water_days"]:
        retire.append(f"under water {uw} days (limit {L['under_water_days']})")
    if slip is not None and slip > L["slippage_budget_bps"]:
        retire.append(f"average slippage {slip:.1f} bps over budget {L['slippage_budget_bps']}")
    if len(rets) < L["min_days"]:
        watch.append(f"only {len(rets)} days of record (min {L['min_days']})")
    if a.expected_sharpe and sharpe < a.expected_sharpe / 2:
        watch.append(f"live Sharpe {sharpe:.2f} below half the expected {a.expected_sharpe}")
    print(json.dumps({"verdict": "RETIRE" if retire else "WATCH" if watch else "KEEP", "retire": retire, "watch": watch,
                      "days": len(rets), "max_drawdown": round(mdd, 4), "current_drawdown": round(cur_dd, 4),
                      "under_water_days_now": uw, "under_water_days_max": uw_max, "sharpe": round(sharpe, 2),
                      "avg_slippage_bps": round(slip, 1) if slip is not None else None,
                      "limits": L, "currency": a.currency}, indent=1))


if __name__ == "__main__":
    main()
