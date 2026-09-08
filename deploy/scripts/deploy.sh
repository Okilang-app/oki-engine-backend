#!/usr/bin/env bash
# Deploy from your laptop: bash deploy/scripts/deploy.sh
# Requires: SSH access to the EC2 instance

set -euo pipefail

EC2_HOST="${EC2_HOST:-ubuntu@18.159.115.152}"
EC2_KEY="${EC2_KEY:-~/.ssh/oki-engine-ec2.pem}"
APP_DIR="/opt/oki"

echo "=== Deploying to $EC2_HOST ==="

ssh -i "$EC2_KEY" "$EC2_HOST" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/oki

echo "→ Pulling latest code..."
git pull origin main

echo "→ Building images..."
docker compose -f compose.prod.yaml build api worker

echo "→ Running migrations..."
docker compose -f compose.prod.yaml run --rm api alembic upgrade head

echo "→ Restarting services..."
docker compose -f compose.prod.yaml up -d

echo "→ Pruning old images..."
docker image prune -f

echo "→ Checking health..."
sleep 5
docker compose -f compose.prod.yaml ps
echo ""
echo "✓ Deploy complete!"
REMOTE
