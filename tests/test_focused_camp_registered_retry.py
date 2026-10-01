from pathlib import Path

import pytest

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


@pytest.mark.parametrize("frame,attempt,point,allowed", [
    ("fresh.png", 1, [0.4, 0.6], True),
    ("older.png", 1, [0.4, 0.6], False),
    ("fresh.png", 2, [0.4, 0.6], False),
    ("fresh.png", 1, [1.4, 0.6], False),
    ("fresh.png", 1, None, False),
])
def test_static_city_retry_consumes_only_its_verified_current_frame(frame, attempt, point, allowed):
    live = object.__new__(LiveRuntime)
    state = WorldState(page=Page.HOME, training={
        "navigation": "PANEL_CAMP_FOCUSED", "camp_focus_source": "REOBSERVED_STATIC_CITY_VIEW",
        "camp_focus_current_frame": frame, "camp_focus_retry_attempt": attempt,
        "camp_focus_tap_norm": point,
    })
    result = live._resolve_semantic_target("TRAINING_CAMP_BODY_FROM_FOCUS", state,
                                           frame_path=Path("fresh.png"))
    assert result == ((0.4, 0.6) if allowed else None)
