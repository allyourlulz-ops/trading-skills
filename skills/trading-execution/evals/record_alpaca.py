#!/usr/bin/env python3
"""Record real Alpaca PAPER responses for the repro fixture. Stdlib only (urllib). Read-only.

Does three GETs and nothing else: /v2/account, /v2/clock, /v2/positions on the paper host
https://paper-api.alpaca.markets. It places, cancels or changes no orders. Any other base URL is
refused, including the live host, http://, another port or a path; redirects are not followed.

Usage
  APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... \
    record_alpaca.py [--out evals/repro/paper-broker/alpaca_paper_account/alpaca] [--base-url URL]

Writes OUT/account.json, OUT/clock.json, OUT/positions.json and OUT/recorded.json (host, UTC time
of recording, the endpoints, and which fields were redacted). account_number and id are replaced by
"REDACTED" before anything is written. Keys come only from the environment and are never written.
Then: repro.py <fixture> --bless (review expected.json), and repro.py <fixture> to replay.
Exit 0 on success, 2 on a refused URL or missing keys, 1 on an HTTP or network error.
"""
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

PAPER = "https://paper-api.alpaca.markets"
ENDPOINTS = ("/v2/account", "/v2/clock", "/v2/positions")
REDACT = ("account_number", "id")
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "repro", "paper-broker", "alpaca_paper_account", "alpaca")


def paper_only(url):
    """Return the canonical paper base URL, or raise ValueError for anything else."""
    u = urllib.parse.urlsplit(str(url).strip())
    if (u.scheme, u.hostname, u.port, u.username, u.password) != ("https", "paper-api.alpaca.markets", None, None, None) \
            or u.path not in ("", "/") or u.query or u.fragment:
        raise ValueError("refusing base URL %r: only %s (Alpaca paper) is allowed" % (url, PAPER))
    return PAPER


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect to %s refused (paper host only)" % newurl, headers, fp)


def get(base, path, key, secret, timeout=20):
    req = urllib.request.Request(base + path, method="GET",
                                 headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def redact(obj):
    if isinstance(obj, dict):
        return {k: ("REDACTED" if k in REDACT and v not in (None, "") else v) for k, v in obj.items()}
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--base-url", default=PAPER)
    a = ap.parse_args()
    try:
        base = paper_only(a.base_url)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)})); sys.exit(2)
    key, secret = os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        print(json.dumps({"ok": False, "error": "set APCA_API_KEY_ID and APCA_API_SECRET_KEY (paper keys)"})); sys.exit(2)
    got = {}
    try:
        for ep in ENDPOINTS:
            got[ep] = get(base, ep, key, secret)
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e), "endpoint": ep})); sys.exit(1)
    os.makedirs(a.out, exist_ok=True)
    files = {"/v2/account": "account.json", "/v2/clock": "clock.json", "/v2/positions": "positions.json"}
    for ep, name in files.items():
        body = redact(got[ep]) if ep == "/v2/account" else got[ep]
        with open(os.path.join(a.out, name), "w") as f:
            json.dump(body, f, indent=1, sort_keys=True); f.write("\n")
    meta = {"recorded": True, "synthetic": False, "base_url": base, "endpoints": list(ENDPOINTS), "method": "GET",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "redacted": {"account.json": list(REDACT)}, "positions": len(got["/v2/positions"] or [])}
    with open(os.path.join(a.out, "recorded.json"), "w") as f:
        json.dump(meta, f, indent=1); f.write("\n")
    print(json.dumps({"ok": True, "out": a.out, **meta}, indent=1))


if __name__ == "__main__":
    main()
