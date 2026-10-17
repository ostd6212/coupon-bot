#!/usr/bin/env bash
# One-time server setup (Ubuntu 22.04/24.04, run as root from the project folder on the server):
#   cd /opt/coupon-bot && bash deploy/setup_server.sh
# Creates a venv, a locked-down 'couponbot' user and the systemd service 'coupon-bot'.
# Touches nothing that belongs to other services (no firewall, timezone or package removals).
# It does NOT start the bot: fill in .env first (see the printed next steps).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/coupon-bot}"
APP_USER="${APP_USER:-couponbot}"

if [[ $EUID -ne 0 ]]; then echo "Run as root (sudo bash deploy/setup_server.sh)"; exit 1; fi
cd "$APP_DIR"
[[ -f requirements.txt ]] || { echo "Missing $APP_DIR/requirements.txt. Copy the project here first."; exit 1; }
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env from the example: fill it in before starting the bot."
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

mkdir -p data
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 .env
chmod 700 "$APP_DIR"

cat > /etc/systemd/system/coupon-bot.service <<UNIT
[Unit]
Description=Carrefour coupon reminder bot
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m coupon_bot.bot
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable coupon-bot >/dev/null

cat <<MSG

Done. The bot is NOT running yet. Next steps:
  1. Fill in the secrets:   nano $APP_DIR/.env
       (TELEGRAM_BOT_TOKEN of the NEW bot, ANTHROPIC_API_KEY, ALLOWED_USER_IDS)
  2. Run the tests:         sudo -u $APP_USER $APP_DIR/.venv/bin/python -m pytest -q
  3. Start:                 systemctl start coupon-bot && journalctl -u coupon-bot -f
  4. Send the bot a coupon photo in Telegram.
MSG
