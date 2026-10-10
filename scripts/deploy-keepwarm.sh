#!/usr/bin/env bash
# Deploy the cron worker that stops the free Render instance from falling asleep,
# so the demo answers immediately whenever judging happens.
#
#   ROOK_API_ORIGIN=https://<your-service>.onrender.com ./scripts/deploy-keepwarm.sh
#
# It runs every 5 minutes and is free on the Cloudflare Workers free plan. Visit the
# worker's own address to see what it last saw. Remove it with:
#   npx wrangler@4 delete --name rook-keepwarm
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

WRANGLER="${WRANGLER:-wrangler@4}"
if [[ -z "${ROOK_API_ORIGIN:-}" ]]; then
  echo "set ROOK_API_ORIGIN to the Render address first, e.g. ROOK_API_ORIGIN=https://rook.onrender.com $0" >&2
  exit 1
fi
ROOK_API_ORIGIN="${ROOK_API_ORIGIN%/}"

cd deploy/keepwarm
npx --yes "$WRANGLER" deploy --var "ROOK_API_ORIGIN:$ROOK_API_ORIGIN"
echo
echo "Keeping $ROOK_API_ORIGIN awake every 5 minutes."
echo "Watch it with: (cd deploy/keepwarm && npx $WRANGLER tail)"
