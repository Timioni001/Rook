# Going live from Ubuntu on WSL: neatlogs → Cloudflare

You end up with:

- **Rook** (agent, API and dashboard) running on your own machine
- **Cloudflare** giving it a public https address through Cloudflare Tunnel, so judges can open the live demo
- **neatlogs** receiving a trace for every incident anyone runs on it

No cloud server or credit card is needed. Do the steps in order. Each one ends with a check, so you know it worked before moving on.

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

### Optional: a fixed dashboard address on Cloudflare Pages

1. Build and upload the dashboard:
   ```bash
   cd web && STATIC_EXPORT=1 npx next build
   npx wrangler login && npx wrangler pages deploy out --project-name rook
   ```
2. In the Cloudflare dashboard, go to **Workers & Pages → rook → Settings → Variables and Secrets**. Set `ROOK_API_ORIGIN` to your tunnel address with no trailing slash, then deploy again.

Quick tunnel addresses change on every run, so you'd update that variable each time. The share link from step 2 is enough for the hackathon.

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
