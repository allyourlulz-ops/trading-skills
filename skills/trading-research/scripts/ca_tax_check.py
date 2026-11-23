#!/usr/bin/env python3
"""Canadian adjusted cost base (ACB), capital gains and superficial-loss check. Stdlib only.
Not tax advice: a record-keeping aid to hand to the user or their accountant.

Usage: ca_tax_check.py --tx transactions.csv [--year 2026] [--tfsa-trades-warn 50]
transactions.csv, every buy and sell in every account the user and their spouse control, oldest first:
  date,account,account_type,symbol,side,qty,price,fees,currency,fx_to_cad
  account_type: taxable | tfsa | rrsp | rrif | fhsa | resp | spouse_taxable | corp
  currency: CAD or USD...; fx_to_cad: the Bank of Canada rate for that day (1 for CAD)

Rules applied (CRA guide T4037, Income Tax Act s.54 and s.251.1):
  ACB is the average cost per share across all of one person's taxable accounts, in CAD, with
  commissions added to cost and deducted from proceeds; each trade converted at its own day's rate.
  A loss is superficial when you or an affiliated person (spouse, a corporation either controls,
  your or their TFSA/RRSP/RRIF/FHSA) acquires identical property in the 30 days before or after
  the sale AND still holds it on day 30 after. Denied share = min(sold, bought in window, held on
  day 30) / sold. The denied loss is added to the ACB of the shares you rebought in a taxable
  account; rebought inside a registered plan or by someone else, it is lost to you.
Output JSON: realized gains by year, each sale with proceeds, ACB, gain, denied loss and why,
year-end ACB per symbol, and warnings (frequent TFSA trading can be taxed as business income).
"""
import argparse, csv, json
from collections import defaultdict
from datetime import date, timedelta

OWN_TAXABLE = {"taxable"}
AFFILIATED = {"taxable", "tfsa", "rrsp", "rrif", "fhsa", "spouse_taxable", "corp"}  # resp is not affiliated


def d(s):
    return date.fromisoformat(s[:10])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tx", required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("--tfsa-trades-warn", type=int, default=50)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.tx, newline="")))
    for r in rows:
        r["d"] = d(r["date"])
        r["qty"] = float(r["qty"])
        r["px_cad"] = float(r["price"]) * float(r.get("fx_to_cad") or 1)
        r["fee_cad"] = float(r.get("fees") or 0) * float(r.get("fx_to_cad") or 1)
        r["symbol"] = r["symbol"].upper()
        r["account_type"] = r.get("account_type", "taxable").lower()
    rows.sort(key=lambda r: (r["d"], 0 if r["side"].lower() == "buy" else 1))
    # holdings of identical property across the affiliated group, by day, for the day-30 test
    def group_held_on(sym, day):
        q = 0.0
        for r in rows:
            if r["symbol"] == sym and r["account_type"] in AFFILIATED and r["d"] <= day:
                q += r["qty"] if r["side"].lower() == "buy" else -r["qty"]
        return max(q, 0.0)

    shares, cost = defaultdict(float), defaultdict(float)
    sales, gains, warn = [], defaultdict(float), []
    pending_add = []  # (date, symbol, amount) denied losses to add to ACB once the rebuy is known
    for i, r in enumerate(rows):
        if r["account_type"] not in OWN_TAXABLE:
            continue
        s = r["symbol"]
        if r["side"].lower() == "buy":
            shares[s] += r["qty"]
            cost[s] += r["qty"] * r["px_cad"] + r["fee_cad"]
            for pd, ps, amt in list(pending_add):
                if ps == s:
                    cost[s] += amt
                    pending_add.remove((pd, ps, amt))
            continue
        if shares[s] <= 0:
            warn.append(f"{r['date']} sell of {s} with no recorded taxable holding (short sale or missing history)")
            continue
        acb_ps = cost[s] / shares[s]
        acb = acb_ps * r["qty"]
        proceeds = r["qty"] * r["px_cad"] - r["fee_cad"]
        gain = proceeds - acb
        denied, why = 0.0, None
        if gain < 0:
            lo, hi = r["d"] - timedelta(days=30), r["d"] + timedelta(days=30)
            bought = [b for b in rows if b is not r and b["symbol"] == s and b["side"].lower() == "buy"
                      and b["account_type"] in AFFILIATED and lo <= b["d"] <= hi]
            qb = sum(b["qty"] for b in bought)
            if qb > 0:
                held = group_held_on(s, hi)
                frac = min(r["qty"], qb, held) / r["qty"]
                if frac > 0:
                    denied = -gain * frac
                    where = sorted({b["account_type"] for b in bought})
                    why = (f"identical {s} bought {qb:g} sh between {lo} and {hi} in {', '.join(where)}, "
                           f"{held:g} sh still held on {hi}")
                    if any(t in OWN_TAXABLE for t in where):
                        pending_add.append((r["d"], s, denied))
                    else:
                        why += "; rebought outside your taxable accounts, so the denied loss is lost, not deferred"
        shares[s] -= r["qty"]
        cost[s] -= acb
        if shares[s] <= 1e-9:
            shares[s], cost[s] = 0.0, 0.0
        for pd, ps, amt in list(pending_add):
            if ps == s and shares[s] > 0:
                cost[s] += amt
                pending_add.remove((pd, ps, amt))
        allowed = gain + denied
        gains[r["d"].year] += allowed
        sales.append(dict(date=r["date"], symbol=s, qty=r["qty"], proceeds_cad=round(proceeds, 2),
                          acb_cad=round(acb, 2), gain_cad=round(gain, 2), denied_loss_cad=round(denied, 2),
                          allowed_gain_cad=round(allowed, 2), superficial=why))
    # denied losses whose rebuy came later in the file
    for pd, ps, amt in pending_add:
        if shares[ps] > 0:
            cost[ps] += amt
        else:
            warn.append(f"denied loss on {ps} from {pd} could not be added to an ACB; check the rebuy")
    tf = defaultdict(int)
    for r in rows:
        if r["account_type"] == "tfsa":
            tf[r["d"].year] += 1
    for y, n in tf.items():
        if n >= a.tfsa_trades_warn:
            warn.append(f"{n} TFSA trades in {y}: frequent trading in a TFSA can be taxed as business income")
    if any(r["account_type"] == "tfsa" and r.get("currency", "CAD").upper() == "USD" for r in rows):
        warn.append("US securities in a TFSA: the 15% US withholding tax on dividends is not recoverable there "
                    "(an RRSP is exempt under the treaty when it holds US-listed shares directly)")
    out = dict(
        realized_gains_cad_by_year={y: round(v, 2) for y, v in sorted(gains.items()) if not a.year or y == a.year},
        sales=[s for s in sales if not a.year or s["date"].startswith(str(a.year))],
        year_end_acb={s: dict(shares=round(shares[s], 4), acb_cad=round(cost[s], 2),
                              acb_per_share=round(cost[s] / shares[s], 4)) for s in shares if shares[s] > 0},
        warnings=warn,
        notes=["Report on Schedule 3; the taxable share of a net gain is set by the inclusion rate for that year.",
               "Registered-plan trades (TFSA, RRSP, RRIF, FHSA) are not taxable sales but do count for superficial losses.",
               "Not tax advice; confirm with the user's accountant."])
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
