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
        except py_compile.PyCompileError:
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

# 8. risk_check.py --bar: forming bar and frozen feed fail the gate, a fresh closed bar does not
order = os.path.join(TMP, "order.json"); pfp = os.path.join(TMP, "pf.json"); ctp = os.path.join(TMP, "ct.json")
now = "2026-11-23T10:20:00-05:00"
json.dump({"symbol": "AAA", "side": "buy", "qty": 5, "type": "limit", "limit_price": 190.0, "stop_price": 186.0,
           "target_price": 198.0, "asset_class": "equity"}, open(order, "w"))
json.dump({"base_currency": "USD", "equity": 25000, "buying_power": 20000, "paper": True, "positions": [],
           "clock": {"is_open": True, "source": "test", "as_of": now}}, open(pfp, "w"))
json.dump({"series": [{"name": "AAA", "symbol": "AAA", "role": "quote", "source": "test", "as_of": now, "last_bar_end": now,
                       "timeframe": "1m", "adjustment": "raw", "currency": "USD"}]}, open(ctp, "w"))
def bar_blocks(bar, now):
    f = os.path.join(TMP, "bar.json"); json.dump(bar, open(f, "w"))
    _, out, _ = run("risk_check.py", "--order", order, "--portfolio", pfp, "--contract", ctp, "--mode", "paper",
                    "--bar", f, "--now", now, "--gate-dir", os.path.join(TMP, "gate"))
    return [b for b in json.loads(out)["reasons"] if b.startswith("BAR:")]
check("bar fresh passes", bar_blocks({"timeframe": "1h", "last_bar_open": "2026-11-23T09:00:00-05:00", "closed": True}, now) == [])
check("bar forming blocks", any("forming" in b for b in bar_blocks({"timeframe": "1h", "last_bar_open": "2026-11-23T10:00:00-05:00", "closed": False}, now)))
check("bar stale blocks", any("stale" in b for b in bar_blocks({"timeframe": "1h", "last_bar_open": "2026-11-23T05:00:00-05:00", "closed": True}, now)))

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
# per-trade costs are charged on 2 x one-way turnover (a round trip is two trades)
check("costs lines", d and abs(lines["spread"] - 2.4 * 5) < 0.3 and abs(lines["slippage"] - 2.4 * 5) < 0.3 and abs(lines["borrow"] - 50) < 1, str(lines) + err[-200:])
check("costs net below gross", d and d["net_annual_return"] < d["gross_annual_return"])
# 17. pipeline.py: noise is NOT_READY; premia backtest feeds it end to end
code, out, err = run("premia_signals.py", "--prices", wide, "--signal", "mom12_1", "--backtest", os.path.join(TMP, "bt"))
check("premia backtest", code == 0 and os.path.exists(os.path.join(TMP, "bt_gross.csv")), err[-200:])
code, out, err = run("pipeline.py", "--gross", os.path.join(TMP, "bt_gross.csv"), "--positions", os.path.join(TMP, "bt_positions.csv"), "--workdir", TMP)
d = json.loads(out) if code == 0 else {}
check("pipeline runs", d.get("verdict") in ("READY_FOR_PAPER", "PAPER_PROBE", "NOT_READY") and "costs" in d.get("results", {}), err[-300:])
random.seed(5)
with open(gross, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "ret", "turnover"])
    for t in range(500):
        w_.writerow([f"d{t:04d}", random.gauss(0, 0.01), 0.05])
code, out, _ = run("pipeline.py", "--gross", gross, "--trials", "20", "--workdir", TMP)
check("pipeline noise not ready", code == 0 and json.loads(out)["verdict"] == "NOT_READY")
# 18. trial_ledger.py: distinct ids counted; --trials auto reads the ledger
LEDGER = os.path.join(TMP, "trials.jsonl")
for vid in ("v1", "v2", "v2"):
    run("trial_ledger.py", "log", "--id", vid, "--family", "t", "--ledger", LEDGER)
code, out, _ = run("trial_ledger.py", "count", "--family", "t", "--ledger", LEDGER)
check("ledger counts distinct ids", code == 0 and json.loads(out)["distinct_trials"] == 2, out)
eqp = os.path.join(TMP, "eq.csv")
with open(eqp, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "value"]); v = 1.0; random.seed(3)
    for t in range(300):
        v *= 1 + random.gauss(0.0005, 0.01); w_.writerow([f"d{t:04d}", v])
code, out, _ = run("validate_backtest.py", "--equity", eqp, "--trials", "auto", "--family", "t", "--ledger", LEDGER)
check("validate reads ledger", code == 0 and json.loads(out)["trials"] == 2 and json.loads(out)["trials_source"] == "ledger", out[-300:])

# 19. costs.py: square-root impact (sigma 1.5%, 0.1% of ADV -> 4.7 bps a trade), capacity curve, cost multiples
with open(gross, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "ret", "turnover", "adv_frac", "sigma"])
    for t in range(252):
        w_.writerow([f"d{t:04d}", 0.0006, 0.5, 0.001, 0.015])
cj0 = os.path.join(TMP, "c0.json"); json.dump({"spread_bps": 0, "slippage_bps": 0}, open(cj0, "w"))
code, out, err = run("costs.py", "--returns", gross, "--costs", cj0, "--out", os.path.join(TMP, "ni"))
d = json.loads(out) if code == 0 else {}
check("costs sqrt impact 4.7 bps per trade", d and abs(d["cost_lines_bps_per_year"]["impact"] - 252 * 1.0 * 4.743) < 3, str(d.get("cost_lines_bps_per_year")) + err[-200:])
cap = d.get("capacity", [])
check("costs capacity: edge shrinks with capital", isinstance(cap, list) and cap[0]["net_annual_return"] > cap[-1]["net_annual_return"] and cap[-1]["periods_over_adv_cap"] > 0)
check("costs multiples", d and d["cost_multiples"]["x3"]["net_annual_return"] < d["cost_multiples"]["x1"]["net_annual_return"])

# 20. rule_screen.py --tried: untraded variants still count in BH
code, out, _ = run("rule_screen.py", "--trades", os.path.join(TMP, "rs.csv")) if os.path.exists(os.path.join(TMP, "rs.csv")) else (1, "", "")
rs = os.path.join(TMP, "rs2.csv"); random.seed(11)
with open(rs, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["rule", "date", "excess"])
    for k in range(300):
        dd = f"20{18 + k // 60}-{1 + (k // 5) % 12:02d}-{1 + k % 28:02d}"
        w_.writerow(["edge", dd, random.gauss(0.004, 0.02)])
code1, out1, _ = run("rule_screen.py", "--trades", rs)
code2, out2, _ = run("rule_screen.py", "--trades", rs, "--tried", "500")
check("rule_screen --tried widens the correction", code1 == 0 and code2 == 0 and json.loads(out2)["variants"] == 500
      and json.loads(out2)["bonferroni_t_5pct"] > json.loads(out1)["bonferroni_t_5pct"])

# 21. universe.py: 120 names with delistings OK; 50 names TOO_NARROW; no delistings SURVIVORSHIP_SUSPECT
def panel(path, n, gone):
    random.seed(n)
    with open(path, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["date", "symbol", "close", "volume"])
        for t in range(120):
            for i in range(n):
                if i < gone and t > 80:
                    continue
                w_.writerow([f"2024-{1 + t // 28:02d}-{1 + t % 28:02d}", f"N{i:03d}", 10 + i, 1000 * (i + 1)])
for n, gone, want in ((120, 10, "OK"), (50, 5, "TOO_NARROW"), (120, 0, "SURVIVORSHIP_SUSPECT")):
    pp = os.path.join(TMP, f"panel{n}_{gone}.csv"); panel(pp, n, gone)
    code, out, err = run("universe.py", "--panel", pp, "--top", "200", "--out", os.path.join(TMP, f"u{n}_{gone}"))
    check(f"universe {want}", code == 0 and json.loads(out)["verdict"] == want, out[-200:] + err[-200:])

# 22. premia_signals.py --long-short with a borrow file and volumes: no unlocatable short, part fills recorded
wide2 = os.path.join(TMP, "wide2.csv"); vols2 = os.path.join(TMP, "vols2.csv"); random.seed(21)
syms2 = [f"S{i}" for i in range(12)]
with open(wide2, "w", newline="") as fh, open(vols2, "w", newline="") as fv:
    w_ = csv.writer(fh); wv = csv.writer(fv); w_.writerow(["date"] + syms2); wv.writerow(["date"] + syms2)
    px = [100.0] * 12
    for t in range(400):
        px = [p * (1 + random.gauss(0.0004 * (i - 6), 0.01)) for i, p in enumerate(px)]
        w_.writerow([f"d{t:04d}"] + [round(p, 4) for p in px]); wv.writerow([f"d{t:04d}"] + [5000] * 12)
bor = os.path.join(TMP, "borrow.csv")
with open(bor, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["symbol", "rate_bps_yr", "locate"])
    for i, sy in enumerate(syms2):
        w_.writerow([sy, 3000 if sy == "S1" else 40, "no" if sy == "S0" else "yes"])
code, out, err = run("premia_signals.py", "--prices", wide2, "--signal", "mom12_1", "--long-short", "--backtest", os.path.join(TMP, "ls"),
                     "--borrow", bor, "--volumes", vols2, "--capital", "100000", "--adv-cap-pct", "1", "--tranches", "3")
wts = list(csv.DictReader(open(os.path.join(TMP, "ls_weights.csv")))) if code == 0 else []
check("long-short never shorts S0 (no locate) or S1 (fee too high)", code == 0 and wts and not any(r["symbol"] in ("S0", "S1") and float(r["weight"]) < 0 for r in wts), err[-300:])
check("long-short has a short leg", any(float(r["weight"]) < 0 for r in wts))
g2 = list(csv.DictReader(open(os.path.join(TMP, "ls_gross.csv")))) if code == 0 else []
check("part fills: adv_frac capped at 1%", g2 and "adv_frac" in g2[0] and max(float(r["adv_frac"]) for r in g2) <= 0.0100001 and "borrow_bps_yr" in g2[0])

# 23. monkey_test.py --mode beta_matched: a random long-only picker in a rising market is LUCK, not EDGE
wide3 = os.path.join(TMP, "wide3.csv"); wfile = os.path.join(TMP, "w3.csv"); random.seed(31)
syms3 = [f"R{i}" for i in range(30)]
with open(wide3, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date"] + syms3); px = [100.0] * 30
    for t in range(1000):
        px = [p * (1 + random.gauss(0.0006, 0.012)) for p in px]
        w_.writerow([f"d{t:04d}"] + [round(p, 4) for p in px])
with open(wfile, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "symbol", "weight"])
    for t in range(0, 1000, 21):
        for sy in random.sample(syms3, 5):
            w_.writerow([f"d{t:04d}", sy, 0.2])
code, out, err = run("monkey_test.py", "--mode", "beta_matched", "--weights", wfile, "--prices", wide3)
check("beta-matched monkey: random long-only picks are LUCK", code == 0 and json.loads(out)["verdict"] == "LUCK", out[-300:] + err[-200:])

# 24. strategy_health.py: a 20% drawdown retires; a steady sleeve keeps
for name, path_, want in (("dd", [1, 1.05, 0.84, 0.85], "RETIRE"), ("ok", [1 + 0.0004 * t for t in range(80)], "KEEP")):
    ep = os.path.join(TMP, f"sh_{name}.csv")
    with open(ep, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["date", "value"]); w_.writerows([f"d{t:04d}", v] for t, v in enumerate(path_))
    code, out, _ = run("strategy_health.py", "--equity", ep)
    check(f"strategy_health {want}", code == 0 and json.loads(out)["verdict"] == want, out[-200:])

# 25. discover.py: a real post-event drift survives the sweep; a no-mechanism event is flagged
wide4 = os.path.join(TMP, "wide4.csv"); ev4 = os.path.join(TMP, "ev4.csv"); spec4 = os.path.join(TMP, "spec4.json"); random.seed(41)
syms4 = [f"E{i}" for i in range(40)]
from datetime import date as _d, timedelta as _td
days4, d0 = [], _d(2018, 1, 1)
while len(days4) < 1500:
    if d0.weekday() < 5:
        days4.append(d0.isoformat())
    d0 += _td(days=1)
events = [(random.randrange(30, 1450), random.choice(syms4), random.choice(["good", "noise"])) for _ in range(700)]
boost = {}
for t, sy, k in events:
    if k == "good":
        for j in range(t + 2, t + 7):
            boost[(j, sy)] = boost.get((j, sy), 0) + 0.004
with open(wide4, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "SPY"] + syms4); px = [100.0] * 41
    for t, dd in enumerate(days4):
        m = random.gauss(0.0003, 0.01)
        px = [px[0] * (1 + m)] + [p * (1 + m + random.gauss(0, 0.01) + boost.get((t, syms4[i]), 0)) for i, p in enumerate(px[1:])]
        w_.writerow([dd] + [round(p, 4) for p in px])
with open(ev4, "w", newline="") as fh:
    w_ = csv.writer(fh); w_.writerow(["date", "symbol", "event", "value"])
    for t, sy, k in events:
        w_.writerow([days4[t], sy, k, 1])
json.dump({"events": "all", "directions": [1, -1], "horizons": [5, 20], "cost_bps_roundtrip": 10,
           "mechanism": {"good": "synthetic underreaction"}}, open(spec4, "w"))
code, out, err = run("discover.py", "--events", ev4, "--prices", wide4, "--spec", spec4, "--out", os.path.join(TMP, "disc"), "--ledger", os.path.join(TMP, "dl.jsonl"))
d = json.loads(out) if code == 0 else {}
check("discover finds the real drift", any(v.startswith("disc_good_None_L") for v in d.get("survivors", [])), out[-400:] + err[-300:])
check("discover: noise event does not survive", not any("noise" in v for v in d.get("survivors", []) + d.get("no_mechanism", [])))
check("discover logs every variant", d.get("variants_tried") == 8 and d.get("ledger_distinct_trials_discover") == 8)

# 26. Positive-control benchmark suite (evals/benchmark_suite.md): the gates must pass a real edge, not only fail noise
SUITE_DAYS, _d0 = [], _d(2017, 1, 2)
while len(SUITE_DAYS) < 2268:
    if _d0.weekday() < 5:
        SUITE_DAYS.append(_d0.isoformat())
    _d0 += _td(days=1)


def suite_case(name, gen, n=2268, turnover=0.0, costs=None, leak=False, trials=5):
    random.seed(sum(map(ord, name)))
    gp, bp, fp, pp, vp = (os.path.join(TMP, f"{name}_{x}.csv") for x in ("gross", "bench", "fac", "pos", "var"))
    bench_r, strat_r = [], []
    for t in range(n):
        bench_r.append(random.gauss(0, 0.18 / math.sqrt(252)))
    mb = sum(bench_r) / n
    bench_r = [x - mb + 0.13 / 252 for x in bench_r]  # exactly 13% a year arithmetic, Sharpe about 0.7
    strat_r = [gen(b) for b in bench_r]
    with open(gp, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["date", "ret", "turnover"])
        for t, x in enumerate(strat_r):
            w_.writerow([SUITE_DAYS[t], x, turnover])
    with open(bp, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["date", "value"]); v = 1.0; w_.writerow(["2016-12-30", v])
        for t, b in enumerate(bench_r):
            v *= 1 + b; w_.writerow([SUITE_DAYS[t], v])
    with open(fp, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["date", "mkt"]); w_.writerows([SUITE_DAYS[t], b] for t, b in enumerate(bench_r))
    with open(pp, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["id", "open_time", "side", "pnl"])
        w_.writerows([f"p{t}", SUITE_DAYS[t], "long", x * 10000] for t, x in enumerate(strat_r))
    with open(vp, "w", newline="") as fh:
        w_ = csv.writer(fh); w_.writerow(["date", "pick"] + [f"alt{k}" for k in range(trials - 1)])
        for t, x in enumerate(strat_r):
            w_.writerow([SUITE_DAYS[t], x] + [random.gauss(0, 0.005) for _ in range(trials - 1)])
    led = os.path.join(TMP, f"{name}_ledger.jsonl")
    for k in range(trials):
        run("trial_ledger.py", "log", "--id", f"{name}{k}", "--ledger", led)
    la, pm = os.path.join(TMP, f"{name}_la.json"), os.path.join(TMP, f"{name}_pm.json")
    json.dump({"verdict": "LEAK" if leak else "PASS"}, open(la, "w")); json.dump({"verdict": "PASS"}, open(pm, "w"))
    args = ["pipeline.py", "--gross", gp, "--benchmark", bp, "--factors", fp, "--positions", pp, "--group", "day",
            "--variants", vp, "--blocks", "8", "--ledger", led, "--lookahead-result", la, "--permutation-result", pm,
            "--workdir", os.path.join(TMP, name)]
    if costs:
        cp = os.path.join(TMP, f"{name}_c.json"); json.dump(costs, open(cp, "w")); args += ["--costs", cp]
    code, out, err = run(*args)
    return json.loads(out) if code == 0 else {"verdict": "ERROR", "err": err[-400:]}

neutral = lambda b: random.gauss(0.08 / 252, 0.05 / math.sqrt(252))
r = suite_case("noise", lambda b: random.gauss(0, 0.01), turnover=0.05)
check("suite: noise is NOT_READY with DSR < 0.5", r["verdict"] == "NOT_READY" and r["results"]["validate_backtest"]["deflated_sharpe_prob"] < 0.5, str(r)[-300:])
r = suite_case("premium3x", neutral, turnover=0.01, costs={"spread_bps": 6, "slippage_bps": 9})
check("suite: strong premium at 3x costs is READY_FOR_PAPER", r["verdict"] == "READY_FOR_PAPER", json.dumps({k: r.get(k) for k in ("verdict", "hard_reasons", "soft_reasons")}))
r = suite_case("leaked", neutral, leak=True)
check("suite: a look-ahead leak is NOT_READY", r["verdict"] == "NOT_READY" and any("lookahead" in x for x in r.get("hard_reasons", [])))
r = suite_case("betaclone", lambda b: b + random.gauss(0, 0.001))
check("suite: long-only SPY clone is BETA_OR_STYLE and not READY", r["results"].get("attribution", {}).get("verdict") == "BETA_OR_STYLE" and r["verdict"] != "READY_FOR_PAPER", str(r.get("soft_reasons")))
r = suite_case("neutral16", neutral)
vb = r.get("results", {}).get("validate_backtest", {})
check("suite: market-neutral Sharpe 1.6 passes without beating SPY", r["verdict"] == "READY_FOR_PAPER" and vb.get("excess_vs_buy_and_hold", 0) < 0, json.dumps({k: r.get(k) for k in ("verdict", "hard_reasons", "soft_reasons")}))

# interlisted.py
il = {"symbol": "RY", "ratio": 1, "ca": {"bid": 180.00, "ask": 180.05, "ts": "2026-11-25T14:30:01-05:00"},
      "us": {"bid": 127.80, "ask": 127.83, "ts": "2026-11-25T14:30:02-05:00"},
      "fx": {"bid": 1.4085, "ask": 1.4087, "ts": "2026-11-25T14:30:01-05:00", "source": "broker"},
      "fees": {"ca_per_trade_cad": 4.95, "us_per_trade_usd": 4.95, "fx_spread_bps": 150}, "amount_cad": 10000}
def il_run(mode, d):
    fp = os.path.join(TMP, f"il_{mode}.json"); json.dump(d, open(fp, "w"))
    code, out, err = run("interlisted.py", mode, "--input", fp); return json.loads(out) if code == 0 else {"verdict": "ERROR", "err": err}
r = il_run("pair", il)
check("interlisted: fair pair with 150 bps FX is NO_EDGE", r["verdict"] == "NO_EDGE" and abs(r["premium_bps_tsx_over_us"]) < 5, str(r))
gap = json.loads(json.dumps(il)); gap["fees"]["fx_spread_bps"] = 0; gap["us"].update(bid=129.5, ask=129.52)
r = il_run("pair", gap)
check("interlisted: 130 bps gap with free FX clears costs", r["verdict"] == "EDGE_AFTER_COSTS" and r["net_cad"] > 0, str(r))
st = json.loads(json.dumps(il)); st["us"]["ts"] = "2026-11-25T14:31:02-05:00"
check("interlisted: quotes 61 s apart are STALE", il_run("pair", st)["verdict"] == "STALE")
cl = json.loads(json.dumps(il)); cl["ca"]["ts"] = cl["us"]["ts"] = cl["fx"]["ts"] = "2026-11-28T11:00:00-05:00"
check("interlisted: Saturday quotes are STALE", il_run("pair", cl)["verdict"] == "STALE")
bc = json.loads(json.dumps(gap)); bc["fx"]["source"] = "boc"
check("interlisted: Bank of Canada rate caps verdict at INDICATIVE", il_run("pair", bc)["verdict"] == "INDICATIVE")
check("interlisted: buy picks TSX when FX costs 150 bps", il_run("buy", il)["verdict"] == "BUY_TSX")
r = il_run("norbert", {"amount_cad": 10000, "dlr_ask_cad": 14.10, "dlr_u_bid_usd": 10.00,
                       "fees": {"per_trade_cad": 4.95, "per_trade_usd": 4.95}, "broker_fx_rate": 1.43})
check("interlisted: Norbert's gambit beats a 1.43 broker rate", r["verdict"] == "GAMBIT_CHEAPER" and r["units"] == 708 and abs(r["gambit_saves_usd"] - 90.61) < 0.01, str(r))

# engine.py: output is accepted by validate_backtest --manifest on alignment, lookahead, same-bar and costs
eg = os.path.join(TMP, "eng"); os.makedirs(eg, exist_ok=True); rr = random.Random(1); pz = 100.0; dd = datetime.date(2022, 1, 3); bars = []
while len(bars) < 600:
    if dd.weekday() < 5:
        o_ = pz * (1 + rr.gauss(0, 0.003)); c_ = o_ * (1 + rr.gauss(0.0004, 0.01))
        bars.append([dd.isoformat(), round(o_, 4), round(max(o_, c_) * 1.003, 4), round(min(o_, c_) * 0.997, 4), round(c_, 4)]); pz = c_
    dd += datetime.timedelta(days=1)
with open(os.path.join(eg, "bars.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["date", "open", "high", "low", "close"]); w.writerows(bars)
open(os.path.join(eg, "sig.py"), "w").write("class SignalEngine:\n    def generate(self, bars):\n        c=[b['close'] for b in bars]\n        return [1.0 if i>=20 and c[i]>sum(c[i-20:i])/20 else 0.0 for i in range(len(c))]\n")
code, out, err = run("engine.py", "--bars", os.path.join(eg, "bars.csv"), "--signal", os.path.join(eg, "sig.py"), "--market", "us_equity", "--out", os.path.join(eg, "out"))
check("engine runs", code == 0, err[-300:])
D_ = [b[0] for b in bars]
folds_ = [{"train_start": D_[0], "train_end": D_[199], "test_start": D_[200], "test_end": D_[332]},
          {"train_start": D_[0], "train_end": D_[332], "test_start": D_[333], "test_end": D_[465]},
          {"train_start": D_[0], "train_end": D_[465], "test_start": D_[466], "test_end": D_[-1]}]
open(os.path.join(eg, "reg.csv"), "w").write("date,label\n" + "".join(f"{d},{'a' if i < 300 else 'b'}\n" for i, d in enumerate(D_)))
json.dump({"periods_per_year": 252, "gross_equity": "out/gross.csv", "net_equity": "out/net.csv", "turnover": "out/turnover.csv",
           "costs": {"fee_bps": 1, "slippage_bps": 4}, "benchmark": "out/gross.csv", "trades": "out/trades.csv", "trials": 3,
           "universe": {"single_instrument": True}, "walk_forward": {"folds": folds_}, "regimes": "reg.csv", "llm_in_loop": False},
          open(os.path.join(eg, "m.json"), "w"))
code, out, _ = run("validate_backtest.py", "--manifest", os.path.join(eg, "m.json"))
vb_ = json.loads(out)["checks"]
check("engine output passes alignment, lookahead, same-bar and cost checks",
      all(vb_[k]["status"] == "pass" for k in ("alignment", "lookahead", "same_bar", "costs")), str({k: v.get("why") for k, v in vb_.items()}))
check("a plain 20-day SMA rule does not pass the full gate", json.loads(out)["verdict"] == "fail")

# golden fixtures: validate_backtest --manifest (every check's failure path) and legacy-mode refusals
g = subprocess.run([sys.executable, os.path.join(HERE, "golden", "run_golden.py")], capture_output=True, text=True)
check("golden validate_backtest fixtures", g.returncode == 0, g.stdout[-1500:])
print(g.stdout.strip().splitlines()[-1] if g.stdout.strip() else "")

# order-flow MCP: github commit pin, and crypto order-flow context gates
import importlib, json as _j
from datetime import datetime as _dt
sys.path.insert(0, SCRIPTS)
_ml = importlib.import_module("mcp_lock"); _rc = importlib.import_module("risk_check")
_lock = _j.load(open(os.path.join(HERE, "..", "assets", "mcp-lock.json")))
_sha = _lock["servers"]["orderflow"]["commit"]
def _cfg(arg):
    return {"mcpServers": {"orderflow": {"command": "npx", "args": ["-y", arg]}}}
_L = _j.load(open(os.path.join(HERE, "..", "assets", "risk-limits.json")))
_o = {"symbol": "BTC/USD", "side": "buy", "asset_class": "crypto"}
def _tg(of, side="buy"):
    b, w = [], []
    m = _rc.timing_gates(_L, dict(_o, side=side), {"orderflow": of}, _dt(2026, 11, 25, 12), b, w)
    return m, b, w
for name, cond in (
        ("orderflow pinned by commit PINNED", _ml.check_config(_cfg("github:zadescoxp/order-flow-mcp#" + _sha), _lock)["verdict"] == "PINNED"),
        ("orderflow on a branch UNPINNED", _ml.check_config(_cfg("github:zadescoxp/order-flow-mcp"), _lock)["verdict"] == "UNPINNED"),
        ("liquidation cascade blocks crypto entry", bool(_tg({"liq_cascade": True, "stream_age_s": 600})[1])),
        ("warming-up stream is ignored", not _tg({"liq_cascade": True, "warming_up": True})[1]),
        ("crowded funding cuts long size", _tg({"funding_8h_pct": 0.15, "stream_age_s": 600})[0] < 1),
        ("crowded funding leaves short size", _tg({"funding_8h_pct": 0.15, "stream_age_s": 600}, side="sell")[0] == 1)):
    print(("PASS " if cond else "FAIL ") + name); fails += [] if cond else [name]
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
