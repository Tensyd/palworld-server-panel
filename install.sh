#!/usr/bin/env bash
set -Eeuo pipefail

PANEL_USER="${PANEL_USER:-demo}"
PANEL_HOME="${PANEL_HOME:-/home/${PANEL_USER}}"
PANEL_DIR="${PANEL_DIR:-${PANEL_HOME}/palworld-panel}"
PALWORLD_DIR="${PALWORLD_DIR:-${PANEL_HOME}/palworld}"
STEAMCMD_DIR="${STEAMCMD_DIR:-${PANEL_HOME}/steamcmd}"
PANEL_PORT="${PANEL_PORT:-8080}"
INSTALL_PALWORLD="${INSTALL_PALWORLD:-true}"
PANEL_REPO_URL="${PANEL_REPO_URL:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash install.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

log() {
  printf '[palworld-panel] %s\n' "$*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

if ! need_cmd apt-get; then
  echo "This installer currently supports Ubuntu/Debian with apt-get." >&2
  exit 1
fi

log "Installing base dependencies"
apt-get update
apt-get install -y ca-certificates curl tar python3 python3-venv gunicorn sudo lib32gcc-s1 lib32stdc++6

if ! id "${PANEL_USER}" >/dev/null 2>&1; then
  log "Creating user ${PANEL_USER}"
  useradd -m -s /bin/bash "${PANEL_USER}"
fi

mkdir -p "${PANEL_HOME}" "${PANEL_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/app.py" && -f "${SCRIPT_DIR}/panel_install.py" ]]; then
  log "Installing panel files from local checkout"
  rsync -a --exclude '__pycache__' "${SCRIPT_DIR}/" "${PANEL_DIR}/" 2>/dev/null || cp -a "${SCRIPT_DIR}/." "${PANEL_DIR}/"
elif [[ -n "${PANEL_REPO_URL}" ]]; then
  log "Cloning panel repository"
  apt-get install -y git
  if [[ -d "${PANEL_DIR}/.git" ]]; then
    git -C "${PANEL_DIR}" pull --ff-only
  else
    rm -rf "${PANEL_DIR}"
    git clone "${PANEL_REPO_URL}" "${PANEL_DIR}"
  fi
else
  echo "Run install.sh from the project checkout, or set PANEL_REPO_URL for curl|bash installs." >&2
  exit 1
fi

chown -R "${PANEL_USER}:${PANEL_USER}" "${PANEL_DIR}"
chmod 755 "${PANEL_DIR}/panel_install.py" "${PANEL_DIR}/panel_update.py" 2>/dev/null || true

# Root runs the installer on behalf of the panel account (sudoers allows it to
# start palworld-panel-install.service), so the executed copy must live outside
# the tree that account owns. Keep one root-owned copy and point the unit at it.
ROOT_EXEC_DIR="${ROOT_EXEC_DIR:-/usr/local/lib/palworld-panel}"
install -d -o root -g root -m 755 "${ROOT_EXEC_DIR}"
install -o root -g root -m 755 "${PANEL_DIR}/panel_install.py" "${ROOT_EXEC_DIR}/panel_install.py"

log "Preparing /etc/palworld-panel.env"
ADMIN_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)"
SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"

if [[ ! -f /etc/palworld-panel.env ]]; then
  cat >/etc/palworld-panel.env <<EOF
PANEL_PORT=${PANEL_PORT}
PANEL_USER=${PANEL_USER}
PANEL_HOME=${PANEL_HOME}
PANEL_DIR=${PANEL_DIR}
PALWORLD_DIR=${PALWORLD_DIR}
PALWORLD_SERVICE=palworld.service
PALWORLD_BACKEND=systemd
RCON_HOST=127.0.0.1
RCON_PORT=25575
RCON_PASSWORD=${ADMIN_PASSWORD}
PANEL_SECRET_KEY=${SECRET_KEY}
STEAMCMD=${STEAMCMD_DIR}/steamcmd.sh
PALWORLD_APP_ID=2394010
PALWORLD_DEPOT_ID=2394012
AUTO_UPDATE_ENABLED=false
MOD_LIBRARY_ROOT=${PANEL_DIR}/mod-library
MOD_UPLOAD_MAX_BYTES=1073741824
PALWORLD_MOD_MODE=pak-safe
PANEL_INSTALL_SCRIPT=${PANEL_DIR}/panel_install.py
PANEL_UPDATE_SCRIPT=${PANEL_DIR}/panel_update.py
PANEL_ASSET_VERSION=$(date +%s)
EOF
else
  grep -q '^PANEL_USER=' /etc/palworld-panel.env || echo "PANEL_USER=${PANEL_USER}" >>/etc/palworld-panel.env
  grep -q '^PANEL_HOME=' /etc/palworld-panel.env || echo "PANEL_HOME=${PANEL_HOME}" >>/etc/palworld-panel.env
  grep -q '^PANEL_DIR=' /etc/palworld-panel.env || echo "PANEL_DIR=${PANEL_DIR}" >>/etc/palworld-panel.env
  grep -q '^PALWORLD_DIR=' /etc/palworld-panel.env || echo "PALWORLD_DIR=${PALWORLD_DIR}" >>/etc/palworld-panel.env
  grep -q '^PALWORLD_BACKEND=' /etc/palworld-panel.env || echo "PALWORLD_BACKEND=systemd" >>/etc/palworld-panel.env
  grep -q '^MOD_LIBRARY_ROOT=' /etc/palworld-panel.env || echo "MOD_LIBRARY_ROOT=${PANEL_DIR}/mod-library" >>/etc/palworld-panel.env
  grep -q '^MOD_UPLOAD_MAX_BYTES=' /etc/palworld-panel.env || echo "MOD_UPLOAD_MAX_BYTES=1073741824" >>/etc/palworld-panel.env
  grep -q '^PALWORLD_MOD_MODE=' /etc/palworld-panel.env || echo "PALWORLD_MOD_MODE=pak-safe" >>/etc/palworld-panel.env
  grep -q '^STEAMCMD=' /etc/palworld-panel.env || echo "STEAMCMD=${STEAMCMD_DIR}/steamcmd.sh" >>/etc/palworld-panel.env
  grep -q '^PANEL_ASSET_VERSION=' /etc/palworld-panel.env && sed -i "s/^PANEL_ASSET_VERSION=.*/PANEL_ASSET_VERSION=$(date +%s)/" /etc/palworld-panel.env || echo "PANEL_ASSET_VERSION=$(date +%s)" >>/etc/palworld-panel.env
fi
chown root:root /etc/palworld-panel.env
chmod 600 /etc/palworld-panel.env

log "Installing/repairing panel services"
PANEL_USER="${PANEL_USER}" PANEL_HOME="${PANEL_HOME}" PANEL_DIR="${PANEL_DIR}" PALWORLD_DIR="${PALWORLD_DIR}" STEAMCMD_DIR="${STEAMCMD_DIR}" \
  python3 "${ROOT_EXEC_DIR}/panel_install.py" --repair

systemctl daemon-reload
systemctl restart palworld-panel.service

if [[ "${INSTALL_PALWORLD}" == "true" ]]; then
  log "Installing Palworld Dedicated Server"
  PANEL_USER="${PANEL_USER}" PANEL_HOME="${PANEL_HOME}" PANEL_DIR="${PANEL_DIR}" PALWORLD_DIR="${PALWORLD_DIR}" STEAMCMD_DIR="${STEAMCMD_DIR}" \
    python3 "${ROOT_EXEC_DIR}/panel_install.py" --install-palworld
fi

log "Done"
log "Panel URL: http://$(hostname -I | awk '{print $1}'):${PANEL_PORT}"
log "RCON/Admin password is stored in /etc/palworld-panel.env"
