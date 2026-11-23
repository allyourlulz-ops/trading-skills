#!/usr/bin/env python3
"""Monte Carlo permutation test + parameter plateau check. Stdlib only.

Asks: does the optimised strategy beat the same optimisation run on price paths
with the same start, end and bar-return distribution but no real patterns?
Prices come from whichever data MCP server you use (OpenBB, Alpaca, CCXT...):
save closes to CSV first; this script makes no network calls.

Input CSV: date,close (oldest first). Strategy: a .py file defining
    def positions(closes, **params) -> list of -1/0/1, same length as closes
where positions[i] is the position held over bar i -> i+1 (decided at bar i close).
Built-in default: EMA crossover (fast, slow).

Modes
  insample      optimise on the whole file; repeat on --perms shuffled paths
  walkforward   rolling train/test; only bars after the first train window are shuffled
Usage:
  permutation_test.py --prices btc.csv --grid '{"fast":[5,10,20],"slow":[50,100,200]}'
  permutation_test.py --prices btc.csv --strategy my.py --grid '{...}' \
      --mode walkforward --train 1008 --test 21 --perms 200 --cost-bps 5
Prints JSON: real score, permutation p-value, verdict, plateau report.
"""
import argparse, csv, importlib.util, itertools, json, math, random


def ema(xs, n):
    k, out, e = 2 / (n + 1), [], xs[0]
    for x in xs:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def ema_cross(closes, fast=20, slow=50):
    if fast >= slow:
        return None
    f, s = ema(closes, fast), ema(closes, slow)
    return [1 if a > b else -1 for a, b in zip(f, s)]


def bar_returns(closes, pos, cost):
    """Bar-level log returns of the position, minus cost on each change."""
    out, prev = [], 0
    for i in range(len(closes) - 1):
        r = pos[i] * math.log(closes[i + 1] / closes[i]) - cost * abs(pos[i] - prev)
        prev = pos[i]
        out.append(r)
    return out


def profit_factor(rets):
    g = sum(r for r in rets if r > 0)
    l = -sum(r for r in rets if r < 0)
    return g / l if l > 0 else (float("inf") if g > 0 else 0.0)


def combos(grid):
    keys = sorted(grid)
    for vals in itertools.product(*(grid[k] for k in keys)):
        yield dict(zip(keys, vals))


def optimise(closes, fn, grid, cost):
    best, table = (None, -1.0), {}
    for p in combos(grid):
        pos = fn(closes, **p)
        if pos is None:
            continue
        sc = profit_factor(bar_returns(closes, pos, cost))
        table[json.dumps(p, sort_keys=True)] = sc
        if sc > best[1]:
            best = (p, sc)
    return best, table


def permute(closes, start, rng):
    """Shuffle log bar returns after index `start`; same start and end price."""
    lr = [math.log(closes[i + 1] / closes[i]) for i in range(start, len(closes) - 1)]
    rng.shuffle(lr)
    out = closes[: start + 1]
    for r in lr:
        out.append(out[-1] * math.exp(r))
    return out


def walkforward(closes, fn, grid, cost, train, test):
    rets, i = [], train
    while i < len(closes) - 1:
        (p, _), _ = optimise(closes[i - train:i + 1], fn, grid, cost)
        if p is None:
            break
        pos = fn(closes[: min(len(closes), i + test + 1)], **p)  # history up to segment end only
        seg = bar_returns(closes[: min(len(closes), i + test + 1)], pos, cost)[i:]
        rets.extend(seg)
        i += test
    return profit_factor(rets), len(rets)


def plateau(table, grid, best):
    """Neighbours one grid step away from the best; a real edge keeps most of its score."""
    if best is None:
        return {}
    keys, nb = sorted(grid), []
    for k in keys:
        vals = grid[k]
        j = vals.index(best[k])
        for jj in (j - 1, j + 1):
            if 0 <= jj < len(vals):
                q = dict(best); q[k] = vals[jj]
                s = table.get(json.dumps(q, sort_keys=True))
                if s is not None:
                    nb.append(s)
    top = table[json.dumps(best, sort_keys=True)]
    if not nb or top <= 0:
        return dict(neighbours=0, verdict="UNKNOWN")
    ratio = (sum(nb) / len(nb)) / top
    profitable = sum(1 for s in table.values() if s > 1) / len(table)
    return dict(neighbours=len(nb), neighbour_score_ratio=round(ratio, 3),
                share_of_grid_profitable=round(profitable, 3),
                verdict="PLATEAU" if ratio >= 0.8 and profitable >= 0.5 else
                        ("SPIKE" if ratio < 0.6 else "MIXED"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--strategy")
    ap.add_argument("--grid", required=True, help="JSON dict of param -> list of values")
    ap.add_argument("--mode", choices=["insample", "walkforward"], default="insample")
    ap.add_argument("--perms", type=int, default=1000)
    ap.add_argument("--train", type=int, default=1008, help="bars per training window")
    ap.add_argument("--test", type=int, default=21, help="bars traded before re-optimising")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="cost per unit of position change")
    ap.add_argument("--alpha", type=float, default=None, help="pass bar; default 0.01 in-sample, 0.05 walk-forward")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    with open(a.prices, newline="") as fh:
        closes = [float(r["close"]) for r in csv.DictReader(fh)]
    grid = json.loads(a.grid)
    fn = ema_cross
    if a.strategy:
        spec = importlib.util.spec_from_file_location("strat", a.strategy)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        fn = mod.positions
    cost, rng = a.cost_bps / 1e4, random.Random(a.seed)

    if a.mode == "insample":
        (bp, real), table = optimise(closes, fn, grid, cost)
        beat = sum(1 for _ in range(a.perms)
                   if optimise(permute(closes, 0, rng), fn, grid, cost)[0][1] >= real)
        alpha = a.alpha or 0.01
        extra = dict(best_params=bp, plateau=plateau(table, grid, bp))
    else:
        if len(closes) <= a.train + a.test:
            raise SystemExit("not enough bars for one train+test window")
        real, n = walkforward(closes, fn, grid, cost, a.train, a.test)
        beat = sum(1 for _ in range(a.perms)
                   if walkforward(permute(closes, a.train, rng), fn, grid, cost, a.train, a.test)[0] >= real)
        alpha = a.alpha or 0.05
        extra = dict(oos_bars=n, note="Use alpha 0.05 for ~1 year out of sample, 0.01 for 2+ years.")
    p = (beat + 1) / (a.perms + 1)
    print(json.dumps(dict(mode=a.mode, bars=len(closes), metric="profit_factor", real_score=round(real, 4),
                          perms=a.perms, perms_beating_real=beat, p_value=round(p, 4), alpha=alpha,
                          verdict="PASS" if p < alpha else "FAIL", **extra,
                          notes=["Re-run every gate after any change to the strategy or grid.",
                                 "Shuffling bar returns kills trends and autocorrelation; it does not model "
                                 "volatility clustering, so treat a near-miss as a FAIL.",
                                 "PASS earns a paper account, not live money."]), indent=2, default=str))


if __name__ == "__main__":
    main()
