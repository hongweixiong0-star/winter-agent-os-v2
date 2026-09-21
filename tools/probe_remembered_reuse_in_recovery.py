"""Which remembered control does the recovery scenario now tap, and where?

Context.  tests/test_live_runtime.py::test_unknown_page_recovery_resumes_the_run
asserts that backing out of an unreadable screen produces NO taps.  With the
production ledger present it now produces one, because the frame after the back
is a readable MAP frame and the brain asks for a control whose template is
missing but whose position was measured from a real frame earlier.

This probe answers the two questions that decide whether that is the feature or a
bug: which semantic, and where on the picture.  It does not modify anything; it
uses a temporary capture directory like the test does.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2 import control_experience  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_live_runtime import FakeDevice, FakeSemantic, FakeVision  # noqa: E402


def main() -> None:
    ledger = control_experience.load()
    print("ledger entries:", len(ledger))
    print()
    print("=== every MAP entry the reuse gate would accept ===")
    for key, entry in sorted(ledger.items()):
        if not key.startswith("MAP|"):
            continue
        print(f"  {key:44} attempts={entry.attempts} last={entry.last_result} "
              f"known={entry.known_result!r} sterile={entry.sterile} resolved={entry.resolved}")
        print(f"      position_norm={entry.position_norm} "
              f"px={tuple(round(v * s) for v, s in zip(entry.position_norm or (0, 0), (720, 1280)))}")
        frame = str(entry.read_from_frame or "")
        print(f"      frame={os.path.basename(frame)} exists={os.path.exists(frame) if frame else False}")

    print()
    print("=== the scenario, with the ledger as production has it ===")
    states = [
        WorldState(),
        WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
    ]
    device = FakeDevice()
    with TemporaryDirectory() as temp:
        run = LiveRuntime(
            device=device,
            vision=FakeVision(states),
            semantic_vision=FakeSemantic(),
            capture_dir=Path(temp),
            sleeper=lambda _seconds: None,
        ).run(max_actions=2)
        reused = getattr(run, "reused_controls", None)
        print("  taps :", device.taps)
        print("  backs:", device.backs)
        print("  stop :", run.stop_reason)
        for step in run.steps:
            action = step.execution.action if step.execution else None
            print(f"  step {step.index}: {step.decision.skill} executed="
                  f"{step.execution.executed if step.execution else None} target="
                  f"{getattr(action, 'target', None)} "
                  f"verifier={step.verification.reason if step.verification else None}")
        print("  reuse notes recorded in memory:", reused)


if __name__ == "__main__":
    main()
