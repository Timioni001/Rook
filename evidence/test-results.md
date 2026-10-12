# Test results and the audit behind them

Three layers, all run on 2026-10-11 against this commit: the unit and integration suite, every
HTTP route exercised through the real Cloudflare Workers proxy, and every playbook driven in a
real browser. Each section says how to reproduce it.

## 1. The suite: 265 passed

```
python -m pytest -q
265 passed, 1 warning in 8.6s        # Python 3.13; the warning is Starlette's test client
```

| File | Tests | What it covers |
|---|---|---|
| `tests/test_all_scenarios.py` | 82 | Every one of the 40 scenarios, end to end, against the rules that must never bend |
| `tests/test_api.py` | 33 | Auth on every route, org scoping, roles, rate limits, body limits, error shapes |
| `tests/test_scenarios.py` | 31 | The engine itself: ordering, idempotency, checkpoints, crash and resume, audit chain |
| `tests/test_setup.py` | 14 | A caller describing their own organisation, and the bounds on what they may say |
| `tests/test_outage.py` | 11 | Service outage: cause attribution, pause-before-rollback, wrong-cause escalation |
| `tests/test_care.py` | 10 | Care follow-up: handoffs that never happened, urgent results, unreachable patients |
| `tests/test_fixtures.py` | 10 | Fixtures: moves, officials, telling both clubs, and the two refusals |
| `tests/test_leak.py` | 8 | Leaked credential, including the two cases where Rook refuses to act |
| `tests/test_cover.py` | 7 | Doctor off sick, including not moving anyone who cannot be told |
| `tests/test_evidence.py` | 7 | Evidence pack: refusals, impact metrics, control mapping |
| `tests/test_tracing.py` | 5 | neatlogs spans: kinds, attributes, redaction |

`test_all_scenarios.py` is the one that scales. For each scenario it asserts that the closure
checks were written down before anything was changed, that the audit chain is intact, that
**closed** means every mandatory check passed with nothing unresolved, and that **not closed**
means a stated reason and something for a person to act on. A new scenario is covered the moment
it is added.

## 2. Every HTTP surface, through the real proxy

Run against `wrangler pages dev` serving the built dashboard and forwarding `/api/*` to the agent,
so the Workers runtime and the Pages Function are in the path, not just FastAPI.

**29 of 29 checks passed.**

| Area | Checks |
|---|---|
| Authentication | `/api/health` is public; no token, bad token → 401 on everything else |
| Roles | viewer cannot create or run (403); analyst cannot approve (403); approver can |
| Org scoping | another company's token gets **404**, not 403, on the incident and its evidence |
| Input | unknown scenario → 422; unknown field → 422; body over 8 KB → 413; bad ids → 404 |
| Path handling | `/api/incidents/..%2F..%2Fetc/passwd` → 404 |
| Lifecycle | create → run (202) → pause for approval → approve → closed with every check passing |
| Artefacts | evidence pack downloads and names the organisation; events feed; `/api/docs` served |
| Re-entry | running a closed incident again → 409 |

## 3. Every playbook, in a real browser

Chromium against the same stack, clicking the dashboard as a person would: pick the industry, pick
the problem, start, run, approve each pause, read the verdict.

| Playbook | Incident it produced | Outcome |
|---|---|---|
| Doctor off sick | Dr Ada Okafor is off sick: 12 appointments to move today | Closed · verified |
| Care follow-up | 3 of 4 things marked done in the record never actually happened | Closed · verified |
| Access & offboarding | Active credential after offboarding: Jordan Doe | Closed · verified |
| Leaked credential | Leaked credential in a repository: Reporting warehouse key | Closed · verified |
| Service outage | checkout-api outage: failing after a deploy | Closed · verified |
| Fixture cannot go ahead | East Park pitch 1 is closed: 3 matches to move today | Closed · verified |

No console errors or page errors in any run.

**Mobile.** The same pages at 390 px, measuring every element against the viewport rather than
eyeballing it: page width stayed 390 px with no horizontal scroll, and a sports fixture ran to
Closed · verified on the phone viewport. The one element wider than a phone is the relationship
map, which scrolls sideways and says so.

Screenshots of these runs are in [../docs/images/](../docs/images/).

## 4. Reproducing it

```bash
python -m pytest -q                                    # layer 1
bash scripts/build-pages.sh                            # build what Cloudflare serves
uvicorn rook.api:create_app --factory --port 8000 &    # the agent
npx wrangler@4 pages dev out --port 8788 \
  --binding ROOK_API_ORIGIN=http://127.0.0.1:8000      # the proxy, locally
python3 scripts/check-live.py http://localhost:8788    # layer 2, end to end, prints PASS
python3 scripts/make-readme-charts.py                  # redraws the README charts from live runs
```

`scripts/check-live.py` also runs against the deployed site and is the one command to trust before
judging: it wakes the agent, loads the dashboard, runs a real incident through to Verified Closure
and exits non-zero if anything fails.
