#!/usr/bin/env python3
"""One cost model for every backtest: gross period returns in, net returns out, each cost a separate line.
Adds market impact, a cost ladder, a cost-multiple stress test and a capacity curve. Stdlib only, no network.

Usage:
  costs.py --returns gross.csv [--costs costs.json] [--periods 252] [--currency USD] [--out net]
           [--ladder 5,10,20,40] [--capacity 1,10,100,1000,10000]
gross.csv  date,ret,turnover[,short][,trades][,borrow_bps_yr][,adv_frac][,sigma]
  ret            gross portfolio return for the period (decimal)
  turnover       one-way fraction of capital traded that period (0.5 = half the book changed hands,
                 i.e. 0.5 sold and 0.5 bought); per-trade costs are charged on 2 x turnover
  short          fraction of capital held short that period (borrow cost), default 0
  trades         number of orders that period (fixed per-order fees), default 0
  borrow_bps_yr  this period's weighted borrow fee on the short book (from your broker's locate list);
                 overrides the flat borrow_bps_yr in costs.json
  adv_frac       average order size / 20-day average daily volume, at costs.json "capital"
  sigma          daily volatility of the names traded (decimal)
costs.json (all optional; defaults are for a liquid US ETF account and should be replaced with yours):
  {"commission_bps": 0, "per_order": 0.0, "spread_bps": 2, "slippage_bps": 3, "borrow_bps_yr": 50,
   "funding_bps_yr": 0, "capital": 10000, "impact_k": 1.0, "adv_cap_pct": 1, "require_survives_cost_x": 3}
  spread_bps is the full quoted spread; half is paid per one-way trade. funding_bps_yr applies to
  gross exposure above 100% (margin) or to perpetual-futures funding you pass in as a flat rate.
Market impact (square-root law: Almgren, Thum, Hauptmann and Li 2005; Toth et al. 2011), charged per
one-way turnover when adv_frac and sigma are given:  impact = impact_k * sigma * sqrt(adv_frac).
At sigma 1.5% and k 1: 0.1% of ADV costs 4.7 bps, 1% costs 15 bps, 5% costs 34 bps. k is an
order-one constant; fit it to your own fills (expected vs filled price) once you have 30 or more.
Stress tests printed with the result:
  cost_multiples  net return and Sharpe with every trading and borrow cost x1, x2, x3; a strategy
                  should stay above zero at require_survives_cost_x (default 3)
  cost_ladder     net return and Sharpe at flat one-way costs (bps) instead of the modelled ones
  capacity        the same strategy at capital x1, x10, ... (adv_frac scales with capital, so impact
                  grows with its square root); shows where the edge dies. Periods where adv_frac would
                  pass adv_cap_pct are counted: those orders would only part-fill in one day. To
                  simulate the part-fills themselves, use premia_signals.py --volumes.
Writes <out>.csv (date,ret) and <out>_equity.csv (date,value from 1.0) for validate_backtest.py,
and prints JSON with gross and net annual return and each cost line in bps a year.
"""
import argparse, csv, json, math, statistics as S

DEF = {"commission_bps": 0, "per_order": 0.0, "spread_bps": 2, "slippage_bps": 3, "borrow_bps_yr": 50,
       "funding_bps_yr": 0, "capital": 10000, "gross_exposure": 1.0, "impact_k": 1.0, "adv_cap_pct": 1,
       "require_survives_cost_x": 3}
NAMES = ("commission", "spread", "slippage", "impact", "per_order", "borrow", "funding")


def f(r, k, d=0.0):
    v = r.get(k)
    return float(v) if v not in (None, "", "NA") else d


def period_costs(r, c, periods, mult=1.0, cap_mult=1.0, flat_bps=None):
    # one-way turnover counts each round trip once; a round trip is two trades (sell one name, buy
    # another), so every per-trade cost is charged on 2 x turnover. (v1.16.0 charged 1 x: half.)
    tv, sh, tr = 2 * f(r, "turnover"), f(r, "short"), f(r, "trades")
    adv, sig = f(r, "adv_frac") * cap_mult, f(r, "sigma")
    borrow = f(r, "borrow_bps_yr", c["borrow_bps_yr"])
    if flat_bps is not None:
        k = {"commission": 0.0, "spread": 0.0, "slippage": tv * flat_bps / 1e4, "impact": 0.0}
    else:
        k = {"commission": tv * c["commission_bps"] / 1e4, "spread": tv * c["spread_bps"] / 2 / 1e4,
             "slippage": tv * c["slippage_bps"] / 1e4,
             "impact": tv * c["impact_k"] * sig * math.sqrt(adv) if adv > 0 and sig > 0 else 0.0}
    k["per_order"] = tr * c["per_order"] / (c["capital"] * cap_mult)
    k["borrow"] = sh * borrow / 1e4 / periods
    k["funding"] = max(0.0, c["gross_exposure"] - 1) * c["funding_bps_yr"] / 1e4 / periods
    return {n: v * mult for n, v in k.items()}


def summary(net, periods):
    yrs = len(net) / periods or 1
    cagr = math.exp(sum(math.log1p(max(x, -0.999999)) for x in net) / yrs) - 1
    sd = S.stdev(net) if len(net) > 1 else 0
    return {"net_annual_return": round(cagr, 4), "net_sharpe": round(S.mean(net) / sd * math.sqrt(periods), 3) if sd else 0.0}


def run(rows, c, periods, **kw):
    return [f(r, "ret") - sum(period_costs(r, c, periods, **kw).values()) for r in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--returns", required=True); ap.add_argument("--costs")
    ap.add_argument("--periods", type=int, default=252); ap.add_argument("--currency", default="USD")
    ap.add_argument("--out", default="net")
    ap.add_argument("--ladder", default="5,10,20,40", help="flat one-way cost levels in bps")
    ap.add_argument("--capacity", default="1,10,100,1000,10000", help="capital multiples to test")
    a = ap.parse_args()
    c = dict(DEF, **(json.load(open(a.costs)) if a.costs else {}))
    rows = list(csv.DictReader(open(a.returns, newline="")))
    lines = dict.fromkeys(NAMES, 0.0)
    net, g_all = [], []
    for r in rows:
        k = period_costs(r, c, a.periods)
        for n, v in k.items():
            lines[n] += v
        net.append((r["date"], f(r, "ret") - sum(k.values()))); g_all.append(f(r, "ret"))
    with open(a.out + ".csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "ret"]); w.writerows((d, round(x, 8)) for d, x in net)
    with open(a.out + "_equity.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "value"]); v = 1.0
        for d, x in net:
            v *= 1 + x; w.writerow([d, round(v, 8)])
    yrs = len(rows) / a.periods or 1
    cagr = lambda rs: math.exp(sum(math.log1p(x) for x in rs) / yrs) - 1
    mults = {f"x{m}": summary(run(rows, c, a.periods, mult=m), a.periods) for m in (1, 2, 3)}
    need = int(c["require_survives_cost_x"])
    survived = max([m for m in (1, 2, 3) if mults[f"x{m}"]["net_annual_return"] > 0 and mults[f"x{m}"]["net_sharpe"] > 0] or [0])
    stress_need = summary(run(rows, c, a.periods, mult=need), a.periods)
    ladder = {f"{b}bps": summary(run(rows, c, a.periods, flat_bps=float(b)), a.periods) for b in a.ladder.split(",") if b.strip()}
    has_adv = any(f(r, "adv_frac") > 0 for r in rows)
    cap = []
    for m in [float(x) for x in a.capacity.split(",") if x.strip()]:
        s = summary(run(rows, c, a.periods, cap_mult=m), a.periods)
        s["capital"] = {"value": round(c["capital"] * m, 2), "currency": a.currency}
        s["periods_over_adv_cap"] = sum(1 for r in rows if f(r, "adv_frac") * m * 100 > c["adv_cap_pct"])
        cap.append(s)
    out = {"periods": len(rows), "years": round(yrs, 2), "currency": a.currency,
           "gross_annual_return": round(cagr(g_all), 4), "net_annual_return": round(cagr([x for _, x in net]), 4),
           "cost_lines_bps_per_year": {n: round(v / yrs * 1e4, 1) for n, v in lines.items()},
           "avg_one_way_turnover_per_year": round(sum(f(r, "turnover") for r in rows) / yrs, 2),
           "cost_multiples": mults, "survives_cost_x": survived, "required_cost_x": need,
           "survives_required": stress_need["net_annual_return"] > 0 and stress_need["net_sharpe"] > 0,
           "cost_ladder_one_way": ladder,
           "capacity": cap if has_adv else "no adv_frac column: impact and capacity not modelled",
           "assumptions": c, "outputs": [a.out + ".csv", a.out + "_equity.csv"]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
