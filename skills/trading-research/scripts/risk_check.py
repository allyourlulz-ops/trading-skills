#!/usr/bin/env python3
"""Pre-trade gate 1 of 3. Returns PASS/BLOCK for one exact order and its fingerprint.
Usage: risk_check.py --order order.json [--state state.json] [--limits ../assets/risk-limits.json] [--now 2026-11-23T10:15]
order.json: {"symbol":"AAPL","side":"buy","qty":10,"type":"limit","limit_price":190.0,"stop_price":186.0,
             "target_price":198.0,"is_exit":false,"asset_class":"equity","uses_margin":false}
state.json: {"date":"2026-11-23","trades_today":1,"orders_today":2,"planned_loss_today_usd":40,
             "realized_pnl_today_usd":-20,"buying_power":4800,"paper":true}
Times are interpreted in the limits' timezone (default America/New_York)."""
import argparse, hashlib, json, os, sys
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:  # py<3.9
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))

def fingerprint(o):
    keys = ["symbol", "side", "qty", "type", "limit_price", "stop_price"]
    s = json.dumps({k: o.get(k) for k in keys}, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()[:16]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--state")
    ap.add_argument("--limits", default=os.path.join(HERE, "..", "assets", "risk-limits.json"))
    ap.add_argument("--now")
    a = ap.parse_args()
    L = json.load(open(a.limits)); o = json.load(open(a.order))
    st = json.load(open(a.state)) if a.state else {}
    tz = ZoneInfo(L.get("timezone", "America/New_York")) if ZoneInfo else None
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(tz)
    hhmm = now.strftime("%H:%M")
    blocks, warns = [], []
    sym = o["symbol"].upper()
    exit_ = bool(o.get("is_exit"))
    if sym in [b.upper() for b in L.get("blocked", [])]: blocks.append(f"{sym} is on the blocked list")
    ac = o.get("asset_class", "equity")
    if ac == "option" and not L.get("allow_options"): blocks.append("options disabled")
    if ac == "crypto" and not L.get("allow_crypto", False): blocks.append("crypto disabled")
    if o.get("uses_margin") and not L.get("allow_margin"): blocks.append("margin disabled")
    if o["side"] == "sell" and not exit_ and not L.get("allow_short"): blocks.append("short selling disabled")
    if st.get("paper") is False and L.get("paper", True): blocks.append("account is LIVE but limits require paper")
    if not exit_:
        px = o.get("limit_price") or o.get("est_price")
        if px is None: blocks.append("need limit_price or est_price to measure risk")
        else:
            notional = px * o["qty"]
            if notional > L["max_order_usd"]: blocks.append(f"notional ${notional:.2f} > max_order_usd {L['max_order_usd']}")
            if notional < L.get("min_order_usd", 0): blocks.append("below min_order_usd")
            if st.get("buying_power") is not None and notional > st["buying_power"]: blocks.append("exceeds buying power")
            cap = L["budget"] * (1 - L.get("cash_buffer_pct", 0) / 100) * L.get("max_position_pct", 100) / 100
            if notional > cap: blocks.append(f"notional ${notional:.2f} > max position ${cap:.2f}")
            stop = o.get("stop_price")
            if L.get("require_stop") and stop is None: blocks.append("stop required")
            if stop is not None:
                loss = (px - stop) * o["qty"]
                if loss <= 0: blocks.append("stop is not below entry")
                if loss > L["max_loss_per_trade_usd"]: blocks.append(f"max loss ${loss:.2f} > per-trade limit {L['max_loss_per_trade_usd']}")
                day = st.get("planned_loss_today_usd", 0) + max(loss, 0)
                if day > L["max_daily_loss_usd"]: blocks.append(f"daily max-loss budget ${day:.2f} > {L['max_daily_loss_usd']}")
                if o.get("target_price"):
                    rr = (o["target_price"] - px) / (px - stop) if px > stop else 0
                    if rr < L.get("min_reward_risk", 0): blocks.append(f"reward/risk {rr:.2f} < {L['min_reward_risk']}")
        if st.get("trades_today", 0) >= L["max_trades_per_day"]: blocks.append("max trades per day reached")
        if st.get("orders_today", 0) >= L.get("max_orders_per_day", 99): blocks.append("max orders per day reached")
        if hhmm < L.get("no_entries_before", "00:00"): blocks.append(f"no entries before {L['no_entries_before']}")
        if hhmm > L.get("no_entries_after", "23:59"): blocks.append(f"no entries after {L['no_entries_after']}")
    else:
        warns.append("exit order: daily limits do not block exits")
    res = {"verdict": "BLOCK" if blocks else "PASS", "fingerprint": fingerprint(o), "symbol": sym,
           "checked_at": now.isoformat(), "blocks": blocks, "warnings": warns,
           "next": "Ask the user for an explicit yes naming this ticker, side and quantity." if not blocks else "Do not place this order."}
    print(json.dumps(res, indent=2)); sys.exit(0 if not blocks else 2)

if __name__ == "__main__":
    main()
