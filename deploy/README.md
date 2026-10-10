# Going live: neatlogs → AWS → Cloudflare

You end up with:

- **AWS Lightsail** running the Rook agent and API (one container, paid from the hackathon AWS credit)
- **Cloudflare Pages** serving the dashboard at a `*.pages.dev` address, forwarding `/api/*` to AWS
- **neatlogs** receiving a trace for every incident anyone runs on the live demo

Do the steps in order. Each one ends with a check, so you know it worked before moving on.

---

## 0. One-time tools on your computer

| Tool | Install | Check |
|---|---|---|
| Git + this repo | `git clone https://github.com/Timioni001/Rook && cd Rook && git checkout keywarden-build-v7m54f` | `ls rook` |
| Docker Desktop | https://docs.docker.com/get-docker/ (start it after installing) | `docker run --rm hello-world` |
| AWS CLI v2 | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html | `aws --version` |
| Lightsail plugin | https://docs.aws.amazon.com/en_us/lightsail/latest/userguide/amazon-lightsail-install-software.html (`lightsailctl`) | `lightsailctl --version` |
| Node 18+ | https://nodejs.org | `node -v` |
| Python 3.10–3.13 | https://python.org | `python3 --version` |

---

## 1. neatlogs: get a project key and prove traces arrive

1. Sign in at https://app.neatlogs.com and create a project, for example `rook`.
2. Open the project settings, copy the **project API key**, and keep it private.
3. In a terminal in the repo:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   export NEATLOGS_API_KEY=paste-your-key                  # Windows PowerShell: $env:NEATLOGS_API_KEY="..."
   python -m neatlogs doctor --probe                        # SDK self-test against the real ingest
   python -m rook.demo                                      # one full incident, with a failure and recovery
   ```
4. **Check:** the demo prints `"status": "closed_verified"` and `"span_export_failures": 0`. In the neatlogs dashboard, under **Traces** or **Sessions**, a trace for workflow `rook-incident-response` appears within a few seconds. Open it and you'll see guardrail spans showing Passed/Blocked and tool spans for each adapter call.
5. **Before/after evidence**, for the submission:
   ```bash
   git stash -u 2>/dev/null; git checkout 0817443
   ROOK_DEMO_LABEL=before python -m rook.demo --scenario transient
   ROOK_DEMO_LABEL=before python -m rook.demo --scenario persistent
   git checkout keywarden-build-v7m54f
   ROOK_DEMO_LABEL=after python -m rook.demo --scenario signature
   ROOK_DEMO_LABEL=after python -m rook.demo --scenario persistent
   ```
   Copy the four trace URLs into `evidence/neatlogs-traces.md`. Each trace carries a `version:<commit>` tag, so you can filter before and after apart.
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
   The script builds the image, creates a `nano` container service called `rook`, pushes and deploys, then prints `Rook is live at: https://rook.xxxxx.us-east-1.cs.amazonlightsail.com/`. The first deploy takes a few minutes.
4. **Check:** open that URL. The Rook dashboard loads. Click **Investigate offboarded contractor**, then **Run plan**. A new session appears in neatlogs.
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
   The first run creates the `rook` Pages project and prints a `https://rook-xxx.pages.dev` URL.
3. Point the proxy at AWS: Cloudflare dashboard → **Workers & Pages → rook → Settings → Variables and Secrets → Add**, name `ROOK_API_ORIGIN`, value the Lightsail URL from step 2 without a trailing slash. Save, then redeploy (`npx wrangler pages deploy out --project-name rook`) so the function picks it up.
4. **Check:** `https://rook-xxx.pages.dev/api/health` returns `{"ok":true,...}`, and the dashboard runs an incident end to end. Use the `pages.dev` link as the demo link in the submission.
5. Optional: attach your own domain under **Custom domains** on the Pages project.

---

## Run everything locally instead

```bash
uvicorn rook.api:create_app --factory --port 8000      # terminal 1
cd web && npm run dev                                   # terminal 2 → http://localhost:3000
# or the single container:
docker build -t rook . && docker run --rm -p 8000:8000 -e NEATLOGS_API_KEY rook   # http://localhost:8000
```

## Notes

- The demo identities (analyst, approver, viewer, other company) are built into this sandbox build, so anyone with the link can use them. Writes are limited to 30 per minute per identity.
- Data lives on the container's disk and resets on every redeploy.
- Never commit `NEATLOGS_API_KEY` or AWS keys. Lightsail stores the neatlogs key in the container's settings only.
