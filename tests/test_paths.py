"""The panel, the updater and the installer must agree on where state lives.

They used to disagree. panel_update.py derived its files from PANEL_DIR while
app.py hard-coded /home/demo/palworld-panel, so any deployment with a custom
PANEL_DIR had the updater writing one status file and the web UI reading
another -- the panel then polls a file nobody updates, forever.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Any of these would mask the default we are trying to observe.
PATH_OVERRIDES = (
    "PANEL_UPDATE_STATUS",
    "PANEL_UPDATE_LOG",
    "PANEL_UPDATE_SCRIPT",
    "PANEL_INSTALL_STATUS",
    "PANEL_INSTALL_LOG",
    "PANEL_INSTALL_SCRIPT",
    "PANEL_INSTALL_REQUEST",
    "AUDIT_LOG",
    "SAVE_SLOT_ROOT",
    "MOD_LIBRARY_ROOT",
    "CONFIG_BACKUP_DIR",
)

TRACKED = (
    "UPDATE_STATUS",
    "UPDATE_LOG",
    "UPDATE_SCRIPT",
    "INSTALL_STATUS",
    "INSTALL_LOG",
    "INSTALL_SCRIPT",
    "INSTALL_REQUEST",
    "AUDIT_LOG",
    "SAVE_SLOT_ROOT",
    "MOD_LIBRARY_ROOT",
    "CONFIG_BACKUP_DIR",
    "PANEL_DIR",
)


class PanelPathTests(unittest.TestCase):
    def test_panel_state_paths_follow_panel_dir(self):
        env = {key: value for key, value in os.environ.items() if key not in PATH_OVERRIDES}
        env["PANEL_DIR"] = "/tmp/custom-panel"
        env["PANEL_SECRET_KEY"] = "test"
        code = (
            "import json, app\n"
            f"print(json.dumps({{name: str(getattr(app, name)) for name in {TRACKED!r}}}))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        paths = json.loads(proc.stdout.strip().splitlines()[-1])
        for name, value in paths.items():
            resolved = Path(value).as_posix()
            with self.subTest(path=name):
                self.assertTrue(
                    resolved == "/tmp/custom-panel" or resolved.startswith("/tmp/custom-panel/"),
                    f"{name} = {value} escaped PANEL_DIR",
                )

    def test_only_the_panel_dir_default_mentions_the_home_path(self):
        for filename in ("app.py", "panel_update.py", "panel_install.py"):
            with self.subTest(file=filename):
                source = (REPO / filename).read_text(encoding="utf-8")
                hits = [line.strip() for line in source.splitlines() if "/home/demo/palworld-panel" in line]
                # A file may derive everything from PANEL_HOME and mention no
                # literal at all; the failure mode is a stray second default.
                self.assertLessEqual(len(hits), 1, f"{filename} hard-codes panel paths: {hits}")
                for hit in hits:
                    self.assertIn("PANEL_DIR", hit)


if __name__ == "__main__":
    unittest.main()
