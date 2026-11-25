#!/usr/bin/env python3
"""Data contract and staleness gate. Stdlib only. Shared, byte-identical, by trading-research and
trading-execution. position_size.py and risk_check.py refuse to size or pass an entry when it fails.

Usage: data_contract.py --contract contract.json [--now ISO] [--purpose sizing|backtest|research]
contract.json:
  {"decision_time": "2026-11-25T10:30:05-05:00",          # when the number will be used (default: now)
   "purpose": "sizing",                                   # sizing | backtest | research
   "max_stale_bars": 3, "max_skew_bars": 1,
   "series": [
     {"name": "AAPL quote", "symbol": "AAPL", "role": "quote",          # quote | stop_basis | signal | returns | fx
      "source": "alpaca:get_stock_latest_quote", "as_of": "2026-11-25T10:30:01-05:00",
      "last_bar_end": "2026-11-25T10:30:00-05:00", "timeframe": "1m",
      "adjustment": "raw", "currency": "USD"}, ...]}
Every series must state: source, as_of (ISO 8601 WITH offset), last_bar_end, timeframe, adjustment
(raw | split | split_div), currency. Rules:
  INVALID    a field missing, a timestamp without an offset, an unknown adjustment or timeframe,
             or as_of / last_bar_end after decision_time (data from the future).
  STALE      decision_time - last_bar_end > max_stale_bars bars (1d: more than max_stale_bars weekdays).
  UNALIGNED  series of one timeframe whose last bars end more than max_skew_bars apart; or mixed
             adjustment policies among price series; or prices in two currencies with no fx series.
  POLICY     purpose sizing: quote / stop_basis / signal prices must be raw or split (orders fill in raw
             prices; dividend-adjusted history puts the stop in the wrong place). purpose backtest:
             returns series must be split_div (raw history books splits and dividends as returns).
  OK         none of the above.
Exit 0 only on OK.
"""
import argparse, json, sys
from datetime import datetime, timedelta, timezone

TF = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
ADJ = ("raw", "split", "split_div")
NEED = ("source", "as_of", "last_bar_end", "timeframe", "adjustment", "currency")


def _t(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("no offset")
    return t


def _weekdays_between(a, b):
    n, d = 0, a.date()
    while d < b.date():
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def check(c, now=None, purpose=None):
    reasons = {"INVALID": [], "STALE": [], "UNALIGNED": [], "POLICY": []}
    purpose = purpose or c.get("purpose", "sizing")
    try:
        dt = _t(c["decision_time"]) if c.get("decision_time") else (
            _t(now) if now else datetime.now(timezone.utc))
    except ValueError:
        return {"verdict": "INVALID", "reasons": ["decision_time needs an ISO 8601 offset"], "series": []}
    S = c.get("series") or []
    if not S:
        reasons["INVALID"].append("no series listed")
    stale_n, skew_n = c.get("max_stale_bars", 3), c.get("max_skew_bars", 1)
    rows, ends = [], {}
    for s in S:
        nm = s.get("name") or s.get("symbol") or "?"
        miss = [k for k in NEED if s.get(k) in (None, "")]
        if miss:
            reasons["INVALID"].append(f"{nm}: missing {', '.join(miss)}"); continue
        if s["timeframe"] not in TF:
            reasons["INVALID"].append(f"{nm}: timeframe {s['timeframe']!r} unknown"); continue
        if s["adjustment"] not in ADJ:
            reasons["INVALID"].append(f"{nm}: adjustment must be one of {', '.join(ADJ)}"); continue
        try:
            asof, end = _t(s["as_of"]), _t(s["last_bar_end"])
        except ValueError:
            reasons["INVALID"].append(f"{nm}: as_of and last_bar_end need an ISO 8601 offset"); continue
        if asof > dt or end > dt:
            reasons["INVALID"].append(f"{nm}: timestamp after decision_time (data from the future)")
        tf = TF[s["timeframe"]]
        age = (dt - end).total_seconds()
        if s["timeframe"] in ("1d", "1w"):
            bars = _weekdays_between(end, dt) / (5 if s["timeframe"] == "1w" else 1)
        else:
            bars = age / tf
        if bars > stale_n:
            reasons["STALE"].append(f"{nm}: last bar ended {round(bars, 1)} bars before decision_time (max {stale_n})")
        ends.setdefault(s["timeframe"], []).append((end, nm))
        rows.append({"name": nm, "role": s.get("role", "signal"), "age_bars": round(bars, 2), "adjustment": s["adjustment"],
                     "currency": s["currency"], "source": s["source"]})
    for tf, lst in ends.items():
        lo, hi = min(lst), max(lst)
        daily = tf in ("1d", "1w")
        gap = _weekdays_between(lo[0], hi[0]) if daily else (hi[0] - lo[0]).total_seconds() / TF[tf]
        if gap > skew_n:
            reasons["UNALIGNED"].append(f"{tf}: {lo[1]} ends {lo[0].isoformat()}, {hi[1]} ends {hi[0].isoformat()}")
    px = [r for r in rows if r["role"] != "fx"]
    if len({r["adjustment"] for r in px if r["role"] in ("returns", "signal")}) > 1:
        reasons["UNALIGNED"].append("mixed adjustment policies among signal/returns series")
    if len({r["currency"] for r in px}) > 1 and not any(r["role"] == "fx" for r in rows):
        reasons["UNALIGNED"].append("prices in %s with no fx series" % "/".join(sorted({r['currency'] for r in px})))
    for r in rows:
        if purpose == "sizing" and r["role"] in ("quote", "stop_basis", "signal") and r["adjustment"] == "split_div":
            reasons["POLICY"].append(f"{r['name']}: sizing needs raw (or split) prices, not dividend-adjusted")
        if purpose == "backtest" and r["role"] == "returns" and r["adjustment"] != "split_div":
            reasons["POLICY"].append(f"{r['name']}: backtest returns need split_div adjustment")
    verdict = next((k for k in ("INVALID", "STALE", "UNALIGNED", "POLICY") if reasons[k]), "OK")
    return {"verdict": verdict, "purpose": purpose, "decision_time": dt.isoformat(),
            "reasons": [x for k in reasons for x in reasons[k]], "series": rows}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True); ap.add_argument("--now")
    ap.add_argument("--purpose", choices=["sizing", "backtest", "research"])
    a = ap.parse_args()
    r = check(json.load(open(a.contract)), a.now, a.purpose)
    print(json.dumps(r, indent=2)); sys.exit(0 if r["verdict"] == "OK" else 2)
