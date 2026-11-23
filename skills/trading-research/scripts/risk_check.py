#!/usr/bin/env python3
"""Pre-trade gate 1 of 3. Returns PASS/BLOCK for one exact order and its fingerprint.
Usage: risk_check.py --order order.json [--state state.json] [--limits ../assets/risk-limits.json] [--now 2026-11-23T10:15]
order.json: {"symbol":"AAPL","side":"buy","qty":10,"type":"limit","limit_price":190.0,"stop_price":186.0,
             "target_price":198.0,"is_exit":false,"asset_class":"equity","uses_margin":false}
state.json: {"date":"2026-11-23","trades_today":1,"orders_today":2,"planned_loss_today_usd":40,
             "realized_pnl_today_usd":-20,"buying_power":4800,"paper":true}
context.json (optional, from the data MCP server; enables the event-timing gates, entries only):
            {"as_of":"2026-11-23","next_earnings_date":"2026-12-02","last_earnings_date":"2026-10-30",
             "return_since_last_earnings_pct":4.1,"rsi14":66,"pct_below_52w_high":3.0,"vix":18.5,
             "safe_haven_5d_pct":{"GLD":0.4,"TLT":-0.2,"UUP":0.1}}
Times are interpreted in the limits' timezone (default America/New_York).
A size_multiplier below 1 means: re-run position_size.py and cut qty by that factor, then check again."""
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

def _days(a, b):
    from datetime import date
    return (date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days


def timing_gates(L, o, c, now, blocks, warns):
    """Event-timing gates for new entries. Returns a size multiplier (<=1, never raises size)."""
    G = L.get("timing", {})
    mult, floor = 1.0, G.get("min_size_multiplier", 0.25)
    ac = o.get("asset_class", "equity")
    if c is None:
        if ac == "equity":
            warns.append("no --context: earnings and market-regime gates skipped; fetch them via the data MCP server")
        return mult
    today = now.date().isoformat()
    if c.get("as_of") and _days(today, c["as_of"]) > 1:
        warns.append(f"context is stale (as_of {c['as_of']}); refresh before trading")
    if ac == "equity":
        ne = c.get("next_earnings_date")
        if ne is None:
            warns.append("next earnings date unknown; treat as inside the blackout until checked")
        else:
            d = _days(ne, today)
            if 0 <= d <= G.get("earnings_blackout_days", 14):
                msg = f"earnings in {d} days ({ne}): no new entries inside {G.get('earnings_blackout_days', 14)} days"
                (blocks if G.get("earnings_blackout_action", "block") == "block" else warns).append(msg)
        le, r = c.get("last_earnings_date"), c.get("return_since_last_earnings_pct")
        if le and r is not None and 0 <= _days(today, le) <= G.get("post_earnings_window_days", 7) \
                and r > G.get("post_earnings_spike_pct", 15):
            warns.append(f"up {r}% since earnings on {le}: gains may already be priced in")
            mult *= G.get("spike_multiplier", 0.7)
    rsi, hi = c.get("rsi14"), c.get("pct_below_52w_high")
    if rsi is not None and hi is not None and o["side"] == "buy" and rsi > G.get("overbought_rsi", 70) \
            and hi <= G.get("near_high_pct", 5):
        warns.append(f"overbought: RSI {rsi} within {hi}% of the 52-week high")
        mult *= G.get("overbought_multiplier", 0.8)
    vix = c.get("vix")
    if vix is not None and vix > G.get("high_vix", 30):
        warns.append(f"VIX {vix} > {G.get('high_vix', 30)}: market stress")
        mult *= G.get("high_vix_multiplier", 0.7)
    sh, th = c.get("safe_haven_5d_pct") or {}, G.get("risk_off_5d_pct", {"GLD": 2.0, "TLT": 1.0, "UUP": 1.0})
    if sh and all(k in sh for k in th) and all(sh[k] >= v for k, v in th.items()):
        warns.append("risk-off: gold, Treasuries and the dollar all rising over 5 days")
        mult *= G.get("risk_off_multiplier", 0.7)
    return max(mult, floor) if mult < 1 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--state")
    ap.add_argument("--limits", default=os.path.join(HERE, "..", "assets", "risk-limits.json"))
    ap.add_argument("--now")
    ap.add_argument("--context", help="market/event context JSON for timing gates")
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
        mult = timing_gates(L, o, json.load(open(a.context)) if a.context else None, now, blocks, warns)
    else:
        mult = 1.0
        warns.append("exit order: daily limits do not block exits")
    res = {"verdict": "BLOCK" if blocks else ("RESIZE" if mult < 1 else "PASS"), "fingerprint": fingerprint(o), "symbol": sym,
           "checked_at": now.isoformat(), "blocks": blocks, "warnings": warns, "size_multiplier": round(mult, 2),
           "next": ("Do not place this order." if blocks else
                     f"Cut qty to floor({o['qty']} x {round(mult, 2)}) and run risk_check again." if mult < 1 else
                     "Ask the user for an explicit yes naming this ticker, side and quantity.")}
    print(json.dumps(res, indent=2)); sys.exit(0 if not blocks else 2)

if __name__ == "__main__":
    main()
