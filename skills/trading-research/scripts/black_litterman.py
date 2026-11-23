#!/usr/bin/env python3
"""Black-Litterman: turn the committee's views into portfolio weights. Stdlib only, no network.

Start from what the market already implies (reverse-optimised returns from market-cap
weights), tilt toward the views in proportion to their confidence, then size with
mean-variance and clamp to long-only / caps. The model writes views; this does the math.

Inputs
  --prices  CSV: date,<TICKER1>,<TICKER2>,... closes, oldest first (pull bars via a data MCP server)
  --views   JSON list, one object per view (several analysts may view the same name):
      {"ticker":"AAPL","conviction":0.6,"confidence":70}            absolute view
      {"long":"MSFT","short":"AAPL","conviction":0.4,"confidence":50} relative view
    conviction in [-1,1]: expected excess return = conviction x --scale x annual vol of the
    ticker (or of the spread). confidence 0-100 (the committee's scale): sets how far the view moves the prior.
  --mcap    optional JSON {"AAPL":3.4e12,...}; default equal weight prior
Usage: black_litterman.py --prices px.csv --views views.json [--mcap caps.json]
       [--tau 0.05] [--delta 2.5] [--scale 0.5] [--periods 252] [--long-only] [--max-weight 0.25]
Prints JSON: prior and posterior returns, weights, change vs market. Feed each resulting
order through risk_check.py; these weights are a target, not an order.
"""
import argparse, csv, json, math


def inv(m, ridge=1e-10):
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for i in range(n):
        a[i][i] += ridge
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-18:
            raise SystemExit("singular matrix: drop a duplicate or constant series")
        a[c], a[p] = a[p], a[c]
        piv = a[c][c]
        a[c] = [x / piv for x in a[c]]
        for r in range(n):
            if r != c and a[r][c]:
                f = a[r][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [row[n:] for row in a]


def mm(a, b):
    bt = list(zip(*b))
    return [[sum(x * y for x, y in zip(r, c)) for c in bt] for r in a]


def mv(a, v):
    return [sum(x * y for x, y in zip(r, v)) for r in a]


def tr(a):
    return [list(r) for r in zip(*a)]


def add(a, b):
    return [[x + y for x, y in zip(r, s)] for r, s in zip(a, b)]


def scal(k, a):
    return [[k * x for x in r] for r in a]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--views", required=True)
    ap.add_argument("--mcap")
    ap.add_argument("--tau", type=float, default=0.05)
    ap.add_argument("--delta", type=float, default=2.5, help="risk aversion")
    ap.add_argument("--scale", type=float, default=0.5, help="conviction 1.0 = this many annual vols")
    ap.add_argument("--periods", type=int, default=252)
    ap.add_argument("--long-only", action="store_true")
    ap.add_argument("--max-weight", type=float, default=1.0)
    a = ap.parse_args()

    with open(a.prices, newline="") as fh:
        rows = list(csv.DictReader(fh))
    tick = [c for c in rows[0] if c.lower() != "date"]
    n = len(tick)
    px = [[float(r[t]) for t in tick] for r in rows]
    rets = [[math.log(px[i + 1][j] / px[i][j]) for j in range(n)] for i in range(len(px) - 1)]
    T = len(rets)
    if T < 60:
        raise SystemExit("need at least 60 bars of returns")
    mu = [sum(r[j] for r in rets) / T for j in range(n)]
    S = [[sum((r[i] - mu[i]) * (r[j] - mu[j]) for r in rets) / (T - 1) * a.periods
          for j in range(n)] for i in range(n)]

    if a.mcap:
        caps = json.load(open(a.mcap))
        w_mkt = [float(caps[t]) for t in tick]
    else:
        w_mkt = [1.0] * n
    s = sum(w_mkt)
    w_mkt = [w / s for w in w_mkt]
    pi = mv(scal(a.delta, S), w_mkt)  # implied equilibrium excess returns

    views = json.load(open(a.views))
    P, Q, om, used = [], [], [], []
    for v in views:
        row = [0.0] * n
        if "ticker" in v:
            if v["ticker"] not in tick:
                continue
            row[tick.index(v["ticker"])] = 1.0
        else:
            if v.get("long") not in tick or v.get("short") not in tick:
                continue
            row[tick.index(v["long"])], row[tick.index(v["short"])] = 1.0, -1.0
        var = sum(row[i] * row[j] * S[i][j] for i in range(n) for j in range(n))
        conv = max(-1.0, min(1.0, float(v["conviction"])))
        conf = float(v.get("confidence", 50))
        conf = max(0.01, min(0.99, conf / 100))
        # prior return of this portfolio + the view's tilt
        q = sum(r * p for r, p in zip(row, pi)) + conv * a.scale * math.sqrt(var)
        P.append(row); Q.append(q); om.append((1 / conf - 1) * a.tau * var); used.append(v)
    if not P:  # no usable views: hold the market prior
        P, Q, om = [[0.0] * n], [0.0], [1e12]
    k = len(P)
    Om_inv = [[(1 / om[i] if i == j else 0.0) for j in range(k)] for i in range(k)]
    tS_inv = inv(scal(a.tau, S))
    Pt = tr(P)
    A = add(tS_inv, mm(mm(Pt, Om_inv), P))
    b = [x + y for x, y in zip(mv(tS_inv, pi), mv(mm(Pt, Om_inv), Q))]
    post = mv(inv(A), b)
    w = mv(inv(scal(a.delta, S)), post)
    raw = w[:]
    if a.long_only:
        w = [max(0.0, x) for x in w]
    tot = sum(abs(x) for x in w) or 1.0
    w = [x / tot for x in w]  # gross exposure 1
    for _ in range(50):  # cap single names, redistribute the excess pro rata
        over = [i for i in range(n) if abs(w[i]) > a.max_weight + 1e-12]
        if not over:
            break
        excess = sum(abs(w[i]) - a.max_weight for i in over)
        for i in over:
            w[i] = math.copysign(a.max_weight, w[i])
        free = [i for i in range(n) if i not in over and w[i] != 0]
        fs = sum(abs(w[i]) for i in free)
        if not free or fs == 0:
            break
        for i in free:
            w[i] += math.copysign(excess * abs(w[i]) / fs, w[i])
    r4 = lambda x: round(x, 4)
    print(json.dumps(dict(
        tickers=tick, bars=T, tau=a.tau, delta=a.delta, views_used=len(used),
        prior_excess_return={t: r4(x) for t, x in zip(tick, pi)},
        posterior_excess_return={t: r4(x) for t, x in zip(tick, post)},
        market_weight={t: r4(x) for t, x in zip(tick, w_mkt)},
        unconstrained_weight={t: r4(x) for t, x in zip(tick, raw)},
        target_weight={t: r4(x) for t, x in zip(tick, w)},
        change_vs_market={t: r4(x - m) for t, x, m in zip(tick, w, w_mkt)},
        notes=["Target weights, not orders: each trade still goes through risk_check.py and the user's yes.",
               "Low-confidence views barely move the prior; that is intended.",
               "Covariance is sample covariance over the whole file; use 1-3 years of daily bars."]), indent=2))


if __name__ == "__main__":
    main()
