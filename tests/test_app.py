from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


class FileStorage:
    def __init__(self, stream, filename):
        self.stream = stream
        self.filename = filename

    def save(self, destination):
        Path(destination).write_bytes(self.stream.read())


@unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is not installed")
class ConfigAndStatusTests(unittest.TestCase):
    def test_official_server_limits_are_enforced(self):
        self.assertEqual(app.NUMERIC_RANGES["BaseCampWorkerMaxNum"], (1, 50))
        self.assertEqual(app.NUMERIC_RANGES["BaseCampMaxNumInGuild"], (1, 512))
        self.assertEqual(app.NUMERIC_RANGES["ServerReplicatePawnCullDistance"], (5000, 15000))

    def test_randomizer_choices_match_current_server_options(self):
        self.assertEqual(app.CHOICE_FIELDS["RandomizerType"], {"None", "Region", "All"})

    def test_pvp_additional_drop_accepts_an_item_id(self):
        self.assertIn("AdditionalDropItemWhenPlayerKillingInPvPMode", app.STRING_FIELDS)
        self.assertNotIn("AdditionalDropItemWhenPlayerKillingInPvPMode", app.CHOICE_FIELDS)

    def test_steamcmd_refreshes_app_metadata_before_updating(self):
        entrypoint = Path(__file__).parents[1] / "docker" / "palworld-entrypoint.sh"
        text = entrypoint.read_text(encoding="utf-8")
        self.assertIn("refresh_steamcmd_app_info", text)
        self.assertIn('refresh_steamcmd_app_info "${steamcmd_network_mode}" && run_steamcmd', text)

    @classmethod
    def setUpClass(cls):
        global app
        import app

    def test_deployment_managed_settings_are_not_returned(self):
        with patch.object(app, "parse_default_palworld_settings", return_value={"AdminPassword": '"secret"', "ServerName": '"Test"'}), patch.object(
            app, "parse_palworld_settings", return_value={"RCONPort": "25575", "ServerName": '"Current"'}
        ):
            self.assertEqual(app.get_panel_settings(), {"ServerName": '"Current"'})

    def test_deployment_managed_settings_cannot_be_saved(self):
        errors = app.validate_config_changes({"AdminPassword": "new-secret"})
        self.assertEqual(errors, ["管理员密码 由部署配置管理，不能在面板中修改"])

    def test_config_save_preserves_managed_values_but_filters_response(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "PalWorldSettings.ini"
            config.write_text(
                '[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(AdminPassword="secret",RCONPort=25575,ServerName="Old")\n',
                encoding="utf-8",
            )
            lock = config.with_name(f".{config.name}.lock")
            with patch.object(app, "PALWORLD_CONFIG", config), patch.object(app, "CONFIG_LOCK_PATH", lock), patch.object(
                app, "parse_default_palworld_settings", return_value={}
            ), patch.object(app, "backup_config_file"):
                result = app.update_palworld_settings({"ServerName": "New"})

            saved = app.parse_palworld_settings(config.read_text(encoding="utf-8"))
            self.assertEqual(saved["AdminPassword"], '"secret"')
            self.assertEqual(saved["RCONPort"], "25575")
            self.assertEqual(saved["ServerName"], '"New"')
            self.assertNotIn("AdminPassword", result)
            self.assertNotIn("RCONPort", result)

    def test_integer_config_values_reject_fractions(self):
        self.assertIn("最大玩家数 必须是整数", app.validate_config_changes({"ServerPlayerMaxNum": "12.5"}))
        self.assertEqual(app.validate_config_changes({"ServerPlayerMaxNum": "12.0"}), [])
        self.assertEqual(app.validate_config_changes({"ExpRate": "1.5"}), [])

    def test_save_upload_uses_save_limit_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imports = root / "imports"
            imports.mkdir()
            upload = FileStorage(stream=io.BytesIO(b"12345"), filename="save.zip")
            with patch.object(app, "SAVE_IMPORT_DIR", imports), patch.object(app, "SAVE_UPLOAD_MAX_BYTES", 4), patch.object(
                app, "ensure_save_dirs"
            ):
                with self.assertRaisesRegex(ValueError, "存档文件太大"):
                    app.upload_save_slot(upload, "test")
            self.assertEqual(list(imports.iterdir()), [])

    def test_successful_save_upload_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imports = root / "imports"
            imports.mkdir()
            upload = FileStorage(stream=io.BytesIO(b"zip"), filename="save.zip")
            with patch.object(app, "SAVE_IMPORT_DIR", imports), patch.object(app, "ensure_save_dirs"), patch.object(
                app, "safe_extract_zip"
            ), patch.object(app, "uploaded_save_payload_root", side_effect=lambda path: path), patch.object(
                app, "import_slot", return_value={"id": "test"}
            ):
                result = app.upload_save_slot(upload, "test")
            self.assertEqual(result["id"], "test")
            self.assertEqual(list(imports.iterdir()), [])

    def test_successful_mod_upload_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imports = root / "imports"
            imports.mkdir(parents=True)
            upload = FileStorage(stream=io.BytesIO(b"pak"), filename="test.pak")
            with patch.object(app, "MOD_LIBRARY_ROOT", root), patch.object(app, "ensure_mod_dirs"), patch.object(
                app, "install_pak_files", return_value={"id": "test"}
            ):
                result = app.upload_mod(upload)
            self.assertEqual(result["id"], "test")
            self.assertEqual(list(imports.iterdir()), [])

    def test_restart_for_mods_leaves_stopped_server_stopped(self):
        with patch.object(app, "get_server_status", return_value={"running": False, "container_running": False}), patch.object(
            app, "backup_current_save", return_value={"id": "backup"}
        ), patch.object(app, "service_action") as service_action:
            result = app.restart_for_mods()
        service_action.assert_not_called()
        self.assertFalse(result["running"])

    def test_switch_save_slot_leaves_stopped_server_stopped(self):
        world_id = "A" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slot = root / "slot"
            slot.mkdir()
            game_user = root / "GameUserSettings.ini"
            with patch.object(app, "slot_path", return_value=slot), patch.object(
                app, "slot_savegames_dir", return_value=slot
            ), patch.object(app, "read_json", return_value={"id": "slot", "is_new": True, "world_id": world_id}), patch.object(
                app, "find_world_dirs", return_value=[]
            ), patch.object(app, "GAME_USER_SETTINGS", game_user), patch.object(
                app, "get_server_status", return_value={"running": False, "container_running": False}
            ), patch.object(app, "backup_current_save", side_effect=ValueError("当前存档目录为空，无法备份")), patch.object(
                app, "remove_children"
            ), patch.object(app, "write_dedicated_server_name"), patch.object(app, "fix_save_ownership"), patch.object(
                app, "write_json"
            ), patch.object(app, "set_recorded_active_slot"), patch.object(app, "service_action") as service_action:
                result = app.switch_save_slot("slot")
        service_action.assert_not_called()
        self.assertFalse(result["running"])

    def test_status_skips_rcon_when_player_list_is_disabled(self):
        with patch.object(app, "parse_palworld_settings", return_value={"bShowPlayerList": "False"}), patch.object(
            app, "get_online_players", return_value={"players": [], "source": "none", "query_ok": False, "error": "disabled", "fallback_used": False}
        ), patch.object(app, "get_game_version", return_value="v1"):
            info = app.get_server_info()
        self.assertFalse(info["player_list_enabled"])
        self.assertFalse(info["players_query_ok"])
        self.assertEqual(info["online_players"], [])

    def test_player_cache_is_separated_by_policy(self):
        app._player_response_cache = (0.0, False, {})
        with patch.object(app, "get_rest_players", side_effect=RuntimeError("unavailable")), patch.object(
            app, "rcon_command", return_value="Alice,123"
        ) as rcon:
            disabled = app.get_online_players(False)
            enabled = app.get_online_players(True)
        self.assertEqual(disabled["source"], "none")
        self.assertEqual(enabled["source"], "rcon")
        rcon.assert_called_once_with("ShowPlayers")

    def test_rcon_api_returns_command_output(self):
        result = SimpleNamespace(success=True, acknowledged=True, response="Welcome to Pal Server", message="")
        with app.app.test_client() as client, patch.object(app, "execute_panel_rcon_command", return_value=result):
            response = client.post("/api/rcon", json={"command": "Info"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["response"], "Welcome to Pal Server")
        self.assertTrue(response.json["acknowledged"])

    def test_showplayers_allows_no_response_but_info_does_not(self):
        with patch.object(app, "execute_rcon_command", return_value=SimpleNamespace()) as execute:
            app.execute_panel_rcon_command("ShowPlayers")
            app.execute_panel_rcon_command("Info")
        self.assertTrue(execute.call_args_list[0].kwargs["allow_no_response"])
        self.assertFalse(execute.call_args_list[1].kwargs["allow_no_response"])

    def test_rcon_api_allows_showplayers_without_response(self):
        result = SimpleNamespace(
            success=True,
            acknowledged=False,
            response="",
            message="Command sent; this Palworld command did not return an RCON response",
        )
        with app.app.test_client() as client, patch.object(app, "execute_panel_rcon_command", return_value=result) as execute:
            response = client.post("/api/rcon", json={"command": "ShowPlayers"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["success"])
        self.assertFalse(response.json["acknowledged"])
        self.assertIn("did not return", response.json["message"])
        execute.assert_called_once_with("ShowPlayers")

    def test_rcon_api_rejects_non_ascii_broadcast(self):
        with app.app.test_client() as client, patch.object(app, "execute_panel_rcon_command") as execute:
            response = client.post("/api/rcon", json={"command": "Broadcast 请问"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["success"])
        self.assertIn("ASCII", response.json["message"])
        execute.assert_not_called()

    def test_rcon_api_reports_unacknowledged_command(self):
        result = SimpleNamespace(success=False, acknowledged=False, response="", message="The server did not acknowledge the command")
        with app.app.test_client() as client, patch.object(app, "execute_panel_rcon_command", return_value=result):
            response = client.post("/api/rcon", json={"command": "Info"})
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json["success"])
        self.assertEqual(response.json["message"], "The server did not acknowledge the command")

    def test_service_action_reports_operation_busy(self):
        with patch.object(app, "save_operation_lock", side_effect=app.SaveOperationBusy("busy")), patch.object(
            app, "_service_action_unlocked"
        ) as unlocked:
            success, message = app.service_action("restart")
        self.assertFalse(success)
        self.assertEqual(message, "busy")
        unlocked.assert_not_called()

    def test_docker_update_duplicate_claim_is_rejected(self):
        with patch.object(app, "using_docker_backend", return_value=True), patch.object(
            app, "acquire_save_operation_lock", side_effect=app.SaveOperationBusy("busy")
        ), patch.object(app.threading, "Thread") as thread:
            success, message = app.start_update_service()
        self.assertFalse(success)
        self.assertEqual(message, "busy")
        thread.assert_not_called()

    def test_stale_update_reconciles_when_target_marker_is_current(self):
        update_status = {
            "running": True,
            "request_id": "request-1",
            "requested_at": "2026-08-11T12:00:00+00:00",
            "target_manifest": "target",
            "initially_running": True,
        }
        marker = {"request_id": "request-1", "update_success": True, "updated_at": "2026-08-11T12:01:00+00:00"}
        with patch.object(app, "parse_steam_manifest", return_value={"buildid": "1", "manifest": "target"}), patch.object(
            app, "read_docker_install_marker", return_value=marker
        ), patch.object(app, "docker_container_running", return_value=True), patch.object(app, "write_json") as write:
            result = app.reconcile_docker_update_status(update_status)
        self.assertFalse(result["running"])
        self.assertTrue(result["success"])
        write.assert_called_once()

    def test_marker_from_older_request_is_ignored(self):
        update_status = {
            "running": True,
            "request_id": "request-2",
            "requested_at": app.iso_now(),
            "started_at": app.iso_now(),
            "target_manifest": "target",
            "initially_running": True,
        }
        marker = {"request_id": "request-1", "phase": "failed", "update_success": False}
        with patch.object(app, "parse_steam_manifest", return_value={"manifest": "old"}), patch.object(
            app, "read_docker_install_marker", return_value=marker
        ), patch.object(app, "docker_container_running", return_value=True), patch.object(app, "write_json") as write:
            result = app.reconcile_docker_update_status(update_status)
        self.assertTrue(result["running"])
        write.assert_not_called()

    def test_status_exposes_effective_upload_limits(self):
        server_status = {"running": False}
        with app.app.test_client() as client, patch.object(app, "get_server_status", return_value=server_status):
            response = client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["upload_limits"]["save_upload_max_bytes"], app.SAVE_UPLOAD_MAX_BYTES)
        self.assertEqual(response.json["upload_limits"]["mod_upload_max_bytes"], app.MOD_UPLOAD_MAX_BYTES)

    def test_log_stream_emits_repeated_text_at_new_position(self):
        snapshots = [["same"], ["same", "same"]]
        with patch.object(app, "get_server_log", side_effect=snapshots), patch.object(
            app.time, "monotonic", side_effect=[0, 0, 1, 3]
        ), patch.object(app.time, "sleep"):
            events = list(app.get_server_log_stream(max_seconds=2))
        self.assertEqual(events.count("data: same\n\n"), 2)

    def test_stale_running_update_is_reclaimed(self):
        stale = {
            "running": True,
            "started_at": "2026-01-01T00:00:00+0000",
            "steps": [{"name": "detect", "status": "done"}],
        }
        with patch.object(app, "write_json") as write_json:
            result = app.reconcile_systemd_update_status(stale, service_active=False)
        self.assertFalse(result["running"])
        self.assertEqual(result["phase"], "failed")
        self.assertIn("后台更新进程已退出", result["message"])
        write_json.assert_called_once()

    def test_running_update_with_a_live_worker_is_left_alone(self):
        with patch.object(app, "write_json") as write_json:
            result = app.reconcile_systemd_update_status(
                {"running": True, "started_at": "2026-01-01T00:00:00+0000"}, service_active=True
            )
        self.assertTrue(result["running"])
        write_json.assert_not_called()

    def test_just_started_update_survives_the_grace_window(self):
        with patch.object(app, "write_json") as write_json:
            result = app.reconcile_systemd_update_status({"running": True, "started_at": app.iso_now()}, service_active=False)
        self.assertTrue(result["running"])
        write_json.assert_not_called()

    def test_parse_iso_timestamp_accepts_strftime_offsets(self):
        # iso_now() emits "+0800"; Python 3.10's fromisoformat rejects that form
        # and used to turn every updater timestamp into 0.0.
        expected = datetime(2026, 10, 29, 12, 24, 12, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(app.parse_iso_timestamp("2026-10-29T20:24:12+0800"), expected, places=0)
        self.assertGreater(app.parse_iso_timestamp("2026-10-29T20:24:12+00:00"), 0)
        self.assertGreater(app.parse_iso_timestamp("2026-10-29T12:24:12Z"), 0)
        self.assertGreater(app.parse_iso_timestamp(app.iso_now()), 0)
        self.assertEqual(app.parse_iso_timestamp(None), 0.0)
        self.assertEqual(app.parse_iso_timestamp(""), 0.0)
        self.assertEqual(app.parse_iso_timestamp("not a timestamp"), 0.0)


if __name__ == "__main__":
    unittest.main()
