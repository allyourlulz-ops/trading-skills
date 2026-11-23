#!/usr/bin/env python3
"""Deterministic position sizing. The model never sizes; this does.
Usage: position_size.py --entry 100 --stop 97 [--target 106] [--quote 100.4] [--limits ../assets/risk-limits.json]
Prints JSON."""
import argparse, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float, required=True)
    ap.add_argument("--target", type=float)
    ap.add_argument("--quote", type=float, help="fresh quote <15 min old; risk uses max(entry, quote) for longs")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--limits", default=os.path.join(HERE, "..", "assets", "risk-limits.json"))
    a = ap.parse_args()
    L = json.load(open(a.limits))
    if a.side == "short" and not L.get("allow_short"):
        return out({"ok": False, "reason": "shorting disabled in limits"})
    eff = a.entry
    if a.quote:
        eff = max(a.entry, a.quote) if a.side == "long" else min(a.entry, a.quote)
    risk_ps = (eff - a.stop) if a.side == "long" else (a.stop - eff)
    if risk_ps <= 0:
        return out({"ok": False, "reason": "stop must be on the losing side of entry"})
    deployable = L["budget"] * (1 - L.get("cash_buffer_pct", 0) / 100)
    caps = {
        "by_max_loss": L["max_loss_per_trade_usd"] / risk_ps,
        "by_max_order": L["max_order_usd"] / eff,
        "by_max_position": deployable * L["max_position_pct"] / 100 / eff,
    }
    qty = math.floor(min(caps.values()))
    res = {"ok": qty > 0, "qty": qty, "effective_entry": eff, "risk_per_share": round(risk_ps, 4),
           "dollar_risk": round(qty * risk_ps, 2), "notional": round(qty * eff, 2),
           "binding_cap": min(caps, key=caps.get), "caps": {k: math.floor(v) for k, v in caps.items()}}
    if a.target:
        reward = (a.target - eff) if a.side == "long" else (eff - a.target)
        rr = reward / risk_ps
        res["reward_risk"] = round(rr, 2)
        res["breakeven_win_rate"] = round(1 / (1 + rr), 3) if rr > 0 else None
        if rr < L.get("min_reward_risk", 0):
            res["ok"] = False; res["reason"] = f"reward/risk {rr:.2f} below min {L['min_reward_risk']}"
    if qty * eff < L.get("min_order_usd", 0):
        res["ok"] = False; res.setdefault("reason", "order below minimum size")
    out(res)

def out(d):
    print(json.dumps(d, indent=2)); sys.exit(0 if d.get("ok") else 1)

if __name__ == "__main__":
    main()
