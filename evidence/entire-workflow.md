# Entire workflow

**Status: enabled from 2026-10-10 09:30 UTC (team decision).**

The team first skipped Entire, then turned it on for the rest of the build. Each agent session is
recorded as a checkpoint, and every commit made during a session carries an `Entire-Checkpoint:`
trailer that links to it. That trailer is the durable record: it is in the commit, so it travels
with the repository whether or not anything else does.

Entire keeps the checkpoints themselves as git refs (`refs/entire/checkpoints/*`) and in the Entire
service. They are deliberately **not** committed as files here: a checkpoint holds a full session
transcript, and a repository is the wrong place for one. An earlier version of this build exported
them into `.entire/checkpoints/` with `scripts/export-entire-checkpoints.py`; that export has been
removed from the working tree, and the script is kept for anyone who wants it locally.

Commits before `Enable Entire session tracking for the Rook build` have no checkpoints. Their
history was not imported or rewritten.

## Check it yourself

```bash
git log --format='%h %s%n%(trailers:key=Entire-Checkpoint)' | head -20   # no Entire install needed
entire status                    # enabled, agents, where checkpoints sync
entire checkpoint list           # checkpoints on this branch
entire checkpoint explain <id>   # what the session did, from the refs or the service
```

## Checkpoints so far

Each id matches an `Entire-Checkpoint:` trailer in `git log`.

| Checkpoint | Commit | What the session did |
|---|---|---|
| `01M4JJDPPS6G0H9544VZHFBCK3` | `caba430` | Record Entire as the build's session tracker and document how to inspect checkpoints |
| `01M4K7NDN001T1HH28YF5J9VE8` | `25f803b` | Commit Entire checkpoints into the repo so they merge into main with the code |
| `01M4K7R9BB2PMACK1VK2KK857T` | `b6a4211` | Export the latest Entire checkpoint and allow extra redaction words |
| `01M4KHB6C93GCV4RPS7YFQ6351` | `e4763b1` | Fix the WSL setup on machines with NodeSource Node and replace AWS with Cloudflare Tunnel |
| `01M4KHBWY3GQ4BH0ZMYZJQYFNW` | `79499ad` | Export the latest Entire checkpoints |
| `01M4KHP984Z0RBZEYECJAV4Z8B` | `d5603f5` | Give the project its own Python 3.13 via uv, since neatlogs does not support 3.14 |
| `01M4KK5YMF2PV0548CAX4KPDYT` | `efc51c2` | Guide new users through the dashboard and make the public link one command |
| `01M4KK752JA1SB7VVM3CYA4YZ3` | `d08898d` | Export the latest Entire checkpoints |
| `01M4KMAH7MFTFAEYJ673B42XYQ` | `8332568` | Go live from the browser: Render runs the agent, Cloudflare Pages serves the dashboard |
| `01M4KMB70M4NBTETESDCAE715X` | `47c62a9` | Export the latest Entire checkpoints |
