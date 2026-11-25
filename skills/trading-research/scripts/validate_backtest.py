#!/usr/bin/env python3
"""Backtest validation: hard gates + overfitting statistics + a benchmark test that fits the sleeve.
Stdlib only.
Usage: validate_backtest.py --equity equity.csv [--benchmark bench.csv] [--trades trades.csv]
         [--trials auto|N] [--family NAME] [--ledger trials.jsonl]
         [--sleeve auto|directional|neutral] [--blend 0.30] [--periods 252] [--seed 42]
equity.csv / bench.csv: date,value (header row); rows are matched on date. trades.csv: one column
'pnl' or 'return' per closed trade.
--trials auto (default) reads scripts/trial_ledger.py; with no ledger it assumes 1 and says so.
Benchmark test (needs --benchmark), three parts:
  risk_adjusted  net Sharpe > benchmark Sharpe
  marginal       a (1-blend)/blend mix of benchmark and strategy, rebalanced each period, has a higher
                 Sharpe AND a smaller max drawdown than 100% benchmark: does it add to the book?
  directional    total return >= benchmark; only for directional sleeves. A market-neutral or hedged
                 sleeve (auto: |beta to benchmark| < 0.3) is not asked to beat a rising index.
PASS = deflated Sharpe prob >= 0.95 and every benchmark part that applies passes; otherwise WEAK.
"""
import argparse, csv, json, math, os, random, statistics as S, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trial_ledger import resolve_trials


def load_dated(path):
    out = []
    with open(path) as f:
        r = csv.reader(f); next(r)
        for row in r:
            if row:
                try: out.append((row[0], float(row[-1])))
                except ValueError: pass
    return out


def align(a_rows, b_rows):
    bd = dict(b_rows)
    common = [(d, v, bd[d]) for d, v in a_rows if d in bd]
    if len(common) >= 30:
        return [c[1] for c in common], [c[2] for c in common], "date"
    n = min(len(a_rows), len(b_rows))
    return [v for _, v in a_rows[:n]], [v for _, v in b_rows[:n]], "index (no common dates)"


def beta(r, b):
    mb, mr = S.mean(b), S.mean(r)
    vb = sum((x - mb) ** 2 for x in b)
    return sum((x - mb) * (y - mr) for x, y in zip(b, r)) / vb if vb else 0.0


def equity_from(r):
    v, out = 1.0, [1.0]
    for x in r:
        v *= 1 + x; out.append(v)
    return out

def load_series(path):
    with open(path) as f:
        r = csv.reader(f); hdr = next(r)
        vals = []
        for row in r:
            if not row: continue
            try: vals.append(float(row[-1]))
            except ValueError: vals.append(float("nan"))
    return vals

def rets(v): return [v[i] / v[i - 1] - 1 for i in range(1, len(v)) if v[i - 1]]

def sharpe(r, p):
    if len(r) < 2: return 0.0
    sd = S.stdev(r); return (S.mean(r) / sd) * math.sqrt(p) if sd > 0 else 0.0

def sortino(r, p):
    dn = [x for x in r if x < 0]
    if len(dn) < 2: return float("inf") if S.mean(r) > 0 else 0.0
    dd = math.sqrt(sum(x * x for x in dn) / len(r)); return S.mean(r) / dd * math.sqrt(p) if dd else 0.0

def max_dd(v):
    peak, mdd, dur, cur = v[0], 0.0, 0, 0
    for x in v:
        if x >= peak: peak, cur = x, 0
        else: cur += 1
        mdd = min(mdd, x / peak - 1); dur = max(dur, cur)
    return mdd, dur

def norm_cdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def norm_ppf(p):
    lo, hi = -10.0, 10.0
    for _ in range(100):
        m = (lo + hi) / 2
        if norm_cdf(m) < p: lo = m
        else: hi = m
    return (lo + hi) / 2

def t_pvalue(x):
    n = len(x)
    if n < 2 or S.stdev(x) == 0: return None
    t = S.mean(x) / (S.stdev(x) / math.sqrt(n))
    return round(2 * (1 - norm_cdf(abs(t))), 4)  # normal approx; fine for n>=30

def skew_kurt(r):
    m, sd = S.mean(r), S.pstdev(r)
    if sd == 0: return 0.0, 3.0
    n = len(r)
    return sum(((x - m) / sd) ** 3 for x in r) / n, sum(((x - m) / sd) ** 4 for x in r) / n

def deflated_sharpe(r, trials):
    """Bailey & Lopez de Prado DSR on per-period Sharpe."""
    n = len(r); sr = S.mean(r) / S.stdev(r) if S.stdev(r) else 0
    g3, g4 = skew_kurt(r)
    emc = 0.5772156649
    var_sr = (1 - g3 * sr + (g4 - 1) / 4 * sr * sr) / (n - 1)
    sd_sr = math.sqrt(max(var_sr, 1e-12))
    if trials > 1:
        sr0 = sd_sr * ((1 - emc) * norm_ppf(1 - 1 / trials) + emc * norm_ppf(1 - 1 / (trials * math.e)))
    else:
        sr0 = 0.0
    z = (sr - sr0) / sd_sr
    return round(norm_cdf(z), 4), sr0

def bootstrap_sharpe_ci(r, p, n=1000, seed=42, block=5):
    rnd = random.Random(seed); out = []; L = len(r)
    for _ in range(n):
        s = []
        while len(s) < L:
            i = rnd.randrange(0, max(1, L - block)); s.extend(r[i:i + block])
        out.append(sharpe(s[:L], p))
    out.sort(); return round(out[int(0.025 * n)], 3), round(out[int(0.975 * n)], 3)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", required=True); ap.add_argument("--benchmark"); ap.add_argument("--trades")
    ap.add_argument("--trials", default="auto", help="auto (trial ledger) or the number of variants tried")
    ap.add_argument("--family"); ap.add_argument("--ledger")
    ap.add_argument("--sleeve", choices=["auto", "directional", "neutral"], default="auto")
    ap.add_argument("--blend", type=float, default=0.30)
    ap.add_argument("--periods", type=int, default=252); ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    eq = load_series(a.equity); gates = []
    if len(eq) < 30: gates.append("fewer than 30 equity points")
    if any(math.isnan(x) for x in eq): gates.append("NaN in equity curve")
    trades = []
    if a.trades:
        with open(a.trades) as f:
            rd = csv.DictReader(f); col = "pnl" if "pnl" in rd.fieldnames else "return"
            trades = [float(row[col]) for row in rd if row.get(col)]
        if not trades: gates.append("zero trades")
    if gates:
        print(json.dumps({"verdict": "FAIL_GATES", "gates": gates}, indent=2)); sys.exit(2)
    trials, tsrc = resolve_trials(a.trials, a.ledger, a.family)
    a.trials = trials
    r = rets(eq); years = len(r) / a.periods
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if years > 0 and eq[0] > 0 else None
    mdd, mdd_dur = max_dd(eq)
    dsr, sr0 = deflated_sharpe(r, max(1, a.trials))
    res = {"periods": len(r), "years": round(years, 2), "total_return": round(eq[-1] / eq[0] - 1, 4),
           "cagr": round(cagr, 4) if cagr is not None else None, "sharpe": round(sharpe(r, a.periods), 3),
           "sortino": round(sortino(r, a.periods), 3), "max_drawdown": round(mdd, 4), "max_dd_duration_periods": mdd_dur,
           "sharpe_95ci_block_bootstrap": bootstrap_sharpe_ci(r, a.periods, seed=a.seed),
           "mean_return_pvalue": t_pvalue(r), "trials": a.trials, "trials_source": tsrc, "deflated_sharpe_prob": dsr}
    if trades:
        w = [t for t in trades if t > 0]; l = [t for t in trades if t <= 0]
        res.update({"trades": len(trades), "win_rate": round(len(w) / len(trades), 3),
                    "profit_factor": round(sum(w) / abs(sum(l)), 3) if l and sum(l) else None,
                    "expectancy": round(S.mean(trades), 4), "trade_pvalue": t_pvalue(trades)})
        if len(trades) < 30: res.setdefault("warnings", []).append("fewer than 30 trades: statistics unreliable")
    bt = {}
    if a.benchmark:
        se, be, how = align(load_dated(a.equity), load_dated(a.benchmark))
        rs, rb = rets(se), rets(be)
        res["benchmark_aligned_on"] = how
        res["buy_and_hold_return"] = round(be[-1] / be[0] - 1, 4)
        res["excess_vs_buy_and_hold"] = round((se[-1] / se[0] - 1) - (be[-1] / be[0] - 1), 4)
        b_ = beta(rs, rb)
        sleeve = a.sleeve if a.sleeve != "auto" else ("neutral" if abs(b_) < 0.3 else "directional")
        mix = [(1 - a.blend) * y + a.blend * x for x, y in zip(rs, rb)]
        sh_s, sh_b, sh_m = sharpe(rs, a.periods), sharpe(rb, a.periods), sharpe(mix, a.periods)
        dd_b, dd_m = max_dd(equity_from(rb))[0], max_dd(equity_from(mix))[0]
        bt = {"sleeve": sleeve, "sleeve_source": a.sleeve, "beta_to_benchmark": round(b_, 3),
              "benchmark_sharpe": round(sh_b, 3), "strategy_sharpe": round(sh_s, 3),
              "risk_adjusted": {"pass": sh_s > sh_b, "rule": "net Sharpe > benchmark Sharpe"},
              "marginal": {"pass": sh_m > sh_b and dd_m > dd_b, "blend": a.blend, "blend_sharpe": round(sh_m, 3),
                           "blend_max_drawdown": round(dd_m, 4), "benchmark_max_drawdown": round(dd_b, 4),
                           "rule": f"{round(1 - a.blend, 2)}/{a.blend} benchmark/strategy mix beats benchmark on Sharpe and drawdown"}}
        if sleeve == "directional":
            bt["directional"] = {"pass": res["excess_vs_buy_and_hold"] >= 0, "rule": "total return >= benchmark"}
        else:
            bt["directional"] = {"pass": None, "rule": "skipped: market-neutral or hedged sleeve"}
        res["benchmark_test"] = bt
    warn = res.setdefault("warnings", [])
    if tsrc == "none": warn.append("no trial ledger found: DSR assumes 1 trial; log every variant with trial_ledger.py")
    if tsrc == "typed": warn.append("trials typed by hand; prefer --trials auto from the trial ledger")
    if dsr < 0.95: warn.append(f"deflated Sharpe prob {dsr} < 0.95 after {a.trials} trials: likely overfit or not significant")
    if res["sharpe"] > 3: warn.append("Sharpe > 3: check for look-ahead bias or missing costs")
    if not a.benchmark: warn.append("no benchmark: risk-adjusted and marginal tests not run")
    warn.append("p-values assume i.i.d. returns and are optimistic; backtests overstate live results")
    failed = [k for k in ("risk_adjusted", "marginal", "directional") if bt.get(k, {}).get("pass") is False]
    res["benchmark_failed"] = failed
    res["verdict"] = "PASS" if dsr >= 0.95 and not failed else "WEAK"
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
