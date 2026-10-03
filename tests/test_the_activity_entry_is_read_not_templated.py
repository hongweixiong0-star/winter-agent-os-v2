"""The activity entry is a moving label, so its position is read, never templated.

Measured 2026-10-03, the frame that stopped production: ``events["calendar_entry"]`` carried
``tap_norm=[0.925, 0.14883]`` at confidence 0.998 with ``visible: true``, the action was
``TAP_SEMANTIC / REGULAR_EVENT_ENTRY``, and the step still failed
``SEMANTIC_TARGET_NOT_VERIFIED`` -> ``SAFE_STOP`` with ``stop_category=CAPABILITY_GAP``.

The cause was not recognition.  ``ocr.classify`` had already read the 常规活动 label off that
exact frame.  The cause was that nothing consumed the reading: every ``calendar_entry`` consumer
sat on the should-we-go side (``brain``, ``goal_library``) and none on the where-to-tap side, so
the V2 resolver had no branch for the semantic and the run depended entirely on a fixed template
ROI (``[632,101,67,84]``, cropped from one 2026-09-25 frame, ``"validation": "NONE"``).  That
template matched 567 times and missed 19, and because a miss here is terminal the misses read as
a capability gap rather than as a stale box.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.models import Page, WorldState  # noqa: E402


def _runtime():
    """``_resolve_semantic_target`` is lifted onto the class precisely so it is reachable
    without a device (runtime.py:4728); nothing here touches the client."""
    from winter_agent_v2.runtime import LiveRuntime

    return LiveRuntime.__new__(LiveRuntime)


def _resolve(runtime, world, semantic="REGULAR_EVENT_ENTRY"):
    return runtime._resolve_semantic_target(semantic, world, frame_path=None)


def _home_with(entry):
    return WorldState(page=Page.HOME, confidence=0.99,
                      events={"calendar_entry": entry} if entry is not None else {})


def _live_entry():
    """Exactly the reading the stopping frame carried."""
    return {
        "visible": True,
        "tap_norm": [0.925, 0.14883],
        "source": "CURRENT_FRAME_OCR",
        "confidence": 0.9983089715242386,
    }


class TheMovingLabelIsReadOffTheFrameTests:
    def test_the_frame_that_stopped_production_now_resolves(self):
        """The regression, stated as a fact about a real frame rather than a fixture."""
        point = _resolve(_runtime(), _home_with(_live_entry()))
        assert point is not None, (
            "the stopping frame had a current-frame OCR box with confidence 0.998; "
            "refusing to resolve it is what took production down"
        )
        assert point[0] == pytest.approx(0.925)
        assert point[1] == pytest.approx(0.14883)

    def test_the_map_page_resolves_the_same_way(self):
        """OPEN_EVENT_CALENDAR_FROM_MAP declares the same semantic from another source page."""
        world = WorldState(page=Page.MAP, confidence=0.99,
                           events={"calendar_entry": _live_entry()})
        assert _resolve(_runtime(), world) == (pytest.approx(0.925), pytest.approx(0.14883))

    def test_a_label_that_moved_is_followed_rather_than_templated(self):
        """The label sits at a different height on different frames; both must be honoured."""
        runtime = _runtime()
        high = dict(_live_entry(), tap_norm=[0.92431, 0.0812])
        low = dict(_live_entry(), tap_norm=[0.92569, 0.2174])
        assert _resolve(runtime, _home_with(high))[1] == pytest.approx(0.0812)
        assert _resolve(runtime, _home_with(low))[1] == pytest.approx(0.2174)

    def test_a_frame_that_drew_no_label_still_refuses(self):
        """None is the honest answer when the client did not draw the label."""
        assert _resolve(_runtime(), _home_with(None)) is None
        assert _resolve(_runtime(), _home_with({"visible": False})) is None

    def test_a_reading_that_is_not_from_this_frame_is_refused(self):
        """A cached or invented box must never become a tap target."""
        cached = dict(_live_entry(), source="CACHED_TEMPLATE")
        assert _resolve(_runtime(), _home_with(cached)) is None

    def test_a_malformed_box_is_refused_rather_than_clamped(self):
        for bad in ([0.925], [], "0.925,0.148", None, [1.4, 0.2], [-0.1, 0.2], ["a", "b"]):
            assert _resolve(_runtime(), _home_with(dict(_live_entry(), tap_norm=bad))) is None, bad

    def test_another_page_never_becomes_an_activity_entry(self):
        """A rail label is not Page.EVENT identity, and a page that is not HOME/MAP has no entry."""
        for page in (Page.EVENT, Page.INTEL, Page.TRAINING, Page.POPUP, Page.MARCH):
            world = WorldState(page=page, confidence=0.99, events={"calendar_entry": _live_entry()})
            assert _resolve(_runtime(), world) is None, page

    def test_the_declaring_skills_are_the_ones_now_answered(self):
        """The two skills that declare this semantic are the two that used to depend on a template."""
        from winter_agent_v2.skills import v2_registry

        registry = v2_registry()
        declaring = []
        for skill_id in ("OPEN_EVENT_CALENDAR_FROM_HOME", "OPEN_EVENT_CALENDAR_FROM_MAP"):
            skill = registry.get(skill_id)
            assert skill is not None, skill_id
            assert skill.action is not None and skill.action.target == "REGULAR_EVENT_ENTRY"
            declaring.append(skill_id)
        assert len(declaring) == 2

    def test_other_semantics_are_untouched_by_this_branch(self):
        """A branch that matched too much would silently move other controls."""
        assert _resolve(_runtime(), _home_with(_live_entry()), "EVENT_CALENDAR_TAB") is None
        assert _resolve(_runtime(), _home_with(_live_entry()), "BTN_OPEN_HOME") is None
