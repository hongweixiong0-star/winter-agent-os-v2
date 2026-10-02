"""The activity strip above the calendar grid is a discovery source, not decoration.

Measured 2026-10-02, pinned production frame
``20261002_135741_630328_step_005_after_20261002T055825254675.png`` (role 1061663148),
re-read offline through the production OCR engine and the production hub reader
(``tools/_wb1002_27_hub_probe.py``).  The frame is the ``常规活动`` **calendar grid**, and it
carries two distinct regions:

* the calendar grid -- 6 event bars, read at confidence 0.995, ``details_observed=True``
  on every one of them, with real detail readings behind them;
* an **activity strip above the grid** -- ``联盟总动员`` at ``y=0.133``, confidence
  **0.999**, plus ``峡谷会战`` and a truncated ``兵`` further right.

``ALLIANCE_MOBILIZATION``, ``CANYON_CLASH`` and ``ARMAMENT_FACTORY_EVENT`` are registered
activities that live **only** on that strip: they never appear as a grid row, so
``_append_scheduled_activities`` binds them ``calendar_observation=None`` forever and
``observation_ticket`` prices them at the floor on evidence that does not exist.  Measured
on the live board: 6 of 20 ``SCHEDULED_*`` goals carry a calendar row, and the 14 that do
not are exactly the 14 registered activities absent from the grid.

The token was **read and then dropped**: ``read_regular_event_hub`` looks for an event
*detail* page (a title plus body markers such as 积分/奖励), which this frame is not, so it
answers ``recognized=False`` and the 0.999-confidence label never reaches any consumer.
``event_goal.event_id_for_label`` already resolves all ten of these labels correctly
(verified offline), so the mapping exists and is unused.

These tests pin the reader on the frame's own measured geometry.  They are deliberately
built from the frame, not from a plausible-looking synthetic layout: a fixture that merely
looked like a grid would pass against the old code.
"""

from winter_agent_v2 import event_goal
from winter_agent_v2.event_calendar import read_regular_event_activity_strip
from winter_agent_v2.ocr import OCRToken

FRAME_SIZE = (720, 1280)


def _token(label, x, y, w, h, confidence):
    return OCRToken(label, confidence, ((x, y), (x + w, y), (x + w, y + h), (x, y + h)))


def calendar_grid_frame_tokens():
    """Every OCR token the production engine returned on the pinned frame, verbatim.

    Coordinates are the frame's own pixels; confidence is the engine's own score.
    """
    return [
        # -- the two regions' shared heading
        _token("常规活动", 123, 22, 195, 38, 0.995),
        # -- the activity strip ABOVE the grid.  These three are the whole point.
        _token("30", 111, 104, 60, 40, 0.998),          # the calendar tab's own day badge
        _token("联盟总动员", 502, 103, 213, 30, 0.999),
        # -- the page clock, which is NOT a strip member
        _token("2026-10-0213:58:28", 241, 233, 268, 26, 0.982),
        # -- the calendar grid's own date row and event bars
        _token("星期三", 20, 331, 86, 28, 0.999),
        _token("09/30", 25, 361, 92, 26, 0.997),
        _token("星期五", 219, 332, 87, 28, 1.000),
        _token("10/02", 221, 361, 93, 26, 0.998),
        _token("1冰封的宝藏", 48, 407, 110, 26, 0.943),
        _token("寻宝特训", 452, 472, 111, 36, 0.998),
        _token("冰封的宝藏", 452, 587, 111, 31, 0.997),
        _token("秘宝商行", 452, 704, 111, 33, 0.999),
        _token("辉煌盛世庆典", 28, 784, 145, 27, 0.995),
        _token("庆典对对碰", 440, 848, 112, 30, 0.996),
        _token("狮舞盛会", 438, 968, 112, 33, 0.999),
        _token("盛会商铺", 440, 1082, 111, 33, 0.998),
        _token("所有活动的最终开放情况以游戏内为准", 70, 1214, 580, 26, 0.997),
    ]


def test_strip_reads_the_labelled_activity_the_grid_omits():
    """The frame's 0.999-confidence strip label becomes a registered event id."""
    result = read_regular_event_activity_strip(
        calendar_grid_frame_tokens(), frame_size=FRAME_SIZE
    )
    assert result["recognized"] is True
    assert result["kind"] == "ACTIVITY_STRIP"
    ids = [entry["event_id"] for entry in result["entries"]]
    # 联盟总动员 was read at 0.999 and mapped to a registered activity by the existing
    # resolver; before this reader existed the label reached no consumer at all.
    assert "ALLIANCE_MOBILIZATION" in ids
    entry = next(e for e in result["entries"] if e["event_id"] == "ALLIANCE_MOBILIZATION")
    assert entry["display_name"] == "联盟总动员"
    # Geometry is normalized against the frame, and it is the strip's own -- not a stored one.
    assert 0.6 < entry["tap_norm"][0] < 0.9
    assert 0.08 < entry["tap_norm"][1] < 0.18
    assert entry["source"] == "CURRENT_FRAME_OCR"


def test_strip_does_not_invent_rows_out_of_the_calendar_grid():
    """A grid bar is a grid bar.  Reporting it as a strip member would double-count it."""
    result = read_regular_event_activity_strip(
        calendar_grid_frame_tokens(), frame_size=FRAME_SIZE
    )
    names = {entry["display_name"] for entry in result["entries"]}
    for grid_only in ("寻宝特训", "冰封的宝藏", "秘宝商行", "庆典对对碰", "狮舞盛会", "盛会商铺"):
        assert grid_only not in names


def test_strip_rejects_a_frame_with_no_strip_at_all():
    """No heading means no page identity, and an empty answer is the honest one."""
    tokens = [t for t in calendar_grid_frame_tokens() if t.text not in ("常规活动", "联盟总动员", "30")]
    result = read_regular_event_activity_strip(tokens, frame_size=FRAME_SIZE)
    assert result["recognized"] is False
    assert result["entries"] == []


def test_strip_ignores_the_page_clock_and_the_day_badge():
    """``2026-10-02 13:58:28`` and the tab's ``30`` are not activities, and neither maps."""
    result = read_regular_event_activity_strip(
        calendar_grid_frame_tokens(), frame_size=FRAME_SIZE
    )
    labels = {entry["display_name"] for entry in result["entries"]}
    assert "2026-10-0213:58:28" not in labels
    assert "30" not in labels
    # The resolver is the reason this is a filter and not a guess: an unmapped label would
    # otherwise become a fabricated event id.
    assert event_goal.event_id_for_label("30") is None


def test_every_strip_entry_resolves_to_a_registered_activity():
    """A strip row may only be reported under an id the registry already knows.

    This is the guard that keeps the reader honest: the strip proves *that an activity is
    advertised*, never *when it runs* or *what it costs*.
    """
    result = read_regular_event_activity_strip(
        calendar_grid_frame_tokens(), frame_size=FRAME_SIZE
    )
    registered = {activity.event_id for activity in event_goal.known_activities()}
    for entry in result["entries"]:
        assert entry["event_id"] in registered
        # A preview carries no clock.  The window stays the registry's to answer.
        assert entry.get("start") is None and entry.get("end") is None
