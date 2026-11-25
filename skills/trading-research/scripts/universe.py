#!/usr/bin/env python3
"""Point-in-time universe: top N names by 20-day average dollar volume, recomputed each rebalance date,
from a panel that includes delisted names. Stdlib only, no network.

Usage:
  universe.py --panel panel.csv [--top 1000] [--every 21] [--min-price 5] [--min-names 100]
              [--out PREFIX]
panel.csv: long format, date,symbol,close,volume, one row per symbol per trading day, INCLUDING names
  that were later delisted, merged or renamed (from the MCP price and filings tools; see
  references/backtesting.md, Universe). Unadjusted close is fine for ranking by dollar volume.
On each rebalance date d the ranking uses only rows before d (no look-ahead), keeps names with a close
of at least --min-price and 20 trading days of data, and takes the top --top by average close x volume.
Writes PREFIX_members.csv (date,symbol for premia_signals.py --universe), PREFIX_closes.csv and
PREFIX_volumes.csv (wide, blank where a name did not trade) and prints a JSON report.
Verdicts:
  OK                    every rebalance date has at least --min-names members and some names leave the panel
  TOO_NARROW            a date has fewer than --min-names: no cross-sectional signal may be judged on it
  SURVIVORSHIP_SUSPECT  no name ends before the panel's last date: the source probably dropped dead names,
                        so results are biased upward; find a source with delisted names or say so plainly
"""
import argparse, csv, json, statistics as S, sys
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", required=True); ap.add_argument("--top", type=int, default=1000)
    ap.add_argument("--every", type=int, default=21); ap.add_argument("--min-price", type=float, default=5)
    ap.add_argument("--min-names", type=int, default=100); ap.add_argument("--out", default="universe")
    a = ap.parse_args()
    px, vol, last = defaultdict(dict), defaultdict(dict), {}
    for r in csv.DictReader(open(a.panel, newline="")):
        try:
            d, s, c, v = r["date"][:10], r["symbol"], float(r["close"]), float(r["volume"] or 0)
        except (KeyError, ValueError):
            continue
        px[d][s], vol[d][s] = c, v
        last[s] = max(last.get(s, ""), d)
    dates = sorted(px)
    if len(dates) < 25:
        sys.exit("need at least 25 trading days")
    syms = sorted(last)
    hist = defaultdict(list)  # symbol -> list of (close*volume) for the trailing 20 days
    members, sizes = [], []
    for i, d in enumerate(dates):
        if i >= 20 and (i - 20) % a.every == 0:
            prev = dates[i - 1]
            cand = []
            for s, dv in hist.items():
                recent = dv[-20:]
                if len(recent) == 20 and recent[-1][0] == prev and px[prev].get(s, 0) >= a.min_price:
                    cand.append((sum(x for _, x in recent) / 20, s))
            cand.sort(reverse=True)
            pick = [s for _, s in cand[:a.top]]
            members += [[d, s] for s in sorted(pick)]
            sizes.append((d, len(pick)))
        for s, c in px[d].items():
            hist[s].append((d, c * vol[d].get(s, 0)))
            if len(hist[s]) > 40:
                hist[s] = hist[s][-20:]
    with open(a.out + "_members.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "symbol"]); w.writerows(members)
    for name, src in (("closes", px), ("volumes", vol)):
        with open(f"{a.out}_{name}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["date"] + syms)
            for d in dates:
                w.writerow([d] + [src[d].get(s, "") for s in syms])
    gone = [s for s in syms if last[s] < dates[-1]]
    n = [k for _, k in sizes]
    verdict = "TOO_NARROW" if not n or min(n) < a.min_names else "SURVIVORSHIP_SUSPECT" if not gone else "OK"
    print(json.dumps({"verdict": verdict, "rebalance_dates": len(sizes), "symbols_in_panel": len(syms),
                      "members_min": min(n) if n else 0, "members_median": S.median(n) if n else 0,
                      "names_that_left_panel": len(gone), "first": dates[0], "last": dates[-1],
                      "min_names": a.min_names, "top": a.top,
                      "outputs": [a.out + "_members.csv", a.out + "_closes.csv", a.out + "_volumes.csv"],
                      "note": "rank uses rows before each rebalance date only; delisted names must be in the panel"}, indent=1))
    sys.exit(0)


if __name__ == "__main__":
    main()
