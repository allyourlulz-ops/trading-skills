#!/usr/bin/env python3
"""Allocation drift, rebalance trades, DCA plan and ETF look-through exposure. Stdlib only.
Usage: rebalance.py --holdings h.json --targets t.json [--band 5] [--cash 0] [--dca 500 --dca-periods 4]
                    [--lookthrough etf.json] [--min-trade 25]
h.json: {"VOO":{"qty":10,"price":540},"AAPL":{"qty":20,"price":190},"CASH":{"value":800}}
t.json: {"VOO":0.6,"AAPL":0.1,"BND":0.25,"CASH":0.05}   (weights sum to 1; prices for new names via "prices")
etf.json: {"VOO":{"AAPL":0.07,"MSFT":0.065,"NVDA":0.07}}  top holdings by weight, from the data MCP server
Prints JSON: weights, drift, trades only for names outside the band (or all with --band 0),
a DCA schedule that fixes underweights with new money before selling anything, and
true single-name exposure when look-through data is given.
"""
import argparse, json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdings", required=True)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--band", type=float, default=5.0, help="absolute drift in percentage points before trading")
    ap.add_argument("--cash", type=float, default=0.0, help="new cash to add now")
    ap.add_argument("--dca", type=float, default=0.0, help="new money per period")
    ap.add_argument("--dca-periods", type=int, default=0)
    ap.add_argument("--lookthrough")
    ap.add_argument("--min-trade", type=float, default=25.0)
    ap.add_argument("--max-single", type=float, default=30.0, help="concentration warning, percent of total in one asset")
    a = ap.parse_args()
    H, T = json.load(open(a.holdings)), json.load(open(a.targets))
    prices = T.pop("prices", {})
    if abs(sum(T.values()) - 1) > 1e-6:
        raise SystemExit(f"target weights sum to {sum(T.values()):.4f}, not 1")
    val = {k: (v["value"] if "value" in v else v["qty"] * v["price"]) for k, v in H.items()}
    val["CASH"] = val.get("CASH", 0) + a.cash
    total = sum(val.values())
    names = sorted(set(val) | set(T))
    w = {k: val.get(k, 0) / total for k in names}
    drift = {k: round(100 * (w[k] - T.get(k, 0)), 2) for k in names}
    px = {k: H[k]["price"] for k in H if "price" in H[k]} | prices
    trades = []
    for k in names:
        if k == "CASH" or abs(drift[k]) < a.band:
            continue
        usd = (T.get(k, 0) - w[k]) * total
        if abs(usd) < a.min_trade:
            continue
        t = dict(symbol=k, side="buy" if usd > 0 else "sell", usd=round(abs(usd), 2))
        if k in px:
            t["qty"] = int(abs(usd) // px[k]) if px[k] else None
        trades.append(t)
    plan = []
    if a.dca and a.dca_periods:
        v2 = dict(val)
        for i in range(a.dca_periods):
            tot = sum(v2.values()) + a.dca
            gaps = {k: max(0.0, T.get(k, 0) * tot - v2.get(k, 0)) for k in T if k != "CASH"}
            g = sum(gaps.values())
            alloc = {k: round(a.dca * gaps[k] / g, 2) for k in gaps if gaps[k] > 0} if g else {}
            for k, x in alloc.items():
                v2[k] = v2.get(k, 0) + x
            v2["CASH"] = v2.get("CASH", 0) + (0 if g else a.dca)
            plan.append(dict(period=i + 1, buys=alloc))
    expo = None
    if a.lookthrough:
        L = json.load(open(a.lookthrough))
        expo = {}
        for k in names:
            if k in L:
                for s, x in L[k].items():
                    expo[s] = expo.get(s, 0) + w[k] * x
            elif k != "CASH":
                expo[k] = expo.get(k, 0) + w[k]
        expo = {k: round(100 * v, 2) for k, v in sorted(expo.items(), key=lambda kv: -kv[1])[:15]}
    conc = [f"{k} is {100 * w[k]:.1f}% of the portfolio (limit {a.max_single:g}%)" for k in names
            if k != "CASH" and 100 * w[k] > a.max_single]
    if expo:
        conc += [f"{k} is {v}% after ETF look-through (limit {a.max_single:g}%)" for k, v in expo.items()
                 if v > a.max_single and 100 * w.get(k, 0) <= a.max_single]
    out = dict(concentration_warnings=conc, total_value=round(total, 2), weights_pct={k: round(100 * w[k], 2) for k in names},
               target_pct={k: round(100 * T.get(k, 0), 2) for k in names}, drift_pts=drift, band_pts=a.band,
               trades=trades, dca_plan=plan, lookthrough_exposure_pct=expo,
               notes=["Prefer fixing drift with new money (dca_plan) over selling: fewer taxable events.",
                      "Each trade still goes through risk_check.py and the user's yes (or an AUTO_OK from a signed mandate).",
                      "Look-through covers only the ETF holdings you supplied (usually the top 10-25)."])
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
