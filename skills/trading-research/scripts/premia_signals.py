#!/usr/bin/env python3
"""Signals and a realistic backtest for the published premia in references/documented-edges.md.
Stdlib only, no network.

Usage:
  premia_signals.py --prices closes.csv --signal mom12_1|tsmom|lowvol [--asof YYYY-MM-DD]
                    [--held held.json] [--enter 0.2] [--keep 0.4] [--target-vol 0.10] [--long-short]
  premia_signals.py ... --backtest PREFIX [--tranches 3] [--universe members.csv]
                    [--volumes volumes.csv --capital 10000 --adv-cap-pct 1]
                    [--borrow borrow.csv --max-borrow-bps 1500]
closes.csv: wide daily closes, date,SYM1,SYM2,... (from MCP price tools). Blank = not trading that day
  (not yet listed or delisted). Keep delisted names in the file: dropping them is survivorship bias.
  mom12_1  cross-sectional: return from 252 to 21 trading days ago; long the top --enter fraction
           (--long-short: also short the bottom --enter fraction, half the capital each side).
  lowvol   cross-sectional: lowest 252-day volatility long (--long-short: highest volatility short).
  tsmom    each symbol on its own: long if its 252-day return > 0, short if < 0, sized to --target-vol
           annualised using 63-day volatility (Moskowitz, Ooi and Pedersen 2012; Hurst, Ooi and Pedersen 2017).
Buy/hold band (Novy-Marx and Velikov 2016): enter only names in the top --enter, keep a held name until
it falls out of the top --keep (same for the short side). Cuts turnover, the main cost driver.

--backtest PREFIX: daily simulation from day 254 on. Point in time: a rebalance on day t uses closes
through day t-2, trades at the close of day t-1 and earns from day t (signal, then next bar).
  --tranches K   K overlapping books, each rebalanced every 21 trading days on staggered days (Jegadeesh
                 and Titman 1993 overlapping portfolios); removes the fixed-rebalance-day artifact.
  --universe     date,symbol rows: point-in-time membership (e.g. from universe.py); a name is eligible
                 only while its latest membership date includes it. Without it every name with data is
                 eligible, which is fine for a fixed ETF set and wrong for stocks.
  --volumes      wide daily share volumes, same layout as closes. Each day a name trades at most
                 --adv-cap-pct of its 20-day average dollar volume at --capital; the rest carries over
                 to the next day (part fills). Also writes adv_frac and sigma columns so costs.py charges
                 square-root impact and prints a capacity curve.
  --borrow       symbol,rate_bps_yr,locate[,asof] from your broker's locate or borrow list. A name with
                 locate != yes, or a fee above --max-borrow-bps, is never shorted; the short book's
                 weighted fee goes in the borrow_bps_yr column. Without it costs.py uses its flat fee.
Writes PREFIX_gross.csv (date,ret,turnover,short,trades[,borrow_bps_yr][,adv_frac,sigma] for costs.py
and pipeline.py), PREFIX_positions.csv (per symbol per 21-day block, pnl per 10,000 of capital, for
monkey_test.py) and PREFIX_weights.csv (date,symbol,weight at each block start, for
monkey_test.py --mode beta_matched). Delisting returns are not in price files: a delisted holding exits
at its last close, which flatters results slightly (Shumway 1997); say so when it happens.
"""
import argparse, csv, json, math, sys


def vol(v, n):
    return math.sqrt(sum(math.log(v[-i] / v[-i - 1]) ** 2 for i in range(1, n + 1)) / n * 252)


def weights(px, signal, held, enter, keep, target_vol, long_short=False, shortable=None):
    """px: symbol -> list of closes (oldest first, >= 253). held: symbol -> +1/-1 currently held."""
    w = {}
    ok_short = (lambda s: True) if shortable is None else (lambda s: s in shortable)
    if signal == "tsmom":
        for s, v in px.items():
            sd = vol(v, 63) or 1e-9
            side = 1 if v[-1] > v[-253] else -1
            if side < 0 and not ok_short(s):
                continue
            w[s] = round(side * min(target_vol / sd, 2.0) / len(px), 6)
        return w
    score = {s: (v[-22] / v[-253] - 1) if signal == "mom12_1" else -vol(v, 252) for s, v in px.items()}
    ranked = sorted(score, key=score.get, reverse=True)
    n_in, n_keep = max(1, round(len(ranked) * enter)), max(1, round(len(ranked) * keep))
    longs = set(ranked[:n_in]) | ({s for s, d in held.items() if d > 0} & set(ranked[:n_keep]))
    if not long_short:
        return {s: round(1 / len(longs), 6) for s in sorted(longs)}
    bottom = [s for s in reversed(ranked) if ok_short(s) and s not in longs]
    shorts = set(bottom[:n_in]) | ({s for s, d in held.items() if d < 0} & set(bottom[:n_keep]))
    for s in sorted(longs):
        w[s] = round(0.5 / len(longs), 6)
    for s in sorted(shorts):
        w[s] = round(-0.5 / len(shorts), 6)
    return w


def read_wide(path):
    rows = list(csv.reader(open(path, newline="")))
    head = rows[0]
    body = [[r[0]] + [float(x) if x not in ("", "NA", "nan") else None for x in r[1:]] for r in rows[1:] if r]
    return head, body


def backtest(head, body, a):
    syms = head[1:]; N = len(syms); T = len(body)
    col = {s: i + 1 for i, s in enumerate(syms)}
    vols = None
    if a.volumes:
        vh, vb = read_wide(a.volumes)
        vmap = {r[0]: r for r in vb}; vcol = {s: i + 1 for i, s in enumerate(vh[1:])}
        vols = [[(vmap.get(r[0]) or [None] * (len(vh)))[vcol[s]] if s in vcol else None for s in syms] for r in body]
    members = None
    if a.universe:
        members = {}
        for r in csv.DictReader(open(a.universe, newline="")):
            members.setdefault(r["date"][:10], set()).add(r["symbol"])
        mdates = sorted(members)
    shortable, borrow = None, {}
    if a.borrow:
        shortable = set()
        for r in csv.DictReader(open(a.borrow, newline="")):
            rate = float(r.get("rate_bps_yr") or 0)
            borrow[r["symbol"]] = rate
            if str(r.get("locate", "")).strip().lower() in ("yes", "y", "true", "1") and rate <= a.max_borrow_bps:
                shortable.add(r["symbol"])
    K = max(1, a.tranches); t0 = 254
    offsets = [j * 21 // K for j in range(K)]
    targets = [dict() for _ in range(K)]
    cur = {}
    gross, pos_pnl, wrows, delisted = [], {}, [], set()

    def eligible(t):
        allowed = None
        if members is not None:
            d = body[t][0][:10]; lo, hi = 0, len(mdates)
            while lo < hi:
                m = (lo + hi) // 2
                if mdates[m] <= d: lo = m + 1
                else: hi = m
            allowed = members[mdates[lo - 1]] if lo else set()
        px = {}
        for s in syms:
            if allowed is not None and s not in allowed:
                continue
            v = [body[i][col[s]] for i in range(t - 252, t + 1)] if t >= 252 else []
            if v and all(x is not None and x > 0 for x in v):
                px[s] = v
        return px

    for t in range(t0, T):
        trades = 0
        for j in range(K):
            if (t - t0) % 21 == offsets[j]:
                px = eligible(t - 2)
                if px:
                    held = {s: (1 if x > 0 else -1) for s, x in targets[j].items()}
                    targets[j] = weights(px, a.signal, held, a.enter, a.keep, a.target_vol, a.long_short, shortable)
        tgt = {}
        for j in range(K):
            for s, x in targets[j].items():
                tgt[s] = tgt.get(s, 0) + x / K
        for s in list(tgt):
            if body[t - 1][col[s]] is None:
                tgt.pop(s); delisted.add(s)
        traded, advs, sigs = 0.0, [], []
        for s in set(tgt) | set(cur):
            want = tgt.get(s, 0) - cur.get(s, 0)
            if abs(want) < 1e-9:
                continue
            if body[t - 1][col[s]] is None:
                cur.pop(s, None); delisted.add(s); continue
            if vols is not None:
                dv = [body[i][col[s]] * vols[i][col[s] - 1] for i in range(max(0, t - 21), t)
                      if body[i][col[s]] is not None and vols[i][col[s] - 1]]
                adv_usd = sum(dv) / len(dv) if dv else 0.0
                cap = a.adv_cap_pct / 100 * adv_usd / a.capital if adv_usd else 0.0
                step = max(-cap, min(cap, want))
                if adv_usd:
                    advs.append(abs(step) * a.capital / adv_usd)
                    c = [body[i][col[s]] for i in range(max(0, t - 64), t) if body[i][col[s]]]
                    if len(c) > 2:
                        lr = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
                        m = sum(lr) / len(lr); sigs.append(math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1)))
            else:
                step = want
            if abs(step) > 1e-12:
                cur[s] = cur.get(s, 0) + step; traded += abs(step); trades += 1
                if abs(cur[s]) < 1e-9:
                    cur.pop(s)
        r = 0.0
        for s, x in cur.items():
            p0, p1 = body[t - 1][col[s]], body[t][col[s]]
            rr = (p1 / p0 - 1) if p0 and p1 else 0.0
            r += x * rr
            blk = (t - t0) // 21
            key = (s, blk)
            pos_pnl[key] = pos_pnl.get(key, 0.0) + x * rr * 10000
            pos_pnl.setdefault(("side", s, blk), 1 if x > 0 else -1)
        if (t - t0) % 21 == 0:
            for s, x in sorted(cur.items()):
                wrows.append([body[t][0], s, round(x, 6)])
        short = sum(-x for x in cur.values() if x < 0)
        row = [body[t][0], round(r, 8), round(traded / 2, 6), round(short, 6), trades]
        if a.borrow:
            row.append(round(sum(-x * borrow.get(s, a.max_borrow_bps) for s, x in cur.items() if x < 0) / short, 1) if short else 0)
        if vols is not None:
            row += [round(sum(advs) / len(advs), 8) if advs else 0, round(sum(sigs) / len(sigs), 6) if sigs else 0]
        gross.append(row)
    hdr = ["date", "ret", "turnover", "short", "trades"] + (["borrow_bps_yr"] if a.borrow else []) + (["adv_frac", "sigma"] if vols is not None else [])
    with open(a.backtest + "_gross.csv", "w", newline="") as f:
        c = csv.writer(f); c.writerow(hdr); c.writerows(gross)
    with open(a.backtest + "_positions.csv", "w", newline="") as f:
        c = csv.writer(f); c.writerow(["id", "open_time", "side", "pnl"])
        for (s, blk), p in sorted((k, v) for k, v in pos_pnl.items() if k[0] != "side"):
            d = body[t0 + blk * 21][0]
            c.writerow([f"{s}-{d}", d, "long" if pos_pnl[("side", s, blk)] > 0 else "short", round(p, 2)])
    with open(a.backtest + "_weights.csv", "w", newline="") as f:
        c = csv.writer(f); c.writerow(["date", "symbol", "weight"]); c.writerows(wrows)
    print(json.dumps({"signal": a.signal, "long_short": a.long_short, "tranches": K, "periods": len(gross),
                      "symbols": N, "universe_file": bool(a.universe), "part_fills": vols is not None,
                      "borrow_file": bool(a.borrow), "delisted_exits": sorted(delisted),
                      "outputs": [a.backtest + "_gross.csv", a.backtest + "_positions.csv", a.backtest + "_weights.csv"],
                      "note": "signal uses closes through t-2, trades at t-1 close; positions pnl is per 10,000 of capital; feed _gross.csv to pipeline.py"}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", required=True); ap.add_argument("--signal", required=True, choices=["mom12_1", "tsmom", "lowvol"])
    ap.add_argument("--asof"); ap.add_argument("--held"); ap.add_argument("--enter", type=float, default=0.2)
    ap.add_argument("--keep", type=float, default=0.4); ap.add_argument("--target-vol", type=float, default=0.10)
    ap.add_argument("--long-short", action="store_true")
    ap.add_argument("--backtest"); ap.add_argument("--tranches", type=int, default=1)
    ap.add_argument("--universe"); ap.add_argument("--volumes"); ap.add_argument("--capital", type=float, default=10000)
    ap.add_argument("--adv-cap-pct", type=float, default=1.0)
    ap.add_argument("--borrow"); ap.add_argument("--max-borrow-bps", type=float, default=1500)
    a = ap.parse_args()
    head, body = read_wide(a.prices)
    body = [r for r in body if not a.asof or r[0][:10] <= a.asof]
    if len(body) < 255:
        sys.exit("need at least 255 daily rows on or before --asof")
    if a.backtest:
        return backtest(head, body, a)
    syms = head[1:]
    px = {}
    for i, s in enumerate(syms):
        v = [r[i + 1] for r in body[-253:]]
        if all(x is not None and x > 0 for x in v):
            px[s] = v
    if not px:
        sys.exit("no symbol has 253 unbroken rows")
    held = {s: 1 for s in json.load(open(a.held))} if a.held else {}
    w = weights(px, a.signal, held, a.enter, a.keep, a.target_vol, a.long_short)
    prev = {s: 1 / len(held) for s in held} if held else {}
    turn = sum(abs(w.get(s, 0) - prev.get(s, 0)) for s in set(w) | set(prev)) / 2
    print(json.dumps({"signal": a.signal, "asof": body[-1][0], "universe": len(px), "weights": w,
                      "one_way_turnover_vs_held": round(turn, 3),
                      "warning": "fewer than 100 names: cross-sectional ranks are close to noise (references/backtesting.md, Universe)" if len(px) < 100 and a.signal != "tsmom" else None,
                      "note": "Published premia, not a promise: anomaly returns fell 26% out of sample and 58% after publication (McLean and Pontiff 2016). Check net of your costs."}, indent=1))


if __name__ == "__main__":
    main()
