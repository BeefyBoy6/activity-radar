#!/usr/bin/env bash
# Idempotent server setup for Activity Radar. Run on the server as ubuntu:
#   bash /tmp/activity-radar/deploy/setup-server.sh
set -euo pipefail

APP_DIR=/srv/activity-radar
SRC_DIR=${1:-/tmp/activity-radar}

echo "== packages =="
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip apache2-utils nginx rsync sqlite3 certbot python3-certbot-nginx

echo "== app dir =="
sudo mkdir -p "$APP_DIR"
sudo chown ubuntu:ubuntu "$APP_DIR"
rsync -a --delete \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude '.env' \
  "$SRC_DIR"/ "$APP_DIR"/
mkdir -p "$APP_DIR/data"

echo "== venv =="
cd "$APP_DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

# Playwright for the JS-rendered sources (Rec1/Dash). Comment out if tight on disk.
.venv/bin/pip install -q playwright && .venv/bin/playwright install --with-deps chromium || \
  echo "playwright install failed — JS-rendered sources will error until installed"

echo "== seed (no-op if already seeded) =="
[ -f .env ] || cp .env.example .env
.venv/bin/python -m seed.seed

echo "== systemd =="
sudo cp deploy/activity-radar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now activity-radar
sleep 2
systemctl --no-pager status activity-radar | head -5

echo "== nginx =="
sudo cp deploy/nginx-activity-radar.conf /etc/nginx/sites-available/activity-radar
sudo ln -sf /etc/nginx/sites-available/activity-radar /etc/nginx/sites-enabled/activity-radar
if [ ! -f /etc/nginx/.htpasswd-activity-radar ]; then
  echo "!! No htpasswd yet. Create one now (you choose the password):"
  echo "   sudo htpasswd -c /etc/nginx/.htpasswd-activity-radar ryan"
fi
sudo nginx -t && sudo systemctl reload nginx

# The repo config is HTTP-only; certbot layers the HTTPS listener onto the live
# copy. Copying the repo file above wipes that layer, so re-apply the existing
# certificate on every deploy or the site silently drops to plain HTTP.
if sudo test -d /etc/letsencrypt/live/activityradar.in; then
  sudo certbot install --nginx --cert-name activityradar.in --redirect --non-interactive
fi

echo
echo "Done. Remaining manual steps:"
echo "  1. DNS: add A record for the subdomain -> this server's IP (Gandi dashboard)"
echo "  2. sudo htpasswd -c /etc/nginx/.htpasswd-activity-radar <user>   (if not done)"
echo "  3. sudo certbot --nginx -d activityradar.in       (HTTPS)"
echo "  4. edit $APP_DIR/.env for email/ntfy notifications, then:"
echo "     sudo systemctl restart activity-radar"
