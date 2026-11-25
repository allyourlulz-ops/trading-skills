#!/usr/bin/env python3
"""One cost model for every backtest: gross period returns in, net returns out, each cost a separate line.
Stdlib only, no network.

Usage:
  costs.py --returns gross.csv [--costs costs.json] [--periods 252] [--currency USD] [--out net]
gross.csv  date,ret,turnover[,short][,trades]
  ret       gross portfolio return for the period (decimal)
  turnover  one-way fraction of capital traded that period (0.5 = half the book changed hands)
  short     fraction of capital held short that period (borrow cost), default 0
  trades    number of orders that period (fixed per-order fees), default 0
costs.json (all optional; defaults are for a liquid US ETF account and should be replaced with yours):
  {"commission_bps": 0, "per_order": 0.0, "spread_bps": 2, "slippage_bps": 3,
   "borrow_bps_yr": 50, "funding_bps_yr": 0, "capital": 10000}
  spread_bps is the full quoted spread; half is paid per one-way trade. funding_bps_yr applies to
  gross exposure above 100% (margin) or to perpetual-futures funding you pass in as a flat rate.
Writes <out>.csv (date,ret) and <out>_equity.csv (date,value from 1.0) for validate_backtest.py,
and prints JSON with gross and net annual return and each cost line in bps a year.
"""
import argparse, csv, json, math, statistics as S

DEF = {"commission_bps": 0, "per_order": 0.0, "spread_bps": 2, "slippage_bps": 3,
       "borrow_bps_yr": 50, "funding_bps_yr": 0, "capital": 10000, "gross_exposure": 1.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--returns", required=True); ap.add_argument("--costs")
    ap.add_argument("--periods", type=int, default=252); ap.add_argument("--currency", default="USD")
    ap.add_argument("--out", default="net")
    a = ap.parse_args()
    c = dict(DEF, **(json.load(open(a.costs)) if a.costs else {}))
    rows = list(csv.DictReader(open(a.returns, newline="")))
    lines = {"commission": 0.0, "spread": 0.0, "slippage": 0.0, "per_order": 0.0, "borrow": 0.0, "funding": 0.0}
    net, g_all = [], []
    for r in rows:
        g, tv = float(r["ret"]), float(r.get("turnover") or 0)
        sh, tr = float(r.get("short") or 0), float(r.get("trades") or 0)
        k = {"commission": tv * c["commission_bps"] / 1e4, "spread": tv * c["spread_bps"] / 2 / 1e4,
             "slippage": tv * c["slippage_bps"] / 1e4, "per_order": tr * c["per_order"] / c["capital"],
             "borrow": sh * c["borrow_bps_yr"] / 1e4 / a.periods,
             "funding": max(0.0, c["gross_exposure"] - 1) * c["funding_bps_yr"] / 1e4 / a.periods}
        for n, v in k.items():
            lines[n] += v
        net.append((r["date"], g - sum(k.values()))); g_all.append(g)
    with open(a.out + ".csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "ret"]); w.writerows((d, round(x, 8)) for d, x in net)
    with open(a.out + "_equity.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "value"]); v = 1.0
        for d, x in net:
            v *= 1 + x; w.writerow([d, round(v, 8)])
    yrs = len(rows) / a.periods or 1
    cagr = lambda rs: math.exp(sum(math.log1p(x) for x in rs) / yrs) - 1
    print(json.dumps({"periods": len(rows), "years": round(yrs, 2), "currency": a.currency,
                      "gross_annual_return": round(cagr(g_all), 4), "net_annual_return": round(cagr([x for _, x in net]), 4),
                      "cost_lines_bps_per_year": {n: round(v / yrs * 1e4, 1) for n, v in lines.items()},
                      "avg_one_way_turnover_per_year": round(sum(float(r.get("turnover") or 0) for r in rows) / yrs, 2),
                      "assumptions": c, "outputs": [a.out + ".csv", a.out + "_equity.csv"]}, indent=1))


if __name__ == "__main__":
    main()
