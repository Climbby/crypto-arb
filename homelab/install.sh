#!/usr/bin/env bash
# First-time setup on a Proxmox LXC. Run as root on the target container.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/crypto-arb}"
REPO_URL="${REPO_URL:-https://github.com/Climbby/crypto-arb.git}"
BRANCH="${BRANCH:-main}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required (v20+) to build the frontend. Install it first."
  exit 1
fi

if ! command -v nginx >/dev/null 2>&1; then
  echo "Installing nginx..."
  apt-get update && apt-get install -y nginx
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  echo "Repo already exists at $APP_DIR — pulling latest..."
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
fi

cd "$APP_DIR"

# Frontend production build (same-origin API; empty VITE_API_BASE)
(
  cd frontend
  npm ci
  npm run build
)

# Backend venv
python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -r backend/requirements.txt
mkdir -p backend/data

if [[ ! -f backend/.env ]]; then
  cp backend/.env.example backend/.env
  # Faster default poll on the server
  sed -i 's/^POLL_INTERVAL_SECONDS=.*/POLL_INTERVAL_SECONDS=1/' backend/.env || true
fi

cp homelab/nginx.conf /etc/nginx/sites-available/crypto-arb.conf
ln -sf /etc/nginx/sites-available/crypto-arb.conf /etc/nginx/sites-enabled/crypto-arb.conf
nginx -t && systemctl reload nginx

cp homelab/crypto-arb.service /etc/systemd/system/crypto-arb.service
systemctl daemon-reload
systemctl enable crypto-arb
systemctl restart crypto-arb

echo ""
echo "ArbWatch is running on http://127.0.0.1:8010 (nginx :8081 → app)."
echo "LAN test: curl -s http://127.0.0.1:8081/health"
echo "Next: Cloudflare Tunnel public hostname arb.guessitgame.me → http://<CT-LAN-IP>:8081"
echo "See homelab/cloudflare-tunnel.md"
