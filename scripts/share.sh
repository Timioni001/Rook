#!/usr/bin/env bash
# Run the whole Rook demo on this machine and share it on a public https address via Cloudflare Tunnel.
#
#   ./scripts/share.sh            # prints https://<random>.trycloudflare.com; Ctrl+C stops everything
#
# The dashboard is built as static files and served by the API, so one address carries both.
# Set NEATLOGS_API_KEY first to trace every incident anyone runs on the shared demo.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3; [[ -x .venv/bin/python ]] && PY=.venv/bin/python
command -v cloudflared >/dev/null || { echo "missing: cloudflared (run ./scripts/setup-wsl.sh)"; exit 1; }

echo "Building the dashboard..."
(cd web && STATIC_EXPORT=1 npx next build >/dev/null)

ROOK_DB="${ROOK_DB:-rook-demo.db}" "$PY" -m uvicorn rook.api:create_app --factory --port 8000 &
api=$!
trap 'kill $api 2>/dev/null' EXIT INT TERM
for _ in $(seq 30); do curl -fs localhost:8000/api/health >/dev/null && break; sleep 0.5; done
echo "Rook is running at http://localhost:8000. Opening a public tunnel (look for the trycloudflare.com address)..."
cloudflared tunnel --no-autoupdate --url http://localhost:8000
