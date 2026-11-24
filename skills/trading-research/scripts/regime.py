#!/usr/bin/env python3
"""Market regime and the actions each regime allows. Stdlib only, no network.
Own reimplementation of the regime idea in jackson-cmd/risk-aware-trading-agents (MIT), the best
performer in that project's 2026 test; thresholds are documented defaults, not copied code.
Usage: regime.py --spy 590 --ema50 580 --ema50-prev 578 --ema200 560 --vix 17.2 --vix3m 19.0
                 [--breadth 0.62] [--days-to-fomc 9] [--days-to-cpi 4] [--days-to-jobs 6]
                 [--hy-vs-ief-20d -0.5] [--fear-greed 55]
breadth = share of sectors above their EMA200 (0..1). hy-vs-ief-20d = HYG minus IEF 20-day return, %.
Prints JSON: regime (risk_on | neutral | uncertain | risk_off), size multiplier, allowed buys,
whether discretionary sells are allowed, and the reasons. Feed size_mult to risk_check --context.
"""
import argparse, json

PLAY = {
    "risk_on":   dict(size_mult=1.00, buys=["pullback", "breakout", "quality_dip"], sells="take_profit, trend_exit"),
    "neutral":   dict(size_mult=0.75, buys=["ema_support", "mean_reversion", "quality_dip"], sells="take_profit"),
    "uncertain": dict(size_mult=0.50, buys=["ema100_or_ema200_support_only"], sells="none: hold"),
    "risk_off":  dict(size_mult=0.35, buys=["quality_dip", "broad_etf", "small_tranches"], sells="none: hold"),
}


def classify(a):
    why = []
    backward = a.vix3m is not None and a.vix > a.vix3m
    credit = a.hy_vs_ief_20d is not None and a.hy_vs_ief_20d <= -2.0
    if a.vix >= 30 or (backward and a.spy < a.ema200) or credit:
        if a.vix >= 30: why.append(f"VIX {a.vix} >= 30")
        if backward and a.spy < a.ema200: why.append("VIX above VIX3M with SPY below EMA200")
        if credit: why.append(f"credit stress: HYG-IEF 20d {a.hy_vs_ief_20d}%")
        return "risk_off", why
    events = [(n, d) for n, d, lim in (("FOMC", a.days_to_fomc, 2), ("CPI", a.days_to_cpi, 1), ("jobs", a.days_to_jobs, 1))
              if d is not None and 0 <= d <= lim]
    downtrend = a.spy < a.ema50 and a.ema50 < a.ema50_prev
    if events or 20 <= a.vix < 30 or (a.fear_greed is not None and a.fear_greed < 35) or downtrend:
        why += [f"{n} in {d} day(s)" for n, d in events]
        if 20 <= a.vix < 30: why.append(f"VIX {a.vix} in 20-30")
        if a.fear_greed is not None and a.fear_greed < 35: why.append(f"fear gauge {a.fear_greed} < 35")
        if downtrend: why.append("SPY below a falling EMA50")
        return "uncertain", why
    rising = a.ema50 > a.ema50_prev
    broad = a.breadth is None or a.breadth > 0.5
    if a.spy > a.ema50 and a.spy > a.ema200 and rising and a.vix < 20 and broad:
        return "risk_on", ["SPY above a rising EMA50 and above EMA200", f"VIX {a.vix} < 20"] + (["breadth > 50%"] if a.breadth is not None else [])
    return "neutral", ["no risk-on, uncertain or risk-off trigger"]


def main():
    ap = argparse.ArgumentParser()
    for k in ("spy", "ema50", "ema50-prev", "ema200", "vix"):
        ap.add_argument("--" + k, type=float, required=True)
    for k in ("vix3m", "breadth", "hy-vs-ief-20d", "fear-greed"):
        ap.add_argument("--" + k, type=float)
    for k in ("days-to-fomc", "days-to-cpi", "days-to-jobs"):
        ap.add_argument("--" + k, type=int)
    a = ap.parse_args()
    reg, why = classify(a)
    out = dict(regime=reg, reasons=why, **PLAY[reg],
               always=["cash floor 30% of equity (cash + T-bill ETF)", "build positions in tranches 50/25/25",
                       "emergency exit only on a company-confirmed red flag (its own 8-K or press release) or the hard stop"],
               note="Context, not a signal. Every input needs its source and as-of time.")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
