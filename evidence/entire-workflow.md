# Entire workflow

**Status: enabled from 2026-10-10 09:30 UTC (team decision).**

The team first skipped Entire, then turned it on for the rest of the build. Entire CLI 0.11.4 runs with Claude Code hooks (`.claude/settings.json`) and project settings (`.entire/settings.json`). Each agent session is recorded as a checkpoint, and commits made during a session carry an `Entire-Checkpoint:` trailer that links to it.

Entire keeps checkpoints as git refs (`refs/entire/checkpoints/*`), which only travel with an extra push. So `scripts/export-entire-checkpoints.py` also writes every checkpoint as plain files in [`.entire/checkpoints/<id>/`](../.entire/checkpoints/). They are committed with the code and merge into main with it. Each folder holds the checkpoint metadata (files touched, agent line attribution, token usage), the prompt, and the compact session transcript. Email addresses and model identifiers are redacted.

Commits before `Enable Entire session tracking for the Rook build` have no checkpoints. Their history wasn't imported or rewritten.

## Check it yourself

```bash
entire status                    # enabled, agents, where checkpoints sync
entire checkpoint list           # checkpoints on this branch
git log --format='%h %s%n%(trailers:key=Entire-Checkpoint)' | head -20
entire checkpoint explain <id>   # what the agent did in that checkpoint (needs the refs)
ls .entire/checkpoints/          # the same checkpoints as committed files, no Entire install needed
```

## Checkpoints so far

| Checkpoint | Commit | What the session did |
|---|---|---|
| [01M4JJDPPS6G0H9544VZHFBCK3](../.entire/checkpoints/01M4JJDPPS6G0H9544VZHFBCK3/) | `0a24e08` | Turned Entire on and documented it |
| [01M4K7NDN001T1HH28YF5J9VE8](../.entire/checkpoints/01M4K7NDN001T1HH28YF5J9VE8/) | `c8be14d` | Committed checkpoints into the repo so they merge into main |
| [01M4K7R9BB2PMACK1VK2KK857T](../.entire/checkpoints/01M4K7R9BB2PMACK1VK2KK857T/) | `f8ed2a0` | Exported the second checkpoint, added extra redaction |
| [01M4KHB6C93GCV4RPS7YFQ6351](../.entire/checkpoints/01M4KHB6C93GCV4RPS7YFQ6351/) | `66ba4a6` | Fixed the WSL setup, replaced AWS with Cloudflare Tunnel |

Run `ls .entire/checkpoints` for the current list. Each folder name matches an `Entire-Checkpoint:` trailer in `git log`.
