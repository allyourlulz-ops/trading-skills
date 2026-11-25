#!/usr/bin/env python3
"""Offline checks for trading-execution: scripts compile and answer --help, and the shared risk
scripts match trading-research's copies byte for byte when both skills sit in one repo."""
import filecmp, os, py_compile, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); SCRIPTS = os.path.join(HERE, "..", "scripts")
TMP = tempfile.mkdtemp(); fails = []
for f in sorted(os.listdir(SCRIPTS)):
    if f.endswith(".py"):
        try:
            py_compile.compile(os.path.join(SCRIPTS, f), cfile=os.path.join(TMP, f + "c"), doraise=True); ok = True
        except py_compile.PyCompileError:
            ok = False
        code = subprocess.run([sys.executable, f, "--help"], cwd=SCRIPTS, capture_output=True).returncode
        for name, cond in ((f"compile {f}", ok), (f"help {f}", code == 0)):
            print(("PASS " if cond else "FAIL ") + name); fails += [] if cond else [name]
other = os.path.join(HERE, "..", "..", "trading-research", "scripts")
if os.path.isdir(other):
    for f in ("risk_check.py", "position_size.py", "strategy_health.py", "gate.py", "data_contract.py", "mcp_lock.py"):
        same = filecmp.cmp(os.path.join(SCRIPTS, f), os.path.join(other, f), shallow=False)
        print(("PASS " if same else "FAIL ") + f"{f} matches trading-research"); fails += [] if same else [f]
# probe mandates: paper only, quarter-size orders
import json
m = json.load(open(os.path.join(HERE, "..", "assets", "mandate.example.json")))
m.update({"probe": True, "granted_on": "2026-11-20", "expires_on": "2026-12-15"})
mp, op, rp = (os.path.join(TMP, x) for x in ("m.json", "o.json", "r.json"))
sys.path.insert(0, SCRIPTS)
from gate import fingerprint, issue
GD = os.path.join(TMP, "gate")
def mcheck(order, **kw):
    mode = kw.get("mode", m.get("mode", "paper"))
    tok = issue("PASS", fingerprint(order), mode, os.path.join(HERE, "..", "assets", "risk-limits.json"), d=GD,
                now="2026-11-24T10:00:00")
    json.dump({"verdict": "pass", "nonce": tok}, open(rp, "w"))
    json.dump(dict(m, **kw), open(mp, "w")); json.dump(order, open(op, "w"))
    p = subprocess.run([sys.executable, "mandate.py", "check", "--order", op, "--risk", rp, "--mandate", mp,
                        "--ledger", os.path.join(TMP, "l.jsonl"), "--now", "2026-11-24T10:00:00", "--gate-dir", GD], cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(p.stdout)
base = {"symbol": "SPY", "side": "buy", "qty": 1, "limit_price": 200, "stop_price": 190, "strategy": "ema9-pullback-v2", "client_order_id": "c1", "paper": True}
for name, cond in (("probe small order AUTO_OK", mcheck(base)["verdict"] == "AUTO_OK"),
                   ("probe order over quarter size NEEDS_YES", mcheck(dict(base, qty=2))["verdict"] == "NEEDS_YES"),
                   ("legacy *_usd mandate keys still cap", mcheck(dict(base, qty=2), max_order=None, max_order_usd=1000)["verdict"] == "NEEDS_YES"),
                   ("probe live mandate HALT", mcheck(base, mode="live")["verdict"] == "HALT")):
    print(("PASS " if cond else "FAIL ") + name); fails += [] if cond else [name]
# golden fixtures: position_size, risk_check, gate, preview, data_contract, mcp_lock (failure paths included)
g = subprocess.run([sys.executable, os.path.join(HERE, "golden", "run_golden.py")], capture_output=True, text=True)
print(g.stdout.strip().splitlines()[-1] if g.stdout.strip() else g.stderr[-300:])
if g.returncode:
    print(g.stdout); fails.append("golden")
print(f"\n{len(fails)} failed" if fails else "\nall passed"); sys.exit(1 if fails else 0)
