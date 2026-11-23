#!/usr/bin/env python3
"""Standing trading mandate: lets a bot place orders without a per-order yes, inside limits the
user signed once. Stdlib only. Replaces gate 2 (the typed yes) for orders it approves; gate 1
(risk_check PASS) still applies to every order, and the mandate's own limits are tighter still.

Commands
  mandate.py check  --order order.json --risk risk_result.json [--mandate m.json] [--ledger l.jsonl] [--now ISO]
  mandate.py record --order order.json --ledger l.jsonl [--pnl -12.5] [--fill-price 190.1]
  mandate.py status [--mandate m.json] [--ledger l.jsonl]
  mandate.py halt   --reason "..."        (writes the HALT file next to the mandate; any run stops)

check verdicts
  AUTO_OK    place it now, no yes needed; then record it and notify the user (fill, P&L, reason)
  NEEDS_YES  outside the mandate: fall back to the explicit per-order yes, with the reasons
  HALT       mandate off (revoked, expired, HALT file, loss or loss-streak limit hit). Exits only,
             each with a per-order yes, until the user signs a new mandate.
Exits that reduce or close a position stay AUTO_OK when only a limit is spent (loss, streak, expiry
trips HALT for entries); once the mandate is revoked or the HALT file exists, exits need a per-order
yes too. Protective stops already resting at the broker stay in place either way.
"""
import argparse, json, os, sys
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_M = os.path.join(HERE, "..", "assets", "mandate.json")
LIVE_ACK = "I accept losses from orders I do not approve one by one"
MAX_DAYS = 30


def load_ledger(p):
    if not p or not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def today_rows(L, day):
    return [r for r in L if str(r.get("ts", ""))[:10] == day]


def halt_file(mpath):
    return os.path.join(os.path.dirname(os.path.abspath(mpath)), "HALT")


def check(a):
    M = json.load(open(a.mandate))
    o = json.load(open(a.order))
    rk = json.load(open(a.risk))
    now = datetime.fromisoformat(a.now) if a.now else datetime.now()
    day = now.date().isoformat()
    L = load_ledger(a.ledger)
    T = today_rows(L, day)
    halt, need = [], []

    if M.get("revoked"):
        halt.append("mandate revoked")
    if os.path.exists(halt_file(a.mandate)):
        halt.append("HALT file present: " + open(halt_file(a.mandate)).read().strip()[:200])
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

    pnl_today = sum(r.get("pnl", 0) for r in T)
    if pnl_today <= -abs(M.get("max_daily_loss_usd", 0)):
        halt.append("daily loss limit hit: %.2f" % pnl_today)
    pnl_total = sum(r.get("pnl", 0) for r in L if r.get("mandate_id") == M.get("id"))
    if M.get("max_total_loss_usd") and pnl_total <= -abs(M["max_total_loss_usd"]):
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
    if rk.get("verdict") != "PASS":
        need.append("risk_check verdict is %s, not PASS" % rk.get("verdict"))
    if rk.get("fingerprint") and "fingerprint" in rk:
        from risk_check import fingerprint  # same hash as gate 1
        if fingerprint(o) != rk["fingerprint"]:
            need.append("order differs from the one risk_check passed")
    if not is_exit:
        sym = str(o.get("symbol", "")).upper()
        if [s.upper() for s in M.get("symbols", [])] and sym not in [s.upper() for s in M["symbols"]]:
            need.append(sym + " not in the mandate's symbols")
        if o.get("strategy") not in M.get("strategies", []):
            need.append("strategy %r not in the mandate" % o.get("strategy"))
        if o.get("asset_class", "equity") not in M.get("asset_classes", ["equity"]):
            need.append("asset class %s not in the mandate" % o.get("asset_class", "equity"))
        if o.get("side") == "sell" and not M.get("allow_short", False):
            need.append("short entries are not in the mandate")
        px = o.get("limit_price") or o.get("price") or 0
        notional = float(px) * float(o.get("qty", 0))
        if not px:
            need.append("entry has no limit price; the mandate only covers limit orders")
        if notional > M.get("max_order_usd", 0):
            need.append("order $%.0f over the mandate's $%s per order" % (notional, M.get("max_order_usd")))
        spent = sum(r.get("notional", 0) for r in T if not r.get("is_exit"))
        if spent + notional > M.get("max_daily_notional_usd", 0):
            need.append("daily notional would be $%.0f, mandate allows $%s" % (spent + notional, M.get("max_daily_notional_usd")))
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
    verdict = "HALT" if halt and not (is_exit and not any(h.startswith(("mandate revoked", "HALT")) for h in halt)) else (
        "NEEDS_YES" if need else "AUTO_OK")
    if verdict == "HALT" and not M.get("revoked") and not os.path.exists(halt_file(a.mandate)):
        with open(halt_file(a.mandate), "w") as f:
            f.write("%s %s" % (now.isoformat(timespec="minutes"), "; ".join(halt)))
    out = dict(verdict=verdict, mandate_id=M.get("id"), mode=M.get("mode", "paper"), symbol=o.get("symbol"),
               reasons=halt + need, pnl_today=round(pnl_today, 2), pnl_mandate=round(pnl_total, 2),
               loss_streak=streak, notify=M.get("notify", "after_each_fill"))
    print(json.dumps(out, indent=2))
    sys.exit({"AUTO_OK": 0, "NEEDS_YES": 1, "HALT": 2}[verdict])


def record(a):
    o = json.load(open(a.order))
    M = json.load(open(a.mandate)) if os.path.exists(a.mandate) else {}
    px = a.fill_price or o.get("limit_price") or 0
    row = dict(ts=a.now or datetime.now().isoformat(timespec="seconds"), mandate_id=M.get("id"),
               symbol=o.get("symbol"), side=o.get("side"), qty=o.get("qty"), price=px,
               notional=round(float(px) * float(o.get("qty", 0)), 2), is_exit=bool(o.get("is_exit")),
               strategy=o.get("strategy"))
    if a.pnl is not None:
        row["pnl"] = a.pnl
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


def halt(a):
    with open(halt_file(a.mandate), "w") as f:
        f.write("%s %s" % (datetime.now().isoformat(timespec="minutes"), a.reason))
    print("HALT written; all mandate orders stop. Delete the HALT file and sign a new mandate to resume.")


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record", "status", "halt"):
        p = sp.add_parser(name)
        p.add_argument("--mandate", default=DEFAULT_M)
        p.add_argument("--ledger", default=os.path.join(HERE, "..", "assets", "mandate-ledger.jsonl"))
        p.add_argument("--now")
        if name in ("check", "record"):
            p.add_argument("--order", required=True)
        if name == "check":
            p.add_argument("--risk", required=True)
        if name == "record":
            p.add_argument("--pnl", type=float)
            p.add_argument("--fill-price", type=float)
        if name == "halt":
            p.add_argument("--reason", required=True)
    a = ap.parse_args()
    {"check": check, "record": record, "status": status, "halt": halt}[a.cmd](a)
