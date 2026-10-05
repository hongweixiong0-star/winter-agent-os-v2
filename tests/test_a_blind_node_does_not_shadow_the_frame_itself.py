"""A position-blind node must not shadow a reader that answers from the frame itself.

Measured 2026-10-05.  Two quick-panel skills preferred a MAA recognition node whose template was
cropped from one frame's geometry:

    OPEN_TASK_FROM_QUICK_PANEL_BUILDING      357 attempts, 103 failures
    OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT  326 attempts,  79 failures

every failure ``SEMANTIC_TARGET_NOT_VERIFIED`` with ``MAA_TEMPLATE:NO_MATCH``, duration 0.06-0.13 s
and an **empty ``after_screenshot``** -- no tap was sent at all -- while the episode's own
``state_before.quick_panel`` already carried the row:

    {'key': 'BUILDING', 'control': 'ARROW', 'arrow_norm': [0.5618, 0.343], 'status': 'IDLE'}

A recognition miss on the MAA path does not fall through, deliberately, because a position-blind
matcher must not become a blind tap.  So the runtime resolver that reads the row off the current
frame -- and answers it, on every one of those frames -- was never consulted.

These tests pin the retirement the operator's rule licenses ("if MAA did not improve it, keep
ADB"), and pin *both* halves: the route that makes the resolver reachable, and the resolver's
answer.  A regression in either one has to fail here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.executor_router import ADB, RoutingTable  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

ROUTING = ROOT / "knowledge/execution/backend_routing.json"

#: The two rows as the failing episodes recorded them in ``state_before.quick_panel``.
ROWS = {
    "OPEN_TASK_FROM_QUICK_PANEL_BUILDING": (
        "QUICK_PANEL_ROW_BUILDING",
        {"key": "BUILDING", "control": "ARROW", "arrow_norm": [0.5618, 0.343], "status": "IDLE"},
        (0.5618, 0.343),
    ),
    "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT": (
        "QUICK_PANEL_ROW_HERO_RECRUIT",
        {"key": "HERO_RECRUIT", "control": "ARROW", "arrow_norm": [0.5618, 0.4102],
         "status": "UNKNOWN"},
        (0.5618, 0.4102),
    ),
}


def _runtime():
    """A LiveRuntime carrying only the read path's bookkeeping.

    The ``_printed_*`` sets are created in ``LiveRuntime.__init__`` and appended to *after* a point
    has been found, so a bare object would raise inside the finder and read as "no answer".  No
    ``semantic_vision`` is set on purpose: this path must not need a template.
    """
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._printed_deferrals = set()
    runtime._printed_remembered = set()
    runtime._printed_screen_refusals = set()
    runtime._printed_declared_refusals = set()
    runtime._printed_printed = set()
    runtime._printed_reads = []
    runtime._printed_boxes = {}
    return runtime


def _panel(row) -> WorldState:
    return WorldState(page=Page.HOME, quick_panel={"open": True, "rows": [row]})


def _payload() -> dict:
    return json.loads(ROUTING.read_text(encoding="utf-8"))


def test_the_route_no_longer_prefers_the_node_that_never_matched():
    table = RoutingTable.load()
    for skill in ROWS:
        route = table.route(skill)
        assert route.preferred == ADB, (skill, route.preferred)
        assert route.recognition_backend == "LEGACY", (skill, route.recognition_backend)


def test_the_retired_node_is_no_longer_handed_out():
    # Not merely shadowed by the preference: the precedents this follows (SEARCH_RESOURCE,
    # OPEN_BUILDING_UPGRADE) carry no recognition dict at all, so a later fallback cannot
    # resurrect a matcher that was measured as blind.
    table = RoutingTable.load()
    for skill, (semantic, _row, _point) in ROWS.items():
        assert table.route(skill).recognition == {}, skill
        assert table.recognition_node(skill, semantic) is None, skill


def test_the_resolver_answers_the_row_the_frame_itself_drew():
    runtime = _runtime()
    for skill, (semantic, row, point) in ROWS.items():
        skill_row = v2_registry().get(skill)
        assert skill_row is not None, skill
        assert skill_row.action.target == semantic, (skill, skill_row.action.target)
        assert runtime._resolve_semantic_target(semantic, _panel(row)) == point, skill


def test_the_whole_chain_route_and_resolver_together_answer_the_step():
    # The previous round's fix was lost because only one half was asserted: the resolver answered
    # and the route still preferred MAA, so the resolver was never reached.
    table = RoutingTable.load()
    runtime = _runtime()
    for skill, (semantic, row, point) in ROWS.items():
        route = table.route(skill)
        assert route.preferred == ADB, skill
        assert runtime._resolve_semantic_target(semantic, _panel(row)) == point, skill


def test_the_retirement_is_recorded_where_a_later_reader_looks():
    payload = _payload()
    for skill, (semantic, _row, point) in ROWS.items():
        entry = payload["skills"][skill]
        measured = entry["evidence"]["measured_record"]
        assert measured["skill_id"] == skill, skill
        assert measured["failure_type"] == "SEMANTIC_TARGET_NOT_VERIFIED"
        assert measured["after_screenshot"] == "EMPTY (no tap sent)", skill
        # The A/B the operator's rule demands, kept with the decision it licenses.
        ab = measured["adb_ab"]
        assert ab["success_side_answered"] == ab["success_side_total"], skill
        assert ab["failure_side_answered"] + ab["failure_side_silent"] == ab["failure_side_total"]
        assert ab["failure_side_answered"] >= 79, skill
        # The recorded reading is a *different frame's* row, so only its invariant is asserted:
        # the panel's right-hand column is fixed and the row's y moves with the panel's scroll --
        # which is the whole reason a fixed rect cannot cover this control.
        recorded_norm = measured["frame_declared_control_norm"]
        assert len(recorded_norm) == 2 and all(0.0 <= float(v) <= 1.0 for v in recorded_norm), skill
        assert float(recorded_norm[0]) == float(point[0]), skill
        recorded = payload["not_migrated"][f"{skill}_RECOGNITION"]
        assert recorded["semantic"] == semantic, skill


def test_no_other_skill_lost_its_node_to_this_change():
    # The retirement is per semantic. Anything else still carrying a node must still carry it.
    payload = _payload()
    still_carrying = {k for k, e in payload["skills"].items() if e.get("recognition")}
    assert "OPEN_TASK_FROM_QUICK_PANEL_BUILDING" not in still_carrying
    assert "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT" not in still_carrying
    # A sample of the untouched ones, so a blanket deletion would fail here.
    for untouched in ("OPEN_HOME", "OPEN_MAP", "DISPATCH_MARCH"):
        assert untouched in still_carrying, untouched
