# Going live: neatlogs → Cloudflare

Two ways to put Rook online. Both send a neatlogs trace for every incident anyone runs.

- **From the browser (recommended):** Render runs the agent and Cloudflare Pages serves the dashboard address. No terminal and no credit card.
- **From your machine:** Ubuntu on WSL plus a Cloudflare quick tunnel (`./scripts/share.sh`). The link lives only while the terminal is open.

---

## Go live from the browser (no terminal)

This path needs only web pages. **Render** runs the Rook agent from this repository, because Rook is a Python service and Cloudflare Pages only hosts static files and small functions. **Cloudflare Pages** gives the dashboard its address and forwards `/api` calls to Render. Both are free and redeploy on every push to `main`.

**A. Render (the agent).**
1. Sign in at https://render.com with GitHub and allow access to the Rook repository.
2. Click **New → Blueprint**, then pick the repo. Render reads `render.yaml`.
3. When it asks for `NEATLOGS_API_KEY`, paste your neatlogs project key. It is stored by Render, never in the repo.
4. Click **Apply** and wait for the deploy to finish.
5. Check: open `https://<your-service>.onrender.com/api/health`. It should say `"ok":true`. The full dashboard already works at that address too, so this alone is a usable demo link.

**B. Cloudflare Pages (the address you share).**
1. In the Cloudflare dashboard, open **Workers & Pages → Create**. Choose the **Pages** tab ("Import an existing Git repository"), then pick the Rook repo.
2. Use these build settings. **The root directory is the one that matters** — getting it wrong is what broke the 2026-10-10 build:

   | Setting | Value |
   |---|---|
   | Production branch | `main` |
   | Framework preset | `None` |
   | Root directory | `web` |
   | Build command | `npm run build:static` |
   | Build output directory | `out` |

   If the root directory field is awkward to reach or you would rather leave it empty, use this instead — it builds the same site from the repo root:

   | Setting | Value |
   |---|---|
   | Root directory | *(empty)* |
   | Build command | `npm run build` |
   | Build output directory | `out` |

   Both commands run `scripts/build-pages.sh` or the pinned Next directly. Neither uses `npx next build`, which is what pulled the wrong major of Next last time. `.node-version` pins Node 22, so no `NODE_VERSION` variable is needed.
3. Under **Settings → Environment variables**, add `ROOK_API_ORIGIN`: the Render address from A5, with no trailing slash. (Alternatively set `DEFAULT_API_ORIGIN` at the top of `web/functions/api/[[path]].ts` and commit it, and the project needs no variables at all.)
4. Click **Save and Deploy**.
5. Check it properly, from your terminal, rather than by eye:
   ```bash
   python3 scripts/check-live.py https://<project>.pages.dev
   ```
   It wakes the agent, loads the dashboard, runs a real incident through to Verified Closure and prints `PASS`. Add `--scenario signature` for the offboarding playbook with the approval step.

**C. Keep it awake, so the link works whenever judging happens.**

The free Render plan stops a service after 15 idle minutes, and the next visitor waits about a minute. One Cloudflare Worker on a cron trigger removes that:

```bash
ROOK_API_ORIGIN=https://<your-service>.onrender.com ./scripts/deploy-keepwarm.sh
```

It calls `/api/health` every 5 minutes, costs nothing on the Workers free plan, and keeps the agent warm around the clock. Visit the worker's own address to see what it last saw, or watch it with `(cd deploy/keepwarm && npx wrangler@4 tail)`. Remove it with `npx wrangler@4 delete --name rook-keepwarm`.

Even without it the dashboard copes: it detects a sleeping agent, says "Starting the agent…" and continues on its own once the agent answers, instead of showing an error.

Good to know:
- Demo data resets whenever the service restarts. Everything in Rook is synthetic, so nothing is lost.
- Render's free plan allows about 750 instance-hours a month, which is one service kept warm continuously.

## Deploy the dashboard from your machine instead (nothing to configure)

The Git build depends on three fields being right in the Cloudflare dashboard. This path depends on none of them:

```bash
ROOK_API_ORIGIN=https://<your-service>.onrender.com ./scripts/deploy-pages.sh
```

It builds the dashboard, creates the Pages project if it does not exist, compiles the agent's address into a staged copy of the `/api` proxy, and uploads the result. **Pick a project name nobody else has taken:** `<name>.pages.dev` is shared across every Cloudflare account, so plain `rook` is already somebody's site. The default is `rook-keywarden`; override it with `CF_PAGES_PROJECT`. No build settings and no environment variables are involved, and nothing in git changes -- the committed proxy keeps its empty default. The first run prints a Cloudflare sign-in link; `CLOUDFLARE_API_TOKEN` (with "Cloudflare Pages: Edit") skips it. Set `CF_PAGES_PROJECT` if the project is not called `rook`.

Then check it:

```bash
python3 scripts/check-live.py https://<project>.pages.dev
```

## Two confusing failures, and what they actually mean

**`403 error code: 1010` from `check-live.py`.** Cloudflare's browser-integrity check rejecting a non-browser client, not a dead deployment. The checker now sends a proper user agent, so this should not recur; if it does, the site is up and something in front of it is filtering requests.

**The address answers, but nothing is Rook.** `<name>.pages.dev` is global, not per account. If the name was taken, you are looking at a stranger's project. `check-live.py` now detects this and says so, and `deploy-pages.sh` refuses to continue instead of deploying into a name it does not own.

## When a Cloudflare Pages build fails

The build log says what went wrong. The failure on 2026-10-10 looked like this:

```
Installing project dependencies: pip install -r requirements.txt
Executing user build command: STATIC_EXPORT=1 npx next build
npm warn exec The following package was not found and will be installed: next@16.4.0
The module 'react' was not found...
Error: > Couldn't find any `pages` or `app` directory.
```

Read it as: the build ran at the repo root, not in `web/`. There is no `app/` directory there, `web/node_modules` was never installed, and `npx` therefore downloaded a newer major of Next instead of the pinned one. The fix is the root directory and build command in the table above. Checks that catch this before pushing:

```bash
bash scripts/build-pages.sh                  # exactly what Cloudflare runs
cd web && npx wrangler@4 pages dev out \
  --binding ROOK_API_ORIGIN=http://localhost:8000   # the Pages site and /api proxy, locally
```

---

The terminal steps below still work if you'd rather run Rook on your own machine.

---

## 0. One-time setup on Ubuntu (WSL)

Everything below runs in an **Ubuntu terminal on WSL**. It was written for Ubuntu 26.04 and also works on 24.04. Ubuntu 26.04 ships Python 3.14, which neatlogs doesn't support yet, so the setup script uses `uv` to give the project its own Python 3.13.

1. **Clone inside WSL, not under `/mnt/c`.** Builds are much faster there, and the scripts keep their Linux line endings:
   ```bash
   cd ~
   git clone https://github.com/Timioni001/Rook && cd Rook && git checkout keywarden-build-v7m54f
   ```
   If you already cloned it, run `git pull` to get the fixed setup script.
2. **Run the setup script.** It installs the system packages, a Python 3.13 venv (through `uv`), the dashboard packages and `cloudflared`, then runs the tests. It only installs Node if yours is missing or older than 18. It's safe to run again.
   ```bash
   ./scripts/setup-wsl.sh            # asks for your sudo password once
   source .venv/bin/activate
   ```
   **Check:** the script ends with a version table, and the tests say `passed`.
3. **Try it locally:** run `./scripts/dev.sh`, then open http://localhost:3000 in your Windows browser. WSL forwards localhost for you.

---

## 1. neatlogs: get a project key and prove traces arrive

1. Sign in at https://app.neatlogs.com and create a project, for example `rook`.
2. Open the project settings, copy the **project API key**, and keep it private.
3. In your Ubuntu terminal, in the repo, with the venv active:
   ```bash
   read -rs NEATLOGS_API_KEY && export NEATLOGS_API_KEY    # paste the key, press Enter; it isn't echoed or saved to history
   python -m neatlogs doctor --probe                        # SDK self-test against the real ingest
   python -m rook.demo                                      # offboarding incident: failure, recovery, approval
   python -m rook.demo --scenario outage                    # service outage: bad deploy, rollback, pipeline
   ```
4. **Check:** each demo prints `"status": "closed_verified"` and `"span_export_failures": 0`. In the neatlogs dashboard, under **Traces** or **Sessions**, a trace for workflow `rook-incident-response` appears within a few seconds. Open it and you'll see guardrail spans showing Passed/Blocked and tool spans for each adapter call.
5. **Before/after evidence**, for the submission:
   ```bash
   git stash -u 2>/dev/null; git checkout c2e097d
   ROOK_DEMO_LABEL=before python -m rook.demo --scenario transient
   ROOK_DEMO_LABEL=before python -m rook.demo --scenario persistent
   git checkout keywarden-build-v7m54f
   ROOK_DEMO_LABEL=after python -m rook.demo --scenario signature
   ROOK_DEMO_LABEL=after python -m rook.demo --scenario persistent
   ROOK_DEMO_LABEL=after python -m rook.demo --scenario outage
   ROOK_DEMO_LABEL=after python -m rook.demo --scenario outage_wrong_cause
   ```
   Copy the trace URLs into `evidence/neatlogs-traces.md`. Each trace carries a `version:<commit>` tag, so you can filter before and after apart.
6. Optional dashboard setup, both in neatlogs: add a **Detection** with a regex on `sk_test_SYNTH`, which should never fire and acts as a leak tripwire. Add an **Alert** on `closure.evaluate` spans where `neatlogs.guardrail.passed = false`, which flags incidents that didn't close.

---

## 2. Cloudflare: share the live demo

```bash
./scripts/share.sh       # keep NEATLOGS_API_KEY exported from step 1 so live runs are traced
```

The script builds the dashboard, starts Rook on port 8000, and opens a Cloudflare Tunnel. You don't need a Cloudflare account. Look for a line like `https://some-words.trycloudflare.com`: that's your public demo link.

**Check:** open the link on your phone, pick an incident type, click **Investigate**, then click **Run plan**. A new session appears in neatlogs.

The link works while the terminal stays open and changes every time you run the script. Run it when you record the video or while judging happens. Ctrl+C stops it.

---

## Optional: Entire on your machine

If you code in this repo with an AI agent on WSL, install Entire using https://hack.entire.io/neathacks-2026, then run `entire enable --agent <your agent>` in the repo. Your commits then link to checkpoints too. Check with `entire status` and `entire checkpoint list`.

## Run everything locally instead

```bash
./scripts/dev.sh                                        # API :8000 + dashboard :3000
```

## Notes

- The demo identities (analyst, approver, viewer, other company) are built into this sandbox build, so anyone with the link can use them. Writes are limited to 30 per minute per identity.
- Data lives in `rook-demo.db` on your machine. Delete the file to start fresh.
- Never commit `NEATLOGS_API_KEY`. The `read -rs` line above keeps it out of your shell history.
