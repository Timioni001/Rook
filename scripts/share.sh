#!/usr/bin/env bash
# Run the whole Rook demo on this machine and share it on a public https address via Cloudflare Tunnel.
#
#   ./scripts/share.sh            # prints https://<random>.trycloudflare.com; Ctrl+C stops everything
#
# The dashboard is built as static files and served by the API, so one address carries both.
# Every incident run on it is traced to neatlogs. The first run asks for your neatlogs project key
# (hidden while you type) and keeps it in .env on this machine only; .env is never committed.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a
if [[ -z "${NEATLOGS_API_KEY:-}" ]]; then
  echo "Paste your neatlogs project API key (from app.neatlogs.com > project settings), then press Enter."
  echo "Leave it empty to run without tracing."
  read -rs NEATLOGS_API_KEY; echo
  if [[ -n "$NEATLOGS_API_KEY" ]]; then
    umask 077; printf 'NEATLOGS_API_KEY=%s\n' "$NEATLOGS_API_KEY" >> .env
    echo "Saved to .env (only readable by you). Delete that file to forget the key."
  fi
fi
export NEATLOGS_API_KEY
PY=python3; [[ -x .venv/bin/python ]] && PY=.venv/bin/python
command -v cloudflared >/dev/null || { echo "missing: cloudflared (run ./scripts/setup-wsl.sh)"; exit 1; }

echo "Building the dashboard..."
(cd web && STATIC_EXPORT=1 npx next build >/dev/null)

ROOK_DB="${ROOK_DB:-rook-demo.db}" "$PY" -m uvicorn rook.api:create_app --factory --port 8000 &
api=$!
trap 'kill $api 2>/dev/null' EXIT INT TERM
for _ in $(seq 30); do curl -fs localhost:8000/api/health >/dev/null && break; sleep 0.5; done
echo
echo "Rook is running at http://localhost:8000 (tracing to neatlogs: $([[ -n "$NEATLOGS_API_KEY" ]] && echo on || echo off))."
echo "Opening the public link. Look below for a line with https://...trycloudflare.com and share that."
echo
cloudflared tunnel --no-autoupdate --url http://localhost:8000
