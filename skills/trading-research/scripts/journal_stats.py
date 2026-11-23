#!/usr/bin/env python3
"""Trade journal statistics and rule-break audit. Stdlib only.
Usage: journal_stats.py --trades trades.csv [--rules rules.json]
trades.csv (one closed trade per row; broker exports can be mapped to this):
  date,symbol,side,entry,exit,stop,qty,fees,setup,tags,notes
  side long|short; stop = planned stop at entry; tags ; separated (fomo;moved_stop;late_entry)
rules.json (optional): {"max_risk_usd":50,"max_trades_per_day":3,"require_stop":true,"allowed_setups":["pullback","breakout"]}
Prints JSON: win rate, average win/loss, expectancy in R and $, profit factor, max drawdown,
longest losing streak, stats by setup and by tag, and every rule break found.
"""
import argparse, csv, json
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--rules")
    a = ap.parse_args()
    R = json.load(open(a.rules)) if a.rules else {}
    rows = list(csv.DictReader(open(a.trades, newline="")))
    T, breaks, per_day = [], [], defaultdict(int)
    for i, r in enumerate(rows, 1):
        e, x, q = float(r["entry"]), float(r["exit"]), float(r["qty"])
        sg = 1 if r.get("side", "long") == "long" else -1
        fees = float(r.get("fees") or 0)
        pnl = sg * (x - e) * q - fees
        stop = float(r["stop"]) if r.get("stop") else None
        risk = abs(e - stop) * q if stop is not None else None
        rr = pnl / risk if risk else None
        tags = [t.strip() for t in (r.get("tags") or "").split(";") if t.strip()]
        day = r["date"][:10]
        per_day[day] += 1
        T.append(dict(n=i, date=day, symbol=r["symbol"], pnl=pnl, R=rr, setup=r.get("setup") or "none", tags=tags))
        if R.get("require_stop") and stop is None:
            breaks.append(f"#{i} {r['symbol']} {day}: no stop")
        if R.get("max_risk_usd") and risk and risk > R["max_risk_usd"]:
            breaks.append(f"#{i} {r['symbol']} {day}: risked ${risk:.2f} > ${R['max_risk_usd']}")
        if R.get("allowed_setups") and r.get("setup") not in R["allowed_setups"]:
            breaks.append(f"#{i} {r['symbol']} {day}: setup '{r.get('setup')}' not in plan")
        if rr is not None and rr < -1.2:
            breaks.append(f"#{i} {r['symbol']} {day}: lost {rr:.2f}R, past the stop")
    if R.get("max_trades_per_day"):
        breaks += [f"{d}: {c} trades > {R['max_trades_per_day']}" for d, c in per_day.items() if c > R["max_trades_per_day"]]
    n = len(T)
    if not n:
        raise SystemExit("no trades")
    wins, losses = [t for t in T if t["pnl"] > 0], [t for t in T if t["pnl"] <= 0]
    eq = peak = mdd = 0.0
    streak = worst = 0
    for t in T:
        eq += t["pnl"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        streak = streak + 1 if t["pnl"] <= 0 else 0; worst = max(worst, streak)
    Rs = [t["R"] for t in T if t["R"] is not None]

    def group(key):
        g = defaultdict(list)
        for t in T:
            for k in (t[key] if key == "tags" else [t[key]]):
                g[k].append(t)
        return {k: dict(n=len(v), win_pct=round(100 * sum(1 for t in v if t["pnl"] > 0) / len(v), 1),
                        pnl=round(sum(t["pnl"] for t in v), 2)) for k, v in sorted(g.items(), key=lambda kv: sum(t["pnl"] for t in kv[1]))}
    gp, gl = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in losses)
    print(json.dumps(dict(
        trades=n, win_rate_pct=round(100 * len(wins) / n, 1),
        avg_win=round(gp / len(wins), 2) if wins else 0, avg_loss=round(-gl / len(losses), 2) if losses else 0,
        expectancy_usd=round((gp - gl) / n, 2), expectancy_R=round(sum(Rs) / len(Rs), 3) if Rs else None,
        profit_factor=round(gp / gl, 3) if gl else None, net_pnl=round(gp - gl, 2), max_drawdown_usd=round(mdd, 2),
        longest_losing_streak=worst, by_setup=group("setup"), by_tag=group("tags"), rule_breaks=breaks,
        notes=["Under 30 trades, expectancy is mostly noise.",
               "The tag with the worst P&L is the habit to fix first."]), indent=2))


if __name__ == "__main__":
    main()
