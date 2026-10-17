#!/usr/bin/env bash
# Update the bot on the server from GitHub (run as root on the server):
#   bash /opt/coupon-bot/deploy/update.sh
# Needs the read-only deploy key set up once (see README, "Оновлення").
# .env, the venv and data/ (database, photos, logs) are untouched.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/coupon-bot}"
APP_USER="${APP_USER:-couponbot}"
BRANCH="${BRANCH:-main}"

if [[ $EUID -ne 0 ]]; then echo "Run as root"; exit 1; fi
cd "$APP_DIR"
# the folder belongs to the service user, root must be told it is fine to run git here
git config --global --get-all safe.directory | grep -qx "$APP_DIR" || git config --global --add safe.directory "$APP_DIR"
git fetch origin "$BRANCH"
git reset --hard FETCH_HEAD
.venv/bin/pip install --quiet -r requirements.txt
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 .env
if systemctl is-enabled --quiet coupon-bot 2>/dev/null; then
  systemctl restart coupon-bot
  sleep 2
  systemctl --no-pager --lines=0 status coupon-bot | head -4
else
  echo "Service coupon-bot is not installed; run deploy/setup_server.sh first."
fi
echo "Updated to: $(git log --oneline -1)"
