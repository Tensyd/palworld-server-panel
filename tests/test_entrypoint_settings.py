"""The Docker entrypoint rewrites PalWorldSettings.ini on every boot.

That rewrite used to be a regex (`Key=([^,\\)]+)`), which truncated any quoted
value containing a comma -- `ServerDescription="Hello, world"` became
`"Hello` plus a dangling `, world"`. It also overwrote ServerName and
ServerDescription from the environment every time the container started, which
silently reverted edits the user had just saved in the panel.

These tests run the real embedded script rather than a copy of its logic.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO / "docker" / "palworld-entrypoint.sh"

BASE_ENV = {
    "RCON_PASSWORD": "s3cret",
    "SERVER_NAME": "From Env",
    "SERVER_DESCRIPTION": "Env Description",
    "SERVER_MAX_PLAYERS": "16",
    "PALWORLD_PORT": "9000",
    "PALWORLD_QUERY_PORT": "27016",
    "RCON_PORT": "25576",
}


def settings_block() -> str:
    lines = ENTRYPOINT.read_text(encoding="utf-8").splitlines()
    marker = next(
        index for index, line in enumerate(lines) if 'python3 - "${SETTINGS_FILE}"' in line and "<<'PY'" in line
    )
    end = next(index for index in range(marker + 1, len(lines)) if lines[index].strip() == "PY")
    return "\n".join(lines[marker + 1 : end])


class EntrypointSettingsTests(unittest.TestCase):
    def apply(self, contents: str, **overrides: str) -> str:
        env = {**os.environ, **BASE_ENV, **overrides}
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "rewrite.py"
            script.write_text(settings_block(), encoding="utf-8")
            target = Path(directory) / "PalWorldSettings.ini"
            target.write_text(contents, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(script), str(target)],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return target.read_text(encoding="utf-8")

    def test_quoted_values_keep_their_commas(self):
        result = self.apply(
            '[/Script/Pal.PalGameWorldSettings]\n'
            'OptionSettings=(ServerDescription="Hello, world",PublicPort=8211)\n'
        )
        self.assertIn('ServerDescription="Hello, world"', result)
        self.assertNotIn(' world"', result.replace('"Hello, world"', ""))
        self.assertIn("PublicPort=9000", result)

    def test_managed_keys_are_not_rewritten_inside_quoted_values(self):
        result = self.apply(
            '[/Script/Pal.PalGameWorldSettings]\n'
            'OptionSettings=(ServerDescription="RCONPort=1, PublicPort=2",RCONPort=25575)\n'
        )
        self.assertIn('ServerDescription="RCONPort=1, PublicPort=2"', result)
        self.assertIn("RCONPort=25576", result)

    def test_parentheses_inside_quotes_do_not_end_the_list(self):
        result = self.apply(
            '[/Script/Pal.PalGameWorldSettings]\n'
            'OptionSettings=(ServerDescription="smile (:)",PublicPort=8211)\n'
        )
        self.assertIn('ServerDescription="smile (:)"', result)
        self.assertIn("PublicPort=9000", result)
        self.assertTrue(result.rstrip().endswith(")"))

    def test_saved_server_name_is_not_reverted_on_boot(self):
        result = self.apply(
            '[/Script/Pal.PalGameWorldSettings]\n'
            'OptionSettings=(ServerName="My Server",AdminPassword="old")\n'
        )
        self.assertIn('ServerName="My Server"', result)
        self.assertIn('AdminPassword="s3cret"', result)

    def test_missing_keys_are_added(self):
        result = self.apply("[/Script/Pal.PalGameWorldSettings]\nOptionSettings=()\n")
        for fragment in ('ServerName="From Env"', "PublicPort=9000", "QueryPort=27016", 'AdminPassword="s3cret"'):
            self.assertIn(fragment, result)
        self.assertTrue(result.rstrip().endswith(")"))

    def test_managed_key_wins_over_an_existing_value(self):
        result = self.apply(
            '[/Script/Pal.PalGameWorldSettings]\n'
            'OptionSettings=(PublicPort=8211,QueryPort=27015,RCONEnabled=False)\n'
        )
        self.assertIn("PublicPort=9000", result)
        self.assertIn("QueryPort=27016", result)
        self.assertIn("RCONEnabled=True", result)

    def test_trailing_comma_and_duplicates_do_not_produce_empty_entries(self):
        result = self.apply(
            '[/Script/Pal.PalGameWorldSettings]\n'
            'OptionSettings=(PublicPort=8211,,PublicPort=8212,)\n'
        )
        self.assertIn("PublicPort=9000", result)
        self.assertNotIn(",,", result)
        self.assertNotIn("=(,", result)


if __name__ == "__main__":
    unittest.main()
