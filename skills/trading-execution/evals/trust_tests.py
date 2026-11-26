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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


# ---------------------------------------------------------------- T3 margin and exits from broker data (P10)
def pf_with(**kw):
    pf = copy.deepcopy(PORTFOLIO)
    pf.update(kw)
    return {k: v for k, v in pf.items() if v is not None}


HELD_AAPL = [{"symbol": "AAPL", "side": "long", "qty": 10, "price": 190, "stop": 185, "currency": "USD"}]
EXIT = dict(jl(os.path.join(F, "order_exit.json")))


@test
def T3_margin_derived_from_settled_cash_fails(e):
    return failed(e.rc(pf=pf_with(settled_cash=1000)), "MARGIN_OFF")


@test
def T3_uses_margin_false_cannot_hide_margin(e):
    return failed(e.rc(order=dict(ORDER, uses_margin=False), pf=pf_with(settled_cash=1000)), "MARGIN_OFF")


@test
def T3_missing_settled_cash_fails(e):
    return failed(e.rc(pf=pf_with(settled_cash=None)), "NO_CASH")


@test
def T3_short_entry_is_margin(e):
    o = jl(os.path.join(F, "order_short.json"))
    return failed(e.rc(order=o, limits=dict(LIMITS_OPEN, allow_margin=False)), "MARGIN_OFF")


@test
def T3_control_cash_covers_the_order_passes(e):
    ex, out = e.rc()
    return passed((ex, out)) and (out.get("margin") or {}).get("uses_margin") is False


@test
def T3_exit_without_broker_positions_read_fails(e):
    return failed(e.rc(order=EXIT, pf=pf_with(positions=HELD_AAPL, positions_source=None)), "EXIT_UNVERIFIED")


@test
def T3_exit_on_stale_positions_read_fails(e):
    pf = pf_with(positions=HELD_AAPL, positions_source={"source": "alpaca:get_all_positions", "as_of": "2026-11-24T10:30:00-05:00"})
    return failed(e.rc(order=EXIT, pf=pf), "EXIT_UNVERIFIED")


@test
def T3_control_verified_exit_passes(e):
    return passed(e.rc(order=EXIT, pf=pf_with(positions=HELD_AAPL)))


MANDATE = jl(os.path.join(SKILL, "assets", "mandate.example.json"))


MANDATE_ACK = "I sign this mandate and accept losses inside its limits"


def sign_mandate(e, mp, ack=MANDATE_ACK):
    return e.run("mandate.py", "sign", "--mandate", mp, "--ack", ack, "--gate-dir", e.gate)


def mandate_check(e, order, mandate=None, ledger=(), rc_kw=None, limits=None, now=NOW, extra=(), reconcile=None,
                  after_reconcile=None, sign=True, after_sign=None):
    """risk_check this order, optionally mandate.py reconcile (reconcile = {"fills": [...], "account": {...}}),
    then mandate.py check it. Returns (exit, out, risk_out)."""
    lim = LIMITS if limits is None else limits
    ex, risk = e.rc(order=order, limits=lim, **(rc_kw or {}))
    rp = e.write(risk, "risk.json")
    mdir = os.path.join(e.tmp, "mandate"); os.makedirs(mdir, exist_ok=True)
    mp = os.path.join(mdir, "mandate.json")
    json.dump(MANDATE if mandate is None else mandate, open(mp, "w"))
    if sign:
        e.last_sign = sign_mandate(e, mp)
    if after_sign:
        after_sign(mp)
    lp = os.path.join(mdir, "ledger.jsonl")
    with open(lp, "w") as f:
        for r in ledger:
            f.write(json.dumps(r) + "\n")
    if reconcile is not None:
        rargs = ["reconcile", "--broker", e.write(reconcile.get("fills", []), "fills.json"), "--ledger", lp,
                 "--mandate", mp, "--gate-dir", e.gate]
        if reconcile.get("account") is not None:
            rargs += ["--account", e.write(reconcile["account"], "account.json")]
        e.last_reconcile = e.run("mandate.py", *rargs)
    if after_reconcile:
        after_reconcile(mp, lp)
    args = ["check", "--order", e.write(order), "--risk", rp, "--mandate", mp, "--ledger", lp,
            "--gate-dir", e.gate, "--limits", e.write(lim, "limits_m.json")]
    if now:
        args += ["--now", now]
    mx, out = e.run("mandate.py", *(args + list(extra)))
    return mx, out, risk


TSLA_HELD = [{"symbol": "TSLA", "side": "long", "qty": 5, "price": 350, "stop": 330, "currency": "USD"}]


@test
def T3_mandate_exit_outside_the_mandate_needs_yes(e):
    o = dict(EXIT, symbol="TSLA", qty=5, limit_price=350.0, stop_price=None, target_price=None,
             client_order_id="m-tsla-x", strategy="ema9-pullback-v2")
    o = {k: v for k, v in o.items() if v is not None}
    mx, out, risk = mandate_check(e, o, rc_kw={"pf": pf_with(positions=TSLA_HELD), "contract": None})
    return risk.get("verdict") == "pass" and out.get("verdict") == "NEEDS_YES" and \
        any("TSLA not in the mandate" in r for r in out.get("reasons", []))


@test
def T3_mandate_exit_without_a_ledger_position_needs_yes(e):
    o = dict(EXIT, client_order_id="m-aapl-x", strategy="ema9-pullback-v2")
    mx, out, risk = mandate_check(e, o, rc_kw={"pf": pf_with(positions=HELD_AAPL), "contract": None})
    return risk.get("verdict") == "pass" and out.get("verdict") == "NEEDS_YES" and \
        any("no open AAPL position" in r for r in out.get("reasons", []))


# ---------------------------------------------------------------- T4 instrument override whitelist (P2)
@test
def T4_P2_equity_session_24x7_cannot_skip_market_closed(e):
    return failed(e.rc(pf=pf_clock(is_open=False), instrument={"session": "24x7"}), "INSTRUMENT")


@test
def T4_P2_multiplier_001_cannot_inflate_size(e):
    return failed(e.rc(order=dict(ORDER, qty=5263), instrument={"multiplier": 0.01}), "INSTRUMENT")


@test
def T4_gap_pct_below_the_class_default_fails(e):
    return failed(e.rc(instrument={"gap_pct": 0.0}), "INSTRUMENT")


@test
def T4_gap_pct_out_of_range_fails(e):
    return failed(e.rc(instrument={"gap_pct": 1.5}), "INSTRUMENT")


@test
def T4_lot_step_nan_fails(e):
    return failed(e.rc(instrument_raw='{"lot_step": NaN}'), "INSTRUMENT")


@test
def T4_lot_step_out_of_range_fails(e):
    return failed(e.rc(instrument={"lot_step": 1e9}), "INSTRUMENT")


@test
def T4_unknown_instrument_key_fails(e):
    return failed(e.rc(instrument={"max_loss_per_trade": 99999}), "INSTRUMENT")


@test
def T4_limits_defaults_cannot_change_the_session(e):
    lim = dict(LIMITS, instrument_defaults=dict(LIMITS.get("instrument_defaults") or {}, equity={"session": "24x7"}))
    return failed(e.rc(pf=pf_clock(is_open=False), limits=lim), "INSTRUMENT")


@test
def T4_position_size_cli_refuses_an_override(e):
    ex, out = e.run("position_size.py", "--symbol", "AAPL", "--entry", "190", "--stop", "185", "--portfolio",
                    e.write(PORTFOLIO), "--limits", e.write(LIMITS), "--instrument", e.write({"multiplier": 0.01}))
    return ex == 2 and "multiplier" in str(out.get("error"))


@test
def T4_control_whitelisted_overrides_pass(e):
    inst = {"asset_class": "equity", "currency": "USD", "lot_step": 0.001, "min_qty": 0.001, "gap_pct": 0.06,
            "cluster": "us_megacap_tech", "multiplier": 1, "session": "exchange", "source": "alpaca:get_asset"}
    return passed(e.rc(instrument=inst))


# ---------------------------------------------------------------- T5 reconcile before any entry
ENTRY = dict(ORDER, qty=5, client_order_id="m-aapl-1", strategy="ema9-pullback-v2")
ACCOUNT = {"equity": "25000", "cash": "20000", "currency": "USD"}   # Alpaca GET /v2/account shape
RECONCILED = {"fills": [], "account": ACCOUNT}


@test
def T5_entry_without_a_reconcile_needs_yes(e):
    mx, out, risk = mandate_check(e, ENTRY)
    return risk.get("verdict") == "pass" and out.get("verdict") != "AUTO_OK" and \
        any("reconcile" in r for r in out.get("reasons", []))


@test
def T5_ledger_changed_since_the_reconcile_needs_yes(e):
    def add_row(mp, lp):
        with open(lp, "a") as f:
            f.write(json.dumps({"ts": NOW, "mandate_id": MANDATE["id"], "client_order_id": "x", "symbol": "SPY",
                                "side": "buy", "qty": 1, "price": 600, "notional": 600, "is_exit": False}) + "\n")
    mx, out, risk = mandate_check(e, ENTRY, reconcile=RECONCILED, after_reconcile=add_row)
    return out.get("verdict") != "AUTO_OK" and any("since the last reconcile" in r for r in out.get("reasons", []))


@test
def T5_unreconciled_equity_halts(e):
    mx, out, risk = mandate_check(e, ENTRY, reconcile={"fills": [], "account": dict(ACCOUNT, equity="12000")})
    return out.get("verdict") == "HALT" and any("equity" in r for r in out.get("reasons", []))


@test
def T5_reconcile_without_the_account_needs_yes(e):
    mx, out, risk = mandate_check(e, ENTRY, reconcile={"fills": []})
    return out.get("verdict") != "AUTO_OK" and any("equity" in r for r in out.get("reasons", []))


@test
def T5_tampered_reconcile_stamp_halts(e):
    def tamper(mp, lp):
        p = lp + ".reconcile.json"
        d = json.load(open(p)); d["equity"] = 25000.0; d["verdict"] = "MATCHED"; d["ledger_sha256"] = "0" * 64
        json.dump(d, open(p, "w"))
    mx, out, risk = mandate_check(e, ENTRY, reconcile=RECONCILED, after_reconcile=tamper)
    return out.get("verdict") == "HALT" and any("reconcile" in r for r in out.get("reasons", []))


@test
def T5_control_reconciled_entry_is_auto_ok(e):
    mx, out, risk = mandate_check(e, ENTRY, reconcile=RECONCILED)
    return mx == 0 and out.get("verdict") == "AUTO_OK"


# ---------------------------------------------------------------- T6 limits contents bound to the nonce
def checked(e, limits=None):
    lp = e.write(LIMITS if limits is None else limits, "limits_t6.json")
    op = e.write(ORDER, "order_t6.json")
    ex, out = e.run("risk_check.py", "--order", op, "--portfolio", e.write(PORTFOLIO), "--mode", "paper",
                    "--limits", lp, "--gate-dir", e.gate, "--now", NOW, "--contract", e.write(quote_contract("AAPL")))
    return out, op, lp


@test
def T6_verify_without_limits_fails_closed(e):
    out, op, lp = checked(e)
    vx, v = e.run("gate.py", "verify", "--nonce", out.get("nonce"), "--order", op, "--mode", "paper", "--gate-dir",
                  e.gate, "--now", NOW, "--no-consume")
    return out.get("verdict") == "pass" and vx == 1 and v.get("gate") == "CLOSED"


@test
def T6_tampered_limits_close_the_preview(e):
    out, op, lp = checked(e)
    json.dump(dict(LIMITS, max_loss_per_trade=10 ** 6), open(lp, "w"))
    rp = e.write(out, "risk_t6.json")
    vx, v = e.run("preview.py", "--order", op, "--risk", rp, "--config", os.path.join(F, "cfg_paper.json"), "--limits", lp,
                  "--gate-dir", e.gate, "--now", NOW, "--json")
    return vx == 1 and v.get("gate") == "CLOSED"


@test
def T6_fingerprint_binds_the_limits_contents(e):
    a, _, _ = checked(e)
    b, _, _ = checked(e, dict(LIMITS, max_order=LIMITS["max_order"] + 0))  # same values, re-serialised
    c, _, _ = checked(e, dict(LIMITS, min_reward_risk=1.4))
    sys.path.insert(0, SCRIPTS)
    import gate
    return a.get("fingerprint") != gate.fingerprint(ORDER) and a.get("fingerprint") != c.get("fingerprint") \
        and a.get("limits_sha256") and a.get("limits_sha256") != c.get("limits_sha256")


@test
def T6_missing_limits_file_is_a_fail_not_nolimits(e):
    code = ("import sys; sys.path.insert(0, %r); import gate\n"
            "try:\n    tok = gate.issue('PASS', 'f' * 16, 'paper', %r, d=%r)\nexcept ValueError:\n    print('REFUSED'); sys.exit(0)\n"
            "ok, why, t = gate.verify(tok, {}, 'paper', %r, %r, consume=False)\nprint('OPEN' if ok else 'CLOSED')\n"
            % (SCRIPTS, os.path.join(e.tmp, "nope.json"), e.gate, os.path.join(e.tmp, "nope.json"), e.gate))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return p.stdout.strip() == "REFUSED"


# ---------------------------------------------------------------- T7 gate dir outside the project
def _cleanup(p):
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)


@test
def T7_gate_dir_inside_the_repo_fails(e):
    g = os.path.join(SKILL, "assets", ".t7-probe-gate")
    try:
        res = e.rc(gate=g)
        return failed(res) and res[1].get("nonce") is None and not os.path.exists(os.path.join(g, "gate.key"))
    finally:
        _cleanup(g)


@test
def T7_env_gate_dir_inside_the_skill_fails(e):
    g = os.path.join(SKILL, ".t7-env-gate")
    env = dict(os.environ, TRADING_GATE_DIR=g)
    args = ["--order", e.write(ORDER), "--portfolio", e.write(PORTFOLIO), "--mode", "paper", "--limits", e.write(LIMITS),
            "--now", NOW, "--contract", e.write(quote_contract("AAPL"))]
    try:
        res = e.run("risk_check.py", *args, env=env)
        return failed(res) and not os.path.exists(os.path.join(g, "gate.key"))
    finally:
        _cleanup(g)


@test
def T7_gate_dir_inside_the_callers_project_fails(e):
    proj = os.path.join(e.tmp, "agent-project"); os.makedirs(os.path.join(proj, ".git"))
    args = ["--order", e.write(ORDER), "--portfolio", e.write(PORTFOLIO), "--mode", "paper", "--limits", e.write(LIMITS),
            "--now", NOW, "--contract", e.write(quote_contract("AAPL")), "--gate-dir", os.path.join(proj, "state", "gate")]
    return failed(e.run("risk_check.py", *args, cwd=proj))


@test
def T7_symlinked_gate_dir_into_the_skill_fails(e):
    target = os.path.join(SKILL, ".t7-link-target"); os.makedirs(target, exist_ok=True)
    link = os.path.join(e.tmp, "gate-link")
    os.symlink(target, link)
    try:
        res = e.rc(gate=link)
        return failed(res) and not os.path.exists(os.path.join(target, "gate.key"))
    finally:
        _cleanup(target)


@test
def T7_gate_dir_is_resolved_and_printed(e):
    ex, out = e.rc()
    return passed((ex, out)) and out.get("gate_dir") == os.path.realpath(e.gate)


@test
def T7_preview_refuses_a_gate_dir_inside_the_repo(e):
    g = os.path.join(SKILL, ".t7-preview-gate")
    try:
        vx, v = e.run("preview.py", "--order", e.write(ORDER), "--nonce", "RC2.PASS.x", "--config",
                      os.path.join(F, "cfg_paper.json"), "--limits", e.write(LIMITS), "--gate-dir", g, "--json")
        return vx != 0 and v.get("gate") == "CLOSED" and not os.path.exists(g)
    finally:
        _cleanup(g)


@test
def T7_gate_where_prints_the_resolved_dir(e):
    vx, v = e.run("gate.py", "where", "--gate-dir", e.gate)
    bx, b = e.run("gate.py", "where", "--gate-dir", os.path.join(SKILL, ".t7-where"))
    return vx == 0 and v.get("gate_dir") == os.path.realpath(e.gate) and bx != 0 and not os.path.exists(os.path.join(SKILL, ".t7-where"))


# ---------------------------------------------------------------- T8 every mandate field, every call; signed
TSLA_ENTRY = dict(ENTRY, symbol="TSLA", qty=2, limit_price=350.0, stop_price=340.0, target_price=380.0, client_order_id="m-tsla-1")


def edit_mandate(**kw):
    def f(mp):
        m = json.load(open(mp)); m.update(kw); json.dump(m, open(mp, "w"))
    return f


@test
def T8_mandate_edited_after_signing_halts(e):
    mx, out, risk = mandate_check(e, TSLA_ENTRY, rc_kw={"contract": quote_contract("TSLA")}, reconcile=RECONCILED,
                                  after_sign=edit_mandate(symbols=MANDATE["symbols"] + ["TSLA"]))
    return risk.get("verdict") == "pass" and out.get("verdict") == "HALT" and \
        any("signature" in r for r in out.get("reasons", []))


@test
def T8_unsigned_mandate_needs_yes(e):
    mx, out, risk = mandate_check(e, ENTRY, reconcile=RECONCILED, sign=False)
    return out.get("verdict") == "NEEDS_YES" and any("not signed" in r for r in out.get("reasons", []))


@test
def T8_sign_needs_the_exact_ack(e):
    mp = e.write(MANDATE, "m_ack.json")
    ex, out = sign_mandate(e, mp, ack="sure, sign it")
    return ex != 0 and "signature" not in json.load(open(mp))


@test
def T8_unknown_mandate_field_halts(e):
    mx, out, risk = mandate_check(e, ENTRY, mandate=dict(MANDATE, max_ordr=10 ** 6), reconcile=RECONCILED, sign=False)
    return out.get("verdict") == "HALT" and any("max_ordr" in r for r in out.get("reasons", []))


OPT_ORDER = {"symbol": OPT, "side": "buy", "qty": 1, "type": "limit", "limit_price": 2.5, "time_in_force": "day",
             "client_order_id": "m-opt-1", "strategy": "ema9-pullback-v2", "paper": True, "risk_pct": 1}
OPT_MANDATE = dict(MANDATE, symbols=MANDATE["symbols"] + [OPT], require_stop=False)


@test
def T8_asset_class_comes_from_the_gate_not_the_order_label(e):
    mx, out, risk = mandate_check(e, OPT_ORDER, mandate=OPT_MANDATE, limits=LIMITS_OPEN, reconcile=RECONCILED,
                                  rc_kw={"contract": jl(os.path.join(F, "contract_opt.json"))})
    return risk.get("verdict") == "pass" and out.get("verdict") == "NEEDS_YES" and \
        any("asset class option" in r for r in out.get("reasons", []))


@test
def T8_order_notional_includes_the_multiplier(e):
    m = dict(OPT_MANDATE, asset_classes=["equity", "option"], max_order=100)
    mx, out, risk = mandate_check(e, OPT_ORDER, mandate=m, limits=LIMITS_OPEN, reconcile=RECONCILED,
                                  rc_kw={"contract": jl(os.path.join(F, "contract_opt.json"))})
    return risk.get("verdict") == "pass" and out.get("verdict") == "NEEDS_YES" and \
        any("over the mandate" in r for r in out.get("reasons", []))


@test
def T8_mandate_window_runs_on_the_gate_clock_not_now(e):
    m = dict(MANDATE, granted_on="2026-11-26", expires_on="2026-12-20")
    mx, out, risk = mandate_check(e, ENTRY, mandate=m, reconcile=RECONCILED, now="2026-11-27T10:00:00-05:00")
    return risk.get("verdict") == "pass" and out.get("verdict") != "AUTO_OK" and \
        any("not yet in force" in r for r in out.get("reasons", []))


@test
def T8_probe_verdict_without_the_probe_flag_halts(e):
    mx, out, risk = mandate_check(e, ENTRY, mandate=dict(MANDATE, pipeline_verdict="PAPER_PROBE", probe=False),
                                  reconcile=RECONCILED, sign=False)
    return out.get("verdict") == "HALT" and any("PAPER_PROBE" in r for r in out.get("reasons", []))


@test
def T8_mandate_caps_above_the_risk_limits_halt(e):
    mx, out, risk = mandate_check(e, ENTRY, mandate=dict(MANDATE, max_order=10 ** 6), reconcile=RECONCILED, sign=False)
    return out.get("verdict") == "HALT" and any("max_order" in r for r in out.get("reasons", []))


@test
def T8_mandate_short_without_limits_short_halts(e):
    mx, out, risk = mandate_check(e, ENTRY, mandate=dict(MANDATE, allow_short=True), reconcile=RECONCILED, sign=False)
    return out.get("verdict") == "HALT" and any("allow_short" in r for r in out.get("reasons", []))


@test
def T8_exit_under_an_edited_mandate_is_not_auto(e):
    led = [{"ts": NOW, "mandate_id": MANDATE["id"], "client_order_id": "m-aapl-0", "symbol": "AAPL", "side": "buy",
            "qty": 10, "price": 190, "notional": 1900, "is_exit": False}]
    o = dict(EXIT, client_order_id="m-aapl-x", strategy="ema9-pullback-v2")
    mx, out, risk = mandate_check(e, o, ledger=led, rc_kw={"pf": pf_with(positions=HELD_AAPL), "contract": None},
                                  after_sign=edit_mandate(max_daily_loss=70))
    return risk.get("verdict") == "pass" and out.get("verdict") == "HALT"


@test
def T8_control_signed_exit_of_a_mandate_position_is_auto_ok(e):
    led = [{"ts": NOW, "mandate_id": MANDATE["id"], "client_order_id": "m-aapl-0", "symbol": "AAPL", "side": "buy",
            "qty": 10, "price": 190, "notional": 1900, "is_exit": False}]
    o = dict(EXIT, client_order_id="m-aapl-x", strategy="ema9-pullback-v2")
    mx, out, risk = mandate_check(e, o, ledger=led, rc_kw={"pf": pf_with(positions=HELD_AAPL), "contract": None})
    return out.get("verdict") == "AUTO_OK"


# ---------------------------------------------------------------- T9 post-fill re-check against the nonce
def placed(e, order=None, preview=True):
    """risk_check + preview (consumes the nonce). Returns (nonce, order_path, limits_path)."""
    o = ORDER if order is None else order
    lp = e.write(LIMITS, "limits_t9.json"); op = e.write(o, "order_t9.json")
    ex, out = e.run("risk_check.py", "--order", op, "--portfolio", e.write(PORTFOLIO), "--mode", "paper", "--limits", lp,
                    "--gate-dir", e.gate, "--now", NOW, "--contract", e.write(quote_contract(o["symbol"])))
    if preview:
        e.run("preview.py", "--order", op, "--risk", e.write(out, "risk_t9.json"), "--config",
              os.path.join(F, "cfg_paper.json"), "--limits", lp, "--gate-dir", e.gate, "--now", NOW, "--json")
    return out.get("nonce"), op, lp


def fill_of(o, **kw):
    """An Alpaca order object after the fill (GET /v2/orders/{id} shape)."""
    f = {"client_order_id": o["client_order_id"], "symbol": o["symbol"], "side": o["side"], "qty": str(o["qty"]),
         "filled_qty": str(o["qty"]), "filled_avg_price": str(o["limit_price"]), "status": "filled",
         "type": o.get("type", "limit"), "limit_price": str(o["limit_price"]), "asset_class": "us_equity",
         "filled_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 5)) + ".123456789Z"}
    f.update(kw)
    return {k: v for k, v in f.items() if v is not None}


def verify_fill(e, fill, nonce=None, op=None, lp=None, raw=None):
    fp = os.path.join(e.tmp, "fill.json")
    if fill is not None or raw is not None:
        with open(fp, "w") as f:
            f.write(raw if raw is not None else json.dumps(fill))
    return e.run("verify_fill.py", "--nonce", nonce or "", "--order", op, "--fill", fp, "--limits", lp,
                 "--gate-dir", e.gate)


def halted(res, e, word=None):
    ex, out = res
    return ex == 2 and out.get("verdict") == "HALT" and os.path.exists(os.path.join(e.gate, "HALT")) and \
        (word is None or any(word in r for r in out.get("reasons", [])))


@test
def T9_control_matching_fill_is_a_match(e):
    n, op, lp = placed(e)
    ex, out = verify_fill(e, fill_of(ORDER), n, op, lp)
    return ex == 0 and out.get("verdict") == "MATCH" and not os.path.exists(os.path.join(e.gate, "HALT"))


@test
def T9_control_partial_fill_is_a_match(e):
    n, op, lp = placed(e)
    ex, out = verify_fill(e, fill_of(ORDER, filled_qty="20", status="partially_filled"), n, op, lp)
    return ex == 0 and out.get("verdict") == "MATCH" and out.get("partial") is True


@test
def T9_control_a_partial_fill_can_be_reverified_as_it_grows(e):
    n, op, lp = placed(e)
    a = verify_fill(e, fill_of(ORDER, filled_qty="20", status="partially_filled"), n, op, lp)
    b = verify_fill(e, fill_of(ORDER), n, op, lp)
    return a[0] == 0 and b[0] == 0 and b[1].get("verdict") == "MATCH" and b[1].get("partial") is False


@test
def T9_a_shrinking_fill_halts(e):
    n, op, lp = placed(e)
    a = verify_fill(e, fill_of(ORDER, filled_qty="30", status="partially_filled"), n, op, lp)
    return a[0] == 0 and halted(verify_fill(e, fill_of(ORDER, filled_qty="20", status="partially_filled"), n, op, lp), e)


@test
def T9_fill_qty_over_the_order_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, fill_of(ORDER, filled_qty="60"), n, op, lp), e, "qty")


@test
def T9_fill_of_another_symbol_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, fill_of(ORDER, symbol="TSLA"), n, op, lp), e, "symbol")


@test
def T9_fill_on_the_other_side_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, fill_of(ORDER, side="sell"), n, op, lp), e, "side")


@test
def T9_fill_through_the_limit_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, fill_of(ORDER, filled_avg_price="191.50"), n, op, lp), e, "price")


@test
def T9_fill_of_another_client_order_id_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, fill_of(ORDER, client_order_id="someone-else"), n, op, lp), e, "client_order_id")


@test
def T9_fill_of_another_asset_class_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, fill_of(ORDER, asset_class="us_option"), n, op, lp), e, "asset class")


@test
def T9_fill_without_a_previewed_nonce_halts(e):
    n, op, lp = placed(e, preview=False)
    return halted(verify_fill(e, fill_of(ORDER), n, op, lp), e, "preview")


@test
def T9_second_fill_for_one_nonce_halts(e):
    n, op, lp = placed(e)
    first = verify_fill(e, fill_of(ORDER), n, op, lp)
    return first[0] == 0 and halted(verify_fill(e, fill_of(ORDER), n, op, lp), e, "already")


@test
def T9_order_file_edited_after_the_check_halts(e):
    n, op, lp = placed(e)
    json.dump(dict(ORDER, qty=60), open(op, "w"))
    return halted(verify_fill(e, fill_of(dict(ORDER, qty=60)), n, op, lp), e, "order")


@test
def T9_missing_fill_file_halts(e):
    n, op, lp = placed(e)
    return halted(verify_fill(e, None, n, op, lp), e)


@test
def T9_gate_halt_blocks_new_entries_not_exits(e):
    n, op, lp = placed(e)
    verify_fill(e, fill_of(ORDER, filled_qty="60"), n, op, lp)
    entry = e.rc(order=dict(ORDER, client_order_id="next-1"))
    ex_ = e.rc(order=EXIT, pf=pf_with(positions=HELD_AAPL), contract=None)
    return failed(entry, "GATE_HALT") and passed(ex_)


@test
def T9_gate_halt_stops_the_mandate_exits_included(e):
    os.makedirs(e.gate, exist_ok=True)
    open(os.path.join(e.gate, "HALT"), "w").write("verify_fill: test break")
    led = [{"ts": NOW, "mandate_id": MANDATE["id"], "client_order_id": "m-aapl-0", "symbol": "AAPL", "side": "buy",
            "qty": 10, "price": 190, "notional": 1900, "is_exit": False}]
    o = dict(EXIT, client_order_id="m-aapl-x", strategy="ema9-pullback-v2")
    mx, out, risk = mandate_check(e, o, ledger=led, rc_kw={"pf": pf_with(positions=HELD_AAPL), "contract": None})
    return risk.get("verdict") == "pass" and out.get("verdict") == "HALT"


# ---------------------------------------------------------------- P13 the two limits copies
RES_LIMITS = os.path.join(REPO, "skills", "trading-research", "assets", "risk-limits.json")
EXEC_LIMITS = os.path.join(SKILL, "assets", "risk-limits.json")


@test
def P13_shipped_limits_copies_differ_only_where_intended(e):
    import limits_guard
    return os.path.exists(RES_LIMITS) and limits_guard.drift(jl(EXEC_LIMITS), jl(RES_LIMITS)) == []


@test
def P13_a_changed_hard_limit_in_one_copy_is_flagged(e):
    import limits_guard
    r = dict(jl(RES_LIMITS), max_loss_per_trade=10 ** 6)
    x = dict(jl(EXEC_LIMITS), allow_margin=True)
    return any("max_loss_per_trade" in d for d in limits_guard.drift(jl(EXEC_LIMITS), r)) and \
        any("allow_margin" in d for d in limits_guard.drift(x, jl(RES_LIMITS)))


# ---------------------------------------------------------------- invariant: every new code is HARD
ACK = "I override the risk gate for this order and accept the loss"
OVR = ("--override", "paper test of the phase 1 hard codes", "--override-ack", ACK)


def refused_override(res, code):
    ex, out = res
    ov = out.get("override") or {}
    return ex == 1 and code in codes(out) and ov.get("accepted") is False and \
        str(out.get("nonce", "")).startswith("RC2.FAIL.")


@test
def HARD_new_phase1_codes_cannot_be_overridden(e):
    os.makedirs(e.gate, exist_ok=True)
    cases = [
        ("ASSET_CLASS", dict(instrument={"asset_class": "etf"})),
        ("NO_CLOCK", dict(pf=pf_clock(as_of=None))),
        ("CLOCK_DRIFT", dict(now="2026-11-25T11:30:00-05:00", contract=quote_contract("AAPL", "2026-11-25T11:30:00-05:00"))),
        ("MARGIN_OFF", dict(pf=pf_with(settled_cash=1000))),
        ("NO_CASH", dict(pf=pf_with(settled_cash=None))),
        ("INSTRUMENT", dict(instrument={"session": "24x7"})),
        ("EXIT_UNVERIFIED", dict(order=EXIT, pf=pf_with(positions=HELD_AAPL, positions_source=None), contract=None)),
    ]
    ok = all(refused_override(e.rc(extra=OVR, **kw), code) for code, kw in cases)
    open(os.path.join(e.gate, "HALT"), "w").write("test")
    return ok and refused_override(e.rc(extra=OVR), "GATE_HALT")


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
