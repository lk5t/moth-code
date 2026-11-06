#!/usr/bin/env bash
# MOTH Cloud — one-time server installation (or adoption of an existing MOTH Server).
#
# Run it from an extracted moth-cloud-<version> bundle:
#
#   tar xzf moth-cloud-0.3.0.tar.gz && cd moth-cloud-0.3.0
#   ./deploy/install-server.sh --domain moth.example.com
#
# After this, MOTH Cloud runs on its own: it survives SSH disconnects, crashes and reboots, backs
# itself up daily, and the update agent installs approved, signed releases automatically.
#
# Works with or without administrator rights. Steps that need root (HTTPS proxy on ports 80/443,
# firewall, system services) are done when possible, otherwise printed for an administrator.
# Nothing existing is deleted: an existing data directory is adopted in place after a verified backup.
set -euo pipefail

BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cat "$BUNDLE/VERSION")"
DOMAIN=""
HOME_DIR=""
PORT=8900
SOURCE="github:lk5t/moth-code"
TOKEN_FILE=""
ADOPT_DATA=""
ADOPT_ENV=""
PUBKEY=""
CHANNEL="stable"
PY="${PYTHON:-python3}"
SUPERVISOR="auto"
ENVIRONMENT="production"
REPLACE_RUNNING=0
NO_START=0
SYSTEM_SITE=False

usage() {
  sed -n '2,15p' "$0"
  cat <<EOF
Options:
  --domain NAME            public HTTPS name of MOTH Cloud (e.g. moth.example.com)
  --home DIR               installation directory (default: /opt/moth-cloud as root, ~/moth-cloud otherwise)
  --adopt-data DIR         use an existing MOTH Server data directory (accounts, models, database) in place
  --adopt-env FILE         import settings (SMTP, Stripe, database URL…) from an existing env file
  --release-source SRC     github:OWNER/REPO (default) or dir:/path/to/releases
  --github-token-file F    read-only GitHub token for a private repository (stored with mode 600)
  --pubkey B64             release signing public key (default: deploy/release-signing.pub in the bundle)
  --channel stable|beta    update channel (default stable)
  --port N                 local port of the API (default 8900; only 127.0.0.1 listens)
  --supervisor MODE        auto | systemd-system | systemd-user | cron
  --environment NAME       production | staging | development
  --replace-running        stop a MOTH Server already listening on the port (same user only)
  --no-start               install and configure, but don't start services
  --use-system-packages    reuse Python packages installed system-wide (e.g. PyTorch installed by an admin)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --home) HOME_DIR="$2"; shift 2 ;;
    --adopt-data) ADOPT_DATA="$2"; shift 2 ;;
    --adopt-env) ADOPT_ENV="$2"; shift 2 ;;
    --release-source) SOURCE="$2"; shift 2 ;;
    --github-token-file) TOKEN_FILE="$2"; shift 2 ;;
    --pubkey) PUBKEY="$2"; shift 2 ;;
    --channel) CHANNEL="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --supervisor) SUPERVISOR="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --replace-running) REPLACE_RUNNING=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --use-system-packages) SYSTEM_SITE=True; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1"; usage; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
ADMIN_STEPS=()
admin() { ADMIN_STEPS+=("$*"); }

echo "MOTH Cloud $VERSION — server installation"
echo
echo "1. Checking requirements"
[ "$(uname -s)" = "Linux" ] || die "MOTH Cloud servers run on Linux"
command -v "$PY" >/dev/null || die "Python 3.10+ is required ($PY not found)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10 or newer is required (found $("$PY" -V 2>&1))"
ok "$("$PY" -V 2>&1)"
"$PY" -c 'import venv, sqlite3, ensurepip' 2>/dev/null \
  || die "the Python venv module is missing — an administrator can install it with: apt-get install python3-venv"
ok "Python venv and sqlite3 modules"
IS_ROOT=0; CAN_SUDO=0
[ "$(id -u)" = "0" ] && IS_ROOT=1
if [ $IS_ROOT = 0 ] && command -v sudo >/dev/null && sudo -n true 2>/dev/null; then CAN_SUDO=1; fi
if [ $IS_ROOT = 1 ]; then ok "running as root"; elif [ $CAN_SUDO = 1 ]; then ok "passwordless sudo available";
else warn "no administrator rights: user-level installation; admin-only steps will be listed at the end"; fi
[ -n "$HOME_DIR" ] || { [ $IS_ROOT = 1 ] && HOME_DIR=/opt/moth-cloud || HOME_DIR="$HOME/moth-cloud"; }
mkdir -p "$HOME_DIR"
HOME_DIR="$(cd "$HOME_DIR" && pwd)"
FREE=$(df -Pk "$HOME_DIR" | awk 'NR==2 {print $4}')
[ "$FREE" -gt $((5 * 1024 * 1024)) ] || die "at least 5 GB of free disk space is needed in $HOME_DIR"
ok "$((FREE / 1024 / 1024)) GB free in $HOME_DIR"
if [ -z "$PUBKEY" ] && [ -f "$BUNDLE/agent/release-signing.pub" ]; then PUBKEY="$(cat "$BUNDLE/agent/release-signing.pub")"; fi
[ -n "$PUBKEY" ] || die "no release signing public key (pass --pubkey)"
ok "release signing key ${PUBKEY:0:12}…"

echo
echo "2. Configuration ($HOME_DIR)"
mkdir -p "$HOME_DIR"/{config,data,releases,runtime,backups,logs,run,state,agent,bin,downloads}
chmod 700 "$HOME_DIR/config" "$HOME_DIR/backups"
DATA_DIR="$HOME_DIR/data"
if [ -n "$ADOPT_DATA" ]; then
  [ -d "$ADOPT_DATA" ] || die "--adopt-data $ADOPT_DATA does not exist"
  DATA_DIR="$(cd "$ADOPT_DATA" && pwd)"
  ok "adopting existing data in place: $DATA_DIR (nothing is moved or deleted)"
fi
ENV_FILE="$HOME_DIR/config/moth.env"
umask 077
if [ ! -f "$ENV_FILE" ]; then
  {
    echo "# MOTH Cloud configuration (secrets: keep this file private, mode 600)"
    if [ -n "$ADOPT_ENV" ]; then
      [ -f "$ADOPT_ENV" ] || die "--adopt-env $ADOPT_ENV does not exist"
      grep -E '^[A-Z_][A-Z0-9_]*=' "$ADOPT_ENV" | grep -vE '^(MOTH_SERVER_DATA_DIR|MOTH_AGENT_TOKEN_FILE|MOTH_RELEASE_PUBKEY|MOTH_SERVER_PORT|MOTH_ENVIRONMENT)=' || true
    fi
    echo "MOTH_SERVER_DATA_DIR=$DATA_DIR"
    [ -n "$DOMAIN" ] && ! grep -qs '^MOTH_SERVER_PUBLIC_URL=' "${ADOPT_ENV:-/dev/null}" && echo "MOTH_SERVER_PUBLIC_URL=https://$DOMAIN"
    [ -n "$DOMAIN" ] && echo "MOTH_TRUST_PROXY_HEADERS=true"
    [ -z "$DOMAIN" ] && ! grep -qs '^MOTH_SERVER_PUBLIC_URL=' "${ADOPT_ENV:-/dev/null}" && echo "MOTH_SERVER_PUBLIC_URL=http://127.0.0.1:$PORT"
    echo "MOTH_AGENT_TOKEN_FILE=$HOME_DIR/config/agent.token"
    echo "MOTH_RELEASE_PUBKEY=$PUBKEY"
    echo "MOTH_SERVER_PORT=$PORT"
    echo "MOTH_ENVIRONMENT=$ENVIRONMENT"
  } > "$ENV_FILE"
  ok "created config/moth.env"
else
  ok "keeping existing config/moth.env"
fi
[ -f "$HOME_DIR/config/agent.token" ] || "$PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$HOME_DIR/config/agent.token"
if [ -n "$TOKEN_FILE" ]; then
  install -m 600 "$TOKEN_FILE" "$HOME_DIR/config/github.token"
  ok "GitHub release token stored (mode 600)"
fi
GH_TOKEN_PATH=""; [ -f "$HOME_DIR/config/github.token" ] && GH_TOKEN_PATH="$HOME_DIR/config/github.token"

# supervisor
if [ "$SUPERVISOR" = "auto" ]; then
  if [ $IS_ROOT = 1 ] && command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then SUPERVISOR=systemd-system
  elif command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then SUPERVISOR=systemd-user
  else SUPERVISOR=cron; fi
fi
TORCH_INDEX="https://download.pytorch.org/whl/cpu"
command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1 && TORCH_INDEX="https://download.pytorch.org/whl/cu128"
"$PY" - "$HOME_DIR/config/agent.json" <<EOF
import json, sys, os
p = sys.argv[1]
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg.update({"source": "$SOURCE", "channel": "$CHANNEL", "pubkey": "$PUBKEY", "server_url": "http://127.0.0.1:$PORT",
            "supervisor": "$SUPERVISOR", "python": "$(command -v "$PY")", "torch_index": cfg.get("torch_index", "$TORCH_INDEX"),
            "venv_system_site_packages": $SYSTEM_SITE})
if "$GH_TOKEN_PATH":
    cfg["github_token_file"] = "$GH_TOKEN_PATH"
json.dump(cfg, open(p, "w"), indent=2)
EOF
ok "update agent: source $SOURCE, channel $CHANNEL, supervisor $SUPERVISOR"
umask 022

subst() {
  sed -e "s|@HOME@|$HOME_DIR|g" -e "s|@PORT@|$PORT|g" -e "s|@DOMAIN@|$DOMAIN|g" -e "s|@PYTHON@|$(command -v "$PY")|g" \
      -e "s|@SERVICE_USER@|$2|g" -e "s|@WANTED_BY@|$3|g" "$BUNDLE/deploy/templates/$1"
}
for f in moth-server-run moth-agent-run moth; do subst "$f.in" "" "" > "$HOME_DIR/bin/$f"; chmod 755 "$HOME_DIR/bin/$f"; done
ok "launch scripts and the 'moth' operator command in $HOME_DIR/bin"

echo
echo "3. Existing server"
if curl -fsS -m 3 "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then
  RUNNING=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/v1/health" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("version"))')
  OLDPID=$(ss -Htlnp "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true)
  if [ -z "$OLDPID" ]; then  # no ss: find the listening socket's owner through /proc (same user only)
    OLDPID=$("$PY" - "$PORT" <<'EOF2'
import os, sys
port = int(sys.argv[1]); inodes = set()
for f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        for line in open(f).read().splitlines()[1:]:
            parts = line.split()
            if int(parts[1].split(":")[1], 16) == port and parts[3] == "0A":
                inodes.add(parts[9])
    except OSError:
        pass
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            link = os.readlink(f"/proc/{pid}/fd/{fd}")
            if link.startswith("socket:[") and link[8:-1] in inodes:
                print(pid); raise SystemExit
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        continue
EOF2
)
  fi
  if [ -f "$HOME_DIR/run/server.pid" ] && [ "$OLDPID" = "$(cat "$HOME_DIR/run/server.pid")" ]; then
    ok "MOTH Cloud $RUNNING managed by this installation is running"
  elif [ $REPLACE_RUNNING = 1 ] && [ -n "$OLDPID" ]; then
    kill "$OLDPID" && sleep 3 && ok "stopped the previous MOTH Server $RUNNING (pid $OLDPID)"
  else
    die "a MOTH Server ($RUNNING) is already running on port $PORT${OLDPID:+ (pid $OLDPID)}. Stop it (or re-run with --replace-running) — its data is adopted with --adopt-data"
  fi
else
  ok "port $PORT is free"
fi

echo
echo "4. Installing MOTH Cloud $VERSION (Python runtime, database)"
MOTH_HOME="$HOME_DIR" "$PY" "$BUNDLE/agent/moth_agent.py" install-local "$BUNDLE" | tail -3
ok "release $VERSION installed and database migrated (backup taken first if it existed)"

echo
echo "5. Supervision, restarts and backups"
CRON_LINES="* * * * * $HOME_DIR/bin/moth supervise >/dev/null 2>&1
@reboot $HOME_DIR/bin/moth supervise >/dev/null 2>&1"
BACKUP_LINE="17 3 * * * $HOME_DIR/bin/moth backup >> $HOME_DIR/logs/backup.log 2>&1"
CRON_OK=1
install_cron() {
  if ! command -v crontab >/dev/null; then
    CRON_OK=0
    admin "sudo apt-get install -y cron && sudo systemctl enable --now cron     # then re-run this installer (as $(id -un)) so MOTH Cloud restarts after crashes and reboots and backs up daily"
    return 1
  fi
  (crontab -l 2>/dev/null | grep -v "$HOME_DIR/bin/moth" || true; echo "$1") | crontab -
}
case "$SUPERVISOR" in
  systemd-system)
    id moth >/dev/null 2>&1 || useradd --system --home-dir "$HOME_DIR" --shell /usr/sbin/nologin moth
    chown -R moth:moth "$HOME_DIR"
    [ "$DATA_DIR" != "$HOME_DIR/data" ] && chown -R moth:moth "$DATA_DIR"
    for u in moth-server moth-agent; do subst "$u.service.in" "User=moth" "multi-user.target" > "/etc/systemd/system/$u.service"; done
    systemctl daemon-reload
    systemctl enable moth-server moth-agent >/dev/null
    su -s /bin/sh moth -c "(crontab -l 2>/dev/null | grep -v '$HOME_DIR/bin/moth' || true; echo '$BACKUP_LINE') | crontab -" 2>/dev/null \
      || install_cron "$BACKUP_LINE" || true
    ok "systemd services moth-server and moth-agent (user 'moth', start at boot, restart on failure)"
    ;;
  systemd-user)
    mkdir -p "$HOME/.config/systemd/user"
    for u in moth-server moth-agent; do subst "$u.service.in" "" "default.target" > "$HOME/.config/systemd/user/$u.service"; done
    systemctl --user daemon-reload
    systemctl --user enable moth-server moth-agent >/dev/null
    if loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
      ok "systemd user services (lingering enabled: they run without a login and after reboots)"
      install_cron "$BACKUP_LINE" || true
    elif loginctl enable-linger "$USER" 2>/dev/null; then
      ok "systemd user services (lingering enabled now)"
      install_cron "$BACKUP_LINE" || true
    else
      warn "systemd user services stop at logout until lingering is enabled; adding the cron supervisor as a fallback"
      admin "sudo loginctl enable-linger $USER     # keep MOTH Cloud running without a login and after reboots"
      install_cron "$CRON_LINES
$BACKUP_LINE" || true
    fi
    ;;
  cron)
    if install_cron "$CRON_LINES
$BACKUP_LINE"; then
      ok "cron supervisor: checks every minute and at boot, restarts MOTH Cloud and the agent if they stop"
    fi
    ;;
esac
if [ "$CRON_OK" = 1 ]; then
  ok "daily verified backup at 03:17 into $HOME_DIR/backups (keeps the latest 5)"
else
  warn "cron is not installed: MOTH Cloud runs now, but it will NOT restart after a crash or reboot, and daily backups"
  warn "are not scheduled, until an administrator installs cron and you run this installer again (see the end)"
fi

echo
echo "6. HTTPS"
if [ -n "$DOMAIN" ]; then
  subst Caddyfile.in "" "" > "$HOME_DIR/config/Caddyfile"
  ok "reverse proxy configuration: $HOME_DIR/config/Caddyfile (agent API and API docs blocked publicly)"
  if [ $IS_ROOT = 1 ] && command -v caddy >/dev/null; then
    install -m 644 "$HOME_DIR/config/Caddyfile" /etc/caddy/Caddyfile && systemctl reload caddy 2>/dev/null || systemctl restart caddy
    ok "Caddy configured for https://$DOMAIN"
  else
    admin "install Caddy (https://caddyserver.com/docs/install) and run: sudo cp $HOME_DIR/config/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy"
  fi
  if [ $IS_ROOT = 1 ] && command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q active; then
    ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && ok "firewall: ports 80 and 443 open (the API port $PORT stays private)"
  else
    admin "firewall: allow inbound TCP 80 and 443 only (e.g. sudo ufw allow 80/tcp && sudo ufw allow 443/tcp); keep port $PORT closed"
  fi
  admin "DNS: point $DOMAIN (A/AAAA record) at this server's public IP address"
else
  warn "no --domain given: MOTH Cloud listens on 127.0.0.1:$PORT only. Re-run with --domain to enable HTTPS."
fi

if [ $NO_START = 1 ]; then echo; echo "Installed (not started)."; exit 0; fi
echo
echo "7. Starting and validating"
case "$SUPERVISOR" in
  systemd-system) systemctl restart moth-server moth-agent ;;
  systemd-user) systemctl --user restart moth-server moth-agent ;;
  cron) "$HOME_DIR/bin/moth" supervise ;;
esac
for i in $(seq 1 90); do
  H=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/v1/health" 2>/dev/null || true)
  [ -n "$H" ] && echo "$H" | grep -q "\"version\":\"$VERSION\"" && break
  sleep 2
done
echo "$H" | grep -q "\"version\":\"$VERSION\"" || die "MOTH Cloud did not start; see $HOME_DIR/logs/ (or journalctl -u moth-server)"
ok "MOTH Cloud $VERSION is healthy on 127.0.0.1:$PORT"
if ss -Htln 2>/dev/null | grep -q "0.0.0.0:$PORT\|\[::\]:$PORT"; then warn "port $PORT is listening publicly"; else ok "API port is private (127.0.0.1 only)"; fi
if [ -n "$DOMAIN" ] && curl -fsS -m 10 "https://$DOMAIN/v1/health" >/dev/null 2>&1; then ok "https://$DOMAIN is reachable with a valid certificate"
elif [ -n "$DOMAIN" ]; then warn "https://$DOMAIN is not reachable yet (finish the administrator steps below)"; fi
OWNER=$(MOTH_HOME="$HOME_DIR" "$HOME_DIR/bin/moth" server migrate --plan >/dev/null 2>&1; "$PY" - "$DATA_DIR/moth-server.db" <<'EOF'
import sqlite3, sys, os
p = sys.argv[1]
if not os.path.exists(p): print("unknown"); raise SystemExit
try:
    print("yes" if sqlite3.connect(p).execute("select 1 from users where role='owner'").fetchone() else "no")
except sqlite3.Error:
    print("unknown")
EOF
)

echo
echo "Done. MOTH Cloud now runs and updates itself; you can close this terminal."
[ "$OWNER" = "no" ] && echo "  • Create the Owner account once (you choose the password): $HOME_DIR/bin/moth server init-owner"
echo "  • Status (exceptional cases only): $HOME_DIR/bin/moth status"
if [ ${#ADMIN_STEPS[@]} -gt 0 ]; then
  echo
  echo "Administrator steps still needed (they require root):"
  for s in "${ADMIN_STEPS[@]}"; do echo "  - $s"; done
fi
