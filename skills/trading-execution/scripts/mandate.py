#!/usr/bin/env python3
"""Standing trading mandate: lets a bot place orders without a per-order yes, inside limits the
user signed once. Stdlib only. Replaces gate 2 (the typed yes) for orders it approves; gate 1
(risk_check PASS) still applies to every order, and the mandate's own limits are tighter still.

Commands
  mandate.py sign   --mandate m.json --ack "I sign this mandate and accept losses inside its limits" [--gate-dir D]
             [--limits L]   The user runs this once: validates every field against the risk limits and adds an
             HMAC signature (gate key). check HALTs on any later edit and says NEEDS_YES while unsigned (T8).
  mandate.py check  --order order.json --risk risk_result.json [--token T] [--mandate m.json] [--ledger l.jsonl]
                    [--gate-dir D] [--limits L] [--now ISO]
             The gate token (risk_result.json's nonce, or --token) must verify for this order and the
             mandate's mode; OVERRIDE tokens never pass here. AUTO_OK still goes through preview.py.
             Every field is re-validated on every call (T8); the window and the day run on the time
             risk_check recorded for the nonce in the gate log (--now must agree within the clock
             tolerance); asset class and notional (with multiplier and fx) come from the gate log too.
  mandate.py record --order order.json --ledger l.jsonl [--pnl -12.5] [--fill-price 190.1]
  mandate.py status [--mandate m.json] [--ledger l.jsonl]
  mandate.py halt   --reason "..."        (writes the HALT file next to the mandate; any run stops)
  mandate.py reconcile --broker fills.json --account account.json [--ledger l.jsonl] [--tol 0.01] [--gate-dir D]
             fills.json: the broker's own orders/fills for the period (e.g. Alpaca get_orders), list of
             {"client_order_id","symbol","side","filled_qty","filled_avg_price"}. Any break HALTs.
             Writes <ledger>.reconcile.json, signed with the gate key (T5). check refuses every ENTRY
             (NEEDS_YES) until a MATCHED reconcile of the current ledger, no older than
             reconcile_max_age_min (default 60), with the account's equity exists; risk_check's equity for
             the order must be within equity_tol_pct (default 2) of it, or the mandate HALTs.

A mandate for a strategy whose pipeline.py verdict was PAPER_PROBE sets "probe": true: it must be
paper, and each order is capped at probe_size_multiplier (default 0.25) of max_order.

Every order needs a client_order_id (derive it from the business action, e.g. strategy+symbol+signal
bar). Send the same id to the broker so a retry can never fill twice. The ledger is append-only: fix a
wrong row by recording a new row with "reverses": <client_order_id>, never by editing the file.

check verdicts
  AUTO_OK    place it now, no yes needed; then record it and notify the user (fill, P&L, reason)
  NEEDS_YES  outside the mandate: fall back to the explicit per-order yes, with the reasons
  HALT       mandate off (revoked, expired, HALT file, loss or loss-streak limit hit). Exits only,
             each with a per-order yes, until the user signs a new mandate.
Exits that reduce or close a position stay AUTO_OK when only a limit is spent (loss, streak, expiry
trips HALT for entries); once the mandate is revoked or the HALT file exists, exits need a per-order
yes too. Protective stops already resting at the broker stay in place either way.
"""
import argparse, hashlib, json, math, os, re, sys, time
from datetime import datetime, date
try:
    from zoneinfo import ZoneInfo
except ImportError:  # py<3.9
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_M = os.path.join(HERE, "..", "assets", "mandate.json")
LIVE_ACK = "I accept losses from orders I do not approve one by one"
MANDATE_ACK = "I sign this mandate and accept losses inside its limits"
MAX_DAYS = 30
ASSET_CLASSES = {"equity", "etf", "crypto", "option"}
MANDATE_KEYS = {
    "id", "granted_on", "expires_on", "mode", "live_ack", "strategies", "pipeline_verdict", "probe",
    "probe_size_multiplier", "symbols", "asset_classes", "allow_short", "require_stop", "base_currency", "max_order",
    "max_daily_notional", "max_orders_per_day", "max_open_positions", "max_daily_loss", "max_total_loss",
    "max_consecutive_losses", "notify", "revoked", "require_broker_mode_match", "reconcile_max_age_min",
    "equity_tol_pct", "timezone", "signed_at", "signature",
    "max_order_usd", "max_daily_notional_usd", "max_daily_loss_usd", "max_total_loss_usd"}  # *_usd: v1 mandates



def lim(M, key):
    """Mandate cap in base_currency. Old *_usd keys still read (v1 mandates)."""
    v = M.get(key)
    if v is None:
        v = M.get(key + "_usd")
    return v or 0

def _parse_ts(ts):
    return datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(ts).replace("Z", "+00:00")))


def _tz(M, Lm):
    name = M.get("timezone") or (Lm or {}).get("timezone") or "America/New_York"
    if ZoneInfo is None:
        raise ValueError("zoneinfo unavailable: the mandate window needs a timezone")
    return ZoneInfo(name)


def validate_mandate(M, Lm):
    """T8: every field, every call. Unknown or malformed fields, caps looser than the risk limits, and scope the
    limits do not allow make the mandate invalid (HALT). Lm is the risk-limits dict."""
    bad = []
    unk = sorted(k for k in M if k not in MANDATE_KEYS and not str(k).startswith("_"))
    if unk:
        bad.append("unknown field(s): " + ", ".join(unk))
    if not isinstance(M.get("id"), str) or not M.get("id"):
        bad.append("id must be a non-empty string")
    if M.get("mode", "paper") not in ("paper", "live"):
        bad.append("mode must be paper or live")
    st = M.get("strategies")
    if not isinstance(st, list) or not st or not all(isinstance(x, str) and x for x in st):
        bad.append("strategies must be a non-empty list of names")
    sy = M.get("symbols", [])
    if not isinstance(sy, list) or not all(isinstance(x, str) and x for x in sy):
        bad.append("symbols must be a list of tickers")
    ac = M.get("asset_classes", ["equity"])
    if not isinstance(ac, list) or not ac or not set(ac) <= ASSET_CLASSES:
        bad.append("asset_classes must be a non-empty subset of " + ", ".join(sorted(ASSET_CLASSES)))
        ac = []
    pv = M.get("pipeline_verdict")
    if pv not in ("READY_FOR_PAPER", "PAPER_PROBE"):
        bad.append("pipeline_verdict must be READY_FOR_PAPER or PAPER_PROBE (got %r)" % (pv,))
    if pv == "PAPER_PROBE" and M.get("probe") is not True:
        bad.append("pipeline_verdict PAPER_PROBE needs probe: true (paper only, reduced size)")
    for k in ("probe", "allow_short", "require_stop", "revoked", "require_broker_mode_match"):
        if k in M and not isinstance(M[k], bool):
            bad.append("%s must be true or false" % k)

    def num(k, lo, hi, required=False, integer=False, legacy=False):
        v = M.get(k)
        if v is None and legacy:
            v = M.get(k + "_usd")
        if v is None:
            if required:
                bad.append("%s is required" % k)
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) \
                or (integer and float(v) != int(v)) or not lo < float(v) <= hi:
            bad.append("%s must be %s in (%g, %g]" % (k, "an integer" if integer else "a number", lo, hi))
            return None
        return float(v)
    mo = num("max_order", 0, 1e12, True, legacy=True)
    num("max_daily_notional", 0, 1e12, True, legacy=True)
    mopd = num("max_orders_per_day", 0, 1000, True, integer=True)
    mdl = num("max_daily_loss", 0, 1e12, True, legacy=True)
    num("max_total_loss", 0, 1e12, legacy=True)
    num("max_consecutive_losses", 0, 1000, integer=True)
    num("max_open_positions", -1, 1000, integer=True)
    num("probe_size_multiplier", 0, 1)
    num("reconcile_max_age_min", 0, 1440)
    num("equity_tol_pct", 0, 10)
    if Lm is None:
        bad.append("risk limits unreadable: the mandate cannot be checked against them")
        return ["mandate invalid: " + b for b in bad]
    for k, v in (("max_order", mo), ("max_daily_loss", mdl)):
        lv = Lm.get(k, Lm.get(k + "_usd"))
        if v is not None and lv is not None and v > float(lv):
            bad.append("%s %g exceeds the risk limits' %s %g: a mandate is tighter, never looser" % (k, v, k, float(lv)))
    if mopd is not None and Lm.get("max_orders_per_day") is not None and mopd > float(Lm["max_orders_per_day"]):
        bad.append("max_orders_per_day exceeds the risk limits'")
    if M.get("allow_short") and not Lm.get("allow_short"):
        bad.append("allow_short is on but the risk limits have allow_short false")
    for c, flag in (("option", "allow_options"), ("crypto", "allow_crypto")):
        if c in ac and not Lm.get(flag):
            bad.append("asset class %s is listed but the risk limits have %s false" % (c, flag))
    if M.get("mode", "paper") == "live" and Lm.get("paper", True):
        bad.append("mode live but the risk limits require paper")
    if M.get("base_currency") and Lm.get("base_currency") and str(M["base_currency"]).upper() != str(Lm["base_currency"]).upper():
        bad.append("base_currency differs from the risk limits'")
    return ["mandate invalid: " + b for b in bad]


def load_ledger(p):
    if not p or not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def file_sha256(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if p and os.path.exists(p) else hashlib.sha256(b"").hexdigest()


def stamp_path(ledger):
    return os.path.abspath(ledger) + ".reconcile.json"


def account_equity(A):
    """Broker account equity: Alpaca GET /v2/account {"equity"}, IBKR summary {"netliquidation": {"amount"}},
    or a plain {"equity": n}."""
    if isinstance(A, dict):
        if isinstance(A.get("netliquidation"), dict):
            return float(A["netliquidation"]["amount"])
        if A.get("equity") is not None:
            return float(A["equity"])
    raise ValueError("account file has no equity (Alpaca equity or IBKR netliquidation.amount)")


def reconcile_gate(a, M, rk_row, halt, need):
    """T5: an entry needs a MATCHED reconcile, signed with the gate key, of this exact ledger, recent, with the
    broker's equity; the equity risk_check sized from must match it."""
    from gate import check_obj
    p = stamp_path(a.ledger)
    if not os.path.exists(p):
        need.append("no reconcile on record: run mandate.py reconcile --broker fills.json --account account.json "
                    "before any entry")
        return
    try:
        S = json.load(open(p))
    except ValueError:
        halt.append("reconcile stamp unreadable: %s" % p)
        return
    if not check_obj(S, "mac", getattr(a, "gate_dir", None), "RS1"):
        halt.append("reconcile stamp signature invalid: it was edited or made with another gate key")
        return
    if S.get("verdict") != "MATCHED":
        halt.append("last reconcile found breaks: fix them and reconcile again")
        return
    if S.get("ledger_sha256") != file_sha256(a.ledger):
        need.append("ledger changed since the last reconcile: reconcile again before the next entry")
    age_min = (time.time() - float(S.get("at_wall", 0))) / 60
    max_age = float(M.get("reconcile_max_age_min", 60))
    if age_min > max_age:
        need.append("last reconcile is %.0f min old (mandate allows %g): reconcile again" % (age_min, max_age))
    be = S.get("equity")
    if be is None:
        need.append("equity not reconciled: run reconcile with --account (the broker account read)")
        return
    pe = (rk_row or {}).get("equity")
    if pe is None:
        need.append("the gate log has no equity for this nonce: run risk_check again")
        return
    tol = float(M.get("equity_tol_pct", 2.0))
    if abs(float(pe) - float(be)) > abs(float(be)) * tol / 100:
        halt.append("unreconciled equity: risk_check sized from %.2f but the broker reported %.2f at reconcile "
                    "(tolerance %g%%)" % (float(pe), float(be), tol))


def ledger_position(L, mandate_id, sym):
    """Net quantity of sym this mandate opened and has not closed, from the ledger (reversed rows excluded)."""
    rev = {r["reverses"] for r in L if r.get("reverses")}
    net = 0.0
    for r in L:
        if r.get("mandate_id") != mandate_id or r.get("reverses") or r.get("client_order_id") in rev:
            continue
        if str(r.get("symbol", "")).upper() == sym:
            net += (-1 if r.get("is_exit") else 1) * float(r.get("qty") or 0)
    return net


def today_rows(L, day):
    return [r for r in L if str(r.get("ts", ""))[:10] == day]


def halt_file(mpath):
    return os.path.join(os.path.dirname(os.path.abspath(mpath)), "HALT")


def check(a):
    from gate import GateDirError, resolve_gate_dir
    try:
        a.gate_dir = resolve_gate_dir(getattr(a, "gate_dir", None))  # T7
    except GateDirError as e:
        print(json.dumps(dict(verdict="NEEDS_YES", reasons=["gate: " + str(e)]), indent=2)); sys.exit(1)
    from gate import check_obj, issued_row, verify
    M = json.load(open(a.mandate))
    o = json.load(open(a.order))
    rk = json.load(open(a.risk))
    halt, need, stop_all = [], [], []  # stop_all: halts that stop exits too (revoked, HALT file, invalid, tampered)
    try:
        Lm = json.load(open(a.limits))
    except (OSError, ValueError, TypeError):
        Lm = None
    stop_all += validate_mandate(M, Lm)
    if not M.get("signature"):
        need.append("mandate is not signed: the user runs mandate.py sign --mandate <file> --ack \"%s\"" % MANDATE_ACK)
    elif not check_obj(M, "signature", a.gate_dir, "MS1"):
        stop_all.append("mandate signature invalid: the file was edited after signing, or signed with another gate key")
    tok = getattr(a, "token", None) or rk.get("nonce")
    row = issued_row(tok, a.gate_dir) if tok else None
    tz = _tz(M, Lm)
    tol = float(((Lm or {}).get("gate") or {}).get("clock_tolerance_s", 120))
    if row and row.get("checked_at"):
        # T8: the mandate's window and day run on the gate's clock (risk_check's broker-anchored time)
        now = _parse_ts(row["checked_at"]).astimezone(tz)
        if a.now:
            n2 = _parse_ts(a.now)
            n2 = n2 if n2.tzinfo else n2.replace(tzinfo=tz)  # a naive --now is read in the mandate's timezone
            if abs((n2 - now).total_seconds()) > tol:
                need.append("--now is %+.0fs from the risk_check clock for this nonce (tolerance %.0fs)"
                            % ((n2 - now).total_seconds(), tol))
    else:
        now = _parse_ts(a.now) if a.now else datetime.now(tz)
        now = (now if now.tzinfo else now.replace(tzinfo=tz)).astimezone(tz)
        if tok:
            need.append("no gate-log record of this nonce's check time: the window cannot be checked on the gate clock")
    day = now.date().isoformat()
    L = load_ledger(a.ledger)
    T = today_rows(L, day)

    if M.get("revoked"):
        stop_all.append("mandate revoked")
    if os.path.exists(halt_file(a.mandate)):
        stop_all.append("HALT file present: " + open(halt_file(a.mandate)).read().strip()[:200])
    try:
        g, e = date.fromisoformat(M["granted_on"]), date.fromisoformat(M["expires_on"])
        if (e - g).days > MAX_DAYS:
            halt.append("mandate longer than %d days; sign a shorter one" % MAX_DAYS)
        if now.date() > e:
            halt.append("mandate expired on " + M["expires_on"])
        if now.date() < g:
            halt.append("mandate not yet in force")
    except (KeyError, ValueError):
        halt.append("mandate needs granted_on and expires_on (YYYY-MM-DD)")
    if M.get("mode", "paper") == "live" and M.get("live_ack") != LIVE_ACK:
        halt.append('live mode needs live_ack set to exactly: "%s"' % LIVE_ACK)
    if M.get("mode", "paper") == "live" and o.get("paper", True) and M.get("require_broker_mode_match", True):
        need.append("mandate is live but the order is marked paper; confirm the account")
    if M.get("mode", "paper") == "paper" and o.get("paper") is False:
        halt.append("paper mandate cannot place a live order")
    if M.get("probe") and M.get("mode", "paper") != "paper":
        halt.append("probe mandates (pipeline.py PAPER_PROBE) are paper only")

    pnl_today = sum(r.get("pnl", 0) for r in T)
    if pnl_today <= -abs(lim(M, "max_daily_loss")):
        halt.append("daily loss limit hit: %.2f" % pnl_today)
    pnl_total = sum(r.get("pnl", 0) for r in L if r.get("mandate_id") == M.get("id"))
    if lim(M, "max_total_loss") and pnl_total <= -abs(lim(M, "max_total_loss")):
        halt.append("mandate loss limit hit: %.2f" % pnl_total)
    streak = 0
    for r in reversed([r for r in L if "pnl" in r]):
        if r["pnl"] < 0:
            streak += 1
        else:
            break
    if M.get("max_consecutive_losses") and streak >= M["max_consecutive_losses"]:
        halt.append("%d losses in a row" % streak)

    is_exit = bool(o.get("is_exit"))
    coid = o.get("client_order_id")
    if not coid:
        need.append("order has no client_order_id (needed so retries cannot fill twice)")
    elif any(r.get("client_order_id") == coid and not r.get("reverses") for r in L):
        need.append("client_order_id %s already in the ledger: this is a retry or a duplicate" % coid)
    if rk.get("verdict") != "pass" or (rk.get("override") or {}).get("accepted"):
        need.append("risk_check verdict is %s, not a plain pass" % rk.get("verdict"))
    if not tok:
        need.append("no nonce from risk_check: the hard stop needs it echoed")
    else:
        # check only; preview.py consumes the token
        ok, why, _t = verify(tok, o, M.get("mode", "paper"), getattr(a, "limits", None), a.gate_dir,
                             False, a.now, consume=False)
        need += ["gate: " + w for w in why]
        if not is_exit:
            reconcile_gate(a, M, row, halt, need)
    # T8: asset class and notional as risk_check derived them (gate log), never the order's own label
    ac = (row or {}).get("asset_class")
    if ac is None:
        need.append("the gate log has no asset class for this nonce: run risk_check again")
    # scope applies to exits too (T3: the old is_exit skip let any held symbol auto-trade)
    sym = str(o.get("symbol", "")).upper()
    if [s_.upper() for s_ in M.get("symbols", [])] and sym not in [s_.upper() for s_ in M["symbols"]]:
        need.append(sym + " not in the mandate's symbols")
    if o.get("strategy") not in M.get("strategies", []):
        need.append("strategy %r not in the mandate" % o.get("strategy"))
    if ac is not None and ac not in M.get("asset_classes", ["equity"]):
        need.append("asset class %s not in the mandate" % ac)
    if is_exit:
        held = ledger_position(L, M.get("id"), sym)
        if held + 1e-9 < float(o.get("qty", 0) or 0):
            need.append("no open %s position of %s recorded under this mandate (ledger holds %g): an exit "
                        "outside what the mandate opened needs a per-order yes" % (sym, o.get("qty"), held))
    if not is_exit:
        if o.get("side") == "sell" and not M.get("allow_short", False):
            need.append("short entries are not in the mandate")
        px = o.get("limit_price") or o.get("price") or 0
        notional = (row or {}).get("notional")  # qty x price x multiplier x fx, base currency (risk_check)
        if notional is None:
            need.append("the gate log has no notional for this nonce: run risk_check again")
            notional = float(px or 0) * float(o.get("qty", 0))
        notional = float(notional)
        if not px:
            need.append("entry has no limit price; the mandate only covers limit orders")
        cap = lim(M, "max_order") * (float(M.get("probe_size_multiplier", 0.25)) if M.get("probe") else 1)
        if notional > cap:
            need.append("order $%.0f over the mandate's $%.0f per order%s" % (notional, cap, " (probe: quarter size)" if M.get("probe") else ""))
        spent = sum(r.get("notional", 0) for r in T if not r.get("is_exit"))
        if spent + notional > lim(M, "max_daily_notional"):
            need.append("daily notional would be $%.0f, mandate allows $%s" % (spent + notional, lim(M, "max_daily_notional")))
        if len([r for r in T if not r.get("is_exit")]) >= M.get("max_orders_per_day", 0):
            need.append("mandate's orders per day used up")
        if M.get("require_stop", True) and not o.get("stop_price"):
            need.append("no stop attached")
        if M.get("max_open_positions") is not None:
            opened = {}
            for r in L:
                if r.get("mandate_id") == M.get("id"):
                    opened[r["symbol"]] = opened.get(r["symbol"], 0) + (-1 if r.get("is_exit") else 1)
            if sum(1 for v in opened.values() if v > 0) >= M["max_open_positions"] and opened.get(sym, 0) <= 0:
                need.append("max open positions reached")
    verdict = "HALT" if stop_all or (halt and not is_exit) else ("NEEDS_YES" if need else "AUTO_OK")
    halt = stop_all + halt
    if verdict == "HALT" and not M.get("revoked") and not os.path.exists(halt_file(a.mandate)):
        with open(halt_file(a.mandate), "w") as f:
            f.write("%s %s" % (now.isoformat(timespec="minutes"), "; ".join(halt)))
    out = dict(verdict=verdict, mandate_id=M.get("id"), mode=M.get("mode", "paper"), symbol=o.get("symbol"),
               reasons=halt + need, pnl_today=round(pnl_today, 2), pnl_mandate=round(pnl_total, 2),
               loss_streak=streak, notify=M.get("notify", "after_each_fill"))
    print(json.dumps(out, indent=2))
    sys.exit({"AUTO_OK": 0, "NEEDS_YES": 1, "HALT": 2}[verdict])


def sign(a):
    """The user signs the mandate once, with the exact sentence; the signature is an HMAC with the gate key
    over every field, so any later edit makes check HALT (T8)."""
    from gate import gate_dir, sign_obj
    gd = gate_dir(getattr(a, "gate_dir", None))
    if a.ack != MANDATE_ACK:
        print(json.dumps(dict(signed=False, error='--ack must be exactly: "%s" (typed by the user)' % MANDATE_ACK)))
        sys.exit(2)
    M = json.load(open(a.mandate))
    try:
        Lm = json.load(open(a.limits))
    except (OSError, ValueError):
        Lm = None
    bad = validate_mandate(M, Lm)
    if bad:
        print(json.dumps(dict(signed=False, reasons=bad), indent=2)); sys.exit(2)
    M.pop("signature", None)
    M["signed_at"] = datetime.now(_tz(M, Lm)).isoformat(timespec="seconds")
    M["signature"] = sign_obj(M, gd, "MS1")
    with open(a.mandate, "w") as f:
        json.dump(M, f, indent=2); f.write("\n")
    with open(os.path.join(gd, "mandates.jsonl"), "a") as f:
        f.write(json.dumps(dict(event="signed", id=M.get("id"), at=M["signed_at"], sha256=file_sha256(a.mandate))) + "\n")
    print(json.dumps(dict(signed=True, mandate_id=M.get("id"), signed_at=M["signed_at"], gate_dir=gd), indent=2))


def record(a):
    o = json.load(open(a.order))
    M = json.load(open(a.mandate)) if os.path.exists(a.mandate) else {}
    px = a.fill_price or o.get("limit_price") or 0
    row = dict(ts=a.now or datetime.now(_tz(M, None)).isoformat(timespec="seconds"), mandate_id=M.get("id"),
               client_order_id=o.get("client_order_id"),
               symbol=o.get("symbol"), side=o.get("side"), qty=o.get("qty"), price=px,
               notional=round(float(px) * float(o.get("qty", 0)), 2), is_exit=bool(o.get("is_exit")),
               strategy=o.get("strategy"))
    if a.pnl is not None:
        row["pnl"] = a.pnl
    if a.reverses:
        row["reverses"] = a.reverses
        row["notional"] = -row["notional"]
    with open(a.ledger, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row))


def status(a):
    M = json.load(open(a.mandate))
    L = load_ledger(a.ledger)
    day = (datetime.fromisoformat(a.now) if a.now else datetime.now()).date().isoformat()
    T = today_rows(L, day)
    print(json.dumps(dict(mandate_id=M.get("id"), mode=M.get("mode", "paper"), expires_on=M.get("expires_on"),
                          revoked=bool(M.get("revoked")), halted=os.path.exists(halt_file(a.mandate)),
                          orders_today=len(T), pnl_today=round(sum(r.get("pnl", 0) for r in T), 2),
                          pnl_mandate=round(sum(r.get("pnl", 0) for r in L if r.get("mandate_id") == M.get("id")), 2)),
                     indent=2))


def reconcile(a):
    from gate import resolve_gate_dir
    a.gate_dir = resolve_gate_dir(getattr(a, "gate_dir", None))  # T7: refuses inside the project
    L = load_ledger(a.ledger)
    B = json.load(open(a.broker))
    B = B.get("orders", B) if isinstance(B, dict) else B
    rev = {r["reverses"] for r in L if r.get("reverses")}
    mine = {r["client_order_id"]: r for r in L if r.get("client_order_id") and not r.get("reverses")
            and r["client_order_id"] not in rev}
    theirs = {b.get("client_order_id"): b for b in B if float(b.get("filled_qty") or 0) > 0}
    breaks = []
    for k, b in theirs.items():
        if k not in mine:
            breaks.append(dict(type="fill_not_in_ledger", client_order_id=k, symbol=b.get("symbol"),
                               why="an order filled that the mandate never recorded (manual trade, retry, or a bug)"))
            continue
        r = mine[k]
        if abs(float(b["filled_qty"]) - float(r["qty"])) > 1e-9:
            breaks.append(dict(type="qty_mismatch", client_order_id=k, ledger=r["qty"], broker=b["filled_qty"]))
        bp = float(b.get("filled_avg_price") or 0)
        if bp and r.get("price") and abs(bp - float(r["price"])) / bp > a.tol:
            breaks.append(dict(type="price_mismatch", client_order_id=k, ledger=r["price"], broker=bp))
    for k, r in mine.items():
        if k not in theirs:
            breaks.append(dict(type="ledger_not_filled", client_order_id=k, symbol=r["symbol"],
                               why="recorded but the broker shows no fill; record a reversing row if it never filled"))
    if breaks:
        with open(halt_file(a.mandate), "w") as f:
            f.write("%s reconcile: %d breaks" % (datetime.now().isoformat(timespec="minutes"), len(breaks)))
    equity = None
    if getattr(a, "account", None):
        equity = account_equity(json.load(open(a.account)))
    from gate import gate_dir, sign_obj
    S = dict(v=1, verdict="BREAKS" if breaks else "MATCHED", at_wall=round(time.time(), 3),
             at=datetime.now().astimezone().isoformat(timespec="seconds"), ledger_sha256=file_sha256(a.ledger),
             broker_sha256=file_sha256(a.broker), account_sha256=file_sha256(a.account) if getattr(a, "account", None) else None,
             equity=equity, breaks=len(breaks))
    S["mac"] = sign_obj(S, getattr(a, "gate_dir", None), "RS1")
    with open(stamp_path(a.ledger), "w") as f:
        json.dump(S, f, indent=1)
    print(json.dumps(dict(verdict="BREAKS" if breaks else "MATCHED", matched=len(set(mine) & set(theirs)),
                          breaks=breaks, equity=equity, stamp=stamp_path(a.ledger),
                          gate_dir=gate_dir(getattr(a, "gate_dir", None))), indent=2))
    sys.exit(2 if breaks else 0)


def halt(a):
    with open(halt_file(a.mandate), "w") as f:
        f.write("%s %s" % (datetime.now().isoformat(timespec="minutes"), a.reason))
    print("HALT written; all mandate orders stop. Delete the HALT file and sign a new mandate to resume.")


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record", "status", "halt", "reconcile", "sign"):
        p = sp.add_parser(name)
        p.add_argument("--mandate", default=DEFAULT_M)
        p.add_argument("--ledger", default=os.path.join(HERE, "..", "assets", "mandate-ledger.jsonl"))
        p.add_argument("--now")
        if name in ("check", "record"):
            p.add_argument("--order", required=True)
        if name == "check":
            p.add_argument("--risk", required=True)
            p.add_argument("--token", help="nonce from risk_check (default: read from --risk)")
            p.add_argument("--gate-dir"); p.add_argument("--limits", default=os.path.join(HERE, "..", "assets", "risk-limits.json"))
        if name == "record":
            p.add_argument("--pnl", type=float)
            p.add_argument("--fill-price", type=float)
            p.add_argument("--reverses", help="client_order_id of the row this one cancels out")
        if name == "reconcile":
            p.add_argument("--broker", required=True)
            p.add_argument("--account", help="broker account read (Alpaca GET /v2/account or IBKR summary): its "
                                             "equity is stamped and every entry's risk_check equity must match it")
            p.add_argument("--gate-dir")
            p.add_argument("--tol", type=float, default=0.01, help="price tolerance as a fraction")
        if name == "halt":
            p.add_argument("--reason", required=True)
        if name == "sign":
            p.add_argument("--ack", required=True, help="the exact sentence, typed by the user: " + MANDATE_ACK)
            p.add_argument("--gate-dir"); p.add_argument("--limits", default=os.path.join(HERE, "..", "assets", "risk-limits.json"))
    a = ap.parse_args()
    {"check": check, "record": record, "status": status, "halt": halt, "reconcile": reconcile, "sign": sign}[a.cmd](a)
