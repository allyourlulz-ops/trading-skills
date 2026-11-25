#!/usr/bin/env python3
"""discover mode: generate candidate event strategies from a spec'd sweep, log every variant to the trial
ledger, and screen the whole sweep at once with rule_screen.py (Benjamini-Hochberg across ALL variants).
Stdlib only, no network. Survivors go to backtest; they are candidates, not edges.

Usage:
  discover.py --events events.csv --prices closes.csv --spec sweep.json [--benchmark SPY]
              [--out PREFIX] [--ledger trials.jsonl] [--fdr 0.10]
events.csv  date,symbol,event[,value][,mechanism]   one row per dated event, from MCP tools only:
            8-K item codes (event=8k_2.02), Form 4 buy clusters (event=form4_cluster, value=insiders),
            token unlocks (event=unlock, value=% of supply), options skew percentile (event=skew,
            value=0-100), borrow-fee extremes (event=borrow, value=bps), index adds/deletes, etc.
            date = when the event became PUBLIC (filing acceptance time, not period end).
closes.csv  wide daily closes date,SYM,...; include the --benchmark column (or --benchmark none).
sweep.json  {"events": ["8k_2.02", "form4_cluster"] or "all",
             "thresholds": {"form4_cluster": [2, 3, 5]},   value >= threshold (optional, per event)
             "directions": [1, -1], "horizons": [1, 5, 10, 20],
             "cost_bps_roundtrip": 20, "mechanism": {"form4_cluster": "insiders buy on private info"}}
Each variant = event x threshold x direction x horizon. Entry is the close of the first trading day
AFTER the event date (the event may land after the close), exit `horizon` days later. Excess =
direction x (stock return - benchmark return) - round-trip cost, as rule_screen.py expects.
Every variant is logged to the trial ledger BEFORE screening, including variants with no trades, and
rule_screen.py gets --tried with the full count. An event with no "mechanism" (who is on the other side
and why they are forced to lose; references/small-capacity-edges.md) is screened but flagged
NO_MECHANISM and does not go to backtest.
"""
import argparse, bisect, csv, itertools, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from trial_ledger import count as ledger_count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", required=True); ap.add_argument("--prices", required=True)
    ap.add_argument("--spec", required=True); ap.add_argument("--benchmark", default="SPY")
    ap.add_argument("--out", default="discover"); ap.add_argument("--ledger"); ap.add_argument("--fdr", default="0.10")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    rows = list(csv.reader(open(a.prices, newline="")))
    head = rows[0]; col = {s: i for i, s in enumerate(head)}
    dates = [r[0][:10] for r in rows[1:]]
    px = [[None] + [float(x) if x not in ("", "NA") else None for x in r[1:]] for r in rows[1:]]
    bench = col.get(a.benchmark) if a.benchmark.lower() != "none" else None
    if a.benchmark.lower() != "none" and bench is None:
        sys.exit(f"no {a.benchmark} column; pass --benchmark none to use raw returns")
    ev = [r for r in csv.DictReader(open(a.events, newline="")) if r.get("symbol") in col]
    kinds = sorted({r["event"] for r in ev}) if spec.get("events", "all") == "all" else spec["events"]
    mech = dict(spec.get("mechanism", {}))
    for r in ev:
        if r.get("mechanism"):
            mech.setdefault(r["event"], r["mechanism"])
    cost = float(spec.get("cost_bps_roundtrip", 20)) / 1e4
    variants = []
    for k in kinds:
        for th in spec.get("thresholds", {}).get(k, [None]):
            for d, h in itertools.product(spec.get("directions", [1]), spec.get("horizons", [5])):
                variants.append((k, th, int(d), int(h)))
    ledger_args = ["--ledger", a.ledger] if a.ledger else []
    for k, th, d, h in variants:
        vid = f"disc_{k}_{th}_{'L' if d > 0 else 'S'}_h{h}"
        subprocess.run([sys.executable, os.path.join(HERE, "trial_ledger.py"), "log", "--id", vid, "--family", "discover",
                        "--note", f"event={k} threshold={th} dir={d} horizon={h}", *ledger_args], capture_output=True)
    trades = []
    for k, th, d, h in variants:
        vid = f"disc_{k}_{th}_{'L' if d > 0 else 'S'}_h{h}"
        for r in ev:
            if r["event"] != k:
                continue
            if th is not None and float(r.get("value") or 0) < float(th):
                continue
            i = bisect.bisect_right(dates, r["date"][:10])  # first trading day after the event date
            j = i + h
            if j >= len(dates):
                continue
            c = col[r["symbol"]]
            p0, p1 = px[i][c], px[j][c]
            if not p0 or not p1:
                continue
            ret = p1 / p0 - 1
            if bench is not None:
                b0, b1 = px[i][bench], px[j][bench]
                if not b0 or not b1:
                    continue
                ret -= b1 / b0 - 1
            trades.append([vid, dates[i], round(d * ret - cost, 6)])
    tpath = a.out + "_trades.csv"
    with open(tpath, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["rule", "date", "excess"]); w.writerows(trades)
    if not trades:
        sys.exit("no trades: check event dates, symbols and the price file")
    p = subprocess.run([sys.executable, os.path.join(HERE, "rule_screen.py"), "--trades", tpath, "--fdr", a.fdr,
                        "--tried", str(len(variants))], capture_output=True, text=True)
    scr = json.loads(p.stdout)
    surv, flagged = [], []
    for v in scr["approved"]:
        kind = next(k for k, th, d, h in variants if v == f"disc_{k}_{th}_{'L' if d > 0 else 'S'}_h{h}")
        (surv if mech.get(kind) else flagged).append(v)
    print(json.dumps({"variants_tried": len(variants), "variants_with_trades": scr["variants"], "trades": len(trades),
                      "ledger_distinct_trials_discover": ledger_count(a.ledger, "discover"),
                      "survivors": surv, "no_mechanism": flagged, "mechanisms": {k: mech.get(k) for k in kinds},
                      "screen_cutoff": scr["cutoff"], "trades_file": tpath,
                      "next": "backtest each survivor with its own strategy contract; pass --trials auto so DSR counts the sweep",
                      "screen": [{k: s[k] for k in ("rule", "is_trades", "is_t", "oos_t", "verdict")} for s in scr["rules"]]}, indent=1))


if __name__ == "__main__":
    main()
