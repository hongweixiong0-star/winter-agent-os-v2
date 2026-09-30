"""The model probe must not point at the wrong service by default.

Measured 2026-10-01: `tools/probe_gui_model_multimodal.py` defaulted to `http://127.0.0.1:8080`,
which is the WorkBuddy gateway, not the model server.  Run with no arguments it therefore got
`HTTP 403 {"error":"Missing required header: x-codebuddy-request"}` and reported
`screenshot_input_verified: false` -- a false negative about the model, produced entirely by an
argument default.  The project treats "a working component reading as broken" as its most expensive
class of false alarm, and this is a cheap way to keep it from coming back.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "tools"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import probe_gui_model_multimodal as probe  # noqa: E402


class DefaultEndpointTests(unittest.TestCase):
    def test_the_default_endpoint_is_the_one_the_config_declares(self):
        declared = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        expected = str((declared.get("local_planner") or {}).get("endpoint") or "").strip()
        self.assertTrue(expected, "config/v2.json must declare local_planner.endpoint")
        self.assertEqual(probe._default_endpoint(), expected)

    def test_the_default_is_not_the_workbuddy_gateway(self):
        """The specific wrong answer, asserted directly so the symptom is named in the failure."""
        endpoint = probe._default_endpoint()
        self.assertNotIn(":8080", endpoint,
                         "8080 is the WorkBuddy gateway; the probe would answer about it, not the model")
        self.assertIn(":18080", endpoint, "the model server binds 18080")


if __name__ == "__main__":
    unittest.main()
