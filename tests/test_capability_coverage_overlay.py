"""The capability-coverage generator must add to hand-confirmed knowledge, never delete it.

Regression for a real loss: ``tools/update_workbuddy_handoff.py`` runs
``tools/build_capability_coverage.py`` on every handoff refresh, and that
regeneration used to overwrite ``knowledge/goals/capability_skill_map.json`` from
the canonical map alone.  The hand-added ``SELECT_BEAST_TARGET_LABELLED`` hop in
``AVOID_STAMINA_WASTE / SPEND_STAMINA_ON_BEAST`` (with its 2026-09-20 note) was
therefore silently dropped, and ``check_wiring``'s
``capability: the labelled hop is SPEND_STAMINA_ON_BEAST`` went from OK to MISS.

The fix is generated-base + manual-overlay
(``knowledge/goals/capability_skill_map.manual.json``); these tests pin it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.capability_coverage import CapabilityCoverage  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

MAP_PATH = ROOT / "knowledge/goals/goal_capability_map.json"
OVERLAY_PATH = ROOT / "knowledge/goals/capability_skill_map.manual.json"
REPORT_PATH = ROOT / "knowledge/goals/capability_skill_map.json"

GOAL = "AVOID_STAMINA_WASTE"
CAPABILITY = "SPEND_STAMINA_ON_BEAST"
MANUAL_SKILL = "SELECT_BEAST_TARGET_LABELLED"


def _coverage(*, with_overlay: bool) -> CapabilityCoverage:
    return CapabilityCoverage(
        v2_registry(),
        verifier_skills=set(LiveRuntime.VERIFIED_ATOMIC),
        map_path=MAP_PATH,
        overlay_path=OVERLAY_PATH if with_overlay else None,
    )


def _capability_row(payload: dict) -> dict:
    for goal in payload["goals"]:
        if goal["goal"] != GOAL:
            continue
        for capability in goal["capabilities"]:
            if capability["capability"] == CAPABILITY:
                return capability
    raise AssertionError(f"{GOAL}/{CAPABILITY} not present in the generated payload")


def test_regenerated_base_keeps_the_manual_hop() -> None:
    payload = _coverage(with_overlay=True).build({})
    row = _capability_row(payload)
    assert MANUAL_SKILL in row["alternatives"]
    assert "2026-09-20" in row["notes"]
    assert "SELECT_BEAST_TARGET_LABELLED" in row["notes"]


def test_overlay_is_what_preserves_it() -> None:
    """Without the overlay the hop is gone -- which is the defect this pins."""
    without = _coverage(with_overlay=False).build({})
    assert MANUAL_SKILL not in _capability_row(without)["alternatives"]

    with_overlay = _coverage(with_overlay=True).build({})
    assert MANUAL_SKILL in _capability_row(with_overlay)["alternatives"]


def test_overlay_only_adds_never_reorders_away_generated_entries() -> None:
    without = _capability_row(_coverage(with_overlay=False).build({}))["alternatives"]
    with_overlay = _capability_row(_coverage(with_overlay=True).build({}))["alternatives"]
    # The generated alternatives survive, in order, and the manual one is appended.
    assert with_overlay[: len(without)] == without
    assert set(without) <= set(with_overlay)


def test_regeneration_is_idempotent() -> None:
    first = _coverage(with_overlay=True).build({"SELECT_BEAST_TARGET_LABELLED": {
        "attempts": 5, "success": 4, "failure": 1}})
    second = _coverage(with_overlay=True).build({"SELECT_BEAST_TARGET_LABELLED": {
        "attempts": 5, "success": 4, "failure": 1}})
    assert _capability_row(first)["alternatives"] == _capability_row(second)["alternatives"]
    assert _capability_row(first)["notes"] == _capability_row(second)["notes"]


def test_applied_overlay_is_recorded_in_the_report() -> None:
    payload = _coverage(with_overlay=True).build({})
    applied = payload.get("manual_overlay")
    assert isinstance(applied, list) and applied, "the merge must be visible in the report"
    assert any(entry["goal"] == GOAL and entry["capability"] == CAPABILITY and
               MANUAL_SKILL in entry["alternatives_add"] for entry in applied)


def test_written_payload_round_trips_and_reader_still_maps_the_skill(tmp_path: Path) -> None:
    payload = _coverage(with_overlay=True).build({})
    target = tmp_path / "capability_skill_map.json"
    CapabilityCoverage.write(payload, target)
    reloaded = json.loads(target.read_text(encoding="utf-8"))
    assert MANUAL_SKILL in _capability_row(reloaded)["alternatives"]

    # The property check_wiring asserts, mirrored here: the project's own table maps
    # the labelled hop to the beast-spending capability.
    from winter_agent_v2.escalation_queue import capability_for_skill

    assert capability_for_skill(MANUAL_SKILL) == CAPABILITY


def test_checked_in_report_matches_a_fresh_generation() -> None:
    """The committed report must be the one the fixed generator produces.

    ``check_wiring`` reads the file on disk, not this builder.  If someone
    regenerates without the overlay and commits, this fails instead of the wiring
    audit silently losing a check.
    """
    if not REPORT_PATH.is_file():
        raise AssertionError("knowledge/goals/capability_skill_map.json is missing")
    on_disk = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert MANUAL_SKILL in _capability_row(on_disk)["alternatives"]
    assert "2026-09-20" in _capability_row(on_disk)["notes"]
