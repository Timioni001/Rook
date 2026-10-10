#!/usr/bin/env bash
# Build the static dashboard for Cloudflare Pages (or any static host).
#
# The 2026-10-10 production build failed because `npx next build` ran at the repo
# root: there is no app/ directory there, and npx downloaded a different major of
# Next because web/node_modules did not exist. This script is immune to both --
# it installs the pinned dependencies and always builds inside web/.
#
# It works whichever "Root directory" the Pages project is set to:
#
#   Root directory "web"  ->  build command: npm run build:static   output: out
#   Root directory "/"    ->  build command: npm run build          output: out
#
# For the second case the export and the /api proxy function are mirrored to the
# repo root, so "out" and "functions" are where Pages looks for them either way.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root/web"

if [[ -f package-lock.json ]]; then
  npm ci --no-audit --no-fund
else
  npm install --no-audit --no-fund
fi

STATIC_EXPORT=1 ./node_modules/.bin/next build
[[ -f out/index.html ]] || { echo "build produced no out/index.html" >&2; exit 1; }

cd "$root"
rm -rf out functions
cp -r web/out out
cp -r web/functions functions
echo "built: web/out ($(find web/out -type f | wc -l) files), mirrored to ./out and ./functions"
