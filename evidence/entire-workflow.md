# Entire workflow

## Status

| Item | Status |
|---|---|
| Entire CLI installed in the build environment | done: `Entire CLI 0.11.4` (built from `github.com/entireio/cli`, since the release download host is blocked here) |
| `entire enable` on this repository | **not done.** Waiting on the team's decision about which coding sessions to link |
| Checkpoints linked to commits | **none yet** |
| Entire Graph (`entire plugin install graph`) | not done |

## What's needed

Follow the official neatHack steps (https://hack.entire.io/neathacks-2026):

```bash
entire enable --agent <agent>          # see `entire enable --help` for supported agents
# work with the agent, then commit and accept linking the commit to session context
entire checkpoint list
entire checkpoint explain HEAD
entire status                           # confirm sync after pushing
```

The shareable checkpoint URL format is `https://entire.io/gh/Timioni001/Rook/commit/<FULL_SHA>`. Record the checkpoint ID and URL here, with a short note on how the session context helped.

The commits before Entire was enabled (`0817443` through the current head) have no checkpoints. They won't be rewritten or backdated to look as if they do.
