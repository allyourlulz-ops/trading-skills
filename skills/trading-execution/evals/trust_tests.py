#!/usr/bin/env python3
"""Phase 1 trust-boundary tests (register T1-T9, plus P1-P3 and P9-P12 where they map).
Each test forges one agent-written input (a fake --now, a relabelled asset class, an instrument
override, tampered limits, an unreconciled portfolio, an out-of-scope mandate, a bad fill) and expects
the gate to fail closed. Most tests have an honest control next to them that must still pass, so a fix
cannot "pass" by refusing everything. Stdlib only, no network. Every gate dir is a temp dir outside
the repository.

Usage: trust_tests.py [-k SUBSTRING ...]     exit 0 when every selected test passes
"""
import argparse, copy, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
REPO = os.path.dirname(os.path.dirname(SKILL))
F = os.path.join(HERE, "golden", "fixtures")
NOW = "2026-11-25T10:30:00-05:00"
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def jl(p):
    return json.load(open(p))


ORDER = jl(os.path.join(F, "order_pass.json"))          # AAPL buy 52 @190, stop 185, target 205
LIMITS = jl(os.path.join(F, "limits.json"))
LIMITS_OPEN = jl(os.path.join(F, "limits_open.json"))
CONTRACT = jl(os.path.join(F, "contract_aapl.json"))
PORTFOLIO = {
    "as_of": NOW, "base_currency": "USD", "equity": 25000, "buying_power": 20000, "settled_cash": 20000,
    "paper": True, "clock": {"is_open": True, "source": "alpaca:get_clock", "as_of": NOW},
    "positions": [], "positions_source": {"source": "alpaca:get_all_positions", "as_of": NOW},
    "today": {"trades": 0, "orders": 0, "realized_pnl": 0, "planned_loss": 0}}


def quote_contract(sym, now=NOW):
    c = copy.deepcopy(CONTRACT)
    c["decision_time"] = now
    s = c["series"][0]
    s.update(name=sym + " quote", symbol=sym, as_of=now, last_bar_end=now)
    return c


class Env:
    """A temp work dir and a fresh gate dir, both outside the repo."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="trust-")
        self.gate = os.path.join(self.tmp, "gate")
        self.n = 0

    def write(self, obj, name=None, raw=None):
        self.n += 1
        p = os.path.join(self.tmp, name or ("f%d.json" % self.n))
        with open(p, "w") as f:
            f.write(raw if raw is not None else json.dumps(obj))
        return p

    def run(self, script, *args, env=None, cwd=None):
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + [str(a) for a in args],
                           capture_output=True, text=True, env=env, cwd=cwd)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            out = {"_stdout": p.stdout[-800:], "_stderr": p.stderr[-800:]}
        return p.returncode, out

    def rc(self, order=None, pf=None, limits=None, contract="aapl", instrument=None, now=NOW, mode="paper",
           extra=(), instrument_raw=None, gate=None):
        o = ORDER if order is None else order
        args = ["--order", self.write(o), "--portfolio", self.write(PORTFOLIO if pf is None else pf),
                "--mode", mode, "--limits", self.write(LIMITS if limits is None else limits),
                "--gate-dir", gate or self.gate]
        if now is not None:
            args += ["--now", now]
        if contract == "aapl":
            contract = quote_contract(str(o.get("symbol")), now or NOW)
        if contract is not None:
            args += ["--contract", self.write(contract)]
        if instrument is not None or instrument_raw is not None:
            args += ["--instrument", self.write(instrument, raw=instrument_raw)]
        return self.run("risk_check.py", *(args + list(extra)))

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def codes(out):
    return [str(r).split(":", 1)[0] for r in out.get("reasons") or []]


def failed(res, code=None):
    """risk_check refused: exit 1 (fail) or 2 (bad input) and, when given, the reason code is present."""
    ex, out = res
    if ex == 0 or out.get("verdict") == "pass":
        return False
    return code is None or code in codes(out) or code in str(out.get("error", ""))


def passed(res):
    ex, out = res
    return ex == 0 and out.get("verdict") == "pass" and out.get("nonce", "").startswith("RC2.PASS.")


# ---------------------------------------------------------------- T1 asset class from the spec
OPT = "AAPL261218C00200000"


@test
def T1_option_symbol_labelled_equity_fails(e):
    o = dict(ORDER, symbol=OPT, qty=3, limit_price=2.5, stop_price=2.0, target_price=4.0, asset_class="equity")
    return failed(e.rc(order=o), "ASSET_CLASS")


@test
def T1_equity_label_with_multiplier_100_fails(e):
    return failed(e.rc(order=dict(ORDER, qty=1), instrument={"multiplier": 100}), "ASSET_CLASS")


@test
def T1_order_and_spec_disagree_fails(e):
    return failed(e.rc(instrument={"asset_class": "etf"}), "ASSET_CLASS")


@test
def T1_stock_symbol_labelled_crypto_fails(e):
    o = dict(ORDER, asset_class="crypto", qty=1)
    return failed(e.rc(order=o, limits=LIMITS_OPEN), "ASSET_CLASS")


@test
def T1_etf_label_without_spec_fails(e):
    o = dict(ORDER, symbol="SPY", asset_class="etf", qty=1, limit_price=600, stop_price=590, target_price=630)
    return failed(e.rc(order=o), "ASSET_CLASS")


@test
def T1_control_spec_agrees_passes(e):
    return passed(e.rc(instrument={"asset_class": "equity"}))


@test
def T1_control_asset_class_derived_when_omitted(e):
    o = {k: v for k, v in ORDER.items() if k != "asset_class"}
    ex, out = e.rc(order=o)
    return passed((ex, out)) and (out.get("sizing") or {}).get("asset_class") == "equity"


@test
def T1_control_etf_with_spec_passes(e):
    o = dict(ORDER, symbol="SPY", asset_class="etf", qty=1, limit_price=600, stop_price=590, target_price=630)
    return passed(e.rc(order=o, instrument={"asset_class": "etf"}))


# ---------------------------------------------------------------- T2 --now anchored to the broker clock (P1)
def pf_clock(**clk):
    pf = copy.deepcopy(PORTFOLIO)
    pf["clock"] = dict(pf["clock"], **clk)
    pf["clock"] = {k: v for k, v in pf["clock"].items() if v is not None}
    return pf


@test
def T2_clock_without_broker_timestamp_fails(e):
    return failed(e.rc(pf=pf_clock(as_of=None)), "NO_CLOCK")


@test
def T2_now_far_from_broker_clock_fails(e):
    return failed(e.rc(now="2026-11-25T11:30:00-05:00", contract=quote_contract("AAPL", "2026-11-25T11:30:00-05:00")),
                  "CLOCK_DRIFT")


@test
def T2_now_within_tolerance_passes_and_reports_drift(e):
    ex, out = e.rc(now="2026-11-25T10:31:00-05:00")
    c = out.get("clock") or {}
    return passed((ex, out)) and c.get("drift_s") == 60 and c.get("tolerance_s") == 120 and c.get("source")


@test
def T2_naive_now_refused(e):
    return failed(e.rc(now="2026-11-25T10:30:00", contract=quote_contract("AAPL")))


@test
def T2_crypto_needs_broker_clock(e):
    o = jl(os.path.join(F, "order_btc.json"))
    pf = copy.deepcopy(PORTFOLIO); pf.pop("clock")
    sat = "2026-11-28T03:00:00-05:00"
    return failed(e.rc(order=o, pf=pf, limits=LIMITS_OPEN, now=sat, contract=quote_contract("BTC/USD", sat)), "NO_CLOCK")


@test
def T2_live_check_far_from_system_clock_fails(e):
    pf = dict(PORTFOLIO, paper=False)
    return failed(e.rc(pf=pf, mode="live", limits=dict(LIMITS, paper=False)), "CLOCK_DRIFT")


@test
def T2_P1_rewound_now_cannot_reopen_an_expired_nonce(e):
    lim = dict(LIMITS, gate={"token_ttl_s": 1})
    lp = e.write(lim, "lim_ttl1.json")
    op = e.write(ORDER, "o.json")
    ex, out = e.run("risk_check.py", "--order", op, "--portfolio", e.write(PORTFOLIO), "--mode", "paper",
                    "--limits", lp, "--gate-dir", e.gate, "--now", NOW, "--contract", e.write(quote_contract("AAPL")))
    if not passed((ex, out)):
        return False
    time.sleep(2.2)
    vx, v = e.run("gate.py", "verify", "--nonce", out["nonce"], "--order", op, "--mode", "paper", "--limits", lp,
                  "--gate-dir", e.gate, "--now", NOW, "--no-consume")
    return vx == 1 and v.get("gate") == "CLOSED" and any("expired" in r for r in v.get("reasons", []))


@test
def T2_nonce_ttl_capped_at_300s(e):
    ex, out = e.rc(limits=dict(LIMITS, gate={"token_ttl_s": 86400}))
    from datetime import datetime
    exp = int(str(out.get("nonce", "")).split(".")[4]) if out.get("nonce") else 10 ** 12
    return passed((ex, out)) and exp - datetime.fromisoformat(NOW).timestamp() <= 300


# ---------------------------------------------------------------- P3 entry window in the limits timezone
def at(ts):
    return dict(now=ts, pf=pf_clock(as_of=ts), contract=quote_contract("AAPL", ts))


@test
def P3_utc_now_inside_the_et_window_passes(e):
    return passed(e.rc(**at("2026-11-25T16:00:00+00:00")))  # 11:00 New York


@test
def P3_pacific_now_after_the_et_cutoff_fails(e):
    return failed(e.rc(**at("2026-11-25T12:45:00-08:00")), "ENTRY_WINDOW")  # 15:45 New York, cutoff 15:30


@test
def P3_checked_at_is_in_the_limits_timezone(e):
    ex, out = e.rc(**at("2026-11-25T16:00:00+00:00"))
    return str(out.get("checked_at", "")).endswith("-05:00") and "T11:00" in str(out.get("checked_at"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-k", action="append", default=[], help="run only tests whose name contains this")
    a = ap.parse_args()
    sel = [t for t in TESTS if not a.k or any(k in t.__name__ for k in a.k)]
    bad = []
    for t in sel:
        e = Env()
        try:
            ok = bool(t(e))
        except Exception as x:  # a crash is a failure, never a skip
            ok = False
            print("      %s: %s" % (type(x).__name__, x))
        finally:
            e.close()
        print(("PASS " if ok else "FAIL ") + t.__name__)
        bad += [] if ok else [t.__name__]
    print("%d/%d trust tests passed" % (len(sel) - len(bad), len(sel)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
