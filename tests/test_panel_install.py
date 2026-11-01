from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import panel_install


DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"


def directives(text: str) -> list[str]:
    """Unit content without blank lines or comments, path separators normalised."""
    lines = [line.strip() for line in text.replace("\\", "/").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


class ServiceFileTests(unittest.TestCase):
    def test_manual_and_scheduled_units_use_different_flags(self):
        units = panel_install.render_service_files()
        manual = units["palworld-panel-update.service"]
        scheduled = units["palworld-panel-auto-update.service"]
        self.assertIn("panel_update.py --apply", manual)
        self.assertNotIn("--auto", manual)
        self.assertIn("panel_update.py --auto", scheduled)

    def test_updater_units_are_forgiving_about_the_environment_file(self):
        units = panel_install.render_service_files()
        for name in ("palworld-panel-update.service", "palworld-panel-auto-update.service"):
            self.assertIn("EnvironmentFile=-", units[name], f"{name} must tolerate a missing env file")
            self.assertIn("KillMode=mixed", units[name])
            self.assertIn("TimeoutStartSec=7200", units[name])

    def test_timer_targets_the_scheduled_unit(self):
        timer = panel_install.render_service_files()["palworld-panel-update.timer"]
        self.assertIn("Unit=palworld-panel-auto-update.service", timer)

    def test_sudoers_covers_both_updater_units(self):
        sudoers = panel_install.render_sudoers()
        # --no-block: a blocking start made the HTTP call time out while the
        # oneshot kept running. sudo matches the full command line, so the rule
        # has to spell the flag out.
        self.assertIn("--no-block start palworld-panel-update.service", sudoers)
        self.assertIn("--no-block start palworld-panel-install.service", sudoers)
        self.assertIn("is-active palworld-panel-update.timer", sudoers)

    def test_deploy_sudoers_match_the_installer(self):
        on_disk = (DEPLOY_DIR / "palworld-panel.sudoers").read_text(encoding="utf-8")
        self.assertEqual(directives(panel_install.render_sudoers()), directives(on_disk))

    def test_deploy_copies_do_not_drift_from_the_installer(self):
        """``deploy/`` is reference material; the installer is what actually ships."""
        units = panel_install.render_service_files()
        for name in (
            "palworld-panel.service",
            "palworld-panel-install.service",
            "palworld-panel-update.service",
            "palworld-panel-auto-update.service",
            "palworld-panel-update.timer",
        ):
            with self.subTest(unit=name):
                on_disk = (DEPLOY_DIR / name).read_text(encoding="utf-8")
                self.assertEqual(directives(units[name]), directives(on_disk), f"{name} drifted from panel_install.py")


class PrivilegedBoundaryTests(unittest.TestCase):
    """The panel account must not be able to feed code to root.

    panel_install runs as root and is startable by the panel user through
    sudoers. It used to live in PANEL_DIR, which is chowned to that same user.
    """

    def test_install_unit_runs_the_root_owned_copy(self):
        unit = panel_install.render_service_files()["palworld-panel-install.service"]
        normalized = unit.replace("\\", "/")
        self.assertIn(f"{panel_install.ROOT_EXEC_DIR.as_posix()}/panel_install.py", normalized)
        panel_exec = f"{panel_install.PANEL_DIR.as_posix()}/panel_install.py"
        self.assertNotIn(panel_exec, normalized, "root must not execute a file the panel user can rewrite")

    def test_root_exec_dir_is_outside_the_panel_tree(self):
        root_dir = panel_install.ROOT_EXEC_DIR.resolve()
        panel_dir = panel_install.PANEL_DIR.resolve()
        self.assertFalse(
            root_dir == panel_dir or panel_dir in root_dir.parents,
            f"{root_dir} sits inside the panel user's tree {panel_dir}",
        )

    def test_privileged_copy_is_installed_root_owned(self):
        with patch.object(panel_install, "run_checked") as run_checked, patch.object(
            panel_install, "status"
        ) as status:
            panel_install.install_privileged_copy()
        commands = [call.args[0] for call in run_checked.call_args_list]
        self.assertTrue(any(cmd[:4] == ["install", "-d", "-o", "root"] for cmd in commands), commands)
        copies = [cmd for cmd in commands if cmd[0] == "install" and "-d" not in cmd]
        self.assertEqual(len(copies), 1, commands)
        cmd = copies[0]
        self.assertEqual(cmd[1:7], ["-o", "root", "-g", "root", "-m", "755"])
        self.assertTrue(cmd[7].endswith("panel_install.py"))
        self.assertEqual(Path(cmd[8]).resolve(), (panel_install.ROOT_EXEC_DIR / "panel_install.py").resolve())
        status.step.assert_called()

    def test_running_from_the_published_copy_does_not_copy_onto_itself(self):
        # install.sh invokes the root copy, which then re-runs this step.
        # `install a a` refuses identical files and aborted the whole repair.
        published = str(panel_install.ROOT_EXEC_DIR / "panel_install.py")
        with patch.object(panel_install, "run_checked") as run_checked, patch.object(
            panel_install, "status"
        ), patch.object(panel_install, "__file__", published):
            panel_install.install_privileged_copy()
        copies = [
            call.args[0]
            for call in run_checked.call_args_list
            if call.args[0][0] == "install" and "-d" not in call.args[0]
        ]
        self.assertEqual(copies, [], "copied the installer onto itself")

class ConfigPasswordTests(unittest.TestCase):
    """The panel and the game must agree on the RCON password."""

    def test_existing_env_password_is_written_into_the_game_config(self):
        # A reinstall used to mint a fresh password for the game config while
        # upsert_env() kept the old one in the env file, so RCON answered
        # "Auth failed" forever after the second install.
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / "palworld-panel.env"
            env_file.write_text("RCON_PASSWORD=from-env-file" + chr(10), encoding="utf-8")
            pal = root / "palworld"
            cfg_dir = pal / "Pal" / "Saved" / "Config" / "LinuxServer"
            cfg_dir.mkdir(parents=True)
            settings = cfg_dir / "PalWorldSettings.ini"
            settings.write_text(
                "[/Script/Pal.PalGameWorldSettings]" + chr(10) + 'OptionSettings=(AdminPassword="stale",PublicPort=8211)' + chr(10),
                encoding="utf-8",
            )

            with patch.object(panel_install, "ENV_FILE", env_file), patch.object(
                panel_install, "PALWORLD_DIR", pal
            ), patch.object(panel_install, "run_checked"), patch.object(panel_install, "status"), patch.dict(
                os.environ, {"RCON_PASSWORD": ""}, clear=False
            ):
                os.environ.pop("RCON_PASSWORD", None)
                panel_install.configure_palworld()

            text = settings.read_text(encoding="utf-8")
            self.assertIn('AdminPassword="from-env-file"', text)
            self.assertIn("RCON_PASSWORD=from-env-file", env_file.read_text(encoding="utf-8"))

    def test_reconfigure_option_ignores_key_text_inside_quotes(self):
        text = 'OptionSettings=(ServerDescription="RCONPort=1, PublicPort=2",RCONPort=25575)'
        result = panel_install.reconfigure_option(text, "pw")
        self.assertIn('ServerDescription="RCONPort=1, PublicPort=2"', result)
        self.assertIn(f"RCONPort={panel_install.RCON_PORT}", result)
        self.assertIn('AdminPassword="pw"', result)

    def test_upsert_env_keeps_values_that_are_already_set(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panel.env"
            path.write_text("RCON_PASSWORD=keep-me" + chr(10), encoding="utf-8")
            with patch.object(panel_install, "run_checked"):
                panel_install.upsert_env(path, {"RCON_PASSWORD": "new", "PANEL_PORT": "8080"})
            values = panel_install.read_env_values(path)
        self.assertEqual(values["RCON_PASSWORD"], "keep-me")
        self.assertEqual(values["PANEL_PORT"], "8080")

    def test_the_timer_is_enabled_and_started(self):
        # The timer used to be rendered but never enabled, so the scheduled
        # updater never ran on a fresh install.
        commands = panel_install.unit_enable_commands()
        self.assertIn(["systemctl", "enable", "--now", panel_install.UPDATE_TIMER], commands)
        targets = {command[-1] for command in commands}
        self.assertIn(panel_install.PANEL_SERVICE, targets)
        self.assertIn(panel_install.PALWORLD_SERVICE, targets)
        self.assertIn(panel_install.UPDATE_TIMER, targets)


if __name__ == "__main__":
    unittest.main()
