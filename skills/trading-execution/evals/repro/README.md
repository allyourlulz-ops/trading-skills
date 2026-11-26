# repro fixtures

`../repro.py` replays each folder here through the whole place-it path, using the real scripts:
portfolio → order → `risk_check.py` → `preview.py` → simulated fill → `verify_fill.py`. It diffs the result against the
folder's `expected.json`, ignoring only the nonce's expiry, random part and MAC, the preview's
"Nonce: … (expires …)" text and `checked_at`. The gate dir is a temp dir outside the repo. Nothing
here talks to a broker, and no order is ever sent: the "fill" is simulated at the limit price.

```
python3 skills/trading-execution/evals/repro.py --all            # every folder (CI, run_tests.py)
python3 skills/trading-execution/evals/repro.py <folder> --bless # rewrite expected.json; review the diff
```

## synthetic/: ALL HAND-WRITTEN, NOT RECORDED

Every file under `synthetic/` was written by hand. None of it came from a broker account, real or
paper. Where a folder has `alpaca/` or `ibkr/`, those files only imitate the *shape* of the broker's
documented responses so the broker layer in repro.py is exercised; the numbers, ids and conids are
placeholders. Each such folder carries a `synthetic.json` saying so, and every `meta.json` has
`"synthetic": true`.

| Folder | Broker layer | What it shows |
|---|---|---|
| `pass_paper_buy` | portfolio.json as given | AAPL buy, 52 shares at the sized max: PASS, preview OPEN, simulated fill |
| `pass_paper_buy_alpaca` | `alpaca_paper` (Alpaca Trading API v2 shapes: account, clock, positions) | The same PASS paper buy, built from Alpaca-shaped responses |
| `pass_paper_buy_ibkr_tsx` | `ibkr_paper` (IBKR Client Portal Web API shapes: accounts, summary, positions) | RY (TSX) buy in a CAD paper account holding ENB: PASS, preview OPEN, simulated fill |
| `hard_fail_too_big` | portfolio.json | 53 shares, one over the sized max, plus an override attempt: SIZE is HARD, override refused, CLOSED, no fill |
| `soft_fail_override` | portfolio.json | Reward/risk 0.4 (SOFT), overridden on paper with the exact ack: OVERRIDE nonce, OPEN with `--allow-override`, simulated fill |

The IBKR fixture brings its own `mcp-config.json` and `mcp-lock.json` (`"mode": "paper"` for the
`ibkr` server), because `preview.py` treats any non-Alpaca server as LIVE unless its lock entry
says paper. The skill does not ship an IBKR config yet.

## paper-broker/: slots for REAL paper recordings (empty until recorded)

| Folder | Recorder | Notes |
|---|---|---|
| `alpaca_paper_account` | `../record_alpaca.py` (GET /v2/account, /v2/clock, /v2/positions on https://paper-api.alpaca.markets only; redacts `account_number`, `id`) | Also run by the manual `.github/workflows/paper-live.yml` with the repo secrets `ALPACA_PAPER_KEY` / `ALPACA_PAPER_SECRET`. |
| `ibkr_paper_account` | `../record_ibkr.py` (GET /portfolio/accounts, /portfolio/{id}/summary, /portfolio/{id}/positions/0 through the local Client Portal Gateway; refuses any account id not starting with `DU`; redacts every account id and the account names) | Needs a gateway logged in to the paper account on the user's own machine, so it cannot run in CI. The Web API has no clock call: set `meta.clock` from the exchange schedule before `--bless`. |

In both slots the order, the quote contract (`{NOW}` is filled with the recording time) and, for
IBKR, the MCP config and lock are hand-written templates. Only the account, clock and positions
responses are recorded. Until a recording is committed, `repro.py --all` reports the slot as `skip`
(and `--require-recorded` turns that into a failure). As of this commit **no recording exists**:
neither recorder has been run.
