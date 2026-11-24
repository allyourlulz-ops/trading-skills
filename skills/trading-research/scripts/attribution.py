#!/usr/bin/env python3
"""Return attribution: how much of a strategy's return was market, style, and stock selection. Stdlib only.

Usage:
  attribution.py --returns port.csv --factors factors.csv [--market mkt] [--periods-per-year 252]
                 [--window 0] [--currency USD]

port.csv     date,ret                     (period returns as decimals, after fees)
factors.csv  date,mkt,<style1>,<style2>,...  (factor returns for the same dates as decimals:
             mkt = benchmark return, styles = long-short factor returns such as size, momentum,
             value, low_vol, quality; build them from MCP price data, never type them in)
Rows are matched on date; dates missing from either file are dropped and counted.

Model: ret_t = a + b_mkt*mkt_t + sum_k b_k*style_k,t + e_t, fitted by OLS (whole sample, or rolling
--window periods with each day's betas fitted on the window before it, so no look-ahead).
Contribution of each part = sum over the sample of beta*factor return; selection = a + e (what the
factors do not explain). Gate SELECTION_ALPHA needs selection t-stat >= 2, annualised information
ratio >= 0.5 and > 52% of periods with positive selection return; otherwise BETA_OR_STYLE.

Method: Barra-style decomposition as used by KTD-Fin (Zhu et al., arXiv 2605.28359, 2026), which
found LLM trading returns largely explained by market and style exposure. Own code; KTD-Fin
released no code. Gate thresholds follow common institutional practice, not that paper.
"""
import argparse, csv, json, math, sys


def read(path):
    rows = list(csv.DictReader(open(path, newline="")))
    if not rows:
        sys.exit(f"{path}: empty")
    return rows


def solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-14:
            raise ValueError("factors are collinear; drop one")
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def ols(X, y):
    k = len(X[0])
    XtX = [[sum(r[i] * r[j] for r in X) for j in range(k)] for i in range(k)]
    Xty = [sum(r[i] * yy for r, yy in zip(X, y)) for i in range(k)]
    return solve(XtX, Xty)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--returns", required=True)
    ap.add_argument("--factors", required=True)
    ap.add_argument("--market", default="mkt")
    ap.add_argument("--periods-per-year", type=float, default=252)
    ap.add_argument("--window", type=int, default=0, help="rolling fit length; 0 = whole sample")
    ap.add_argument("--currency", default="USD")
    a = ap.parse_args()

    P = {r["date"]: float(r["ret"]) for r in read(a.returns)}
    F = read(a.factors)
    names = [c for c in F[0].keys() if c != "date"]
    if a.market not in names:
        sys.exit(f"factor file has no '{a.market}' column")
    names = [a.market] + [n for n in names if n != a.market]
    dates, y, X = [], [], []
    for r in F:
        if r["date"] in P:
            dates.append(r["date"]); y.append(P[r["date"]])
            X.append([1.0] + [float(r[n]) for n in names])
    dropped = len(P) - len(dates)
    k = len(names) + 1
    if len(y) < max(30, 3 * k):
        sys.exit(f"only {len(y)} matched periods; need at least {max(30, 3 * k)}")

    contrib = {n: 0.0 for n in names}
    sel = []
    if a.window:
        if len(y) <= a.window + 10:
            sys.exit("window too long for the sample")
        last = None
        for t in range(a.window, len(y)):
            b = ols(X[t - a.window:t], y[t - a.window:t]); last = b
            fit = sum(bi * xi for bi, xi in zip(b[1:], X[t][1:]))
            for i, n in enumerate(names):
                contrib[n] += b[i + 1] * X[t][i + 1]
            sel.append(y[t] - fit)
        betas, used = last, len(y) - a.window
        total = sum(y[a.window:])
    else:
        betas = ols(X, y)
        for t in range(len(y)):
            for i, n in enumerate(names):
                contrib[n] += betas[i + 1] * X[t][i + 1]
            sel.append(y[t] - sum(bi * xi for bi, xi in zip(betas[1:], X[t][1:])))
        used, total = len(y), sum(y)

    m = sum(sel) / len(sel)
    sd = math.sqrt(sum((s - m) ** 2 for s in sel) / (len(sel) - 1)) or 1e-12
    t_stat = m / (sd / math.sqrt(len(sel)))
    ir = m / sd * math.sqrt(a.periods_per_year)
    hit = sum(1 for s in sel if s > 0) / len(sel)
    resid_var = sum((s - m) ** 2 for s in sel)
    ybar = total / used
    yy = y[-used:]
    tss = sum((v - ybar) ** 2 for v in yy) or 1e-12
    verdict = "SELECTION_ALPHA" if (t_stat >= 2 and ir >= 0.5 and hit > 0.52) else "BETA_OR_STYLE"
    style = sum(v for n, v in contrib.items() if n != a.market)
    print(json.dumps({
        "verdict": verdict, "periods": used, "dates_dropped": dropped,
        "basis": "sum of period returns (arithmetic), after fees as supplied",
        "total_return_sum": round(total, 6),
        "contribution": {"market": round(contrib[a.market], 6), "style": round(style, 6),
                          "by_style": {n: round(v, 6) for n, v in contrib.items() if n != a.market},
                          "selection": round(sum(sel), 6)},
        "betas": {n: round(b, 4) for n, b in zip(names, betas[1:])},
        "beta_basis": "last rolling window" if a.window else "whole sample",
        "selection_t_stat": round(t_stat, 2), "selection_ir_annual": round(ir, 2),
        "selection_hit_rate": round(hit, 3), "r_squared": round(1 - resid_var / tss, 3),
        "gates": {"t_stat_min": 2, "ir_min": 0.5, "hit_rate_min": 0.52},
        "note": "high total return with BETA_OR_STYLE means the factors explain it; a cheap ETF mix would have done the same."
    }, indent=1))


if __name__ == "__main__":
    main()
