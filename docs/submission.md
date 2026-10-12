# neatHack 2026 submission — answers to paste

Project: **Rook**, by **Keywarden**.

| Field | Value |
|---|---|
| Live demo + waitlist | https://rook-keywarden.pages.dev |
| Code | https://github.com/Timioni001/Rook |
| Demo video | `docs/video/rook-demo.mp4` (4:05, with voice-over) |
| Open to a call with neatlogs | yes |

---

## What the agent does, in two sentences

Rook is an operations agent for the work that falls between the systems an organisation already
runs: a doctor off sick with a day of patients booked in, a key that outlived the person who made
it, a pitch shut on a Saturday with three matches on it. It investigates across every connected
system before touching anything, writes down what would have to be true before the job can be
called done, waits for a human before anything reaches a person outside the building, and then
re-reads the live systems to prove the result — closing only when every check passes, and naming
what it refused to do when they do not.

---

## How did cfo.ai shape your business plan?

Plan: **https://cfo.ai/s/D9MnZeXwqy0WpZeV** · inputs, with every number sourced:
[`evidence/cfo-ai-business-plan.md`](https://github.com/Timioni001/Rook/blob/main/evidence/cfo-ai-business-plan.md)

We did not hand cfo.ai a guess. We wrote an input sheet where every assumption is named, given a
value, and labelled **measured** (taken from this repository), **benchmark** (a published figure) or
**assumption** (ours, and arguable). cfo.ai did the modelling on top of that, which is what made it
useful rather than decorative: the output could be traced back to a line we could defend or change.

Three things it changed:

1. **It priced the thing we could actually measure.** Model inference is **$0 per incident** — the
   shipped planner is deterministic and makes no model calls — and observability is **52 spans per
   incident** (measured, 20 to 130 across the playbooks, with an in-memory OpenTelemetry exporter).
   So unit economics are dominated by support and hosting, not tokens, and the price could be set
   against the admin hours Rook absorbs (16 h/month for a standard clinic) rather than against a
   cost per call.
2. **It found the assumption that breaks the plan.** With acquisition done on founder time, the
   lowest cash balance is **$2,320 in month 7** on $30,000 raised. The moment the same acquisition
   is paid in cash at $600 a customer, month 10 goes to **−$14,539**: year one needs roughly
   **$15,000 more capital**. That sensitivity is the single most important output of the exercise,
   and we would not have found it by eye.
3. **It kept us honest about what has not happened.** Rook has no customers. The plan says so, and
   nothing in it is presented as a result.

## How did you use Entire? Add evidence links.

Evidence: [`evidence/entire-workflow.md`](https://github.com/Timioni001/Rook/blob/main/evidence/entire-workflow.md)

Entire checkpoints every agent session that built Rook, and **every commit made during a session
carries an `Entire-Checkpoint:` trailer** pointing back at it. That trailer is the durable part: it
lives in the commit, so the provenance travels with the repository whether or not anything else
does. Ten checkpoints are on `main` today, each one matched to its commit in the table in that file.

Anyone can verify it without installing anything:

```bash
git log --format='%h %s%n   %(trailers:key=Entire-Checkpoint,valueonly)' | head -20
entire checkpoint list            # with Entire installed
entire checkpoint explain <id>    # what that session actually did
```

Two decisions worth naming, because they are the interesting part of using it honestly:

- **Checkpoints are not committed as files.** A checkpoint holds a full session transcript, and a
  repository is the wrong place for one. They live as git refs (`refs/entire/checkpoints/*`) and in
  the Entire service. An earlier version of this build did export them into the tree; that export
  was removed, and the reasoning is written down rather than quietly reversed.
- **History before Entire was turned on was left alone.** Commits made before
  `Record Entire as the build's session tracker` have no checkpoints, and we did not back-fill or
  rewrite them to pretend otherwise.

## How did you use neatlogs to identify and resolve the incidents your agent ran into?

Evidence: [`evidence/neatlogs-traces.md`](https://github.com/Timioni001/Rook/blob/main/evidence/neatlogs-traces.md)
· incident `4c1da347-2e61-4655-9774-707e023a0583` · fix commit
[`7553caa`](https://github.com/Timioni001/Rook/commit/7553caa)

**Instrumentation.** The neatlogs SDK is initialised in `rook/obs.py` and every phase of the engine
is a span: `incident.start` and `incident.run` as WORKFLOW, `investigate` and `plan` as AGENT,
`discover.dependencies` as RETRIEVER, `execute` as TOOL, `reconcile` and `checkpoint.restore` as
CHAIN, and every policy decision, approval, verification and the final closure verdict as
GUARDRAIL. Each incident is one **session** (`session_id` = the incident id), so a whole incident
replays as one session, with the human principal recorded as the end user. Secret values are
fingerprinted before export, both when the span is created and again in the client-side `mask`.

**The incident neatlogs found.** Neatlogs raised `4c1da347` off those traces — before we had
noticed anything — as a detection spike: **six negative detections against a baseline of zero**, in
the Cloud Infrastructure Span Monitor group, pattern **silent degradation**. Two findings:

| What neatlogs saw | What it actually was |
|---|---|
| Tool, retriever, chain and workflow spans arriving with **empty outputs** | Real. We were setting our own attributes and never the flat `input.value` / `output.value` pair the session view reads, so a step that worked rendered as a step that produced nothing |
| `Transient` and `Timeout` on `app.update_dependent` and `cloud.rollback_service`, with no error on the span | Half real. Those failures are injected deliberately and the engine is built to survive them — but a failure it *handled* closed its span green, so the trace said nothing had gone wrong |

**The resolution.** We sent the incident to Claude Code straight from the neatlogs incident page,
with the traces as the brief. The recommended fix was a retry policy with backoff; the engine
already had one, re-reading live state before any retry, which the traces could not show. So the
fix was the honesty, not the retries:

- `_Span.failed(kind, message, retrying=)` records a failure the caller handles itself — ERROR
  status, `rook.error.kind`, `rook.error.message`, `rook.retrying`, and an output saying which it
  was. Applied to the rollback path (`cloud.rollback_service`) and to opening the tracking ticket,
  the two places that caught an exception and carried on.
- No span can export an empty input or output any more: anything that did not set them gets a
  summary of its own attributes.
- `execute` spans now carry the call that went out (adapter, target, attempt, idempotency key) and
  the result that came back; `reconcile` carries the question it asked the live system and the
  answer.

Four tests guard it, one of which sweeps **every span of a full run and fails if a single one
exports nothing**. 225 tests, all passing. The failure mode was invisible once; it cannot be again.

**What we would use next.** Two detections worth configuring in the dashboard rather than in code:
a regex detection on our synthetic key prefix as a leak tripwire, which should never match, and a
condition detection on `neatlogs.guardrail.passed = false` for `closure.evaluate` spans, meaning an
incident that did not close.

---

## Supporting links

- Demo and waitlist: https://rook-keywarden.pages.dev
- Code: https://github.com/Timioni001/Rook
- Business plan on cfo.ai: https://cfo.ai/s/D9MnZeXwqy0WpZeV
- Entire evidence: `evidence/entire-workflow.md`
- neatlogs evidence: `evidence/neatlogs-traces.md`
- Test results: `evidence/test-results.md`
- Security notes: `evidence/security-notes.md`

## Before you submit

- [ ] Mark incident `4c1da347` **Resolved** on the neatlogs board.
- [ ] Paste the trace URLs into the pending table at the end of `evidence/neatlogs-traces.md`.
- [ ] Redeploy Pages so the live site reads 225 tests:
      `ROOK_API_ORIGIN=https://rook-qswm.onrender.com ./scripts/deploy-pages.sh`
- [ ] Make the repository public, if it is not already.
- [ ] Upload `docs/video/rook-demo.mp4`, or link it if the form wants a URL.
