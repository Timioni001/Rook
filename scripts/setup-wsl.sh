#!/usr/bin/env bash
# One-time setup for Ubuntu on WSL (written for Ubuntu 26.04, works on 24.04).
#
#   ./scripts/setup-wsl.sh            # system packages, Python venv, dashboard deps, cloudflared
#
# Safe to re-run. Node is only installed if missing or older than 18 (NodeSource's nodejs already
# includes npm, so npm is never installed from apt).
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

if [[ "$(pwd)" == /mnt/* ]]; then
  echo "This checkout is on the Windows drive ($(pwd))."
  echo "Clone it inside WSL instead (for example ~/Rook): builds are much faster and scripts keep their line endings."
  exit 1
fi

say "System packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv git curl ca-certificates

node_major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
if (( node_major < 18 )) || ! have npm; then
  echo "Installing Node 22 (with npm) from NodeSource."
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

say "Python environment (.venv)"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
.venv/bin/python -m pytest -q

say "Dashboard dependencies"
(cd web && npm ci --no-audit --no-fund)

if ! have cloudflared; then
  say "cloudflared (Cloudflare Tunnel, to share the local demo)"
  arch=$(dpkg --print-architecture)
  tmp=$(mktemp -d)
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb" -o "$tmp/cloudflared.deb"
  sudo apt-get install -y "$tmp/cloudflared.deb"
  rm -rf "$tmp"
fi

say "Check"
printf '%-14s %s\n' python "$(.venv/bin/python --version)" node "$(node -v)" npm "$(npm -v)"
have cloudflared && printf '%-14s %s\n' cloudflared "$(cloudflared --version 2>&1 | head -1)"
echo
echo "Done. Next: source .venv/bin/activate && ./scripts/dev.sh   (dashboard on http://localhost:3000)"
