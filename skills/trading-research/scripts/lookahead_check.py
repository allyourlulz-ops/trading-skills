#!/usr/bin/env python3
"""Look-ahead check for any local strategy. Stdlib only, no network.
Idea from jackson-cmd/risk-aware-trading-agents (MIT): rerun the strategy with every bar after a
cut date replaced by a random path; decisions on or before the cut must not change. Own code.
Usage: lookahead_check.py --prices closes.csv --cmd "python3 my_strategy.py --prices {prices}" [--cuts 5] [--seed 7]
closes.csv: date,SYM1,SYM2,... closes. The command must print decisions as CSV lines
date,symbol,action[,qty] (header optional). It runs on the user's machine with the user's own code.
Exit 0 = PASS (no decision before a cut changed), 2 = LEAK.
"""
import argparse, csv, json, math, os, random, shlex, statistics, subprocess, sys, tempfile


def read(path):
    with open(path) as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def decisions(cmd, path):
    p = subprocess.run(shlex.split(cmd.replace("{prices}", path)), capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise SystemExit("strategy failed: " + p.stderr[-500:])
    out = set()
    for line in p.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 3 and parts[0].lower() != "date":
            out.add(tuple(parts[:4]))
    return out


def scramble(header, rows, cut_i, rng):
    new = [r[:] for r in rows]
    for j in range(1, len(header)):
        col = [float(r[j]) for r in rows[:cut_i + 1] if r[j]]
        rets = [math.log(b / a) for a, b in zip(col, col[1:]) if a > 0 and b > 0] or [0.0]
        sd = statistics.pstdev(rets) or 0.01
        px = float(rows[cut_i][j])
        for i in range(cut_i + 1, len(rows)):
            px *= math.exp(rng.gauss(0, sd))
            new[i][j] = f"{px:.6f}"
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--cmd", required=True)
    ap.add_argument("--cuts", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    header, rows = read(a.prices)
    if len(rows) < 30:
        raise SystemExit("need at least 30 rows")
    rng = random.Random(a.seed)
    base = decisions(a.cmd, a.prices)
    n = len(rows)
    cuts = sorted({int(n * f) for f in [0.5 + 0.4 * k / max(1, a.cuts - 1) for k in range(a.cuts)]} - {n - 1})
    report, leak = [], False
    tmp = tempfile.mkdtemp()
    for c in cuts:
        cut_date = rows[c][0]
        path = os.path.join(tmp, f"cut_{c}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(header); w.writerows(scramble(header, rows, c, rng))
        alt = decisions(a.cmd, path)
        before = lambda s: {d for d in s if d[0] <= cut_date}
        changed = sorted(before(base) ^ before(alt))
        leak |= bool(changed)
        report.append(dict(cut=cut_date, changed=len(changed), examples=changed[:5]))
    print(json.dumps(dict(test="lookahead", verdict="LEAK" if leak else "PASS", cuts=report,
                          note="Dates compare as text, so use ISO dates (YYYY-MM-DD)."), indent=2))
    sys.exit(2 if leak else 0)


if __name__ == "__main__":
    main()
