# Entire workflow

**Status: enabled from 2026-10-10 09:30 UTC (team decision).**

The team first skipped Entire, then turned it on for the rest of the build. Entire CLI 0.11.4 runs with Claude Code hooks (`.claude/settings.json`) and project settings (`.entire/settings.json`). Each agent session is recorded as a checkpoint stored as git refs and pushed with the branch. Commits made during a session carry an `Entire-Checkpoint:` trailer that links to it.

Commits before `Enable Entire session tracking for the Rook build` have no checkpoints. Their history wasn't imported or rewritten.

## Check it yourself

```bash
entire status                    # enabled, agents, where checkpoints sync
entire checkpoint list           # checkpoints on this branch
git log --format='%h %s%n%(trailers:key=Entire-Checkpoint)' | head -20
entire checkpoint explain <id>   # what the agent did in that checkpoint
```

## Checkpoints so far

See `git log` trailers on branch `keywarden-build-v7m54f`. The list below is updated as work lands.
