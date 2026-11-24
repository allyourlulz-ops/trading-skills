#!/usr/bin/env python3
"""Offline regression tests for the skill's scripts: synthetic data only, no network, stdlib only.
Usage: python3 evals/run_tests.py   (exit 0 = all pass). Run before every release.
Trigger and task evals (trigger_evals.json, task_evals.json) are run by the user in their own agent
client; this file only checks the deterministic scripts."""
import csv, json, os, py_compile, random, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
TMP = tempfile.mkdtemp()
fails = []


def run(*args):
    p = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=SCRIPTS)
    return p.returncode, p.stdout, p.stderr


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + detail))
    if not cond:
        fails.append(name)


# 1. every script compiles and answers --help
for f in sorted(os.listdir(SCRIPTS)):
    if f.endswith(".py"):
        path = os.path.join(SCRIPTS, f)
        try:
            py_compile.compile(path, cfile=os.path.join(TMP, f + "c"), doraise=True)
            ok = True
        except py_compile.PyCompileError as e:
            ok = False
        check(f"compile {f}", ok)
        code, _, err = run(f, "--help")
        check(f"help {f}", code == 0, err[-200:])


def variants(path, edge, seed):
    random.seed(seed)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date"] + [f"v{i}" for i in range(20)])
        for t in range(1000):
            w.writerow([t] + [random.gauss(edge if i == 0 else 0, 0.01) for i in range(20)])


# 2. overfit.py: noise family fails, strong edge passes
noise, strong = os.path.join(TMP, "noise.csv"), os.path.join(TMP, "strong.csv")
variants(noise, 0.0, 1); variants(strong, 0.002, 2)
for label, f, want in (("noise", noise, "FAIL"), ("strong", strong, "PASS")):
    code, out, err = run("overfit.py", "dsr", "--returns", f)
    check(f"overfit dsr {label}", code == 0 and json.loads(out)["verdict"] == want, out[-200:] + err[-200:])
code, out, _ = run("overfit.py", "pbo", "--returns", strong)
check("overfit pbo strong", code == 0 and json.loads(out)["pbo"] <= 0.2)
code, out, _ = run("overfit.py", "cpcv", "--n", "100", "--groups", "5", "--test-groups", "2", "--horizon", "2")
d = json.loads(out) if code == 0 else {}
check("overfit cpcv splits", d.get("splits") == 10 and d.get("backtest_paths") == 4)
check("overfit cpcv purge", d and all(a >= 40 for a, b in d["folds"][0]["train"]))

# 3. options_payoff.py: covered call and unit warning
cc = os.path.join(TMP, "cc.json")
json.dump([{"type": "stock", "side": "buy", "premium": 100, "qty": 100},
           {"type": "call", "side": "sell", "strike": 105, "premium": 2, "qty": 1}], open(cc, "w"))
code, out, _ = run("options_payoff.py", "--spot", "100", "--legs", cc)
d = json.loads(out) if code == 0 else {}
check("covered call max profit", d.get("max_profit") == 700.0)
check("covered call max loss", d.get("max_loss") == -9800.0)
check("covered call breakeven", d.get("breakevens") == [98.0])
check("covered call no warnings", d.get("warnings") == [])
bad = os.path.join(TMP, "bad.json")
json.dump([{"type": "stock", "side": "buy", "premium": 100, "qty": 1},
           {"type": "call", "side": "sell", "strike": 105, "premium": 2, "qty": 1}], open(bad, "w"))
code, out, _ = run("options_payoff.py", "--spot", "100", "--legs", bad)
check("uncovered call flagged", code == 0 and len(json.loads(out)["warnings"]) == 2)

# 4. kelly.py: an edge-free bet sizes to zero
code, out, _ = run("kelly.py", "--price", "0.50", "--prob", "0.50", "--bankroll", "500")
check("kelly no edge", code == 0 and "0" in out)

# 5. regime.py: calm uptrend is risk_on, FOMC tomorrow is uncertain, VIX backwardation under EMA200 is risk_off
base = ["regime.py", "--spy", "590", "--ema50", "580", "--ema50-prev", "578", "--ema200", "560", "--vix", "17", "--vix3m", "19"]
for label, extra, want in (("risk_on", [], "risk_on"), ("fomc", ["--days-to-fomc", "1"], "uncertain")):
    code, out, _ = run(*base, *extra)
    check(f"regime {label}", code == 0 and json.loads(out)["regime"] == want)
code, out, _ = run("regime.py", "--spy", "540", "--ema50", "580", "--ema50-prev", "582", "--ema200", "560", "--vix", "24", "--vix3m", "22")
check("regime risk_off", code == 0 and json.loads(out)["regime"] == "risk_off")

# 6. lookahead_check.py: a moving-average rule passes, a rule that reads tomorrow's close leaks
import datetime, math as _m
px = os.path.join(TMP, "px.csv"); random.seed(3); p = 100.0
with open(px, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["date", "AAA"])
    for i in range(200):
        p *= _m.exp(random.gauss(0, 0.01)); w.writerow([(datetime.date(2025, 1, 1) + datetime.timedelta(i)).isoformat(), round(p, 4)])
good, cheat = os.path.join(TMP, "good.py"), os.path.join(TMP, "cheat.py")
open(good, "w").write("import csv,sys\nr=list(csv.reader(open(sys.argv[1])))[1:]\nfor i in range(20,len(r)):\n    m=sum(float(x[1]) for x in r[i-20:i])/20\n    print(r[i][0]+',AAA,'+('buy' if float(r[i][1])>m else 'flat'))\n")
open(cheat, "w").write("import csv,sys\nr=list(csv.reader(open(sys.argv[1])))[1:]\nfor i in range(len(r)-1):\n    print(r[i][0]+',AAA,'+('buy' if float(r[i+1][1])>float(r[i][1]) else 'flat'))\n")
code, out, _ = run("lookahead_check.py", "--prices", px, "--cmd", f"{sys.executable} {good} {{prices}}")
check("lookahead honest rule passes", code == 0 and json.loads(out)["verdict"] == "PASS")
code, out, _ = run("lookahead_check.py", "--prices", px, "--cmd", f"{sys.executable} {cheat} {{prices}}")
check("lookahead cheating rule leaks", code == 2 and json.loads(out)["verdict"] == "LEAK")

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
