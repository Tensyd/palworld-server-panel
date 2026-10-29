#!/usr/bin/env python3
"""
Palworld Server Web Management Panel.

Small Flask app for managing a Palworld dedicated server over systemd and RCON.
Runtime secrets and paths come from environment variables so the source file can
stay free of machine passwords.
"""

from __future__ import annotations

import base64
import math
import os
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from rcon import execute_rcon_command, rcon_command as send_rcon_command


app = Flask(__name__)
app.secret_key = os.environ.get("PANEL_SECRET_KEY", os.urandom(24).hex())
SAVE_UPLOAD_MAX_BYTES = int(os.environ.get("SAVE_UPLOAD_MAX_BYTES", str(1024 * 1024 * 1024)))
app.config["MAX_CONTENT_LENGTH"] = SAVE_UPLOAD_MAX_BYTES

PALWORLD_DIR = Path(os.environ.get("PALWORLD_DIR", "/home/demo/palworld"))
PALWORLD_CONFIG = Path(
    os.environ.get(
        "PALWORLD_CONFIG",
        str(PALWORLD_DIR / "Pal" / "Saved" / "Config" / "LinuxServer" / "PalWorldSettings.ini"),
    )
)
DEFAULT_PALWORLD_SETTINGS = Path(os.environ.get("DEFAULT_PALWORLD_SETTINGS", str(PALWORLD_DIR / "DefaultPalWorldSettings.ini")))
DEPLOYMENT_MANAGED_CONFIG_KEYS = {"PublicPort", "QueryPort", "RCONPort", "RCONEnabled", "AdminPassword"}
CONFIG_LOCK_PATH = PALWORLD_CONFIG.with_name(f".{PALWORLD_CONFIG.name}.lock")
PALWORLD_SERVICE = os.environ.get("PALWORLD_SERVICE", "palworld.service")
PALWORLD_BACKEND = os.environ.get("PALWORLD_BACKEND", "systemd").strip().lower()
PALWORLD_CONTAINER_NAME = os.environ.get("PALWORLD_CONTAINER_NAME", "palworld-panel-palworld-1")
PANEL_USER = os.environ.get("PANEL_USER", "demo")

RCON_HOST = os.environ.get("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD = os.environ.get("RCON_PASSWORD", "")
RCON_TIMEOUT_SECONDS = float(os.environ.get("RCON_TIMEOUT_SECONDS", "10"))
PALWORLD_REST_ENABLED = os.environ.get("PALWORLD_REST_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
PALWORLD_REST_HOST = os.environ.get("PALWORLD_REST_HOST", "127.0.0.1")
PALWORLD_REST_PORT = int(os.environ.get("PALWORLD_REST_PORT", "8212"))
PALWORLD_REST_PATH = os.environ.get("PALWORLD_REST_PATH", "/v1/api/players")
PALWORLD_REST_USERNAME = os.environ.get("PALWORLD_REST_USERNAME", "admin")
PALWORLD_REST_PASSWORD = os.environ.get("PALWORLD_REST_PASSWORD", "") or RCON_PASSWORD
PALWORLD_REST_TIMEOUT_SECONDS = float(os.environ.get("PALWORLD_REST_TIMEOUT_SECONDS", "5"))
PLAYER_CACHE_TTL_SECONDS = float(os.environ.get("PLAYER_CACHE_TTL_SECONDS", "8"))
_player_response_cache: tuple[float, bool, dict[str, Any]] = (0.0, False, {})
_player_response_lock = threading.Lock()

SYSTEMCTL = os.environ.get("SYSTEMCTL", "/usr/bin/systemctl")
JOURNALCTL = os.environ.get("JOURNALCTL", "/usr/bin/journalctl")
APP_VERSION = os.environ.get("PANEL_ASSET_VERSION", str(int(time.time())))
CONFIG_BACKUP_DIR = Path(os.environ.get("CONFIG_BACKUP_DIR", "/home/demo/palworld-panel/config-backups"))
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG", "/home/demo/palworld-panel/audit.log"))
SAVE_ROOT = PALWORLD_DIR / "Pal" / "Saved"
ACTIVE_SAVEGAMES_DIR = SAVE_ROOT / "SaveGames" / "0"
CONFIG_DIR = SAVE_ROOT / "Config" / "LinuxServer"
GAME_USER_SETTINGS = CONFIG_DIR / "GameUserSettings.ini"
SAVE_SLOT_ROOT = Path(os.environ.get("SAVE_SLOT_ROOT", "/home/demo/palworld-panel/save-slots"))
SAVE_SLOT_DIR = SAVE_SLOT_ROOT / "slots"
SAVE_BACKUP_DIR = SAVE_SLOT_ROOT / "backups"
SAVE_IMPORT_DIR = SAVE_SLOT_ROOT / "imports"
SAVE_LOCK_PATH = SAVE_SLOT_ROOT / ".operation.lock"
ACTIVE_SLOT_PATH = SAVE_SLOT_ROOT / "active-slot.json"
CHOWN = os.environ.get("CHOWN", "/usr/bin/chown")
MOD_LIBRARY_ROOT = Path(os.environ.get("MOD_LIBRARY_ROOT", "/home/demo/palworld-panel/mod-library"))
MOD_UPLOAD_MAX_BYTES = int(os.environ.get("MOD_UPLOAD_MAX_BYTES", str(1024 * 1024 * 1024)))
PALWORLD_MOD_MODE = os.environ.get("PALWORLD_MOD_MODE", "pak-safe")
MOD_PAK_DIR = PALWORLD_DIR / "Pal" / "Content" / "Paks" / "~mods"
PAL_MODS_DIR = PALWORLD_DIR / "Pal" / "Content" / "Paks" / "Mods"
OFFICIAL_MOD_WORKSHOP_DIR = PAL_MODS_DIR / "Workshop"
PAL_MOD_SETTINGS = PAL_MODS_DIR / "PalModSettings.ini"
app.config["MAX_CONTENT_LENGTH"] = max(app.config["MAX_CONTENT_LENGTH"], MOD_UPLOAD_MAX_BYTES)
UPDATE_SCRIPT = Path(os.environ.get("PANEL_UPDATE_SCRIPT", "/home/demo/palworld-panel/panel_update.py"))
UPDATE_STATUS = Path(os.environ.get("PANEL_UPDATE_STATUS", "/home/demo/palworld-panel/update-status.json"))
UPDATE_LOG = Path(os.environ.get("PANEL_UPDATE_LOG", "/home/demo/palworld-panel/update.log"))
PALWORLD_UPDATE_REQUEST = Path(os.environ.get("PALWORLD_UPDATE_REQUEST_FILE", str(PALWORLD_DIR / ".panel-update-request")))
DOCKER_STEAMCMD_LOG = Path(os.environ.get("STEAMCMD_UPDATE_LOG", str(PALWORLD_DIR / ".panel-steamcmd-update.log")))
UPDATE_SERVICE = os.environ.get("PANEL_UPDATE_SERVICE", "palworld-panel-update.service")
UPDATE_AUTO_SERVICE = os.environ.get("PANEL_AUTO_UPDATE_SERVICE", "palworld-panel-auto-update.service")
UPDATE_TIMER = os.environ.get("PANEL_UPDATE_TIMER", "palworld-panel-update.timer")
# 状态文件说"在跑"但后台进程已经不在时，多久之后回收成失败状态。
UPDATE_STALE_GRACE_SECONDS = int(os.environ.get("PANEL_UPDATE_STALE_GRACE_SECONDS", "90"))
INSTALL_SCRIPT = Path(os.environ.get("PANEL_INSTALL_SCRIPT", "/home/demo/palworld-panel/panel_install.py"))
INSTALL_STATUS = Path(os.environ.get("PANEL_INSTALL_STATUS", "/home/demo/palworld-panel/install-status.json"))
INSTALL_LOG = Path(os.environ.get("PANEL_INSTALL_LOG", "/home/demo/palworld-panel/install.log"))
INSTALL_REQUEST = Path(os.environ.get("PANEL_INSTALL_REQUEST", "/home/demo/palworld-panel/install-request.json"))
INSTALL_SERVICE = os.environ.get("PANEL_INSTALL_SERVICE", "palworld-panel-install.service")
VALID_SLOT_ID = re.compile(r"^[a-z0-9_-]{1,64}$")
VALID_WORLD_ID = re.compile(r"^[A-Fa-f0-9]{32}$")
CONFIG_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
STRING_FIELDS = {
    "ServerName",
    "ServerDescription",
    "ServerPassword",
    "AdminPassword",
    "RandomizerSeed",
    "DenyTechnologyList",
    "AdditionalDropItemWhenPlayerKillingInPvPMode",
}
UNQUOTED_STRING_FIELDS: set[str] = set()
SAVE_UPLOAD_MAX_EXTRACTED_BYTES = int(os.environ.get("SAVE_UPLOAD_MAX_EXTRACTED_BYTES", str(2 * 1024 * 1024 * 1024)))
LOG_STREAM_MAX_SECONDS = int(os.environ.get("LOG_STREAM_MAX_SECONDS", "300"))
UPDATE_TIMEOUT_SECONDS = int(os.environ.get("PALWORLD_UPDATE_TIMEOUT_SECONDS", "2700"))

NUMERIC_RANGES = {
    "ServerPlayerMaxNum": (1, 128),
    "GuildPlayerMaxNum": (1, 100),
    "CoopPlayerMaxNum": (1, 32),
    "AutoSaveSpan": (1, 3600),
    "ChatPostLimitPerMinute": (0, 1000),
    "BaseCampMaxNum": (1, 512),
    "BaseCampWorkerMaxNum": (1, 50),
    "BaseCampMaxNumInGuild": (1, 512),
    "ExpRate": (0.1, 20),
    "PalCaptureRate": (0.1, 5),
    "PalSpawnNumRate": (0.1, 5),
    "DayTimeSpeedRate": (0.1, 5),
    "NightTimeSpeedRate": (0.1, 5),
    "WorkSpeedRate": (0.1, 10),
    "CollectionDropRate": (0.1, 10),
    "EnemyDropItemRate": (0.1, 10),
    "ItemWeightRate": (0.1, 10),
    "PalDamageRateAttack": (0.1, 10),
    "PalDamageRateDefense": (0.1, 10),
    "PlayerDamageRateAttack": (0.1, 10),
    "PlayerDamageRateDefense": (0.1, 10),
    "PlayerStomachDecreaceRate": (0.1, 10),
    "PlayerStaminaDecreaceRate": (0.1, 10),
    "PlayerAutoHPRegeneRate": (0.1, 10),
    "PlayerAutoHpRegeneRateInSleep": (0.1, 10),
    "PalStomachDecreaceRate": (0.1, 10),
    "PalStaminaDecreaceRate": (0.1, 10),
    "PalAutoHPRegeneRate": (0.1, 10),
    "PalAutoHpRegeneRateInSleep": (0.1, 10),
    "BuildObjectHpRate": (0.1, 10),
    "BuildObjectDamageRate": (0.1, 10),
    "BuildObjectDeteriorationDamageRate": (0, 10),
    "CollectionObjectHpRate": (0.1, 10),
    "CollectionObjectRespawnSpeedRate": (0.1, 10),
    "DropItemMaxNum": (0, 10000),
    "PhysicsActiveDropItemMaxNum": (-1, 10000),
    "DropItemMaxNum_UNKO": (0, 10000),
    "DropItemAliveMaxHours": (0.1, 240),
    "PalEggDefaultHatchingTime": (0, 240),
    "EquipmentDurabilityDamageRate": (0, 10),
    "SupplyDropSpan": (1, 1440),
    "AutoResetGuildTimeNoOnlinePlayers": (0, 720),
    "MaxBuildingLimitNum": (0, 100000),
    "ServerReplicatePawnCullDistance": (5000, 15000),
    "ItemContainerForceMarkDirtyInterval": (0.1, 60),
    "PlayerDataPalStorageUpdateCheckTickInterval": (0.1, 60),
    "ItemCorruptionMultiplier": (0, 10),
    "MonsterFarmActionSpeedRate": (0.1, 10),
    "GuildRejoinCooldownMinutes": (0, 10080),
    "AutoTransferMasterCheckIntervalSeconds": (60, 604800),
    "AutoTransferMasterThresholdDays": (0, 365),
    "MaxGuildsPerFrame": (1, 1000),
    "BlockRespawnTime": (0, 3600),
    "RespawnPenaltyDurationThreshold": (0, 3600),
    "RespawnPenaltyTimeScale": (0, 10),
    "AdditionalDropItemNumWhenPlayerKillingInPvPMode": (0, 100),
    "VoiceChatMaxVolumeDistance": (0, 100000),
    "VoiceChatZeroVolumeDistance": (0, 100000),
    "BuildingNameDisplayCacheTTLSeconds": (0, 3600),
    "RESTAPIPort": (1024, 65535),
}

INTEGER_CONFIG_KEYS = {
    "ServerPlayerMaxNum",
    "GuildPlayerMaxNum",
    "CoopPlayerMaxNum",
    "ChatPostLimitPerMinute",
    "BaseCampMaxNum",
    "BaseCampWorkerMaxNum",
    "BaseCampMaxNumInGuild",
    "DropItemMaxNum",
    "PhysicsActiveDropItemMaxNum",
    "DropItemMaxNum_UNKO",
    "SupplyDropSpan",
    "MaxBuildingLimitNum",
    "GuildRejoinCooldownMinutes",
    "AutoTransferMasterThresholdDays",
    "MaxGuildsPerFrame",
    "AdditionalDropItemNumWhenPlayerKillingInPvPMode",
    "BuildingNameDisplayCacheTTLSeconds",
    "RESTAPIPort",
}

FIELD_LABELS = {
    "ServerName": "服务器名称",
    "ServerDescription": "服务器描述",
    "ServerPassword": "服务器密码",
    "AdminPassword": "管理员密码",
    "ServerPlayerMaxNum": "最大玩家数",
    "GuildPlayerMaxNum": "公会最大人数",
    "CoopPlayerMaxNum": "合作模式最大玩家数",
    "AutoSaveSpan": "自动存档间隔",
    "ChatPostLimitPerMinute": "聊天限速",
    "BaseCampMaxNum": "据点最大数量",
    "BaseCampWorkerMaxNum": "每个据点的帕鲁上限",
    "BaseCampMaxNumInGuild": "公会据点上限",
    "ExpRate": "经验倍率",
    "PalCaptureRate": "帕鲁捕获倍率",
    "PalSpawnNumRate": "帕鲁生成数量倍率",
    "ItemCorruptionMultiplier": "物品腐败速度倍率",
    "MonsterFarmActionSpeedRate": "牧场放牧产出速度倍率",
    "DropItemMaxNum": "掉落物最大数量",
    "PhysicsActiveDropItemMaxNum": "物理掉落物上限",
    "MaxBuildingLimitNum": "每名玩家建筑数量上限",
    "ServerReplicatePawnCullDistance": "帕鲁同步距离",
    "DenyTechnologyList": "禁用科技列表",
    "RESTAPIPort": "REST API 端口",
}

BOOL_FIELDS = {
    "bIsRandomizerPalLevelRandom",
    "bEnablePlayerToPlayerDamage",
    "bEnableFriendlyFire",
    "bIsPvP",
    "bEnableInvaderEnemy",
    "bActiveUNKO",
    "bEnableAimAssistPad",
    "bEnableAimAssistKeyboard",
    "bAutoResetGuildNoOnlinePlayers",
    "bIsMultiplay",
    "bHardcore",
    "bPalLost",
    "bCharacterRecreateInHardcore",
    "bCanPickupOtherGuildDeathPenaltyDrop",
    "bEnableNonLoginPenalty",
    "bEnableFastTravel",
    "bEnableFastTravelOnlyBaseCamp",
    "bIsStartLocationSelectByMap",
    "bExistPlayerAfterLogout",
    "bEnableDefenseOtherGuildPlayer",
    "bInvisibleOtherGuildBaseCampAreaFX",
    "bBuildAreaLimit",
    "bAllowClientMod",
    "bIsShowJoinLeftMessage",
    "bShowPlayerList",
    "bIsUseBackupSaveData",
    "EnablePredatorBossPal",
    "bAllowGlobalPalboxExport",
    "bAllowGlobalPalboxImport",
    "bDisplayPvPItemNumOnWorldMap_BaseCamp",
    "bDisplayPvPItemNumOnWorldMap_Player",
    "bAdditionalDropItemWhenPlayerKillingInPvPMode",
    "bEnableVoiceChat",
    "bAllowEnhanceStat_Health",
    "bAllowEnhanceStat_Attack",
    "bAllowEnhanceStat_Stamina",
    "bAllowEnhanceStat_Weight",
    "bAllowEnhanceStat_WorkSpeed",
    "bEnableBuildingPlayerUIdDisplay",
    "RESTAPIEnabled",
}

CHOICE_FIELDS = {
    "Difficulty": {"None", "Casual", "Normal", "Hard", "Hardcore"},
    "RandomizerType": {"None", "Region", "All"},
    "DeathPenalty": {"None", "Item", "ItemAndEquipment", "All"},
}

ALLOWED_CONFIG_KEYS = STRING_FIELDS | set(NUMERIC_RANGES) | BOOL_FIELDS | set(CHOICE_FIELDS)


def run_command(args: list[str], timeout: int = 30, sudo: bool = False) -> tuple[str, str, int]:
    """Run a command and return stdout, stderr, and exit code."""
    cmd = ["sudo", "-n", *args] if sudo else args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except Exception as exc:  # pragma: no cover - defensive boundary
        return "", str(exc), -1


def systemctl(*args: str, timeout: int = 30) -> tuple[str, str, int]:
    return run_command([SYSTEMCTL, *args], timeout=timeout, sudo=True)


def systemctl_query(*args: str, timeout: int = 15) -> tuple[str, str, int]:
    """Read-only systemctl queries (``is-active`` & friends) need no root.

    Routing them through ``sudo -n`` meant that a missing or mismatched
    ``/etc/sudoers.d/palworld-panel`` made every query fail, which was then
    read as "the service is not running". The updater trusted that answer and
    overwrote the game files underneath a live server.
    """
    out, err, code = run_command([SYSTEMCTL, *args], timeout=timeout, sudo=False)
    if out or err or code in (0, 3, 4):
        return out, err, code
    return run_command([SYSTEMCTL, *args], timeout=timeout, sudo=True)


def journalctl(*args: str, timeout: int = 30) -> tuple[str, str, int]:
    return run_command([JOURNALCTL, *args], timeout=timeout, sudo=True)


def using_docker_backend() -> bool:
    return PALWORLD_BACKEND == "docker"


def get_docker_container():
    try:
        import docker  # type: ignore

        client = docker.from_env()
        return client.containers.get(PALWORLD_CONTAINER_NAME)
    except Exception as exc:
        raise RuntimeError(f"Docker backend unavailable: {exc}") from exc


def docker_container_running() -> bool:
    try:
        container = get_docker_container()
        container.reload()
        return container.status == "running"
    except Exception:
        return False


def docker_container_logs(lines: int = 80) -> list[str]:
    try:
        container = get_docker_container()
        raw = container.logs(tail=max(1, min(int(lines), 300)), stdout=True, stderr=True)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return text.splitlines() or ["No log entries available"]
    except Exception as exc:
        return [f"Unable to read Docker logs: {exc}"]


def docker_exec_shell(command: str, timeout: int = 8) -> tuple[int, str]:
    try:
        container = get_docker_container()
        result = container.exec_run(["/bin/sh", "-lc", command], stdout=True, stderr=True, demux=False, tty=False)
        output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)
        return int(result.exit_code or 0), output.strip()
    except Exception as exc:
        return -1, str(exc)


def read_docker_install_marker() -> dict[str, Any]:
    marker = PALWORLD_DIR / ".panel-install-status.json"
    try:
        if marker.exists():
            data = json.loads(marker.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def get_steamcmd_failure_detail() -> str:
    log_lines = tail_text(DOCKER_STEAMCMD_LOG, 40)
    if log_lines:
        useful_lines = [
            line.strip()
            for line in log_lines
            if any(token in line.lower() for token in ("error", "failed", "state is", "attempt", "network"))
        ]
        detail = " | ".join((useful_lines or log_lines)[-8:])
        if detail:
            return detail[:2000]

    code, output = docker_exec_shell(
        "log=/home/palworld/Steam/logs/content_log.txt; "
        "test -f \"$log\" && grep -E \"Access Denied|Failed downloading|No connection\" \"$log\" | tail -n 1 || true"
    )
    return output.strip() if code == 0 else ""


def tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_docker_game_state() -> dict[str, Any]:
    container = get_docker_container()
    container.reload()
    state = container.attrs.get("State", {})
    container_running = container.status == "running"
    installed = (PALWORLD_DIR / "PalServer.sh").exists()
    marker = read_docker_install_marker()
    pal_process = False
    process_text = ""
    rcon_ready = False

    if container_running:
        code, output = docker_exec_shell(
            r'''for f in /proc/[0-9]*/cmdline; do cmd="$(tr '\0' ' ' < "$f" 2>/dev/null || true)"; case "$cmd" in *PalServer*) echo "$cmd"; exit 0;; esac; done; exit 1'''
        )
        pal_process = code == 0
        process_text = output
        rcon_ready = tcp_port_open(RCON_HOST, RCON_PORT)

    if not container_running:
        phase = "stopped"
        message = "Palworld container is stopped"
    elif pal_process and installed and rcon_ready:
        phase = "running"
        message = "Palworld server is running"
    elif pal_process and installed:
        phase = "starting"
        message = "Palworld server is starting; waiting for RCON"
    elif installed:
        phase = "starting"
        message = marker.get("message") or "Palworld files are installed; server is starting"
    else:
        phase = str(marker.get("phase") or "installing")
        message = str(marker.get("message") or "Palworld files are being installed by SteamCMD")

    ready = container_running and installed and pal_process and rcon_ready
    return {
        "running": ready,
        "container_running": container_running,
        "installed": installed,
        "ready": ready,
        "rcon_ready": rcon_ready,
        "phase": phase,
        "message": message,
        "process": process_text,
        "pid": str(state.get("Pid") or ""),
        "start_time": state.get("StartedAt", "") if container_running else "",
    }


def parse_palworld_settings(text: str | None = None) -> dict[str, str]:
    """Parse PalWorldSettings.ini's OptionSettings line into a dict."""
    if text is None:
        text = PALWORLD_CONFIG.read_text(encoding="utf-8") if PALWORLD_CONFIG.exists() else ""

    match = re.search(r"OptionSettings=\((.*)\)", text, re.DOTALL)
    if not match:
        return {}

    inner = match.group(1)
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    quote_char = ""

    escaped = False
    for char in inner:
        if in_quote:
            buf.append(char)
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote_char:
                in_quote = False
            continue
        if char in ('"', "'"):
            in_quote = True
            quote_char = char
            buf.append(char)
        elif char == "(":
            depth += 1
            buf.append(char)
        elif char == ")":
            depth -= 1
            buf.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)

    if "".join(buf).strip():
        parts.append("".join(buf).strip())

    options: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        options[key.strip()] = value.strip()
    return options


def decode_setting_string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value)
    if len(text) >= 2 and text[0] == text[-1] == '"':
        body = text[1:-1]
        decoded: list[str] = []
        escaped = False
        for char in body:
            if escaped:
                decoded.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            else:
                decoded.append(char)
        if escaped:
            decoded.append("\\")
        return "".join(decoded)
    return text


def encode_setting_string(value: Any) -> str:
    text = str(value if value is not None else "")
    if any(ord(char) < 32 for char in text):
        raise ValueError("字符串配置不能包含换行或控制字符")
    if len(text) > 512:
        raise ValueError("字符串配置不能超过 512 个字符")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def normalize_config_value(key: str, value: Any) -> str:
    if key in STRING_FIELDS:
        return decode_setting_string(value)
    return str(value if value is not None else "").strip()


def serialize_config_value(key: str, value: Any) -> str:
    if key in UNQUOTED_STRING_FIELDS:
        return str(value if value is not None else "").strip()
    if key in STRING_FIELDS:
        return encode_setting_string(value)
    return str(value if value is not None else "").strip()


def parse_default_palworld_settings() -> dict[str, str]:
    try:
        return parse_palworld_settings(DEFAULT_PALWORLD_SETTINGS.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def get_panel_settings() -> dict[str, str]:
    settings = parse_default_palworld_settings()
    settings.update(parse_palworld_settings())
    for key in DEPLOYMENT_MANAGED_CONFIG_KEYS:
        settings.pop(key, None)
    return settings


def build_palworld_settings(options: dict[str, str]) -> str:
    option_line = "OptionSettings=(" + ",".join(f"{key}={value}" for key, value in options.items()) + ")"
    return "[/Script/Pal.PalGameWorldSettings]\n" + option_line + "\n"


def validate_config_changes(changes: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for raw_key, value in changes.items():
        key = str(raw_key or "").strip()
        label = FIELD_LABELS.get(key, key or "配置项")

        if not key or not CONFIG_KEY_RE.match(key):
            errors.append(f"{label} 名称不合法")
            continue
        if key in DEPLOYMENT_MANAGED_CONFIG_KEYS:
            errors.append(f"{label} 由部署配置管理，不能在面板中修改")
            continue
        if key not in ALLOWED_CONFIG_KEYS:
            errors.append(f"不支持修改配置项：{key}")
            continue

        if key in STRING_FIELDS:
            try:
                encode_setting_string(decode_setting_string(value))
            except ValueError as exc:
                errors.append(f"{label}：{exc}")
            continue

        text = str(value if value is not None else "").strip()

        if key in NUMERIC_RANGES:
            try:
                number = float(text)
            except ValueError:
                errors.append(f"{label} 必须是数字")
                continue

            if not math.isfinite(number):
                errors.append(f"{label} 必须是有限数字")
                continue

            if key in INTEGER_CONFIG_KEYS and not number.is_integer():
                errors.append(f"{label} 必须是整数")
                continue

            minimum, maximum = NUMERIC_RANGES[key]
            if number < minimum or number > maximum:
                errors.append(f"{label} 必须在 {minimum} 到 {maximum} 之间")

        if key in BOOL_FIELDS and text not in {"True", "False"}:
            errors.append(f"{label} 必须是 True 或 False")

        if key in CHOICE_FIELDS and text not in CHOICE_FIELDS[key]:
            choices = ", ".join(sorted(CHOICE_FIELDS[key]))
            errors.append(f"{label} 必须是以下值之一：{choices}")

    return errors


def backup_config_file() -> None:
    if not PALWORLD_CONFIG.exists():
        return
    CONFIG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(PALWORLD_CONFIG, CONFIG_BACKUP_DIR / f"PalWorldSettings.ini.{stamp}.bak")


@contextmanager
def locked_file(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    locked_with = ""
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            locked_with = "msvcrt"
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked_with = "fcntl"
        yield
    finally:
        try:
            handle.seek(0)
            if locked_with == "msvcrt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif locked_with == "fcntl":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            tmp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


def update_palworld_settings(changes: dict[str, Any]) -> dict[str, str]:
    errors = validate_config_changes(changes)
    if errors:
        raise ValueError("; ".join(errors[:5]))

    with locked_file(CONFIG_LOCK_PATH):
        current = parse_default_palworld_settings()
        current.update(parse_palworld_settings())
        for raw_key, value in changes.items():
            key = str(raw_key or "").strip()
            if key and value is not None:
                normalized = normalize_config_value(key, value)
                current[key] = serialize_config_value(key, normalized)

        backup_config_file()
        atomic_write_text(PALWORLD_CONFIG, build_palworld_settings(current))
    return {key: value for key, value in current.items() if key not in DEPLOYMENT_MANAGED_CONFIG_KEYS}


def get_changed_config_keys(changes: dict[str, Any]) -> list[str]:
    current = parse_palworld_settings()
    changed = []
    for raw_key, value in changes.items():
        key = str(raw_key or "").strip()
        if normalize_config_value(key, current.get(key, "")) != normalize_config_value(key, value):
            changed.append(key)
    return sorted(changed)


def audit_event(action: str, success: bool, **details: Any) -> None:
    """Append an audit event without interrupting the user-facing action."""
    try:
        source_ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_ip": source_ip,
            "action": action,
            "success": bool(success),
            **details,
        }
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_audit_events(limit: int = 80) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 300))
    if not AUDIT_LOG.exists():
        return []

    try:
        lines = AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    records: list[dict[str, Any]] = []
    for line in lines[-safe_limit:]:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return list(reversed(records))


def tail_text(path: Path, lines: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception:
        return []


def parse_steam_manifest(manifest_path: Path | None = None) -> dict[str, str]:
    app_manifest = manifest_path or (PALWORLD_DIR / "steamapps" / "appmanifest_2394010.acf")
    text = app_manifest.read_text(encoding="utf-8", errors="replace") if app_manifest.exists() else ""
    build_match = re.search(r'"buildid"\s+"([^"]+)"', text)
    depot_match = re.search(r'"2394012"\s*\{(?P<body>.*?)\n\s*\}', text, flags=re.S)
    manifest = ""
    if depot_match:
        manifest_match = re.search(r'"manifest"\s+"([^"]+)"', depot_match.group("body"))
        if manifest_match:
            manifest = manifest_match.group(1)
    return {"buildid": build_match.group(1) if build_match else "", "manifest": manifest}


def fetch_latest_manifest() -> str:
    url = "https://api.steamcmd.net/v1/info/2394010"

    def fetch(opener: urllib.request.OpenerDirector) -> dict[str, Any]:
        with opener.open(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    proxies = urllib.request.getproxies()
    has_proxy = any(name in proxies for name in ("http", "https", "all"))
    if has_proxy:
        try:
            data = fetch(urllib.request.build_opener())
        except urllib.error.URLError:
            data = fetch(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    else:
        data = fetch(urllib.request.build_opener(urllib.request.ProxyHandler({})))

    app_data = data["data"]["2394010"]
    return str(app_data["depots"]["2394012"]["manifests"]["public"]["gid"])


def run_docker_update_check() -> dict[str, Any]:
    existing = read_json(UPDATE_STATUS, {})
    if existing.get("running"):
        return reconcile_docker_update_status(existing)
    local = parse_steam_manifest()
    latest_manifest = fetch_latest_manifest()
    update_available = bool(latest_manifest and local.get("manifest") and latest_manifest != local["manifest"])
    status = {
        **read_json(UPDATE_STATUS, {}),
        "backend": "docker",
        "running": False,
        "phase": "checked",
        "checked_at": iso_now(),
        "auto_update_enabled": False,
        "local_buildid": local.get("buildid", ""),
        "local_manifest": local.get("manifest", ""),
        "latest_manifest": latest_manifest,
        "update_available": update_available,
        "message": "Update available" if update_available else "Already up to date",
        "success": True,
        "steps": [{"name": "detect", "status": "done", "message": "Update available" if update_available else "Already up to date", "time": iso_now()}],
    }
    write_json(UPDATE_STATUS, status)
    return status


ISO_OFFSET_WITHOUT_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_iso_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # iso_now() formats with %z, which emits "+0800". fromisoformat() only
    # accepts that colon-less form from Python 3.11 on, so every timestamp
    # written by the updater parsed as 0.0 on 3.10 (Ubuntu 22.04's default).
    text = ISO_OFFSET_WITHOUT_COLON.sub(r"\1:\2", text)
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return 0.0


def marker_matches_request(marker: dict[str, Any], update_status: dict[str, Any]) -> bool:
    request_id = str(update_status.get("request_id") or "")
    marker_request_id = str(marker.get("request_id") or "")
    if marker_request_id:
        return bool(request_id and marker_request_id == request_id)
    return parse_iso_timestamp(marker.get("updated_at")) >= parse_iso_timestamp(update_status.get("requested_at")) > 0


def reconcile_docker_update_status(update_status: dict[str, Any]) -> dict[str, Any]:
    if not update_status.get("running"):
        return update_status
    target = str(update_status.get("target_manifest") or update_status.get("latest_manifest") or "")
    local = parse_steam_manifest()
    marker = read_docker_install_marker()
    marker_current = marker_matches_request(marker, update_status)
    container_running = docker_container_running()
    initially_running = bool(update_status.get("initially_running"))

    if target and local.get("manifest") == target and marker_current and marker.get("update_success") is True:
        if not initially_running and container_running:
            try:
                container = get_docker_container()
                container.stop(timeout=60)
                container.reload()
            except Exception as exc:
                update_status["message"] = f"Update installed, but failed to restore stopped state: {exc}"
                return update_status
        update_status.update(running=False, phase="complete", finished_at=iso_now(), success=True, message="SteamCMD update complete; target manifest verified" + ("" if initially_running else "; container restored to stopped state"), local_buildid=local.get("buildid", ""), local_manifest=local.get("manifest", ""), update_available=False)
        write_json(UPDATE_STATUS, update_status)
    elif marker_current and (marker.get("phase") == "failed" or marker.get("fallback_used")):
        update_status.update(running=False, phase="failed", finished_at=iso_now(), success=False, message=marker.get("message") or "SteamCMD update failed")
        write_json(UPDATE_STATUS, update_status)
    else:
        started = parse_iso_timestamp(update_status.get("started_at"))
        if started and time.time() - started > UPDATE_TIMEOUT_SECONDS + 60:
            update_status.update(running=False, phase="failed", finished_at=iso_now(), success=False, message="Update worker was lost or timed out before the target manifest was verified")
            write_json(UPDATE_STATUS, update_status)
        elif not container_running and not PALWORLD_UPDATE_REQUEST.exists() and marker_current:
            update_status.update(running=False, phase="failed", finished_at=iso_now(), success=False, message="Update container stopped before the target manifest was installed")
            write_json(UPDATE_STATUS, update_status)
    return update_status


def reconcile_systemd_update_status(update_status: dict[str, Any], service_active: bool) -> dict[str, Any]:
    """回收「状态说运行中、进程其实已经不在」的残留 running 标记。

    没有这一步，任何一次被 systemd 超时终止（或主机重启）的更新都会让面板
    永远停在"更新进行中"：按钮是灰的，每 30 分钟的定时任务也永远等不到结束。
    """
    if not update_status.get("running") or service_active:
        return update_status
    started = parse_iso_timestamp(update_status.get("started_at"))
    if started and time.time() - started < UPDATE_STALE_GRACE_SECONDS:
        return update_status
    message = "后台更新进程已退出但没有写入结果（可能被 systemd 超时终止或主机重启），请查看 update.log 后重试"
    steps = [item for item in update_status.get("steps", []) if item.get("name") != "failed"]
    steps.append({"name": "failed", "status": "error", "message": message, "time": iso_now()})
    update_status.update(running=False, phase="failed", finished_at=iso_now(), success=False, message=message, steps=steps)
    write_json(UPDATE_STATUS, update_status)
    return update_status


def read_update_status() -> dict[str, Any]:
    status = read_json(UPDATE_STATUS, {})
    if using_docker_backend():
        status = reconcile_docker_update_status(status)
        log_tail = tail_text(UPDATE_LOG, 60)
        steamcmd_log_tail = tail_text(DOCKER_STEAMCMD_LOG, 80)
        if steamcmd_log_tail:
            log_tail.extend(["--- SteamCMD update diagnostics ---", *steamcmd_log_tail])
        log_tail.extend(docker_container_logs(40))
        status.update(
            {
                "backend": "docker",
                "service_active": False,
                "timer_active": False,
                "auto_update_enabled": False,
                "log_tail": log_tail[-180:],
            }
        )
        return status

    active, _, _ = systemctl_query("is-active", UPDATE_SERVICE, timeout=10)
    auto_active, _, _ = systemctl_query("is-active", UPDATE_AUTO_SERVICE, timeout=10)
    timer_active, _, _ = systemctl_query("is-active", UPDATE_TIMER, timeout=10)
    auto_service_active = auto_active.strip() == "active"
    service_active = active.strip() == "active" or auto_service_active
    status = reconcile_systemd_update_status(status, service_active)
    status.update(
        {
            "backend": "systemd",
            "service_active": service_active,
            "auto_service_active": auto_service_active,
            "timer_active": timer_active.strip() == "active",
            "log_tail": tail_text(UPDATE_LOG, 80),
        }
    )
    return status


def run_update_check_now() -> tuple[bool, str]:
    if using_docker_backend():
        try:
            details = run_docker_update_check()
            return True, "检查完成：发现新版本" if details.get("update_available") else "检查完成：已是最新"
        except Exception as exc:
            status = read_update_status()
            write_json(
                UPDATE_STATUS,
                {
                    **status,
                    "backend": "docker",
                    "running": False,
                    "phase": "failed",
                    "checked_at": iso_now(),
                    "success": False,
                    "message": str(exc),
                },
            )
            return False, f"检查失败：{exc}"
    if not UPDATE_SCRIPT.exists():
        return False, "update script is not installed"
    out, err, code = run_command([sys.executable, str(UPDATE_SCRIPT), "--check"], timeout=120, sudo=False)
    message = out or err or ("检查完成" if code == 0 else f"检查失败：{code}")
    return code == 0, message


def start_update_service() -> tuple[bool, str]:
    if using_docker_backend():
        try:
            operation = acquire_save_operation_lock("docker-update")
        except SaveOperationBusy as exc:
            return False, str(exc)
        try:
            update_status = reconcile_docker_update_status(read_json(UPDATE_STATUS, {}))
            if update_status.get("running"):
                release_save_operation_lock(operation)
                return False, "更新任务正在运行"
            local = parse_steam_manifest()
            expected_manifest = fetch_latest_manifest()
            if not expected_manifest or not local.get("manifest"):
                release_save_operation_lock(operation)
                return False, "未获取到本地或目标 Manifest"
            if local.get("manifest") == expected_manifest:
                update_status.update(running=False, phase="idle", success=True, update_available=False, message="Already up to date")
                write_json(UPDATE_STATUS, update_status)
                release_save_operation_lock(operation)
                return False, "当前已是最新版本"
            request_id = uuid.uuid4().hex
            requested_at = iso_now()
            initially_running = bool(get_docker_game_state().get("container_running"))
            update_status = {
                **update_status,
                "backend": "docker",
                "running": True,
                "phase": "running",
                "request_id": request_id,
                "operation_id": request_id,
                "requested_at": requested_at,
                "target_manifest": expected_manifest,
                "latest_manifest": expected_manifest,
                "started_at": requested_at,
                "initially_running": initially_running,
                "backup_id": "",
                "recovery": None,
                "success": None,
                "message": "Preparing a consistent backup before requesting the Docker update",
                "steps": [{"name": "detect", "status": "done", "message": "Fresh target manifest confirmed", "time": requested_at}],
            }
            write_json(UPDATE_STATUS, update_status)
        except Exception:
            release_save_operation_lock(operation)
            raise

        def run_update() -> None:
            try:
                started_at = int(time.time())
                container = get_docker_container()
                game_state = get_docker_game_state()
                if game_state.get("ready"):
                    result = execute_panel_rcon_command("Save")
                    if not result.success or not result.acknowledged:
                        raise RuntimeError(result.message or "RCON Save was not acknowledged")
                    time.sleep(5)
                    update_status["steps"].append({"name": "save", "status": "done", "message": result.response or result.message or "Save acknowledged", "time": iso_now()})
                if game_state.get("container_running"):
                    container.stop(timeout=60)
                    container.reload()
                    if container.status == "running":
                        raise RuntimeError("Docker container did not stop before backup")
                update_status["steps"].append({"name": "stop", "status": "done", "message": "Container stopped", "time": iso_now()})
                backup = backup_current_save("before-update")
                update_status["backup_id"] = backup["id"]
                update_status["steps"].append({"name": "backup", "status": "done", "message": backup["id"], "time": iso_now()})
                write_json(UPDATE_STATUS, update_status)
                PALWORLD_UPDATE_REQUEST.parent.mkdir(parents=True, exist_ok=True)
                write_json(PALWORLD_UPDATE_REQUEST, {"mode": "update", "request_id": request_id, "requested_at": requested_at, "target_manifest": expected_manifest})
                container.start()
                deadline = time.monotonic() + UPDATE_TIMEOUT_SECONDS

                while True:
                    local = parse_steam_manifest()
                    game_state = get_docker_game_state()
                    marker = read_docker_install_marker()
                    marker_current = marker_matches_request(marker, update_status)
                    installed = local.get("manifest") == expected_manifest and marker_current and marker.get("update_success") is True
                    if installed and (game_state.get("ready") or not initially_running):
                        if not initially_running and game_state.get("container_running"):
                            container.stop(timeout=60)
                        write_json(
                            UPDATE_STATUS,
                            {
                                **update_status,
                                "backend": "docker",
                                "running": False,
                                "phase": "complete",
                                "finished_at": iso_now(),
                                "success": True,
                                "message": "SteamCMD update complete; target manifest verified" + (" and Palworld is ready" if initially_running else "; container restored to stopped state"),
                                "local_buildid": local.get("buildid", ""),
                                "local_manifest": local.get("manifest", ""),
                                "update_available": False,
                                "steps": [
                                    {"name": "detect", "status": "done", "message": "Update available", "time": iso_now()},
                                    {"name": "update", "status": "done", "message": f"Manifest {expected_manifest} installed", "time": iso_now()},
                                    {"name": "start", "status": "done", "message": "Palworld server ready" if initially_running else "Update required temporary startup; container stopped again", "time": iso_now()},
                                    {"name": "complete", "status": "done", "message": "Target manifest verified", "time": iso_now()},
                                ],
                            },
                        )
                        return

                    raw_logs = container.logs(since=started_at, tail=160, stdout=True, stderr=True)
                    log_text = raw_logs.decode("utf-8", errors="replace") if isinstance(raw_logs, bytes) else str(raw_logs)
                    if marker_current and (marker.get("phase") == "failed" or marker.get("fallback_used")):
                        detail = str(marker.get("steamcmd_detail") or get_steamcmd_failure_detail())
                        detail_suffix = f" Detail: {detail}" if detail else ""
                        raise RuntimeError(
                            f"SteamCMD update failed after retries; manifest is still {local.get('manifest') or 'unknown'} (expected {expected_manifest}).{detail_suffix}"
                        )

                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Timed out waiting for SteamCMD to install manifest {expected_manifest}; current manifest is {local.get('manifest') or 'unknown'}"
                        )

                    write_json(
                        UPDATE_STATUS,
                        {
                            **update_status,
                            "backend": "docker",
                            "running": True,
                            "phase": "running",
                            "success": None,
                            "message": f"Waiting for SteamCMD update (current manifest: {local.get('manifest') or '-'})",
                            "local_buildid": local.get("buildid", ""),
                            "local_manifest": local.get("manifest", ""),
                            "steps": [
                                {"name": "detect", "status": "done", "message": "Update available", "time": iso_now()},
                                {"name": "update", "status": "active", "message": "SteamCMD update in progress", "time": iso_now()},
                                {"name": "start", "status": "pending", "message": game_state.get("message", "Waiting for Palworld"), "time": iso_now()},
                            ],
                        },
                    )
                    time.sleep(10)
            except Exception as exc:
                recovery = {"attempted": False, "success": False, "message": "not required"}
                if initially_running:
                    recovery["attempted"] = True
                    recovered, recovery_message = _service_action_unlocked("start")
                    recovery.update(success=recovered, message=recovery_message)
                current_status = read_json(UPDATE_STATUS, update_status)
                write_json(
                    UPDATE_STATUS,
                    {
                        **current_status,
                        "backend": "docker",
                        "running": False,
                        "phase": "failed",
                        "finished_at": iso_now(),
                        "success": False,
                        "message": str(exc),
                        "recovery": recovery,
                        "log_tail": docker_container_logs(120),
                        "steps": [
                            {"name": "detect", "status": "done", "message": "Update available", "time": iso_now()},
                            {"name": "update", "status": "error", "message": str(exc), "time": iso_now()},
                            {"name": "complete", "status": "error", "message": "Target manifest was not verified", "time": iso_now()},
                        ],
                    },
                )
            finally:
                release_save_operation_lock(operation)

        threading.Thread(target=run_update, name="palworld-update", daemon=True).start()
        return True, "更新任务已在后台启动；面板会在目标 Manifest 验证后才显示完成"

    active, _, _ = systemctl_query("is-active", UPDATE_SERVICE, timeout=10)
    auto_active, _, _ = systemctl_query("is-active", UPDATE_AUTO_SERVICE, timeout=10)
    if active.strip() == "active" or auto_active.strip() == "active":
        return False, "更新任务正在运行"
    update_status = read_update_status()
    if update_status.get("running"):
        return False, "更新任务正在运行（状态文件标记为运行中，请稍后再试或查看 update.log）"
    if not update_status.get("update_available"):
        return False, "当前没有检测到可用更新，请先点击检查更新"
    _, err, code = systemctl("start", UPDATE_SERVICE, timeout=20)
    if code != 0:
        return False, err or f"systemctl start {UPDATE_SERVICE} exited with {code}"
    return True, "更新任务已在后台启动"


def read_install_status() -> dict[str, Any]:
    if using_docker_backend():
        try:
            game_state = get_docker_game_state()
        except Exception as exc:
            game_state = {
                "running": False,
                "container_running": False,
                "installed": False,
                "phase": "error",
                "message": str(exc),
            }
        checks = {
            "docker_backend": True,
            "palworld_installed": bool(game_state["installed"]),
            "palworld_manifest": (PALWORLD_DIR / "steamapps" / "appmanifest_2394010.acf").exists(),
            "panel_installed": Path(__file__).exists(),
            "env_file": True,
            "container_running": bool(game_state["container_running"]),
        }
        installed = bool(game_state["installed"])
        return {
            "backend": "docker",
            "running": bool(game_state["container_running"] and not installed),
            "service_active": False,
            "phase": game_state["phase"],
            "message": game_state["message"],
            "success": game_state["phase"] != "failed",
            "panel_user": "container",
            "panel_dir": str(Path.cwd()),
            "palworld_dir": str(PALWORLD_DIR),
            "steamcmd": "inside palworld container",
            "checks": checks,
            "steps": [
                {
                    "name": "docker",
                    "status": "done" if game_state["container_running"] else "error",
                    "message": "Palworld container running" if game_state["container_running"] else "Palworld container stopped",
                },
                {
                    "name": "install",
                    "status": "done" if installed else "active",
                    "message": "Palworld files installed" if installed else game_state["message"],
                },
            ],
            "log_tail": docker_container_logs(80),
        }

    status = read_json(INSTALL_STATUS, {})
    active, _, _ = systemctl_query("is-active", INSTALL_SERVICE, timeout=10)
    status.update(
        {
            "service_active": active.strip() == "active",
            "log_tail": tail_text(INSTALL_LOG, 100),
        }
    )
    return status


def run_install_check_now() -> tuple[bool, str]:
    if using_docker_backend():
        return True, "Docker Compose 部署模式检查完成"
    if not INSTALL_SCRIPT.exists():
        return False, "installer script is not installed"
    out, err, code = run_command([sys.executable, str(INSTALL_SCRIPT), "--check"], timeout=120, sudo=False)
    message = out or err or ("检查完成" if code == 0 else f"检查失败：{code}")
    return code == 0, message


def start_install_service(action: str) -> tuple[bool, str]:
    if using_docker_backend():
        return False, "Docker 模式不在面板内执行 systemd 安装；请使用 docker compose 管理部署"
    if action not in {"install-palworld", "repair"}:
        return False, "unsupported installer action"
    active, _, _ = systemctl_query("is-active", INSTALL_SERVICE, timeout=10)
    if active.strip() == "active":
        return False, "安装任务正在运行"
    write_json(INSTALL_REQUEST, {"action": action, "requested_at": iso_now()})
    _, err, code = systemctl("start", INSTALL_SERVICE, timeout=20)
    if code != 0:
        return False, err or f"systemctl start {INSTALL_SERVICE} exited with {code}"
    return True, "安装任务已在后台启动"


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def ensure_save_dirs() -> None:
    SAVE_SLOT_DIR.mkdir(parents=True, exist_ok=True)
    SAVE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    SAVE_IMPORT_DIR.mkdir(parents=True, exist_ok=True)


class SaveOperationBusy(RuntimeError):
    pass


@contextmanager
def save_operation_lock():
    operation = acquire_save_operation_lock("panel-operation")
    try:
        yield
    finally:
        release_save_operation_lock(operation)


def acquire_save_operation_lock(owner: str):
    ensure_save_dirs()
    handle = SAVE_LOCK_PATH.open("a+", encoding="utf-8")
    locked_with = ""
    try:
        if os.name == "nt":
            import msvcrt

            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                locked_with = "msvcrt"
            except OSError as exc:
                raise SaveOperationBusy("已有存档、更新或服务操作正在进行，请等待完成后再试") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked_with = "fcntl"
            except BlockingIOError as exc:
                raise SaveOperationBusy("已有存档、更新或服务操作正在进行，请等待完成后再试") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{owner} {os.getpid()} {iso_now()}\n")
        handle.flush()
        return handle, locked_with
    except Exception:
        handle.close()
        raise


def release_save_operation_lock(operation) -> None:
    handle, locked_with = operation
    try:
        try:
            if locked_with == "msvcrt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif locked_with == "fcntl":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()
    except Exception:
        pass


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_safe_managed_path(path: Path) -> Path:
    resolved = path.resolve()
    if path_within(resolved, SAVE_ROOT) or path_within(resolved, SAVE_SLOT_ROOT):
        return resolved
    raise ValueError(f"Path is outside managed save roots: {path}")


def has_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    if path.is_dir():
        return any(child.is_symlink() for child in path.rglob("*"))
    return False


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def latest_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    mtimes = [item.stat().st_mtime for item in path.rglob("*")]
    return max(mtimes) if mtimes else path.stat().st_mtime


def format_ts(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def normalize_slot_id(raw: str) -> str:
    slot_id = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")
    return slot_id[:64] or f"slot-{int(time.time())}"


def require_slot_id(slot_id: str) -> str:
    slot_id = str(slot_id or "").strip()
    if not VALID_SLOT_ID.match(slot_id):
        raise ValueError("slot_id 只允许小写字母、数字、- 和 _，长度 1-64")
    return slot_id


def generate_world_id() -> str:
    return os.urandom(16).hex().upper()


def normalize_world_id(world_id: str) -> str:
    world_id = str(world_id or "").strip().upper()
    return world_id if VALID_WORLD_ID.match(world_id) else ""


def require_world_id(world_id: str) -> str:
    world_id = normalize_world_id(world_id)
    if not world_id:
        raise ValueError("world_id 必须是 32 位十六进制字符串")
    return world_id


def slot_path(slot_id: str) -> Path:
    return SAVE_SLOT_DIR / require_slot_id(slot_id)


def slot_savegames_dir(slot_id: str) -> Path:
    return slot_path(slot_id) / "SaveGames" / "0"


def metadata_path(slot_id: str) -> Path:
    return slot_path(slot_id) / "metadata.json"


def get_recorded_active_slot_id() -> str:
    payload = read_json(ACTIVE_SLOT_PATH, {})
    slot_id = str(payload.get("slot_id", "")).strip()
    if slot_id and VALID_SLOT_ID.match(slot_id) and slot_path(slot_id).exists():
        return slot_id
    return ""


def set_recorded_active_slot(slot_id: str, world_id: str) -> None:
    write_json(
        ACTIVE_SLOT_PATH,
        {
            "slot_id": require_slot_id(slot_id),
            "world_id": require_world_id(world_id),
            "updated_at": iso_now(),
        },
    )


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    lock_path = path.with_name(f".{path.name}.lock")
    with locked_file(lock_path):
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def find_world_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    worlds = []
    for path in root.iterdir():
        if path.is_dir() and normalize_world_id(path.name) and (path / "Level.sav").exists():
            worlds.append(path)
    return sorted(worlds, key=lambda item: item.name)


def read_dedicated_server_name() -> str:
    if not GAME_USER_SETTINGS.exists():
        return ""
    match = re.search(r"^DedicatedServerName=(.+)$", GAME_USER_SETTINGS.read_text(encoding="utf-8", errors="replace"), re.M)
    return match.group(1).strip() if match else ""


def write_dedicated_server_name(world_id: str) -> None:
    world_id = require_world_id(world_id)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    text = GAME_USER_SETTINGS.read_text(encoding="utf-8", errors="replace") if GAME_USER_SETTINGS.exists() else ""
    line = f"DedicatedServerName={world_id}"
    if re.search(r"^DedicatedServerName=.*$", text, re.M):
        text = re.sub(r"^DedicatedServerName=.*$", line, text, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "[ServerSettings]\n" + line + "\n"
    tmp = GAME_USER_SETTINGS.with_suffix(".ini.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(GAME_USER_SETTINGS)


def current_world_id() -> str:
    configured = normalize_world_id(read_dedicated_server_name())
    worlds = find_world_dirs(ACTIVE_SAVEGAMES_DIR)
    if configured and any(normalize_world_id(world.name) == configured for world in worlds):
        return configured
    if worlds:
        return require_world_id(worlds[0].name)
    return configured


def savegames_payload_root(source: Path) -> tuple[Path, str, bool]:
    source = assert_safe_managed_path(source)
    if has_symlink(source):
        raise ValueError("存档目录不能包含符号链接")
    if (source / "Level.sav").exists():
        return source, require_world_id(source.name), True
    nested = source / "SaveGames" / "0"
    worlds = find_world_dirs(nested)
    if worlds:
        return nested, require_world_id(worlds[0].name), False
    worlds = find_world_dirs(source)
    if worlds:
        return source, require_world_id(worlds[0].name), False
    raise ValueError("未找到有效存档目录，至少需要 Level.sav")


def uploaded_save_payload_root(source: Path) -> Path:
    source = assert_safe_managed_path(source)
    try:
        savegames_payload_root(source)
        return source
    except ValueError:
        pass

    candidates = []
    for level_file in source.rglob("Level.sav"):
        world_dir = level_file.parent
        if has_symlink(world_dir):
            continue
        if world_dir.parent.name == "0" and world_dir.parent.parent.name == "SaveGames":
            candidates.append(world_dir.parent)
        else:
            candidates.append(world_dir)

    unique = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(candidate)

    if not unique:
        raise ValueError("上传包里没有找到 Level.sav")
    if len(unique) > 1:
        raise ValueError("上传包里包含多个世界，请只上传一个存档世界")
    return unique[0]


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_dir = assert_safe_managed_path(target_dir)
    total_size = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("压缩包包含不安全路径")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("压缩包不能包含符号链接")
            total_size += info.file_size
            if total_size > SAVE_UPLOAD_MAX_EXTRACTED_BYTES:
                raise ValueError("压缩包解压后太大")

        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            destination = (target_dir / name).resolve()
            if not path_within(destination, target_dir):
                raise ValueError("压缩包包含不安全路径")
            if name.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source_file, destination.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)


MOD_ALLOWED_UPLOAD_SUFFIXES = {".pak", ".sig", ".zip"}
MOD_DANGEROUS_SUFFIXES = {".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".so", ".dylib", ".msi", ".scr", ".com"}


def ensure_mod_dirs() -> None:
    MOD_LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    (MOD_LIBRARY_ROOT / "disabled").mkdir(parents=True, exist_ok=True)
    (MOD_LIBRARY_ROOT / "imports").mkdir(parents=True, exist_ok=True)
    (MOD_LIBRARY_ROOT / "metadata").mkdir(parents=True, exist_ok=True)
    (MOD_LIBRARY_ROOT / "trash").mkdir(parents=True, exist_ok=True)
    MOD_PAK_DIR.mkdir(parents=True, exist_ok=True)
    OFFICIAL_MOD_WORKSHOP_DIR.mkdir(parents=True, exist_ok=True)


def mod_metadata_path(mod_id: str) -> Path:
    return MOD_LIBRARY_ROOT / "metadata" / f"{normalize_mod_id(mod_id)}.json"


def normalize_mod_id(raw: str) -> str:
    mod_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(raw or "").strip()).strip("-_.")
    return (mod_id[:80] or f"mod-{int(time.time())}").lower()


def path_within_any(path: Path, roots: list[Path]) -> bool:
    return any(path_within(path, root) for root in roots)


def assert_safe_mod_path(path: Path) -> Path:
    resolved = path.resolve()
    roots = [MOD_LIBRARY_ROOT, MOD_PAK_DIR, PAL_MODS_DIR]
    if path_within_any(resolved, roots):
        return resolved
    raise ValueError(f"Path is outside managed mod roots: {path}")


def read_mod_meta(mod_id: str) -> dict[str, Any]:
    return read_json(mod_metadata_path(mod_id), {})


def write_mod_meta(mod_id: str, payload: dict[str, Any]) -> None:
    payload["id"] = normalize_mod_id(mod_id)
    payload["updated_at"] = iso_now()
    write_json(mod_metadata_path(mod_id), payload)


def mod_file_info(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
        "updated_at": format_ts(path.stat().st_mtime if path.exists() else None),
    }


def safe_extract_mod_zip(zip_path: Path, target_dir: Path) -> None:
    target_dir = assert_safe_mod_path(target_dir)
    total_size = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("压缩包包含不安全路径")
            suffix = Path(name).suffix.lower()
            if suffix in MOD_DANGEROUS_SUFFIXES:
                raise ValueError(f"压缩包包含禁止的文件类型：{suffix}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("压缩包不能包含符号链接")
            total_size += info.file_size
            if total_size > MOD_UPLOAD_MAX_BYTES:
                raise ValueError("MOD 压缩包解压后太大")

        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            destination = (target_dir / name).resolve()
            if not path_within(destination, target_dir):
                raise ValueError("压缩包包含不安全路径")
            if name.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source_file, destination.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)


def find_info_json(root: Path) -> Path | None:
    matches = [path for path in root.rglob("Info.json") if path.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda item: len(item.parts))
    return matches[0]


def read_official_mod_info(info_path: Path) -> dict[str, Any]:
    payload = json.loads(info_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError("Info.json 格式不正确")
    package_name = str(payload.get("PackageName") or payload.get("Name") or info_path.parent.name).strip()
    if not package_name:
        raise ValueError("Info.json 缺少 PackageName")
    return {
        "package_name": package_name,
        "version": str(payload.get("Version") or payload.get("ModVersion") or ""),
        "is_server": payload.get("IsServer"),
        "install_rules": payload.get("InstallRules"),
        "raw": payload,
    }


def read_active_official_mods() -> set[str]:
    if not PAL_MOD_SETTINGS.exists():
        return set()
    text = PAL_MOD_SETTINGS.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^ActiveModList=(.*)$", text, re.M)
    if not match:
        return set()
    return {item.strip() for item in re.split(r"[,;]", match.group(1)) if item.strip()}


def write_active_official_mods(active: set[str]) -> None:
    PAL_MOD_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[/Script/Pal.PalGameLocalSettings]",
        "bGlobalEnableMod=true" if active else "bGlobalEnableMod=false",
        "ActiveModList=" + ",".join(sorted(active)),
        "",
    ]
    tmp = PAL_MOD_SETTINGS.with_suffix(".ini.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(PAL_MOD_SETTINGS)


def discover_mod_files(mod_id: str, enabled: bool) -> list[Path]:
    root = MOD_PAK_DIR if enabled else MOD_LIBRARY_ROOT / "disabled"
    mod_id = normalize_mod_id(mod_id)
    files = []
    for path in root.glob("*"):
        if path.is_file() and path.suffix.lower() in {".pak", ".sig"} and normalize_mod_id(path.stem) == mod_id:
            files.append(path)
    return files


def unique_file_infos(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for info in files:
        path = str(info.get("path") or info.get("name") or "")
        key = str(Path(path).resolve()) if path else str(info)
        if key in seen:
            continue
        seen.add(key)
        unique.append(info)
    return unique


def list_mods() -> list[dict[str, Any]]:
    ensure_mod_dirs()
    mods: dict[str, dict[str, Any]] = {}

    for meta_file in (MOD_LIBRARY_ROOT / "metadata").glob("*.json"):
        meta = read_json(meta_file, {})
        if meta.get("deleted_at"):
            continue
        if meta.get("id"):
            mods[str(meta["id"])] = meta

    for enabled, root in [(True, MOD_PAK_DIR), (False, MOD_LIBRARY_ROOT / "disabled")]:
        for path in root.glob("*"):
            if not path.is_file() or path.suffix.lower() not in {".pak", ".sig"}:
                continue
            mod_id = normalize_mod_id(path.stem)
            meta = mods.setdefault(
                mod_id,
                {
                    "id": mod_id,
                    "name": path.stem,
                    "type": "pak",
                    "source": "discovered",
                    "created_at": "",
                    "notes": "",
                },
            )
            meta["enabled"] = enabled or bool(meta.get("enabled"))
            meta["type"] = "pak" if meta.get("type") in {None, "", "sig"} else meta.get("type")
            meta.setdefault("files", [])
            meta["files"] = unique_file_infos([*meta.get("files", []), mod_file_info(path)])

    active_official = read_active_official_mods()
    for item in OFFICIAL_MOD_WORKSHOP_DIR.iterdir() if OFFICIAL_MOD_WORKSHOP_DIR.exists() else []:
        if not item.is_dir():
            continue
        info_path = item / "Info.json"
        if not info_path.exists():
            continue
        try:
            info = read_official_mod_info(info_path)
        except Exception:
            info = {"package_name": item.name, "version": "", "is_server": None, "install_rules": None}
        mod_id = normalize_mod_id(item.name)
        meta = mods.setdefault(
            mod_id,
            {
                "id": mod_id,
                "name": info["package_name"],
                "type": "official",
                "source": "discovered",
                "created_at": "",
                "notes": "",
            },
        )
        meta.update(
            {
                "type": "official",
                "package_name": info["package_name"],
                "version": info.get("version", ""),
                "is_server": info.get("is_server"),
                "install_rules": info.get("install_rules"),
                "enabled": info["package_name"] in active_official,
                "path": str(item),
                "size_bytes": dir_size(item),
                "updated_at": format_ts(latest_mtime(item)),
                "compatibility": "官方服务端 MOD 目前官方标注仅 Windows dedicated server 支持；Linux/Docker 后端请谨慎启用。",
            }
        )

    for meta in mods.values():
        if meta.get("type") == "pak":
            files = unique_file_infos(meta.get("files") or [])
            meta["files"] = files
            meta["size_bytes"] = sum(file.get("size_bytes", 0) for file in files)
            meta["compatibility"] = "PAK MOD 通常要求客户端安装同款 MOD；启用后需要重启服务器。"
        meta.setdefault("enabled", False)
        meta.setdefault("needs_restart", True)

    return sorted(mods.values(), key=lambda item: (not item.get("enabled", False), item.get("name") or item.get("id") or ""))


def install_pak_files(files: list[Path], name: str = "", notes: str = "") -> dict[str, Any]:
    pak_files = [path for path in files if path.suffix.lower() == ".pak"]
    if not pak_files:
        raise ValueError("未找到 .pak 文件")
    empty_files = [path.name for path in files if path.suffix.lower() in {".pak", ".sig"} and path.stat().st_size <= 0]
    if empty_files:
        raise ValueError(f"MOD 文件不能为空：{', '.join(empty_files)}")
    pak_stems = {normalize_mod_id(path.stem) for path in pak_files}
    if len(pak_stems) > 1:
        raise ValueError("压缩包包含多个不同的 .pak 文件，请拆分后分别上传")
    installed = []
    primary = pak_files[0]
    mod_id = normalize_mod_id(primary.stem)
    for path in files:
        if path.suffix.lower() not in {".pak", ".sig"}:
            continue
        if path.suffix.lower() == ".sig" and normalize_mod_id(path.stem) != mod_id:
            continue
        target = MOD_PAK_DIR / path.name
        if target.exists():
            raise ValueError(f"MOD 文件已存在：{target.name}")
        shutil.copy2(path, target)
        installed.append(mod_file_info(target))
    meta = {
        "id": mod_id,
        "name": name or primary.stem,
        "type": "pak",
        "enabled": True,
        "source": "uploaded",
        "created_at": iso_now(),
        "notes": notes,
        "files": installed,
        "needs_restart": True,
    }
    write_mod_meta(mod_id, meta)
    return meta


def install_official_mod(source_root: Path, name: str = "", notes: str = "") -> dict[str, Any]:
    info_path = find_info_json(source_root)
    if not info_path:
        raise ValueError("未找到 Info.json")
    info = read_official_mod_info(info_path)
    mod_id = normalize_mod_id(info["package_name"])
    target = OFFICIAL_MOD_WORKSHOP_DIR / mod_id
    if target.exists():
        raise ValueError(f"官方 MOD 已存在：{mod_id}")
    shutil.copytree(info_path.parent, target, symlinks=False)
    meta = {
        "id": mod_id,
        "name": name or info["package_name"],
        "type": "official",
        "enabled": False,
        "source": "uploaded",
        "created_at": iso_now(),
        "notes": notes,
        "package_name": info["package_name"],
        "version": info.get("version", ""),
        "is_server": info.get("is_server"),
        "install_rules": info.get("install_rules"),
        "path": str(target),
        "size_bytes": dir_size(target),
        "needs_restart": True,
        "compatibility": "官方服务端 MOD 目前官方标注仅 Windows dedicated server 支持；Linux/Docker 后端默认导入但不自动启用。",
    }
    write_mod_meta(mod_id, meta)
    return meta


def upload_mod(file_storage, name: str = "", notes: str = "") -> dict[str, Any]:
    ensure_mod_dirs()
    filename = Path(file_storage.filename or "").name
    if not filename:
        raise ValueError("请选择要上传的 MOD 文件")
    suffix = Path(filename).suffix.lower()
    if suffix not in MOD_ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError("只支持上传 .pak、.sig 或 .zip")
    if suffix in MOD_DANGEROUS_SUFFIXES:
        raise ValueError("禁止上传可执行文件或脚本")

    upload_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{normalize_mod_id(filename)}"
    upload_dir = MOD_LIBRARY_ROOT / "imports" / upload_id
    upload_dir.mkdir(parents=True, exist_ok=False)
    upload_path = upload_dir / filename
    try:
        file_storage.save(upload_path)
        if upload_path.stat().st_size <= 0:
            raise ValueError("MOD 文件不能为空")
        if upload_path.stat().st_size > MOD_UPLOAD_MAX_BYTES:
            raise ValueError("MOD 文件太大")

        if suffix == ".zip":
            extract_dir = upload_dir / "extracted"
            extract_dir.mkdir()
            safe_extract_mod_zip(upload_path, extract_dir)
            info_path = find_info_json(extract_dir)
            if info_path:
                mod = install_official_mod(extract_dir, name=name, notes=notes)
            else:
                files = [path for path in extract_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".pak", ".sig"}]
                mod = install_pak_files(files, name=name, notes=notes)
        elif suffix == ".pak":
            sidecar = upload_path.with_suffix(".sig")
            files = [upload_path, sidecar] if sidecar.exists() else [upload_path]
            mod = install_pak_files(files, name=name, notes=notes)
        else:
            if upload_path.stat().st_size <= 0:
                raise ValueError("MOD 文件不能为空")
            target = MOD_PAK_DIR / filename
            if target.exists():
                raise ValueError(f"MOD 文件已存在：{target.name}")
            shutil.copy2(upload_path, target)
            mod_id = normalize_mod_id(upload_path.stem)
            mod = {
                "id": mod_id,
                "name": name or upload_path.stem,
                "type": "sig",
                "enabled": True,
                "source": "uploaded",
                "created_at": iso_now(),
                "notes": notes,
                "files": [mod_file_info(target)],
                "needs_restart": True,
            }
            write_mod_meta(mod_id, mod)
        return mod
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


def set_mod_enabled(mod_id: str, enabled: bool, allow_official: bool = False) -> dict[str, Any]:
    ensure_mod_dirs()
    mod_id = normalize_mod_id(mod_id)
    meta = read_mod_meta(mod_id)
    official_dir = OFFICIAL_MOD_WORKSHOP_DIR / mod_id
    if not meta and (official_dir / "Info.json").exists():
        info = read_official_mod_info(official_dir / "Info.json")
        meta = {
            "id": mod_id,
            "name": info["package_name"],
            "type": "official",
            "package_name": info["package_name"],
            "version": info.get("version", ""),
            "is_server": info.get("is_server"),
            "install_rules": info.get("install_rules"),
            "path": str(official_dir),
        }
    mod_type = meta.get("type") or "pak"
    if mod_type == "official":
        package_name = str(meta.get("package_name") or meta.get("name") or "").strip()
        if not package_name:
            raise ValueError("官方 MOD 缺少 PackageName")
        if enabled and not allow_official:
            raise ValueError("官方服务端 MOD 在当前 Linux/Docker 后端存在兼容风险，请确认风险后再启用")
        active = read_active_official_mods()
        if enabled:
            active.add(package_name)
        else:
            active.discard(package_name)
        write_active_official_mods(active)
        meta["enabled"] = enabled
        meta["needs_restart"] = True
        write_mod_meta(mod_id, meta)
        return meta

    source_root = MOD_LIBRARY_ROOT / "disabled" if enabled else MOD_PAK_DIR
    target_root = MOD_PAK_DIR if enabled else MOD_LIBRARY_ROOT / "disabled"
    moved = []
    for path in discover_mod_files(mod_id, not enabled):
        target = target_root / path.name
        if target.exists():
            raise ValueError(f"目标文件已存在：{target.name}")
        shutil.move(str(path), str(target))
        moved.append(mod_file_info(target))
    if not moved:
        for path in source_root.glob(f"{mod_id}*"):
            if path.is_file() and path.suffix.lower() in {".pak", ".sig"}:
                target = target_root / path.name
                shutil.move(str(path), str(target))
                moved.append(mod_file_info(target))
    if not moved:
        raise ValueError("未找到可切换的 MOD 文件")
    meta.update({"id": mod_id, "type": "pak", "enabled": enabled, "files": moved, "needs_restart": True})
    write_mod_meta(mod_id, meta)
    return meta


def delete_mod(mod_id: str) -> dict[str, Any]:
    ensure_mod_dirs()
    mod_id = normalize_mod_id(mod_id)
    meta = read_mod_meta(mod_id)
    trash_dir = MOD_LIBRARY_ROOT / "trash" / f"{time.strftime('%Y%m%d-%H%M%S')}-{mod_id}"
    trash_dir.mkdir(parents=True, exist_ok=False)
    moved = []

    official_dir = OFFICIAL_MOD_WORKSHOP_DIR / mod_id
    if meta.get("type") == "official" or official_dir.exists():
        package_name = str(meta.get("package_name") or "").strip()
        if not package_name and (official_dir / "Info.json").exists():
            package_name = read_official_mod_info(official_dir / "Info.json")["package_name"]
        active = read_active_official_mods()
        if package_name and package_name in active:
            active.discard(package_name)
            write_active_official_mods(active)
        source = official_dir
        if source.exists():
            shutil.move(str(source), str(trash_dir / source.name))
            moved.append(str(trash_dir / source.name))
    else:
        for enabled in (True, False):
            for path in discover_mod_files(mod_id, enabled):
                target = trash_dir / path.name
                shutil.move(str(path), str(target))
                moved.append(str(target))

    if not moved:
        raise ValueError("未找到要删除的 MOD 文件")
    meta.update({"enabled": False, "deleted_at": iso_now(), "trash_path": str(trash_dir), "needs_restart": True})
    write_mod_meta(mod_id, meta)
    return meta


def empty_mod_trash() -> int:
    ensure_mod_dirs()
    trash = MOD_LIBRARY_ROOT / "trash"
    count = 0
    for item in list(trash.iterdir()):
        item = assert_safe_mod_path(item)
        if item.is_dir():
            shutil.rmtree(item)
            count += 1
        elif item.is_file():
            item.unlink()
            count += 1
    return count


def get_mod_status() -> dict[str, Any]:
    mods = list_mods()
    return {
        "backend": PALWORLD_BACKEND,
        "mode": PALWORLD_MOD_MODE,
        "mod_library_root": str(MOD_LIBRARY_ROOT),
        "pak_enabled_dir": str(MOD_PAK_DIR),
        "official_mod_dir": str(PAL_MODS_DIR),
        "official_server_mods_supported": False,
        "ue4ss_supported": False,
        "needs_restart": any(mod.get("needs_restart") for mod in mods),
        "mods_count": len(mods),
        "enabled_count": sum(1 for mod in mods if mod.get("enabled")),
        "warning": "2.0 首版只自动管理 PAK/官方 Info.json 包；UE4SS/Lua 不自动安装。官方服务端 MOD 目前官方标注仅 Windows dedicated server 支持。",
    }


def restart_for_mods() -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    def step(name: str, success: bool, message: str = "") -> None:
        steps.append({"step": name, "success": success, "message": message})

    backup = None
    status_before = get_server_status()
    was_running = bool(status_before.get("running"))
    container_running = bool(status_before.get("container_running", was_running))

    if was_running:
        save_output = rcon_command("Save")
        save_ok = not save_output.startswith("[RCON Error]")
        step("save", save_ok, save_output or "Save command sent")
        time.sleep(5)
    else:
        step("save", True, "server is not running; skip RCON save")

    if container_running or was_running:
        success, message = _service_action_unlocked("stop")
        step("stop", success, message)
        if not success or not wait_for_service_state(False, timeout=90):
            raise RuntimeError("停止服务器失败，已取消应用 MOD")
    else:
        step("stop", True, "server already stopped")

    backup = backup_current_save("before-mod-restart")
    step("backup", True, backup["id"])

    if was_running:
        success, message = _service_action_unlocked("start")
        step("restart", success, message)
        if not success:
            raise RuntimeError(message)
        restored = wait_for_service_state(True, timeout=90)
        step("status", restored, "server running" if restored else "server did not report running in time")
    else:
        step("restart", True, "server was stopped; leaving it stopped")
    return {"backup": backup, "steps": steps, "running": get_server_status()["running"]}


def copytree_clean(source: Path, target: Path) -> None:
    source = assert_safe_managed_path(source)
    target = assert_safe_managed_path(target)
    if has_symlink(source):
        raise ValueError("存档目录不能包含符号链接")
    if target.is_symlink():
        raise ValueError("目标存档路径不能是符号链接")
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)


def remove_children(path: Path) -> None:
    path = assert_safe_managed_path(path)
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_symlink():
            raise ValueError("存档目录不能包含符号链接")
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def get_active_save_info() -> dict[str, Any]:
    world_id = current_world_id()
    world_path = ACTIVE_SAVEGAMES_DIR / world_id if world_id else ACTIVE_SAVEGAMES_DIR
    return {
        "world_id": world_id,
        "path": str(world_path),
        "size_bytes": dir_size(world_path),
        "updated_at": format_ts(latest_mtime(world_path)),
        "savegames_root": str(ACTIVE_SAVEGAMES_DIR),
    }


def list_save_slots() -> list[dict[str, Any]]:
    ensure_save_dirs()
    slots = []
    active_world = current_world_id()
    recorded_active_slot_id = get_recorded_active_slot_id()
    for item in sorted(SAVE_SLOT_DIR.iterdir(), key=lambda path: path.name):
        if not item.is_dir():
            continue
        meta = read_json(item / "metadata.json", {})
        slot_id = meta.get("id") or item.name
        savegames = slot_savegames_dir(slot_id)
        worlds = find_world_dirs(savegames)
        meta_world_id = normalize_world_id(meta.get("world_id", ""))
        world_id = meta_world_id or (require_world_id(worlds[0].name) if worlds else "")
        slots.append(
            {
                "id": slot_id,
                "name": meta.get("name") or slot_id,
                "world_id": world_id,
                "source": meta.get("source", ""),
                "notes": meta.get("notes", ""),
                "created_at": meta.get("created_at", ""),
                "last_used_at": meta.get("last_used_at", ""),
                "is_new": bool(meta.get("is_new")),
                "matches_active_world": bool(world_id and world_id == active_world),
                "size_bytes": dir_size(savegames),
                "updated_at": format_ts(latest_mtime(savegames)),
            }
        )
    recorded_slot = next((slot for slot in slots if slot["id"] == recorded_active_slot_id), None)
    if not recorded_slot or (active_world and recorded_slot.get("world_id") != active_world):
        matching_slots = [slot for slot in slots if slot["matches_active_world"]]
        matching_slots.sort(
            key=lambda slot: (
                slot.get("last_used_at") or "",
                slot.get("updated_at") or "",
                slot.get("created_at") or "",
                slot.get("id") or "",
            ),
            reverse=True,
        )
        recorded_active_slot_id = matching_slots[0]["id"] if matching_slots else ""

    for slot in slots:
        slot["is_active"] = bool(recorded_active_slot_id and slot["id"] == recorded_active_slot_id)
        slot["is_same_world_copy"] = bool(slot["matches_active_world"] and not slot["is_active"])
    return slots


def create_slot(name: str, notes: str = "", slot_id: str | None = None, is_new: bool = True) -> dict[str, Any]:
    ensure_save_dirs()
    slot_id = require_slot_id(slot_id or normalize_slot_id(name or "new-world"))
    path = slot_path(slot_id)
    if path.exists():
        raise ValueError("存档槽已存在")
    (path / "SaveGames" / "0").mkdir(parents=True)
    metadata = {
        "id": slot_id,
        "name": name or slot_id,
        "world_id": generate_world_id(),
        "created_at": iso_now(),
        "last_used_at": None,
        "source": "new",
        "notes": notes,
        "is_new": is_new,
    }
    write_json(path / "metadata.json", metadata)
    return metadata


def import_slot(source_path: str, name: str, notes: str = "", slot_id: str | None = None) -> dict[str, Any]:
    ensure_save_dirs()
    source_root, world_id, direct_world = savegames_payload_root(Path(source_path).expanduser())
    world_id = require_world_id(world_id)
    if path_within(source_root, SAVE_ROOT) and get_server_status()["running"]:
        raise ValueError("服务器运行中不能从当前活跃存档目录导入，请先停止服务器或复制到导入目录")
    slot_id = require_slot_id(slot_id or normalize_slot_id(name or world_id))
    path = slot_path(slot_id)
    if path.exists():
        raise ValueError("存档槽已存在")
    target_root = path / "SaveGames" / "0"
    if direct_world:
        copytree_clean(source_root, target_root / world_id)
    else:
        copytree_clean(source_root, target_root)
        target_worlds = find_world_dirs(target_root)
        if len(target_worlds) == 1 and target_worlds[0].name != world_id:
            normalized_target = target_root / world_id
            if normalized_target.exists():
                raise ValueError("目标存档世界目录已存在")
            target_worlds[0].rename(normalized_target)
    config_source = source_root.parent.parent / "Config" if direct_world and source_root.parent.name == "0" else source_root / "Config"
    if config_source.exists() and path_within(config_source, SAVE_ROOT):
        copytree_clean(config_source, path / "Config")
    metadata = {
        "id": slot_id,
        "name": name or slot_id,
        "world_id": world_id,
        "created_at": iso_now(),
        "last_used_at": None,
        "source": "imported",
        "source_path": str(source_root),
        "notes": notes,
        "is_new": False,
    }
    write_json(path / "metadata.json", metadata)
    return metadata


def upload_save_slot(file_storage, name: str, notes: str = "", slot_id: str | None = None) -> dict[str, Any]:
    ensure_save_dirs()
    filename = Path(file_storage.filename or "").name
    if not filename:
        raise ValueError("请选择要上传的存档压缩包")
    if not filename.lower().endswith(".zip"):
        raise ValueError("目前只支持上传 .zip 存档包")

    upload_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{normalize_slot_id(name or filename)}"
    upload_dir = SAVE_IMPORT_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=False)
    zip_path = upload_dir / "upload.zip"
    try:
        file_storage.save(zip_path)
        if zip_path.stat().st_size > SAVE_UPLOAD_MAX_BYTES:
            raise ValueError("存档文件太大")

        extract_dir = upload_dir / "extracted"
        extract_dir.mkdir()
        safe_extract_zip(zip_path, extract_dir)
        payload_root = uploaded_save_payload_root(extract_dir)
        slot = import_slot(str(payload_root), name=name, notes=notes, slot_id=slot_id)
        return slot
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


def backup_current_save(reason: str = "manual") -> dict[str, Any]:
    ensure_save_dirs()
    if not ACTIVE_SAVEGAMES_DIR.exists() or not any(ACTIVE_SAVEGAMES_DIR.iterdir()):
        raise ValueError("当前存档目录为空，无法备份")
    world_id = current_world_id() or "unknown"
    backup_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{reason}-{world_id}"
    target = SAVE_BACKUP_DIR / backup_id
    copytree_clean(ACTIVE_SAVEGAMES_DIR, target / "SaveGames" / "0")
    if CONFIG_DIR.exists():
        copytree_clean(CONFIG_DIR, target / "Config" / "LinuxServer")
    metadata = {
        "id": backup_id,
        "world_id": world_id,
        "created_at": iso_now(),
        "reason": reason,
        "size_bytes": dir_size(target),
    }
    write_json(target / "metadata.json", metadata)
    return metadata


def wait_for_service_state(active: bool, timeout: int = 80) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_server_status()["running"] is active:
            return True
        time.sleep(2)
    return False


def fix_save_ownership() -> None:
    if using_docker_backend():
        return
    owner = f"{PANEL_USER}:{PANEL_USER}"
    run_command([CHOWN, "-R", owner, str(SAVE_ROOT / "SaveGames")], timeout=60, sudo=True)
    run_command([CHOWN, "-R", owner, str(CONFIG_DIR)], timeout=60, sudo=True)


def switch_save_slot(slot_id: str) -> dict[str, Any]:
    slot_id = require_slot_id(slot_id)
    path = slot_path(slot_id)
    if not path.exists():
        raise ValueError("目标存档槽不存在")
    metadata = read_json(path / "metadata.json", {"id": slot_id, "name": slot_id})
    slot_savegames = slot_savegames_dir(slot_id)
    worlds = find_world_dirs(slot_savegames)
    is_new = bool(metadata.get("is_new"))
    if not worlds and not is_new:
        raise ValueError("目标存档槽无有效存档")

    steps: list[dict[str, Any]] = []

    def step(name: str, success: bool = True, message: str = "") -> None:
        steps.append({"step": name, "success": success, "message": message})

    original_game_user = GAME_USER_SETTINGS.read_text(encoding="utf-8", errors="replace") if GAME_USER_SETTINGS.exists() else None
    was_running = get_server_status()["running"]
    if was_running:
        success, message = _service_action_unlocked("stop")
        step("stop", success, message)
        if not success or not wait_for_service_state(False):
            raise RuntimeError("停止服务器失败，已取消切换")
    else:
        step("stop", True, "server already stopped")

    backup = None
    try:
        backup = backup_current_save("before-switch")
        step("backup", True, backup["id"])
    except ValueError as exc:
        if "当前存档目录为空" not in str(exc):
            raise
        step("backup", True, "当前存档目录为空，跳过备份")

    world_id = ""

    def rollback_after_failure(reason: Exception) -> None:
        try:
            current_status = get_server_status()
            if current_status.get("container_running"):
                _service_action_unlocked("stop")
                wait_for_service_state(False, timeout=60)
            remove_children(ACTIVE_SAVEGAMES_DIR)
            if backup:
                copytree_clean(SAVE_BACKUP_DIR / backup["id"] / "SaveGames" / "0", ACTIVE_SAVEGAMES_DIR)
            if original_game_user is None:
                if GAME_USER_SETTINGS.exists():
                    GAME_USER_SETTINGS.unlink()
            else:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                tmp = GAME_USER_SETTINGS.with_suffix(".ini.tmp")
                tmp.write_text(original_game_user, encoding="utf-8")
                tmp.replace(GAME_USER_SETTINGS)
            fix_save_ownership()
            if was_running:
                _service_action_unlocked("start")
            step("rollback", True, "已回滚到切换前存档")
        except Exception as rollback_exc:
            step("rollback", False, str(rollback_exc))
            raise RuntimeError(f"{reason}; 回滚失败：{rollback_exc}") from rollback_exc

    try:
        remove_children(ACTIVE_SAVEGAMES_DIR)
        if worlds:
            copytree_clean(slot_savegames, ACTIVE_SAVEGAMES_DIR)
            world_id = require_world_id(metadata.get("world_id") or worlds[0].name)
        else:
            world_id = normalize_world_id(metadata.get("world_id", "")) or generate_world_id()
        write_dedicated_server_name(world_id)
        fix_save_ownership()
        step("switch", True, world_id)
        step("permissions", True, "权限已修复")

        if was_running:
            success, message = _service_action_unlocked("start")
            step("start", success, message)
            if not success:
                raise RuntimeError(message)
            restored = wait_for_service_state(True, timeout=90)
            step("status", restored, "server running" if restored else "server did not report running in time")
            if not restored:
                raise RuntimeError("服务器启动后未在限定时间内恢复运行")
        else:
            step("start", True, "server was stopped; leaving it stopped")
    except Exception as exc:
        rollback_after_failure(exc)
        raise RuntimeError(f"{exc}; 已回滚到切换前存档") from exc

    metadata["last_used_at"] = iso_now()
    metadata["world_id"] = world_id
    write_json(path / "metadata.json", metadata)
    set_recorded_active_slot(slot_id, world_id)
    return {"slot": metadata, "backup": backup, "steps": steps, "running": get_server_status()["running"]}


def delete_save_slot(slot_id: str) -> dict[str, Any]:
    slot_id = require_slot_id(slot_id)
    path = slot_path(slot_id)
    if not path.exists():
        raise ValueError("存档槽不存在")
    meta = read_json(path / "metadata.json", {"id": slot_id, "name": slot_id})
    active_slot_id = get_recorded_active_slot_id()
    if not active_slot_id:
        active_slot = next((slot for slot in list_save_slots() if slot.get("is_active")), None)
        active_slot_id = active_slot.get("id", "") if active_slot else ""
    if slot_id == active_slot_id:
        raise ValueError("不能删除当前正在使用的存档")
    if not path_within(path, SAVE_SLOT_DIR):
        raise ValueError("存档槽路径异常")
    shutil.rmtree(path)
    return meta


def unquote_setting(value: str, fallback: str = "") -> str:
    return decode_setting_string(value, fallback=fallback)


def rcon_command(command: str) -> str:
    """Send an RCON command to the configured Palworld server."""
    return send_rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, command, timeout=RCON_TIMEOUT_SECONDS)


def execute_panel_rcon_command(command: str):
    """Run a command and retain its acknowledgement metadata for the API."""
    command_name = command.split(maxsplit=1)[0].casefold()
    return execute_rcon_command(
        RCON_HOST,
        RCON_PORT,
        RCON_PASSWORD,
        command,
        timeout=RCON_TIMEOUT_SECONDS,
        allow_no_response=command_name in {"broadcast", "showplayers"},
    )


def get_server_status() -> dict[str, Any]:
    if using_docker_backend():
        try:
            game_state = get_docker_game_state()
            return {
                "running": game_state["running"],
                "pid": game_state["pid"],
                "start_time": game_state["start_time"] if game_state["container_running"] else "",
                "service_name": PALWORLD_CONTAINER_NAME,
                "backend": "docker",
                "container_running": game_state["container_running"],
                "installed": game_state["installed"],
                "ready": game_state["ready"],
                "rcon_ready": game_state["rcon_ready"],
                "phase": game_state["phase"],
                "message": game_state["message"],
            }
        except Exception as exc:
            return {
                "running": False,
                "pid": "",
                "start_time": "",
                "service_name": PALWORLD_CONTAINER_NAME,
                "backend": "docker",
                "container_running": False,
                "installed": False,
                "ready": False,
                "rcon_ready": False,
                "phase": "error",
                "message": str(exc),
                "error": str(exc),
            }

    out, _, _ = systemctl_query("is-active", PALWORLD_SERVICE, timeout=10)
    running = out.strip() == "active"
    pid = ""
    start_time = ""

    if running:
        pid, _, _ = systemctl("show", PALWORLD_SERVICE, "--property=MainPID", "--value", timeout=10)
        start_time, _, _ = systemctl(
            "show",
            PALWORLD_SERVICE,
            "--property=ActiveEnterTimestamp",
            "--value",
            timeout=10,
        )

    return {
        "running": running,
        "pid": pid.strip(),
        "start_time": start_time.strip(),
        "service_name": PALWORLD_SERVICE,
        "backend": "systemd",
    }


def parse_players(rcon_response: str) -> list[dict[str, str]]:
    players: list[dict[str, str]] = []
    if not rcon_response or rcon_response.startswith("[RCON Error]"):
        return players

    lines = [line.strip() for line in rcon_response.splitlines() if line.strip()]
    if lines and lines[0].lower().startswith("name,"):
        lines = lines[1:]

    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        players.append(
            {
                "name": parts[0],
                "account_name": "",
                "player_id": parts[1],
                "level": "",
                "ping": "",
            }
        )
    return players


def get_rest_players() -> tuple[list[dict[str, str]], str]:
    if not PALWORLD_REST_ENABLED:
        raise RuntimeError("disabled")
    if not PALWORLD_REST_PASSWORD:
        raise RuntimeError("not_configured")

    path = "/" + PALWORLD_REST_PATH.lstrip("/")
    url = f"http://{PALWORLD_REST_HOST}:{PALWORLD_REST_PORT}{path}"
    credentials = f"{PALWORLD_REST_USERNAME}:{PALWORLD_REST_PASSWORD}".encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
    }

    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=request_headers), timeout=PALWORLD_REST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("auth_failed") from exc
        raise RuntimeError("request_failed") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("unreachable") from exc

    raw_players = payload.get("players") if isinstance(payload, dict) else None
    if not isinstance(raw_players, list):
        raise RuntimeError("bad_response")

    players: list[dict[str, str]] = []
    for raw_player in raw_players:
        if not isinstance(raw_player, dict):
            continue
        players.append(
            {
                "name": str(raw_player.get("name") or ""),
                "account_name": str(raw_player.get("accountName") or ""),
                "player_id": str(raw_player.get("playerId") or raw_player.get("userId") or ""),
                "level": str(raw_player.get("level") or ""),
                "ping": str(raw_player.get("ping") or ""),
            }
        )
    return players, "rest"


def get_online_players(player_list_enabled: bool) -> dict[str, Any]:
    global _player_response_cache
    with _player_response_lock:
        if len(_player_response_cache) == 3:
            cached_at, cached_policy, cached_result = _player_response_cache
        else:
            cached_at, cached_result = _player_response_cache
            cached_policy = None
        if cached_policy == player_list_enabled and time.monotonic() - cached_at < PLAYER_CACHE_TTL_SECONDS:
            return dict(cached_result)

    result: dict[str, Any] = {
        "players": [],
        "source": "none",
        "query_ok": False,
        "error": "disabled",
        "fallback_used": False,
    }
    try:
        players, source = get_rest_players()
        result.update({"players": players, "source": source, "query_ok": True, "error": ""})
    except RuntimeError as rest_error:
        result["error"] = str(rest_error)
        if player_list_enabled:
            response = rcon_command("ShowPlayers")
            if not response.startswith("[RCON Error]"):
                result.update({"players": parse_players(response), "source": "rcon", "query_ok": True, "error": "", "fallback_used": True})
            else:
                result["error"] = "rcon_failed"

    with _player_response_lock:
        _player_response_cache = (time.monotonic(), player_list_enabled, result)
    return dict(result)


def get_game_version() -> str:
    lines = docker_container_logs(120) if using_docker_backend() else journalctl("-u", PALWORLD_SERVICE, "-n", "80", "--no-pager", timeout=10)[0].splitlines()
    for line in reversed(lines):
        match = re.search(r"Game version is (v?[\d.]+)", line)
        if match:
            return match.group(1)
    return ""


def get_server_info() -> dict[str, Any]:
    settings = parse_palworld_settings()
    player_list_enabled = settings.get("bShowPlayerList", "False") == "True"
    player_result = get_online_players(player_list_enabled)
    players = player_result["players"]
    players_query_ok = player_result["query_ok"]
    players_response_empty = players_query_ok and not players
    return {
        "server_name": unquote_setting(settings.get("ServerName", "")),
        "server_description": unquote_setting(settings.get("ServerDescription", "")),
        "port": settings.get("PublicPort", "8211"),
        "rcon_port": settings.get("RCONPort", str(RCON_PORT)),
        "game_version": get_game_version(),
        "online_players": players,
        "players_query_ok": players_query_ok,
        "player_list_enabled": player_list_enabled,
        "players_response_empty": players_response_empty,
        "players_source": player_result["source"],
        "players_error": player_result["error"],
        "players_fallback_used": player_result["fallback_used"],
        "max_players": settings.get("ServerPlayerMaxNum", "32"),
        "exp_rate": settings.get("ExpRate", "1.0"),
    }


def read_cpu_times() -> tuple[int, int] | None:
    try:
        first = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
        values = [int(item) for item in first[1:]]
    except Exception:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def get_cpu_percent() -> float | None:
    first = read_cpu_times()
    if first is None:
        return None
    time.sleep(0.08)
    second = read_cpu_times()
    if second is None:
        return None
    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(max(0, min(100, (1 - idle_delta / total_delta) * 100)), 1)


def get_memory_info() -> dict[str, Any]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
    except Exception:
        return {"total": 0, "used": 0, "percent": None}
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)
    percent = round((used / total) * 100, 1) if total else None
    return {"total": total, "used": used, "percent": percent}


def get_system_info() -> dict[str, Any]:
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    disk = shutil.disk_usage(PALWORLD_DIR if PALWORLD_DIR.exists() else "/")
    uptime_seconds = 0.0
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except Exception:
        pass
    return {
        "cpu_percent": get_cpu_percent(),
        "load": [round(item, 2) for item in load],
        "memory": get_memory_info(),
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": round((disk.used / disk.total) * 100, 1) if disk.total else None,
        },
        "uptime_seconds": int(uptime_seconds),
    }


def get_server_log(lines: int = 80) -> list[str]:
    if using_docker_backend():
        return docker_container_logs(lines)

    safe_lines = str(max(1, min(int(lines), 300)))
    out, err, code = journalctl(
        "-u",
        PALWORLD_SERVICE,
        "-n",
        safe_lines,
        "--no-pager",
        "--output=cat",
        timeout=15,
    )
    if code != 0:
        return [err or "Unable to read logs"]
    return out.splitlines() or ["No log entries available"]


def get_server_log_stream(max_seconds: int | None = None):
    previous: list[str] = []
    deadline = time.monotonic() + (LOG_STREAM_MAX_SECONDS if max_seconds is None else max(0, max_seconds))
    while time.monotonic() < deadline:
        current = get_server_log(100)[-100:]
        overlap = 0
        for size in range(min(len(previous), len(current)), 0, -1):
            if previous[-size:] == current[:size]:
                overlap = size
                break
        for line in current[overlap:]:
            yield f"data: {line}\n\n"
        previous = current
        yield "data: \n\n"
        time.sleep(3)


def _service_action_unlocked(action: str) -> tuple[bool, str]:
    if action not in {"start", "stop", "restart"}:
        return False, "Unsupported action"

    if using_docker_backend():
        try:
            container = get_docker_container()
            if action == "start":
                container.start()
            elif action == "stop":
                container.stop(timeout=60)
            elif action == "restart":
                container.restart(timeout=90)
            time.sleep(3 if action == "restart" else 2)
            container.reload()
            container_running = container.status == "running"
            if action in {"start", "restart"}:
                if container_running:
                    messages = {
                        "start": "Server container started; Palworld is starting",
                        "restart": "Server container restarted; Palworld is starting",
                    }
                    return True, messages[action]
                return False, f"Docker container {action} did not enter running state"
            if not container_running:
                return True, "Server container stopped"
            return False, "Docker container stop did not reach expected state"
        except Exception as exc:
            return False, str(exc)

    _, err, code = systemctl(action, PALWORLD_SERVICE, timeout=60)
    time.sleep(2 if action != "restart" else 3)
    running = get_server_status()["running"]
    success = running if action in {"start", "restart"} else not running
    if success:
        messages = {"start": "Server started", "stop": "Server stopped", "restart": "Server restarted"}
        return True, messages[action]
    return False, err or f"systemctl {action} exited with {code}"


def service_action(action: str) -> tuple[bool, str]:
    try:
        with save_operation_lock():
            return _service_action_unlocked(action)
    except SaveOperationBusy as exc:
        return False, str(exc)


@app.route("/")
def index():
    return render_template("index.html", app_version=APP_VERSION)


@app.after_request
def add_cache_headers(response):
    if request.path == "/" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/api/status")
def api_status():
    status = get_server_status()
    offline_info = {
        "server_name": "N/A",
        "server_description": "",
        "port": "N/A",
        "rcon_port": "N/A",
        "game_version": "N/A",
        "online_players": [],
        "players_query_ok": False,
        "player_list_enabled": False,
        "players_response_empty": False,
        "players_source": "none",
        "players_error": "not_running",
        "players_fallback_used": False,
        "max_players": "N/A",
        "exp_rate": "N/A",
    }
    return jsonify({
        "status": status,
        "info": get_server_info() if status["running"] else offline_info,
        "upload_limits": {
            "save_upload_max_bytes": SAVE_UPLOAD_MAX_BYTES,
            "save_upload_max_extracted_bytes": SAVE_UPLOAD_MAX_EXTRACTED_BYTES,
            "mod_upload_max_bytes": MOD_UPLOAD_MAX_BYTES,
        },
    })


@app.route("/api/system")
def api_system():
    return jsonify({"success": True, "system": get_system_info()})


@app.route("/api/audit")
def api_audit():
    try:
        limit = int(request.args.get("limit", "80"))
    except ValueError:
        limit = 80
    return jsonify({"success": True, "records": read_audit_events(limit)})


@app.route("/api/update/status")
def api_update_status():
    return jsonify({"success": True, "status": read_update_status()})


@app.route("/api/update/check", methods=["POST"])
def api_update_check():
    success, message = run_update_check_now()
    audit_event("update.check", success, message=message)
    return jsonify({"success": success, "message": message, "status": read_update_status()}), (200 if success else 500)


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    success, message = start_update_service()
    audit_event("update.apply", success, message=message)
    return jsonify({"success": success, "message": message, "status": read_update_status()}), (202 if success else 409)


@app.route("/api/install/status")
def api_install_status():
    return jsonify({"success": True, "status": read_install_status()})


@app.route("/api/install/check", methods=["POST"])
def api_install_check():
    success, message = run_install_check_now()
    audit_event("install.check", success, message=message)
    return jsonify({"success": success, "message": message, "status": read_install_status()}), (200 if success else 500)


@app.route("/api/install/palworld", methods=["POST"])
def api_install_palworld():
    success, message = start_install_service("install-palworld")
    audit_event("install.palworld", success, message=message)
    return jsonify({"success": success, "message": message, "status": read_install_status()}), (202 if success else 409)


@app.route("/api/install/repair", methods=["POST"])
def api_install_repair():
    success, message = start_install_service("repair")
    audit_event("install.repair", success, message=message)
    return jsonify({"success": success, "message": message, "status": read_install_status()}), (202 if success else 409)


@app.route("/api/start", methods=["POST"])
def api_start():
    success, message = service_action("start")
    audit_event("service.start", success, message=message)
    return jsonify({"success": success, "message": message})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    success, message = service_action("stop")
    audit_event("service.stop", success, message=message)
    return jsonify({"success": success, "message": message})


@app.route("/api/restart", methods=["POST"])
def api_restart():
    success, message = service_action("restart")
    audit_event("service.restart", success, message=message)
    return jsonify({"success": success, "message": message})


@app.route("/api/log")
def api_log():
    lines = request.args.get("lines", "80")
    try:
        line_count = int(lines)
    except ValueError:
        line_count = 80
    return jsonify({"lines": get_server_log(line_count)})


@app.route("/api/log/stream")
def api_log_stream():
    return Response(
        stream_with_context(get_server_log_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/rcon", methods=["POST"])
def api_rcon():
    data = request.get_json(silent=True) or {}
    command = str(data.get("command", "")).strip()
    if not command:
        return jsonify({"success": False, "message": "No command provided"}), 400
    command_name = command.split(maxsplit=1)[0].casefold()
    if command_name == "broadcast" and any(ord(char) > 127 for char in command):
        message = "Palworld RCON 广播仅可靠支持英文/ASCII 字符；中文或表情会被游戏端错误解析"
        audit_event("rcon.command", False, command=command, message=message)
        return jsonify({"success": False, "acknowledged": False, "response": "", "message": message}), 400

    result = execute_panel_rcon_command(command)
    audit_event(
        "rcon.command",
        result.success,
        command=command,
        acknowledged=result.acknowledged,
        message=result.message,
    )
    return jsonify(
        {
            "success": result.success,
            "acknowledged": result.acknowledged,
            "response": result.response,
            "message": result.message,
        }
    ), (200 if result.success else 502)


@app.route("/api/saves/status")
def api_saves_status():
    try:
        ensure_save_dirs()
        return jsonify(
            {
                "success": True,
                "active": get_active_save_info(),
                "service": get_server_status(),
                "slot_root": str(SAVE_SLOT_ROOT),
                "import_hint": str(SAVE_IMPORT_DIR),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/slots")
def api_saves_slots():
    try:
        return jsonify({"success": True, "slots": list_save_slots()})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/backup_current", methods=["POST"])
def api_saves_backup_current():
    if get_server_status()["running"]:
        message = "服务器运行中不能手动备份，请先停止服务器，或使用切换流程自动备份"
        audit_event("saves.backup_current", False, message=message)
        return jsonify({"success": False, "message": message}), 409
    try:
        with save_operation_lock():
            backup = backup_current_save("manual")
        audit_event("saves.backup_current", True, backup_id=backup["id"])
        return jsonify({"success": True, "backup": backup, "message": "当前存档已备份"})
    except SaveOperationBusy as exc:
        audit_event("saves.backup_current", False, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except Exception as exc:
        audit_event("saves.backup_current", False, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/create_slot", methods=["POST"])
def api_saves_create_slot():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    notes = str(data.get("notes", "")).strip()
    slot_id = str(data.get("slot_id", "")).strip() or None
    if not name:
        return jsonify({"success": False, "message": "请输入存档名称"}), 400
    try:
        with save_operation_lock():
            slot = create_slot(name=name, notes=notes, slot_id=slot_id, is_new=True)
        audit_event("saves.create_slot", True, slot_id=slot["id"])
        return jsonify({"success": True, "slot": slot, "message": "新存档槽已创建"})
    except SaveOperationBusy as exc:
        audit_event("saves.create_slot", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("saves.create_slot", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("saves.create_slot", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/import_slot", methods=["POST"])
def api_saves_import_slot():
    data = request.get_json(silent=True) or {}
    source_path = str(data.get("source_path", "")).strip()
    name = str(data.get("name", "")).strip()
    notes = str(data.get("notes", "")).strip()
    slot_id = str(data.get("slot_id", "")).strip() or None
    if not source_path or not name:
        return jsonify({"success": False, "message": "请输入导入路径和存档名称"}), 400
    try:
        with save_operation_lock():
            slot = import_slot(source_path=source_path, name=name, notes=notes, slot_id=slot_id)
        audit_event("saves.import_slot", True, slot_id=slot["id"], source_path=source_path)
        return jsonify({"success": True, "slot": slot, "message": "存档已导入"})
    except SaveOperationBusy as exc:
        audit_event("saves.import_slot", False, slot_id=slot_id, source_path=source_path, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("saves.import_slot", False, slot_id=slot_id, source_path=source_path, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("saves.import_slot", False, slot_id=slot_id, source_path=source_path, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/upload_slot", methods=["POST"])
def api_saves_upload_slot():
    file_storage = request.files.get("file")
    name = str(request.form.get("name", "")).strip()
    notes = str(request.form.get("notes", "")).strip()
    slot_id = str(request.form.get("slot_id", "")).strip() or None
    if not file_storage or not name:
        return jsonify({"success": False, "message": "请选择 zip 文件并输入存档名称"}), 400
    try:
        with save_operation_lock():
            slot = upload_save_slot(file_storage, name=name, notes=notes, slot_id=slot_id)
        audit_event("saves.upload_slot", True, slot_id=slot["id"], filename=file_storage.filename)
        return jsonify({"success": True, "slot": slot, "message": "存档上传并导入完成"})
    except SaveOperationBusy as exc:
        audit_event("saves.upload_slot", False, slot_id=slot_id, filename=file_storage.filename, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("saves.upload_slot", False, slot_id=slot_id, filename=file_storage.filename, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("saves.upload_slot", False, slot_id=slot_id, filename=file_storage.filename, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/switch", methods=["POST"])
def api_saves_switch():
    data = request.get_json(silent=True) or {}
    slot_id = str(data.get("slot_id", "")).strip()
    if not slot_id:
        return jsonify({"success": False, "message": "缺少目标存档槽"}), 400
    try:
        with save_operation_lock():
            result = switch_save_slot(slot_id)
        audit_event(
            "saves.switch",
            True,
            slot_id=slot_id,
            backup_id=(result.get("backup") or {}).get("id"),
            running=result.get("running"),
        )
        message = "存档切换完成，服务器已启动" if result.get("running") else "存档切换完成，服务器保持停止"
        return jsonify({"success": True, "message": message, **result})
    except SaveOperationBusy as exc:
        audit_event("saves.switch", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("saves.switch", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("saves.switch", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/saves/slots/<slot_id>", methods=["DELETE"])
def api_saves_delete_slot(slot_id: str):
    try:
        with save_operation_lock():
            slot = delete_save_slot(slot_id)
        audit_event("saves.delete_slot", True, slot_id=slot_id)
        return jsonify({"success": True, "slot": slot, "message": "存档槽已删除"})
    except SaveOperationBusy as exc:
        audit_event("saves.delete_slot", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("saves.delete_slot", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("saves.delete_slot", False, slot_id=slot_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/status")
def api_mods_status():
    try:
        return jsonify({"success": True, "status": get_mod_status()})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/list")
def api_mods_list():
    try:
        return jsonify({"success": True, "mods": list_mods()})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/upload", methods=["POST"])
def api_mods_upload():
    file_storage = request.files.get("file")
    name = str(request.form.get("name", "")).strip()
    notes = str(request.form.get("notes", "")).strip()
    if not file_storage:
        return jsonify({"success": False, "message": "请选择 .pak、.sig 或 .zip MOD 文件"}), 400
    try:
        with save_operation_lock():
            mod = upload_mod(file_storage, name=name, notes=notes)
        audit_event("mods.upload", True, mod_id=mod["id"], filename=file_storage.filename, mod_type=mod.get("type"))
        return jsonify({"success": True, "mod": mod, "message": "MOD 上传并导入完成"})
    except SaveOperationBusy as exc:
        audit_event("mods.upload", False, filename=file_storage.filename, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("mods.upload", False, filename=file_storage.filename, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("mods.upload", False, filename=file_storage.filename, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/enable", methods=["POST"])
def api_mods_enable():
    data = request.get_json(silent=True) or {}
    mod_id = str(data.get("mod_id", "")).strip()
    allow_official = bool(data.get("allow_official"))
    if not mod_id:
        return jsonify({"success": False, "message": "缺少 mod_id"}), 400
    try:
        with save_operation_lock():
            mod = set_mod_enabled(mod_id, True, allow_official=allow_official)
        audit_event("mods.enable", True, mod_id=mod_id, mod_type=mod.get("type"))
        return jsonify({"success": True, "mod": mod, "message": "MOD 已启用，重启服务器后生效"})
    except SaveOperationBusy as exc:
        audit_event("mods.enable", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("mods.enable", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("mods.enable", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/disable", methods=["POST"])
def api_mods_disable():
    data = request.get_json(silent=True) or {}
    mod_id = str(data.get("mod_id", "")).strip()
    if not mod_id:
        return jsonify({"success": False, "message": "缺少 mod_id"}), 400
    try:
        with save_operation_lock():
            mod = set_mod_enabled(mod_id, False)
        audit_event("mods.disable", True, mod_id=mod_id, mod_type=mod.get("type"))
        return jsonify({"success": True, "mod": mod, "message": "MOD 已禁用，重启服务器后生效"})
    except SaveOperationBusy as exc:
        audit_event("mods.disable", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("mods.disable", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("mods.disable", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/<mod_id>", methods=["DELETE"])
def api_mods_delete(mod_id: str):
    try:
        with save_operation_lock():
            mod = delete_mod(mod_id)
        audit_event("mods.delete", True, mod_id=mod_id)
        return jsonify({"success": True, "mod": mod, "message": "MOD 已移入废纸篓，重启服务器后生效"})
    except SaveOperationBusy as exc:
        audit_event("mods.delete", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("mods.delete", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("mods.delete", False, mod_id=mod_id, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/empty_trash", methods=["POST"])
def api_mods_empty_trash():
    try:
        with save_operation_lock():
            count = empty_mod_trash()
        audit_event("mods.empty_trash", True, count=count)
        return jsonify({"success": True, "count": count, "message": f"已清理 {count} 个废纸篓项目"})
    except SaveOperationBusy as exc:
        audit_event("mods.empty_trash", False, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except Exception as exc:
        audit_event("mods.empty_trash", False, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/mods/apply_restart", methods=["POST"])
def api_mods_apply_restart():
    try:
        with save_operation_lock():
            result = restart_for_mods()
        audit_event(
            "mods.apply_restart",
            True,
            backup_id=(result.get("backup") or {}).get("id"),
            running=result.get("running"),
        )
        message = "服务器已重启，MOD 变更已应用" if result.get("running") else "MOD 变更已应用，服务器保持停止"
        return jsonify({"success": True, "message": message, **result})
    except SaveOperationBusy as exc:
        audit_event("mods.apply_restart", False, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except Exception as exc:
        audit_event("mods.apply_restart", False, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify({"settings": get_panel_settings()})


@app.route("/api/config", methods=["POST"])
def api_update_config():
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400
    changed_keys = get_changed_config_keys(data)
    try:
        with save_operation_lock():
            updated = update_palworld_settings(data)
        audit_event("config.save", True, changed_keys=changed_keys)
        return jsonify({"success": True, "settings": updated})
    except SaveOperationBusy as exc:
        audit_event("config.save", False, changed_keys=changed_keys, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("config.save", False, changed_keys=changed_keys, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("config.save", False, changed_keys=changed_keys, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/config/apply_restart", methods=["POST"])
def api_apply_config_restart():
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400
    changed_keys = get_changed_config_keys(data)
    try:
        with save_operation_lock():
            updated = update_palworld_settings(data)
            success, message = _service_action_unlocked("restart")
        audit_event("config.save_restart", success, changed_keys=changed_keys, message=message)
        return jsonify({"success": success, "settings": updated, "message": message}), (200 if success else 502)
    except SaveOperationBusy as exc:
        audit_event("config.save_restart", False, changed_keys=changed_keys, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 409
    except ValueError as exc:
        audit_event("config.save_restart", False, changed_keys=changed_keys, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        audit_event("config.save_restart", False, changed_keys=changed_keys, message=str(exc))
        return jsonify({"success": False, "message": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PANEL_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
