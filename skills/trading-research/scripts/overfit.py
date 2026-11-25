#!/usr/bin/env python3
"""Overfitting toolkit for a family of strategy variants. Stdlib only, no network.
Own implementation of published methods (Bailey, Borwein, Lopez de Prado & Zhu 2014 "The Probability
of Backtest Overfitting"; Bailey & Lopez de Prado 2014 "The Deflated Sharpe Ratio"; Lopez de Prado 2018
purged/embargoed and combinatorial purged cross-validation). No third-party code copied.

Usage:
  overfit.py pbo   --returns variants.csv [--blocks 10]
  overfit.py dsr   --returns variants.csv [--pick NAME] [--periods 252] [--trials auto|N] [--family F]
  overfit.py cpcv  --n 1000 [--groups 6] [--test-groups 2] [--horizon 5] [--embargo 0.01]
variants.csv: first column date, then one column of per-period returns per variant (every variant
you tried, including the losers; dropping them is what makes PBO lie).
Prints JSON. Gates (references/backtesting.md): PBO <= 0.20 and DSR >= 0.95 to promote a variant.
"""
import argparse, csv, itertools, json, math, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_ledger import resolve_trials
from statistics import NormalDist

ND = NormalDist()


def load(path):
    with open(path) as f:
        rows = list(csv.reader(f))
    names = rows[0][1:]
    cols = [[] for _ in names]
    for r in rows[1:]:
        if not r or len(r) < len(names) + 1:
            continue
        for j, v in enumerate(r[1:]):
            cols[j].append(float(v) if v.strip() else 0.0)
    if len(names) < 2:
        raise SystemExit("need at least 2 variant columns")
    return names, cols


def sharpe(x):
    if len(x) < 2:
        return 0.0
    s = statistics.pstdev(x)
    return statistics.fmean(x) / s if s > 0 else 0.0


def pbo(names, cols, blocks):
    T = len(cols[0])
    blocks -= blocks % 2
    if blocks < 4 or T < blocks * 5:
        raise SystemExit("need an even --blocks >= 4 and at least 5 rows per block")
    size = T // blocks
    idx = [list(range(b * size, (b + 1) * size if b < blocks - 1 else T)) for b in range(blocks)]
    N, lams, degr, best_counts = len(cols), [], [], {}
    for combo in itertools.combinations(range(blocks), blocks // 2):
        ins = [i for b in combo for i in idx[b]]
        oos = [i for b in range(blocks) if b not in combo for i in idx[b]]
        sr_in = [sharpe([c[i] for i in ins]) for c in cols]
        sr_out = [sharpe([c[i] for i in oos]) for c in cols]
        best = max(range(N), key=lambda j: sr_in[j])
        best_counts[names[best]] = best_counts.get(names[best], 0) + 1
        rank = sorted(sr_out).index(sr_out[best]) + 1          # 1 = worst OOS
        w = rank / (N + 1)
        lams.append(math.log(w / (1 - w)))
        degr.append((sr_in[best], sr_out[best]))
    p = sum(1 for l in lams if l <= 0) / len(lams)
    slope = statistics.linear_regression([d[0] for d in degr], [d[1] for d in degr]).slope if len(degr) > 2 else None
    return dict(test="pbo", variants=N, rows=T, blocks=blocks, splits=len(lams), pbo=round(p, 3),
                median_logit=round(statistics.median(lams), 3),
                oos_sharpe_of_is_best_mean=round(statistics.fmean(d[1] for d in degr), 4),
                is_to_oos_slope=None if slope is None else round(slope, 3),
                most_often_is_best=sorted(best_counts.items(), key=lambda kv: -kv[1])[:3],
                verdict="PASS" if p <= 0.20 else ("CAUTION" if p <= 0.50 else "FAIL"),
                note="PBO is the share of splits where the in-sample winner lands in the bottom half out of sample.")


def moments(x):
    m, s = statistics.fmean(x), statistics.pstdev(x)
    if s == 0:
        return 0.0, 3.0
    sk = sum(((v - m) / s) ** 3 for v in x) / len(x)
    ku = sum(((v - m) / s) ** 4 for v in x) / len(x)
    return sk, ku


def dsr(names, cols, pick, periods, trials=None):
    srs = [sharpe(c) for c in cols]
    j = names.index(pick) if pick else max(range(len(cols)), key=lambda k: srs[k])
    x, sr, N, T = cols[j], srs[j], max(len(cols), trials or 0), len(cols[j])
    var = statistics.pvariance(srs)
    g = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - g) * ND.inv_cdf(1 - 1 / N) + g * ND.inv_cdf(1 - 1 / (N * math.e))) if var > 0 else 0.0
    sk, ku = moments(x)
    denom = 1 - sk * sr + (ku - 1) / 4 * sr * sr
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(denom) if denom > 0 else 0.0
    d = ND.cdf(z)
    psr = ND.cdf(sr * math.sqrt(T - 1) / math.sqrt(denom)) if denom > 0 else 0.0
    return dict(test="dsr", variant=names[j], trials=N, rows=T, sharpe_per_period=round(sr, 4),
                sharpe_annual=round(sr * math.sqrt(periods), 3),
                expected_max_sharpe_from_luck_per_period=round(sr0, 4), skew=round(sk, 3), kurtosis=round(ku, 3),
                probabilistic_sharpe=round(psr, 3), deflated_sharpe=round(d, 3),
                verdict="PASS" if d >= 0.95 else "FAIL",
                note="DSR is the probability the true Sharpe beats the best Sharpe expected from this many tries by luck.")


def cpcv(n, groups, k, horizon, embargo):
    if not (2 <= k < groups <= n):
        raise SystemExit("need 2 <= test-groups < groups <= n")
    size = n // groups
    bounds = [(g * size, (g + 1) * size if g < groups - 1 else n) for g in range(groups)]
    emb = int(math.ceil(n * embargo))
    splits = []
    for combo in itertools.combinations(range(groups), k):
        test = [bounds[g] for g in combo]
        banned = set()
        for a, b in test:
            banned.update(range(max(0, a - horizon), min(n, b + emb)))   # purge labels overlapping test, embargo after
        train, start = [], None
        for i in range(n + 1):
            ok = i < n and i not in banned
            if ok and start is None:
                start = i
            if not ok and start is not None:
                train.append([start, i]); start = None
        splits.append(dict(test_groups=list(combo), test=[list(t) for t in test], train=train,
                           train_rows=sum(b - a for a, b in train)))
    paths = math.comb(groups, k) * k // groups
    return dict(test="cpcv", n=n, groups=groups, test_groups=k, horizon=horizon, embargo_rows=emb,
                splits=len(splits), backtest_paths=paths, folds=splits,
                note="Ranges are [start, end) row indices. Fit on train, score on test, stitch test pieces into paths.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pbo", "dsr", "cpcv"])
    ap.add_argument("--returns")
    ap.add_argument("--blocks", type=int, default=10)
    ap.add_argument("--pick")
    ap.add_argument("--periods", type=int, default=252)
    ap.add_argument("--n", type=int)
    ap.add_argument("--groups", type=int, default=6)
    ap.add_argument("--test-groups", type=int, default=2)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--embargo", type=float, default=0.01)
    ap.add_argument("--trials", default="auto", help="dsr: auto = max(columns, trial ledger count), or a number")
    ap.add_argument("--family"); ap.add_argument("--ledger")
    a = ap.parse_args()
    if a.cmd == "cpcv":
        if not a.n:
            raise SystemExit("--n required")
        out = cpcv(a.n, a.groups, a.test_groups, a.horizon, a.embargo)
    else:
        if not a.returns:
            raise SystemExit("--returns required")
        names, cols = load(a.returns)
        out = pbo(names, cols, a.blocks) if a.cmd == "pbo" else dsr(names, cols, a.pick, a.periods, resolve_trials(a.trials, a.ledger, a.family)[0])
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
