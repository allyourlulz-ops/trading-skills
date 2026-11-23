#!/usr/bin/env python3
"""Binary-outcome sizing (prediction markets, yes/no contracts). Stdlib only.
Usage: kelly.py --price 0.42 --prob 0.55 --bankroll 500 [--fee-pct 2] [--fraction 0.25]
                [--min-edge-pts 8] [--max-stake-pct 5] [--side yes|no]
price   market price of the contract you would buy (0-1, = implied probability)
prob    YOUR probability that it resolves your way, from evidence, not from the price
Prints JSON: edge in points, full and fractional Kelly stake, expected value, verdict.
Defaults are conservative: quarter Kelly, no bet under an 8-point edge, cap 5% of bankroll.
"""
import argparse, json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--prob", type=float, required=True)
    ap.add_argument("--bankroll", type=float, required=True)
    ap.add_argument("--side", choices=["yes", "no"], default="yes")
    ap.add_argument("--fee-pct", type=float, default=0.0, help="fee as % of winnings")
    ap.add_argument("--fraction", type=float, default=0.25)
    ap.add_argument("--min-edge-pts", type=float, default=8.0)
    ap.add_argument("--max-stake-pct", type=float, default=5.0)
    a = ap.parse_args()
    price, p = a.price, a.prob
    if a.side == "no":
        price, p = 1 - price, 1 - p
    if not (0 < price < 1 and 0 <= p <= 1):
        raise SystemExit("price must be in (0,1) and prob in [0,1]")
    b = (1 - price) / price * (1 - a.fee_pct / 100)  # net odds per $1 staked
    edge_pts = (p - price) * 100
    full = max(0.0, (b * p - (1 - p)) / b)
    stake = min(full * a.fraction, a.max_stake_pct / 100) * a.bankroll
    ev = (p * b - (1 - p)) * stake
    if edge_pts < a.min_edge_pts or full == 0:
        verdict, stake, ev = "NO_BET", 0.0, 0.0
    else:
        verdict = "BET"
    print(json.dumps(dict(side=a.side, price=round(price, 4), your_prob=round(p, 4), edge_pts=round(edge_pts, 2),
                          net_odds=round(b, 4), full_kelly_pct=round(100 * full, 2), fraction=a.fraction,
                          stake=round(stake, 2), expected_value=round(ev, 2), verdict=verdict,
                          notes=["The price is the crowd's probability; you need evidence it is wrong.",
                                 "Log the call in scorekeeper.py; size up only after your Brier score beats the market's.",
                                 "One limit order at a time; still needs risk_check-style limits and the user's yes."]), indent=2))


if __name__ == "__main__":
    main()
