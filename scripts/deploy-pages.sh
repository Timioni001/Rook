#!/usr/bin/env bash
# Put the dashboard live on Cloudflare Pages from this machine, in one command.
#
#   ROOK_API_ORIGIN=https://rook-qswm.onrender.com ./scripts/deploy-pages.sh
#
# This is a direct upload. It does not use the Git integration, so none of the
# build settings in the Cloudflare dashboard apply and none of them can get it
# wrong. The agent's address is compiled into the /api proxy here, so the Pages
# project needs no environment variables either.
#
# Cloudflare sign-in: the first run prints a link to open (paste it into Windows
# if you are on WSL). Or export CLOUDFLARE_API_TOKEN with the "Cloudflare Pages:
# Edit" permission and nothing is prompted.
set -euo pipefail
cd "$(dirname "$0")/.."
root=$(pwd)
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

PROJECT="${CF_PAGES_PROJECT:-rook}"
WRANGLER="${WRANGLER:-wrangler@4}"
BRANCH="${CF_PAGES_BRANCH:-main}"
STAGE="$root/.pages-deploy"

if [[ -z "${ROOK_API_ORIGIN:-}" ]]; then
  cat >&2 <<'MSG'
ROOK_API_ORIGIN is not set, so the dashboard would have no agent behind it.

  ROOK_API_ORIGIN=https://<your-service>.onrender.com ./scripts/deploy-pages.sh

Find the address on the Render service page (deploy/README.md step A). Put the
line in .env in this repo to stop retyping it.
MSG
  exit 1
fi
ROOK_API_ORIGIN="${ROOK_API_ORIGIN%/}"

echo "==> checking the agent at $ROOK_API_ORIGIN"
if curl -fsS --max-time 120 "$ROOK_API_ORIGIN/api/health" >/dev/null; then
  echo "    healthy"
else
  echo "    warning: /api/health did not answer. Deploying anyway." >&2
fi

echo "==> building the dashboard"
bash scripts/build-pages.sh

echo "==> staging the upload with the agent's address compiled in"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -r "$root/web/out" "$STAGE/out"
cp -r "$root/web/functions" "$STAGE/functions"
# Replace the empty DEFAULT_API_ORIGIN in the staged copy only. The committed
# source keeps its empty default, so nothing in git changes.
fn="$STAGE/functions/api/[[path]].ts"
python3 - "$fn" "$ROOK_API_ORIGIN" <<'PY'
import sys, pathlib
path, origin = pathlib.Path(sys.argv[1]), sys.argv[2]
src = path.read_text()
old = "const DEFAULT_API_ORIGIN = ''"
if old not in src:
    sys.exit(f"could not find {old!r} in {path}")
path.write_text(src.replace(old, f"const DEFAULT_API_ORIGIN = {origin!r}", 1))
print(f"    /api will forward to {origin}")
PY

echo "==> making sure the Pages project exists"
npx --yes "$WRANGLER" pages project create "$PROJECT" --production-branch "$BRANCH" >/dev/null 2>&1 \
  && echo "    created project '$PROJECT'" \
  || echo "    project '$PROJECT' already exists (or needs creating by hand)"

echo "==> uploading"
# Run from the staging directory so functions/ sits beside out/ and ships too.
cd "$STAGE"
npx --yes "$WRANGLER" pages deploy out --project-name "$PROJECT" --branch "$BRANCH" --commit-dirty=true

cd "$root"
echo
echo "Now check it end to end:"
echo "  python3 scripts/check-live.py https://$PROJECT.pages.dev"
