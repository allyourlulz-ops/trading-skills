#!/usr/bin/env python3
"""Post-fill re-check (T9): after the broker reports a fill, prove it is the order the gate checked.
Stdlib only, no network. trading-execution only. Run it on every fill, before mandate.py record.

Usage: verify_fill.py --nonce N | --risk risk_result.json  --order order.json --fill fill.json
                      --limits ../assets/risk-limits.json [--gate-dir D] [--mandate m.json]
                      [--market-tol-bps 100] [--clock-tol-s 120]
fill.json  the broker's own order object after the fill (Alpaca GET /v2/orders/{id} or
           /v2/orders:by_client_order_id), or a list of them / {"orders": [...]}: the one whose client_order_id
           is the order's is used. Fields read: client_order_id, symbol, side, filled_qty, filled_avg_price,
           status, type, limit_price, asset_class, filled_at.

MATCH (exit 0) only if all of these hold; anything else is HALT (exit 2), including bad or missing input:
  the nonce's MAC is valid for this gate key, it is in gate-log.jsonl, preview.py consumed it, and no fill was
  verified for it before; the order file still has the checked fingerprint (order + limits contents); the
  fill's client_order_id, symbol and side are the order's; 0 < filled_qty <= the checked qty; a limit buy
  filled at or under its limit (a sell at or over); a market order within --market-tol-bps of est_price;
  the fill's type and limit price, when reported, are the order's; its asset class maps to the one
  risk_check derived; it filled no earlier than the check (minus the clock tolerance).
NO_FILL (exit 0): the broker reports zero filled quantity; nothing to verify.
HALT writes <gate_dir>/HALT (risk_check then refuses every new entry: GATE_HALT) and, with --mandate, the
mandate's HALT file. Only the user deletes them, after looking at the break.
"""
import argparse, hmac, json, os, re, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gate import _key, _log, _mac, _append, file_sha256, fingerprint, gate_dir, parse  # noqa: E402

ALPACA_CLASS = {"us_equity": ("equity", "etf"), "crypto": ("crypto",), "us_option": ("option",)}


def _f(x):
    return None if x is None or x == "" else float(x)


def _ts(x):
    return datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", str(x).replace("Z", "+00:00"))).timestamp()


def pick(fill, coid):
    rows = fill.get("orders", fill) if isinstance(fill, dict) else fill
    rows = rows if isinstance(rows, list) else [rows]
    mine = [r for r in rows if isinstance(r, dict) and r.get("client_order_id") == coid]
    if len(mine) > 1:
        raise ValueError("%d broker orders carry client_order_id %s: a retry filled twice" % (len(mine), coid))
    if mine:
        return mine[0]
    if len(rows) == 1 and isinstance(rows[0], dict):
        return rows[0]  # reported as a client_order_id mismatch below
    raise ValueError("no broker order with client_order_id %s in the fill file" % coid)


def check(nonce, o, f, limits, d, a):
    why = []
    t = parse(nonce)
    if not t:
        return ["not a gate nonce"], {}
    if not hmac.compare_digest(_mac(_key(d), nonce.rsplit(".", 1)[0]), t["mac"]):
        return ["nonce signature invalid for this gate key"], {}
    log = _log(d)
    row = next((r for r in log if r.get("nonce") == nonce and r.get("event") == "issued"), None)
    if row is None:
        return ["nonce not in gate-log.jsonl"], {}
    used = [r for r in log if r.get("nonce") == nonce and r.get("event") == "used"]
    if not used:
        why.append("nonce was never consumed by preview.py: this order skipped the preview")
    if any(r.get("nonce") == nonce and r.get("event") in ("fill_verified", "fill_halt") for r in log):
        why.append("a fill was already verified for this nonce: one nonce, one order")
    if t["verdict"] == "FAIL":
        why.append("the nonce's verdict is FAIL: this order should never have been sent")
    if fingerprint(o, file_sha256(limits)) != t["fp"]:
        why.append("order file (or limits file) differs from the one risk_check checked")
    coid = o.get("client_order_id")
    if f.get("client_order_id") != coid:
        why.append("fill client_order_id %r is not the order's %r" % (f.get("client_order_id"), coid))
    if str(f.get("symbol", "")).upper().replace(" ", "") != str(o.get("symbol", "")).upper().replace(" ", ""):
        why.append("fill symbol %s is not the order's %s" % (f.get("symbol"), o.get("symbol")))
    if str(f.get("side", "")).lower() != str(o.get("side", "")).lower():
        why.append("fill side %s is not the order's %s" % (f.get("side"), o.get("side")))
    q, oq = _f(f.get("filled_qty")), float(o["qty"])
    px = _f(f.get("filled_avg_price"))
    info = {"filled_qty": q, "filled_avg_price": px, "partial": bool(q is not None and 0 < q < oq - 1e-12)}
    if q is None or q < 0:
        why.append("fill has no filled_qty")
    elif q > min(oq, float(row.get("qty") or oq)) + 1e-12:
        why.append("filled qty %g exceeds the checked qty %g" % (q, min(oq, float(row.get("qty") or oq))))
    if q and (px is None or px <= 0):
        why.append("fill has no filled_avg_price")
    typ = str(o.get("type", "limit")).lower()
    if f.get("type") and str(f["type"]).lower() != typ:
        why.append("fill order type %s is not the order's %s" % (f["type"], typ))
    if q and px:
        if typ == "market":
            ref = _f(o.get("est_price"))
            if not ref:
                why.append("market order has no est_price to check the fill price against")
            elif abs(px - ref) / ref * 1e4 > a.market_tol_bps:
                why.append("market fill price %g is %.0f bps from est_price %g (tolerance %g bps)"
                           % (px, abs(px - ref) / ref * 1e4, ref, a.market_tol_bps))
        else:
            lim = _f(o.get("limit_price"))
            if f.get("limit_price") not in (None, "") and lim is not None and abs(_f(f["limit_price"]) - lim) > 1e-9:
                why.append("broker limit price %s is not the order's %s" % (f["limit_price"], lim))
            if lim is None:
                why.append("limit order has no limit_price")
            elif (o["side"] == "buy" and px > lim + 1e-9) or (o["side"] == "sell" and px < lim - 1e-9):
                why.append("fill price %g went through the limit %g on a %s" % (px, lim, o["side"]))
    ac = row.get("asset_class")
    if f.get("asset_class"):
        ok = ALPACA_CLASS.get(str(f["asset_class"]).lower(), (str(f["asset_class"]).lower(),))
        if ac and ac not in ok:
            why.append("fill asset class %s does not match the checked %s" % (f["asset_class"], ac))
    if f.get("filled_at") and q:
        try:
            if _ts(f["filled_at"]) < float(row.get("wall", 0)) - a.clock_tol_s:
                why.append("fill time %s is before the risk check: not the checked order" % f["filled_at"])
        except ValueError:
            why.append("fill filled_at is not ISO 8601")
    return why, info


def halt_files(d, mandate, text):
    paths = [os.path.join(d, "HALT")]
    if mandate:
        paths.append(os.path.join(os.path.dirname(os.path.abspath(mandate)), "HALT"))
    for p in paths:
        with open(p, "w") as fh:
            fh.write(text)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nonce"); ap.add_argument("--risk"); ap.add_argument("--order", required=True)
    ap.add_argument("--fill", required=True); ap.add_argument("--limits", required=True)
    ap.add_argument("--gate-dir"); ap.add_argument("--mandate")
    ap.add_argument("--market-tol-bps", type=float, default=100.0)
    ap.add_argument("--clock-tol-s", type=float, default=120.0)
    a = ap.parse_args()
    try:
        d = gate_dir(a.gate_dir)
    except ValueError as e:
        print(json.dumps({"verdict": "HALT", "reasons": [str(e)], "halt_files": []}, indent=2)); sys.exit(2)
    nonce = (a.nonce or "").strip()
    info = {}
    try:
        if not nonce and a.risk:
            nonce = str(json.load(open(a.risk)).get("nonce") or "").strip()
        if not nonce:
            raise ValueError("no nonce: pass --nonce or --risk")
        o = json.load(open(a.order))
        f = pick(json.load(open(a.fill)), o.get("client_order_id"))
        if not _f(f.get("filled_qty")) and str(f.get("status", "")).lower() not in ("filled", "partially_filled"):
            print(json.dumps({"verdict": "NO_FILL", "nonce": nonce, "status": f.get("status"), "reasons": [],
                              "gate_dir": d}, indent=2)); return
        why, info = check(nonce, o, f, a.limits, d, a)
    except (OSError, ValueError, KeyError, TypeError) as e:
        why = ["bad input, treated as a break: %s" % e]
    if why:
        text = "%s verify_fill: %s" % (datetime.now().astimezone().isoformat(timespec="seconds"), "; ".join(why))
        paths = halt_files(d, a.mandate, text[:2000])
        _append(d, "gate-log.jsonl", dict(event="fill_halt", nonce=nonce, reasons=why, at=int(time.time())))
        print(json.dumps(dict({"verdict": "HALT", "nonce": nonce, "reasons": why, "halt_files": paths, "gate_dir": d,
                               "next": "Stop. Show the user every reason. Cancel open agent orders (not resting stops). "
                                       "Only the user deletes the HALT files."}, **info), indent=2))
        sys.exit(2)
    _append(d, "gate-log.jsonl", dict(event="fill_verified", nonce=nonce, at=int(time.time()), **info))
    print(json.dumps(dict({"verdict": "MATCH", "nonce": nonce, "reasons": [], "gate_dir": d,
                           "next": "Record the fill with mandate.py record --fill-price <filled_avg_price>."}, **info), indent=2))


if __name__ == "__main__":
    main()
