#!/usr/bin/env python3
"""Screen many rule variants for real edge: week-clustered t-stats, in/out-of-sample
split by date, Benjamini-Hochberg false discovery control. Stdlib only.

Input CSV (one row per trade): rule,date,excess
  rule    variant name (e.g. dip_2sd_20d_h10)
  date    entry date YYYY-MM-DD
  excess  trade return in its direction MINUS the symbol's ordinary return over the
          same holding period MINUS round-trip costs (log or simple, be consistent)

Usage: rule_screen.py --trades trades.csv [--split 0.7] [--fdr 0.10]
                      [--min-is 30] [--min-oos 10] [--oos-t 1.0] [--tried N]
Prints JSON: per rule IS/OOS trades, weeks, mean, t, p, BH flag and a verdict
(APPROVED | FAILED_OOS | NOT_SIGNIFICANT | TOO_FEW_TRADES).
"""
import argparse, csv, json, math, sys
from collections import defaultdict
from datetime import date


def norm_sf(x):
    return 0.5 * math.erfc(x / math.sqrt(2))


def week_key(d):
    y, w, _ = d.isocalendar()
    return (y, w)


def clustered_t(rows):
    """Average excess per entry week, then t over weeks (same-week trades are one bet)."""
    by_week = defaultdict(list)
    for d, x in rows:
        by_week[week_key(d)].append(x)
    means = [sum(v) / len(v) for v in by_week.values()]
    n = len(means)
    if n < 2:
        return n, (means[0] if means else 0.0), 0.0
    m = sum(means) / n
    var = sum((v - m) ** 2 for v in means) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    return n, m, (m / se if se > 0 else 0.0)


def bh(pvals, q):
    """Benjamini-Hochberg: return set of indices that are discoveries at FDR q."""
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m, cut = len(pvals), -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / m:
            cut = rank
    return set(order[:cut]) if cut > 0 else set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--split", type=float, default=0.7, help="in-sample share of the date range")
    ap.add_argument("--fdr", type=float, default=0.10)
    ap.add_argument("--min-is", type=int, default=30)
    ap.add_argument("--min-oos", type=int, default=10)
    ap.add_argument("--oos-t", type=float, default=1.0)
    ap.add_argument("--tried", type=int, default=0,
                    help="variants tried in total, including ones with no trades (BH and Bonferroni count them all)")
    a = ap.parse_args()

    trades = defaultdict(list)
    with open(a.trades, newline="") as fh:
        for r in csv.DictReader(fh):
            trades[r["rule"]].append((date.fromisoformat(r["date"][:10]), float(r["excess"])))
    if not trades:
        sys.exit("no trades in input")
    alld = sorted(d for v in trades.values() for d, _ in v)
    cutoff = alld[min(len(alld) - 1, int(len(alld) * a.split))]

    rules = sorted(trades)
    stats = []
    for name in rules:
        ins = [t for t in trades[name] if t[0] < cutoff]
        oos = [t for t in trades[name] if t[0] >= cutoff]
        w_is, m_is, t_is = clustered_t(ins)
        w_oos, m_oos, t_oos = clustered_t(oos)
        stats.append(dict(rule=name, is_trades=len(ins), is_weeks=w_is, is_mean=m_is, is_t=t_is,
                          is_p=norm_sf(t_is), oos_trades=len(oos), oos_weeks=w_oos,
                          oos_mean=m_oos, oos_t=t_oos))
    m = max(len(stats), a.tried)
    disc = bh([s["is_p"] for s in stats] + [1.0] * (m - len(stats)), a.fdr)
    bonf_t = -1 * (math.sqrt(2) * _erfcinv(2 * (0.05 / m))) if m else 0.0
    for i, s in enumerate(stats):
        s["bh_discovery"] = i in disc
        if s["is_trades"] < a.min_is or s["oos_trades"] < a.min_oos:
            v = "TOO_FEW_TRADES"
        elif not s["bh_discovery"]:
            v = "NOT_SIGNIFICANT"
        elif s["oos_mean"] > 0 and s["oos_t"] >= a.oos_t:
            v = "APPROVED"
        else:
            v = "FAILED_OOS"
        s["verdict"] = v
        for k in ("is_mean", "is_t", "is_p", "oos_mean", "oos_t"):
            s[k] = round(s[k], 6)
    out = dict(variants=m, cutoff=cutoff.isoformat(), fdr=a.fdr, bonferroni_t_5pct=round(abs(bonf_t), 3),
               approved=[s["rule"] for s in stats if s["verdict"] == "APPROVED"], rules=stats,
               notes=["Every variant you tried must be in the file, including the ones you dropped.",
                      "p-values are one-sided normal approximations on week-clustered means.",
                      "APPROVED means 'survived this screen', not 'will pay'. Paper-trade it next."])
    print(json.dumps(out, indent=2))


def _erfcinv(y):
    # inverse of erfc via bisection (stdlib only); y in (0, 2)
    lo, hi = -6.0, 6.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if math.erfc(mid) > y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == "__main__":
    main()
