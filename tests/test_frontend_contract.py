"""Contract checks between the browser code and the values it is handed.

These are cheap static assertions over static/app.js. They exist because the
panel's own defaults used to fail its own form validation, and because the
chart code silently multiplied its canvas size on every refresh while a tab was
hidden -- neither is visible to Python tests that only exercise app.py.
"""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"

FIELD_RE = re.compile(
    r'\["(?P<key>[A-Za-z0-9_]+)",\s*"[^"]*",\s*"number",\s*\{(?P<opts>[^}]*)\}\]'
)
DEFAULT_RE = re.compile(r'^\s*(?P<key>[A-Za-z0-9_]+):\s*"(?P<value>[^"]*)",\s*$', re.MULTILINE)


def _js_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _option(opts: str, name: str) -> float | None:
    match = re.search(rf'\b{name}:\s*(-?[0-9.]+)', opts)
    return float(match.group(1)) if match else None


def _config_defaults(source: str) -> dict[str, str]:
    start = source.index("const configDefaults = {")
    end = source.index("\n};", start)
    return {m["key"]: m["value"] for m in DEFAULT_RE.finditer(source[start:end])}


def numeric_fields(source: str) -> list[dict]:
    fields = []
    for match in FIELD_RE.finditer(source):
        opts = match["opts"]
        fields.append(
            {
                "key": match["key"],
                "min": _option(opts, "min"),
                "max": _option(opts, "max"),
                "step": _option(opts, "step"),
            }
        )
    return fields


class FrontendSchemaTests(unittest.TestCase):
    def setUp(self):
        self.source = _js_source()

    def test_every_numeric_field_is_parsable(self):
        # If the schema syntax drifts, the checks below would silently pass on
        # an empty list.
        self.assertGreater(len(numeric_fields(self.source)), 40)

    def test_defaults_satisfy_their_own_validation_rules(self):
        defaults = _config_defaults(self.source)
        self.assertIn("DropItemAliveMaxHours", defaults)
        problems = []
        for field in numeric_fields(self.source):
            raw = defaults.get(field["key"])
            if raw is None or raw.strip() == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue  # non-numeric default on a numeric field is caught elsewhere
            if field["min"] is not None and value < field["min"]:
                problems.append(f"{field['key']}={raw} < min {field['min']}")
            if field["max"] is not None and value > field["max"]:
                problems.append(f"{field['key']}={raw} > max {field['max']}")
            step = field["step"]
            if step and step > 0:
                base = field["min"] if field["min"] is not None else 0.0
                steps = (value - base) / step
                if not math.isclose(steps, round(steps), abs_tol=1e-6):
                    problems.append(f"{field['key']}={raw} is not on a {step} step from {base}")
        self.assertEqual(problems, [], "默认值会被前端自己的校验拒绝：" + "；".join(problems))

    def test_chart_does_not_compound_the_device_pixel_ratio(self):
        body = self.source[
            self.source.index("function drawTrendChart(") : self.source.index("\nfunction renderSystemCharts(")
        ]
        self.assertIn("canvas.width / dpr", body)
        self.assertNotIn("rect.width || canvas.width ||", body)

    def test_api_errors_keep_the_response_body(self):
        body = self.source[self.source.index("async function api(") : self.source.index("\nfunction updateTabIndicator(")]
        self.assertIn("error.payload = data", body)
        self.assertIn("error.status = response.status", body)

    def test_progress_polling_is_scoped_to_one_dialog(self):
        self.assertIn("progressToken: 0", self.source)
        for start, end in (
            ("async function pollUpdateProgress(", "\nconst installStepLabels"),
            ("async function pollInstallProgress(", "\nfunction modTypeLabel"),
        ):
            with self.subTest(poller=start):
                poll = self.source[self.source.index(start) : self.source.index(end)]
                self.assertIn("state.progressToken === token", poll)
                self.assertGreaterEqual(poll.count("if (!mine()) return;"), 2)
                # A poller must never finish a dialog it no longer owns.
                self.assertIn("if (mine()) finishProgressDialog(", poll)


if __name__ == "__main__":
    unittest.main()
