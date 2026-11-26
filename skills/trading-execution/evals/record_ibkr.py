#!/usr/bin/env python3
"""Record IBKR PAPER account responses for the repro fixture. Stdlib only (urllib). Read-only.

Talks to the IBKR Client Portal Web API through the user's own Client Portal Gateway, which must
already be running and logged in to a PAPER account (the session lives in the gateway; there is no
key to pass). It does three GETs and nothing else:
  GET /portfolio/accounts
  GET /portfolio/{accountId}/summary
  GET /portfolio/{accountId}/positions/0
No order, reply, cancel or POST call exists in this file.

Refusals (exit 2), before any account data is fetched:
  - the base URL is not https on localhost / 127.0.0.1 (the gateway), or carries a query or user info
  - the chosen account id does not start with "DU" (IBKR paper accounts); live ids start with "U"
  - --account names an id the gateway did not list
The account id, and accountTitle / displayName / accountAlias (names), are redacted to "DU-REDACTED"
or "REDACTED" in every file before it is written. The gateway's self-signed certificate is accepted
only because the host is local.

Usage
  record_ibkr.py [--base-url https://localhost:5000/v1/api] [--account DUxxxxxxx]
                 [--out evals/repro/paper-broker/ibkr_paper_account/ibkr]
Writes OUT/accounts.json, OUT/summary.json, OUT/positions.json and OUT/recorded.json (with
recorded_at, the fixed --now for repro). The Web API has no market-clock call: fill meta.clock in
the fixture from the exchange schedule before running repro.py --bless.
"""
import argparse, json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_BASE = "https://localhost:5000/v1/api"
LOCAL = ("localhost", "127.0.0.1")
NAMES = ("accountTitle", "displayName", "accountAlias")
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "repro", "paper-broker", "ibkr_paper_account", "ibkr")


def local_gateway(url):
    u = urllib.parse.urlsplit(str(url).strip())
    if u.scheme != "https" or u.hostname not in LOCAL or u.username or u.password or u.query or u.fragment:
        raise ValueError("refusing base URL %r: only the local Client Portal Gateway (https://localhost:<port>/v1/api)" % url)
    return url.rstrip("/")


def paper_account(accounts, wanted=None):
    ids = [str(a.get("accountId") or a.get("id") or "") for a in (accounts or [])]
    if wanted:
        if wanted not in ids:
            raise ValueError("account %s is not in the gateway's account list" % ("DU..." if wanted.startswith("DU") else "given"))
        aid = wanted
    elif len(ids) == 1:
        aid = ids[0]
    else:
        raise ValueError("the gateway lists %d accounts: pass --account DUxxxxxxx" % len(ids))
    if not aid.startswith("DU"):
        raise ValueError("refusing: account id does not start with DU, so it is not an IBKR paper account")
    return aid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect to %s refused" % newurl, headers, fp)


def get(base, path, timeout=20):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the gateway's self-signed cert; host already checked to be local
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), NoRedirect)
    req = urllib.request.Request(base + path, method="GET", headers={"Accept": "application/json", "User-Agent": "record_ibkr"})
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def redact(obj, ids):
    """Every listed account id becomes DU-REDACTED (paper) or U-REDACTED; names become REDACTED."""
    if isinstance(obj, dict):
        return {k: ("REDACTED" if k in NAMES and v not in (None, "") else redact(v, ids)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, ids) for v in obj]
    if isinstance(obj, str):
        for i in sorted((i for i in ids if i), key=len, reverse=True):
            obj = obj.replace(i, "DU-REDACTED" if i.startswith("DU") else "U-REDACTED")
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=DEFAULT_BASE); ap.add_argument("--account"); ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    try:
        base = local_gateway(a.base_url)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)})); sys.exit(2)
    try:
        accounts = get(base, "/portfolio/accounts")
        aid = paper_account(accounts, a.account)
        q = urllib.parse.quote(aid, safe="")
        summary = get(base, "/portfolio/%s/summary" % q)
        positions = get(base, "/portfolio/%s/positions/0" % q)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)})); sys.exit(2)
    except (urllib.error.URLError, OSError) as e:
        print(json.dumps({"ok": False, "error": "%s: %s (is the gateway running and logged in?)" % (type(e).__name__, e)})); sys.exit(1)
    ids = [str(x.get("accountId") or x.get("id") or "") for x in accounts] + [aid]
    os.makedirs(a.out, exist_ok=True)
    for name, body in (("accounts.json", accounts), ("summary.json", summary), ("positions.json", positions)):
        with open(os.path.join(a.out, name), "w") as f:
            json.dump(redact(body, ids), f, indent=1, sort_keys=True); f.write("\n")
    meta = {"recorded": True, "synthetic": False, "base_url": base, "method": "GET", "account_prefix": "DU",
            "endpoints": ["/portfolio/accounts", "/portfolio/{accountId}/summary", "/portfolio/{accountId}/positions/0"],
            # exchange-local time (TSX/NYSE are both on Toronto/New York time): risk_check reads the
            # entry window from --now's own offset, so a UTC stamp would shift it by five hours
            "recorded_at": datetime.now(timezone.utc).astimezone(ZoneInfo("America/Toronto")).isoformat(timespec="seconds"),
            "redacted": ["accountId everywhere -> DU-REDACTED"] + list(NAMES)}
    with open(os.path.join(a.out, "recorded.json"), "w") as f:
        json.dump(meta, f, indent=1); f.write("\n")
    print(json.dumps({"ok": True, "out": a.out, **meta}, indent=1))


if __name__ == "__main__":
    main()
