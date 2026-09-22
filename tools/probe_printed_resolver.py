"""Read-only probe: does the new "read the client's own words" resolver layer answer correctly?

Runs the *production* resolver -- not a copy of its logic -- against the live frames the
episode stream says are the problem, and against frames where it must refuse.  A layer that
answers everywhere would be worse than none, so the refusals are half the test.

Usage:
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/probe_printed_resolver.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from live_stack import production_vision  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

RAW = ROOT / "dataset" / "raw"
AUTO = RAW / "control_panel" / "runtime_auto"

#: ``(semantic, frame, page the frame is on, the verdict the measurement predicts)``
CASES = (
    (
        "BTN_OPEN_HOME",
        AUTO / "20260922_101948_054413" / "20260922_101948_054413_step_010_before_20260922T022230092501.png",
        "MAP",
        "FOUND",
    ),
    (
        "BTN_OPEN_HOME",
        AUTO / "20260921_213842_443057" / "20260921_213842_443057_step_001_before_20260921T133846478992.png",
        "MAP",
        "ABSENT",
    ),
    (
        "BTN_OPEN_ALLIANCE",
        AUTO / "20260921_095040_726092" / "20260921_095040_726092_step_003_before_20260921T015109182497.png",
        "HOME",
        "FOUND",
    ),
    (
        "BTN_OPEN_ALLIANCE",
        AUTO / "20260922_101948_054413" / "20260922_101948_054413_step_010_before_20260922T022230092501.png",
        "MAP",
        "FOUND",
    ),
    (
        "POPUP_GENERIC_REWARD_HEADER",
        AUTO / "20260919_171501_633313" / "20260919_171501_633313_step_007_before_20260919T091636010866.png",
        "POPUP",
        "FOUND",
    ),
    (
        "BTN_DISMISS_INTEL_REWARD",
        AUTO / "20260922_102539_122690" / "20260922_102539_122690_step_002_before_20260922T022551064551.png",
        "POPUP",
        "FOUND",
    ),
    (
        "BTN_CLOSE",
        AUTO / "20260922_102539_122690" / "20260922_102539_122690_step_002_before_20260922T022551064551.png",
        "POPUP",
        "FOUND",
    ),
    (
        "BTN_CLOSE",
        AUTO / "20260921_150011_817103" / "20260921_150011_817103_step_002_before_20260921T070056849860.png",
        "ALLIANCE",
        "UNDECLARED",
    ),
)


def build_runtime():
    """A bare instance carrying only what the resolver reads, as the tests do."""
    vision = production_vision()
    runtime = object.__new__(LiveRuntime)
    runtime.vision = vision
    runtime.semantic_vision = vision.template_vision
    runtime._control_ledger = {}
    runtime._printed_remembered = set()
    runtime._printed_printed = set()
    return runtime


def main() -> int:
    runtime = build_runtime()
    print(f"resolver layer on {LiveRuntime._client_printed_control.__qualname__}")
    print()
    wrong: list[str] = []
    for semantic, frame, page_name, expected in CASES:
        if not frame.exists():
            print(f"{semantic:32} MISSING FRAME {frame.name}")
            wrong.append(f"{semantic} (missing frame)")
            continue
        page = Page(page_name)
        state = WorldState(page=page, confidence=0.99)
        verdict, point = runtime._client_printed_control(semantic, state, frame)
        agree = verdict == expected
        if not agree:
            wrong.append(f"{semantic} on {page_name}: expected {expected}, got {verdict}")
        shown = "none" if point is None else f"({point[0]:.4f}, {point[1]:.4f})"
        print(
            f"{semantic:32} {page_name:9} -> {verdict:10} {shown:20} "
            f"{'ok' if agree else 'MISMATCH'}"
        )
    print()
    print("cases that did not behave as measured:", wrong or "none")
    return 0 if not wrong else 1


if __name__ == "__main__":
    raise SystemExit(main())
