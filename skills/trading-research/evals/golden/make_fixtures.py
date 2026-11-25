#!/usr/bin/env python3
"""Rebuild the validate_backtest golden fixtures. Deterministic (seed 7), stdlib only.
python3 make_fixtures.py  -> writes fixtures/ and the manifests used by cases.json."""
import csv, json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "fixtures")


def bdays(start, n):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def write(name, header, rows):
    with open(os.path.join(F, name), "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def equity(rets):
    v, out = 100.0, []
    for r in rets:
        v *= 1 + r; out.append(round(v, 6))
    return out


def main():
    os.makedirs(F, exist_ok=True)
    rnd = random.Random(7)
    n = 756
    D = bdays(date(2022, 1, 3), n)
    turn = [0.05] * n
    cost_bps = 5.0  # fee 1 + slippage 4
    g = [0.0] + [0.0009 + 0.006 * rnd.gauss(0, 1) for _ in range(n - 1)]
    net = [x - (2 * t * cost_bps / 1e4 if i else 0) for i, (x, t) in enumerate(zip(g, turn))]
    b = [0.0] + [0.0003 + 0.01 * rnd.gauss(0, 1) for _ in range(n - 1)]
    write("gross.csv", ["date", "value"], zip(D, equity(g)))
    write("net.csv", ["date", "value"], zip(D, equity(net)))
    write("bench.csv", ["date", "value"], zip(D, equity(b)))
    write("turnover.csv", ["date", "turnover"], zip(D, turn))
    write("regimes.csv", ["date", "label"], [(d, "risk_on" if (i // 126) % 2 == 0 else "risk_off") for i, d in enumerate(D)])
    # one-regime variant: losing in risk_off
    g1 = [x if (i // 126) % 2 == 0 else x * 0.3 - 0.0012 for i, x in enumerate(g)]
    g1 = [x * 3 if (i // 126) % 2 == 0 else x for i, x in enumerate(g1)]
    net1 = [x - (2 * t * cost_bps / 1e4 if i else 0) for i, (x, t) in enumerate(zip(g1, turn))]
    write("gross_oneregime.csv", ["date", "value"], zip(D, equity(g1)))
    write("net_oneregime.csv", ["date", "value"], zip(D, equity(net1)))
    # cost-fragile variant: high turnover, thin edge
    t2 = [1.0] * n
    g2 = [0.0] + [0.0012 + 0.006 * rnd.gauss(0, 1) for _ in range(n - 1)]
    net2 = [x - (2 * t * cost_bps / 1e4 if i else 0) for i, (x, t) in enumerate(zip(g2, t2))]
    write("gross_fragile.csv", ["date", "value"], zip(D, equity(g2)))
    write("net_fragile.csv", ["date", "value"], zip(D, equity(net2)))
    write("turnover_fragile.csv", ["date", "turnover"], zip(D, t2))
    # benchmark on shifted dates (misaligned)
    write("bench_disjoint.csv", ["date", "value"], zip(bdays(date(2030, 1, 7), n), equity(b)))
    write("bench_shifted.csv", ["date", "value"], zip(bdays(date(2023, 6, 1), n), equity(b)))
    # trades: signal at close, entry next bar open, exit later
    hdr = ["signal_time", "entry_time", "exit_time", "side", "exit_reason", "stop", "target", "exit_bar_high", "exit_bar_low"]
    rows = []
    for k in range(40):
        i = 10 + k * 18
        rows.append([D[i] + "T16:00:00-05:00", D[i + 1] + "T09:30:00-05:00", D[i + 6] + "T16:00:00-05:00", "long",
                     "target" if k % 3 else "stop", 95.0, 110.0, 108.0 if k % 3 == 0 else 111.0, 94.0 if k % 3 == 0 else 101.0])
    write("trades.csv", hdr, rows)
    bad = [r[:] for r in rows]; bad[3][1] = bad[3][0]
    write("trades_lookahead.csv", hdr, bad)
    amb = [r[:] for r in rows]; amb[4][4], amb[4][7], amb[4][8] = "target", 111.0, 94.0
    write("trades_samebar.csv", hdr, amb)
    folds = [{"train_start": D[0], "train_end": D[251], "test_start": D[252], "test_end": D[419]},
             {"train_start": D[0], "train_end": D[419], "test_start": D[420], "test_end": D[587]},
             {"train_start": D[0], "train_end": D[587], "test_start": D[588], "test_end": D[755]}]
    base = {"strategy": "golden_pass", "periods_per_year": 252, "timeframe": "1d",
            "gross_equity": "fixtures/gross.csv", "net_equity": "fixtures/net.csv", "turnover": "fixtures/turnover.csv",
            "costs": {"fee_bps": 1, "slippage_bps": 4}, "benchmark": "fixtures/bench.csv", "trades": "fixtures/trades.csv",
            "trials": 5, "universe": {"single_instrument": True}, "walk_forward": {"folds": folds},
            "regimes": "fixtures/regimes.csv", "llm_in_loop": False}
    variants = {
        "pass": {},
        "lookahead": {"trades": "fixtures/trades_lookahead.csv"},
        "samebar": {"trades": "fixtures/trades_samebar.csv"},
        "no_slippage": {"costs": {"fee_bps": 1}},
        "single_split": {"walk_forward": {"folds": folds[:1]}},
        "llm_leak": {"llm_in_loop": True, "model_train_cutoff": "2025-01-01"},
        "llm_clean": {"llm_in_loop": True, "model_train_cutoff": "2022-06-30"},
        "misaligned": {"benchmark": "fixtures/bench_shifted.csv"},
        "cost_fragile": {"gross_equity": "fixtures/gross_fragile.csv", "net_equity": "fixtures/net_fragile.csv",
                         "turnover": "fixtures/turnover_fragile.csv"},
        "one_regime": {"gross_equity": "fixtures/gross_oneregime.csv", "net_equity": "fixtures/net_oneregime.csv"},
        "no_universe": {"universe": None},
        "many_trials": {"trials": 100000},
        "net_mismatch": {"net_equity": "fixtures/gross.csv"},
    }
    for k, v in variants.items():
        m = dict(base); m.update(v); m["strategy"] = "golden_" + k
        m = {a: b for a, b in m.items() if b is not None}
        json.dump(m, open(os.path.join(HERE, f"manifest_{k}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
