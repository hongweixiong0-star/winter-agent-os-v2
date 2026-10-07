"""``NO_PRODUCTION_ORPHAN_MODULE`` must measure, and must not cry wolf.

The check exists because a hand-grep concluded the opposite of the truth about ``recovery.py``:
``grep recovery`` returns 970 hits in production paths, all of them the *word* in a docstring,
and the module itself is imported by one test and nothing else.  So two things are pinned here:

1. **It measures the real thing.**  A module that IS imported by production code must not be
   reported -- the four controls below are live modules with wide fan-in, and a scanner that
   flags them is measuring substrings rather than imports.
2. **It stays registered.**  A check that is written and never wired is the same defect the
   check is about, one level up.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest  # noqa: E402

from tools.invariant_review import (  # noqa: E402
    CHECKS, FAIL, KNOWN_PRODUCTION_ORPHANS, PASS, UNMEASURED,
    no_production_orphan_module,
)


class TheCheckIsRegisteredAndWellFormedTest(unittest.TestCase):
    def test_it_is_in_the_check_table(self):
        names = [name for name, _fn in CHECKS]
        self.assertIn("NO_PRODUCTION_ORPHAN_MODULE", names)

    def test_it_returns_a_verdict_and_a_reason(self):
        verdict, detail = no_production_orphan_module()
        self.assertIn(verdict, (PASS, FAIL, UNMEASURED))
        self.assertTrue(detail.strip(), "a verdict without a reason is not a measurement")

    def test_the_known_debt_is_printed_even_when_it_passes(self):
        """Pinning the known set must not hide it: the count and the names stay in the detail.

        A check whose PASS says only "ok" would let seven unreachable modules disappear from the
        report the moment the verdict went green -- which is the failure mode the pin is meant to
        avoid, not to cause.
        """
        verdict, detail = no_production_orphan_module()
        if verdict == PASS:
            self.assertIn("known", detail)
            for name in KNOWN_PRODUCTION_ORPHANS:
                self.assertIn(name, detail)

    def test_every_pinned_name_is_a_real_module(self):
        """A typo in the pinned list would make the real module read as *new* and fail forever."""
        package = ROOT / "winter_agent_v2"
        for name in KNOWN_PRODUCTION_ORPHANS:
            self.assertTrue((package / f"{name}.py").exists(),
                            f"{name!r} is pinned as known debt but is not a module")


class LiveModulesAreNotReportedTest(unittest.TestCase):
    """Wide fan-in modules.  Flagging any of these means the scan reads text, not imports."""

    CONTROLS = ("scheduler", "device_lease", "loop_detector", "escalation_queue",
                "runtime_snapshot", "executor_router")

    def test_no_live_module_is_called_an_orphan(self):
        _verdict, detail = no_production_orphan_module()
        for control in self.CONTROLS:
            self.assertNotIn(
                control, detail,
                f"{control!r} is imported by production code; the scan must read import "
                "statements, not substrings",
            )


if __name__ == "__main__":
    unittest.main()
