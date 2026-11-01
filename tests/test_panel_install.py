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
        self.assertEqual(cmd[8], str(panel_install.ROOT_EXEC_DIR / "panel_install.py"))
        status.step.assert_called()


if __name__ == "__main__":
    unittest.main()
