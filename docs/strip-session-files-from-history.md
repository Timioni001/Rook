# Removing the old session files from git history

The working tree no longer has `.claude/` or `.entire/`, and both are gitignored, so a fresh clone
is clean. The blobs still exist in the commits that added them, which is only visible to someone
running `git log` on those paths. These commands remove them.

Run from your own machine, with the repository up to date and nothing uncommitted:

```bash
cd ~/Rook
git fetch origin && git checkout main && git pull
git filter-branch -f --prune-empty \
  --index-filter 'git rm -r --cached --ignore-unmatch -q .claude .entire' \
  --tag-name-filter cat -- --all
git push --force-with-lease origin main
```

`--prune-empty` also drops the commits that only ever exported checkpoints, so
"Export the latest Entire checkpoints" disappears from the log with them.

**What this does not break.** Everything before `48fa09a` keeps its commit id, because
`filter-branch` only rewrites from the first commit it changes onward. That includes `0817443`,
the before/after baseline `scripts/neatlogs-evidence.sh` and `evidence/neatlogs-traces.md` both
reference, so the neatlogs comparison still runs after the rewrite. The 37 commits after it get
new ids, which matters only if something outside the repository quotes one.

**What to expect.** Render auto-deploys from `main`, so the force-push triggers one rebuild. Any
other clone of this repository has to be re-cloned rather than pulled.

To check it worked:

```bash
git log --all --oneline -- .claude .entire     # prints nothing
git count-objects -vH | grep size-pack          # noticeably smaller
```
