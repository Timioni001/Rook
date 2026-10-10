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
5. Check: open `https://<your-service>.onrender.com/api/health`. It should say `"ok":true`. The full dashboard already works at that address too.

**B. Cloudflare Pages (the address you share).**
1. In the Cloudflare dashboard, open **Workers & Pages → Create**. Choose the **Pages** tab ("Import an existing Git repository"), then pick the Rook repo.
2. Use these build settings:
   - Production branch: `main`
   - Framework preset: `None`
   - Root directory: `web`
   - Build command: `STATIC_EXPORT=1 npx next build`
   - Build output directory: `out`
3. Under **Environment variables**, add:
   - `ROOK_API_ORIGIN`: the Render address from A5, with no trailing slash
   - `NODE_VERSION`: `22`
4. Click **Save and Deploy**.
5. Check: open `https://<project>.pages.dev` and run an incident. A trace should appear in neatlogs.

Good to know:
- The free Render service sleeps after 15 idle minutes. The first visit after that takes about a minute to wake it, so open the link yourself just before judges or a recording.
- Demo data resets whenever the service restarts. Everything in Rook is synthetic, so nothing is lost.

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
   git stash -u 2>/dev/null; git checkout 0817443
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
