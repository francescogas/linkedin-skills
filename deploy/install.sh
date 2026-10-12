#!/usr/bin/env bash
# Install LinkedIn Skills Studio on a Debian/Ubuntu VPS (tested target: Aruba Cloud VPS).
# Run as root on the server:
#   curl -fsSL <raw url of this file> -o install.sh && sudo bash install.sh
# Re-running updates the code and restarts the service; secrets and data are kept.
#
# Environment overrides:
#   REPO_URL   git URL to clone      (default: https://github.com/francescogas/linkedin-skills.git)
#   BRANCH     branch to deploy      (default: claude/dazzling-planck-18p21t; use main once merged)
#   DOMAIN     public host name      (if set, Caddy is installed and serves HTTPS on it)
#   APP_DIR    install directory     (default: /opt/linkedin-studio)
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/francescogas/linkedin-skills.git}"
BRANCH="${BRANCH:-claude/dazzling-planck-18p21t}"
APP_DIR="${APP_DIR:-/opt/linkedin-studio}"
DATA_DIR="/var/lib/linkedin-studio"
ENV_FILE="/etc/linkedin-studio.env"
SVC_USER="studio"
PORT=8765

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo bash install.sh)"; exit 1; }
command -v apt-get >/dev/null || { echo "This script targets Debian/Ubuntu (apt-get)."; exit 1; }

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip curl openssl ca-certificates

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit("Python 3.9+ is required, found %d.%d" % sys.version_info[:2])
PY

echo "==> Service user and directories"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 700 "$DATA_DIR"

echo "==> Code ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet -B "$BRANCH" "origin/$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R root:root "$APP_DIR"

echo "==> Configuration ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<ENV
# LinkedIn Skills Studio. Keep this file private (chmod 600).
APP_HOST=127.0.0.1
APP_PORT=$PORT
APP_TOKEN=$(openssl rand -hex 24)
LINKEDIN_APP_DATA=$DATA_DIR

# Model: set ONE of these (or both with LLM_CHAIN=anthropic,local).
#ANTHROPIC_API_KEY=
#LLM_BASE_URL=http://127.0.0.1:11434/v1
#LLM_MODEL=llama3.1
#LLM_CHAIN=anthropic,local

# LinkedIn read / publish / images (all optional).
#APIFY_TOKEN=
#PUBLORA_API_KEY=
#LINKEDIN_PLATFORM_ID=
#PIXFARO_TOKEN=
ENV
  chmod 600 "$ENV_FILE"
  echo "    created, with a generated APP_TOKEN"
else
  echo "    kept existing file"
fi

echo "==> systemd unit"
cat > /etc/systemd/system/linkedin-studio.service <<UNIT
[Unit]
Description=LinkedIn Skills Studio
After=network-online.target
Wants=network-online.target

[Service]
User=$SVC_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python -m app serve
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --quiet linkedin-studio
systemctl restart linkedin-studio

if [ -n "${DOMAIN:-}" ]; then
  echo "==> HTTPS with Caddy for $DOMAIN"
  if ! command -v caddy >/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy.gpg
    echo "deb [signed-by=/usr/share/keyrings/caddy.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" > /etc/apt/sources.list.d/caddy.list
    apt-get update -qq && apt-get install -y -qq caddy
  fi
  printf '%s {\n    reverse_proxy 127.0.0.1:%s\n}\n' "$DOMAIN" "$PORT" > /etc/caddy/Caddyfile
  systemctl enable --quiet caddy && systemctl restart caddy
  echo "    DNS for $DOMAIN must point to this server, and ports 80/443 must be open."
fi

sleep 2
systemctl is-active --quiet linkedin-studio && echo "==> Running" || { journalctl -u linkedin-studio -n 30 --no-pager; exit 1; }
TOKEN="$(grep '^APP_TOKEN=' "$ENV_FILE" | cut -d= -f2)"
echo
if [ -n "${DOMAIN:-}" ]; then
  echo "Open:  https://$DOMAIN   (token below when the page asks)"
else
  echo "Open from your PC with an SSH tunnel:  ssh -L $PORT:127.0.0.1:$PORT <user>@<vps-ip>   then http://127.0.0.1:$PORT"
fi
echo "Access token: $TOKEN"
echo "Add your model key: nano $ENV_FILE   then   systemctl restart linkedin-studio"
echo "Logs: journalctl -u linkedin-studio -f"
