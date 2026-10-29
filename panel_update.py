#!/usr/bin/env python3
"""Background updater for the Palworld panel.

This script is intentionally standalone so systemd timers can run update checks
without involving Flask or gunicorn workers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rcon import rcon_command as send_rcon_command


def env_int(name: str, default: int, minimum: int = 0) -> int:
    """Read an integer environment variable without letting a typo kill the updater."""
    try:
        return max(minimum, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


PALWORLD_DIR = Path(os.environ.get("PALWORLD_DIR", "/home/demo/palworld"))
PALWORLD_SERVICE = os.environ.get("PALWORLD_SERVICE", "palworld.service")
PALWORLD_APP_ID = os.environ.get("PALWORLD_APP_ID", "2394010")
PALWORLD_DEPOT_ID = os.environ.get("PALWORLD_DEPOT_ID", "2394012")
STEAMCMD = os.environ.get("STEAMCMD", "/home/demo/steamcmd/steamcmd.sh")
SYSTEMCTL = os.environ.get("SYSTEMCTL", "/usr/bin/systemctl")
CHOWN = os.environ.get("CHOWN", "/usr/bin/chown")
PANEL_USER = os.environ.get("PANEL_USER", "demo")
AUTO_UPDATE_ENABLED = env_flag("AUTO_UPDATE_ENABLED", False)
AUTO_UPDATE_WARN_MINUTES = env_int("AUTO_UPDATE_WARN_MINUTES", 10)

# SteamCMD reliability knobs. The systemd updater used to call SteamCMD exactly
# once with no timeout: one flaky Steam CM connection meant "update failed"
# forever. These mirror the hardening that already lived in the Docker
# entrypoint (docker/palworld-entrypoint.sh).
STEAMCMD_TCP = env_flag("STEAMCMD_TCP", True)
STEAMCMD_RETRIES = env_int("STEAMCMD_RETRIES", 3, minimum=1)
STEAMCMD_RETRY_DELAY = env_int("STEAMCMD_RETRY_DELAY", 30)
STEAMCMD_ATTEMPT_TIMEOUT = env_int("STEAMCMD_ATTEMPT_TIMEOUT", 1800, minimum=60)

MANIFEST_URL_TEMPLATE = os.environ.get("STEAM_MANIFEST_URL", "https://api.steamcmd.net/v1/info/{app}")
MANIFEST_RETRIES = env_int("MANIFEST_RETRIES", 3, minimum=1)
MANIFEST_RETRY_DELAY = env_int("MANIFEST_RETRY_DELAY", 5, minimum=1)

# Palworld ships with RCON disabled by default, so a missing/broken RCON must
# never block an update: the on-disk save after the server stops is the
# authoritative copy that gets backed up anyway.
RCON_SAVE_REQUIRED = env_flag("RCON_SAVE_REQUIRED", False)

RCON_HOST = os.environ.get("RCON_HOST", "127.0.0.1")
RCON_PORT = env_int("RCON_PORT", 25575)
RCON_PASSWORD = os.environ.get("RCON_PASSWORD", "")
RCON_TIMEOUT_SECONDS = env_float("RCON_TIMEOUT_SECONDS", 10.0)

PANEL_DIR = Path(os.environ.get("PANEL_DIR", "/home/demo/palworld-panel"))
STATUS_PATH = Path(os.environ.get("PANEL_UPDATE_STATUS", str(PANEL_DIR / "update-status.json")))
LOG_PATH = Path(os.environ.get("PANEL_UPDATE_LOG", str(PANEL_DIR / "update.log")))
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG", str(PANEL_DIR / "audit.log")))
SAVE_SLOT_ROOT = Path(os.environ.get("SAVE_SLOT_ROOT", str(PANEL_DIR / "save-slots")))
SAVE_BACKUP_DIR = SAVE_SLOT_ROOT / "backups"
SAVE_LOCK_PATH = SAVE_SLOT_ROOT / ".operation.lock"
ACTIVE_SAVEGAMES_DIR = PALWORLD_DIR / "Pal" / "Saved" / "SaveGames" / "0"
CONFIG_DIR = PALWORLD_DIR / "Pal" / "Saved" / "Config" / "LinuxServer"
GAME_USER_SETTINGS = CONFIG_DIR / "GameUserSettings.ini"
APP_MANIFEST = PALWORLD_DIR / "steamapps" / f"appmanifest_{PALWORLD_APP_ID}.acf"


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
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as lock_handle:
        import fcntl

        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                tmp_name = handle.name
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def append_audit(action: str, success: bool, **details: Any) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "time": iso_now(),
        "source_ip": "systemd",
        "action": action,
        "success": success,
        **details,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class UpdateStatus:
    def __init__(self) -> None:
        self.payload: dict[str, Any] = {
            "running": False,
            "phase": "idle",
            "message": "",
            "auto_update_enabled": AUTO_UPDATE_ENABLED,
            "warn_minutes": AUTO_UPDATE_WARN_MINUTES,
            "checked_at": "",
            "started_at": "",
            "finished_at": "",
            "local_buildid": "",
            "local_manifest": "",
            "latest_manifest": "",
            "update_available": False,
            "success": None,
            "steps": [],
        }

    def load_existing(self) -> None:
        if not STATUS_PATH.exists():
            return
        try:
            existing = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(existing, dict):
            self.payload.update(existing)

    def set(self, **items: Any) -> None:
        self.payload.update(items)
        write_json(STATUS_PATH, self.payload)

    def step(self, name: str, status: str, message: str = "") -> None:
        steps = [item for item in self.payload.get("steps", []) if item.get("name") != name]
        steps.append({"name": name, "status": status, "message": message, "time": iso_now()})
        self.set(steps=steps)


status = UpdateStatus()


def run(args: list[str], timeout: int = 60) -> tuple[str, str, int]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", f"{args[0]} timed out after {timeout}s", -1
    except FileNotFoundError:
        return "", f"command not found: {args[0]}", 127
    except OSError as exc:
        return "", f"failed to run {args[0]}: {exc}", 126


def run_privileged(args: list[str], timeout: int = 60) -> tuple[str, str, int]:
    if os.geteuid() == 0:
        return run(args, timeout=timeout)
    return run(["sudo", "-n", *args], timeout=timeout)


def systemctl(*args: str, timeout: int = 60) -> tuple[str, str, int]:
    return run_privileged([SYSTEMCTL, *args], timeout=timeout)


def service_state() -> str:
    """Return the systemd state string for the game unit, or "" when unknown.

    ``systemctl is-active`` never needs root, so try it unprivileged first. The
    old implementation always went through ``sudo -n`` and silently treated any
    failure as "server is stopped" -- which let the updater overwrite the game
    files while Palworld was still running.
    """
    out, _, _ = run([SYSTEMCTL, "is-active", PALWORLD_SERVICE], timeout=15)
    state = out.strip().splitlines()[0].strip() if out.strip() else ""
    if state:
        return state
    if os.geteuid() != 0:
        out, _, _ = run(["sudo", "-n", SYSTEMCTL, "is-active", PALWORLD_SERVICE], timeout=15)
        state = out.strip().splitlines()[0].strip() if out.strip() else ""
    return state


def is_service_running(strict: bool = False) -> bool:
    state = service_state()
    if not state:
        if strict:
            raise RuntimeError(
                f"无法确认 {PALWORLD_SERVICE} 的运行状态（systemctl is-active 没有任何输出）。"
                f"请检查 SYSTEMCTL={SYSTEMCTL} 是否正确，避免在服务器仍然运行时覆盖游戏文件。"
            )
        return False
    return state == "active"


def wait_for_service(active: bool, timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_service_running() is active:
            return True
        time.sleep(2)
    return False


def parse_local_manifest() -> dict[str, str]:
    text = APP_MANIFEST.read_text(encoding="utf-8", errors="replace") if APP_MANIFEST.exists() else ""
    buildid = ""
    build_match = re.search(r'"buildid"\s+"([^"]+)"', text)
    if build_match:
        buildid = build_match.group(1)

    depot_manifest = ""
    depot_match = re.search(
        rf'"{re.escape(PALWORLD_DEPOT_ID)}"\s*\{{(?P<body>.*?)\n\s*\}}',
        text,
        flags=re.S,
    )
    if depot_match:
        manifest_match = re.search(r'"manifest"\s+"([^"]+)"', depot_match.group("body"))
        if manifest_match:
            depot_manifest = manifest_match.group(1)

    return {"buildid": buildid, "manifest": depot_manifest}


def fetch_latest_manifest() -> str:
    """Read the public depot manifest from the Steam metadata API.

    The updater used to issue a single bare ``urlopen`` with no retry and no
    proxy handling, so on a box behind a proxy (or with a flaky route to the
    API) *every* scheduled run died on its first step while the panel's own
    "check for updates" button kept working. Same request, different luck.
    """
    url = MANIFEST_URL_TEMPLATE.format(app=PALWORLD_APP_ID)
    proxies = urllib.request.getproxies()
    openers = []
    if any(name in proxies for name in ("http", "https", "all")):
        openers.append(urllib.request.build_opener())
    openers.append(urllib.request.build_opener(urllib.request.ProxyHandler({})))

    last_error: Exception | None = None
    for attempt in range(1, MANIFEST_RETRIES + 1):
        for opener in openers:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "palworld-panel-updater/1.0"})
                with opener.open(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                app_data = data["data"][PALWORLD_APP_ID]
                manifest = str(app_data["depots"][PALWORLD_DEPOT_ID]["manifests"]["public"]["gid"])
                if manifest:
                    return manifest
                last_error = RuntimeError("Steam API returned an empty manifest")
            except Exception as exc:  # noqa: BLE001 - report every transport failure the same way
                last_error = exc
        if attempt < MANIFEST_RETRIES:
            delay = MANIFEST_RETRY_DELAY * attempt
            log(f"Steam manifest fetch failed (attempt {attempt}/{MANIFEST_RETRIES}): {last_error}; retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(
        f"无法获取 Steam 最新 manifest（已尝试 {MANIFEST_RETRIES} 次）：{last_error}。"
        f"请检查服务器到 {url} 的网络连通性，或通过 STEAM_MANIFEST_URL 指定可用镜像。"
    )


def check_update() -> dict[str, Any]:
    status.step("detect", "active", "Checking local and latest manifests")
    local = parse_local_manifest()
    latest_manifest = fetch_latest_manifest()
    local_manifest = local.get("manifest", "")
    update_available = bool(latest_manifest and local_manifest and latest_manifest != local_manifest)
    if not local_manifest:
        message = "无法读取本地 appmanifest，服务端可能尚未安装"
    else:
        message = "Update available" if update_available else "Already up to date"
    status.set(
        phase="checked",
        checked_at=iso_now(),
        auto_update_enabled=AUTO_UPDATE_ENABLED,
        local_buildid=local.get("buildid", ""),
        local_manifest=local_manifest,
        latest_manifest=latest_manifest,
        update_available=update_available,
        message=message,
        success=True,
    )
    status.step("detect", "done", message)
    return {
        "local_buildid": local.get("buildid", ""),
        "local_manifest": local_manifest,
        "latest_manifest": latest_manifest,
        "update_available": update_available,
    }


@contextmanager
def operation_lock():
    SAVE_SLOT_ROOT.mkdir(parents=True, exist_ok=True)
    handle = SAVE_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another save/update operation is already running") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"update {os.getpid()} {iso_now()}\n")
        handle.flush()
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


def rcon_command(command: str, timeout: int = 5) -> str:
    return send_rcon_command(RCON_HOST, RCON_PORT, RCON_PASSWORD, command, timeout=timeout)


def player_count() -> int:
    if not is_service_running():
        return 0
    output = rcon_command("ShowPlayers")
    if output.startswith("[RCON Error]"):
        log(f"Unable to read player count: {output}")
        return 0
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return 0
    if lines[0].lower().startswith("name"):
        lines = lines[1:]
    return len(lines)


def broadcast(message: str) -> None:
    # Keep spaces: stripping them turned every countdown into
    # "Palworld_server_update_in_10_minutes".
    safe = re.sub(r"[\x00-\x1f\x7f]+", " ", message)
    safe = re.sub(r"\s+", " ", safe).strip()
    if not safe:
        return
    output = rcon_command(f"Broadcast {safe}")
    log(f"Broadcast: {safe} -> {output or 'OK'}")


def save_world() -> None:
    """Ask the running server to flush its world to disk before we stop it.

    RCON is optional in Palworld and often unconfigured. Treating a failed
    ``Save`` as fatal meant auto-update could never finish on any server where
    RCON was off or the password did not match -- which is most of them.
    """
    status.step("save", "active", "Saving current world")
    output = rcon_command("Save", timeout=10)
    if output.startswith("[RCON Error]"):
        detail = output[len("[RCON Error]"):].strip() or "unknown RCON error"
        if RCON_SAVE_REQUIRED:
            raise RuntimeError(f"RCON save failed: {detail}")
        status.step("save", "done", f"跳过 RCON 保存（{detail}）；停服后直接备份磁盘存档")
        log(f"RCON save skipped: {detail}")
        return
    log(f"RCON Save: {output or 'OK'}")
    time.sleep(5)
    status.step("save", "done", "Save command sent")


def countdown_if_needed(minutes: int) -> None:
    if minutes <= 0 or player_count() == 0:
        status.step("notify", "done", "No online players, skipping countdown")
        return

    status.step("notify", "active", f"Broadcasting {minutes} minute update countdown")
    checkpoints = []
    if minutes >= 10:
        checkpoints.append((minutes * 60, f"Palworld server update in {minutes} minutes"))
        checkpoints.append((5 * 60, "Palworld server update in 5 minutes"))
    elif minutes >= 5:
        checkpoints.append((minutes * 60, f"Palworld server update in {minutes} minutes"))
    checkpoints.extend([(60, "Palworld server update in 1 minute"), (30, "Palworld server update in 30 seconds"), (10, "Palworld server update in 10 seconds")])

    previous = minutes * 60
    for seconds_left, message in checkpoints:
        if seconds_left > previous:
            continue
        sleep_for = previous - seconds_left
        if sleep_for > 0:
            time.sleep(sleep_for)
        broadcast(message)
        previous = seconds_left
    if previous > 0:
        time.sleep(previous)
    status.step("notify", "done", "Countdown finished")


def current_world_id() -> str:
    if GAME_USER_SETTINGS.exists():
        text = GAME_USER_SETTINGS.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^DedicatedServerName=(.+)$", text, flags=re.M)
        if match:
            return match.group(1).strip()
    if ACTIVE_SAVEGAMES_DIR.exists():
        for item in sorted(ACTIVE_SAVEGAMES_DIR.iterdir()):
            if item.is_dir() and (item / "Level.sav").exists():
                return item.name
    return "unknown"


def backup_current_save() -> str:
    if not ACTIVE_SAVEGAMES_DIR.exists() or not any(ACTIVE_SAVEGAMES_DIR.iterdir()):
        return "skipped-empty-save"
    SAVE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    world_id = current_world_id()
    if not re.fullmatch(r"[A-Fa-f0-9]{32}", world_id):
        raise RuntimeError("invalid configured world id")
    backup_id = f"{time.strftime('%Y%m%d-%H%M%S')}-before-update-{world_id}"
    target = SAVE_BACKUP_DIR / backup_id
    suffix = 1
    while target.exists():
        # Two attempts inside the same second (a retry right after a failure)
        # must not collide on the backup directory name.
        suffix += 1
        target = SAVE_BACKUP_DIR / f"{backup_id}-{suffix}"
    backup_id = target.name
    shutil.copytree(ACTIVE_SAVEGAMES_DIR, target / "SaveGames" / "0", symlinks=False)
    if CONFIG_DIR.exists():
        shutil.copytree(CONFIG_DIR, target / "Config" / "LinuxServer", symlinks=False)
    write_json(
        target / "metadata.json",
        {
            "id": backup_id,
            "world_id": world_id,
            "created_at": iso_now(),
            "reason": "before-update",
        },
    )
    return backup_id


def fix_ownership() -> None:
    paths = [
        PALWORLD_DIR / "Pal" / "Saved" / "SaveGames",
        CONFIG_DIR,
    ]
    owner = f"{PANEL_USER}:{PANEL_USER}"
    for path in paths:
        if path.exists():
            _, error, code = run_privileged([CHOWN, "-R", owner, str(path)], timeout=180)
            if code != 0:
                raise RuntimeError(error or f"failed to set ownership on {path}")


STEAMCMD_FATAL_MARKERS = (
    "access denied",
    "missing content manifest",
    "failed to install app",
    "no subscription",
    "content servers unreachable",
)


def steam_update_command() -> list[str]:
    command = [STEAMCMD]
    if STEAMCMD_TCP:
        # Force TCP for the Steam CM connection. The UDP default is what makes
        # SteamCMD sit silently for ages and then give up.
        command.append("-tcp")
    command.extend(
        [
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
        ]
    )
    return command


def manifest_state_flags() -> str:
    if not APP_MANIFEST.exists():
        return ""
    text = APP_MANIFEST.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"StateFlags"\s+"([^"]+)"', text)
    return match.group(1).strip() if match else ""


def needs_manifest_reset(output: str) -> bool:
    """Detect the classic "Palworld will never update again" state.

    When Steam decides the cached depot manifest no longer matches what the CDN
    serves it answers ``Access Denied`` (or parks ``StateFlags`` at 6) and every
    following attempt fails identically until the .acf is moved aside.
    """
    if manifest_state_flags() in {"2", "6"}:
        return True
    lowered = output.lower()
    return "access denied" in lowered or "missing content manifest" in lowered


def reset_stale_manifest() -> str:
    if not APP_MANIFEST.exists():
        return ""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = APP_MANIFEST.with_name(f"{APP_MANIFEST.name}.stale-{stamp}")
    try:
        APP_MANIFEST.rename(backup_path)
    except OSError as exc:
        log(f"Unable to move the stale appmanifest aside: {exc}")
        return ""
    for folder in ("downloading", "temp"):
        stale_dir = PALWORLD_DIR / "steamapps" / folder / PALWORLD_APP_ID
        if stale_dir.exists():
            shutil.rmtree(stale_dir, ignore_errors=True)
    log(f"Stale appmanifest moved to {backup_path.name}; the app will be re-verified from scratch")
    return str(backup_path)


def _terminate_process(process: subprocess.Popen) -> None:
    """Take down SteamCMD, including the shell wrapper and its children.

    The old code simply abandoned the child on timeout, so a hung SteamCMD kept
    holding the game files and every later attempt failed too. ``killpg`` needs
    a process group (POSIX only), hence the guarded fallbacks.
    """
    signals = [signal.SIGTERM]
    kill_signal = getattr(signal, "SIGKILL", None)
    if kill_signal is not None:
        signals.append(kill_signal)

    for sig in signals:
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (OSError, AttributeError):
            try:
                if sig == kill_signal:
                    process.kill()
                else:
                    process.terminate()
            except Exception:  # pragma: no cover - best effort only
                pass
        try:
            process.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            continue


def _run_steamcmd_once(timeout: int) -> tuple[str, int, bool]:
    command = steam_update_command()
    log("steamcmd: " + " ".join(command))
    lines: list[str] = []
    timed_out = False
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        log(f"steamcmd: attempt exceeded {timeout}s, terminating")
        _terminate_process(process)

    watchdog = threading.Timer(timeout, on_timeout)
    watchdog.daemon = True
    watchdog.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if not line:
                continue
            log("steamcmd: " + line)
            lines.append(line)
            if len(lines) > 400:
                del lines[0]
        code = process.wait()
    finally:
        watchdog.cancel()
    return "\n".join(lines), code, timed_out


def steamcmd_reported_failure(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in STEAMCMD_FATAL_MARKERS)


def run_steam_update(expected_manifest: str = "") -> None:
    """Run SteamCMD with retries, a hard per-attempt timeout and stale-manifest recovery.

    The previous version invoked SteamCMD exactly once with no timeout and left
    the child process running when it gave up, so a single hiccup produced a
    permanent "update failed" state plus a zombie SteamCMD holding the game
    files hostage.
    """
    attempts = STEAMCMD_RETRIES
    last_output = ""
    last_code = 0
    last_timeout = False

    for attempt in range(1, attempts + 1):
        status.step("update", "active", f"SteamCMD 更新中（第 {attempt}/{attempts} 次尝试）")
        last_output, last_code, last_timeout = _run_steamcmd_once(STEAMCMD_ATTEMPT_TIMEOUT)
        local_manifest = parse_local_manifest().get("manifest", "")
        installed = not expected_manifest or local_manifest == expected_manifest
        reported_failure = last_code != 0 or last_timeout or steamcmd_reported_failure(last_output)

        if not reported_failure and installed:
            return
        if not reported_failure:
            log(
                f"SteamCMD exited 0 but the local manifest is still {local_manifest or '<empty>'} "
                f"(expected {expected_manifest}); treating the attempt as failed"
            )
        if attempt == attempts:
            break

        if needs_manifest_reset(last_output):
            reset_stale_manifest()

        status.step("update", "active", f"SteamCMD 第 {attempt} 次失败，{STEAMCMD_RETRY_DELAY}s 后重试")
        log(f"SteamCMD attempt {attempt}/{attempts} failed (exit={last_code}, timeout={last_timeout}); retrying")
        time.sleep(STEAMCMD_RETRY_DELAY)

    tail = "\n".join(last_output.splitlines()[-8:]) or "无输出"
    reason = "超时" if last_timeout else f"退出码 {last_code}"
    raise RuntimeError(
        f"SteamCMD 更新失败（{attempts} 次尝试，最后一次{reason}）。"
        f"本地 manifest={parse_local_manifest().get('manifest', '') or '<空>'}，"
        f"目标={expected_manifest or '<未知>'}。最后输出：{tail}"
    )


def apply_update(auto: bool = False) -> None:
    status.load_existing()
    was_running = False
    stopped_for_update = False
    backup_id = ""
    with operation_lock():
        try:
            status.set(running=True, phase="running", started_at=iso_now(), finished_at="", success=None, steps=[], message="Checking for updates")
            details = check_update()
            expected_manifest = str(details.get("latest_manifest") or "")
            if auto and not AUTO_UPDATE_ENABLED:
                # Still report the detection result: the whole point of the
                # 30-minute timer is that the panel knows an update exists even
                # when applying it automatically is switched off.
                message = "检测到新版本，但自动更新已关闭" if details["update_available"] else "已是最新（自动更新关闭）"
                status.set(
                    running=False,
                    phase="checked",
                    finished_at=iso_now(),
                    success=True,
                    update_available=bool(details["update_available"]),
                    message=message,
                )
                log(f"Auto update disabled; {message}")
                return
            if not details["update_available"]:
                status.set(running=False, phase="idle", finished_at=iso_now(), success=True, message="Already up to date")
                append_audit("update.check", True, message="already up to date", **details)
                log("Already up to date")
                return

            append_audit("update.apply", True, message="update started", **details)

            # Confirm the server state before touching anything. Assuming
            # "stopped" when systemctl cannot be queried means overwriting game
            # files that are still in use; that failure looks like a SteamCMD
            # bug but is really a permissions/state guess.
            was_running = is_service_running(strict=True)

            if was_running:
                countdown_if_needed(AUTO_UPDATE_WARN_MINUTES)
                save_world()
            else:
                status.step("notify", "done", "Server was stopped")
                status.step("save", "done", "Server was stopped")

            if was_running:
                status.step("stop", "active", "Stopping Palworld service")
                _, err, code = systemctl("stop", PALWORLD_SERVICE, timeout=90)
                stopped_for_update = code == 0
                if code != 0 or not wait_for_service(False, 120):
                    raise RuntimeError(err or "failed to stop Palworld service")
                status.step("stop", "done", "Server stopped")
            else:
                status.step("stop", "done", "Server already stopped")

            status.step("backup", "active", "Backing up current save")
            backup_id = backup_current_save()
            status.step("backup", "done", backup_id)

            status.step("update", "active", "Updating with SteamCMD")
            run_steam_update(expected_manifest)
            status.step("update", "done", "SteamCMD update finished")

            status.step("permissions", "active", "Fixing ownership")
            fix_ownership()
            status.step("permissions", "done", "Ownership fixed")

            if was_running:
                status.step("start", "active", "Starting Palworld service")
                _, err, code = systemctl("start", PALWORLD_SERVICE, timeout=90)
                if code != 0 or not wait_for_service(True, 150):
                    raise RuntimeError(err or "failed to start Palworld service")
                stopped_for_update = False
                status.step("start", "done", "Server started")
            else:
                status.step("start", "done", "Server was stopped; leaving it stopped")

            final: dict[str, Any] = {}
            try:
                final = check_update()
            except Exception as exc:
                # The update is already installed. A flaky metadata API at this
                # point used to mark the whole run as failed and restart the
                # server for no reason.
                log(f"Post-update verification failed: {exc}")
                status.step("complete", "done", f"更新完成（收尾校验未能联网确认：{exc}）")
            status.step("complete", "done", "Update complete")
            status.set(running=False, phase="complete", finished_at=iso_now(), success=True, message="Update complete")
            append_audit("update.apply", True, message="update complete", backup_id=backup_id, **final)
            log("Update complete")
        except Exception as exc:
            message = str(exc)
            if was_running and stopped_for_update:
                _, restart_error, restart_code = systemctl("start", PALWORLD_SERVICE, timeout=90)
                restarted = restart_code == 0 and wait_for_service(True, 150)
                status.step("recovery-start", "done" if restarted else "error", "Server restarted after update failure" if restarted else (restart_error or "failed to restart server after update failure"))
            status.step("failed", "error", message)
            status.set(running=False, phase="failed", finished_at=iso_now(), success=False, message=message)
            append_audit("update.failed", False, message=message)
            log(f"Update failed: {message}")
            raise


def check_only() -> None:
    status.load_existing()
    with operation_lock():
        try:
            status.set(running=True, phase="checking", started_at=iso_now(), success=None, message="Checking for updates", steps=[])
            details = check_update()
            status.set(running=False, finished_at=iso_now(), success=True)
            append_audit("update.check", True, **details)
            log(status.payload.get("message", "Check complete"))
        except Exception as exc:
            status.step("detect", "error", str(exc))
            status.set(running=False, phase="failed", finished_at=iso_now(), success=False, message=str(exc))
            append_audit("update.check", False, message=str(exc))
            log(f"Check failed: {exc}")
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check only; do not update")
    parser.add_argument("--apply", action="store_true", help="check and apply update if needed")
    parser.add_argument("--auto", action="store_true", help="timer mode; obey AUTO_UPDATE_ENABLED")
    args = parser.parse_args()

    try:
        if args.check:
            check_only()
        else:
            apply_update(auto=args.auto)
        return 0
    except Exception as exc:
        # Without this the unit failed with a bare exit code and the journal
        # showed nothing but "Failed with result 'exit-code'".
        print(f"panel_update: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
