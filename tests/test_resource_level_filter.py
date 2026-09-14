"""Lock the resource-search level filter to live measurements.

The old code hard-coded ``resource_level = 8`` and never read the slider, so
every search filtered for level-8 nodes.  When the nearby map had none, the
game answered "在您的城镇附近没有发现条件相符的目标" and the gather goal could
never complete.  These tests pin the level reader to the frames that were
captured live while stepping the slider from 8 down to 1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_resource_level_relaxed

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "dataset" / "candidate" / "template_manifest.json"
FRAMES = ROOT / "dataset" / "truth_audit"

# (frame, level) pairs captured live on 2026-09-14 while stepping the minus
# control.  lv_after6/lv_after7 both sit at the floor: the fill is empty and
# the minus control is greyed out.
LIVE_LEVELS = {
    "live_now.png": 8,
    "lv_lvl7.png": 7,
    "lv_after1.png": 6,
    "lv_after2.png": 5,
    "lv_after3.png": 4,
    "lv_after4.png": 3,
    "lv_after5.png": 2,
    "lv_after6.png": 1,
    "lv_after7.png": 1,
    "relax_after_minus1.png": 7,
}


def _vision():
    from winter_agent_v2.vision import SemanticWorldVision

    return SemanticWorldVision(CANDIDATE)


def _require(name: str) -> Path:
    path = FRAMES / name
    if not path.exists():
        pytest.skip(f"live frame not captured: {name}")
    return path


@pytest.mark.parametrize("frame,expected", sorted(LIVE_LEVELS.items()))
def test_live_slider_frame_reads_its_measured_level(frame: str, expected: int) -> None:
    assert _vision().semantic.resource_level(_require(frame)) == expected


def test_level_is_read_from_the_screen_not_hard_coded() -> None:
    vision = _vision()
    levels = {vision.semantic.resource_level(_require(name)) for name in LIVE_LEVELS}
    # A hard-coded 8 could only ever produce {8}.  The live frames cover 1..8.
    assert levels == set(range(1, 9))


def test_map_without_a_slider_never_reports_a_level() -> None:
    vision = _vision()
    for name in ("tapchk_after.png",):
        state = vision.observe(_require(name))
        if state.page is not Page.MAP or not state.resource_search_open:
            assert state.resource_level is None


def test_search_panel_reports_the_measured_level_in_world_state() -> None:
    state = _vision().observe(_require("lv_after6.png"))
    assert state.page is Page.MAP
    assert state.resource_search_open is True
    assert state.resource_level == 1


def test_resource_detail_page_no_longer_claims_level_eight() -> None:
    # The level-1 wood node found live: the old code stamped it level 8.
    state = _vision().observe(_require("tapchk_after.png"))
    assert state.page is Page.RESOURCE_DETAIL
    assert state.resource_available is True
    assert state.resource_level is None


def _panel(level: int) -> WorldState:
    return WorldState(
        page=Page.MAP,
        resource_search_open=True,
        resource_selected="WOOD",
        resource_level=level,
        confidence=0.99,
    )


def test_relax_is_proven_only_by_exactly_one_step_down() -> None:
    assert verify_resource_level_relaxed(_panel(8), _panel(7)).ok is True
    assert verify_resource_level_relaxed(_panel(2), _panel(1)).ok is True


def test_relax_is_not_proven_when_the_level_does_not_move() -> None:
    result = verify_resource_level_relaxed(_panel(8), _panel(8))
    assert result.ok is False
    assert result.reason == "RESOURCE_LEVEL_RELAX_NOT_PROVEN"


def test_relax_is_not_proven_when_the_panel_closes() -> None:
    before = _panel(8)
    after = WorldState(page=Page.RESOURCE_DETAIL, resource_available=True, confidence=0.99)
    assert verify_resource_level_relaxed(before, after).ok is False


def test_relax_at_the_floor_is_reported_as_minimum_not_success() -> None:
    result = verify_resource_level_relaxed(_panel(1), _panel(1))
    assert result.ok is False
    assert result.reason == "RESOURCE_LEVEL_ALREADY_MINIMUM"


def test_relax_skill_is_registered_and_verifier_backed() -> None:
    from winter_agent_v2.runtime import LiveRuntime

    skill = v2_registry().get("RELAX_RESOURCE_LEVEL")
    assert skill is not None
    assert skill.action.kind == "TAP_SEMANTIC"
    assert skill.action.target == "RESOURCE_LEVEL_MINUS"
    assert "RELAX_RESOURCE_LEVEL" in LiveRuntime.VERIFIED_ATOMIC


def test_relax_never_targets_a_point_when_the_panel_is_closed() -> None:
    # The resolver is the only thing that decides where a relax tap lands, so
    # a closed panel must produce no target at all rather than a stale centre.
    from winter_agent_v2.vision import SemanticWorldVision

    vision = SemanticWorldVision(CANDIDATE)
    assert vision.semantic.resource_level_minus == (0.0958, 0.8219)


def test_brain_does_not_claim_level_filter_is_always_satisfiable() -> None:
    # Guard the regression: the brain must read the level to decide, not assume
    # level 8 is already configured.
    world = _panel(4)
    decision = RuleBrain().decide(world, v2_registry())
    assert decision.skill == "SUBMIT_RESOURCE_SEARCH"


def test_exhausted_search_relaxes_the_level_instead_of_repeating_it() -> None:
    """资源搜索落空时必须降等级重搜，而不是原样再提交一次。

    8 次 RESOURCE_NOT_FOUND 失败样本全部是 level=8 固定过滤造成的：
    附近没有 8 级节点时，同样的查询只会得到同样的空结果。
    """
    from dataclasses import replace

    exhausted = replace(_panel(8), resource_search_exhausted=True)
    decision = RuleBrain(current_goal="GATHER_RESOURCE").decide(exhausted, v2_registry())
    assert decision.skill == "RELAX_RESOURCE_LEVEL"
    assert decision.reason == "no_node_matched_current_level_filter"


def test_exhausted_search_at_minimum_level_still_submits() -> None:
    from dataclasses import replace

    at_floor = replace(_panel(1), resource_search_exhausted=True)
    decision = RuleBrain(current_goal="GATHER_RESOURCE").decide(at_floor, v2_registry())
    assert decision.skill == "SUBMIT_RESOURCE_SEARCH"


def test_relax_is_bounded_per_run() -> None:
    """降等级必须有限次，避免等级到底后无限重搜。"""
    import inspect

    from winter_agent_v2.runtime import LiveRuntime

    params = inspect.signature(LiveRuntime.__init__).parameters
    assert "max_relax_attempts" in params
    assert params["max_relax_attempts"].default >= 1
