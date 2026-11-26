#!/usr/bin/env python3
"""Replay a fixture directory through the whole place-it path and diff it against expected.json.
Stdlib only, no network. Every step is the real script, run as a subprocess.

  portfolio  portfolio.json as given, or built by the simulated broker layer named in meta.broker:
               alpaca_paper  alpaca/account.json, clock.json, positions.json (Alpaca Trading API v2;
                             recorded by record_alpaca.py, or synthetic)
               ibkr_paper    ibkr/accounts.json, summary.json, positions.json (IBKR Client Portal Web
                             API; recorded by record_ibkr.py against a logged-in gateway, or synthetic);
                             the session comes from meta.clock, since that API has no clock call
             alpaca/ or ibkr/ also holds recorded.json (from a recorder) or synthetic.json (hand-written)
  order      order.json (its fingerprint is what the gate binds)
  risk_check scripts/risk_check.py with the fixture's limits, contract and fixed --now
  preview    scripts/preview.py --json with the risk result, the MCP config and the same --now
  fill       simulated: only when the preview gate is OPEN; filled at the limit price, never sent

Usage
  repro.py FIXTURE_DIR [FIXTURE_DIR ...]      replay and diff; exit 1 on any diff or error
  repro.py --all [ROOT]                       every fixture under ROOT (default: evals/repro)
  repro.py FIXTURE_DIR --bless                write expected.json from this run (review it first)
  repro.py ... --require-recorded             a fixture waiting for recorded responses fails
                                              instead of being skipped

FIXTURE_DIR/meta.json
  {"synthetic": true|false, "description": "...", "broker": "alpaca_paper" | "ibkr_paper",
   "now": "<ISO 8601 with offset>", "mode": "paper", "lock": "mcp-lock.json",
   "clock": {"is_open": true, "source": "...", "as_of": "..."},   (ibkr_paper only)
   "limits": "limits.json", "contract": "contract.json", "instrument": null, "bar": null, "context": null,
   "config": "mcp-config.json", "server": "alpaca", "override": {"reason": "...", "ack": "..."},
   "allow_override": false, "today": {"trades": 0, "orders": 0, "planned_loss": 0}}
  "now": "from_clock" uses the recorded Alpaca clock timestamp as the fixed --now; "from_recorded"
  uses recorded_at in the broker dir's recorded.json (IBKR).
  Paths are relative to FIXTURE_DIR; config defaults to the shipped paper config. A "{NOW}" in the
  contract, instrument, bar or context file is replaced by the fixed --now (templates for recordings).

Volatile fields are normalised before the diff: the nonce's expiry, random part and MAC, the
preview's "Nonce: ..." line, checked_at and clock.system_drift_s. Everything else must match exactly. The gate dir is a
fresh temp dir outside the repository, removed afterwards.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
REPO = os.path.dirname(os.path.dirname(SKILL))
DEFAULT_ROOT = os.path.join(HERE, "repro")
DEFAULT_CONFIG = os.path.join(SKILL, "assets", "mcp-config.paper-execute.json")
PAPER_HOST = "paper-api.alpaca.markets"
NONCE_RE = re.compile(r"RC2\.(PASS|FAIL|OVERRIDE)\.([0-9a-f]{16})\.(paper|live|unknown)\.\d+\.([0-9a-z]+)\.[0-9a-f]+\.[0-9a-f]+")


# checked_at and the clock's drift from the machine running the replay change on every run
VOLATILE = {"checked_at", "system_drift_s"}


class Waiting(Exception):
    """The fixture is a slot for recorded responses that have not been recorded yet."""


def _iso(ts):
    """Alpaca timestamps carry nanoseconds; Python 3.9 parses at most 6 fractional digits."""
    s = str(ts).replace("Z", "+00:00")
    return re.sub(r"(\.\d{6})\d+", r"\1", s)


def _src(B, d):
    """recorded.json (written by a recorder) or synthetic.json (hand-written fixture)."""
    for name in ("recorded.json", "synthetic.json"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return json.load(open(p))
    return {}


def _today(meta, eq=None, last=None):
    today = dict({"trades": 0, "orders": 0, "planned_loss": 0}, **(meta.get("today") or {}))
    if eq is not None and last is not None:
        # day change includes unrealised P&L; counting a down day as realised is the conservative side
        today.setdefault("realized_pnl", round(min(0.0, eq - last), 2))
    today.setdefault("realized_pnl", 0)
    return today


def _need(d, names, broker, recorder):
    need = [os.path.join(d, f) for f in names]
    if not all(os.path.exists(p) for p in need):
        raise Waiting("no %s responses in %s (run evals/%s, or add synthetic ones)" % (broker, d, recorder))
    return [json.load(open(p)) for p in need]


def alpaca_portfolio(d, meta):
    """portfolio.json from GET /v2/account, /v2/clock and /v2/positions (Alpaca Trading API v2)."""
    A = os.path.join(d, "alpaca")
    acct, clock, pos = _need(A, ("account.json", "clock.json", "positions.json"), "Alpaca paper", "record_alpaca.py")
    base = str(_src("alpaca", A).get("base_url", ""))
    eq, last = float(acct["equity"]), float(acct.get("last_equity") or acct["equity"])
    # cash-style buying power when the account reports it: limits keep margin off
    bp = acct.get("non_marginable_buying_power") or acct["buying_power"]
    return {
        "as_of": _iso(clock["timestamp"]),
        "base_currency": str(acct.get("currency") or "USD").upper(),
        "equity": eq, "buying_power": float(bp),
        # settled cash for the derived margin check (T3): the non-marginable figure, else cash (judgement call)
        "settled_cash": float(acct.get("non_marginable_buying_power") or acct["cash"]),
        # paper is proven by the host the responses came from, not by a field Alpaca returns
        "paper": base == "https://" + PAPER_HOST,
        "clock": {"is_open": clock["is_open"] is True, "next_close": clock.get("next_close"),
                  "source": "alpaca:GET /v2/clock (%s)" % (base or "unknown host"), "as_of": _iso(clock["timestamp"])},
        "positions": [{"symbol": p["symbol"], "side": p.get("side", "long"), "qty": abs(float(p["qty"])),
                       "price": float(p.get("current_price") or p["avg_entry_price"]), "stop": None,
                       "currency": "USD", "multiplier": 1} for p in pos],
        "positions_source": {"source": "alpaca:GET /v2/positions (%s)" % (base or "unknown host"),
                             "as_of": _iso(clock["timestamp"])},
        "today": _today(meta, eq, last),
    }


def _amt(summary, key):
    v = summary.get(key) or {}
    return None if v.get("isNull") or v.get("amount") is None else float(v["amount"])


def ibkr_portfolio(d, meta):
    """portfolio.json from IBKR Client Portal Web API responses:
    GET /portfolio/accounts, /portfolio/{accountId}/summary, /portfolio/{accountId}/positions/0.
    Paper is proven by the account id prefix "DU" (kept through redaction). The Web API has no single
    market-clock call, so the session comes from meta.clock, which must name its source."""
    B = os.path.join(d, "ibkr")
    accts, summ, pos = _need(B, ("accounts.json", "summary.json", "positions.json"), "IBKR paper", "record_ibkr.py")
    src = _src("ibkr", B)
    acct = next((a for a in accts if str(a.get("accountId") or a.get("id", "")).startswith("DU")), accts[0] if accts else {})
    aid = str(acct.get("accountId") or acct.get("id") or "")
    eq = _amt(summ, "netliquidation")
    ccy = str((summ.get("netliquidation") or {}).get("currency") or acct.get("currency") or "").upper()
    # cash-style funds first: limits keep margin off
    bp = _amt(summ, "availablefunds")
    bp = bp if bp is not None else _amt(summ, "buyingpower")
    clk = meta.get("clock") or {}
    return {
        "as_of": meta["now"] if meta.get("now") not in ("from_clock", "from_recorded") else clk.get("as_of"),
        "base_currency": ccy, "equity": eq, "buying_power": bp,
        # settled cash for the derived margin check (T3): settledcash, else totalcashvalue (judgement call;
        # field names from the public docs, not yet checked against a recording)
        "settled_cash": _amt(summ, "settledcash") if _amt(summ, "settledcash") is not None else _amt(summ, "totalcashvalue"),
        "paper": aid.startswith("DU"),
        "clock": {"is_open": clk.get("is_open") is True, "next_close": clk.get("next_close"),
                  "source": clk.get("source"), "as_of": clk.get("as_of")} if clk else None,
        "positions": [{"symbol": str(p.get("ticker") or p.get("contractDesc")), "side": "long" if float(p["position"]) > 0 else "short",
                       "qty": abs(float(p["position"])), "price": float(p["mktPrice"]), "stop": None,
                       "currency": str(p.get("currency") or ccy).upper(), "multiplier": float(p.get("multiplier") or 1)}
                      for p in pos if float(p.get("position") or 0) != 0],
        "positions_source": {"source": "ibkr:GET /portfolio/{accountId}/positions/0", "as_of": clk.get("as_of")},
        "today": _today(meta),
        "_broker_source": src.get("base_url"),
    }


BROKERS = {"alpaca_paper": alpaca_portfolio, "ibkr_paper": ibkr_portfolio}


def _run(args):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = {"_stdout": p.stdout[-500:], "_stderr": p.stderr[-500:]}
    return p.returncode, out


def normalise(x):
    if isinstance(x, dict):
        return {k: normalise(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [normalise(v) for v in x]
    if isinstance(x, str):
        x = NONCE_RE.sub(lambda m: "RC2.%s.%s.%s.<exp>.%s.<rand>.<mac>" % m.groups(), x)
        return re.sub(r"\(expires [^)]*\)", "(expires <exp>)", x)
    return x


def replay(d):
    d = os.path.abspath(d)
    meta = json.load(open(os.path.join(d, "meta.json")))
    rel = lambda k, default=None: (os.path.join(d, meta[k]) if meta.get(k) else default)  # noqa: E731
    work = tempfile.mkdtemp(prefix="repro-")
    gate = os.path.join(work, "gate")
    if os.path.commonpath([os.path.realpath(gate), os.path.realpath(REPO)]) == os.path.realpath(REPO):
        raise SystemExit("refusing: temp gate dir %s is inside the repository" % gate)
    try:
        broker = meta.get("broker")
        if os.path.exists(os.path.join(d, "portfolio.json")):
            pf, source = json.load(open(os.path.join(d, "portfolio.json"))), "portfolio.json"
        elif broker in BROKERS:
            pf, source = BROKERS[broker](d, meta), broker
        else:
            raise ValueError("meta.broker must be one of %s (got %r)" % (", ".join(BROKERS), broker))
        if pf.get("clock") is None:
            pf.pop("clock")
        now = meta["now"]
        if now == "from_clock":
            now = pf["clock"]["as_of"]
        elif now == "from_recorded":  # the recorder's own timestamp (IBKR has no clock call)
            now = _src(broker, os.path.join(d, {"alpaca_paper": "alpaca", "ibkr_paper": "ibkr"}[broker])).get("recorded_at")
            pf["as_of"] = now
        pfp = os.path.join(work, "portfolio.json"); json.dump(pf, open(pfp, "w"), indent=1)
        op = os.path.join(d, "order.json"); order = json.load(open(op))
        limits = rel("limits", os.path.join(SKILL, "assets", "risk-limits.json"))
        rc = [os.path.join(SCRIPTS, "risk_check.py"), "--order", op, "--portfolio", pfp, "--mode", meta.get("mode", "paper"),
              "--limits", limits, "--gate-dir", gate, "--now", now]
        for k in ("contract", "instrument", "bar", "context"):
            if meta.get(k):
                src = rel(k)
                txt = open(src).read()
                if "{NOW}" in txt:  # template for recorded fixtures: stamped with the fixed --now
                    src = os.path.join(work, k + ".json"); open(src, "w").write(txt.replace("{NOW}", now))
                rc += ["--" + k, src]
        if meta.get("override"):
            rc += ["--override", meta["override"]["reason"], "--override-ack", meta["override"]["ack"]]
        rc_exit, rc_out = _run(rc)
        rp = os.path.join(work, "risk.json"); json.dump(rc_out, open(rp, "w"))
        pv = [os.path.join(SCRIPTS, "preview.py"), "--order", op, "--risk", rp, "--config", rel("config", DEFAULT_CONFIG),
              "--server", meta.get("server", "alpaca"), "--limits", limits, "--gate-dir", gate, "--now", now, "--json"]
        if meta.get("lock"):
            pv += ["--lock", rel("lock")]
        if meta.get("allow_override"):
            pv.append("--allow-override")
        pv_exit, pv_out = _run(pv)
        fill = None
        if pv_exit == 0 and pv_out.get("gate") == "OPEN":
            px = order.get("limit_price") or order.get("est_price")
            fill = {"simulated": True, "status": "filled", "client_order_id": order.get("client_order_id"),
                    "symbol": order.get("symbol"), "side": order.get("side"), "qty": order.get("qty"),
                    "filled_qty": order.get("qty"), "filled_avg_price": px, "type": order.get("type", "limit"),
                    "time_in_force": order.get("time_in_force", "day"), "filled_at": now}
        return normalise({"fixture": os.path.basename(d), "synthetic": meta.get("synthetic"),
                          "broker": broker, "portfolio_source": source, "now": now, "portfolio": pf,
                          "risk_check": {"exit": rc_exit, "out": rc_out},
                          "preview": {"exit": pv_exit, "out": pv_out}, "fill": fill})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def diff(a, b, path="$"):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return [f"{path}: {b!r} != expected {a!r}"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in b:
                out.append(f"{path}.{k}: missing (expected {a[k]!r})")
            elif k not in a:
                out.append(f"{path}.{k}: unexpected {b[k]!r}")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: length {len(b)} != expected {len(a)}"]
        return [x for i, (p, q) in enumerate(zip(a, b)) for x in diff(p, q, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {b!r} != expected {a!r}"]


def fixtures_under(root):
    return sorted(os.path.dirname(p) for p in (os.path.join(r, "meta.json") for r, _, f in os.walk(root) if "meta.json" in f))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fixtures", nargs="*")
    ap.add_argument("--all", nargs="?", const=DEFAULT_ROOT, help="run every fixture under this root")
    ap.add_argument("--bless", action="store_true", help="write expected.json from this run")
    ap.add_argument("--require-recorded", action="store_true")
    a = ap.parse_args()
    dirs = list(a.fixtures) + (fixtures_under(a.all) if a.all else [])
    if not dirs:
        ap.error("give a fixture dir or --all")
    bad = 0
    for d in dirs:
        name = os.path.relpath(d, DEFAULT_ROOT) if os.path.abspath(d).startswith(DEFAULT_ROOT) else d
        try:
            got = replay(d)
        except Waiting as w:
            print(("FAIL  " if a.require_recorded else "skip  ") + f"{name}: {w}")
            bad += a.require_recorded
            continue
        except (OSError, ValueError, KeyError) as e:
            print(f"FAIL  {name}: {type(e).__name__}: {e}"); bad += 1; continue
        exp_p = os.path.join(d, "expected.json")
        if a.bless:
            json.dump(got, open(exp_p, "w"), indent=1, sort_keys=True); open(exp_p, "a").write("\n")
            print(f"bless {name}: wrote expected.json (verdict {got['risk_check']['out'].get('verdict')}, "
                  f"preview {got['preview']['out'].get('gate')})"); continue
        if not os.path.exists(exp_p):
            print(f"FAIL  {name}: no expected.json (run with --bless after reviewing the output)"); bad += 1; continue
        why = diff(json.load(open(exp_p)), got)
        tag = " [SYNTHETIC]" if got.get("synthetic") else " [recorded]"
        print(("ok    " if not why else "FAIL  ") + name + tag + ("" if not why else "\n      " + "\n      ".join(why[:20])))
        bad += bool(why)
    print(f"{len(dirs) - bad}/{len(dirs)} repro fixtures ok" + (" (skips count as ok)" if not a.require_recorded else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
