#!/usr/bin/env python3
"""Multi-leg options payoff at expiry + Black-Scholes value, greeks and probability of profit.
Stdlib only, no network (pull chain, IV and spot from the data MCP server).
Usage: options_payoff.py --spot 100 --legs legs.json [--iv 0.30] [--days 30] [--rate 0.04]
legs.json: [{"type":"put","side":"sell","strike":95,"premium":1.80,"qty":1},
            {"type":"put","side":"buy","strike":90,"premium":0.70,"qty":1}]
           type call|put|stock (stock: premium = entry price per share, strike ignored, qty in SHARES);
           option qty is in contracts (x100 shares). Covered call = 100 shares + 1 short call.
Per-leg "iv" overrides --iv. Prints JSON: net credit/debit, max profit, max loss, breakevens,
probability of profit (lognormal at the given IV), net greeks, payoff table.
"""
import argparse, json, math


def N(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def n(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs(kind, S, K, T, r, v):
    if T <= 0 or v <= 0:
        intr = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
        return intr, (1.0 if S > K else 0.0) if kind == "call" else (-1.0 if S < K else 0.0), 0.0, 0.0, 0.0
    d1 = (math.log(S / K) + (r + v * v / 2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    if kind == "call":
        price = S * N(d1) - K * math.exp(-r * T) * N(d2); delta = N(d1)
        theta = -S * n(d1) * v / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * N(d2)
    else:
        price = K * math.exp(-r * T) * N(-d2) - S * N(-d1); delta = N(d1) - 1
        theta = -S * n(d1) * v / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * N(-d2)
    gamma = n(d1) / (S * v * math.sqrt(T)); vega = S * n(d1) * math.sqrt(T) / 100
    return price, delta, gamma, theta / 365, vega


def payoff(legs, S):
    tot = 0.0
    for L in legs:
        sgn = 1 if L["side"] == "buy" else -1
        mult = 100 * L.get("qty", 1)
        if L["type"] == "stock":
            tot += sgn * (S - L["premium"]) * L.get("qty", 1)
            continue
        intr = max(0.0, S - L["strike"]) if L["type"] == "call" else max(0.0, L["strike"] - S)
        tot += sgn * (intr - L["premium"]) * mult
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", type=float, required=True)
    ap.add_argument("--legs", required=True)
    ap.add_argument("--iv", type=float, default=0.30)
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument("--rate", type=float, default=0.04)
    a = ap.parse_args()
    legs = json.load(open(a.legs))
    S, T = a.spot, a.days / 365
    strikes = sorted({L["strike"] for L in legs if L["type"] != "stock"} | {S})
    lo, hi = 0.01, max(strikes) * 2.0
    grid = [lo + (hi - lo) * i / 2000 for i in range(2001)]
    pay = [payoff(legs, x) for x in grid]
    bes = [round(grid[i] - pay[i] * (grid[i + 1] - grid[i]) / (pay[i + 1] - pay[i]), 2)
           for i in range(len(grid) - 1) if pay[i] == 0 or (pay[i] < 0) != (pay[i + 1] < 0)]
    has_long_call_tail = sum((1 if L["side"] == "buy" else -1) * L.get("qty", 1) * (100 if L["type"] == "call" else 1)
                             for L in legs if L["type"] in ("call", "stock"))
    max_p = "unlimited" if has_long_call_tail > 0 else round(max(pay + [payoff(legs, 0.0)]), 2)
    max_l = "unlimited" if has_long_call_tail < 0 else round(min(pay + [payoff(legs, 0.0)]), 2)
    v_ = a.iv
    # probability of profit under lognormal terminal price with drift r
    pop = 0.0
    for i in range(len(grid) - 1):
        if pay[i] > 0:
            z = lambda x: (math.log(x / S) - (a.rate - v_ * v_ / 2) * T) / (v_ * math.sqrt(T))
            pop += N(z(grid[i + 1])) - N(z(grid[i]))
    if pay[-1] > 0:
        pop += 1 - N((math.log(grid[-1] / S) - (a.rate - v_ * v_ / 2) * T) / (v_ * math.sqrt(T)))
    if pay[0] > 0:
        pop += N((math.log(grid[0] / S) - (a.rate - v_ * v_ / 2) * T) / (v_ * math.sqrt(T)))
    net, stock_cost, G = 0.0, 0.0, dict(delta=0.0, gamma=0.0, theta=0.0, vega=0.0)
    warnings = []
    opt_shares = sum(100 * L.get("qty", 1) for L in legs if L["type"] == "call" and L["side"] == "sell")
    stock_long = sum(L.get("qty", 1) for L in legs if L["type"] == "stock" and L["side"] == "buy")
    if stock_long and stock_long < 100 and opt_shares:
        warnings.append(f"stock qty is {stock_long} shares; stock qty is in shares, not lots (a covered call needs 100 per contract)")
    if stock_long and opt_shares > stock_long:
        warnings.append(f"short calls cover {opt_shares} shares but only {stock_long} are held: {opt_shares - stock_long} uncovered")
    for L in legs:
        sgn = 1 if L["side"] == "buy" else -1
        if L["type"] == "stock":
            G["delta"] += sgn * L.get("qty", 1); stock_cost += sgn * L["premium"] * L.get("qty", 1); continue
        m = 100 * L.get("qty", 1)
        _, d, g, th, ve = bs(L["type"], S, L["strike"], T, a.rate, L.get("iv", v_))
        G["delta"] += sgn * d * m; G["gamma"] += sgn * g * m; G["theta"] += sgn * th * m; G["vega"] += sgn * ve * m
        net -= sgn * L["premium"] * m
    table = [dict(price=round(x, 2), pnl=round(payoff(legs, x), 2))
             for x in sorted({round(S * k, 2) for k in (0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2)} | set(strikes))]
    print(json.dumps(dict(net_option_premium=round(net, 2), credit=net > 0, stock_cost=round(stock_cost, 2),
                          net_cash_outlay=round(stock_cost - net, 2), warnings=warnings, max_profit=max_p, max_loss=max_l,
                          breakevens=bes, prob_of_profit_pct=round(100 * pop, 1),
                          greeks={k: round(v, 3) for k, v in G.items()}, payoff_at_expiry=table,
                          notes=["Probability of profit assumes the IV given; real moves have fatter tails.",
                                 "Undefined-risk shapes (naked short calls) are blocked unless the limits allow them.",
                                 "Close or roll before earnings and major macro releases unless that is the trade."]), indent=2))


if __name__ == "__main__":
    main()
