#!/usr/bin/env bash
# Put the dashboard live on Cloudflare Pages from this machine, in one command.
#
#   ROOK_API_ORIGIN=https://<your-service>.onrender.com ./scripts/deploy-pages.sh
#
# This is a direct upload: it does not use the Git integration, so no build settings
# in the Cloudflare dashboard can get it wrong. Use it when the dashboard build fails
# or when you want the live site updated right now.
#
# Cloudflare sign-in: the first run opens a browser window (in WSL it prints a link to
# paste into Windows). Alternatively export CLOUDFLARE_API_TOKEN with the
# "Cloudflare Pages: Edit" permission and nothing is prompted.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

PROJECT="${CF_PAGES_PROJECT:-rook}"
WRANGLER="${WRANGLER:-wrangler@4}"

if [[ -z "${ROOK_API_ORIGIN:-}" ]]; then
  cat >&2 <<'MSG'
ROOK_API_ORIGIN is not set, so the dashboard would have no agent behind it.

  ROOK_API_ORIGIN=https://<your-service>.onrender.com ./scripts/deploy-pages.sh

Find the address on the Render service page (deploy/README.md step A). Add the line
to .env in this repo to stop retyping it.
MSG
  exit 1
fi
ROOK_API_ORIGIN="${ROOK_API_ORIGIN%/}"

echo "==> checking the agent at $ROOK_API_ORIGIN"
if ! curl -fsS --max-time 120 "$ROOK_API_ORIGIN/api/health" >/dev/null; then
  echo "warning: $ROOK_API_ORIGIN/api/health did not answer. Deploying anyway." >&2
fi

echo "==> building the dashboard"
bash scripts/build-pages.sh

echo "==> telling the Pages project where the agent is"
# Stored on the project, so it survives later deploys. Harmless if it is already set.
printf '%s' "$ROOK_API_ORIGIN" | npx --yes "$WRANGLER" pages secret put ROOK_API_ORIGIN \
  --project-name "$PROJECT" >/dev/null 2>&1 \
  || echo "   could not set it from here; set ROOK_API_ORIGIN in the Pages project's environment variables" >&2

echo "==> uploading"
# Run from web/, where functions/ sits beside out/, so the /api proxy ships with the site.
cd web && npx --yes "$WRANGLER" pages deploy out \
  --project-name "$PROJECT" --branch main --commit-dirty=true
