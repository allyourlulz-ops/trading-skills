#!/usr/bin/env python3
"""Forecast scorekeeper: log every committee view, grade it after its horizon,
and report whether the stated confidence holds up. Stdlib only, no network.

  log     append one view to the journal (JSONL)
  grade   score views whose horizon has passed, using a closes CSV from the data MCP server
  report  hit rate, Brier score, calibration by confidence bucket, per-source reliability, worst misses
Use --source to track anyone's calls (a persona, an analyst, an X account) and rank them by Brier.

Examples
  scorekeeper.py log --journal views.jsonl --ticker AAPL --rating Buy --conviction 0.6 \
      --confidence 70 --horizon-days 20 --date 2026-11-23
  scorekeeper.py grade --journal views.jsonl --prices closes.csv --benchmark SPY
  scorekeeper.py report --journal views.jsonl

closes.csv: date,<TICKER>,...,<BENCHMARK> (oldest first, trading days only).
A view is right when the sign of its conviction matches the sign of its excess return
over the horizon (vs the benchmark if given). Hold / |conviction| < 0.15 is right when
|excess| < --hold-band percent. Confidence (0-100) is read as the chance of being right.
"""
import argparse, csv, json, math, os, sys
from datetime import date

RATINGS = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


def load(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def save(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, path)


def direction(v):
    c = float(v.get("conviction", 0))
    if v.get("rating") == "Hold" or abs(c) < 0.15:
        return 0
    return 1 if c > 0 else -1


def cmd_log(a):
    rows = load(a.journal)
    if a.rating not in RATINGS:
        sys.exit(f"rating must be one of {list(RATINGS)}")
    conv = max(-1.0, min(1.0, a.conviction))
    if RATINGS[a.rating] and conv and (conv > 0) != (RATINGS[a.rating] > 0):
        sys.exit("conviction sign contradicts the rating")
    v = dict(id=len(rows) + 1, date=a.date or date.today().isoformat(), ticker=a.ticker.upper(),
             rating=a.rating, conviction=conv, confidence=max(0, min(100, a.confidence)),
             horizon_days=a.horizon_days, note=a.note or "", source=a.source or "committee", status="open")
    rows.append(v)
    save(a.journal, rows)
    print(json.dumps(v))


def cmd_grade(a):
    rows = load(a.journal)
    with open(a.prices, newline="") as fh:
        px = list(csv.DictReader(fh))
    dates = [r["date"][:10] for r in px]
    graded = 0
    for v in rows:
        if v.get("status") != "open":
            continue
        t = v["ticker"]
        if t not in px[0]:
            continue
        start = next((i for i, d in enumerate(dates) if d >= v["date"]), None)
        if start is None or start + v["horizon_days"] >= len(px):
            continue  # horizon not reached yet
        end = start + v["horizon_days"]
        try:
            r = float(px[end][t]) / float(px[start][t]) - 1
            b = (float(px[end][a.benchmark]) / float(px[start][a.benchmark]) - 1) if a.benchmark else 0.0
        except (KeyError, ValueError, ZeroDivisionError):
            continue
        ex = (r - b) * 100
        d = direction(v)
        right = abs(ex) < a.hold_band if d == 0 else (ex > 0) == (d > 0)
        v.update(status="graded", graded_on=dates[end], return_pct=round(r * 100, 3),
                 excess_pct=round(ex, 3), benchmark=a.benchmark or None, right=bool(right))
        graded += 1
    save(a.journal, rows)
    print(json.dumps(dict(graded_now=graded, still_open=sum(1 for v in rows if v.get("status") == "open"))))


def cmd_report(a):
    g = [v for v in load(a.journal) if v.get("status") == "graded"]
    n = len(g)
    if n == 0:
        print(json.dumps(dict(graded=0, note="No graded views yet. Grade after horizons pass."))); return
    hits = sum(v["right"] for v in g)
    brier = sum((v["confidence"] / 100 - v["right"]) ** 2 for v in g) / n
    # one-sided binomial p-value vs a coin flip
    p = sum(math.comb(n, k) for k in range(hits, n + 1)) / 2 ** n
    buckets = {}
    for v in g:
        lo = min(90, int(v["confidence"] // 10 * 10))
        b = buckets.setdefault(f"{lo}-{lo + 10}", [0, 0, 0.0])
        b[0] += 1; b[1] += v["right"]; b[2] += v["confidence"]
    cal = {k: dict(n=b[0], stated=round(b[2] / b[0], 1), actual=round(100 * b[1] / b[0], 1),
                   gap=round(100 * b[1] / b[0] - b[2] / b[0], 1)) for k, b in sorted(buckets.items())}
    overconf = sum(b["n"] * -b["gap"] for b in cal.values() if b["gap"] < 0) / n
    by_rating = {}
    for v in g:
        r = by_rating.setdefault(v["rating"], [0, 0, 0.0])
        r[0] += 1; r[1] += v["right"]; r[2] += v["excess_pct"]
    by_source = {}
    for v in g:
        s_ = by_source.setdefault(v.get("source", "committee"), [0, 0, 0.0])
        s_[0] += 1; s_[1] += v["right"]; s_[2] += (v["confidence"] / 100 - v["right"]) ** 2
    worst = sorted((v for v in g if not v["right"]), key=lambda v: -v["confidence"] * abs(v["excess_pct"]))[:3]
    print(json.dumps(dict(
        graded=n, hit_rate_pct=round(100 * hits / n, 1), coin_flip_p_value=round(p, 4),
        brier=round(brier, 4), brier_if_always_50=0.25,
        calibration=cal, avg_overconfidence_pts=round(overconf, 1),
        by_rating={k: dict(n=r[0], hit_pct=round(100 * r[1] / r[0], 1), avg_excess_pct=round(r[2] / r[0], 2))
                   for k, r in by_rating.items()},
        by_source={k: dict(n=r[0], hit_pct=round(100 * r[1] / r[0], 1), brier=round(r[2] / r[0], 4))
                   for k, r in sorted(by_source.items(), key=lambda kv: kv[1][2] / kv[1][0])},
        lessons=[dict(id=v["id"], ticker=v["ticker"], date=v["date"], rating=v["rating"],
                      confidence=v["confidence"], excess_pct=v["excess_pct"], note=v.get("note", "")) for v in worst],
        notes=["Under 30 graded views, treat every number here as noise.",
               "Brier above 0.25 means the stated confidence is worse than saying 50% every time.",
               "Feed 'lessons' into the committee's 'Lessons from prior decisions'."]), indent=2))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    l = sp.add_parser("log")
    l.add_argument("--journal", required=True); l.add_argument("--ticker", required=True)
    l.add_argument("--rating", required=True); l.add_argument("--conviction", type=float, required=True)
    l.add_argument("--confidence", type=float, required=True); l.add_argument("--horizon-days", type=int, required=True)
    l.add_argument("--date"); l.add_argument("--note")
    l.add_argument("--source", help="who made the call: committee, a persona, an analyst, an X account")
    gr = sp.add_parser("grade")
    gr.add_argument("--journal", required=True); gr.add_argument("--prices", required=True)
    gr.add_argument("--benchmark"); gr.add_argument("--hold-band", type=float, default=2.0)
    r = sp.add_parser("report"); r.add_argument("--journal", required=True)
    a = ap.parse_args()
    {"log": cmd_log, "grade": cmd_grade, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
