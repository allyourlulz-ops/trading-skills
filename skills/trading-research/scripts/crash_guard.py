#!/usr/bin/env python3
"""Portfolio crash-protection layer. Stdlib only, no network (closes come from the data MCP server).

One call answers: how much of normal size should the book hold right now, where does its
risk really sit, and what would the big historical crashes have done to it?

Usage: crash_guard.py --prices closes.csv --weights w.json [--index SPY] [--equity equity.csv]
                      [--target-vol 0.10] [--cap 1.5] [--lam 0.94] [--trend-days 252]
closes.csv: date,<TICKER>,...  daily closes, oldest first; include the index column (default SPY)
w.json:     {"SPY":0.6,"TLT":0.3,"GLD":0.1}   current weights (cash = whatever is left)
equity.csv: date,equity  your account curve (optional; drives the drawdown brake)

Rules (method from hft.md/crash, reimplemented):
  vol target     exposure = target_vol / EWMA portfolio vol, capped
  drawdown brake 0.75 at -10%, 0.50 at -20%, 0.25 at -30% from the equity peak
  trend filter   index below its level trend-days ago -> x0.5
  exposure       product of the three, never above cap; < 1 means cut gross exposure to that share
Also: risk contribution per holding, inverse-vol weights, 1-day 99% VaR and 97.5% ES (normal and
historical), and a beta-based stress test against the S&P 500 falls of 1987, 2000-02, 2007-09,
2020 and 2022. Every rule has a failure mode; they are listed in the output.
"""
import argparse, csv, json, math

CRASHES = {  # S&P 500 closing peak -> trough, price only
    "1987 Black Monday (1987-08-25 to 1987-12-04)": (336.77, 223.92),
    "2000-02 dot-com (2000-03-24 to 2002-10-09)": (1527.46, 776.76),
    "2007-09 financial crisis (2007-10-09 to 2009-03-09)": (1565.15, 676.53),
    "2020 Covid (2020-02-19 to 2020-03-23)": (3386.15, 2237.40),
    "2022 rate shock (2022-01-03 to 2022-10-12)": (4796.56, 3577.03),
}
BRAKE = ((0.10, 0.75), (0.20, 0.50), (0.30, 0.25))


def N(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def ninv(p):
    lo, hi = -10.0, 10.0
    for _ in range(100):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if N(m) < p else (lo, m)
    return (lo + hi) / 2


def ewma_var(rs, lam):
    v = sum(r * r for r in rs[:20]) / min(20, len(rs))
    for r in rs:
        v = lam * v + (1 - lam) * r * r
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--index", default="SPY")
    ap.add_argument("--equity")
    ap.add_argument("--target-vol", type=float, default=0.10)
    ap.add_argument("--cap", type=float, default=1.5)
    ap.add_argument("--lam", type=float, default=0.94)
    ap.add_argument("--trend-days", type=int, default=252)
    ap.add_argument("--value", type=float, default=0, help="portfolio value in $ for VaR/ES in money")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.prices, newline="")))
    W = json.load(open(a.weights))
    names = [k for k in W if k in rows[0]]
    missing = [k for k in W if k not in rows[0]]
    px = {k: [float(r[k]) for r in rows] for k in rows[0] if k.lower() != "date"}
    R = {k: [v[i] / v[i - 1] - 1 for i in range(1, len(v))] for k, v in px.items()}
    T = len(rows) - 1
    if T < 60:
        raise SystemExit("need at least 60 daily closes")
    port = [sum(W[k] * R[k][t] for k in names) for t in range(T)]
    pvol = math.sqrt(ewma_var(port, a.lam) * 252)
    e_vol = min(a.cap, a.target_vol / max(pvol, 1e-9))

    dd, e_dd = None, 1.0
    if a.equity:
        eq = [float(r["equity"]) for r in csv.DictReader(open(a.equity, newline=""))]
        peak = max(eq)
        dd = 1 - eq[-1] / peak
        for lvl, m in BRAKE:
            if dd >= lvl:
                e_dd = m
    trend, e_tr = None, 1.0
    if a.index in px and len(px[a.index]) > a.trend_days:
        ix = px[a.index]
        trend = 1 if ix[-1] > ix[-1 - a.trend_days] else -1
        e_tr = 0.5 if trend < 0 else 1.0
    exposure = round(min(a.cap, e_vol * e_dd * e_tr), 3)

    # sample covariance (annualised) for risk contributions
    mu = {k: sum(R[k]) / T for k in names}
    C = {(i, j): sum((R[i][t] - mu[i]) * (R[j][t] - mu[j]) for t in range(T)) / (T - 1) * 252
         for i in names for j in names}
    Sw = {i: sum(C[(i, j)] * W[j] for j in names) for i in names}
    var = sum(W[i] * Sw[i] for i in names)
    rc = {i: round(100 * W[i] * Sw[i] / var, 1) for i in names} if var > 0 else {}
    vols = {i: math.sqrt(C[(i, i)]) for i in names}
    inv = {i: 1 / vols[i] for i in names if vols[i] > 0}
    s = sum(inv.values())
    ivw = {i: round(inv[i] / s, 3) for i in inv}

    dvol = pvol / math.sqrt(252)
    var99, es975 = ninv(0.99) * dvol, dvol * math.exp(-ninv(0.975) ** 2 / 2) / math.sqrt(2 * math.pi) / 0.025
    srt = sorted(port)
    k99 = max(1, int(0.01 * T))
    k975 = max(1, int(0.025 * T))
    hvar99, hes975 = -srt[k99 - 1], -sum(srt[:k975]) / k975

    stress = None
    if a.index in R:
        m = R[a.index]
        mm = sum(m) / T
        vm = sum((x - mm) ** 2 for x in m) / (T - 1)
        beta = {k: sum((R[k][t] - mu[k]) * (m[t] - mm) for t in range(T)) / (T - 1) / vm for k in names}
        pb = sum(W[k] * beta[k] for k in names)
        stress = dict(portfolio_beta=round(pb, 3), betas={k: round(v, 2) for k, v in beta.items()},
                      est_loss_pct={n_: round(100 * pb * (tr / pk - 1), 1) for n_, (pk, tr) in CRASHES.items()},
                      caveat="Beta from this window only; in 2022 bonds fell with stocks, and betas jump in crashes. "
                             "Use each holding's actual returns over those dates for a real test.")
    money = (lambda x: round(x * a.value, 2)) if a.value else (lambda x: None)
    print(json.dumps(dict(
        exposure_multiplier=exposure,
        parts=dict(vol_target=round(e_vol, 3), portfolio_vol_ewma=round(pvol, 4), target_vol=a.target_vol,
                   drawdown=round(dd, 4) if dd is not None else None, drawdown_brake=e_dd,
                   index_trend=trend, trend_filter=e_tr),
        action=("cut gross exposure to %.0f%% of normal" % (100 * exposure)) if exposure < 1 else
               ("room to run up to %.0f%% of normal (only if the plan allows leverage)" % (100 * exposure)
                if exposure > 1 else "hold normal size"),
        risk_contribution_pct=rc, inverse_vol_weights=ivw,
        one_day=dict(var99_pct=round(100 * var99, 2), es975_pct=round(100 * es975, 2),
                     hist_var99_pct=round(100 * hvar99, 2), hist_es975_pct=round(100 * hes975, 2),
                     var99_usd=money(var99), es975_usd=money(es975)),
        stress_test=stress, unknown_tickers=missing,
        fails_when=["Vol targeting cuts after vol rises, so it can sell near lows and miss the rebound.",
                    "Slow trend filters miss very fast crashes (Feb-Mar 2020).",
                    "Risk parity and stock/bond mixes failed in 2022 when both fell together.",
                    "Normal VaR understates fat tails; trust ES and the stress test more.",
                    "None of this predicts a crash; it limits the damage of one."]), indent=2))


if __name__ == "__main__":
    main()
