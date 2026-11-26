#!/usr/bin/env python3
"""Portfolio-aware position sizing. The model never sizes; this does. Stdlib only, no network.
Shared, byte-identical, by trading-research and trading-execution. risk_check.py calls size().

Usage
  position_size.py --symbol AAPL --entry 190 --stop 185 [--side long|short] [--target 205]
                   [--risk-pct 2 | --risk-amount 400] --portfolio portfolio.json
                   [--instrument instrument.json] [--asset-class equity|etf|crypto|option]
                   [--limits ../assets/risk-limits.json] [--size-multiplier 1.0]

portfolio.json (from the broker MCP server; base currency is the account's):
  {"as_of": "...", "base_currency": "USD", "equity": 25000, "buying_power": 20000, "paper": true,
   "fx": {"CADUSD": {"rate": 0.712, "as_of": "...", "source": "boc:valet FXCADUSD"}},   # base per 1 unit
   "positions": [{"symbol": "MSFT", "side": "long", "qty": 10, "price": 410, "stop": 395,
                  "multiplier": 1, "currency": "USD", "cluster": "us_megacap_tech"}],
   "correlations": {"AAPL|MSFT": 0.78},          # optional; |rho| >= limits cluster_corr joins a cluster
   "today": {"trades": 1, "orders": 2, "realized_pnl": -40, "planned_loss": 25}}
instrument.json (optional; defaults come from limits.instrument_defaults[asset_class]):
  {"asset_class": "equity", "currency": "USD", "multiplier": 1, "lot_step": 1, "min_qty": 1, "session": "exchange" | "24x7",
   "gap_pct": 0.05, "cluster": "us_megacap_tech"}
  Fractional shares: lot_step 0.001 (or the broker's increment). Crypto: lot_step 0.000001, session 24x7.
  Only the keys in INSTRUMENT_KEYS are accepted (T4). multiplier and session are fixed by the asset class
  (1 and "exchange" for equity/etf, 1 and "24x7" for crypto, 100 for options) and may only be restated;
  gap_pct may raise the class default, never lower it, and stays <= 1; lot_step and min_qty must be finite
  and within [1e-9, 1e6]. Anything else refuses (exit 2).
  Options (long premium only): entry = premium per share, stop ignored, risk = premium x multiplier.
  Asset class: the instrument spec's asset_class, checked against the symbol's shape (OCC option symbol,
  BASE/QUOTE crypto pair, exchange ticker) and the order's label; any disagreement refuses. etf needs a
  spec saying etf. An exchange ticker with no label is equity.

Constraints, each a maximum quantity; the smallest binds and is named:
  risk_per_trade   R / r                         R = min(limit %, limit amount, requested) x size_multiplier
  gap              gap_loss_multiple x R / g     g = (|entry-stop| + entry x gap_pct) x mult x fx
  portfolio_heat   (equity x max_heat% - open risk) / r
  cluster          (equity x max_cluster% - open risk in the same cluster or |rho| >= cluster_corr) / r
  daily_loss       (daily limit - planned - realized losses today) / r
  position         (equity x max_position% - notional already held in this symbol) / n
  order            max_order / n
  buying_power     buying_power x (1 - cash_buffer%) / n
  r = (|entry - stop| + entry x stop_slippage_bps/1e4) x multiplier x fx     (risk per unit, base ccy)
  n = entry x multiplier x fx                                                (notional per unit)
Open risk of a position = |price - stop| x qty x mult x fx; a position with no stop counts its full
notional. Quantity is floored to lot_step. A request above a risk limit refuses (it is never silently cut).
Exit 0 when qty >= min_qty, 1 when sizing refuses, 2 on bad input.
"""
from __future__ import annotations

import argparse, json, math, os, re, sys
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LIMITS = os.path.join(HERE, "..", "assets", "risk-limits.json")
BUILTIN_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "equity": {"multiplier": 1, "lot_step": 1, "min_qty": 1, "session": "exchange", "gap_pct": 0.05},
    "etf": {"multiplier": 1, "lot_step": 1, "min_qty": 1, "session": "exchange", "gap_pct": 0.03},
    "crypto": {"multiplier": 1, "lot_step": 0.000001, "min_qty": 0.000001, "session": "24x7", "gap_pct": 0.10},
    "option": {"multiplier": 100, "lot_step": 1, "min_qty": 1, "session": "exchange", "gap_pct": 0.0},
}


class SizingError(ValueError):
    """Bad or missing input: sizing refuses rather than guessing."""


# OCC option symbol: root (1-6, adjusted roots may carry a digit) + yymmdd + C|P + strike x 1000 (8 digits)
OCC_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,5}\d{6}[CP]\d{8}$")


def symbol_class(symbol: str) -> Optional[str]:
    """What the symbol's own shape proves: option (OCC), crypto (BASE/QUOTE), or None (an exchange ticker)."""
    s = str(symbol).upper().replace(" ", "")
    if OCC_SYMBOL.match(s):
        return "option"
    if "/" in s:
        return "crypto"
    return None


def resolve_asset_class(symbol: str, declared: Optional[str], instrument: Optional[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """Asset class from the instrument spec and the symbol, never from the order's label alone (T1).
    Returns (asset_class, problems); any problem is a HARD fail in risk_check."""
    spec_ac = (instrument or {}).get("asset_class")
    shape = symbol_class(symbol)
    problems: List[str] = []
    for name, v in (("order", declared), ("instrument spec", spec_ac)):
        if v is not None and v not in BUILTIN_DEFAULTS:
            problems.append(f"{name} asset_class {v!r} unknown; use one of {', '.join(sorted(BUILTIN_DEFAULTS))}")
    if declared is not None and spec_ac is not None and declared != spec_ac:
        problems.append(f"order says asset_class {declared} but the instrument spec says {spec_ac}")
    ac = str(spec_ac or declared or shape or "equity")
    if shape == "option" and ac != "option":
        problems.append(f"{symbol} is an OCC option symbol but is labelled {ac}")
    elif shape == "crypto" and ac != "crypto":
        problems.append(f"{symbol} is a BASE/QUOTE crypto pair but is labelled {ac}")
    elif shape is None and ac in ("option", "crypto"):
        problems.append(f"{ac} needs {'an OCC option' if ac == 'option' else 'a BASE/QUOTE crypto'} symbol; "
                        f"{symbol} is an exchange ticker")
    if ac == "etf" and spec_ac != "etf":
        problems.append("etf lowers the default gap: it needs an instrument spec with asset_class etf")
    m = (instrument or {}).get("multiplier")
    try:
        m100 = m is not None and float(m) == 100
    except (TypeError, ValueError):
        m100 = False
    if m100 and ac != "option":
        problems.append(f"{ac}-labelled order with multiplier 100: that is an option contract, label and size it as one")
    return ac, problems


def limit_money(L: Dict[str, Any], key: str, base: str) -> Optional[float]:
    """A money limit in the base currency. Legacy *_usd keys count only when the base is USD."""
    if key in L:
        return float(L[key])
    if key + "_usd" in L:
        if base != "USD":
            raise SizingError(f"limit {key}_usd is in USD but the account base is {base}: set {key}")
        return float(L[key + "_usd"])
    return None


def fx_rate(portfolio: Dict[str, Any], ccy: str, base: str) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Base units per 1 unit of ccy. Refuses when the rate is not recorded with a source and time."""
    if ccy == base:
        return 1.0, None
    fx = (portfolio.get("fx") or {}).get(ccy + base)
    if not fx or not fx.get("rate") or not fx.get("as_of") or not fx.get("source"):
        raise SizingError(f"need fx {ccy}{base} with rate, as_of and source in the portfolio")
    return float(fx["rate"]), fx


def floor_step(x: float, step: float) -> float:
    if x <= 0:
        return 0.0
    s = Decimal(str(step))
    return float((Decimal(repr(x)) / s).to_integral_value(rounding=ROUND_FLOOR) * s)


class InstrumentError(SizingError):
    """An instrument spec (caller file or limits default) that tries to change what the asset class fixes."""


# T4: the keys an instrument.json may carry. multiplier and session are fixed by the asset class: they may be
# stated only with the class's own value. gap_pct may only be raised; lot_step and min_qty are range-checked.
INSTRUMENT_KEYS = {"asset_class", "symbol", "name", "exchange", "conid", "source", "as_of", "currency", "lot_step",
                   "min_qty", "gap_pct", "cluster", "multiplier", "session"}
LIMIT_DEFAULT_KEYS = {"multiplier", "lot_step", "min_qty", "gap_pct", "session"}
FIXED_KEYS = ("multiplier", "session")
STEP_RANGE = (1e-9, 1e6)


def _num(spec: Dict[str, Any], k: str, where: str) -> float:
    try:
        v = float(spec[k])
    except (TypeError, ValueError, KeyError):
        raise InstrumentError(f"{where} {k} must be a number")
    if not math.isfinite(v):
        raise InstrumentError(f"{where} {k} must be finite (got {spec[k]!r})")
    return v


def instrument_spec(L: Dict[str, Any], asset_class: str, given: Optional[Dict[str, Any]], base: str) -> Dict[str, Any]:
    spec = dict(BUILTIN_DEFAULTS.get(asset_class) or {})
    if not spec:
        raise SizingError(f"unknown asset_class {asset_class!r}")
    lim_def = dict((L.get("instrument_defaults") or {}).get(asset_class, {}))
    bad = sorted(k for k in set(lim_def) - LIMIT_DEFAULT_KEYS if not str(k).startswith("_"))
    if bad:
        raise InstrumentError(f"limits instrument_defaults.{asset_class} keys not allowed: {', '.join(bad)}")
    if "session" in lim_def and lim_def["session"] != spec["session"]:
        raise InstrumentError(f"limits instrument_defaults.{asset_class}.session cannot change the "
                              f"{asset_class} session ({spec['session']})")
    spec.update({k: v for k, v in lim_def.items() if not str(k).startswith("_")})
    gap_floor = _num(spec, "gap_pct", "limits instrument_defaults")
    if not 0 <= gap_floor <= 1:
        raise InstrumentError(f"limits instrument_defaults.{asset_class}.gap_pct must be in [0, 1]")
    g = {k: v for k, v in (given or {}).items() if not str(k).startswith("_")}
    bad = sorted(set(g) - INSTRUMENT_KEYS)
    if bad:
        raise InstrumentError(f"instrument keys not allowed: {', '.join(bad)} (allowed: {', '.join(sorted(INSTRUMENT_KEYS))})")
    for k in FIXED_KEYS:
        if k in g:
            same = g[k] == spec[k] if k == "session" else (
                isinstance(g[k], (int, float)) and not isinstance(g[k], bool) and float(g[k]) == float(spec[k]))
            if not same:
                raise InstrumentError(f"instrument {k} {g[k]!r} cannot override the {asset_class} value {spec[k]!r}")
    spec.update(g)
    spec.setdefault("currency", base)
    m = _num(spec, "multiplier", "instrument")
    if (asset_class != "option" and m != 1) or not 0 < m <= 1000:
        raise InstrumentError(f"instrument multiplier {m:g} is out of range for {asset_class} "
                              f"({'1' if asset_class != 'option' else '(0, 1000]'})")
    gap = _num(spec, "gap_pct", "instrument")
    if not gap_floor <= gap <= 1:
        raise InstrumentError(f"instrument gap_pct {gap:g} must be in [{gap_floor:g}, 1]: it may raise the "
                              f"{asset_class} default, never lower it")
    for k in ("lot_step", "min_qty"):
        v = _num(spec, k, "instrument")
        if not STEP_RANGE[0] <= v <= STEP_RANGE[1]:
            raise InstrumentError(f"instrument {k} {v:g} must be in [{STEP_RANGE[0]:g}, {STEP_RANGE[1]:g}]")
    if not (isinstance(spec["currency"], str) and len(spec["currency"]) == 3 and spec["currency"].isalpha()):
        raise InstrumentError("instrument currency must be a 3-letter ISO code")
    return spec


def position_risk(p: Dict[str, Any], portfolio: Dict[str, Any], base: str) -> Tuple[float, float]:
    """(open risk, notional) of one held position in the base currency."""
    fx, _ = fx_rate(portfolio, p.get("currency", base), base)
    m = float(p.get("multiplier", 1)); q = abs(float(p["qty"])); px = float(p["price"])
    notional = q * px * m * fx
    if p.get("stop") is None:
        return notional, notional
    return abs(px - float(p["stop"])) * q * m * fx, notional


def correlated(sym: str, other: str, portfolio: Dict[str, Any], thr: float) -> bool:
    c = portfolio.get("correlations") or {}
    rho = c.get(f"{sym}|{other}", c.get(f"{other}|{sym}"))
    return rho is not None and abs(float(rho)) >= thr


def size(symbol: str, side: str, entry: float, stop: Optional[float], portfolio: Dict[str, Any],
         limits: Dict[str, Any], asset_class: str = "equity", instrument: Optional[Dict[str, Any]] = None,
         risk_pct: Optional[float] = None, risk_amount: Optional[float] = None, target: Optional[float] = None,
         size_multiplier: float = 1.0) -> Dict[str, Any]:
    """Pure: returns {"ok", "qty", "binding_constraint", "constraints", ...}. Raises SizingError on bad input."""
    L, sym = limits, symbol.upper()
    base = str(portfolio.get("base_currency") or L.get("base_currency") or "").upper()
    if not base:
        raise SizingError("portfolio.base_currency is required")
    equity = portfolio.get("equity")
    if equity is None or float(equity) <= 0:
        raise SizingError("portfolio.equity is required and must be > 0")
    equity = float(equity)
    if side not in ("long", "short"):
        raise SizingError("side must be long or short")
    if entry is None or entry <= 0:
        raise SizingError("entry must be > 0")
    spec = instrument_spec(L, asset_class, instrument, base)
    fx, fx_used = fx_rate(portfolio, str(spec["currency"]).upper(), base)
    m = float(spec["multiplier"])
    reasons: List[str] = []
    if asset_class == "option":
        if side != "long":
            raise SizingError("options: long premium only (defined risk)")
        dist = entry  # premium is the most a long option can lose
    else:
        if stop is None:
            raise SizingError("a stop is required to size by risk")
        dist = (entry - stop) if side == "long" else (stop - entry)
        if dist <= 0:
            raise SizingError(f"stop must be on the losing side of entry for a {side}")
    slip = 0.0 if asset_class == "option" else entry * float(L.get("stop_slippage_bps", 10)) / 1e4
    r = (dist + slip) * m * fx
    n = entry * m * fx
    gap_pct = float(spec.get("gap_pct", 0))
    g = (dist + entry * gap_pct) * m * fx if asset_class != "option" else r

    pct_cap = float(L.get("max_risk_per_trade_pct", 1.0))
    amt_cap = limit_money(L, "max_loss_per_trade", base)
    asks = {"limit_pct": equity * pct_cap / 100}
    if amt_cap is not None:
        asks["limit_amount"] = amt_cap
    if risk_pct is not None:
        if risk_pct <= 0:
            raise SizingError("risk_pct must be > 0")
        asks["requested_pct"] = equity * risk_pct / 100
        if risk_pct > pct_cap:
            reasons.append(f"requested {risk_pct}% risk exceeds max_risk_per_trade_pct {pct_cap}%")
    if risk_amount is not None:
        if risk_amount <= 0:
            raise SizingError("risk_amount must be > 0")
        asks["requested_amount"] = risk_amount
        if amt_cap is not None and risk_amount > amt_cap:
            reasons.append(f"requested risk {risk_amount} {base} exceeds max_loss_per_trade {amt_cap}")
    R = min(asks.values()) * max(0.0, min(1.0, size_multiplier))

    held = [p for p in portfolio.get("positions", []) if abs(float(p.get("qty", 0))) > 0]
    risks = {i: position_risk(p, portfolio, base) for i, p in enumerate(held)}
    open_risk = sum(v[0] for v in risks.values())
    thr = float(L.get("cluster_corr", 0.7))
    cl = spec.get("cluster")
    in_cluster = [i for i, p in enumerate(held) if p["symbol"].upper() != sym and (
        (cl and p.get("cluster") == cl) or correlated(sym, p["symbol"].upper(), portfolio, thr))]
    same = [i for i, p in enumerate(held) if p["symbol"].upper() == sym]
    cluster_risk = sum(risks[i][0] for i in in_cluster + same)
    held_notional = sum(risks[i][1] for i in same)
    today = portfolio.get("today") or {}
    daily_cap = limit_money(L, "max_daily_loss", base)
    if daily_cap is None:
        daily_cap = equity * float(L.get("max_daily_loss_pct", 3.0)) / 100
    used_today = float(today.get("planned_loss", 0)) + max(0.0, -float(today.get("realized_pnl", 0)))
    bp = portfolio.get("buying_power")

    C: Dict[str, float] = {
        "risk_per_trade": R / r,
        "gap": float(L.get("gap_loss_multiple", 2.0)) * R / g if g > 0 else math.inf,
        "portfolio_heat": (equity * float(L.get("max_portfolio_heat_pct", 6.0)) / 100 - open_risk) / r,
        "cluster": (equity * float(L.get("max_cluster_risk_pct", 3.0)) / 100 - cluster_risk) / r,
        "daily_loss": (daily_cap - used_today) / r,
        "position": (equity * float(L.get("max_position_pct", 25)) / 100 - held_notional) / n,
    }
    max_order = limit_money(L, "max_order", base)
    if max_order is not None:
        C["order"] = max_order / n
    if bp is None:
        raise SizingError("portfolio.buying_power is required")
    C["buying_power"] = float(bp) * (1 - float(L.get("cash_buffer_pct", 0)) / 100) / n
    step, min_q = float(spec["lot_step"]), float(spec["min_qty"])
    binding = min(C, key=C.get)
    qty = floor_step(max(0.0, C[binding]), step)
    ok = qty >= min_q and not reasons
    if qty < min_q:
        reasons.append(f"{binding} leaves {qty} < min_qty {min_q}")
    min_order = limit_money(L, "min_order", base)
    if ok and min_order is not None and qty * n < min_order:
        ok = False; reasons.append(f"notional {qty * n:.2f} {base} below min_order {min_order}")
    res: Dict[str, Any] = {
        "ok": ok, "symbol": sym, "side": side, "asset_class": asset_class, "qty": qty,
        "binding_constraint": binding,
        "constraints": {k: (floor_step(v, step) if v > 0 and math.isfinite(v) else (0.0 if v <= 0 else None))
                        for k, v in C.items()},
        "risk_budget": round(R, 2), "risk_per_unit": round(r, 6), "notional_per_unit": round(n, 6),
        "dollar_risk": round(qty * r, 2), "gap_loss": round(qty * g, 2), "notional": round(qty * n, 2),
        "base_currency": base, "instrument_currency": spec["currency"], "fx": fx, "fx_source": fx_used,
        "multiplier": m, "lot_step": step, "session": spec["session"],
        "open_risk_before": round(open_risk, 2), "heat_after_pct": round((open_risk + qty * r) / equity * 100, 3),
        "cluster_members": [held[i]["symbol"] for i in in_cluster], "reasons": reasons,
    }
    if target is not None:
        reward = (target - entry) if side == "long" else (entry - target)
        rr = reward / dist if dist else 0.0
        cost_r = slip / dist if dist else 0.0
        res["reward_risk"] = round(rr, 3)
        res["breakeven_win_rate"] = round((1 + cost_r) / (1 + rr), 4) if rr > 0 else None
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True); ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float); ap.add_argument("--target", type=float)
    ap.add_argument("--side", choices=["long", "short"], default="long")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--risk-pct", type=float); g.add_argument("--risk-amount", type=float)
    ap.add_argument("--portfolio", required=True); ap.add_argument("--instrument")
    ap.add_argument("--asset-class", choices=sorted(BUILTIN_DEFAULTS),
                    help="optional: derived from --instrument's asset_class and the symbol; a disagreement refuses")
    ap.add_argument("--limits", default=DEFAULT_LIMITS)
    ap.add_argument("--size-multiplier", type=float, default=1.0)
    a = ap.parse_args()
    try:
        inst = json.load(open(a.instrument)) if a.instrument else None
        ac, problems = resolve_asset_class(a.symbol, a.asset_class, inst)
        if problems:
            raise SizingError("; ".join(problems))
        res = size(a.symbol, a.side, a.entry, a.stop, json.load(open(a.portfolio)), json.load(open(a.limits)),
                   ac, inst,
                   a.risk_pct, a.risk_amount, a.target, a.size_multiplier)
    except (SizingError, KeyError, ValueError, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2)); sys.exit(2)
    print(json.dumps(res, indent=2)); sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
