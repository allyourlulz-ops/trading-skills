#!/usr/bin/env python3
"""Coin-flip edge test: did the direction calls beat chance, given the same trades? Stdlib only.

Usage:
  monkey_test.py --positions positions.csv [--monkeys 2048] [--group position|day]
                 [--bar 1] [--seed 7] [--currency USD]
  monkey_test.py --mode beta_matched --weights weights.csv --prices closes.csv [--monkeys 2048] [--bar 1]

positions.csv, one row per position from flat to flat (broker or paper fills rolled up):
  id,open_time,side,pnl[,fees]
  open_time  ISO date or datetime (the first 10 characters are the day)
  side       long|short (or 1|-1)
  pnl        result of the position BEFORE fees: realised P&L + funding + mark-to-close if still open
  fees       optional; reported only, because a monkey pays the same fees

Each monkey keeps every position at the same moments and sizes and flips a fair coin for the side;
the opposite side earns the opposite result. --group day gives all positions opened on one day a
single coin (a day's trades are usually one bet). Verdict, at bar k (default 1):
  EDGE       the actual result beats all but at most k monkeys
  ANTI_EDGE  it loses to all but at most k monkeys (the calls were reliably wrong)
  LUCK       anything in between: cannot be told from chance at this sample size
LUCK is not proof of no skill; short samples and few groups rarely clear the bar.
What it tests: direction only. Timing and sizing are held fixed. A long-only strategy in a rising
market scores HIGH (a monkey goes short half the time), so a high percentile can be pure beta:
always pair it with attribution.py. (Found on the real-data run, examples/real-data-run.md.) Run it on paper results before any stage advance.

--mode beta_matched (selection test): weights.csv is date,symbol,weight at each rebalance (from
premia_signals.py --backtest). Each monkey keeps the same weights on the same dates, so the same
number of names, the same gross and net exposure and the same long/short split, and draws WHICH names
at random from those trading on both dates. Beta and timing are held fixed; only selection varies.
A long-only fund in a rising market no longer scores high just for being long.

Method: per-position coin-flip test as published by oaia.fun for Alpha Arena (2026-11-06 and
2026-11-10); this is own code, no code from that site is used.
"""
import argparse, csv, json, random, sys
from collections import defaultdict


def load(path):
    rows = list(csv.DictReader(open(path, newline="")))
    if not rows:
        sys.exit("no positions in file")
    out = []
    for i, r in enumerate(rows, 1):
        try:
            s = str(r.get("side", "")).strip().lower()
            side = 1 if s in ("long", "1", "+1", "buy") else -1 if s in ("short", "-1", "sell") else None
            if side is None:
                raise ValueError(f"side {r.get('side')!r}")
            out.append({"id": r.get("id") or str(i), "day": (r.get("open_time") or "")[:10],
                        "side": side, "pnl": float(r["pnl"]), "fees": float(r.get("fees") or 0)})
        except (KeyError, ValueError) as e:
            sys.exit(f"row {i}: {e}")
    return out


def verdict_of(actual, sims, bar):
    ge = sum(1 for x in sims if x >= actual); le = sum(1 for x in sims if x <= actual)
    below = sum(1 for x in sims if x < actual)
    pct = 100.0 * (below + 0.5 * (len(sims) - below - (len(sims) - le))) / len(sims)
    return ("EDGE" if ge <= bar else "ANTI_EDGE" if le <= bar else "LUCK"), pct, ge


def beta_matched(a):
    import math
    rows = list(csv.reader(open(a.prices, newline="")))
    syms = rows[0][1:]
    px = {r[0][:10]: {s: float(x) for s, x in zip(syms, r[1:]) if x not in ("", "NA")} for r in rows[1:] if r}
    dates = sorted(px)
    W = defaultdict(dict)
    for r in csv.DictReader(open(a.weights, newline="")):
        W[r["date"][:10]][r["symbol"]] = float(r["weight"])
    starts = sorted(d for d in W if d in px)
    if len(starts) < 2:
        sys.exit("need at least 2 rebalance dates found in the price file")
    blocks = []
    for i, d in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else dates[-1]
        pool = [s for s in syms if s in px[d] and s in px[e] and px[d][s] > 0]
        w = {s: x for s, x in W[d].items() if s in pool}
        if not w or len(pool) <= len(w):
            continue
        ret = {s: px[e][s] / px[d][s] - 1 for s in pool}
        blocks.append((w, pool, ret))
    if not blocks:
        sys.exit("no usable blocks: every block held the whole pool, so selection cannot be tested")
    lg = lambda x: math.log(max(1e-9, 1 + x))
    actual = sum(lg(sum(x * b[2][s] for s, x in b[0].items())) for b in blocks)
    rng = random.Random(a.seed); sims = []
    for _ in range(a.monkeys):
        tot = 0.0
        for w, pool, ret in blocks:
            pick = rng.sample(pool, len(w))
            tot += lg(sum(x * ret[s] for x, s in zip(w.values(), pick)))
        sims.append(tot)
    v, pct, ge = verdict_of(actual, sims, a.bar)
    sims.sort()
    warn = [] if len(blocks) >= 30 else [f"only {len(blocks)} blocks; LUCK is the likely verdict"]
    avg_pool = sum(len(b[1]) for b in blocks) / len(blocks); avg_n = sum(len(b[0]) for b in blocks) / len(blocks)
    if avg_pool < 3 * avg_n:
        warn.append(f"holding {avg_n:.1f} of {avg_pool:.1f} names on average: too few alternatives for a strong test; use a wider universe")
    print(json.dumps({"verdict": v, "mode": "beta_matched", "percentile": round(pct, 1),
                      "p_value_one_sided": round((ge + 1) / (a.monkeys + 1), 4), "monkeys": a.monkeys, "bar": a.bar,
                      "blocks": len(blocks), "avg_names_held": round(avg_n, 1), "avg_pool": round(avg_pool, 1),
                      "actual_log_return": round(actual, 4), "median_monkey_log_return": round(sims[len(sims) // 2], 4),
                      "seed": a.seed, "warnings": warn,
                      "note": "selection-only test: same weights, exposure and dates; only the names are random"}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--positions")
    ap.add_argument("--mode", choices=["direction", "beta_matched"], default="direction")
    ap.add_argument("--weights"); ap.add_argument("--prices")
    ap.add_argument("--monkeys", type=int, default=2048)
    ap.add_argument("--group", choices=["position", "day"], default="position")
    ap.add_argument("--bar", type=int, default=1, help="monkeys allowed at or beyond the actual result")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--currency", default="USD")
    a = ap.parse_args()
    if a.mode == "beta_matched":
        if not (a.weights and a.prices):
            sys.exit("--mode beta_matched needs --weights and --prices")
        return beta_matched(a)
    if not a.positions:
        sys.exit("--positions required")
    P = load(a.positions)
    if a.group == "day" and any(not p["day"] for p in P):
        sys.exit("--group day needs open_time on every row")

    groups = defaultdict(float)
    for p in P:
        groups[p["id"] if a.group == "position" else p["day"]] += p["pnl"]
    g = list(groups.values())
    actual = sum(g)
    rng = random.Random(a.seed)
    sims = [sum(x if rng.random() < 0.5 else -x for x in g) for _ in range(a.monkeys)]
    ge = sum(1 for s in sims if s >= actual)
    le = sum(1 for s in sims if s <= actual)
    below = sum(1 for s in sims if s < actual)
    pct = 100.0 * (below + 0.5 * (a.monkeys - below - (a.monkeys - le))) / a.monkeys
    verdict = "EDGE" if ge <= a.bar else "ANTI_EDGE" if le <= a.bar else "LUCK"
    sims.sort()
    days = len({p["day"] for p in P if p["day"]}) or None
    fees = sum(p["fees"] for p in P)
    gross = sum(abs(p["pnl"]) for p in P)
    warn = []
    if len(g) < 30:
        warn.append(f"only {len(g)} coin groups; the bar is hard to clear and LUCK is the likely verdict")
    if days and len(P) / days > 10:
        warn.append(f"{len(P) / days:.1f} positions a day: high turnover, check fee drag")
    if gross and fees / gross > 0.25:
        warn.append(f"fees are {100 * fees / gross:.0f}% of gross absolute P&L")
    print(json.dumps({
        "verdict": verdict, "percentile": round(pct, 1), "p_value_one_sided": round((ge + 1) / (a.monkeys + 1), 4),
        "monkeys": a.monkeys, "bar": a.bar, "group": a.group, "coin_groups": len(g), "positions": len(P),
        "actual_pnl_before_fees": {"value": round(actual, 2), "currency": a.currency},
        "median_monkey_pnl": {"value": round(sims[len(sims) // 2], 2), "currency": a.currency},
        "fees_total": {"value": round(fees, 2), "currency": a.currency},
        "actual_pnl_after_fees": {"value": round(actual - fees, 2), "currency": a.currency},
        "positions_per_day": round(len(P) / days, 2) if days else None,
        "monkeys_at_or_above_actual": ge, "seed": a.seed, "warnings": warn,
        "note": "direction-only test; timing and sizing held fixed. LUCK means cannot be told from chance, not no skill."
    }, indent=1))


if __name__ == "__main__":
    main()
