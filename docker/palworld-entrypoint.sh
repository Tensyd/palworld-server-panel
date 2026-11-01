#!/usr/bin/env bash
set -Eeuo pipefail

STEAMCMD_DIR="${STEAMCMD_DIR:-/steamcmd}"
PALWORLD_DIR="${PALWORLD_DIR:-/palworld}"
PALWORLD_APP_ID="${PALWORLD_APP_ID:-2394010}"
PALWORLD_PORT="${PALWORLD_PORT:-8211}"
PALWORLD_QUERY_PORT="${PALWORLD_QUERY_PORT:-27015}"
RCON_PORT="${RCON_PORT:-25575}"
RCON_PASSWORD="${RCON_PASSWORD:-}"
SERVER_NAME="${SERVER_NAME:-Palworld Docker Server}"
SERVER_DESCRIPTION="${SERVER_DESCRIPTION:-Managed by Palworld Panel}"
SERVER_MAX_PLAYERS="${SERVER_MAX_PLAYERS:-32}"
STEAMCMD_RETRIES="${STEAMCMD_RETRIES:-8}"
STEAMCMD_RETRY_DELAY="${STEAMCMD_RETRY_DELAY:-30}"
STEAMCMD_ATTEMPT_TIMEOUT="${STEAMCMD_ATTEMPT_TIMEOUT:-1800}"
STEAMCMD_NETWORK_MODE="${STEAMCMD_NETWORK_MODE:-auto}"
STEAMCMD_LOG_FILE="${STEAMCMD_UPDATE_LOG:-${PALWORLD_DIR}/.panel-steamcmd-update.log}"
PALWORLD_START_ON_STEAMCMD_FAILURE="${PALWORLD_START_ON_STEAMCMD_FAILURE:-true}"
PALWORLD_UPDATE_REQUEST_FILE="${PALWORLD_UPDATE_REQUEST_FILE:-${PALWORLD_DIR}/.panel-update-request}"
PALWORLD_USER="${PALWORLD_USER:-palworld}"
PALWORLD_UID="${PALWORLD_UID:-1000}"
PALWORLD_GID="${PALWORLD_GID:-1000}"

write_status() {
  local phase="$1"
  local message="$2"
  local success="${3:-true}"
  local update_success="${4:-}"
  local fallback_used="${5:-false}"
  local steamcmd_exit_code="${6:-}"
  local steamcmd_detail="${7:-}"
  local request_id="${8:-${update_request_id:-}}"
  local status_file="${PALWORLD_INSTALL_STATUS_FILE:-${PALWORLD_DIR}/.panel-install-status.json}"

  mkdir -p "$(dirname "${status_file}")"
  python3 - "${status_file}" "${phase}" "${message}" "${success}" "${update_success}" "${fallback_used}" "${steamcmd_exit_code}" "${steamcmd_detail}" "${request_id}" <<'PY'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

path, phase, message, success, update_success, fallback_used, steamcmd_exit_code, steamcmd_detail, request_id = sys.argv[1:10]
payload = {
    "phase": phase,
    "message": message,
    "success": success.lower() == "true",
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
if update_success:
    payload["update_success"] = update_success.lower() == "true"
if fallback_used.lower() == "true":
    payload["fallback_used"] = True
if steamcmd_exit_code:
    payload["steamcmd_exit_code"] = int(steamcmd_exit_code)
if steamcmd_detail:
    payload["steamcmd_detail"] = steamcmd_detail
if request_id:
    payload["request_id"] = request_id

directory = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
PY
}

if [[ -z "${RCON_PASSWORD}" ]]; then
  echo "RCON_PASSWORD is required. Copy .env.example to .env and set a strong password." >&2
  exit 1
fi

mkdir -p "${STEAMCMD_DIR}" "${PALWORLD_DIR}"

if ! getent group "${PALWORLD_USER}" >/dev/null 2>&1; then
  groupadd --gid "${PALWORLD_GID}" "${PALWORLD_USER}"
fi

if ! id -u "${PALWORLD_USER}" >/dev/null 2>&1; then
  useradd --uid "${PALWORLD_UID}" --gid "${PALWORLD_USER}" --create-home --shell /bin/bash "${PALWORLD_USER}"
fi

chown -R "${PALWORLD_USER}:${PALWORLD_USER}" "${STEAMCMD_DIR}" "${PALWORLD_DIR}"

has_existing_installation() {
  [[ -x "${PALWORLD_DIR}/PalServer.sh" ]]
}

installation_needs_resume() {
  local manifest="${PALWORLD_DIR}/steamapps/appmanifest_${PALWORLD_APP_ID}.acf"

  if [[ -d "${PALWORLD_DIR}/steamapps/downloading/${PALWORLD_APP_ID}" ]]; then
    return 0
  fi
  if [[ -f "${manifest}" ]]; then
    ! grep -Eq '"StateFlags"[[:space:]]+"4"' "${manifest}"
    return
  fi
  compgen -G "${manifest}.stale-*" >/dev/null
}

has_proxy_environment() {
  [[ -n "${HTTP_PROXY:-}${HTTPS_PROXY:-}${ALL_PROXY:-}${http_proxy:-}${https_proxy:-}${all_proxy:-}" ]]
}

steamcmd_network_for_attempt() {
  local attempt="$1"
  case "${STEAMCMD_NETWORK_MODE}" in
    direct)
      printf 'direct\n'
      ;;
    proxy)
      printf 'proxy\n'
      ;;
    auto)
      if has_proxy_environment && (( attempt % 2 == 0 )); then
        printf 'proxy\n'
      else
        printf 'direct\n'
      fi
      ;;
  esac
}

run_steamcmd() {
  local network_mode="$1"
  local -a env_command=(env)
  local -a steamcmd_command=("${STEAMCMD_DIR}/steamcmd.sh" -tcp)

  if [[ "${network_mode}" == "direct" ]]; then
    env_command=(env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy)
  fi

  timeout --signal=TERM --kill-after=15 "${STEAMCMD_ATTEMPT_TIMEOUT}" \
    runuser -u "${PALWORLD_USER}" -- "${env_command[@]}" "${steamcmd_command[@]}" \
    +@sSteamCmdForcePlatformType linux \
    +@sSteamCmdForcePlatformBitness 64 \
    +force_install_dir "${PALWORLD_DIR}" \
    +login anonymous \
    "${steamcmd_args[@]}" \
    +quit 2>&1 | tee -a "${STEAMCMD_LOG_FILE}"
  return "${PIPESTATUS[0]}"
}

refresh_steamcmd_app_info() {
  local network_mode="$1"
  local -a env_command=(env)
  local -a steamcmd_command=("${STEAMCMD_DIR}/steamcmd.sh" -tcp)

  if [[ "${network_mode}" == "direct" ]]; then
    env_command=(env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy)
  fi

  echo "[entrypoint] Refreshing Steam app metadata" | tee -a "${STEAMCMD_LOG_FILE}"
  timeout --signal=TERM --kill-after=15 "${STEAMCMD_ATTEMPT_TIMEOUT}" \
    runuser -u "${PALWORLD_USER}" -- "${env_command[@]}" "${steamcmd_command[@]}" \
    +login anonymous \
    +app_info_update 1 \
    +quit 2>&1 | tee -a "${STEAMCMD_LOG_FILE}"
  return "${PIPESTATUS[0]}"
}

repair_stale_manifest() {
  local manifest="${PALWORLD_DIR}/steamapps/appmanifest_${PALWORLD_APP_ID}.acf"
  local content_log="/home/${PALWORLD_USER}/Steam/logs/content_log.txt"
  local backup

  [[ -f "${manifest}" ]] || return 1
  if [[ "${1:-}" != "force" ]]; then
    grep -q "Access Denied" "${STEAMCMD_LOG_FILE}" 2>/dev/null \
      || grep -q "Access Denied" "${content_log}" 2>/dev/null \
      || return 1
  fi

  backup="${manifest}.stale-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "[entrypoint] Steam rejected the cached depot manifest; backing up ${manifest} to ${backup}" | tee -a "${STEAMCMD_LOG_FILE}"
  mv "${manifest}" "${backup}"
  rm -rf "${PALWORLD_DIR}/steamapps/downloading/${PALWORLD_APP_ID}" \
    "${PALWORLD_DIR}/steamapps/temp/${PALWORLD_APP_ID}"
  return 0
}

update_mode="normal"
update_request_id=""
steamcmd_update_success=""
steamcmd_fallback_used=false
steamcmd_exit_code=""
steamcmd_detail=""
case "${STEAMCMD_NETWORK_MODE}" in
  auto|direct|proxy)
    ;;
  *)
    echo "[entrypoint] Invalid STEAMCMD_NETWORK_MODE=${STEAMCMD_NETWORK_MODE}; using auto" >&2
    STEAMCMD_NETWORK_MODE="auto"
    ;;
esac
if [[ -f "${PALWORLD_UPDATE_REQUEST_FILE}" ]]; then
  readarray -t update_request < <(python3 - "${PALWORLD_UPDATE_REQUEST_FILE}" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    payload = {}
print(payload.get("mode", ""))
print(payload.get("request_id", ""))
PY
  )
  requested_mode="${update_request[0]:-}"
  update_request_id="${update_request[1]:-}"
  rm -f "${PALWORLD_UPDATE_REQUEST_FILE}"
  case "${requested_mode}" in
    update|validate)
      update_mode="${requested_mode}"
      ;;
    *)
      echo "[entrypoint] Ignoring invalid update request mode: ${requested_mode:-empty}" >&2
      ;;
  esac
fi

if has_existing_installation && [[ "${update_mode}" == "normal" ]] && installation_needs_resume; then
  echo "[entrypoint] Incomplete Steam update detected; resuming before starting Palworld"
  update_mode="update"
fi

if has_existing_installation && [[ "${update_mode}" == "normal" ]]; then
  echo "[entrypoint] Using existing Palworld installation; SteamCMD update is not requested"
  write_status "starting" "Using existing Palworld installation"
else
  if [[ ! -x "${STEAMCMD_DIR}/steamcmd.sh" ]]; then
    echo "[entrypoint] Installing SteamCMD"
    write_status "steamcmd" "Installing SteamCMD"
    curl -fsSL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" -o "${STEAMCMD_DIR}/steamcmd_linux.tar.gz"
    tar -xzf "${STEAMCMD_DIR}/steamcmd_linux.tar.gz" -C "${STEAMCMD_DIR}"
    chown -R "${PALWORLD_USER}:${PALWORLD_USER}" "${STEAMCMD_DIR}"
  fi

  if [[ "${update_mode}" == "validate" ]]; then
    steamcmd_action="Validating Palworld Dedicated Server"
    steamcmd_args=(+app_update "${PALWORLD_APP_ID}" validate)
  elif has_existing_installation; then
    steamcmd_action="Updating Palworld Dedicated Server"
    steamcmd_args=(+app_update "${PALWORLD_APP_ID}")
  else
    steamcmd_action="Installing Palworld Dedicated Server"
    steamcmd_args=(+app_update "${PALWORLD_APP_ID}")
  fi

  echo "[entrypoint] ${steamcmd_action}"
  write_status "installing" "${steamcmd_action}" "true" ""
  : > "${STEAMCMD_LOG_FILE}"
  chown "${PALWORLD_USER}:${PALWORLD_USER}" "${STEAMCMD_LOG_FILE}"
  attempt=1
  steamcmd_succeeded=false
  stale_manifest_repaired=false
  steamcmd_exit_code=0
  manifest="${PALWORLD_DIR}/steamapps/appmanifest_${PALWORLD_APP_ID}.acf"
  if [[ "${update_mode}" == "update" && -f "${manifest}" ]] \
    && grep -Eq '"StateFlags"[[:space:]]+"6"' "${manifest}" \
    && grep -Eq '"UpdateResult"[[:space:]]+"6"' "${manifest}"; then
    repair_stale_manifest force
    stale_manifest_repaired=true
  fi
  while [[ "${attempt}" -le "${STEAMCMD_RETRIES}" ]]; do
    steamcmd_network_mode="$(steamcmd_network_for_attempt "${attempt}")"
    echo "[entrypoint] SteamCMD attempt ${attempt}/${STEAMCMD_RETRIES} via ${steamcmd_network_mode}" | tee -a "${STEAMCMD_LOG_FILE}"
    if refresh_steamcmd_app_info "${steamcmd_network_mode}" && run_steamcmd "${steamcmd_network_mode}"; then
      steamcmd_succeeded=true
      break
    else
      steamcmd_exit_code=$?
    fi

    if [[ "${stale_manifest_repaired}" != "true" ]] && repair_stale_manifest; then
      stale_manifest_repaired=true
      echo "[entrypoint] Retrying with a fresh app manifest" | tee -a "${STEAMCMD_LOG_FILE}"
      continue
    fi

    if [[ "${attempt}" -ge "${STEAMCMD_RETRIES}" ]]; then
      break
    fi

    echo "[entrypoint] SteamCMD failed on attempt ${attempt}/${STEAMCMD_RETRIES} via ${steamcmd_network_mode}; retrying in ${STEAMCMD_RETRY_DELAY}s" >&2
    write_status "retrying" "SteamCMD failed on attempt ${attempt}/${STEAMCMD_RETRIES} via ${steamcmd_network_mode}; retrying in ${STEAMCMD_RETRY_DELAY}s" "false" "false" "false" "${steamcmd_exit_code}"
    attempt=$((attempt + 1))
    sleep "${STEAMCMD_RETRY_DELAY}"
  done

  if [[ "${steamcmd_succeeded}" != "true" ]]; then
    steamcmd_detail="$(tail -n 30 "${STEAMCMD_LOG_FILE}" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' | tail -c 2000)"
    if has_existing_installation && [[ "${PALWORLD_START_ON_STEAMCMD_FAILURE}" =~ ^([Tt]rue|1|yes|on)$ ]]; then
      echo "[entrypoint] SteamCMD ${update_mode} failed after ${attempt}/${STEAMCMD_RETRIES} attempts; starting existing Palworld installation" >&2
      steamcmd_update_success=false
      steamcmd_fallback_used=true
      write_status "fallback" "SteamCMD ${update_mode} failed after ${attempt} attempts; starting existing Palworld installation" "true" "false" "true" "${steamcmd_exit_code}" "${steamcmd_detail}"
    else
      echo "[entrypoint] SteamCMD failed after ${attempt} attempts" >&2
      write_status "failed" "SteamCMD install/update failed after ${attempt} attempts" "false" "false" "false" "${steamcmd_exit_code}"
      exit 1
    fi
  else
    steamcmd_update_success=true
    write_status "updated" "SteamCMD ${update_mode} completed" "true" "true"
  fi
fi

if ! has_existing_installation; then
  echo "[entrypoint] PalServer.sh was not created by SteamCMD" >&2
  write_status "failed" "SteamCMD finished but PalServer.sh is missing" "false"
  exit 1
fi

CONFIG_DIR="${PALWORLD_DIR}/Pal/Saved/Config/LinuxServer"
SETTINGS_FILE="${CONFIG_DIR}/PalWorldSettings.ini"
GAME_USER_FILE="${CONFIG_DIR}/GameUserSettings.ini"
mkdir -p "${CONFIG_DIR}"

if [[ ! -f "${SETTINGS_FILE}" ]]; then
  if [[ -f "${PALWORLD_DIR}/DefaultPalWorldSettings.ini" ]]; then
    cp "${PALWORLD_DIR}/DefaultPalWorldSettings.ini" "${SETTINGS_FILE}"
  else
    cat >"${SETTINGS_FILE}" <<'EOF'
[/Script/Pal.PalGameWorldSettings]
OptionSettings=()
EOF
  fi
fi

python3 - "${SETTINGS_FILE}" <<'PY'
import os
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8", errors="replace").read()
if "OptionSettings=(" not in text:
    text = "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=()\n"

# Fields the container owns: always taken from the environment, because the
# published ports and the RCON credentials have to match what Docker and the
# panel were configured with.
managed = {
    "PublicPort": os.environ.get("PALWORLD_PORT", "8211"),
    "QueryPort": os.environ.get("PALWORLD_QUERY_PORT", "27015"),
    "RCONEnabled": "True",
    "bShowPlayerList": "True",
    "RCONPort": os.environ.get("RCON_PORT", "25575"),
    "AdminPassword": '"' + os.environ["RCON_PASSWORD"].replace('"', '\\"') + '"',
}
if os.environ.get("PALWORLD_REST_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
    managed["RESTAPIEnabled"] = "True"
    managed["RESTAPIPort"] = os.environ.get("PALWORLD_REST_PORT", "8212")

# Fields the panel lets the operator edit. These are only seeded when the key
# is missing: rewriting them on every boot silently reverted the name the user
# had just saved.
defaults = {
    "ServerName": '"' + os.environ.get("SERVER_NAME", "Palworld Docker Server").replace('"', '\\"') + '"',
    "ServerDescription": '"' + os.environ.get("SERVER_DESCRIPTION", "Managed by Palworld Panel").replace('"', '\\"') + '"',
    "ServerPlayerMaxNum": os.environ.get("SERVER_MAX_PLAYERS", "32"),
}


def option_settings_bounds(document: str) -> tuple[int, int] | None:
    """Return the (start, end) of the OptionSettings list body.

    Values are quoted and may contain commas and parentheses, so the closing
    bracket cannot be found with a regex -- scan instead of guessing.
    """
    marker = "OptionSettings=("
    start = document.find(marker)
    if start < 0:
        return None
    start += len(marker)
    depth = 1
    in_quotes = False
    escaped = False
    for index in range(start, len(document)):
        char = document[index]
        if escaped:
            escaped = False
        elif in_quotes and char == "\\":
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
        elif in_quotes:
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return start, index
    return None


def split_entries(body: str) -> list[str]:
    """Split on commas that are outside quotes."""
    entries: list[str] = []
    buffer: list[str] = []
    in_quotes = False
    escaped = False
    for char in body:
        if escaped:
            buffer.append(char)
            escaped = False
        elif in_quotes and char == "\\":
            buffer.append(char)
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
            buffer.append(char)
        elif char == "," and not in_quotes:
            entries.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    entries.append("".join(buffer))
    return [entry for entry in entries if entry.strip()]


bounds = option_settings_bounds(text)
if bounds is None:
    body, head, tail = "", "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(", ")\n"
else:
    start, end = bounds
    head, body, tail = text[:start], text[start:end], text[end:]

entries = split_entries(body)
seen: set[str] = set()
for index, entry in enumerate(entries):
    key = entry.partition("=")[0].strip()
    if key in managed:
        entries[index] = f"{key}={managed[key]}"
        seen.add(key)
    elif key in defaults and entry.partition("=")[1]:
        seen.add(key)
for key, value in managed.items():
    if key not in seen:
        entries.append(f"{key}={value}")
for key, value in defaults.items():
    if key not in seen:
        entries.append(f"{key}={value}")

open(path, "w", encoding="utf-8").write(head + ",".join(entries) + tail)
PY
chown "${PALWORLD_USER}:${PALWORLD_USER}" "${SETTINGS_FILE}"

if [[ ! -f "${GAME_USER_FILE}" ]]; then
  WORLD_ID="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16).upper())
PY
)"
  cat >"${GAME_USER_FILE}" <<EOF
[/Script/Pal.PalGameInstance]
DedicatedServerName=${WORLD_ID}
EOF
fi
chown -R "${PALWORLD_USER}:${PALWORLD_USER}" "${CONFIG_DIR}" "${PALWORLD_DIR}/Pal/Saved"

echo "[entrypoint] Starting Palworld"
if [[ "${steamcmd_fallback_used}" == "true" ]]; then
  write_status "starting" "Starting existing Palworld installation after SteamCMD ${update_mode} failure" "true" "false" "true" "${steamcmd_exit_code}" "${steamcmd_detail}"
elif [[ "${steamcmd_update_success}" == "true" ]]; then
  write_status "starting" "Starting Palworld after successful SteamCMD ${update_mode}" "true" "true"
else
  write_status "starting" "Starting Palworld Dedicated Server"
fi
chown -R "${PALWORLD_USER}:${PALWORLD_USER}" "${PALWORLD_DIR}/Pal" "${PALWORLD_DIR}/Engine" 2>/dev/null || true
exec runuser -u "${PALWORLD_USER}" -- bash -lc "cd '${PALWORLD_DIR}' && exec '${PALWORLD_DIR}/PalServer.sh'"
