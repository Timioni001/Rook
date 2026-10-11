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
| `01M4JJDPPS6G0H9544VZHFBCK3` | `0a24e08` | Turned Entire on and documented it |
| `01M4K7NDN001T1HH28YF5J9VE8` | `c8be14d` | Committed checkpoints into the repo so they merge into main |
| `01M4K7R9BB2PMACK1VK2KK857T` | `f8ed2a0` | Exported the second checkpoint, added extra redaction |
| `01M4KHB6C93GCV4RPS7YFQ6351` | `66ba4a6` | Fixed the WSL setup, replaced AWS with Cloudflare Tunnel |
| `01M4KHPDHXNSAXNEF8HDC7WT8K` | `908dcc6` | Gave the project its own Python 3.13 via uv for neatlogs |
| `01M4KK5YMF2PV0548CAX4KPDYT` | `7c94aa1` | Guided dashboard, one-command public link, cfo.ai inputs |
| `01M4KK752JA1SB7VVM3CYA4YZ3` | `893d52e` | Exported checkpoints with a stricter email redaction |
| `01M4KMAH7MFTFAEYJ673B42XYQ` | `2db6886` | No-terminal deploy (Render + Cloudflare Pages), handoff notes |
