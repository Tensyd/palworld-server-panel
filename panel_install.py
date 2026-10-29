#!/usr/bin/env python3
"""Installer and repair helper for Palworld Panel.

The web panel starts this script through a fixed systemd oneshot. The script
accepts only whitelisted actions and writes progress to install-status.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any


PANEL_USER = os.environ.get("PANEL_USER", "demo")
PANEL_HOME = Path(os.environ.get("PANEL_HOME", f"/home/{PANEL_USER}"))
PANEL_DIR = Path(os.environ.get("PANEL_DIR", str(PANEL_HOME / "palworld-panel")))
PALWORLD_DIR = Path(os.environ.get("PALWORLD_DIR", str(PANEL_HOME / "palworld")))
STEAMCMD_DIR = Path(os.environ.get("STEAMCMD_DIR", str(PANEL_HOME / "steamcmd")))
STEAMCMD = Path(os.environ.get("STEAMCMD", str(STEAMCMD_DIR / "steamcmd.sh")))
PALWORLD_SERVICE = os.environ.get("PALWORLD_SERVICE", "palworld.service")
PANEL_SERVICE = os.environ.get("PANEL_SERVICE", "palworld-panel.service")
INSTALL_SERVICE = os.environ.get("PANEL_INSTALL_SERVICE", "palworld-panel-install.service")
PALWORLD_APP_ID = os.environ.get("PALWORLD_APP_ID", "2394010")
PANEL_PORT = os.environ.get("PANEL_PORT", "8080")
RCON_PORT = os.environ.get("RCON_PORT", "25575")
GAME_PORT = os.environ.get("PALWORLD_PORT", "8211")
QUERY_PORT = os.environ.get("PALWORLD_QUERY_PORT", "27015")

STATUS_PATH = Path(os.environ.get("PANEL_INSTALL_STATUS", str(PANEL_DIR / "install-status.json")))
LOG_PATH = Path(os.environ.get("PANEL_INSTALL_LOG", str(PANEL_DIR / "install.log")))
REQUEST_PATH = Path(os.environ.get("PANEL_INSTALL_REQUEST", str(PANEL_DIR / "install-request.json")))
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG", str(PANEL_DIR / "audit.log")))
ENV_FILE = Path(os.environ.get("PANEL_ENV_FILE", "/etc/palworld-panel.env"))
SAVE_SLOT_ROOT = Path(os.environ.get("SAVE_SLOT_ROOT", str(PANEL_DIR / "save-slots")))
LOCK_PATH = SAVE_SLOT_ROOT / ".operation.lock"

STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
APT_DEPS = [
    "ca-certificates",
    "curl",
    "tar",
    "python3",
    "python3-venv",
    "gunicorn",
    "sudo",
    "lib32gcc-s1",
    "lib32stdc++6",
]
ALLOWED_ACTIONS = {"install-palworld", "repair"}


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{iso_now()} {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return value if isinstance(value, dict) else default


class Status:
    def __init__(self) -> None:
        self.payload: dict[str, Any] = {
            "running": False,
            "phase": "idle",
            "message": "",
            "success": None,
            "started_at": "",
            "finished_at": "",
            "panel_user": PANEL_USER,
            "panel_dir": str(PANEL_DIR),
            "palworld_dir": str(PALWORLD_DIR),
            "steamcmd": str(STEAMCMD),
            "checks": {},
            "steps": [],
        }

    def load(self) -> None:
        self.payload.update(read_json(STATUS_PATH, {}))

    def set(self, **items: Any) -> None:
        self.payload.update(items)
        write_json(STATUS_PATH, self.payload)

    def step(self, name: str, state: str, message: str = "") -> None:
        steps = [item for item in self.payload.get("steps", []) if item.get("name") != name]
        steps.append({"name": name, "status": state, "message": message, "time": iso_now()})
        self.set(steps=steps)


status = Status()


def run(args: list[str], timeout: int = 300, env: dict[str, str] | None = None) -> tuple[str, str, int]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def run_checked(args: list[str], timeout: int = 300, env: dict[str, str] | None = None) -> str:
    log("$ " + " ".join(args))
    out, err, code = run(args, timeout=timeout, env=env)
    if out:
        log(out)
    if err:
        log(err)
    if code != 0:
        raise RuntimeError(err or out or f"command failed: {code}")
    return out


def run_as_user(args: list[str], timeout: int = 3600) -> str:
    env = os.environ.copy()
    env["HOME"] = str(PANEL_HOME)
    if os.geteuid() == 0:
        return run_checked(["sudo", "-u", PANEL_USER, "env", f"HOME={PANEL_HOME}", *args], timeout=timeout)
    return run_checked(args, timeout=timeout, env=env)


def append_audit(action: str, success: bool, **details: Any) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {"time": iso_now(), "source_ip": "installer", "action": action, "success": success, **details}
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


@contextmanager
def operation_lock():
    SAVE_SLOT_ROOT.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("w", encoding="utf-8")
    try:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another save/install/update operation is already running") from exc
        handle.write(f"install {os.getpid()} {iso_now()}\n")
        handle.flush()
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def systemctl_available() -> bool:
    return command_exists("systemctl") and Path("/run/systemd/system").exists()


def service_active(name: str) -> bool:
    if not systemctl_available():
        return False
    out, _, _ = run(["systemctl", "is-active", name], timeout=10)
    return out.strip() == "active"


def check_environment() -> dict[str, Any]:
    os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace") if Path("/etc/os-release").exists() else ""
    checks = {
        "is_root": os.geteuid() == 0,
        "os_supported": any(item in os_release for item in ["ID=ubuntu", "ID=debian", "ID_LIKE=debian"]),
        "apt_get": command_exists("apt-get"),
        "systemd": systemctl_available(),
        "python3": command_exists("python3"),
        "curl": command_exists("curl"),
        "tar": command_exists("tar"),
        "steamcmd_installed": STEAMCMD.exists(),
        "palworld_installed": (PALWORLD_DIR / "PalServer.sh").exists(),
        "palworld_manifest": (PALWORLD_DIR / "steamapps" / f"appmanifest_{PALWORLD_APP_ID}.acf").exists(),
        "panel_installed": (PANEL_DIR / "app.py").exists(),
        "env_file": ENV_FILE.exists(),
        "palworld_service_active": service_active(PALWORLD_SERVICE),
        "panel_service_active": service_active(PANEL_SERVICE),
    }
    status.set(
        phase="checked",
        message="Environment checked",
        success=True,
        finished_at=iso_now(),
        checks=checks,
        panel_user=PANEL_USER,
        panel_dir=str(PANEL_DIR),
        palworld_dir=str(PALWORLD_DIR),
        steamcmd=str(STEAMCMD),
    )
    return checks


def ensure_root() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("installer action requires root")


def ensure_user() -> None:
    status.step("user", "active", f"Ensuring user {PANEL_USER}")
    try:
        import pwd

        pwd.getpwnam(PANEL_USER)
    except KeyError:
        run_checked(["useradd", "-m", "-s", "/bin/bash", PANEL_USER], timeout=60)
    PANEL_HOME.mkdir(parents=True, exist_ok=True)
    status.step("user", "done", str(PANEL_HOME))


def install_dependencies() -> None:
    status.step("dependencies", "active", "Installing apt dependencies")
    if not command_exists("apt-get"):
        raise RuntimeError("apt-get is required on Ubuntu/Debian")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    run_checked(["apt-get", "update"], timeout=900, env=env)
    run_checked(["apt-get", "install", "-y", *APT_DEPS], timeout=1200, env=env)
    status.step("dependencies", "done", "Dependencies installed")


def install_steamcmd() -> None:
    status.step("steamcmd", "active", "Installing SteamCMD")
    if STEAMCMD.exists():
        status.step("steamcmd", "done", "SteamCMD already installed")
        return
    STEAMCMD_DIR.mkdir(parents=True, exist_ok=True)
    archive = STEAMCMD_DIR / "steamcmd_linux.tar.gz"
    log(f"Downloading SteamCMD from {STEAMCMD_URL}")
    urllib.request.urlretrieve(STEAMCMD_URL, archive)
    run_checked(["tar", "-xzf", str(archive), "-C", str(STEAMCMD_DIR)], timeout=120)
    run_checked(["chown", "-R", f"{PANEL_USER}:{PANEL_USER}", str(STEAMCMD_DIR)], timeout=120)
    status.step("steamcmd", "done", str(STEAMCMD))


def install_palworld_server() -> None:
    status.step("palworld", "active", "Downloading Palworld Dedicated Server")
    PALWORLD_DIR.mkdir(parents=True, exist_ok=True)
    run_checked(["chown", "-R", f"{PANEL_USER}:{PANEL_USER}", str(PALWORLD_DIR)], timeout=120)
    run_as_user(
        [
            str(STEAMCMD),
            "+@sSteamCmdForcePlatformType",
            "linux",
            "+@sSteamCmdForcePlatformBitness",
            "64",
            "+force_install_dir",
            str(PALWORLD_DIR),
            "+login",
            "anonymous",
            "+app_update",
            PALWORLD_APP_ID,
            "validate",
            "+quit",
        ],
        timeout=5400,
    )
    status.step("palworld", "done", "Palworld server installed")


def upsert_env(path: Path, values: dict[str, str], overwrite_empty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = value.strip()
    for key, value in values.items():
        if key not in existing or (overwrite_empty and not existing[key]):
            existing[key] = value
    text = "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n"
    path.write_text(text, encoding="utf-8")
    run_checked(["chown", "root:root", str(path)], timeout=30)
    run_checked(["chmod", "600", str(path)], timeout=30)


def configure_palworld() -> str:
    status.step("config", "active", "Generating panel env and Palworld config")
    admin_password = os.environ.get("RCON_PASSWORD") or secrets.token_urlsafe(18)
    upsert_env(
        ENV_FILE,
        {
            "PANEL_PORT": PANEL_PORT,
            "PANEL_USER": PANEL_USER,
            "PANEL_HOME": str(PANEL_HOME),
            "PANEL_DIR": str(PANEL_DIR),
            "PALWORLD_DIR": str(PALWORLD_DIR),
            "PALWORLD_SERVICE": PALWORLD_SERVICE,
            "PALWORLD_BACKEND": "systemd",
            "RCON_HOST": "127.0.0.1",
            "RCON_PORT": RCON_PORT,
            "RCON_PASSWORD": admin_password,
            "PANEL_SECRET_KEY": secrets.token_hex(32),
            "STEAMCMD": str(STEAMCMD),
            "PALWORLD_APP_ID": PALWORLD_APP_ID,
            "PALWORLD_DEPOT_ID": "2394012",
            "AUTO_UPDATE_ENABLED": "false",
            "MOD_LIBRARY_ROOT": str(PANEL_DIR / "mod-library"),
            "MOD_UPLOAD_MAX_BYTES": "1073741824",
            "PALWORLD_MOD_MODE": "pak-safe",
            "PANEL_INSTALL_SCRIPT": str(PANEL_DIR / "panel_install.py"),
            "PANEL_UPDATE_SCRIPT": str(PANEL_DIR / "panel_update.py"),
        },
    )

    config_dir = PALWORLD_DIR / "Pal" / "Saved" / "Config" / "LinuxServer"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings = config_dir / "PalWorldSettings.ini"
    if not settings.exists():
        default_settings = PALWORLD_DIR / "DefaultPalWorldSettings.ini"
        base = default_settings.read_text(encoding="utf-8", errors="replace") if default_settings.exists() else "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=()\n"
        if "OptionSettings=(" in base:
            base = reconfigure_option(base, admin_password)
        settings.write_text(base, encoding="utf-8")

    game_user = config_dir / "GameUserSettings.ini"
    if not game_user.exists():
        world_id = secrets.token_hex(16).upper()
        game_user.write_text(f"[/Script/Pal.PalGameInstance]\nDedicatedServerName={world_id}\n", encoding="utf-8")

    run_checked(["chown", "-R", f"{PANEL_USER}:{PANEL_USER}", str(PALWORLD_DIR / "Pal" / "Saved")], timeout=120)
    status.step("config", "done", "Config generated")
    return admin_password


def reconfigure_option(text: str, admin_password: str) -> str:
    replacements = {
        "RCONEnabled": "True",
        "RCONPort": RCON_PORT,
        "AdminPassword": f'"{admin_password}"',
        "PublicPort": GAME_PORT,
        "QueryPort": QUERY_PORT,
    }
    for key, value in replacements.items():
        if f"{key}=" in text:
            text = re.sub(rf"{key}=([^,\)]+)", f"{key}={value}", text)
        else:
            text = text.replace("OptionSettings=(", f"OptionSettings=({key}={value},", 1)
    return text


def render_service_files() -> dict[str, str]:
    """Build the systemd units as plain strings.

    Kept pure (no writes, no root) so the unit contents can be asserted in
    tests -- ``deploy/`` only holds reference copies and used to drift from
    what the installer actually wrote.
    """
    palworld_service = f"""[Unit]
Description=Palworld Dedicated Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User={PANEL_USER}
Group={PANEL_USER}
WorkingDirectory={PALWORLD_DIR}
ExecStart={PALWORLD_DIR}/PalServer.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
TimeoutStartSec=120
TimeoutStopSec=60
Environment=HOME={PANEL_HOME}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LimitNOFILE=65536
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
"""
    panel_service = f"""[Unit]
Description=Palworld Web Management Panel
After=network.target

[Service]
Type=simple
User={PANEL_USER}
WorkingDirectory={PANEL_DIR}
Environment=HOME={PANEL_HOME}
EnvironmentFile={ENV_FILE}
ExecStart=/usr/bin/gunicorn --config {PANEL_DIR}/gunicorn.conf.py app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    install_service = f"""[Unit]
Description=Palworld Panel Installer
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={PANEL_DIR}
EnvironmentFile={ENV_FILE}
ExecStart=/usr/bin/python3 {PANEL_DIR}/panel_install.py --service
TimeoutStartSec=7200
"""
    # The updater never had a retry budget of its own before, so 90 minutes was
    # also the hard ceiling for a 3-attempt SteamCMD run plus the player
    # countdown. `EnvironmentFile=-` keeps the unit startable when the env file
    # is missing or unreadable instead of failing with "Failed to load
    # environment files".
    update_service = f"""[Unit]
Description=Palworld Panel Background Updater (manual)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={PANEL_USER}
Group={PANEL_USER}
WorkingDirectory={PANEL_DIR}
EnvironmentFile=-{ENV_FILE}
ExecStart=/usr/bin/python3 {PANEL_DIR}/panel_update.py --apply
TimeoutStartSec=7200
TimeoutStopSec=120
KillMode=mixed
Nice=5
"""
    auto_update_service = f"""[Unit]
Description=Palworld Panel Background Updater (scheduled)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={PANEL_USER}
Group={PANEL_USER}
WorkingDirectory={PANEL_DIR}
EnvironmentFile=-{ENV_FILE}
ExecStart=/usr/bin/python3 {PANEL_DIR}/panel_update.py --auto
TimeoutStartSec=7200
TimeoutStopSec=120
KillMode=mixed
Nice=5
"""
    update_timer = """[Unit]
Description=Check Palworld server updates every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
AccuracySec=1min
Persistent=false
Unit=palworld-panel-auto-update.service

[Install]
WantedBy=timers.target
"""

    return {
        "palworld.service": palworld_service,
        "palworld-panel.service": panel_service,
        "palworld-panel-install.service": install_service,
        "palworld-panel-update.service": update_service,
        "palworld-panel-auto-update.service": auto_update_service,
        "palworld-panel-update.timer": update_timer,
    }


def render_sudoers() -> str:
    return f"""{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start palworld.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl stop palworld.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart palworld.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl is-active palworld.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl show palworld.service *
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/journalctl -u palworld.service *
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/chown -R {PANEL_USER}\\:{PANEL_USER} {PALWORLD_DIR}/Pal/Saved/SaveGames
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/chown -R {PANEL_USER}\\:{PANEL_USER} {PALWORLD_DIR}/Pal/Saved/Config/LinuxServer
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start palworld-panel-update.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl is-active palworld-panel-update.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start palworld-panel-auto-update.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl is-active palworld-panel-auto-update.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl is-active palworld-panel-update.timer
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start palworld-panel-install.service
{PANEL_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl is-active palworld-panel-install.service
"""


def write_service_files() -> None:
    status.step("systemd", "active", "Installing systemd units and sudoers")
    for name, content in render_service_files().items():
        Path(f"/etc/systemd/system/{name}").write_text(content, encoding="utf-8")
    sudoers_path = Path("/etc/sudoers.d/palworld-panel")
    sudoers_path.write_text(render_sudoers(), encoding="utf-8")
    run_checked(["chmod", "440", str(sudoers_path)], timeout=30)
    run_checked(["visudo", "-cf", str(sudoers_path)], timeout=30)
    run_checked(["systemctl", "daemon-reload"], timeout=60)
    run_checked(["systemctl", "enable", PANEL_SERVICE], timeout=60)
    run_checked(["systemctl", "enable", PALWORLD_SERVICE], timeout=60)
    status.step("systemd", "done", "Systemd units installed")


def install_panel_files() -> None:
    status.step("panel", "active", "Preparing panel directory")
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    run_checked(["chown", "-R", f"{PANEL_USER}:{PANEL_USER}", str(PANEL_DIR)], timeout=120)
    status.step("panel", "done", str(PANEL_DIR))


def repair() -> None:
    ensure_root()
    status.set(running=True, phase="repair", started_at=iso_now(), finished_at="", success=None, steps=[])
    try:
        ensure_user()
        install_panel_files()
        configure_palworld()
        write_service_files()
        check_environment()
        status.set(running=False, phase="complete", finished_at=iso_now(), success=True, message="Repair complete")
        append_audit("install.repair", True, message="repair complete")
    except Exception as exc:
        status.step("failed", "error", str(exc))
        status.set(running=False, phase="failed", finished_at=iso_now(), success=False, message=str(exc))
        append_audit("install.repair", False, message=str(exc))
        raise


def install_palworld() -> None:
    ensure_root()
    status.set(running=True, phase="installing", started_at=iso_now(), finished_at="", success=None, steps=[])
    try:
        with operation_lock():
            ensure_user()
            install_dependencies()
            install_steamcmd()
            install_panel_files()
            install_palworld_server()
            configure_palworld()
            write_service_files()
            check_environment()
        status.set(running=False, phase="complete", finished_at=iso_now(), success=True, message="Palworld server installed")
        append_audit("install.palworld", True, message="install complete")
    except Exception as exc:
        status.step("failed", "error", str(exc))
        status.set(running=False, phase="failed", finished_at=iso_now(), success=False, message=str(exc))
        append_audit("install.palworld", False, message=str(exc))
        raise


def service_action() -> str:
    request = read_json(REQUEST_PATH, {})
    action = str(request.get("action", "")).strip()
    if action not in ALLOWED_ACTIONS:
        raise RuntimeError("missing or unsupported installer request")
    return action


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--install-palworld", action="store_true")
    parser.add_argument("--install-panel", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--service", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.check:
            status.load()
            status.set(running=False, phase="checking", started_at=iso_now(), success=None, steps=[])
            checks = check_environment()
            if args.json:
                print_json({"success": True, "checks": checks, "status": status.payload})
        elif args.install_palworld:
            install_palworld()
        elif args.install_panel:
            repair()
        elif args.repair:
            repair()
        elif args.service:
            action = service_action()
            if action == "install-palworld":
                install_palworld()
            elif action == "repair":
                repair()
        else:
            parser.error("choose --check, --install-palworld, --repair, or --service")
        return 0
    except Exception as exc:
        log(f"Installer failed: {exc}")
        if args.json:
            print_json({"success": False, "message": str(exc), "status": status.payload})
        return 1


if __name__ == "__main__":
    sys.exit(main())
