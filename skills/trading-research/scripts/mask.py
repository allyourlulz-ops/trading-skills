#!/usr/bin/env python3
"""Mask tickers and dates in a data file before an LLM sees it, so memory of what happened cannot leak.
Stdlib only.

Usage:
  mask.py mask   --in bars.csv --out masked.csv --key key.json --level blinded
                 [--symbol-col symbol] [--date-col date] [--anchor 2026-01-02] [--seed 11]
  mask.py unmask --key key.json --value asset_007        (or --value day_+12)
  mask.py check  --in masked.csv --key key.json          (no real ticker or date left in the file)

Levels:  bright (nothing masked) | stock-blind (tickers -> asset_NNN) | date-blind (dates -> day_+N
relative to --anchor or the first date) | blinded (both).
Aliases are stable inside one key file and shuffled by --seed across episodes. Numbers are left as they
are (compute features on the real series first), so only the identifying handles change. Wide files
with tickers as column headers (date,AAPL,MSFT) are masked too: headers that are not the date column
are treated as tickers. key.json maps aliases back; keep it out of the model's context. Tool arguments
the model sends are unmasked with `unmask` before the MCP call and the result is masked again before
it goes back.
Method: four-level data-side masking protocol from KTD-Fin (Zhu et al., arXiv 2605.28359, 2026); own code.
Limits: a ticker named inside free text (news) is not masked; mask text with the same key or leave it
out. Price levels can still identify famous series; the check command flags exact tickers and dates only.
"""
import argparse, csv, datetime as dt, json, random, re, sys


def parse_date(s):
    return dt.date.fromisoformat(s.strip()[:10])


def cmd_mask(a):
    rows = list(csv.reader(open(a.inp, newline="")))
    if not rows:
        sys.exit("empty file")
    head, body = rows[0], rows[1:]
    if a.date_col not in head:
        sys.exit(f"no '{a.date_col}' column")
    di = head.index(a.date_col)
    si = head.index(a.symbol_col) if a.symbol_col in head else None
    wide = si is None
    stock = a.level in ("stock-blind", "blinded")
    date = a.level in ("date-blind", "blinded")
    rng = random.Random(a.seed)
    syms = sorted({r[si] for r in body} if not wide else {h for i, h in enumerate(head) if i != di})
    order = list(range(len(syms))); rng.shuffle(order)
    s_alias = {s: f"asset_{order[i]:03d}" for i, s in enumerate(syms)} if stock else {}
    dates = sorted({parse_date(r[di]) for r in body})
    anchor = parse_date(a.anchor) if a.anchor else dates[0]
    d_alias = {d.isoformat(): f"day_{(d - anchor).days:+d}" for d in dates} if date else {}
    out_head = [s_alias.get(h, h) if wide and i != di else h for i, h in enumerate(head)]
    w = csv.writer(open(a.out, "w", newline=""))
    w.writerow(out_head)
    for r in body:
        r = r[:]
        if date:
            r[di] = d_alias[parse_date(r[di]).isoformat()]
        if stock and not wide:
            r[si] = s_alias[r[si]]
        w.writerow(r)
    json.dump({"level": a.level, "seed": a.seed, "anchor": anchor.isoformat(),
               "symbols": {v: k for k, v in s_alias.items()}, "dates": {v: k for k, v in d_alias.items()}},
              open(a.key, "w"), indent=1)
    print(json.dumps({"level": a.level, "symbols_masked": len(s_alias), "dates_masked": len(d_alias),
                      "out": a.out, "key": a.key, "reminder": "keep the key file out of the model's context"}))


def cmd_unmask(a):
    k = json.load(open(a.key))
    v = a.value.strip()
    if v in k["symbols"]:
        print(k["symbols"][v]); return
    if v in k["dates"]:
        print(k["dates"][v]); return
    m = re.fullmatch(r"day_([+-]\d+)", v)
    if m:
        print((parse_date(k["anchor"]) + dt.timedelta(days=int(m.group(1)))).isoformat()); return
    sys.exit(f"unknown alias {v}")


def cmd_check(a):
    k = json.load(open(a.key))
    text = open(a.inp).read()
    leaks = [s for s in k["symbols"].values() if re.search(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])", text)]
    leaks += [d for d in k["dates"].values() if d in text]
    leaks += re.findall(r"\b(?:19|20)\d\d-\d\d-\d\d\b", text) if k["dates"] else []
    leaks = sorted(set(leaks))
    print(json.dumps({"verdict": "LEAK" if leaks else "CLEAN", "found": leaks[:20]}))
    sys.exit(1 if leaks else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("mask")
    m.add_argument("--in", dest="inp", required=True); m.add_argument("--out", required=True)
    m.add_argument("--key", required=True)
    m.add_argument("--level", choices=["bright", "stock-blind", "date-blind", "blinded"], default="blinded")
    m.add_argument("--symbol-col", default="symbol"); m.add_argument("--date-col", default="date")
    m.add_argument("--anchor"); m.add_argument("--seed", type=int, default=11)
    u = sp.add_parser("unmask"); u.add_argument("--key", required=True); u.add_argument("--value", required=True)
    c = sp.add_parser("check"); c.add_argument("--in", dest="inp", required=True); c.add_argument("--key", required=True)
    a = ap.parse_args()
    {"mask": cmd_mask, "unmask": cmd_unmask, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
