#!/usr/bin/env python3
"""P13: the two risk-limits.json copies are not byte-identical by design (research lets proposals and
backtests use shorts, options and crypto). This guard says they differ ONLY there, and that the execution
copy keeps those switches off. Stdlib only.

Usage: limits_guard.py [EXEC_LIMITS RESEARCH_LIMITS]     exit 0 when clean, 1 with the drift listed
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXEC = os.path.join(HERE, "..", "assets", "risk-limits.json")
RES = os.path.join(HERE, "..", "..", "trading-research", "assets", "risk-limits.json")
# keys allowed to differ, and why
MAY_DIFFER = {
    "_notes": "prose",
    "allow_short": "research proposals and backtests may use short legs",
    "allow_options": "research proposals may use defined-risk options",
    "allow_crypto": "research may study crypto",
    "cost_ladder_bps": "research-only (costs.py)",
    "require_survives_cost_x": "research-only (pipeline.py)",
}
EXEC_MUST = {"paper": True, "allow_short": False, "allow_options": False, "allow_crypto": False, "allow_margin": False}


def flat(d, p=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, p + k + "."))
        else:
            out[p + k] = v
    return out


def drift(exec_limits, research_limits):
    a, b = flat(exec_limits), flat(research_limits)
    out = ["%s differs (execution %r, research %r)" % (k, a.get(k), b.get(k))
           for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k) and k not in MAY_DIFFER]
    out += ["execution %s must be %r (is %r)" % (k, v, exec_limits.get(k)) for k, v in EXEC_MUST.items()
            if exec_limits.get(k) != v]
    return out


if __name__ == "__main__":
    e, r = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else (EXEC, RES)
    if not os.path.exists(r):
        print("research limits not found next to this skill: nothing to compare"); sys.exit(0)
    d = drift(json.load(open(e)), json.load(open(r)))
    print("\n".join(d) if d else "risk-limits copies differ only where intended")
    sys.exit(1 if d else 0)
