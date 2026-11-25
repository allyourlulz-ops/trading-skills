#!/usr/bin/env python3
"""Offline regression tests for the skill's scripts: synthetic data only, no network, stdlib only.
Usage: python3 evals/run_tests.py   (exit 0 = all pass). Run before every release.
Trigger and task evals (trigger_evals.json, task_evals.json) are run by the user in their own agent
client; this file only checks the deterministic scripts."""
import math, csv, json, os, py_compile, random, subprocess, sys, tempfile

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

# 7. lookahead_check.py: a two-sided (centred) smoother, like an HP filter run over the whole history, leaks
centred = os.path.join(TMP, "centred.py")
open(centred, "w").write("import csv,sys\nr=list(csv.reader(open(sys.argv[1])))[1:]\nfor i in range(10,len(r)-10):\n    m=sum(float(x[1]) for x in r[i-10:i+11])/21\n    print(r[i][0]+',AAA,'+('buy' if float(r[i][1])>m else 'flat'))\n")
code, out, _ = run("lookahead_check.py", "--prices", px, "--cmd", f"{sys.executable} {centred} {{prices}}")
check("lookahead two-sided smoother leaks", code == 2 and json.loads(out)["verdict"] == "LEAK")

# 8. risk_check.py --bar: forming bar and frozen feed block, a fresh closed bar does not
order = os.path.join(TMP, "order.json")
json.dump({"symbol": "AAA", "side": "buy", "qty": 5, "type": "limit", "limit_price": 190.0, "stop_price": 186.0,
           "target_price": 198.0, "asset_class": "equity"}, open(order, "w"))
def bar_blocks(bar, now):
    f = os.path.join(TMP, "bar.json"); json.dump(bar, open(f, "w"))
    _, out, _ = run("risk_check.py", "--order", order, "--bar", f, "--now", now)
    return [b for b in json.loads(out)["blocks"] if "bar" in b or "stale" in b]
now = "2026-11-23T15:20:00+00:00"
check("bar fresh passes", bar_blocks({"timeframe": "1h", "last_bar_open": "2026-11-23T14:00:00+00:00", "closed": True}, now) == [])
check("bar forming blocks", any("forming" in b for b in bar_blocks({"timeframe": "1h", "last_bar_open": "2026-11-23T15:00:00+00:00", "closed": False}, now)))
check("bar stale blocks", any("stale" in b for b in bar_blocks({"timeframe": "1h", "last_bar_open": "2026-11-23T10:00:00+00:00", "closed": True}, now)))

# 9. black_litterman.py --neutral: net exposure 0, gross 1, cap respected
bl = os.path.join(TMP, "bl.csv"); random.seed(5); ps = [100.0] * 4
with open(bl, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["date", "A", "B", "C", "D"])
    for i in range(300):
        ps = [x * _m.exp(random.gauss(0, 0.01 + 0.004 * j)) for j, x in enumerate(ps)]; w.writerow([i] + [round(x, 4) for x in ps])
views = os.path.join(TMP, "views.json")
json.dump([{"ticker": "A", "conviction": 0.6, "confidence": 70}, {"long": "B", "short": "D", "conviction": 0.4, "confidence": 50}], open(views, "w"))
code, out, err = run("black_litterman.py", "--prices", bl, "--views", views, "--neutral", "--ridge", "1e-4")
d = json.loads(out) if code == 0 else {}
check("bl neutral net zero", code == 0 and abs(d["net_exposure"]) < 1e-3, err[-200:])
check("bl neutral gross one", d and abs(d["gross_exposure"] - 1) < 1e-3)
code, out, _ = run("black_litterman.py", "--prices", bl, "--views", views, "--neutral", "--max-weight", "0.2")
d = json.loads(out) if code == 0 else {}
check("bl neutral cap keeps neutrality", d and max(abs(x) for x in d["target_weight"].values()) <= 0.2001 and abs(d["net_exposure"]) < 1e-3)
code, _, _ = run("black_litterman.py", "--prices", bl, "--views", views, "--neutral", "--long-only")
check("bl neutral refuses long-only", code != 0)

# 10. monkey_test.py: strong edge is EDGE, noise is not, reversed calls are ANTI_EDGE
def positions(path, edge, seed, flip=False):
    random.seed(seed)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["id", "open_time", "side", "pnl", "fees"])
        for i in range(300):
            v = random.gauss(edge, 1.0)
            w.writerow([i, f"2026-10-{1 + i % 28:02d}T10:00:00-04:00", "long", -v if flip else v, 0.05])
for label, e, flip, want in (("edge", 0.6, False, "EDGE"), ("noise", 0.0, False, "LUCK"), ("anti", 0.6, True, "ANTI_EDGE")):
    f = os.path.join(TMP, f"pos_{label}.csv"); positions(f, e, 21, flip)
    code, out, err = run("monkey_test.py", "--positions", f)
    check(f"monkey {label}", code == 0 and json.loads(out)["verdict"] == want, out[-200:] + err[-200:])

# 11. attribution.py: pure beta+style is BETA_OR_STYLE, added alpha is SELECTION_ALPHA
random.seed(31)
fac, pb, pa = (os.path.join(TMP, n) for n in ("fac.csv", "pbeta.csv", "palpha.csv"))
with open(fac, "w", newline="") as f1, open(pb, "w", newline="") as f2, open(pa, "w", newline="") as f3:
    w1, w2, w3 = csv.writer(f1), csv.writer(f2), csv.writer(f3)
    w1.writerow(["date", "mkt", "size", "mom"]); w2.writerow(["date", "ret"]); w3.writerow(["date", "ret"])
    for t in range(500):
        m, sz, mo = random.gauss(0.0005, 0.01), random.gauss(0, 0.005), random.gauss(0, 0.005)
        w1.writerow([t, m, sz, mo]); w2.writerow([t, 1.2 * m + 0.8 * mo + random.gauss(0, 0.002)])
        w3.writerow([t, 0.5 * m + 0.002 + random.gauss(0, 0.003)])
code, out, err = run("attribution.py", "--returns", pb, "--factors", fac)
d = json.loads(out) if code == 0 else {}
check("attribution beta", d.get("verdict") == "BETA_OR_STYLE" and abs(d["betas"]["mkt"] - 1.2) < 0.1, out[-200:] + err[-200:])
code, out, _ = run("attribution.py", "--returns", pa, "--factors", fac, "--window", "120")
check("attribution alpha rolling", code == 0 and json.loads(out)["verdict"] == "SELECTION_ALPHA")

# 12. mask.py: blinded file has no real ticker or date; unmask round-trips
bars, mbars, key = (os.path.join(TMP, n) for n in ("bars.csv", "mbars.csv", "key.json"))
with open(bars, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["date", "symbol", "close"])
    for d_ in ("2026-01-02", "2026-01-05"):
        for s_ in ("AAPL", "MSFT"): w.writerow([d_, s_, 100])
run("mask.py", "mask", "--in", bars, "--out", mbars, "--key", key, "--level", "blinded")
code, _, _ = run("mask.py", "check", "--in", mbars, "--key", key)
check("mask clean", code == 0)
code, _, _ = run("mask.py", "check", "--in", bars, "--key", key)
check("mask detects leak", code != 0)
_, out, _ = run("mask.py", "unmask", "--key", key, "--value", "day_+3")
check("mask unmask date", out.strip() == "2026-01-05")

# 13. pit_store.py: forming bar hidden, priority source wins, conflict kept, cooldown skips source
routes = os.path.join(SCRIPTS, "..", "assets", "data-routes.json")
store, st, r1, r2 = (os.path.join(TMP, n) for n in ("m.jsonl", "st.json", "r1.json", "r2.json"))
mk = lambda s_, d_, c: {"symbol": s_, "ts": f"{d_}T00:00:00-05:00", "open": 1, "high": 2, "low": 1, "close": c, "volume": 1}
json.dump([mk("aapl", "2026-11-20", 100), mk("aapl", "2026-11-23", 101), mk("aapl", "2026-11-24", 102)], open(r1, "w"))
json.dump([mk("AAPL", "2026-11-23", 103)], open(r2, "w"))
NOW = "2026-11-24T18:00:00-05:00"
for src, f in (("openbb", r1), ("alpaca", r2)):
    run("pit_store.py", "ingest", "--store", store, "--source", src, "--timeframe", "1d", "--file", f,
        "--routes", routes, "--asset", "equity_us", "--now", NOW)
code, out, err = run("pit_store.py", "asof", "--store", store, "--symbol", "AAPL", "--timeframe", "1d", "--at", NOW)
d = json.loads(out) if code == 0 else {}
check("pit forming hidden", d and len(d["rows"]) == 2 and d["hidden_future_or_forming"] == 1, err[-200:])
check("pit priority and conflict", d and d["rows"][-1]["source"] == "alpaca" and d["rows"][-1].get("alt") == {"openbb": 101.0})
run("pit_store.py", "fail", "--state", st, "--source", "alpaca", "--code", "429", "--now", NOW)
_, out, _ = run("pit_store.py", "route", "--routes", routes, "--asset", "equity_us", "--state", st, "--now", NOW)
check("pit cooldown skips", json.loads(out)["try_in_order"][0] == "openbb")

# 14. score_tool_calls.py: perfect run scores 1, a forbidden order tool is a safety fail
sc = os.path.join(HERE, "tool_scenarios.json"); runf = os.path.join(TMP, "run.json")
S = json.load(open(sc))["scenarios"]
json.dump({x["id"]: x["reference"] for x in S}, open(runf, "w"))
p = subprocess.run([sys.executable, os.path.join(HERE, "score_tool_calls.py"), "--scenarios", sc, "--run", runf], capture_output=True, text=True)
d = json.loads(p.stdout) if p.returncode == 0 else {}
check("tool score perfect", d and d["overall"]["TF1"] == 1 and d["overall"]["EMR"] == 1, p.stderr[-200:])
bad = {x["id"]: x["reference"] for x in S}; bad["mar-quote"] = [["get_stock_snapshot", "place_stock_order"]]
json.dump(bad, open(runf, "w"))
p = subprocess.run([sys.executable, os.path.join(HERE, "score_tool_calls.py"), "--scenarios", sc, "--run", runf], capture_output=True, text=True)
check("tool score safety fail", p.returncode == 1 and "mar-quote" in json.loads(p.stdout)["safety_failures"])

# 15. premia_signals.py: momentum picks the trending names; buy/hold band keeps a held name
random.seed(41)
wide = os.path.join(TMP, "wide.csv")
with open(wide, "w", newline="") as fh:
    w_ = csv.writer(fh); syms = [f"S{i}" for i in range(10)]; w_.writerow(["date"] + syms)
    lv = [100.0] * 10
    for t in range(300):
        lv = [x * math.exp(0.0004 * (i - 5) + random.gauss(0, 0.01)) for i, x in enumerate(lv)]
        w_.writerow([f"d{t:04d}"] + [round(x, 4) for x in lv])
code, out, err = run("premia_signals.py", "--prices", wide, "--signal", "mom12_1")
d = json.loads(out) if code == 0 else {}
check("premia momentum top", d and set(d["weights"]) <= {"S9", "S8", "S7"}, err[-200:])
held = os.path.join(TMP, "held.json"); json.dump(["S6"], open(held, "w"))
code, out, _ = run("premia_signals.py", "--prices", wide, "--signal", "mom12_1", "--held", held)
check("premia band keeps held", code == 0 and ("S6" in json.loads(out)["weights"]) == (sorted(json.loads(out)["weights"]) != []))
code, out, _ = run("premia_signals.py", "--prices", wide, "--signal", "tsmom")
check("premia tsmom", code == 0 and len(json.loads(out)["weights"]) == 10)
# 16. costs.py: each cost is its own line and net < gross by turnover x one-way cost
gross = os.path.join(TMP, "gross.csv")
with open(gross, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "ret", "turnover", "short", "trades"])
    for t in range(252):
        w_.writerow([f"d{t:04d}", 0.0004, 0.1 if t % 21 == 0 else 0, 0.5, 2 if t % 21 == 0 else 0])
cj = os.path.join(TMP, "c.json"); json.dump({"spread_bps": 10, "slippage_bps": 5, "borrow_bps_yr": 100}, open(cj, "w"))
code, out, err = run("costs.py", "--returns", gross, "--costs", cj, "--out", os.path.join(TMP, "n"))
d = json.loads(out) if code == 0 else {}
lines = d.get("cost_lines_bps_per_year", {})
check("costs lines", d and abs(lines["spread"] - 1.2 * 5) < 0.2 and abs(lines["slippage"] - 1.2 * 5) < 0.2 and abs(lines["borrow"] - 50) < 1, str(lines) + err[-200:])
check("costs net below gross", d and d["net_annual_return"] < d["gross_annual_return"])
# 17. pipeline.py: noise is NOT_READY; premia backtest feeds it end to end
code, out, err = run("premia_signals.py", "--prices", wide, "--signal", "mom12_1", "--backtest", os.path.join(TMP, "bt"))
check("premia backtest", code == 0 and os.path.exists(os.path.join(TMP, "bt_gross.csv")), err[-200:])
code, out, err = run("pipeline.py", "--gross", os.path.join(TMP, "bt_gross.csv"), "--positions", os.path.join(TMP, "bt_positions.csv"), "--workdir", TMP)
d = json.loads(out) if code == 0 else {}
check("pipeline runs", d.get("verdict") in ("READY_FOR_PAPER", "NOT_READY") and "costs" in d.get("results", {}), err[-300:])
random.seed(5)
with open(gross, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "ret", "turnover"])
    for t in range(500):
        w_.writerow([f"d{t:04d}", random.gauss(0, 0.01), 0.05])
code, out, _ = run("pipeline.py", "--gross", gross, "--trials", "20", "--workdir", TMP)
check("pipeline noise not ready", code == 0 and json.loads(out)["verdict"] == "NOT_READY")
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
