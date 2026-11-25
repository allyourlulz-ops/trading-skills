#!/usr/bin/env python3
"""Run the validation gates in order and print one verdict. Stdlib only; calls the other scripts.

Usage:
  pipeline.py --gross gross.csv [--costs costs.json] [--benchmark bench_equity.csv] [--trials 1]
              [--variants variants.csv --blocks 16] [--positions positions.csv --group day]
              [--factors factors.csv] [--periods 252] [--workdir DIR]
Order: costs.py (net of costs) -> validate_backtest.py (hard gates, deflated Sharpe vs buy-and-hold)
-> overfit.py pbo (if --variants) -> monkey_test.py (if --positions) -> attribution.py (if --factors).
Each gate runs on NET returns. Verdict:
  READY_FOR_PAPER  every gate that ran passed and validate_backtest ran
  NOT_READY        a gate failed; the reasons list says which
LUCK (monkey) and BETA_OR_STYLE (attribution) do not block paper trading but are listed under
"say_plainly": tell the user the result can't be told from chance, or is market and style exposure.
Gates not run are listed under "skipped"; a skipped gate is not a pass. Lookahead and permutation
tests need the strategy code; run lookahead_check.py and permutation_test.py on it first.
"""
import argparse, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def call(*args):
    p = subprocess.run([sys.executable, os.path.join(HERE, args[0]), *args[1:]], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"verdict": "ERROR", "stderr": p.stderr[-300:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gross", required=True); ap.add_argument("--costs"); ap.add_argument("--benchmark")
    ap.add_argument("--trials", default="1"); ap.add_argument("--variants"); ap.add_argument("--blocks", default="16")
    ap.add_argument("--positions"); ap.add_argument("--group", default="position"); ap.add_argument("--factors")
    ap.add_argument("--periods", default="252"); ap.add_argument("--workdir")
    a = ap.parse_args()
    wd = a.workdir or tempfile.mkdtemp(); net = os.path.join(wd, "net")
    out, reasons, plain, skipped = {}, [], [], []
    out["costs"] = call("costs.py", "--returns", a.gross, "--periods", a.periods, "--out", net,
                        *(["--costs", a.costs] if a.costs else []))
    vb = call("validate_backtest.py", "--equity", net + "_equity.csv", "--trials", a.trials, "--periods", a.periods,
              *(["--benchmark", a.benchmark] if a.benchmark else []))
    out["validate_backtest"] = vb
    if vb.get("verdict") != "PASS":
        reasons.append(f"validate_backtest {vb.get('verdict')}")
    if a.variants:
        pb = call("overfit.py", "pbo", "--returns", a.variants, "--blocks", a.blocks); out["pbo"] = pb
        if pb.get("verdict") != "PASS":
            reasons.append(f"pbo {pb.get('verdict')}")
    else:
        skipped.append("pbo (no --variants)")
    if a.positions:
        mk = call("monkey_test.py", "--positions", a.positions, "--group", a.group); out["monkey_test"] = mk
        v = mk.get("verdict")
        if v in ("ANTI_EDGE", "ERROR"):
            reasons.append(f"monkey_test {v}")
        elif v == "LUCK":
            plain.append("monkey_test LUCK: this result can't be told from chance")
    else:
        skipped.append("monkey_test (no --positions)")
    if a.factors:
        at = call("attribution.py", "--returns", net + ".csv", "--factors", a.factors, "--periods-per-year", a.periods)
        out["attribution"] = at
        if at.get("verdict") == "ERROR":
            reasons.append("attribution ERROR")
        elif at.get("verdict") == "BETA_OR_STYLE":
            plain.append("attribution BETA_OR_STYLE: this is market and style exposure, not stock selection")
    else:
        skipped.append("attribution (no --factors)")
    skipped.append("lookahead_check and permutation_test (need strategy code; run them separately)")
    print(json.dumps({"verdict": "NOT_READY" if reasons else "READY_FOR_PAPER", "reasons": reasons,
                      "say_plainly": plain, "skipped": skipped, "results": out}, indent=1))


if __name__ == "__main__":
    main()
