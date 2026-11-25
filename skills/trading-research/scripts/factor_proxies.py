#!/usr/bin/env python3
"""Build factors.csv for attribution.py from independent ETF proxies. Stdlib only, no network.

Usage:
  factor_proxies.py --prices proxies.csv [--market SPY] [--map size=IWM,momentum=MTUM,low_vol=USMV,quality=QUAL,value=VLUE]
                    [--out factors.csv]
proxies.csv: wide daily closes, date,SPY,IWM,MTUM,USMV,QUAL,VLUE (from MCP price tools; the user's own
fetch). Output: date,mkt,<style>... where mkt = market return and each style = proxy return minus
market return (a long-proxy, short-market spread). Proxies missing from the file are skipped.

Why: factors built from the strategy's own universe on its own rebalance day share its noise, so the
regression credits noise to "style" and the rebalance day leaves a day-of-week pattern. Proxies run by
someone else, on their own schedule, are independent of the strategy. They are rough: an ETF spread
is not a pure long-short factor, and the ETFs only start in 2013 (MTUM, USMV, QUAL, VLUE). Name the
proxies in the result.
"""
import argparse, csv, json, sys

DEFAULT = "size=IWM,momentum=MTUM,low_vol=USMV,quality=QUAL,value=VLUE"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", required=True); ap.add_argument("--market", default="SPY")
    ap.add_argument("--map", default=DEFAULT); ap.add_argument("--out", default="factors.csv")
    a = ap.parse_args()
    rows = list(csv.reader(open(a.prices, newline="")))
    head = rows[0]; idx = {s: i for i, s in enumerate(head)}
    if a.market not in idx:
        sys.exit(f"no {a.market} column")
    styles = [(n, p) for n, p in (kv.split("=") for kv in a.map.split(",")) if p in idx]
    skipped = [kv for kv in a.map.split(",") if kv.split("=")[1] not in idx]
    out, prev = [], None
    for r in rows[1:]:
        try:
            cur = {s: float(r[idx[s]]) for s in [a.market] + [p for _, p in styles]}
        except (ValueError, IndexError):
            prev = None; continue
        if prev:
            m = cur[a.market] / prev[a.market] - 1
            out.append([r[0], round(m, 8)] + [round(cur[p] / prev[p] - 1 - m, 8) for _, p in styles])
        prev = cur
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "mkt"] + [n for n, _ in styles]); w.writerows(out)
    print(json.dumps({"rows": len(out), "market": a.market, "styles": dict(styles), "skipped": skipped,
                      "out": a.out, "first": out[0][0] if out else None, "last": out[-1][0] if out else None}, indent=1))


if __name__ == "__main__":
    main()
