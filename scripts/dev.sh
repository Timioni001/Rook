#!/usr/bin/env bash
# Run the API (port 8000) and the dashboard (port 3000) together. Ctrl+C stops both.
# Open http://localhost:3000 in your Windows browser; WSL forwards localhost automatically.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3; [[ -x .venv/bin/python ]] && PY=.venv/bin/python

"$PY" -m uvicorn rook.api:create_app --factory --port 8000 &
api=$!
trap 'kill $api 2>/dev/null' EXIT INT TERM
(cd web && npm run dev)
