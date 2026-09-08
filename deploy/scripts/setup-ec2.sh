#!/usr/bin/env bash
# One-time EC2 setup script for Ubuntu 24.04+.
# Usage: bash setup-ec2.sh

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/YOUR_ORG/oki-engine-backend.git}"
APP_DIR="/opt/oki"

echo "=== 1. System packages ==="
sudo apt-get update -q
sudo apt-get install -y --no-install-recommends \
  git curl jq unzip ca-certificates gnupg lsb-release

echo "=== 2. Docker ==="
if ! command -v docker &>/dev/null; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -q
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ubuntu
echo "Docker $(docker --version)"

echo "=== 3. Clone repo ==="
sudo mkdir -p "$APP_DIR"
sudo chown ubuntu:ubuntu "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "=== 4. Certbot (Let's Encrypt) ==="
if ! command -v certbot &>/dev/null; then
  sudo apt-get install -y snapd
  sudo snap install --classic certbot
  sudo ln -sf /snap/bin/certbot /usr/bin/certbot
fi

sudo mkdir -p /var/www/certbot /etc/letsencrypt

echo "=== 5. .env file ==="
if [ ! -f "$APP_DIR/.env.prod" ]; then
  cp "$APP_DIR/.env.prod.example" "$APP_DIR/.env.prod"
  echo ""
  echo "IMPORTANT: Edit $APP_DIR/.env.prod with your real secrets before starting services!"
fi

echo "=== 6. Systemd service (auto-start on reboot) ==="
sudo tee /etc/systemd/system/oki.service > /dev/null <<EOF
[Unit]
Description=OKI Engine
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env.prod
ExecStart=docker compose -f compose.prod.yaml up -d --wait
ExecStop=docker compose -f compose.prod.yaml down
TimeoutStartSec=300
User=ubuntu

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable oki.service

echo "=== 7. Certbot renewal cron ==="
echo "0 3 * * * root certbot renew --quiet && docker compose -f $APP_DIR/compose.prod.yaml exec nginx nginx -s reload" \
  | sudo tee /etc/cron.d/certbot-renew > /dev/null

echo ""
echo "======================================================"
echo "Setup complete! Next steps:"
echo ""
echo "1. Get SSL certs (DNS must already point here):"
echo "   sudo certbot certonly --standalone \\"
echo "     -d oki-api.ugcflow.online -d oki-auth.ugcflow.online \\"
echo "     --email your@email.com --agree-tos --non-interactive"
echo ""
echo "2. Edit secrets:"
echo "   nano $APP_DIR/.env.prod"
echo ""
echo "3. Build & start everything:"
echo "   cd $APP_DIR && docker compose -f compose.prod.yaml up -d --build"
echo "======================================================"
