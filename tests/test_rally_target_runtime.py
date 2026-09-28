from __future__ import annotations

from types import SimpleNamespace

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.rally import (
    BearRole,
    RallyRow,
    RallyRowState,
    RallyRowReading,
    RallyListReading,
    RallyTarget,
    _bear_target_in,
    _rally_target_in,
    choose_rally_operation,
    fastest_joinable_for,
    live_rally_join_point,
    normalize_rally_target,
    rally_target_for_goal,
    select_join_candidates,
)
from winter_agent_v2.executor_router import ExecutorRouter
from winter_agent_v2.runtime import LiveRuntime, _verify_rally_action


def _live_rally_frame() -> WorldState:
    return WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "RALLY_LIST", "rally_list_visible": True},
        rally={
            "source": "LIVE_CLIENT_RALLY_LIST",
            "rows": [
                {"target_type": "BEAR", "state": "JOINABLE", "join_norm": [0.81, 0.25],
                 "remaining_seconds": 12, "capacity_used": 1, "capacity_max": 15},
                {"target_type": "POLAR_TERROR", "state": "JOINABLE", "join_norm": [0.72, 0.43],
                 "remaining_seconds": 30, "capacity_used": 2, "capacity_max": 15},
                {"target_type": "ICEFIELD_BEAST", "state": "JOINABLE", "join_norm": [0.76, 0.51],
                 "remaining_seconds": 10, "capacity_used": 4, "capacity_max": 15},
            ],
        },
    )


def test_icefield_beast_is_not_classified_as_bear():
    assert _rally_target_in("等级1变异巨熊") == (RallyTarget.BEAR, "变异巨熊")
    assert _rally_target_in("冰原巨兽") == (RallyTarget.ICEFIELD_BEAST, "冰原巨兽")
    assert _bear_target_in("冰原巨兽") is None
    assert normalize_rally_target("POLAR_TERROR") is RallyTarget.ICEFIELD_BEAST
    assert normalize_rally_target(RallyTarget.POLAR_TERROR) is RallyTarget.ICEFIELD_BEAST


def test_goal_target_is_explicit_and_legacy_target_names_are_accepted():
    assert rally_target_for_goal("PARTICIPATE_BEAR") is RallyTarget.BEAR
    assert rally_target_for_goal("DISCOVER_BEAR_RALLY_LIST") is RallyTarget.BEAR
    assert rally_target_for_goal("PARTICIPATE_ICEFIELD_BEAST") is RallyTarget.ICEFIELD_BEAST
    assert rally_target_for_goal("SOME_EVENT", {"rally_target": "POLAR_TERROR"}) is RallyTarget.ICEFIELD_BEAST
    assert rally_target_for_goal("SOME_EVENT", {"rally_target": "UNREADABLE"}) is None
    assert rally_target_for_goal("SOME_EVENT", skill_id="JOIN_RALLY") is None


def test_join_policy_only_uses_idle_capacity_for_the_requested_target():
    bear = RallyRow(RallyTarget.BEAR, "bear-leader", RallyRowState.JOINABLE, 8, 1, 15)
    icefield = RallyRow(RallyTarget.ICEFIELD_BEAST, "ice-leader", RallyRowState.JOINABLE, 4, 1, 15)
    world = WorldState(normal_idle_slots=1)

    assert choose_rally_operation(
        world, BearRole.JOINER, (bear, icefield), target=RallyTarget.ICEFIELD_BEAST
    ) == "JOIN_RALLY"
    assert fastest_joinable_for((bear, icefield), "ICEFIELD_BEAST") is icefield
    assert choose_rally_operation(
        world, BearRole.JOINER, (bear,), target=RallyTarget.ICEFIELD_BEAST
    ) is None
    assert choose_rally_operation(
        world, BearRole.JOINER, (icefield,), target=RallyTarget.UNKNOWN
    ) is None


def test_current_frame_resolver_selects_only_the_requested_target():
    frame = _live_rally_frame()
    assert live_rally_join_point(frame, RallyTarget.BEAR) == (0.81, 0.25)
    assert live_rally_join_point(frame, RallyTarget.ICEFIELD_BEAST) == (0.76, 0.51)
    assert live_rally_join_point(frame, RallyTarget.UNKNOWN) is None

    runtime = LiveRuntime.__new__(LiveRuntime)
    assert runtime._resolve_semantic_target(
        "RALLY_ROW_JOIN_BUTTON", frame, rally_target=RallyTarget.ICEFIELD_BEAST
    ) == (0.76, 0.51)


def test_list_selection_is_scoped_to_the_requested_target():
    def row(index: int, target: RallyTarget, timer: int) -> RallyRowReading:
        return RallyRowReading(
            row_index=index,
            header_y_norm=0.2 + index * 0.2,
            band_norm=(0.18 + index * 0.2, 0.36 + index * 0.2),
            target_text=target.value,
            target_type=target,
            leader=f"leader-{index}",
            remaining_seconds=timer,
            capacity_used=2,
            capacity_max=15,
            join_norm=(0.8, 0.3 + index * 0.2),
            join_box_norm=(0.77, 0.27 + index * 0.2, 0.84, 0.33 + index * 0.2),
            state=RallyRowState.JOINABLE,
            row_id=f"row-{index}",
            join_available=True,
            timer=timer,
            join_button_bbox=(0.77, 0.27 + index * 0.2, 0.84, 0.33 + index * 0.2),
        )

    reading = RallyListReading(
        rows=(row(0, RallyTarget.BEAR, 6), row(1, RallyTarget.ICEFIELD_BEAST, 12),
              row(2, RallyTarget.ICEFIELD_BEAST, 3)),
        container_norm=None,
        frame_size=(720, 1280),
    )

    assert [item.row_index for item in select_join_candidates(reading, "ICEFIELD_BEAST")] == [2, 1]
    assert reading.best_joinable_for("ICEFIELD_BEAST").row_index == 2
    assert reading.best_joinable().row_index == 0


def test_maa_list_dynamic_resolver_uses_bound_goal_target(monkeypatch):
    import numpy as np

    bear_row = SimpleNamespace(join_norm=(0.81, 0.25))
    icefield_row = SimpleNamespace(join_norm=(0.76, 0.51))
    reading = SimpleNamespace(
        has_rows=True,
        best_joinable_for=lambda target: (
            icefield_row if normalize_rally_target(target) is RallyTarget.ICEFIELD_BEAST else bear_row
        ),
    )

    monkeypatch.setattr("winter_agent_v2.rally.read_rally_list_image", lambda frame, tokens: reading)

    class FakeRapidOCR:
        def recognize(self, image):
            return ()

    monkeypatch.setattr("winter_agent_v2.ocr.RapidOCRBackend", FakeRapidOCR)

    class FakeAdapter:
        last_frame = np.zeros((32, 32, 3), dtype=np.uint8)

        def frame(self):
            return self.last_frame

    router = ExecutorRouter.__new__(ExecutorRouter)
    router.maa_adapter = FakeAdapter()
    router.routing = SimpleNamespace(recognition_node=lambda _skill, _semantic: {
        "kind": "LIST_DYNAMIC", "reader": "rally_list", "field": "join_button",
    })
    router.rally_target = RallyTarget.ICEFIELD_BEAST
    router.adb_resolver = None
    router.last_outcome = None
    router.last_recognition_error = None

    assert router.maa_resolver("RALLY_ROW_JOIN_BUTTON", "JOIN_RALLY") == (0.76, 0.51)


def test_target_bound_verifier_accepts_alias_but_rejects_other_rally():
    before = WorldState(march_used=2)
    icefield_after = WorldState(
        march_used=3,
        alliance={"rally": {"target_type": "POLAR_TERROR", "member_state": "JOINED"}},
    )
    bear_after = WorldState(
        march_used=3,
        alliance={"rally": {"target_type": "BEAR", "member_state": "JOINED"}},
    )

    assert _verify_rally_action("JOIN_RALLY", before, icefield_after, "ICEFIELD_BEAST").ok
    assert not _verify_rally_action("JOIN_RALLY", before, bear_after, "ICEFIELD_BEAST").ok
    assert not _verify_rally_action("JOIN_RALLY", before, icefield_after, "UNKNOWN").ok
