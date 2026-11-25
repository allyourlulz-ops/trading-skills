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
This flag mode is a statistics report used by pipeline.py. It does not check lookahead, survivorship,
same-bar fills, walk-forward, cost sweep, regimes or train-cutoff leakage, so its output carries
"rigor": "not checked". The gate for promotion is --manifest mode (pass | fail, fail closed).
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
    return None, None, f"only {len(common)} common dates (need 30); pairing rows by position would compare different days"


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
        r = csv.reader(f); next(r)
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

def deflated_sharpe(r, trials, trial_sharpes=None):
    """Bailey & Lopez de Prado (2014) DSR on per-period Sharpe.
    SR0 = sqrt(V) * ((1-g) * Phi^-1(1-1/N) + g * Phi^-1(1-1/(N e))), g = Euler-Mascheroni.
    V is the variance of the N trials' Sharpe ratios when trial_sharpes is given (the paper's form);
    otherwise this series' estimation variance stands in for it (exact only if every trial has the
    same length and true SR 0), and the caller must say so."""
    n = len(r); sr = S.mean(r) / S.stdev(r) if S.stdev(r) else 0
    g3, g4 = skew_kurt(r)
    emc = 0.5772156649
    var_sr = (1 - g3 * sr + (g4 - 1) / 4 * sr * sr) / (n - 1)
    sd_sr = math.sqrt(max(var_sr, 1e-12))
    if trial_sharpes and len(trial_sharpes) >= 2:
        trials = len(trial_sharpes)
        sd_trials = math.sqrt(max(S.variance(trial_sharpes), 1e-12))
    else:
        sd_trials = sd_sr
    if trials > 1:
        sr0 = sd_trials * ((1 - emc) * norm_ppf(1 - 1 / trials) + emc * norm_ppf(1 - 1 / (trials * math.e)))
    else:
        sr0 = 0.0
    z = (sr - sr0) / sd_sr
    return round(norm_cdf(z), 4), sr0

def bootstrap_sharpe_ci(r, p, n=1000, seed=42, block=5):
    rnd = random.Random(seed); out = []; L = len(r)
    for _ in range(n):
        s = []
        while len(s) < L:
            i = rnd.randrange(0, max(1, L - block + 1)); s.extend(r[i:i + block])
        out.append(sharpe(s[:L], p))
    out.sort(); return round(out[int(0.025 * n)], 3), round(out[int(0.975 * n)], 3)

# ---------------------------------------------------------------------------------------------
# Rigor mode: validate_backtest.py --manifest manifest.json   (fail closed; verdict pass | fail)
# ---------------------------------------------------------------------------------------------
RIGOR_DOC = """manifest.json (paths relative to the manifest):
  {"strategy": "mom12_1", "periods_per_year": 252, "timeframe": "1d",
   "gross_equity": "gross.csv",          # date,value before costs
   "net_equity": "net.csv",              # date,value after fees AND slippage
   "turnover": "turnover.csv",           # date,turnover  (one-way fraction of capital traded; cost = 2 x turnover x bps)
   "costs": {"fee_bps": 1, "slippage_bps": 4},   # both required; both 0 needs "zero_cost_reason"
   "benchmark": "bench.csv",             # date,value
   "trades": "trades.csv",               # signal_time,entry_time,exit_time,exit_reason,stop,target,exit_bar_high,exit_bar_low,side
   "trials": 12, "trial_sharpes": [...], # trials tried; optional per-period Sharpe of every trial (exact DSR)
   "universe": {"single_instrument": true} | {"verdict": "OK", "includes_delisted": true},   # universe.py result
   "walk_forward": {"folds": [{"train_start","train_end","test_start","test_end"}, ...]},   # >= 3, ISO dates
   "regimes": "regimes.csv",             # date,label  (regime.py output)
   "llm_in_loop": false, "model_train_cutoff": "2025-03-01", "masked": false}
Checks (each pass | fail, any fail -> verdict fail; a missing input is a fail, never a skip):
  alignment     dates parse, strictly increasing, gross/net/benchmark/turnover share >= 95% of dates
  lookahead     every trade enters on a later bar than its signal; exit not before entry
  same_bar      a bar that touched both stop and target may not be booked as the target (stop first)
  survivorship  single instrument, or a universe.py verdict OK that includes delisted names
  costs         fees and slippage both declared; net equals gross minus 2 x turnover x (fee+slippage) within 0.1 bp a period
  walk_forward  >= 3 folds, each test after its train, tests non-overlapping; >= 50% of folds have net Sharpe > 0
  deflated_sharpe  DSR prob >= 0.95 at the declared trial count
  cost_sweep    net Sharpe and net return > 0 at 1x, 2x and 3x costs
  regimes       >= 2 regimes with >= 63 periods each; no single regime supplies more than 100% of the log return
  train_cutoff  share of the test window on or before the model's training cutoff; LLM in loop: must be 0
                (or masked with mask.py, which turns it into a warning); no LLM: not applicable, said so
"""


class Missing(Exception):
    pass


def _req(m, k):
    if m.get(k) in (None, "", []):
        raise Missing(k)
    return m[k]


def _dated(base, rel):
    rows = load_dated(os.path.join(base, rel))
    if not rows:
        raise Missing(rel + " (empty)")
    return rows


def _d(s):
    from datetime import date
    return date.fromisoformat(str(s)[:10])


def _ts(s):
    from datetime import datetime as _dt
    return _dt.fromisoformat(str(s).replace("Z", "+00:00"))


def _sharpe_of(vals, p):
    r = rets(vals)
    return sharpe(r, p) if len(r) >= 2 else 0.0


def rigor(path):
    base = os.path.dirname(os.path.abspath(path))
    m = json.load(open(path))
    checks, reasons, metrics = {}, [], {}

    def put(name, ok, **kw):
        checks[name] = dict(status="pass" if ok else "fail", **kw)
        if not ok:
            reasons.append(f"{name}: {kw.get('why', 'failed')}")

    def missing(name, k):
        put(name, False, why=f"missing input {k}")

    p = int(m.get("periods_per_year") or 0)
    if p <= 0:
        missing("alignment", "periods_per_year")
        p = 252
    # alignment
    series = {}
    try:
        for k in ("gross_equity", "net_equity", "benchmark", "turnover"):
            series[k] = _dated(base, _req(m, k))
        bad = []
        for k, rows in series.items():
            ds = [r[0] for r in rows]
            try:
                parsed = [_d(x) for x in ds]
            except ValueError:
                bad.append(f"{k}: unparseable date"); continue
            if any(b <= a for a, b in zip(parsed, parsed[1:])):
                bad.append(f"{k}: dates not strictly increasing (duplicate or unsorted)")
            if any(math.isnan(v) for _, v in rows):
                bad.append(f"{k}: NaN values")
        sets = {k: {r[0] for r in v} for k, v in series.items()}
        ref = sets["net_equity"]
        for k, sset in sets.items():
            share = len(ref & sset) / max(len(ref), 1)
            if share < 0.95:
                bad.append(f"{k} shares {share:.0%} of net_equity dates (< 95%)")
        common = sorted(set.intersection(*sets.values()))
        if len(common) < 30:
            bad.append(f"only {len(common)} common dates")
        put("alignment", not bad, why="; ".join(bad) or None, common_dates=len(common))
    except Missing as e:
        missing("alignment", str(e)); common = []
    S_ = {k: dict(v) for k, v in series.items()}
    net = [S_["net_equity"][d] for d in common] if common else []
    gross = [S_["gross_equity"][d] for d in common] if common else []
    bench = [S_["benchmark"][d] for d in common] if common else []
    turn = [S_["turnover"][d] for d in common] if common else []
    if len(net) >= 3:
        rn = rets(net)
        metrics.update(net_sharpe=round(sharpe(rn, p), 3), net_total_return=round(net[-1] / net[0] - 1, 4),
                       max_drawdown=round(max_dd(net)[0], 4), benchmark_sharpe=round(_sharpe_of(bench, p), 3))
    # lookahead + same_bar
    try:
        with open(os.path.join(base, _req(m, "trades"))) as f:
            T = list(csv.DictReader(f))
        if not T:
            raise Missing("trades (no rows)")
        look, amb, nobar = [], [], 0
        for i, t in enumerate(T):
            try:
                st, en, ex = _ts(t["signal_time"]), _ts(t["entry_time"]), _ts(t["exit_time"])
            except (KeyError, ValueError):
                look.append(f"row {i + 1}: signal_time/entry_time/exit_time missing or not ISO"); continue
            if en <= st:
                look.append(f"row {i + 1}: entry {t['entry_time']} not after signal {t['signal_time']}")
            if ex < en:
                look.append(f"row {i + 1}: exit before entry")
            try:
                hi, lo = float(t["exit_bar_high"]), float(t["exit_bar_low"])
                stop, tgt = float(t["stop"]), float(t["target"])
            except (KeyError, ValueError, TypeError):
                nobar += 1; continue
            long_ = t.get("side", "long") == "long"
            both = (lo <= stop and hi >= tgt) if long_ else (hi >= stop and lo <= tgt)
            if both and t.get("exit_reason") == "target":
                amb.append(f"row {i + 1}")
        put("lookahead", not look, why="; ".join(look[:5]) or None, trades=len(T))
        sb_ok = not amb and nobar == 0
        why = []
        if amb: why.append(f"{len(amb)} trades booked at target on a bar that also hit the stop ({', '.join(amb[:5])})")
        if nobar: why.append(f"{nobar} trades lack stop/target/exit_bar_high/exit_bar_low, so ambiguity cannot be ruled out")
        put("same_bar", sb_ok, why="; ".join(why) or None, policy="stop first")
    except Missing as e:
        missing("lookahead", str(e)); missing("same_bar", str(e))
    # survivorship
    u = m.get("universe")
    if not u:
        missing("survivorship", "universe")
    elif u.get("single_instrument") is True:
        put("survivorship", True, basis="single instrument")
    else:
        ok = u.get("verdict") == "OK" and u.get("includes_delisted") is True
        put("survivorship", ok, why=None if ok else f"universe verdict {u.get('verdict')}, includes_delisted {u.get('includes_delisted')}")
    # costs
    c = m.get("costs") or {}
    cost_bps = None
    if "fee_bps" not in c or "slippage_bps" not in c:
        missing("costs", "costs.fee_bps and costs.slippage_bps")
    else:
        cost_bps = float(c["fee_bps"]) + float(c["slippage_bps"])
        why = []
        if cost_bps == 0 and not c.get("zero_cost_reason"):
            why.append("fees and slippage both 0 with no zero_cost_reason")
        if len(net) >= 3:
            rg, rn = rets(gross), rets(net)
            implied = [g - 2 * tv * cost_bps / 1e4 for g, tv in zip(rg, turn[1:])]
            gap = max(abs(a_ - b_) for a_, b_ in zip(implied, rn)) if rn else 0
            if gap > 0.00001:
                why.append(f"net differs from gross - 2 x turnover x {cost_bps} bps by up to {gap * 1e4:.1f} bps a period")
        put("costs", not why, why="; ".join(why) or None, round_trip_bps=None if cost_bps is None else 2 * cost_bps)
    # walk-forward
    wf = (m.get("walk_forward") or {}).get("folds")
    if not wf:
        missing("walk_forward", "walk_forward.folds (a single split is not walk-forward)")
    else:
        why, fold_sh = [], []
        try:
            F = sorted(wf, key=lambda f: _d(f["test_start"]))
            for i, f in enumerate(F):
                if _d(f["test_start"]) <= _d(f["train_end"]):
                    why.append(f"fold {i + 1}: test starts on or before train end")
                if i and _d(f["test_start"]) <= _d(F[i - 1]["test_end"]):
                    why.append(f"fold {i + 1}: test overlaps fold {i}")
                seg = [S_["net_equity"][d] for d in common if _d(f["test_start"]) <= _d(d) <= _d(f["test_end"])] if common else []
                fold_sh.append(round(_sharpe_of(seg, p), 3) if len(seg) >= 3 else None)
            if len(F) < 3:
                why.append(f"{len(F)} folds (need >= 3)")
            got = [x for x in fold_sh if x is not None]
            if len(got) < len(F):
                why.append("a fold has fewer than 3 net equity points")
            if got and sum(1 for x in got if x > 0) / len(got) < 0.5:
                why.append("fewer than half the folds have net Sharpe > 0")
        except (KeyError, ValueError) as e:
            why.append(f"fold dates missing or not ISO ({e})")
        put("walk_forward", not why, why="; ".join(why) or None, fold_sharpes=fold_sh)
    # deflated Sharpe
    if not m.get("trials"):
        missing("deflated_sharpe", "trials")
    elif len(net) >= 3:
        ts_ = m.get("trial_sharpes")
        dsr, sr0 = deflated_sharpe(rets(net), max(1, int(m["trials"])), ts_)
        put("deflated_sharpe", dsr >= 0.95, why=None if dsr >= 0.95 else f"DSR prob {dsr} < 0.95 at {m['trials']} trials",
            prob=dsr, sr0_per_period=round(sr0, 5),
            basis="cross-trial variance" if ts_ and len(ts_) >= 2 else "estimation-variance approximation")
    else:
        missing("deflated_sharpe", "net_equity")
    # cost sweep
    if cost_bps is not None and len(gross) >= 3:
        sweep, why = {}, []
        rg = rets(gross)
        for k in (1, 2, 3):
            rk = [g - 2 * tv * cost_bps * k / 1e4 for g, tv in zip(rg, turn[1:])]
            eqk = equity_from(rk)
            sweep[f"x{k}"] = {"sharpe": round(sharpe(rk, p), 3), "total_return": round(eqk[-1] - 1, 4)}
            if sweep[f"x{k}"]["sharpe"] <= 0 or sweep[f"x{k}"]["total_return"] <= 0:
                why.append(f"net <= 0 at {k}x costs")
        put("cost_sweep", not why, why="; ".join(why) or None, sweep=sweep)
    else:
        missing("cost_sweep", "costs and gross_equity")
    # regimes
    try:
        lab = dict((d, v) for d, v in _labels(os.path.join(base, _req(m, "regimes"))))
        if len(net) < 3:
            raise Missing("net_equity")
        rn = rets(net)
        by = {}
        for d, x in zip(common[1:], rn):
            by.setdefault(lab.get(d, "UNLABELLED"), []).append(x)
        tot = sum(math.log1p(x) for x in rn)
        stats, why = {}, []
        for g, xs in by.items():
            lr = sum(math.log1p(x) for x in xs)
            stats[g] = {"periods": len(xs), "sharpe": round(sharpe(xs, p), 3) if len(xs) > 1 else None,
                        "share_of_log_return": round(lr / tot, 3) if tot else None}
        big = [g for g, s in stats.items() if s["periods"] >= 63 and g != "UNLABELLED"]
        if len(big) < 2:
            why.append(f"{len(big)} regimes with >= 63 periods (need 2)")
        if "UNLABELLED" in stats:
            why.append(f"{stats['UNLABELLED']['periods']} periods have no regime label")
        if tot <= 0:
            why.append("total net log return <= 0")
        elif any((s["share_of_log_return"] or 0) > 1.0 for s in stats.values()):
            why.append("one regime supplies more than all of the return; the others lose money")
        put("regimes", not why, why="; ".join(why) or None, by_regime=stats)
    except Missing as e:
        missing("regimes", str(e))
    # train cutoff
    if "llm_in_loop" not in m:
        missing("train_cutoff", "llm_in_loop (true or false)")
    elif m["llm_in_loop"] is not True:
        checks["train_cutoff"] = {"status": "pass", "applies": False, "basis": "no LLM decides inside the backtest"}
    elif not m.get("model_train_cutoff"):
        missing("train_cutoff", "model_train_cutoff")
    elif not wf or not common:
        missing("train_cutoff", "walk_forward folds and net_equity")
    else:
        cut = _d(m["model_train_cutoff"])
        test_days = sorted({d for f in wf for d in common if _d(f["test_start"]) <= _d(d) <= _d(f["test_end"])})
        pre = [d for d in test_days if _d(d) <= cut]
        frac = round(len(pre) / len(test_days), 4) if test_days else 1.0
        whole = round(sum(1 for d in common if _d(d) <= cut) / len(common), 4)
        if frac == 0 or m.get("masked") is True:
            checks["train_cutoff"] = {"status": "pass", "applies": True, "test_share_before_cutoff": frac,
                                      "window_share_before_cutoff": whole,
                                      "note": "masked with mask.py: memory leak reduced, not removed" if frac and m.get("masked") else None}
        else:
            put("train_cutoff", False, why=f"{frac:.0%} of test periods predate the model's training cutoff {cut}",
                applies=True, test_share_before_cutoff=frac, window_share_before_cutoff=whole)
    order = ["alignment", "lookahead", "same_bar", "survivorship", "costs", "walk_forward", "deflated_sharpe",
             "cost_sweep", "regimes", "train_cutoff"]
    out = {"verdict": "fail" if reasons else "pass", "strategy": m.get("strategy"), "reasons": reasons,
           "checks": {k: checks.get(k, {"status": "fail", "why": "not evaluated"}) for k in order}, "metrics": metrics}
    if any(v["status"] != "pass" for v in out["checks"].values()):
        out["verdict"] = "fail"
    return out


def _labels(path):
    with open(path) as f:
        r = csv.reader(f); next(r)
        return [(row[0], row[-1]) for row in r if row]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="rigor mode: every check, fail closed (see RIGOR_DOC)")
    ap.add_argument("--equity"); ap.add_argument("--benchmark"); ap.add_argument("--trades")
    ap.add_argument("--trials", default="auto", help="auto (trial ledger) or the number of variants tried")
    ap.add_argument("--family"); ap.add_argument("--ledger")
    ap.add_argument("--sleeve", choices=["auto", "directional", "neutral"], default="auto")
    ap.add_argument("--blend", type=float, default=0.30)
    ap.add_argument("--periods", type=int, default=252); ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    if a.manifest:
        try:
            res = rigor(a.manifest)
        except (OSError, ValueError, KeyError) as e:
            print(json.dumps({"verdict": "fail", "error": f"bad input: {e}"}, indent=2)); sys.exit(2)
        print(json.dumps(res, indent=2)); sys.exit(0 if res["verdict"] == "pass" else 1)
    if not a.equity:
        ap.error("--equity or --manifest is required")
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
        if se is None:
            print(json.dumps({"verdict": "FAIL_GATES", "gates": ["benchmark not aligned: " + how]}, indent=2)); sys.exit(2)
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
    res["rigor"] = "not checked: run validate_backtest.py --manifest for the fail-closed gate"
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
