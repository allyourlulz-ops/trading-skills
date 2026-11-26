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
from gate import file_sha256, fingerprint, issue
GD = os.path.join(TMP, "gate")
def mcheck(order, **kw):
    mode = kw.get("mode", m.get("mode", "paper"))
    lp = os.path.join(HERE, "..", "assets", "risk-limits.json")
    tok = issue("PASS", fingerprint(order, file_sha256(lp)), mode, lp, d=GD,
                now="2026-11-24T10:00:00", extra={"equity": 25000, "checked_at": "2026-11-24T10:00:00-05:00",
                                                  "asset_class": "equity", "notional": order["qty"] * order["limit_price"]})
    json.dump({"verdict": "pass", "nonce": tok}, open(rp, "w"))
    json.dump(dict(m, **kw), open(mp, "w")); json.dump(order, open(op, "w"))
    # T8: the user signs the mandate once (an invalid one is refused and stays unsigned)
    subprocess.run([sys.executable, "mandate.py", "sign", "--mandate", mp, "--ack",
                    "I sign this mandate and accept losses inside its limits", "--gate-dir", GD], cwd=SCRIPTS, capture_output=True)
    # T5: entries need a MATCHED reconcile with the broker's equity first
    json.dump([], open(os.path.join(TMP, "fills.json"), "w")); json.dump({"equity": "25000"}, open(os.path.join(TMP, "acct.json"), "w"))
    subprocess.run([sys.executable, "mandate.py", "reconcile", "--broker", os.path.join(TMP, "fills.json"), "--account",
                    os.path.join(TMP, "acct.json"), "--ledger", os.path.join(TMP, "l.jsonl"), "--mandate", mp,
                    "--gate-dir", GD], cwd=SCRIPTS, capture_output=True)
    p = subprocess.run([sys.executable, "mandate.py", "check", "--order", op, "--risk", rp, "--mandate", mp,
                        "--ledger", os.path.join(TMP, "l.jsonl"), "--now", "2026-11-24T10:00:00", "--gate-dir", GD], cwd=SCRIPTS, capture_output=True, text=True)
    return json.loads(p.stdout)
# funding gate with this skill's own risk-limits.json: cost/tail-risk dampener, off switch, settlement skip
from datetime import datetime as _dt
import risk_check as _rc
_L = json.load(open(os.path.join(HERE, "..", "assets", "risk-limits.json")))
def _fg(of, **timing):
    b, w = [], []
    m = _rc.timing_gates(dict(_L, timing=dict(_L["timing"], **timing)), {"symbol": "BTC/USD", "side": "buy", "asset_class": "crypto"},
                         {"orderflow": dict({"funding_8h_pct": 0.15, "stream_age_s": 600}, **of)}, _dt(2026, 11, 25, 12), b, w)
    return m, w
for name, cond in (("limits carry funding_gate_mode and funding_cost_multiplier",
                    _L["timing"].get("funding_gate_mode") == "cost_risk" and "funding_cost_multiplier" in _L["timing"]),
                   ("funding paid by longs dampens size", _fg({})[0] < 1 and "not a return forecast" in " ".join(_fg({})[1])),
                   ("funding gate off leaves size", _fg({}, funding_gate_mode="off")[0] == 1),
                   ("hold crossing no settlement leaves size", _fg({"crosses_settlement": False})[0] == 1)):
    print(("PASS " if cond else "FAIL ") + name); fails += [] if cond else [name]
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
# repro: whole place-it path (portfolio -> order -> risk_check -> preview -> simulated fill) vs expected.json
r = subprocess.run([sys.executable, os.path.join(HERE, "repro.py"), "--all"], capture_output=True, text=True)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
if r.returncode:
    print(r.stdout + r.stderr[-500:]); fails.append("repro")
# trust boundary (Phase 1, T1-T9): each forged agent-written input must fail closed
t = subprocess.run([sys.executable, os.path.join(HERE, "trust_tests.py")], capture_output=True, text=True)
print(t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
if t.returncode:
    print(t.stdout + t.stderr[-500:]); fails.append("trust")
# record_alpaca: paper host only, keys from env only (no network is touched by these checks)
sys.path.insert(0, HERE)
import record_alpaca as _ra
import repro as _rp
import record_ibkr as _ib
def _refused_ib(u):
    try:
        _ib.local_gateway(u); return False
    except ValueError:
        return True
def _refused_acct(a, w):
    try:
        _ib.paper_account(a, w); return False
    except ValueError:
        return True
def _refused(u):
    try:
        _ra.paper_only(u); return False
    except ValueError:
        return True
for name, cond in (
        ("record_alpaca accepts only the paper host", _ra.paper_only("https://paper-api.alpaca.markets/") == _ra.PAPER),
        ("record_alpaca refuses live, http, port, path and look-alike hosts", all(_refused(u) for u in (
            "https://api.alpaca.markets", "http://paper-api.alpaca.markets", "https://paper-api.alpaca.markets:8443",
            "https://paper-api.alpaca.markets/v2", "https://paper-api.alpaca.markets.evil.com", "https://u@paper-api.alpaca.markets"))),
        ("record_alpaca redacts account_number and id", _ra.redact({"id": "x", "account_number": "y", "equity": "1"}) ==
         {"id": "REDACTED", "account_number": "REDACTED", "equity": "1"}),
        ("record_alpaca without keys exits 2 before any request", subprocess.run(
            [sys.executable, os.path.join(HERE, "record_alpaca.py"), "--out", os.path.join(TMP, "rec")], capture_output=True,
            env={k: v for k, v in os.environ.items() if not k.startswith("APCA_")}).returncode == 2
         and not os.path.exists(os.path.join(TMP, "rec"))),
        ("record_ibkr accepts only a local https gateway", all(_refused_ib(u) for u in (
            "http://localhost:5000/v1/api", "https://api.ibkr.com/v1/api", "https://localhost.evil.com/v1/api")) and
         _ib.local_gateway("https://localhost:5000/v1/api/") == "https://localhost:5000/v1/api"),
        ("record_ibkr refuses any account id not starting with DU", _ib.paper_account([{"accountId": "DU1"}]) == "DU1" and
         all(_refused_acct(a, w) for a, w in (([{"accountId": "U1"}], None), ([{"accountId": "DU1"}, {"accountId": "U2"}], "U2"),
                                               ([{"accountId": "DU1"}, {"accountId": "U2"}], None), ([{"accountId": "DU1"}], "DU9")))),
        ("record_ibkr redacts every account id and the account names", _ib.redact(
            {"accountId": "DU123", "displayName": "Jo", "x": ["DU123 acct", "U999"]}, ["DU123", "U999"]) ==
         {"accountId": "DU-REDACTED", "displayName": "REDACTED", "x": ["DU-REDACTED acct", "U-REDACTED"]}),
        ("record_ibkr has no order or POST call", not any(w in open(os.path.join(HERE, "record_ibkr.py")).read()
                                                          for w in ('method="POST"', "/iserver/account/", "/orders"))),
        ("repro trims nanosecond Alpaca timestamps for py3.9", _rp._iso("2026-11-25T10:30:00.123456789-05:00") ==
         "2026-11-25T10:30:00.123456-05:00")):
    print(("PASS " if cond else "FAIL ") + name); fails += [] if cond else [name]
print(f"\n{len(fails)} failed" if fails else "\nall passed"); sys.exit(1 if fails else 0)
