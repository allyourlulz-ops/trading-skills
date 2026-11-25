#!/usr/bin/env python3
"""Signals for the published premia in references/documented-edges.md. Stdlib only, no network.

Usage:
  premia_signals.py --prices closes.csv --signal mom12_1|tsmom|lowvol [--asof YYYY-MM-DD]
                    [--held held.json] [--enter 0.2] [--keep 0.4] [--target-vol 0.10]
closes.csv: wide daily closes, date,SYM1,SYM2,... (from MCP price tools; universe as it stood on each date).
  mom12_1  cross-sectional: return from 252 to 21 trading days ago, long the top --enter fraction.
  lowvol   cross-sectional: lowest 252-day volatility, long the top --enter fraction.
  tsmom    each symbol on its own: long if its 252-day return > 0, short if < 0, sized to --target-vol
           annualised using 63-day volatility (Moskowitz, Ooi and Pedersen 2012; Hurst, Ooi and Pedersen 2017).
Buy/hold band (Novy-Marx and Velikov 2016): buy only names in the top --enter, keep a held name
(--held: JSON list) until it falls out of the top --keep. Cuts turnover, the main cost driver.
Uses only rows on or before --asof.
--backtest PREFIX: rebalance every 21 trading days from day 253 on, using only past rows each time,
and write PREFIX_gross.csv (date,ret,turnover,short,trades for costs.py and pipeline.py) and
PREFIX_positions.csv (one row per symbol per holding period, for monkey_test.py). Output: weights, estimated one-way turnover vs held, and the
research note to quote. Signals are research candidates; run them through backtesting.md gates.
"""
import argparse, csv, json, math, sys


def vol(v, n):
    return math.sqrt(sum(math.log(v[-i] / v[-i - 1]) ** 2 for i in range(1, n + 1)) / n * 252)


def weights(px, signal, held, enter, keep, target_vol):
    w = {}
    if signal == "tsmom":
        for s, v in px.items():
            sd = vol(v, 63) or 1e-9
            w[s] = round((1 if v[-1] > v[-253] else -1) * min(target_vol / sd, 2.0) / len(px), 4)
        return w
    score = {s: (v[-22] / v[-253] - 1) if signal == "mom12_1" else -vol(v, 252) for s, v in px.items()}
    ranked = sorted(score, key=score.get, reverse=True)
    n_in, n_keep = max(1, round(len(ranked) * enter)), max(1, round(len(ranked) * keep))
    pick = set(ranked[:n_in]) | (set(held) & set(ranked[:n_keep]))
    return {s: round(1 / len(pick), 4) for s in sorted(pick)}


def backtest(head, body, a):
    syms = head[1:]; cols = {s: i + 1 for i, s in enumerate(syms)}
    gross, pos, w, t = [], [], {}, 253
    while t < len(body):
        px = {}
        for s in syms:
            v = [float(r[cols[s]]) for r in body[:t] if r[cols[s]] not in ("", "NA")]
            if len(v) >= 253 and len(v) == t:
                px[s] = v
        if not px:
            t += 21; continue
        nw = weights(px, a.signal, set(w), a.enter, a.keep, a.target_vol)
        tv = sum(abs(nw.get(s, 0) - w.get(s, 0)) for s in set(nw) | set(w)) / 2
        trades = sum(1 for s in set(nw) | set(w) if abs(nw.get(s, 0) - w.get(s, 0)) > 1e-9)
        w = nw; end = min(t + 21, len(body))
        for k in range(t, end):
            r = sum(wt * (float(body[k][cols[s]]) / float(body[k - 1][cols[s]]) - 1) for s, wt in w.items())
            gross.append([body[k][0], round(r, 8), round(tv if k == t else 0, 6),
                          round(sum(-x for x in w.values() if x < 0), 6), trades if k == t else 0])
        for s, wt in w.items():
            ret = float(body[end - 1][cols[s]]) / float(body[t - 1][cols[s]]) - 1
            pos.append([f"{s}-{body[t][0]}", body[t][0], "long" if wt > 0 else "short", round(abs(wt) * ret * (1 if wt > 0 else -1) * 10000, 2)])
        t = end
    with open(a.backtest + "_gross.csv", "w", newline="") as f:
        c = csv.writer(f); c.writerow(["date", "ret", "turnover", "short", "trades"]); c.writerows(gross)
    with open(a.backtest + "_positions.csv", "w", newline="") as f:
        c = csv.writer(f); c.writerow(["id", "open_time", "side", "pnl"]); c.writerows(pos)
    print(json.dumps({"signal": a.signal, "periods": len(gross), "positions": len(pos),
                      "outputs": [a.backtest + "_gross.csv", a.backtest + "_positions.csv"],
                      "note": "positions pnl is per 10,000 of capital; feed _gross.csv to pipeline.py"}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", required=True); ap.add_argument("--signal", required=True, choices=["mom12_1", "tsmom", "lowvol"])
    ap.add_argument("--asof"); ap.add_argument("--held"); ap.add_argument("--enter", type=float, default=0.2)
    ap.add_argument("--keep", type=float, default=0.4); ap.add_argument("--target-vol", type=float, default=0.10)
    ap.add_argument("--backtest")
    a = ap.parse_args()
    rows = list(csv.reader(open(a.prices, newline="")))
    head, body = rows[0], [r for r in rows[1:] if not a.asof or r[0][:10] <= a.asof]
    if len(body) < 253:
        sys.exit("need at least 253 daily rows on or before --asof")
    syms = head[1:]
    if a.backtest:
        return backtest(head, body, a)
    px = {s: [float(r[i + 1]) for r in body if r[i + 1] not in ("", "NA")] for i, s in enumerate(syms)}
    px = {s: v for s, v in px.items() if len(v) >= 253}
    if not px:
        sys.exit("no symbol has 253 rows")
    held = set(json.load(open(a.held))) if a.held else set()
    w = weights(px, a.signal, held, a.enter, a.keep, a.target_vol)
    prev = {s: 1 / len(held) for s in held} if held else {}
    turn = sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in set(w) | set(prev)) / 2
    print(json.dumps({"signal": a.signal, "asof": body[-1][0], "universe": len(px), "weights": w,
                      "one_way_turnover_vs_held": round(turn, 3),
                      "note": "Published premia, not a promise: anomaly returns fell 26% out of sample and 58% after publication (McLean and Pontiff 2016). Check net of your costs."}, indent=1))


if __name__ == "__main__":
    main()
