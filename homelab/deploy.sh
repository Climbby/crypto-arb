#!/usr/bin/env bash
# Deploy from your dev machine after pushing to GitHub.
# Usage: ./homelab/deploy.sh [user@host]
set -euo pipefail

TARGET="${1:-root@192.168.1.13}"  # CT115 project-viz (shared web CT)
APP_DIR="/opt/crypto-arb"

ssh "$TARGET" bash -s <<EOF
set -euo pipefail
cd "$APP_DIR"
git pull --ff-only origin main
cd frontend && npm ci && npm run build && cd ..
backend/.venv/bin/pip install -r backend/requirements.txt
systemctl restart crypto-arb
nginx -t && systemctl reload nginx
systemctl is-active --quiet crypto-arb && echo "Deploy OK — crypto-arb is running."
curl -sf http://127.0.0.1:8010/health && echo
EOF
