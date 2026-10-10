#!/usr/bin/env bash
# One-time setup for Ubuntu on WSL (written for Ubuntu 26.04, works on 24.04).
#
#   ./scripts/setup-wsl.sh            # system packages, Python venv, web deps, AWS CLI, lightsailctl
#   SKIP_AWS=1 ./scripts/setup-wsl.sh # local development only
#
# Docker is not installed here: on WSL the simplest route is Docker Desktop for Windows with
# "WSL integration" switched on for this distro. The script checks for it at the end.
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
sudo apt-get install -y python3 python3-venv python3-pip git curl unzip ca-certificates nodejs npm

node_major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
if (( node_major < 18 )); then
  echo "Node $(node -v 2>/dev/null || echo missing) is too old for the dashboard; installing Node 22 from NodeSource."
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

if [[ "${SKIP_AWS:-0}" != "1" ]]; then
  arch=$(uname -m)
  if ! have aws; then
    say "AWS CLI v2"
    tmp=$(mktemp -d)
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${arch}.zip" -o "$tmp/awscliv2.zip"
    unzip -q "$tmp/awscliv2.zip" -d "$tmp"
    sudo "$tmp/aws/install"
    rm -rf "$tmp"
  fi
  if ! have lightsailctl; then
    say "Lightsail plugin (lightsailctl)"
    [[ "$arch" == "aarch64" ]] && la=arm64 || la=amd64
    sudo curl -fsSL "https://s3.us-west-2.amazonaws.com/lightsailctl/latest/linux-${la}/lightsailctl" \
      -o /usr/local/bin/lightsailctl
    sudo chmod +x /usr/local/bin/lightsailctl
  fi
fi

say "Check"
printf '%-14s %s\n' python "$(.venv/bin/python --version)" node "$(node -v)" npm "$(npm -v)"
have aws && printf '%-14s %s\n' aws "$(aws --version 2>&1)"
have lightsailctl && printf '%-14s %s\n' lightsailctl "$(lightsailctl --version 2>&1 | head -1)"
if have docker && docker info >/dev/null 2>&1; then
  printf '%-14s %s\n' docker "$(docker --version)"
else
  echo "docker         not reachable. Install Docker Desktop for Windows, then Settings > Resources >"
  echo "               WSL integration > turn on this distro, and open a new WSL terminal."
fi
echo
echo "Done. Next: source .venv/bin/activate && ./scripts/dev.sh   (dashboard on http://localhost:3000)"
