#!/usr/bin/env python3
"""Risk-gate nonces. risk_check.py issues one per check; the execution step must echo it back.
Stdlib only, no network. Shared, byte-identical, by trading-research and trading-execution.

Nonce (one line, dot-separated):
  RC2.<VERDICT>.<fingerprint>.<mode>.<expires_epoch>.<limits_sha8>.<rand>.<mac>
  VERDICT  PASS | FAIL | OVERRIDE
  mode     paper | live | unknown   (unknown never opens)
  mac      HMAC-SHA256 over everything before it, keyed by <gate_dir>/gate.key (created 0600 on first use)
fingerprint = sha256 of the whole order JSON (sorted keys; keys starting with "_" ignored), first 16 hex.
Any change to the order after the check (account, time in force, legs, qty, price) closes the gate.

Commands
  gate.py verify --nonce N --order order.json --mode paper|live [--limits L] [--gate-dir D]
                 [--allow-override] [--no-consume] [--now ISO]
      OPEN only if: mac valid, issued here (gate-log.jsonl), unused, not expired (by --now AND by this
      machine's clock since issue: a rewound --now cannot reopen a nonce; TTL capped at 300 s), fingerprint equals this
      order, limits file unchanged, mode equals --mode, verdict PASS (or OVERRIDE with --allow-override).
      A successful verify marks the nonce used unless --no-consume (one order, one nonce).
  gate.py log [--gate-dir D]     print every override

Overrides are made by risk_check.py --override "reason" --override-ack "<OVERRIDE_ACK>": paper only,
soft reasons only, appended to overrides.jsonl with the reasons they overrode.

Gate dir: --gate-dir, else $TRADING_GATE_DIR, else ~/.trading-gate. Keep it outside the skill folder.
Limit: this stops skipped steps and orders edited after the check. It does not stop an agent that can
read gate.key and forge a nonce, or one that calls the broker tool directly. Broker-side controls
(paper keys, the client's per-call permission, Questrade Push Approval) remain the outer wall.
"""
from __future__ import annotations

import argparse, hashlib, hmac, json, os, secrets, sys, time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

OVERRIDE_ACK = "I override the risk gate for this order and accept the loss"
DEFAULT_TTL = 300
MAX_TTL = 300  # nonces live at most 5 minutes, whatever the limits file says
VERSION = "RC2"


def fingerprint(order: Dict[str, Any]) -> str:
    body = json.dumps({k: v for k, v in order.items() if not str(k).startswith("_")}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def gate_dir(d: Optional[str] = None) -> str:
    d = d or os.environ.get("TRADING_GATE_DIR") or os.path.join(os.path.expanduser("~"), ".trading-gate")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _key(d: str) -> bytes:
    p = os.path.join(d, "gate.key")
    if not os.path.exists(p):
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return open(p).read().strip().encode()


def file_sha8(path: Optional[str]) -> str:
    if not path or not os.path.exists(path):
        return "nolimits"
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:8]


def _mac(key: bytes, body: str) -> str:
    return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()[:32]


def _now(now: Any = None) -> float:
    if now is None:
        return time.time()
    if isinstance(now, (int, float)):
        return float(now)
    if isinstance(now, datetime):
        return now.timestamp()
    return datetime.fromisoformat(str(now)).timestamp()


def _append(d: str, name: str, row: Dict[str, Any]) -> None:
    with open(os.path.join(d, name), "a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _log(d: str) -> List[Dict[str, Any]]:
    p = os.path.join(d, "gate-log.jsonl")
    return [json.loads(x) for x in open(p)] if os.path.exists(p) else []


def issue(verdict: str, fp: str, mode: Optional[str], limits_path: Optional[str], reasons: Sequence[str] = (),
          warnings: Sequence[str] = (), d: Optional[str] = None, ttl: int = DEFAULT_TTL, now: Any = None,
          extra: Optional[Dict[str, Any]] = None) -> str:
    if verdict not in ("PASS", "FAIL", "OVERRIDE"):
        raise ValueError("verdict must be PASS, FAIL or OVERRIDE")
    d = gate_dir(d)
    mode = mode if mode in ("paper", "live") else "unknown"
    ttl = max(1, min(int(ttl), MAX_TTL))
    exp = int(_now(now)) + ttl
    body = ".".join([VERSION, verdict, fp, mode, str(exp), file_sha8(limits_path), secrets.token_hex(4)])
    tok = body + "." + _mac(_key(d), body)
    _append(d, "gate-log.jsonl", dict(event="issued", nonce=tok, verdict=verdict, fingerprint=fp, mode=mode,
                                      expires=exp, ttl=ttl, wall=round(time.time(), 3),
                                      reasons=list(reasons), warnings=list(warnings), **(extra or {})))
    if verdict == "OVERRIDE":
        _append(d, "overrides.jsonl", dict(nonce=tok, fingerprint=fp, mode=mode, at=int(_now(now)), **(extra or {})))
    return tok


def sign_obj(obj: Dict[str, Any], d: Optional[str] = None, tag: str = "MS1") -> str:
    """HMAC, with the gate key, over a JSON object minus its "mac" / "signature" fields (mandates, reconcile
    stamps). Editing any other field afterwards makes check_obj fail."""
    body = json.dumps({k: v for k, v in obj.items() if k not in ("mac", "signature")}, sort_keys=True,
                      separators=(",", ":"))
    return tag + "." + _mac(_key(gate_dir(d)), tag + "|" + body)


def check_obj(obj: Dict[str, Any], field: str, d: Optional[str] = None, tag: str = "MS1") -> bool:
    return hmac.compare_digest(sign_obj(obj, d, tag), str(obj.get(field, "")))


def issued_row(tok: str, d: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The gate log's own record of an issued nonce (what risk_check saw), or None."""
    tok = str(tok).strip()
    return next((r for r in _log(gate_dir(d)) if r.get("nonce") == tok and r.get("event") == "issued"), None)


def parse(tok: str) -> Optional[Dict[str, str]]:
    p = str(tok).strip().split(".")
    if len(p) != 8 or p[0] != VERSION:
        return None
    return dict(zip(["v", "verdict", "fp", "mode", "exp", "lim", "rand", "mac"], p))


def verify(tok: str, order: Dict[str, Any], mode: str, limits_path: Optional[str] = None, d: Optional[str] = None,
           allow_override: bool = False, now: Any = None, consume: bool = True) -> Tuple[bool, List[str], Optional[Dict[str, str]]]:
    d = gate_dir(d); why: List[str] = []
    tok = str(tok).strip()
    t = parse(tok)
    if not t:
        return False, ["not a gate nonce (expected %s.<verdict>....)" % VERSION], None
    if not hmac.compare_digest(_mac(_key(d), tok.rsplit(".", 1)[0]), t["mac"]):
        return False, ["nonce signature invalid: not issued by risk_check with this gate key"], t
    log = _log(d)
    row = next((r for r in log if r.get("nonce") == tok and r.get("event") == "issued"), None)
    if row is None:
        why.append("nonce not in gate-log.jsonl")
    elif not isinstance(row.get("wall"), (int, float)):
        why.append("nonce issued without a wall-clock stamp (older gate); run risk_check again")
    elif time.time() - float(row["wall"]) > min(int(row.get("ttl", MAX_TTL)), MAX_TTL):
        # P1: expiry also runs on this machine's clock, so a rewound --now cannot reopen the nonce
        why.append("nonce expired by the gate's own clock (issued %ds ago); run risk_check again"
                   % int(time.time() - float(row["wall"])))
    if any(r.get("nonce") == tok and r.get("event") == "used" for r in log):
        why.append("nonce already used for an order; run risk_check again")
    if _now(now) > int(t["exp"]):
        why.append("nonce expired; run risk_check again on a fresh quote")
    if t["fp"] != fingerprint(order):
        why.append("order differs from the one risk_check checked")
    if limits_path and t["lim"] != file_sha8(limits_path):
        why.append("risk-limits file changed since the check")
    if t["mode"] == "unknown":
        why.append("mode unknown at check time")
    elif t["mode"] != mode:
        why.append("nonce was issued for %s, this order goes to %s" % (t["mode"].upper(), str(mode).upper()))
    if t["verdict"] == "OVERRIDE" and not allow_override:
        why.append("OVERRIDE nonce: the execution step must be run with --allow-override")
    elif t["verdict"] == "FAIL":
        why.append("risk_check verdict fail: do not place this order")
    ok = not why
    if ok and consume:
        _append(d, "gate-log.jsonl", dict(event="used", nonce=tok, at=int(_now(now))))
    return ok, why, t


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    v = sp.add_parser("verify"); lg = sp.add_parser("log")
    v.add_argument("--nonce", required=True); v.add_argument("--order", required=True); v.add_argument("--now")
    v.add_argument("--mode", required=True, choices=["paper", "live"]); v.add_argument("--limits")
    v.add_argument("--allow-override", action="store_true"); v.add_argument("--no-consume", action="store_true")
    for p in (v, lg):
        p.add_argument("--gate-dir")
    a = ap.parse_args()
    if a.cmd == "log":
        p = os.path.join(gate_dir(a.gate_dir), "overrides.jsonl")
        print(open(p).read() if os.path.exists(p) else ""); return
    ok, why, t = verify(a.nonce, json.load(open(a.order)), a.mode, a.limits, a.gate_dir, a.allow_override,
                        a.now, not a.no_consume)
    print(json.dumps({"gate": "OPEN" if ok else "CLOSED", "verdict": (t or {}).get("verdict"),
                      "mode": (t or {}).get("mode"), "nonce": a.nonce.strip(), "reasons": why}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
