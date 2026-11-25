#!/usr/bin/env python3
"""Append-only trial ledger: one line per strategy variant, written BEFORE its result is read.
Stdlib only, no network.

Usage:
  trial_ledger.py log   --id mom12_1_v3 [--family mom12_1] [--note "enter .3 keep .5"]
  trial_ledger.py count [--family mom12_1] [--since YYYY-MM-DD]   -> {"distinct_trials": N}
  trial_ledger.py list  [--family mom12_1]
Ledger file: --ledger PATH, else $TRIAL_LEDGER, else ./trials.jsonl in the project directory.
validate_backtest.py, overfit.py dsr and pipeline.py accept --trials auto, which reads this count
(same --family and --ledger), so the deflated Sharpe deflates by what was really tried, not by a
number typed afterwards. Never edit or delete lines; a variant that was tried and dropped still counts.
Idea: an outside review of this skill (2026-11-24); trial counting follows Bailey and Lopez de Prado
(2014), who show the deflated Sharpe is only honest with the true number of trials. Own code.
"""
import argparse, json, os, sys
from datetime import datetime, timezone


def path(arg=None):
    return arg or os.environ.get("TRIAL_LEDGER") or os.path.join(os.getcwd(), "trials.jsonl")


def load(p):
    out = []
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def count(ledger=None, family=None, since=None):
    rows = load(path(ledger))
    if family:
        rows = [r for r in rows if r.get("family") == family]
    if since:
        rows = [r for r in rows if r.get("ts", "")[:10] >= since]
    return len({r["id"] for r in rows if "id" in r})


def resolve_trials(value, ledger=None, family=None, floor=1):
    """'auto' -> ledger count (at least floor); a number -> that number. Returns (n, source)."""
    if str(value).lower() == "auto":
        n = count(ledger, family)
        return (max(n, floor), "ledger") if n else (max(1, floor), "none")
    return max(int(value), floor), "typed"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["log", "count", "list"])
    ap.add_argument("--id"); ap.add_argument("--family"); ap.add_argument("--note", default="")
    ap.add_argument("--since"); ap.add_argument("--ledger")
    a = ap.parse_args()
    p = path(a.ledger)
    if a.cmd == "log":
        if not a.id:
            sys.exit("--id required")
        rec = {"id": a.id, "family": a.family, "note": a.note,
               "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps({"logged": rec, "ledger": p, "distinct_trials": count(a.ledger, a.family)}, indent=1))
    elif a.cmd == "count":
        print(json.dumps({"distinct_trials": count(a.ledger, a.family, a.since), "ledger": p, "family": a.family}))
    else:
        rows = load(p)
        print(json.dumps([r for r in rows if not a.family or r.get("family") == a.family], indent=1))


if __name__ == "__main__":
    main()
