#!/usr/bin/env python3
"""Order preview: the last step before an order tool is called (trade-execute). Stdlib only, no network.
Resolves PAPER or LIVE from the broker MCP config itself, echoes and verifies the risk_check nonce for
this exact order and mode, and prints a preview whose FIRST LINE states the mode. Show the whole preview
to the user verbatim. Exit 0 = gate OPEN, the order may be sent after the user's explicit yes (or a
mandate AUTO_OK); exit 1 = do not send; exit 2 = bad input.

Usage: preview.py --order order.json --risk risk_result.json --config mcp-config.json [--server alpaca]
                  [--lock ../assets/mcp-lock.json] [--limits ../assets/risk-limits.json] [--gate-dir D]
                  [--allow-override] [--json] [--now ISO]
       (--nonce N may replace --risk; the risk result adds sizing lines and must carry the same nonce.)

Layout follows reddygopalkrishna/trading-skills (MIT) md_preview: mode header, the order line,
estimated notional, purpose, stop handling, the confirmation handle and its expiry. The gate is ours.

Mode rules (checked against alpaca-mcp-server 2.4.1, server.py _get_trading_base_url):
  Alpaca  paper base URL https://paper-api.alpaca.markets when ALPACA_PAPER_TRADE lower-cased is "true",
          "1" or "yes"; https://api.alpaca.markets (LIVE) for ANY other value, so "ture" or "paper" trades
          live. Accepted here: only the literal "true" (PAPER) or "false" (LIVE). Missing, a ${VAR}
          placeholder or anything else is refused, even though the server's own default is paper.
  Others  Questrade, IBKR and any server without a "mode" in mcp-lock.json are LIVE.
"""
from __future__ import annotations

import argparse, json, os, sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gate import GateDirError, parse, resolve_gate_dir, verify  # noqa: E402

ALPACA_URL = {"paper": "https://paper-api.alpaca.markets", "live": "https://api.alpaca.markets"}


def resolve_mode(cfg: Dict[str, Any], server: str, lock: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], List[str]]:
    s = (cfg.get("mcpServers") or {}).get(server)
    if s is None:
        return None, None, [f"server {server!r} not in the MCP config"]
    blob = " ".join([str(s.get("command", ""))] + [str(x) for x in s.get("args", [])] + [str(s.get("url", ""))])
    if "alpaca-mcp-server" in blob or "alpaca_mcp_server" in blob:
        v = (s.get("env") or {}).get("ALPACA_PAPER_TRADE")
        if v == "true":
            return "paper", ALPACA_URL["paper"], []
        if v == "false":
            return "live", ALPACA_URL["live"], []
        return None, None, ["ALPACA_PAPER_TRADE is %r: set the literal \"true\" (paper) or \"false\" (live). "
                            "alpaca-mcp-server treats any value other than true/1/yes as LIVE" % (v,)]
    entry = ((lock or {}).get("servers") or {}).get(server, {})
    m = entry.get("mode", "live")
    return (m if m in ("paper", "live") else "live"), s.get("url") or entry.get("url") or blob.strip(), []


def render(o: Dict[str, Any], mode: Optional[str], url: Optional[str], nonce: str, t: Optional[Dict[str, str]],
           risk: Optional[Dict[str, Any]], why: List[str]) -> List[str]:
    head = ("MODE: PAPER, simulated fills, " + str(url)) if mode == "paper" else (
        ("MODE: LIVE, REAL MONEY, " + str(url)) if mode == "live" else "MODE: UNKNOWN, order refused")
    px = o.get("limit_price") or o.get("est_price")
    parts = ["%s %s %s" % (str(o.get("side", "")).upper(), o.get("qty"), str(o.get("symbol", "")).upper()),
             "%s%s" % (o.get("type", "limit"), f" @ {px}" if px else ""),
             f"stop {o['stop_price']}" if o.get("stop_price") is not None else "no stop",
             f"target {o['target_price']}" if o.get("target_price") is not None else None,
             str(o.get("time_in_force", "day"))]
    lines = [head, "Order: " + " | ".join(p for p in parts if p)]
    sz = (risk or {}).get("sizing") or {}
    if sz:
        lines.append("Estimated notional %s %s; risk to stop %s %s; gap loss %s %s; binding: %s" % (
            round(float(o["qty"]) * float(sz.get("notional_per_unit", 0)), 2), sz.get("base_currency"),
            round(float(o["qty"]) * float(sz.get("risk_per_unit", 0)), 2), sz.get("base_currency"),
            round(float(o["qty"]) * float(sz.get("gap_loss", 0)) / max(float(sz.get("qty") or 1), 1e-12), 2),
            sz.get("base_currency"), sz.get("binding_constraint")))
    elif px:
        lines.append("Estimated notional %s (ref price %s)" % (round(float(px) * float(o.get("qty", 0)), 2), px))
    lines.append("Purpose: " + ("close or reduce an existing position" if o.get("is_exit") else "open position"))
    if o.get("stop_price") is not None and not o.get("is_exit"):
        lines.append("Stop: sent as a bracket leg" if o.get("order_class") in ("bracket", "oto") else
                     "Stop: NOT attached to this order; place the stop order right after the fill")
    lines.append("client_order_id: %s" % o.get("client_order_id", "MISSING"))
    exp = datetime.fromtimestamp(int(t["exp"])).astimezone().isoformat(timespec="seconds") if t else "n/a"
    lines.append("Nonce: %s (expires %s)" % (nonce, exp))
    if t and t.get("verdict") == "OVERRIDE":
        lines.insert(1, "RISK GATE OVERRIDDEN by the user (logged in overrides.jsonl)")
    lines.append("Gate: " + ("OPEN. Send only after the user's explicit yes for this exact order." if not why else "CLOSED"))
    lines += ["Refused: " + r for r in why]
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--order", required=True); ap.add_argument("--risk"); ap.add_argument("--nonce")
    ap.add_argument("--config", required=True); ap.add_argument("--server", default="alpaca")
    ap.add_argument("--lock", default=os.path.join(HERE, "..", "assets", "mcp-lock.json"))
    ap.add_argument("--limits", default=os.path.join(HERE, "..", "assets", "risk-limits.json"))
    ap.add_argument("--gate-dir"); ap.add_argument("--allow-override", action="store_true")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--now")
    a = ap.parse_args()
    try:
        o = json.load(open(a.order)); cfg = json.load(open(a.config))
        risk = json.load(open(a.risk)) if a.risk else None
        lock = json.load(open(a.lock)) if a.lock and os.path.exists(a.lock) else None
    except (OSError, ValueError) as e:
        print(json.dumps({"gate": "CLOSED", "error": f"bad input: {e}"})); sys.exit(2)
    try:
        gd = resolve_gate_dir(a.gate_dir)  # T7
    except GateDirError as e:
        print(json.dumps({"gate": "CLOSED", "gate_dir": None, "error": str(e), "reasons": [str(e)]})); sys.exit(2)
    nonce = (a.nonce or (risk or {}).get("nonce") or "").strip()
    why: List[str] = []
    if not nonce:
        why.append("no nonce: run risk_check.py and pass its result with --risk")
    if a.nonce and risk and risk.get("nonce") and risk["nonce"].strip() != a.nonce.strip():
        why.append("--nonce differs from the nonce in --risk")
    mode, url, mwhy = resolve_mode(cfg, a.server, lock)
    why += mwhy
    if mode and "paper" in o and (o["paper"] is True) != (mode == "paper"):
        why.append("order is marked %s but the config sends it to %s" % ("paper" if o["paper"] else "live", mode.upper()))
    if not o.get("client_order_id"):
        why.append("order has no client_order_id")
    t = parse(nonce) if nonce else None
    if mode and nonce:
        ok, gw, t = verify(nonce, o, mode, a.limits, gd, a.allow_override, a.now, consume=not why)
        why += gw
    lines = render(o, mode, url, nonce or "MISSING", t, risk, why)
    res = {"mode": mode or "unknown", "endpoint": url, "gate": "OPEN" if not why else "CLOSED",
           "override": bool(t and t.get("verdict") == "OVERRIDE"), "nonce": nonce or None,
           "preview_first_line": lines[0], "preview": lines, "reasons": why, "gate_dir": gd}
    print(json.dumps(res, indent=2) if a.json else "\n".join(lines))
    sys.exit(0 if not why else 1)


if __name__ == "__main__":
    main()
