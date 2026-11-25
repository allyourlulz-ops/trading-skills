#!/usr/bin/env python3
"""Minimal stdlib backtest engine whose output is exactly what validate_backtest.py --manifest reads.
Stdlib only, no network. The engine abstraction follows HKUDS/Vibe-Trading (MIT), studied, not vendored:
a SignalEngine turns bars into target weights in [-1, 1], and a per-market rules object decides
can_execute / round_size / commission / slippage. None of its code or dependencies are used.

Usage
  engine.py --bars bars.csv --signal my_signal.py --market us_equity|ca_equity|crypto --out DIR
            [--capital 100000] [--fee-bps 1] [--slippage-bps 4] [--stop-pct 0.05] [--target-pct 0.10]
bars.csv  date,open,high,low,close   (one instrument; as-filed, split-and-dividend adjusted for returns)
my_signal.py defines class SignalEngine with a no-argument constructor and
    generate(self, bars: list[dict]) -> list[float]     # one target weight per bar, decided at its close
Execution rules (fixed, not options):
  * a weight decided at bar t's close trades at bar t+1's open (never the same bar)
  * a stop and a target are set at entry; if one bar touches both, the STOP fills (pessimistic)
  * gaps through the stop fill at the open, not at the stop
  * costs: fee_bps + slippage_bps per side on traded notional; net = gross - 2 x turnover x bps
    (turnover is one-way; per side because the in and out legs are each a trade)
Writes DIR/gross.csv, net.csv, turnover.csv (date,value / date,turnover) and trades.csv with the columns
the manifest's lookahead and same-bar checks read. Exit 0 on success, 2 on bad input.
"""
from __future__ import annotations

import argparse, csv, importlib.util, json, math, os, sys
from typing import Any, Dict, List

MARKETS: Dict[str, Dict[str, Any]] = {
    "us_equity": {"lot_step": 1.0, "allow_short": False, "close": "16:00:00-05:00", "open": "09:30:00-05:00"},
    "ca_equity": {"lot_step": 1.0, "allow_short": False, "close": "16:00:00-05:00", "open": "09:30:00-05:00"},
    "crypto": {"lot_step": 1e-6, "allow_short": False, "close": "23:59:59+00:00", "open": "00:00:00+00:00"},
}


class Rules:
    """Per-market rules (Vibe-Trading's BaseEngine hooks, reduced to what a one-asset test needs)."""

    def __init__(self, market: str, fee_bps: float, slip_bps: float) -> None:
        if market not in MARKETS:
            raise ValueError(f"market must be one of {', '.join(MARKETS)}")
        self.m, self.fee, self.slip = MARKETS[market], fee_bps, slip_bps

    def can_execute(self, weight: float) -> bool:
        return weight >= 0 or self.m["allow_short"]

    def round_size(self, qty: float) -> float:
        s = self.m["lot_step"]
        return math.floor(qty / s + 1e-9) * s

    def cost(self, notional: float) -> float:
        return abs(notional) * (self.fee + self.slip) / 1e4


def load_bars(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({"date": r["date"], **{k: float(r[k]) for k in ("open", "high", "low", "close")}})
    if len(rows) < 30:
        raise ValueError("need at least 30 bars")
    if any(b["date"] <= a["date"] for a, b in zip(rows, rows[1:])):
        raise ValueError("bar dates must be strictly increasing")
    return rows


def load_signal(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("user_signal", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.SignalEngine()


def run(bars: List[Dict[str, Any]], weights: List[float], rules: Rules, capital: float,
        stop_pct: float, target_pct: float) -> Dict[str, List[Any]]:
    if len(weights) != len(bars):
        raise ValueError("generate() must return one weight per bar")
    w = [max(-1.0, min(1.0, float(x))) for x in weights]
    prev, net_eq, cash, qty = capital, 100.0, capital, 0.0
    gross, net, turn, trades = [], [], [], []
    entry = None
    for t, b in enumerate(bars):
        traded = 0.0
        # 1) stop / target on the open position, stop first
        if qty and entry:
            stop, tgt = entry["stop"], entry["target"]
            hit = None
            if b["open"] <= stop:
                hit, px = "stop", b["open"]
            elif b["low"] <= stop:
                hit, px = "stop", stop
            elif b["high"] >= tgt:
                hit, px = "target", max(tgt, b["open"])
            if hit:
                traded += abs(qty * px); cash += qty * px
                trades.append({**entry["row"], "exit_time": f"{b['date']}T{rules.m['close']}", "exit_reason": hit,
                               "exit_bar_high": b["high"], "exit_bar_low": b["low"]})
                qty, entry = 0.0, None
        # 2) the weight decided at the previous close trades at this open
        if t > 0:
            want = w[t - 1] if rules.can_execute(w[t - 1]) else 0.0
            value = cash + qty * b["open"]
            tq = rules.round_size(want * value / b["open"]) if want > 0 else 0.0
            if qty == 0 and entry is None and tq > 0:
                traded += abs(tq * b["open"]); cash -= tq * b["open"]; qty = tq
                entry = {"stop": b["open"] * (1 - stop_pct), "target": b["open"] * (1 + target_pct),
                         "row": {"signal_time": f"{bars[t - 1]['date']}T{rules.m['close']}",
                                 "entry_time": f"{b['date']}T{rules.m['open']}", "side": "long",
                                 "stop": round(b["open"] * (1 - stop_pct), 6), "target": round(b["open"] * (1 + target_pct), 6)}}
            elif qty > 0 and tq == 0:
                traded += abs(qty * b["open"]); cash += qty * b["open"]
                trades.append({**entry["row"], "exit_time": f"{b['date']}T{rules.m['open']}", "exit_reason": "signal",
                               "exit_bar_high": b["high"], "exit_bar_low": b["low"]})
                qty, entry = 0.0, None
        mark = cash + qty * b["close"]
        to = traded / prev / 2  # one-way turnover: notional traded / equity at the last close / 2
        g = mark / prev - 1
        net_eq *= 1 + g - 2 * to * (rules.fee + rules.slip) / 1e4  # same formula validate_backtest checks
        prev = mark
        gross.append((b["date"], round(mark / capital * 100, 10)))
        net.append((b["date"], round(net_eq, 10)))
        turn.append((b["date"], round(to, 12)))
    return {"gross": gross, "net": net, "turnover": turn, "trades": trades}


def write(out: str, res: Dict[str, List[Any]]) -> None:
    os.makedirs(out, exist_ok=True)
    for k, hdr in (("gross", "value"), ("net", "value"), ("turnover", "turnover")):
        with open(os.path.join(out, k + ".csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["date", hdr]); w.writerows(res[k])
    cols = ["signal_time", "entry_time", "exit_time", "side", "exit_reason", "stop", "target", "exit_bar_high", "exit_bar_low"]
    with open(os.path.join(out, "trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(res["trades"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bars", required=True); ap.add_argument("--signal", required=True)
    ap.add_argument("--market", required=True, choices=sorted(MARKETS)); ap.add_argument("--out", required=True)
    ap.add_argument("--capital", type=float, default=100000); ap.add_argument("--fee-bps", type=float, default=1)
    ap.add_argument("--slippage-bps", type=float, default=4)
    ap.add_argument("--stop-pct", type=float, default=0.05); ap.add_argument("--target-pct", type=float, default=0.10)
    a = ap.parse_args()
    try:
        bars = load_bars(a.bars)
        res = run(bars, load_signal(a.signal).generate(bars), Rules(a.market, a.fee_bps, a.slippage_bps),
                  a.capital, a.stop_pct, a.target_pct)
    except (OSError, ValueError, KeyError, AttributeError) as e:
        print(json.dumps({"ok": False, "error": str(e)})); sys.exit(2)
    write(a.out, res)
    print(json.dumps({"ok": True, "bars": len(bars), "trades": len(res["trades"]), "out": a.out,
                      "costs_bps_per_side": a.fee_bps + a.slippage_bps,
                      "next": "write a manifest pointing at these files and run validate_backtest.py --manifest"}, indent=2))


if __name__ == "__main__":
    main()
