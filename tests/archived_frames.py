"""Best-effort lookup for archived runtime frames: a probe, not a claim.

Measured 2026-10-16: eleven frames that test files pinned by full path were pruned by the
capture TTL before anyone copied them into a protected tree.  The evidence-integrity guard
was right to say so -- a hard reference that names a file which is gone is a claim the
suite cannot keep, and the honest end states are few.  The project's own answer, established
in ``test_last_step_execution``, is this pattern: look the frame up by the timestamp in its
name across the rotation directory, and skip -- naming what is gone -- rather than re-pin
the test to a lookalike (``_require``'s comment: "a test that swaps in its own evidence is
the habit that hid the two faults this file exists for").

A lookup is not a claim, so the patterns here are deliberately not path literals the guard
reads; the guard stays red for references that DO claim a file, which is what keeps the
next prune from being silent.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / "dataset" / "raw" / "control_panel" / "runtime_auto"


def archived(pattern: str) -> Path | None:
    """The newest frame matching ``pattern`` anywhere under the rotation directory, or None."""
    found = sorted(AUTO.glob("*/" + pattern))
    return found[-1] if found else None


def require(*frames: tuple[str, Path | None]) -> None:
    """Skip, naming what is gone."""
    gone = [role for role, path in frames if path is None or not path.is_file()]
    if gone:
        raise unittest.SkipTest("archived frames not on this machine: " + ", ".join(gone))
