#!/usr/bin/env python3
"""Pre-trade hard gate. One exact order in, one verdict and one nonce out. Stdlib only, no network.
Shared, byte-identical, by trading-research (dry runs) and trading-execution (orders).

Usage
  risk_check.py --order order.json --portfolio portfolio.json --mode paper|live --contract contract.json
                [--instrument instrument.json] [--bar bar.json] [--context context.json]
                [--limits ../assets/risk-limits.json] [--gate-dir D] [--now ISO]
                [--override "reason" --override-ack "<gate.OVERRIDE_ACK>"]
order.json  {"symbol":"AAPL","side":"buy","qty":12,"type":"limit","limit_price":190.0,"stop_price":185.0,
             "target_price":205.0,"time_in_force":"day","asset_class":"equity","is_exit":false,
             "risk_pct":2}                       # risk_pct / risk_amount optional: the user's requested risk
portfolio   see position_size.py; also "paper": true|false and, for exchange sessions,
            "clock": {"is_open": true, "next_close": "...", "source": "alpaca:get_clock", "as_of": "..."}
contract    see data_contract.py; must contain a role "quote" series for this symbol
bar         {"timeframe":"5m","last_bar_open":"2026-11-25T10:25:00-05:00","closed":true}

Output JSON: {"verdict": "pass"|"fail", "reasons": [...], "limits_used": {...}, "sizing": {...},
              "nonce": "RC2....", "mode", "fingerprint", "warnings", "override", "checked_at", "next"}
reasons are "CODE: text". HARD codes can never be overridden; SOFT codes can, on paper only, with
--override "reason" (10+ chars) and --override-ack set to the exact sentence the user typed; the
override is logged to <gate_dir>/overrides.jsonl and the nonce says OVERRIDE.
The order's qty must not exceed the size position_size.size() allows for this portfolio: there is no
silent resize. Exits must match an open position (no exit flag on an opening trade).
Exit codes: 0 pass, 1 fail, 2 bad input. Every outcome, including bad input, gets a nonce or an error.
"""
from __future__ import annotations

import argparse, json, math, os, sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
try:
    from zoneinfo import ZoneInfo
except ImportError:  # py<3.9
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gate import OVERRIDE_ACK, fingerprint, issue  # noqa: E402
from position_size import SizingError, size  # noqa: E402
from data_contract import check as contract_check  # noqa: E402

DEFAULT_LIMITS = os.path.join(HERE, "..", "assets", "risk-limits.json")
SOFT = {"ENTRY_WINDOW", "TRADES_PER_DAY", "ORDERS_PER_DAY", "REWARD_RISK", "TIMING", "MIN_ORDER"}


def _days(a, b):
    from datetime import date
    return (date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days


TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def bar_gates(L, b, now, tz, blocks, warns):
    """Live-bar hygiene: no signal from an unfinished bar, no trading on frozen data."""
    if b is None:
        warns.append("no --bar: bar freshness unchecked (bots should always pass it)")
        return
    tf = TF_SEC.get(b.get("timeframe"))
    if tf is None:
        blocks.append(f"bar timeframe {b.get('timeframe')!r} unknown; use one of {', '.join(TF_SEC)}")
        return
    if b.get("closed") is not True:
        blocks.append("signal uses a bar that is still forming: drop the last unfinished bar and recompute")
    try:
        opened = datetime.fromisoformat(str(b["last_bar_open"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        blocks.append("bar.last_bar_open missing or not ISO 8601")
        return
    n = now if now.tzinfo else (now.replace(tzinfo=tz) if tz else None)
    if opened.tzinfo is None or n is None:
        blocks.append("bar time needs a timezone offset (e.g. +00:00) to measure staleness")
        return
    age = (n - opened).total_seconds() - tf  # seconds since the bar closed
    limit = L.get("timing", {}).get("max_stale_bars", 3)
    if age < 0 and b.get("closed") is True:
        blocks.append(f"bar marked closed but it closes in {int(-age)}s; clock or feed mismatch")
    elif age > limit * tf:
        blocks.append(f"data is stale: last bar closed {int(age)}s ago, more than {limit} x {b['timeframe']}; feed may be frozen")


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
        blocks.append(f"context is stale (as_of {c['as_of']}); refresh before trading")
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
    v3 = c.get("vix3m")
    if vix is not None and v3 and vix > v3:
        warns.append(f"VIX term structure inverted (VIX {vix} > VIX3M {v3}): near-term stress")
        mult *= G.get("vix_backwardation_multiplier", 0.8)
    for ev in c.get("event_risk") or []:
        if not ev.get("source_url"):
            warns.append(f"event_risk '{ev.get('event')}' ignored: needs a primary-source URL, not a keyword hit")
            continue
        m = G.get("event_direct_multiplier", 0.7) if ev.get("exposure") == "direct" else G.get("event_sector_multiplier", 0.85)
        warns.append(f"event risk: {ev.get('event')} ({ev.get('exposure', 'sector')} exposure)")
        mult *= m
    if ac == "crypto" and o["side"] == "buy":
        corr, b5 = c.get("btc_corr_30d"), c.get("btc_5d_pct")
        if corr is not None and b5 is not None and corr >= G.get("btc_corr_min", 0.7) and b5 <= G.get("btc_drawdown_5d_pct", -10):
            warns.append(f"BTC down {b5}% in 5 days and this coin's 30-day correlation is {corr}")
            mult *= G.get("btc_drag_multiplier", 0.7)
    return max(mult, floor) if mult < 1 else 1.0


class Reasons:
    def __init__(self) -> None:
        self.items: List[Tuple[str, str]] = []

    def add(self, code: str, text: str) -> None:
        self.items.append((code, text))

    def strings(self) -> List[str]:
        return [f"{c}: {t}" for c, t in self.items]

    def hard(self) -> List[str]:
        return [f"{c}: {t}" for c, t in self.items if c not in SOFT]


def side_of(o: Dict[str, Any]) -> str:
    s = str(o.get("side", "")).lower()
    if s not in ("buy", "sell"):
        raise ValueError("order.side must be buy or sell")
    return s


def check_exit(o: Dict[str, Any], pf: Dict[str, Any], R: Reasons) -> None:
    sym, qty = o["symbol"].upper(), float(o["qty"])
    pos = [p for p in pf.get("positions", []) if p["symbol"].upper() == sym]
    held = sum(float(p["qty"]) * (1 if p.get("side", "long") == "long" else -1) for p in pos)
    s = side_of(o)
    if held == 0:
        R.add("EXIT_NO_POSITION", f"is_exit but no open {sym} position: this would open a new one")
    elif (s == "sell" and held < 0) or (s == "buy" and held > 0):
        R.add("EXIT_WRONG_SIDE", f"is_exit {s} would add to the {sym} position, not reduce it")
    elif qty > abs(held) + 1e-12:
        R.add("EXIT_TOO_BIG", f"exit qty {qty} exceeds held {abs(held)}: the rest would open a reverse position")


def session_gates(L: Dict[str, Any], spec_session: str, pf: Dict[str, Any], now: datetime, R: Reasons) -> None:
    if spec_session == "24x7":
        return
    clk = pf.get("clock")
    if not clk or "is_open" not in clk or not clk.get("source"):
        R.add("NO_CLOCK", "exchange session needs portfolio.clock {is_open, source} from the broker")
        return
    if clk["is_open"] is not True:
        R.add("MARKET_CLOSED", f"market closed per {clk['source']}")
    hhmm = now.strftime("%H:%M")
    if hhmm < L.get("no_entries_before", "00:00"):
        R.add("ENTRY_WINDOW", f"no entries before {L['no_entries_before']}")
    if hhmm > L.get("no_entries_after", "23:59"):
        R.add("ENTRY_WINDOW", f"no entries after {L['no_entries_after']}")


def evaluate(o: Dict[str, Any], pf: Dict[str, Any], L: Dict[str, Any], mode: str, contract: Optional[Dict[str, Any]],
             instrument: Optional[Dict[str, Any]], bar: Optional[Dict[str, Any]], context: Optional[Dict[str, Any]],
             now: datetime, tz: Any) -> Tuple[Reasons, List[str], Dict[str, Any], Dict[str, Any]]:
    """Pure apart from the clock passed in. Returns (reasons, warnings, sizing, limits_used)."""
    R, warns = Reasons(), []
    sym = str(o["symbol"]).upper()
    s = side_of(o)
    qty = float(o["qty"])
    if qty <= 0:
        R.add("BAD_QTY", "qty must be > 0")
    ac = o.get("asset_class", "equity")
    exit_ = bool(o.get("is_exit"))
    used: Dict[str, Any] = {k: L.get(k) for k in (
        "base_currency", "max_risk_per_trade_pct", "max_loss_per_trade", "max_portfolio_heat_pct",
        "max_cluster_risk_pct", "cluster_corr", "max_daily_loss", "max_daily_loss_pct", "max_position_pct",
        "max_order", "min_order", "cash_buffer_pct", "gap_loss_multiple", "stop_slippage_bps",
        "min_reward_risk", "max_trades_per_day", "max_orders_per_day", "no_entries_before",
        "no_entries_after", "timezone", "paper", "allow_short", "allow_options", "allow_crypto", "allow_margin")
        if k in L}
    if sym in [b.upper() for b in L.get("blocked", [])]:
        R.add("BLOCKED_SYMBOL", f"{sym} is on the blocked list")
    if ac == "option" and not L.get("allow_options"):
        R.add("OPTIONS_OFF", "options disabled in limits")
    if ac == "crypto" and not L.get("allow_crypto", False):
        R.add("CRYPTO_OFF", "crypto disabled in limits")
    if o.get("uses_margin") and not L.get("allow_margin"):
        R.add("MARGIN_OFF", "margin disabled in limits")
    pmode = None if "paper" not in pf else ("paper" if pf["paper"] else "live")
    if mode not in ("paper", "live"):
        R.add("MODE_UNKNOWN", "pass --mode paper or live")
    if pmode is None:
        R.add("MODE_UNKNOWN", "portfolio.paper missing: the account's mode is not proven")
    elif mode in ("paper", "live") and pmode != mode:
        R.add("MODE_MISMATCH", f"--mode {mode} but the account is {pmode}")
    if mode == "live" and L.get("paper", True):
        R.add("LIVE_NOT_ALLOWED", "account is LIVE but limits require paper")
    sizing: Dict[str, Any] = {}
    if exit_:
        check_exit(o, pf, R)
        warns.append("exit order: entry limits are not applied to a verified reduce-only exit")
        return R, warns, sizing, used
    side = "long" if s == "buy" else "short"
    if side == "short" and not L.get("allow_short"):
        R.add("SHORT_OFF", "short selling disabled in limits")
    px = o.get("limit_price") if o.get("type", "limit") != "market" else o.get("est_price")
    if px is None:
        px = o.get("est_price")
    if px is None or float(px) <= 0:
        R.add("NO_PRICE", "need limit_price (or est_price for a market order) to measure risk")
        return R, warns, sizing, used
    px = float(px)
    stop = o.get("stop_price")
    if stop is None and ac != "option" and L.get("require_stop", True):
        R.add("NO_STOP", "stop_price required for entries")
    # data contract: hard, and it must cover this symbol's quote
    if contract is None:
        R.add("DATA_CONTRACT", "required for entries: pass --contract")
    else:
        c2 = dict(contract, decision_time=now.isoformat())  # the gate's clock, never the caller's
        dc = contract_check(c2, now.isoformat(), "sizing")
        if dc["verdict"] != "OK":
            R.add("DATA_CONTRACT", f"{dc['verdict']}: " + "; ".join(dc.get("reasons", []))[:300])
        q = [x for x in contract.get("series", []) if x.get("role") == "quote" and str(x.get("symbol", "")).upper() == sym]
        if not q:
            R.add("DATA_CONTRACT", f"no quote series for {sym} in the contract")
    if bar is not None or L.get("require_bar", False):
        blk: List[str] = []
        bar_gates(L, bar, now, tz, blk, warns)
        for b in blk:
            R.add("BAR", b)
    tblk: List[str] = []
    mult = timing_gates(L, o, context, now, tblk, warns)
    for b in tblk:
        R.add("STALE_CONTEXT" if b.startswith("context is stale") else "TIMING", b)
    today = pf.get("today") or {}
    if today.get("trades", 0) >= L.get("max_trades_per_day", math.inf):
        R.add("TRADES_PER_DAY", "max trades per day reached")
    if today.get("orders", 0) >= L.get("max_orders_per_day", math.inf):
        R.add("ORDERS_PER_DAY", "max orders per day reached")
    try:
        sizing = size(sym, side, px, None if stop is None else float(stop), pf, L, ac, instrument,
                      o.get("risk_pct"), o.get("risk_amount"), o.get("target_price"), mult)
    except SizingError as e:
        R.add("SIZING_INPUT", str(e))
        return R, warns, sizing, used
    session_gates(L, sizing["session"], pf, now, R)
    for r in sizing.get("reasons", []):
        code = "MIN_ORDER" if "min_order" in r else "RISK_LIMIT"
        R.add(code, r)
    if qty > sizing["qty"] + 1e-12:
        R.add("SIZE", f"qty {qty:g} > sized max {sizing['qty']:g} (binding: {sizing['binding_constraint']}); "
              f"send qty {sizing['qty']:g} and check again")
    rr = sizing.get("reward_risk")
    if rr is not None and rr < L.get("min_reward_risk", 0):
        R.add("REWARD_RISK", f"reward/risk {rr} < {L['min_reward_risk']}")
    if mult < 1:
        warns.append(f"timing gates cut the risk budget to {round(mult, 2)}x")
    return R, warns, sizing, used


def main() -> None:
    try:
        _main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed: any unexpected error is a fail with no usable nonce
        print(json.dumps({"verdict": "fail", "error": f"internal error: {type(e).__name__}: {e}", "nonce": None}, indent=2))
        sys.exit(2)


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--order", required=True); ap.add_argument("--portfolio", required=True)
    ap.add_argument("--mode", required=True, choices=["paper", "live"])
    ap.add_argument("--contract"); ap.add_argument("--instrument"); ap.add_argument("--bar"); ap.add_argument("--context")
    ap.add_argument("--limits", default=DEFAULT_LIMITS); ap.add_argument("--gate-dir"); ap.add_argument("--now")
    ap.add_argument("--override", help="reason for proceeding despite SOFT reasons (paper only, logged)")
    ap.add_argument("--override-ack", help="the exact acknowledgement sentence, typed by the user")
    a = ap.parse_args()
    ld = lambda p: json.load(open(p)) if p else None  # noqa: E731
    try:
        L, o, pf = ld(a.limits), ld(a.order), ld(a.portfolio)
        tz = ZoneInfo(L.get("timezone", "America/New_York")) if ZoneInfo else None
        now = datetime.fromisoformat(a.now) if a.now else datetime.now(tz)
        if now.tzinfo is None and tz is not None:
            now = now.replace(tzinfo=tz)
        R, warns, sizing, used = evaluate(o, pf, L, a.mode, ld(a.contract), ld(a.instrument), ld(a.bar),
                                          ld(a.context), now, tz)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(json.dumps({"verdict": "fail", "error": f"bad input: {e}", "nonce": None}, indent=2)); sys.exit(2)
    reasons, fp, override = R.strings(), fingerprint(o), None
    verdict = "FAIL" if reasons else "PASS"
    if a.override is not None and reasons:
        why = []
        if a.mode != "paper": why.append("overrides are paper only")
        if len(a.override.strip()) < 10: why.append("override reason must be 10+ characters")
        if a.override_ack != OVERRIDE_ACK: why.append(f'override ack must be exactly: "{OVERRIDE_ACK}" (typed by the user)')
        if R.hard(): why.append("HARD reasons cannot be overridden: " + "; ".join(R.hard()))
        override = {"accepted": not why, "reason": a.override.strip(), "refused_because": why,
                    "overridden": reasons if not why else []}
        if not why:
            verdict = "OVERRIDE"
    ttl = int((L.get("gate") or {}).get("token_ttl_s", 300))
    nonce = issue(verdict, fp, a.mode, a.limits, reasons, warns, a.gate_dir, ttl, now,
                  {"symbol": o.get("symbol"), "qty": o.get("qty"),
                   "override_reason": (override or {}).get("reason") if verdict == "OVERRIDE" else None,
                   "overridden": (override or {}).get("overridden") if verdict == "OVERRIDE" else None})
    out = {"verdict": "fail" if verdict == "FAIL" else "pass", "reasons": reasons, "limits_used": used, "sizing": sizing,
           "nonce": nonce, "mode": a.mode, "fingerprint": fp, "warnings": warns, "override": override,
           "checked_at": now.isoformat(),
           "next": ("Do not place this order. " + reasons[0] if verdict == "FAIL" else
                    "Override logged. Preview with --allow-override; the preview prints OVERRIDE." if verdict == "OVERRIDE" else
                    "Show preview.py output with this nonce, then get the user's yes for this exact order.")}
    print(json.dumps(out, indent=2)); sys.exit(1 if verdict == "FAIL" else 0)


if __name__ == "__main__":
    main()
