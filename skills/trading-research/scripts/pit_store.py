#!/usr/bin/env python3
"""Live data pipeline for MCP-fetched bars: source fallback with cooldowns, one merged point-in-time
store, and as-of reads that never return a future or still-forming bar. Stdlib only, no network:
the agent fetches bars through its MCP servers and hands the rows to this script as files.

Usage:
  pit_store.py route  --routes ../assets/data-routes.json --asset equity_us --state state.json [--now ISO]
  pit_store.py fail   --state state.json --source openbb --code 429 [--now ISO]
  pit_store.py ok     --state state.json --source openbb
  pit_store.py ingest --store merged.jsonl --source openbb --timeframe 1d --file rows.json
                      [--routes ../assets/data-routes.json --asset equity_us] [--fetched-at ISO] [--now ISO] [--tol-pct 0.5]
  pit_store.py asof   --store merged.jsonl --symbol AAPL --timeframe 1d --at ISO [--n 60] [--bar-out bar.json]
  pit_store.py conflicts --store merged.jsonl

rows.json: a list of {"symbol","ts","open","high","low","close","volume"[,"closed"]} (ts = bar OPEN
time, ISO 8601 with offset). CSV with the same headers also works.
- route: the asset's sources in priority order, skipping any still in cooldown (state.json).
- fail: 429 sets a long cooldown, 5xx/timeout a short one; consecutive failures double it (cap 60 min).
  Report the failure per source (rule 6) and move to the next source in the route.
- ingest: normalises symbols (upper case, "BTC/USD" -> "BTC-USD", exchange suffixes such as .TO kept),
  marks a bar closed only when ts + timeframe <= --now, and keys rows by (symbol, timeframe, ts).
  A closed bar replaces a forming one; between two closed bars the higher-priority source wins and a
  close that differs by more than 0.5% is kept as a conflict (show both, never average).
- asof: only closed bars whose close time is <= --at, newest last; --bar-out writes the
  {timeframe,last_bar_open,closed} file that risk_check.py --bar reads.
Pipeline idea (provider routing, fallback, cooldown and backoff, merged store, anti-look-ahead price
reads) from HKUDS/AI-Trader, which has no licence file; no code from it is used. Its direct API pulls
(Alpha Vantage, yfinance, Hyperliquid) are replaced here by the user's MCP servers.
"""
import argparse, csv, json, os, sys
from datetime import datetime, timedelta, timezone

TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
COOL = {"429": 900, "5xx": 120, "timeout": 120, "auth": 3600}


def ts(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None:
        sys.exit(f"time {s!r} needs a timezone offset")
    return d


def now_of(a):
    return ts(a.now) if getattr(a, "now", None) else datetime.now(timezone.utc)


def load_json(p, default):
    return json.load(open(p)) if p and os.path.exists(p) else default


def norm(sym):
    s = str(sym).strip().upper().replace(" ", "")
    return s.replace("/", "-")


def cmd_route(a):
    R = load_json(a.routes, {})
    if a.asset not in R.get("routes", {}):
        sys.exit(f"no route for {a.asset}; known: {', '.join(R.get('routes', {}))}")
    st, n = load_json(a.state, {}), now_of(a)
    out, cooling = [], []
    for s in R["routes"][a.asset]:
        until = st.get(s, {}).get("until")
        if until and ts(until) > n:
            cooling.append({"source": s, "until": until})
        else:
            out.append(s)
    print(json.dumps({"asset": a.asset, "try_in_order": out, "cooling_down": cooling,
                      "verdict": "OK" if out else "NO_SOURCE"}))
    sys.exit(0 if out else 2)


def cmd_fail(a):
    st, n = load_json(a.state, {}), now_of(a)
    code = "429" if a.code == "429" else "auth" if a.code in ("401", "403") else "timeout" if a.code == "timeout" else "5xx"
    e = st.get(a.source, {"fails": 0})
    e["fails"] = e.get("fails", 0) + 1
    secs = min(3600, COOL[code] * 2 ** (e["fails"] - 1))
    e.update(until=(n + timedelta(seconds=secs)).isoformat(), last_code=a.code)
    st[a.source] = e
    json.dump(st, open(a.state, "w"), indent=1)
    print(json.dumps({"source": a.source, "cooldown_s": secs, "until": e["until"], "fails_in_a_row": e["fails"]}))


def cmd_ok(a):
    st = load_json(a.state, {})
    st.pop(a.source, None)
    json.dump(st, open(a.state, "w"), indent=1)
    print(json.dumps({"source": a.source, "status": "reset"}))


def read_rows(p):
    if p.endswith(".csv"):
        return list(csv.DictReader(open(p, newline="")))
    d = json.load(open(p))
    return d.get("rows", d) if isinstance(d, dict) else d


def cmd_ingest(a):
    tf = TF_SEC.get(a.timeframe) or sys.exit(f"timeframe must be one of {', '.join(TF_SEC)}")
    n = now_of(a)
    fetched = a.fetched_at or n.isoformat()
    prio = load_json(a.routes, {}).get("routes", {}).get(a.asset, []) if a.routes and a.asset else []
    rank = lambda s: prio.index(s) if s in prio else len(prio)
    store = {}
    if os.path.exists(a.store):
        for line in open(a.store):
            if line.strip():
                r = json.loads(line); store[(r["symbol"], r["timeframe"], r["ts"])] = r
    added = replaced = kept = conflicts = 0
    for raw in read_rows(a.file):
        try:
            t = ts(raw["ts"])
            r = {"symbol": norm(raw["symbol"]), "timeframe": a.timeframe, "ts": t.isoformat(),
                 "open": float(raw["open"]), "high": float(raw["high"]), "low": float(raw["low"]),
                 "close": float(raw["close"]), "volume": float(raw.get("volume") or 0),
                 "closed": t + timedelta(seconds=tf) <= n, "source": a.source, "fetched_at": fetched}
        except (KeyError, ValueError) as e:
            sys.exit(f"bad row {raw}: {e}")
        k = (r["symbol"], r["timeframe"], r["ts"])
        old = store.get(k)
        if old is None:
            store[k] = r; added += 1; continue
        better = (r["closed"] and not old["closed"]) or (r["closed"] == old["closed"] and rank(r["source"]) <= rank(old["source"]))
        win, lose = (r, old) if better else (old, r)
        if "alt" in lose:
            win.setdefault("alt", {}).update({k2: v for k2, v in lose["alt"].items() if k2 != win["source"]})
        if old["closed"] and r["closed"] and old["source"] != r["source"]:
            diff = abs(old["close"] - r["close"]) / max(abs(old["close"]), 1e-12) * 100
            if diff > a.tol_pct:
                conflicts += 1
                win.setdefault("alt", {})[lose["source"]] = lose["close"]
        store[k] = win
        if better:
            replaced += 1
        else:
            kept += 1
    with open(a.store, "w") as fh:
        for k in sorted(store):
            fh.write(json.dumps(store[k]) + "\n")
    print(json.dumps({"added": added, "replaced": replaced, "kept_existing": kept, "close_conflicts": conflicts,
                      "store_rows": len(store), "source": a.source, "fetched_at": fetched}))


def cmd_asof(a):
    tf = TF_SEC.get(a.timeframe) or sys.exit("unknown timeframe")
    at, sym = ts(a.at), norm(a.symbol)
    rows = [json.loads(l) for l in open(a.store) if l.strip()]
    rows = [r for r in rows if r["symbol"] == sym and r["timeframe"] == a.timeframe]
    ok = sorted((r for r in rows if r["closed"] and ts(r["ts"]) + timedelta(seconds=tf) <= at), key=lambda r: r["ts"])
    hidden = sum(1 for r in rows if ts(r["ts"]) + timedelta(seconds=tf) > at)
    out = ok[-a.n:] if a.n else ok
    res = {"symbol": sym, "timeframe": a.timeframe, "as_of": at.isoformat(), "rows": out,
           "hidden_future_or_forming": hidden, "sources": sorted({r["source"] for r in out})}
    if a.bar_out and out:
        json.dump({"timeframe": a.timeframe, "last_bar_open": out[-1]["ts"], "closed": True}, open(a.bar_out, "w"))
        res["bar_file"] = a.bar_out
    if not out:
        res["warning"] = "no closed bar on or before as_of"
    print(json.dumps(res, indent=1))


def cmd_conflicts(a):
    rows = [json.loads(l) for l in open(a.store) if l.strip()]
    c = [{"symbol": r["symbol"], "ts": r["ts"], "kept": {r["source"]: r["close"]}, "other": r["alt"]}
         for r in rows if r.get("alt")]
    print(json.dumps({"conflicts": c, "count": len(c)}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("route"); p.add_argument("--routes", required=True); p.add_argument("--asset", required=True)
    p.add_argument("--state", required=True); p.add_argument("--now")
    p = sp.add_parser("fail"); p.add_argument("--state", required=True); p.add_argument("--source", required=True)
    p.add_argument("--code", required=True, help="429, 5xx, timeout, 401/403"); p.add_argument("--now")
    p = sp.add_parser("ok"); p.add_argument("--state", required=True); p.add_argument("--source", required=True)
    p = sp.add_parser("ingest"); p.add_argument("--store", required=True); p.add_argument("--source", required=True)
    p.add_argument("--timeframe", required=True); p.add_argument("--file", required=True)
    p.add_argument("--routes"); p.add_argument("--asset"); p.add_argument("--fetched-at"); p.add_argument("--now")
    p.add_argument("--tol-pct", type=float, default=0.5, help="close gap between sources that counts as a conflict")
    p = sp.add_parser("asof"); p.add_argument("--store", required=True); p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe", required=True); p.add_argument("--at", required=True)
    p.add_argument("--n", type=int, default=0); p.add_argument("--bar-out")
    p = sp.add_parser("conflicts"); p.add_argument("--store", required=True)
    a = ap.parse_args()
    {"route": cmd_route, "fail": cmd_fail, "ok": cmd_ok, "ingest": cmd_ingest, "asof": cmd_asof,
     "conflicts": cmd_conflicts}[a.cmd](a)


if __name__ == "__main__":
    main()
