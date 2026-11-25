#!/usr/bin/env python3
"""Run the validation gates in order and print one verdict on a three-step ladder. Stdlib only.

Usage:
  pipeline.py --gross gross.csv [--costs costs.json] [--benchmark bench_equity.csv]
              [--sleeve auto|directional|neutral] [--trials auto|N] [--family F] [--ledger trials.jsonl]
              [--variants variants.csv --blocks 16] [--positions positions.csv --group day]
              [--weights weights.csv --prices closes.csv]  (beta-matched selection test)
              [--factors factors.csv] [--regimes regimes.csv | --regime-conditional LABEL]
              [--lookahead-result la.json] [--permutation-result perm.json]
              [--universe-result universe.json] [--cross-sectional] [--periods 252] [--workdir DIR]
Order: costs.py (net, cost multiples, capacity) -> validate_backtest.py (DSR with the ledger's trial
count; risk-adjusted, marginal and, for directional sleeves, total-return tests) -> overfit.py pbo ->
monkey_test.py (direction and beta-matched) -> attribution.py -> regime split. Gates run on NET returns.

Verdict ladder:
  NOT_READY        a mechanical gate failed: hard gates (FAIL_GATES), look-ahead LEAK, PBO fail,
                   permutation fail, net Sharpe <= 0 at the required cost multiple (default x3), monkey
                   ANTI_EDGE, a cross-sectional test on a universe that is TOO_NARROW, or an error
  PAPER_PROBE      mechanics clean, alpha unproven (DSR below 0.95, a benchmark test failed, LUCK,
                   BETA_OR_STYLE, one regime, or a confirming gate not run). Paper-trade at a quarter
                   of the normal size to buy forward data, the only unbiased sample there is. Review with
                   strategy_health.py after 63 trading days; re-run this pipeline on backtest + paper.
  READY_FOR_PAPER  every gate ran and passed, including look-ahead and permutation results passed in
"say_plainly" lists what the user must hear in plain words before any paper trade.
Probe and paper are paper only. Live money needs trading-execution's signed mandate and live_ack.
"""
import argparse, csv, json, math, os, statistics as S, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from trial_ledger import resolve_trials

PROBE = {"mode": "paper", "size_multiplier": 0.25, "review_after_trading_days": 63,
         "review_with": "strategy_health.py, then pipeline.py on backtest + paper record"}


def call(*args):
    p = subprocess.run([sys.executable, os.path.join(HERE, args[0]), *args[1:]], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"verdict": "ERROR", "stderr": p.stderr[-300:]}


def regime_split(net_csv, bench_csv, regimes_csv, periods):
    net = {r["date"]: float(r["ret"]) for r in csv.DictReader(open(net_csv))}
    lab = {}
    if regimes_csv:
        lab = {r["date"]: r["label"] for r in csv.DictReader(open(regimes_csv))}
        basis = "user regimes file"
    elif bench_csv:
        b = [(r["date"], float(r["value"])) for r in csv.DictReader(open(bench_csv))]
        br = [(b[i][0], b[i][1] / b[i - 1][1] - 1) for i in range(1, len(b))]
        vol = {}
        for i in range(63, len(br)):
            w = [x for _, x in br[i - 63:i]]
            vol[br[i][0]] = S.pstdev(w)
        if not vol:
            return None
        v = sorted(vol.values()); lo, hi = v[len(v) // 3], v[2 * len(v) // 3]
        lab = {d: ("calm" if x <= lo else "stressed" if x > hi else "normal") for d, x in vol.items()}
        basis = "benchmark 63-day realised volatility terciles (VIX-tercile proxy), labels known only after the fact"
    else:
        return None
    by = {}
    for d, x in net.items():
        if d in lab:
            by.setdefault(lab[d], []).append(x)
    out = {}
    for k, xs in sorted(by.items()):
        sd = S.stdev(xs) if len(xs) > 1 else 0
        out[k] = {"days": len(xs), "annual_return_arith": round(S.mean(xs) * periods, 4),
                  "sharpe": round(S.mean(xs) / sd * math.sqrt(periods), 2) if sd else 0.0}
    big = [k for k, v in out.items() if v["days"] >= 126]
    pos = [k for k in big if out[k]["sharpe"] > 0]
    return {"basis": basis, "by_regime": out, "regimes_with_126_days": len(big), "positive_in": pos,
            "pass": len(big) >= 2 and len(pos) >= 2}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gross", required=True); ap.add_argument("--costs"); ap.add_argument("--benchmark")
    ap.add_argument("--sleeve", default="auto", choices=["auto", "directional", "neutral"])
    ap.add_argument("--trials", default="auto"); ap.add_argument("--family"); ap.add_argument("--ledger")
    ap.add_argument("--variants"); ap.add_argument("--blocks", default="16")
    ap.add_argument("--positions"); ap.add_argument("--group", default="position")
    ap.add_argument("--weights"); ap.add_argument("--prices"); ap.add_argument("--factors")
    ap.add_argument("--regimes"); ap.add_argument("--regime-conditional")
    ap.add_argument("--lookahead-result"); ap.add_argument("--permutation-result"); ap.add_argument("--universe-result")
    ap.add_argument("--cross-sectional", action="store_true", help="the signal ranks names against each other")
    ap.add_argument("--periods", default="252"); ap.add_argument("--workdir")
    a = ap.parse_args()
    wd = a.workdir or tempfile.mkdtemp(); os.makedirs(wd, exist_ok=True); net = os.path.join(wd, "net")
    out, hard, soft, plain, skipped = {}, [], [], [], []
    n_trials, tsrc = resolve_trials(a.trials, a.ledger, a.family)
    ledger = [*(["--ledger", a.ledger] if a.ledger else []), *(["--family", a.family] if a.family else [])]

    co = call("costs.py", "--returns", a.gross, "--periods", a.periods, "--out", net, *(["--costs", a.costs] if a.costs else []))
    out["costs"] = co
    if co.get("verdict") == "ERROR":
        hard.append("costs ERROR")
    elif not co.get("survives_required"):
        hard.append(f"net Sharpe <= 0 at x{co.get('required_cost_x')} costs (survives x{co.get('survives_cost_x')})")

    vb = call("validate_backtest.py", "--equity", net + "_equity.csv", "--trials", str(n_trials), "--periods", a.periods,
              "--sleeve", a.sleeve, *(["--benchmark", a.benchmark] if a.benchmark else []))
    out["validate_backtest"] = vb
    if vb.get("verdict") in ("FAIL_GATES", "ERROR", None):
        hard.append(f"hard_gate {vb.get('verdict')}")
    else:
        if vb.get("deflated_sharpe_prob", 0) < 0.95:
            soft.append(f"deflated Sharpe {vb.get('deflated_sharpe_prob')} < 0.95 after {n_trials} trials")
        for k in vb.get("benchmark_failed", []):
            soft.append(f"benchmark {k} failed")
        if not a.benchmark:
            soft.append("no benchmark: risk-adjusted and marginal tests not run")
    if tsrc == "none":
        soft.append("no trial ledger: DSR assumed 1 trial")
        plain.append("Nobody counted the variants tried, so the overfitting correction may be too soft.")

    if a.variants:
        pb = call("overfit.py", "pbo", "--returns", a.variants, "--blocks", a.blocks); out["pbo"] = pb
        if pb.get("verdict") != "PASS":
            hard.append(f"pbo {pb.get('verdict')}")
    elif n_trials > 1:
        soft.append(f"pbo not run although {n_trials} trials were logged"); skipped.append("pbo (no --variants)")
    else:
        skipped.append("pbo (single trial)")

    for name, path in (("lookahead", a.lookahead_result), ("permutation", a.permutation_result)):
        if path:
            r = json.load(open(path)); out[name] = r
            v = str(r.get("verdict", "")).upper()
            if v not in ("PASS", "OK"):
                hard.append(f"{name} {v or 'unknown'}")
        else:
            soft.append(f"{name} not run"); skipped.append(f"{name} (pass --{name}-result from {name}_check.py/permutation_test.py)" if name == "lookahead" else f"{name} (pass --permutation-result from permutation_test.py)")

    if a.cross_sectional:
        if a.universe_result:
            u = json.load(open(a.universe_result)); out["universe"] = u
            if u.get("verdict") == "TOO_NARROW":
                hard.append(f"universe TOO_NARROW ({u.get('members_min')} names; need {u.get('min_names', 100)})")
            elif u.get("verdict") == "SURVIVORSHIP_SUSPECT":
                soft.append("universe SURVIVORSHIP_SUSPECT"); plain.append("The universe has no delisted names, so results are biased upward.")
        else:
            hard.append("cross-sectional signal without a universe.py result (need >= 100 point-in-time names, delisted included)")

    if a.positions:
        mk = call("monkey_test.py", "--positions", a.positions, "--group", a.group); out["monkey_direction"] = mk
        if mk.get("verdict") in ("ANTI_EDGE", "ERROR"):
            hard.append(f"monkey_test {mk.get('verdict')}")
        elif mk.get("verdict") == "LUCK":
            soft.append("monkey direction LUCK"); plain.append("Its direction calls can't be told from coin flips.")
    if a.weights and a.prices:
        mb = call("monkey_test.py", "--mode", "beta_matched", "--weights", a.weights, "--prices", a.prices)
        out["monkey_beta_matched"] = mb
        if mb.get("verdict") == "ANTI_EDGE":
            hard.append("beta-matched monkey ANTI_EDGE")
        elif mb.get("verdict") == "LUCK":
            soft.append("beta-matched monkey LUCK"); plain.append("With exposure held equal, random names did as well: no proven selection skill.")
        elif mb.get("verdict") == "ERROR":
            skipped.append("beta-matched monkey (error: " + mb.get("stderr", "")[-120:] + ")")
    if not a.positions and not (a.weights and a.prices):
        soft.append("monkey test not run"); skipped.append("monkey_test (no --positions or --weights/--prices)")

    if a.factors:
        at = call("attribution.py", "--returns", net + ".csv", "--factors", a.factors, "--periods-per-year", a.periods)
        out["attribution"] = at
        if at.get("verdict") == "ERROR":
            hard.append("attribution ERROR")
        elif at.get("verdict") == "BETA_OR_STYLE":
            soft.append("attribution BETA_OR_STYLE"); plain.append("Market and style exposure explain the return, not stock selection.")
    else:
        soft.append("attribution not run"); skipped.append("attribution (no --factors; build them with factor_proxies.py)")

    rg = regime_split(net + ".csv", a.benchmark, a.regimes, int(a.periods))
    out["regimes"] = rg
    if a.regime_conditional:
        out["regime_conditional"] = a.regime_conditional
        plain.append(f"Declared regime-conditional: only run it in '{a.regime_conditional}'.")
    elif rg is None:
        soft.append("regime split not run (no --benchmark or --regimes)")
    elif not rg["pass"]:
        soft.append("works in fewer than two regimes"); plain.append("It only worked in one kind of market in this sample.")

    verdict = "NOT_READY" if hard else "PAPER_PROBE" if soft else "READY_FOR_PAPER"
    print(json.dumps({"verdict": verdict, "hard_reasons": hard, "soft_reasons": soft, "say_plainly": plain,
                      "probe": PROBE if verdict == "PAPER_PROBE" else None, "trials": n_trials, "trials_source": tsrc,
                      "skipped": skipped, "results": out}, indent=1))


if __name__ == "__main__":
    main()
