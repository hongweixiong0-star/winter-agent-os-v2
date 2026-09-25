from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.entry_badges import PRESENT, UNKNOWN, read_entry_badges
from winter_agent_v2.goal_library import GoalLibrary, GoalStatus, route_for
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.rally import RallyRowState, RallyTarget
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_bear_rally_list_open
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"


def test_alliance_home_emits_read_only_discovery_goal_with_unknown_window():
    world = WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "HOME", "bear_entry_visible": True},
        red_dots={"BTN_ALLIANCE_WAR": {"state": PRESENT}},
    )

    goal = next(
        goal for goal in GoalLibrary().discover(world)
        if goal.goal_id == "DISCOVER_BEAR_RALLY_LIST"
    )

    assert route_for(goal.goal_id) == "ALLIANCE"
    assert goal.status is GoalStatus.READY
    assert goal.available_skills == ("OPEN_BEAR_RALLY_LIST",)
    assert goal.evidence["window"] == "UNKNOWN"
    assert goal.evidence["participation_allowed"] is False


def test_bear_discovery_route_uses_only_the_current_alliance_war_entry():
    brain = RuleBrain(current_goal="ALLIANCE")
    brain.goal_id = "DISCOVER_BEAR_RALLY_LIST"
    world = WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "HOME", "bear_entry_visible": True},
        red_dots={"BTN_ALLIANCE_WAR": {"state": PRESENT}},
    )

    decision = brain.decide(world, v2_registry())

    assert decision.skill == "OPEN_BEAR_RALLY_LIST"
    assert decision.expected_result == "bear_rally_list_observed"


def test_alliance_war_badge_is_unknown_outside_its_home_section():
    record = read_entry_badges(
        None, "ALLIANCE", section="RALLY_LIST"
    )["BTN_ALLIANCE_WAR"]
    assert record.state == UNKNOWN


def test_rally_list_verifier_requires_the_actual_destination():
    before = WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "HOME", "bear_entry_visible": True},
    )
    after = WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "RALLY_LIST", "rally_list_visible": True},
    )

    assert verify_bear_rally_list_open(before, after).ok
    assert not verify_bear_rally_list_open(
        before, WorldState(page=Page.ALLIANCE, alliance={"section": "GIFTS"})
    ).ok


def test_semantic_vision_distinguishes_alliance_home_and_rally_list(monkeypatch):
    def observe_with_matches(matches):
        vision = SemanticWorldVision(MANIFEST)
        vision.semantic.begin_frame = lambda _path: None
        vision.semantic.find = lambda _path, name: object() if name in matches else None
        return vision.observe(Path("unused.png"))

    rally_list = observe_with_matches({"TAB_RALLY_LIST"})
    assert rally_list.page is Page.ALLIANCE
    assert rally_list.alliance == {"section": "RALLY_LIST", "rally_list_visible": True}

    alliance_home = observe_with_matches({"PAGE_ALLIANCE", "BTN_ALLIANCE_WAR"})
    assert alliance_home.page is Page.ALLIANCE
    assert alliance_home.alliance == {"section": "HOME", "bear_entry_visible": True}


def test_hybrid_observation_attaches_current_rally_rows(monkeypatch):
    from winter_agent_v2 import rally
    from winter_agent_v2.ocr import HybridVision

    rows = (
        SimpleNamespace(
            row_index=0, target_text="等级1变异巨熊", target_type=RallyTarget.BEAR,
            leader="leader-a", remaining_seconds=45, capacity_used=8, capacity_max=15,
            joinable=True, join_norm=(0.8, 0.4), join_box_norm=(0.75, 0.38, 0.85, 0.42),
            state=RallyRowState.JOINABLE,
        ),
        SimpleNamespace(
            row_index=1, target_text="等级1变异巨熊", target_type=RallyTarget.BEAR,
            leader="leader-b", remaining_seconds=61, capacity_used=10, capacity_max=15,
            joinable=True, join_norm=(0.8, 0.7), join_box_norm=(0.75, 0.68, 0.85, 0.72),
            state=RallyRowState.JOINABLE,
        ),
    )
    reading = SimpleNamespace(
        rows=rows, container_norm=(0.1, 0.2, 0.9, 0.9),
        frame_size=(720, 1280), evidence={"container_source": "row_headers_and_footer"},
    )
    monkeypatch.setattr(rally, "read_rally_list", lambda *_args, **_kwargs: reading)

    vision = HybridVision.__new__(HybridVision)
    vision.ocr = object()
    before = WorldState(page=Page.ALLIANCE, alliance={"section": "RALLY_LIST"})
    observed = vision._read_rally_list_state(Path("unused.png"), before)

    assert observed.alliance["rally_list_visible"] is True
    assert len(observed.rally["rows"]) == 2
    assert observed.rally["rows"][0]["join_norm"] == (0.8, 0.4)
    assert observed.events["bear"]["source"] == "LIVE_CLIENT_RALLY_ROW"
    assert observed.events["bear"]["remaining_seconds"] == 45
