#!/usr/bin/env bash
# Install LinkedIn Skills Studio on a Debian/Ubuntu VPS that already runs other things.
#
# Design rule: touch nothing that is not ours.
#   - everything lives in its own names: /opt/linkedin-studio, /var/lib/linkedin-studio,
#     /etc/linkedin-studio.env, service "linkedin-studio", user "studio"
#   - Python runs in its own virtualenv; no system pip, no system packages upgraded
#   - apt installs only what is missing (git, python3-venv, curl, openssl), no `apt-get update`
#     unless something has to be installed, and never an upgrade
#   - the port is verified free (listening sockets, Docker mappings, web-server configs) and bound
#     to 127.0.0.1 only; an explicit PORT that is taken stops the install, it is never shifted
#   - no web server is installed or reconfigured: nginx/Caddy/Apache snippets are printed for you
#
# Preview without changing anything:   DRY_RUN=1 bash install.sh   (no root needed)
# Install / update:                    sudo bash install.sh
# Remove:                              sudo bash install.sh --uninstall   (keeps data and env file)
#
# Choose the port yourself:            PORT=18080 sudo -E bash install.sh
# Overrides: REPO_URL, BRANCH (default claude/dazzling-planck-18p21t; use main once merged),
#            APP_DIR, PORT
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/francescogas/linkedin-skills.git}"
BRANCH="${BRANCH:-claude/dazzling-planck-18p21t}"
APP_DIR="${APP_DIR:-/opt/linkedin-studio}"
DATA_DIR="/var/lib/linkedin-studio"
ENV_FILE="/etc/linkedin-studio.env"
UNIT="/etc/systemd/system/linkedin-studio.service"
SVC_USER="studio"
DRY="${DRY_RUN:-0}"

say() { echo "==> $*"; }
run() { if [ "$DRY" = 1 ]; then echo "    [dry-run] $*"; else "$@"; fi; }

[ "$DRY" = 1 ] || [ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo bash install.sh   (the preview needs no root: DRY_RUN=1 bash install.sh)"; exit 1; }
command -v apt-get >/dev/null || { echo "Debian/Ubuntu only (apt-get not found)."; exit 1; }
command -v systemctl >/dev/null || { echo "systemd not found."; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  [ "$(id -u)" -eq 0 ] || { echo "Run as root."; exit 1; }
  systemctl disable --now linkedin-studio 2>/dev/null || true
  rm -f "$UNIT"; systemctl daemon-reload
  rm -rf "$APP_DIR"
  echo "Removed service and code. Kept: $DATA_DIR, $ENV_FILE, user $SVC_USER (delete by hand if you want)."
  exit 0
fi

# A port counts as taken if something listens on it now, Docker publishes it, or a web-server /
# systemd config on this machine mentions it (covers services that are stopped at the moment).
# Listening TCP ports: `ss` if present, else the kernel table (state 0A = LISTEN); no extra package.
listening_ports() {
  if command -v ss >/dev/null; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | sed 's/.*[:.]//'
  else
    cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk '$4=="0A"{split($2,a,":"); print a[2]}' |
      while read -r hex; do echo $((16#$hex)); done
  fi
}
used_ports() {
  listening_ports || true
  if command -v docker >/dev/null; then
    docker ps --format '{{.Ports}}' 2>/dev/null | grep -oE ':[0-9]+->' | tr -dc '0-9\n' || true
    echo
  fi
  grep -rhoE '(listen|proxy_pass|reverse_proxy|ProxyPass|Listen|APP_PORT|PORT)[^#]{0,40}' \
    /etc/nginx /etc/caddy /etc/apache2 /etc/systemd/system /etc/*.env 2>/dev/null | grep -oE '[0-9]{4,5}' || true
}
USED="$(used_ports | sed '/^$/d' | sort -un)"
port_busy() { echo "$USED" | grep -qx "$1"; }

say "Preflight (read only)"
echo "    OS: $(. /etc/os-release && echo "$PRETTY_NAME")   RAM free: $(free -m | awk '/Mem:/{print $7}') MB   disk free on /opt: $(df -h /opt | awk 'NR==2{print $4}')"
echo "    ports in use or referenced here: $(echo "$USED" | tr '\n' ' ')"
if [ -e "$APP_DIR" ] && [ ! -d "$APP_DIR/.git" ]; then
  echo "    $APP_DIR exists and is not a previous install of this app. Set APP_DIR to another path."; exit 1
fi
if [ -f "$UNIT" ] && ! grep -q "LinkedIn Skills Studio" "$UNIT"; then
  echo "    $UNIT exists and is not ours. Aborting."; exit 1
fi
PORT="${PORT:-}"
if [ -z "$PORT" ] && [ -f "$ENV_FILE" ]; then PORT="$(grep -E '^APP_PORT=' "$ENV_FILE" | cut -d= -f2 || true)"; fi
if [ -n "$PORT" ]; then
  case "$PORT" in *[!0-9]*) echo "    PORT must be a number."; exit 1;; esac
  # Our own running service legitimately holds its port on a re-run.
  if port_busy "$PORT" && ! { systemctl is-active --quiet linkedin-studio && grep -q "^APP_PORT=$PORT\$" "$ENV_FILE" 2>/dev/null; }; then
    echo "    port $PORT is taken. Pick another with PORT=<free port>. Nothing was changed."; exit 1
  fi
  echo "    port: $PORT (your choice, verified free)"
else
  PORT=8765; while port_busy "$PORT"; do PORT=$((PORT + 1)); done
  echo "    port: $PORT (first free from 8765; to choose your own, rerun with PORT=<n>)"
fi
MISSING=()
for pair in git:git curl:curl openssl:openssl python3:python3; do
  command -v "${pair%%:*}" >/dev/null || MISSING+=("${pair##*:}")
done
python3 -c 'import venv, ensurepip' 2>/dev/null || MISSING+=(python3-venv)
echo "    apt packages to install: ${MISSING[*]:-none}"

if [ "${#MISSING[@]}" -gt 0 ]; then
  say "Installing missing packages only"
  export DEBIAN_FRONTEND=noninteractive
  run apt-get update -qq
  run apt-get install -y -qq --no-install-recommends "${MISSING[@]}"
fi
if [ "$DRY" != 1 ]; then
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ required")'
fi

say "Service user and data directory"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  run useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"
fi
run install -d -o "$SVC_USER" -g "$SVC_USER" -m 700 "$DATA_DIR"

say "Code ($BRANCH) in $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  run git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  run git -C "$APP_DIR" checkout --quiet -B "$BRANCH" "origin/$BRANCH"
else
  run git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
run python3 -m venv "$APP_DIR/.venv"
run "$APP_DIR/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$APP_DIR/requirements.txt"

say "Configuration $ENV_FILE"
if [ -f "$ENV_FILE" ]; then
  echo "    kept existing file"
elif [ "$DRY" = 1 ]; then
  echo "    [dry-run] would create it with a generated APP_TOKEN, mode 600"
else
  umask 077
  cat > "$ENV_FILE" <<ENV
# LinkedIn Skills Studio. Keep private (chmod 600).
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
fi

say "systemd service"
if [ "$DRY" = 1 ]; then
  echo "    [dry-run] would write $UNIT, then enable and start linkedin-studio"
else
  cat > "$UNIT" <<UNITFILE
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
MemoryMax=512M

[Install]
WantedBy=multi-user.target
UNITFILE
  systemctl daemon-reload
  systemctl enable --quiet linkedin-studio
  systemctl restart linkedin-studio
  sleep 2
  systemctl is-active --quiet linkedin-studio || { journalctl -u linkedin-studio -n 30 --no-pager; exit 1; }
fi

echo
if [ "$DRY" = 1 ]; then echo "Dry run finished: nothing was changed."; exit 0; fi
echo "Running on 127.0.0.1:$PORT. Access token: $(grep '^APP_TOKEN=' "$ENV_FILE" | cut -d= -f2)"
cat <<TXT

Reach it from your PC without exposing anything:
  ssh -L $PORT:127.0.0.1:$PORT <user>@<vps-ip>     then open http://127.0.0.1:$PORT

To publish it on a domain, add ONE of these to the web server you already run (nothing was changed for you):
  nginx:   location / { proxy_pass http://127.0.0.1:$PORT; proxy_set_header Host \$host; }   (inside a server block with TLS)
  Caddy:   studio.example.com { reverse_proxy 127.0.0.1:$PORT }
  Apache:  ProxyPass / http://127.0.0.1:$PORT/   (mod_proxy, mod_proxy_http)

Next: nano $ENV_FILE   (add ANTHROPIC_API_KEY or LLM_BASE_URL)   then   systemctl restart linkedin-studio
Logs: journalctl -u linkedin-studio -f
TXT
