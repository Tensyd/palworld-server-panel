from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import panel_update


class PanelUpdateTests(unittest.TestCase):
    def setUp(self):
        panel_update.status = panel_update.UpdateStatus()
        self.write_json = patch.object(panel_update, "write_json").start()
        self.addCleanup(patch.stopall)

    def test_check_only_uses_operation_lock(self):
        with patch.object(panel_update, "operation_lock", return_value=nullcontext()) as operation_lock, patch.object(
            panel_update, "check_update", return_value={"update_available": False}
        ), patch.object(panel_update.status, "set"), patch.object(panel_update, "append_audit"), patch.object(panel_update, "log"):
            panel_update.check_only()
        operation_lock.assert_called_once_with()

    def test_operation_lock_does_not_truncate_metadata_when_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / ".operation.lock"
            lock_path.write_text("existing owner\n", encoding="utf-8")
            fake_fcntl = SimpleNamespace(
                LOCK_EX=1,
                LOCK_NB=2,
                LOCK_UN=4,
                flock=lambda *_args: (_ for _ in ()).throw(BlockingIOError()),
            )
            with patch.object(panel_update, "SAVE_SLOT_ROOT", root), patch.object(
                panel_update, "SAVE_LOCK_PATH", lock_path
            ), patch.dict(sys.modules, {"fcntl": fake_fcntl}):
                with self.assertRaisesRegex(RuntimeError, "another save/update operation"):
                    with panel_update.operation_lock():
                        pass
            self.assertEqual(lock_path.read_text(encoding="utf-8"), "existing owner\n")

    def test_stopped_server_is_backed_up_without_starting(self):
        with patch.object(panel_update, "operation_lock", return_value=nullcontext()), patch.object(
            panel_update, "check_update", side_effect=[{"update_available": True}, {"update_available": False}]
        ), patch.object(panel_update, "is_service_running", return_value=False), patch.object(
            panel_update, "backup_current_save", return_value="backup"
        ) as backup, patch.object(panel_update, "run_steam_update"), patch.object(panel_update, "fix_ownership"), patch.object(
            panel_update, "systemctl"
        ) as systemctl, patch.object(panel_update, "append_audit"), patch.object(panel_update, "log"):
            panel_update.apply_update()
        backup.assert_called_once_with()
        systemctl.assert_not_called()

    def test_running_server_stops_before_backup_and_restarts_after_failure(self):
        events = []

        def systemctl(action, *_args, **_kwargs):
            events.append(action)
            return "", "", 0

        def backup():
            events.append("backup")
            raise RuntimeError("backup failed")

        with patch.object(panel_update, "operation_lock", return_value=nullcontext()), patch.object(
            panel_update, "check_update", return_value={"update_available": True}
        ), patch.object(panel_update, "is_service_running", return_value=True), patch.object(
            panel_update, "countdown_if_needed"
        ), patch.object(panel_update, "rcon_command", return_value="Complete Save"), patch.object(
            panel_update.time, "sleep"
        ), patch.object(panel_update, "wait_for_service", return_value=True), patch.object(
            panel_update, "backup_current_save", side_effect=backup
        ), patch.object(panel_update, "systemctl", side_effect=systemctl), patch.object(panel_update, "append_audit"), patch.object(
            panel_update, "log"
        ):
            with self.assertRaisesRegex(RuntimeError, "backup failed"):
                panel_update.apply_update()
        self.assertEqual(events, ["stop", "backup", "start"])

    def test_rcon_save_failure_does_not_block_the_update(self):
        """RCON is optional in Palworld; a dead RCON must not abort the update."""
        with patch.object(panel_update, "operation_lock", return_value=nullcontext()), patch.object(
            panel_update, "check_update", side_effect=[{"update_available": True}, {"update_available": False}]
        ), patch.object(panel_update, "is_service_running", return_value=True), patch.object(
            panel_update, "countdown_if_needed"
        ), patch.object(panel_update, "rcon_command", return_value="[RCON Error] RCON_PASSWORD is not configured"), patch.object(
            panel_update, "wait_for_service", return_value=True
        ), patch.object(panel_update, "systemctl", return_value=("", "", 0)), patch.object(
            panel_update, "backup_current_save", return_value="backup"
        ) as backup, patch.object(panel_update, "run_steam_update") as steam_update, patch.object(
            panel_update, "fix_ownership"
        ), patch.object(panel_update, "append_audit"), patch.object(panel_update, "log"):
            panel_update.apply_update()
        backup.assert_called_once_with()
        steam_update.assert_called_once()
        self.assertEqual(panel_update.status.payload["phase"], "complete")
        self.assertTrue(panel_update.status.payload["success"])

    def test_rcon_save_failure_aborts_when_explicitly_required(self):
        with patch.object(panel_update, "RCON_SAVE_REQUIRED", True), patch.object(
            panel_update, "operation_lock", return_value=nullcontext()
        ), patch.object(panel_update, "check_update", return_value={"update_available": True}), patch.object(
            panel_update, "is_service_running", return_value=True
        ), patch.object(panel_update, "countdown_if_needed"), patch.object(
            panel_update, "rcon_command", return_value="[RCON Error] timeout"
        ), patch.object(panel_update, "systemctl") as systemctl, patch.object(
            panel_update, "backup_current_save"
        ) as backup, patch.object(panel_update, "append_audit"), patch.object(panel_update, "log"):
            with self.assertRaisesRegex(RuntimeError, "RCON save failed"):
                panel_update.apply_update()
        systemctl.assert_not_called()
        backup.assert_not_called()

    def test_unknown_service_state_aborts_instead_of_overwriting_running_files(self):
        with patch.object(panel_update, "service_state", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "无法确认"):
                panel_update.is_service_running(strict=True)
            self.assertFalse(panel_update.is_service_running())

    def test_service_state_query_does_not_require_sudo(self):
        with patch.object(panel_update, "run", return_value=("active", "", 0)) as run, patch.object(
            panel_update, "run_privileged"
        ) as run_privileged:
            self.assertEqual(panel_update.service_state(), "active")
        run_privileged.assert_not_called()
        self.assertEqual(run.call_args.args[0], [panel_update.SYSTEMCTL, "is-active", panel_update.PALWORLD_SERVICE])

    def test_post_update_verification_failure_keeps_the_update_successful(self):
        with patch.object(panel_update, "operation_lock", return_value=nullcontext()), patch.object(
            panel_update,
            "check_update",
            side_effect=[{"update_available": True, "latest_manifest": "target"}, RuntimeError("Steam API unreachable")],
        ), patch.object(panel_update, "is_service_running", return_value=False), patch.object(
            panel_update, "backup_current_save", return_value="backup"
        ), patch.object(panel_update, "run_steam_update"), patch.object(panel_update, "fix_ownership"), patch.object(
            panel_update, "append_audit"
        ), patch.object(panel_update, "log"):
            panel_update.apply_update()
        self.assertEqual(panel_update.status.payload["phase"], "complete")
        self.assertTrue(panel_update.status.payload["success"])

    def test_steam_update_command_forces_tcp(self):
        command = panel_update.steam_update_command()
        self.assertEqual(command[0], panel_update.STEAMCMD)
        self.assertEqual(command[1], "-tcp")
        self.assertIn("validate", command)

    def test_needs_manifest_reset_detects_stale_state_flags_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "appmanifest_2394010.acf"
            manifest.write_text('"AppState"\n{\n\t"StateFlags"\t\t"4"\n}\n', encoding="utf-8")
            with patch.object(panel_update, "APP_MANIFEST", manifest):
                self.assertFalse(panel_update.needs_manifest_reset("everything is fine"))
                self.assertTrue(panel_update.needs_manifest_reset("ERROR! Failed to install app '2394010' (Access Denied)"))
                manifest.write_text('"AppState"\n{\n\t"StateFlags"\t\t"6"\n}\n', encoding="utf-8")
                self.assertTrue(panel_update.needs_manifest_reset(""))

    def test_run_steam_update_retries_after_resetting_stale_manifest(self):
        attempts = []

        def fake_attempt(_timeout):
            attempts.append(1)
            if len(attempts) == 1:
                return "ERROR! Failed to install app '2394010' (Access Denied)", 0, False
            return "Success! App '2394010' fully installed.", 0, False

        with patch.object(panel_update, "_run_steamcmd_once", side_effect=fake_attempt), patch.object(
            panel_update, "parse_local_manifest", return_value={"manifest": "target"}
        ), patch.object(panel_update, "reset_stale_manifest") as reset, patch.object(panel_update.time, "sleep"):
            panel_update.run_steam_update("target")
        self.assertEqual(len(attempts), 2)
        reset.assert_called_once()

    def test_run_steam_update_reports_the_last_steamcmd_output(self):
        with patch.object(
            panel_update, "_run_steamcmd_once", return_value=("ERROR! Failed to install app '2394010' (No subscription)", 8, False)
        ), patch.object(panel_update, "parse_local_manifest", return_value={"manifest": "old"}), patch.object(
            panel_update, "reset_stale_manifest"
        ), patch.object(panel_update.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "No subscription"):
                panel_update.run_steam_update("target")

    def test_fix_ownership_reports_chown_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(panel_update, "PALWORLD_DIR", path), patch.object(panel_update, "CONFIG_DIR", path), patch.object(
                panel_update, "run_privileged", return_value=("", "denied", 1)
            ):
                with self.assertRaisesRegex(RuntimeError, "denied"):
                    panel_update.fix_ownership()


if __name__ == "__main__":
    unittest.main()
