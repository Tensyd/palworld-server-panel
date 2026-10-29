from __future__ import annotations

from pathlib import Path
import unittest

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
        self.assertIn("systemctl start palworld-panel-update.service", sudoers)
        self.assertIn("systemctl start palworld-panel-auto-update.service", sudoers)

    def test_deploy_copies_do_not_drift_from_the_installer(self):
        """``deploy/`` is reference material; the installer is what actually ships."""
        units = panel_install.render_service_files()
        for name in (
            "palworld-panel-update.service",
            "palworld-panel-auto-update.service",
            "palworld-panel-update.timer",
        ):
            with self.subTest(unit=name):
                on_disk = (DEPLOY_DIR / name).read_text(encoding="utf-8")
                self.assertEqual(directives(units[name]), directives(on_disk), f"{name} drifted from panel_install.py")


if __name__ == "__main__":
    unittest.main()
