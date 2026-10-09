"""A tab parked past the visible strip window needs the swipe that did not exist.

Measured 2026-10-10 on dataset/evidence/bear_baseline_newaccount_20260927T100038Z:
p11_step_1.png draws 巨熊行动 at x=636 of 720 and the production reader returns it as
"熊行动" with a 50px box, against 69-117px for its visible neighbours -- the label is
clipped by the right edge.  Only the towards-start swipe existed, so that tab could not be
brought in, and the one probe that did reach the page walked the strip in 60px nudges.

These tests pin the two halves that had to change: the strip now offers the reversed pair
of points, and the runtime flips direction when a swipe does not move the strip.
"""

from types import SimpleNamespace

from winter_agent_v2.event_calendar import read_regular_event_hub
from winter_agent_v2.ocr import OCRToken
from winter_agent_v2.runtime import LiveRuntime


def token(label, x, y, w=100, h=24, confidence=0.99):
    return OCRToken(label, confidence, ((x, y), (x + w, y), (x + w, y + h), (x, y + h)))


def hub_tokens(*, calendar=False, dx=0):
    # Same geometry as tests/test_regular_event_hub.py, measured from the real frame; the
    # body rows are what let read_regular_event_hub recognize the page at all.
    rows = [token("常规活动", 95, 22, 135, 38),
            token("兵工厂争夺战", 493 + dx, 159, 134, 23),
            token("联盟总动员", 39, 211, 211, 48),
            token("积分：2,550", 526, 273, 128, 27),
            token("可接次数：8/13", 57, 533, 177, 29)]
    rows.append(token("日历" if calendar else "峡谷会战", 115 + dx, 159, 100, 23))
    return rows


def hub(signature):
    return SimpleNamespace(events={"regular_events_hub": {"tab_signature": signature}})


def a_runtime_without_history():
    """The two helpers only touch attributes, so they need no full LiveRuntime."""
    return object.__new__(LiveRuntime)


# ---------------------------------------------------------------- geometry


def test_the_two_directions_are_the_same_two_points_drawn_opposite_ways():
    result = read_regular_event_hub(hub_tokens(), frame_size=(720, 1280))
    assert result["recognized"]
    start = result["scroll_to_start_norm"]
    end = result["scroll_to_end_norm"]
    assert start is not None and end is not None
    # Same two measured points, same row, opposite order -- not a new coordinate.
    assert end == [start[2], start[3], start[0], start[1]]
    assert start[0] < start[2] and end[0] > end[2]
    assert start[1] == end[1] == start[3] == end[3]


def test_a_visible_calendar_tab_still_authorizes_neither_direction():
    result = read_regular_event_hub(hub_tokens(calendar=True), frame_size=(720, 1280))
    assert result["calendar_tab_visible"]
    assert result["scroll_to_start_norm"] is None
    assert result["scroll_to_end_norm"] is None


# ---------------------------------------------------------------- direction choice


def test_the_first_attempt_of_a_fresh_run_still_walks_towards_the_start():
    runtime = a_runtime_without_history()
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_start_norm"


def test_a_swipe_that_did_not_move_the_strip_flips_the_direction():
    runtime = a_runtime_without_history()
    # First attempt: there is no earlier frame to compare against yet.
    runtime._calendar_tab_resolved_swipe = "scroll_to_start_norm"
    runtime._note_regular_event_strip_swipe(hub("S1"))
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_start_norm"
    # Second frame, same signature: the strip did not move, so try the other way.
    runtime._calendar_tab_resolved_swipe = "scroll_to_start_norm"
    runtime._note_regular_event_strip_swipe(hub("S1"))
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_end_norm"


def test_a_swipe_that_moved_the_strip_keeps_the_direction_that_moved_it():
    runtime = a_runtime_without_history()
    runtime._calendar_tab_resolved_swipe = "scroll_to_end_norm"
    runtime._note_regular_event_strip_swipe(hub("S1"))
    # The signature changed, so the strip scrolled: towards-end is the useful direction.
    runtime._calendar_tab_resolved_swipe = "scroll_to_end_norm"
    runtime._note_regular_event_strip_swipe(hub("S2"))
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_end_norm"


def test_neither_direction_can_be_latched_in_when_nothing_moves():
    runtime = a_runtime_without_history()
    runtime._calendar_tab_resolved_swipe = "scroll_to_start_norm"
    runtime._note_regular_event_strip_swipe(hub("S1"))
    runtime._calendar_tab_resolved_swipe = "scroll_to_start_norm"
    runtime._note_regular_event_strip_swipe(hub("S1"))
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_end_norm"
    # A towards-end attempt that also moves nothing flips back rather than sticking.
    runtime._calendar_tab_resolved_swipe = "scroll_to_end_norm"
    runtime._note_regular_event_strip_swipe(hub("S1"))
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_start_norm"


def test_a_frame_without_a_signature_does_not_flip_the_direction():
    """No hub means no measurement, and a reading that was never made is not evidence."""
    runtime = a_runtime_without_history()
    runtime._calendar_tab_resolved_swipe = "scroll_to_start_norm"
    runtime._note_regular_event_strip_swipe(SimpleNamespace(events={}))
    runtime._calendar_tab_resolved_swipe = "scroll_to_start_norm"
    runtime._note_regular_event_strip_swipe(SimpleNamespace(events={}))
    assert runtime._regular_event_strip_swipe_key() == "scroll_to_start_norm"
