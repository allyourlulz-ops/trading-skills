#!/usr/bin/env python3
"""Interlisted (TSX + US) fair value, cheaper-venue choice, and CAD/USD conversion cost. Stdlib only.

Idea credit: pricing a thin listing off its liquid twin, as in the Jane Street ETC ADR pair
(yafet-a/Jane-Street-FTTP-Trading-Bot, no licence; idea only, no code used).

Modes (all read one JSON file; every price carries its currency and a timestamp):
  pair     implied CAD price of the US line, premium in bps, and whether a two-leg trade clears
           costs at executable quotes (buy at ask, sell at bid, FX at the side you trade).
  buy      which listing is cheaper to BUY a given CAD amount of, all costs in.
  norbert  Norbert's gambit (buy DLR.TO in CAD, journal, sell DLR-U.TO in USD) vs the broker's FX.

pair/buy input:
  {"symbol":"RY", "ratio":1,                       # US shares per one TSX share
   "ca":{"bid":..,"ask":..,"ts":"2026-11-25T14:30:01-05:00"},   # CAD
   "us":{"bid":..,"ask":..,"ts":"2026-11-25T14:30:02-05:00"},   # USD
   "fx":{"bid":..,"ask":..,"ts":"...","source":"broker|boc|..."}, # USDCAD (CAD per USD)
   "fees":{"ca_per_trade_cad":0,"us_per_trade_usd":0,"fx_spread_bps":0},
   "amount_cad":10000, "max_skew_s":5}
norbert input:
  {"amount_cad":10000, "dlr_ask_cad":.., "dlr_u_bid_usd":.., "fx_ts":"...",
   "fees":{"per_trade_cad":0,"per_trade_usd":0,"journal_cad":0}, "broker_fx_rate":.., "broker_fx_source":".."}
Output JSON with a verdict. Refuses (STALE) when quotes are more than max_skew_s apart or outside
both regular sessions (09:30-16:00 America/Toronto, weekdays). Bank of Canada Valet is a daily
reference rate, not a quote you can trade: it is flagged and the pair verdict is capped at INDICATIVE.
"""
import argparse, json
from datetime import datetime, time, timedelta, timezone

ET = timezone(timedelta(hours=-5))  # assumed only for a timestamp with no offset


def ts(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=ET)


def in_session(t):
    # Toronto and New York share a clock; the quote's offset already reflects EST/EDT
    loc = t
    return loc.weekday() < 5 and time(9, 30) <= loc.time() <= time(16, 0)


def check_quotes(q, needs):
    warns, stale = [], []
    stamps = [ts(q[k]["ts"]) for k in needs]
    skew = (max(stamps) - min(stamps)).total_seconds()
    if skew > q.get("max_skew_s", 5):
        stale.append(f"quotes {skew:.0f}s apart (max {q.get('max_skew_s', 5)}s)")
    for k in needs:
        if not in_session(ts(q[k]["ts"])):
            stale.append(f"{k} quote outside 09:30-16:00 weekday session")
    for k in needs:
        if q[k]["bid"] > q[k]["ask"] or q[k]["bid"] <= 0:
            stale.append(f"{k} bid/ask invalid")
    return skew, warns, stale


def fx_side(q):
    fx, warns = dict(q["fx"]), []
    if "bid" not in fx:
        fx["bid"] = fx["ask"] = fx["mid"]
    sp = q.get("fees", {}).get("fx_spread_bps", 0) / 1e4
    if str(fx.get("source", "")).lower() in ("boc", "bank of canada", "valet"):
        warns.append("Bank of Canada rate is a daily reference, not a tradable quote: result is indicative")
    # selling USD gets fewer CAD; buying USD costs more CAD
    return fx["bid"] * (1 - sp), fx["ask"] * (1 + sp), warns


def pair(q):
    skew, warns, stale = check_quotes(q, ["ca", "us", "fx"])
    fx_sell_usd, fx_buy_usd, w = fx_side(q); warns += w
    r = q.get("ratio", 1)
    f = q.get("fees", {})
    ca_mid = (q["ca"]["bid"] + q["ca"]["ask"]) / 2
    us_mid_cad = (q["us"]["bid"] + q["us"]["ask"]) / 2 * r * (fx_sell_usd + fx_buy_usd) / 2
    prem = (ca_mid / us_mid_cad - 1) * 1e4
    amt = q.get("amount_cad", 10000)
    n = amt / q["ca"]["ask"]
    fixed = f.get("ca_per_trade_cad", 0) + f.get("us_per_trade_usd", 0) * fx_buy_usd
    # leg A: buy TSX at ask, sell US at bid, USD proceeds converted to CAD
    a = n * (q["us"]["bid"] * r * fx_sell_usd - q["ca"]["ask"]) - fixed
    # leg B: buy US at ask (paying USD bought with CAD), sell TSX at bid
    b = n * (q["ca"]["bid"] - q["us"]["ask"] * r * fx_buy_usd) - fixed
    best = max(a, b)
    out = {"mode": "pair", "symbol": q.get("symbol"), "premium_bps_tsx_over_us": round(prem, 1),
           "us_mid_in_cad": round(us_mid_cad, 4), "tsx_mid_cad": round(ca_mid, 4), "quote_skew_s": skew,
           "net_cad_buy_tsx_sell_us": round(a, 2), "net_cad_buy_us_sell_tsx": round(b, 2),
           "notional_cad": amt, "warnings": warns}
    if stale:
        out.update(verdict="STALE", reasons=stale)
    elif best <= 0:
        out.update(verdict="NO_EDGE", reasons=["gap does not cover spreads, FX and commissions at executable quotes"])
    else:
        out.update(verdict="INDICATIVE" if warns else "EDGE_AFTER_COSTS", net_cad=round(best, 2),
                   reasons=["needs both legs filled at once and shares already held for the sell leg (no naked shorts)",
                            "journal or settlement between venues is the broker's process; confirm before trading"])
    return out


def buy(q):
    skew, warns, stale = check_quotes(q, ["ca", "us", "fx"])
    fx_sell_usd, fx_buy_usd, w = fx_side(q); warns += w
    r, f, amt = q.get("ratio", 1), q.get("fees", {}), q.get("amount_cad", 10000)
    cost_ca = q["ca"]["ask"]  # CAD per TSX share
    cost_us = q["us"]["ask"] * r * fx_buy_usd  # CAD per TSX-equivalent via US line
    sh_ca = (amt - f.get("ca_per_trade_cad", 0)) / cost_ca
    sh_us = (amt - f.get("us_per_trade_usd", 0) * fx_buy_usd) / cost_us
    diff = (sh_us / sh_ca - 1) * 1e4
    out = {"mode": "buy", "symbol": q.get("symbol"), "amount_cad": amt,
           "shares_via_tsx": round(sh_ca, 4), "shares_equiv_via_us": round(sh_us, 4),
           "us_better_by_bps": round(diff, 1), "quote_skew_s": skew, "warnings": warns,
           "notes": ["not in this number: the FX to convert back when you sell, and the currency the dividend is paid in. "
                     "Withholding follows the issuer's home country, not the listing: a Canadian issuer's US line has no US withholding"]}
    if stale:
        out.update(verdict="STALE", reasons=stale)
    else:
        out["verdict"] = "BUY_US" if diff > 0 else "BUY_TSX"
    return out


def norbert(q):
    f, amt = q.get("fees", {}), q["amount_cad"]
    n = int((amt - f.get("per_trade_cad", 0)) // q["dlr_ask_cad"])
    usd = n * q["dlr_u_bid_usd"] - f.get("per_trade_usd", 0)
    spent = n * q["dlr_ask_cad"] + f.get("per_trade_cad", 0) + f.get("journal_cad", 0)
    eff = spent / usd  # CAD paid per USD received
    out = {"mode": "norbert", "units": n, "cad_spent": round(spent, 2), "usd_received": round(usd, 2),
           "effective_usdcad": round(eff, 5),
           "notes": ["journal takes the broker's processing time; you carry DLR price risk until it clears",
                     "units are whole; leftover CAD stays CAD"]}
    if "broker_fx_rate" in q:
        b_usd = spent / q["broker_fx_rate"]  # USD the same CAD buys at the broker
        out.update(broker_usd_same_cad=round(b_usd, 2), gambit_saves_usd=round(usd - b_usd, 2),
                   broker_fx_source=q.get("broker_fx_source"))
        out["verdict"] = "GAMBIT_CHEAPER" if eff < q["broker_fx_rate"] else "BROKER_CHEAPER"
    else:
        out["verdict"] = "NO_BROKER_RATE"
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["pair", "buy", "norbert"]); p.add_argument("--input", required=True)
    a = p.parse_args()
    q = json.load(open(a.input))
    print(json.dumps({"pair": pair, "buy": buy, "norbert": norbert}[a.mode](q), indent=2))
