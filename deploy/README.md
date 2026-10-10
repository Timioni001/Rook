# Going live from Ubuntu on WSL: neatlogs → AWS → Cloudflare

You end up with:

- **AWS Lightsail** running the Rook agent and API (one container, paid from the hackathon AWS credit)
- **Cloudflare Pages** serving the dashboard at a `*.pages.dev` address, forwarding `/api/*` to AWS
- **neatlogs** receiving a trace for every incident anyone runs on the live demo

Do the steps in order. Each one ends with a check, so you know it worked before moving on.

---

## 0. One-time setup on Ubuntu (WSL)

Everything below runs in an **Ubuntu terminal on WSL** (written for Ubuntu 26.04, also fine on 24.04). Python 3.14, which is the Ubuntu 26.04 default, passes the full test suite.

1. **Docker:** install Docker Desktop for Windows from https://docs.docker.com/desktop/setup/install/windows-install/. Then go to **Settings → Resources → WSL integration**, turn on your Ubuntu distro, and open a new Ubuntu terminal.
2. **Clone inside WSL, not under `/mnt/c`.** Builds are much faster there and the scripts keep their Linux line endings:
   ```bash
   cd ~
   git clone https://github.com/Timioni001/Rook && cd Rook && git checkout keywarden-build-v7m54f
   ```
3. **Run the setup script.** It installs the system packages, Python venv, dashboard packages, AWS CLI v2 and `lightsailctl`, then runs the tests:
   ```bash
   ./scripts/setup-wsl.sh            # asks for your sudo password once
   source .venv/bin/activate
   ```
   **Check:** the script ends with a version table, `docker` is listed (not "not reachable"), and the tests say `passed`.
4. **Try it locally:** run `./scripts/dev.sh`, then open http://localhost:3000 in your Windows browser. WSL forwards localhost for you.

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

## 2. AWS: run the agent on Lightsail

1. In the AWS console, confirm the hackathon credit appears under **Billing → Credits**.
2. Create an access key for the CLI. The simplest route is **IAM → Users → (you) → Security credentials → Create access key → CLI**. Then:
   ```bash
   aws configure            # paste the key id + secret, region e.g. us-east-1, output json
   aws sts get-caller-identity
   ```
   **Check:** your account id is printed.
3. Deploy (the neatlogs key from step 1 is still exported in this terminal):
   ```bash
   export AWS_REGION=us-east-1
   ./deploy/aws-lightsail.sh
   ```
   The script first checks Docker, the AWS CLI, `lightsailctl` and your credentials, and says what's missing. Then it builds the image, creates a `nano` container service called `rook`, pushes and deploys, then prints `Rook is live at: https://rook.xxxxx.us-east-1.cs.amazonlightsail.com/`. The first deploy takes a few minutes.
4. **Check:** open that URL and the Rook dashboard loads. Pick an incident type, click **Investigate**, then click **Run plan**. A new session appears in neatlogs.
5. Look up the current price of the `nano` power in the Lightsail console before leaving it running. After judging, run `aws lightsail delete-container-service --service-name rook --region $AWS_REGION`.

---

## 3. Cloudflare: serve the dashboard on Pages

The dashboard is static files. A small Pages Function (`web/functions/api/[[path]].ts`) forwards `/api/*` to the AWS service, so the browser only ever talks to Cloudflare.

1. Create a free Cloudflare account at https://dash.cloudflare.com/sign-up.
2. Build and deploy from the `web` folder:
   ```bash
   cd web
   npm install
   STATIC_EXPORT=1 npx next build          # writes web/out
   npx wrangler login                      # opens the browser once
   npx wrangler pages deploy out --project-name rook
   ```
   On WSL, `wrangler login` prints a URL. If no browser window opens, paste that URL into your Windows browser; the login callback still reaches WSL. If it doesn't, create an API token in the Cloudflare dashboard (**My Profile → API Tokens**, using the "Edit Cloudflare Workers" template) and run `read -rs CLOUDFLARE_API_TOKEN && export CLOUDFLARE_API_TOKEN` instead of logging in.
   The first run creates the `rook` Pages project and prints a `https://rook-xxx.pages.dev` URL.
3. Point the proxy at AWS: Cloudflare dashboard → **Workers & Pages → rook → Settings → Variables and Secrets → Add**, name `ROOK_API_ORIGIN`, value the Lightsail URL from step 2 without a trailing slash. Save, then redeploy (`npx wrangler pages deploy out --project-name rook`) so the function picks it up.
4. **Check:** `https://rook-xxx.pages.dev/api/health` returns `{"ok":true,...}`, and the dashboard runs an incident end to end. Use the `pages.dev` link as the demo link in the submission.
5. Optional: attach your own domain under **Custom domains** on the Pages project.

---

## Optional: Entire on your machine

If you code in this repo with an AI agent on WSL, install Entire using https://hack.entire.io/neathacks-2026, then run `entire enable --agent <your agent>` in the repo. Your commits then link to checkpoints too. Check with `entire status` and `entire checkpoint list`.

## Run everything locally instead

```bash
./scripts/dev.sh                                        # API :8000 + dashboard :3000
# or the single container:
docker build -t rook . && docker run --rm -p 8000:8000 -e NEATLOGS_API_KEY rook   # http://localhost:8000
```

## Notes

- The demo identities (analyst, approver, viewer, other company) are built into this sandbox build, so anyone with the link can use them. Writes are limited to 30 per minute per identity.
- Data lives on the container's disk and resets on every redeploy.
- Never commit `NEATLOGS_API_KEY` or AWS keys. Lightsail stores the neatlogs key in the container's settings only.
