"""A page's identity is not the same question as what time it prints.

``read_event_detail`` answered only the second one for its whole life, and that is why the
activity strip could never discharge its debt.  Measured 2026-10-03 on the live frame
``dataset/truth_audit/live_ops/20261003T060634_登录好礼/drift_00.png`` (the 峡谷会战 detail
page, 720x1280), the 20 OCR tokens carry 常规活动, 峡谷会战, 最强王国, 参赛人数：30/30 three
times, [DIW]凌霄阁, tabs 1/2, 教学/奖励/商店/战绩/记录, and 战斗开始倒计时 07:53:19 -- and
**not one of the seven labels the predicate required**, no 前往, and no date range.  Every
branch answered False on a page the client was plainly showing.

Since ACTIVITY_STRIP advertises CANYON_CLASH and STATE_VS_STATE above the grid, those two
are never grid rows, so ``advertised_but_unread_activities`` never emptied,
``calendar_scan_due`` stayed True, and DISCOVER_EVENT_CALENDAR was re-selected 213 times
with a median gap of 0.4 minutes.

The fix accepts page identity -- a registered alias at heading scale, the same rule and the
same 0.03 threshold ``ocr.py`` uses to separate the active event from a tab that merely
navigates to it.  These tests pin the two directions, plus the line the fix must not cross.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_calendar as ec  # noqa: E402
from winter_agent_v2 import ocr as o  # noqa: E402

DETAIL_FRAME = ROOT / "dataset/truth_audit/live_ops/20261003T060634_登录好礼/drift_00.png"


class _Token:
    """The minimum an OCR token needs to answer the question, built from measured geometry."""

    def __init__(self, text: str, box: list[tuple[float, float]]) -> None:
        self.text = text
        self.box = box


def _token(text: str, x0: float, y0: float, x1: float, y1: float) -> _Token:
    return _Token(text, [(x0, y0), (x1, y1)])


@pytest.fixture(scope="module")
def detail_frame_reading():
    if not DETAIL_FRAME.exists():
        pytest.skip(f"the measured frame is not on disk: {DETAIL_FRAME}")
    from PIL import Image

    service = o.OCRService(o.RapidOCRBackend())
    width, height = Image.open(DETAIL_FRAME).size
    tokens = service.recognize(DETAIL_FRAME).tokens
    return ec.read_event_detail(tokens, event_label=None, frame_size=(width, height)), (width, height), tokens


def test_the_scale_is_one_criterion_shared_with_the_page_model():
    """One number, and it is the *scale* half -- the label half is deliberately not copied.

    ``ocr.py`` answers "is this page an event page" with scale **or** membership in
    ``EVENT_PAGE_TITLE_LABELS``, which is right for a boolean. Naming the page needs one
    activity, so only the scale half applies. Replaying the wider rule on the measured frame
    matches five labels, which is why copying it wholesale would be a bug rather than a
    completion.
    """
    import inspect
    import re

    source = inspect.getsource(o.OCRPageClassifier)
    assert str(ec.HEADING_SCALE) in source or f">= {ec.HEADING_SCALE}" in open(
        ROOT / "winter_agent_v2/ocr.py", encoding="utf-8").read(), (
        "ocr.py's Page.EVENT heading test and event_calendar's identity test must be the "
        "same number; if one moved, the page model and the detail reader would answer "
        "different questions about the same frame"
    )
    assert ec.HEADING_SCALE == 0.03
    # And the identity test must not consult that set, which is the half that cannot name.
    body = inspect.getsource(ec._heading_scale_activity)
    assert "EVENT_PAGE_TITLE_LABELS" not in body, (
        "the page-identity test must use heading scale alone. EVENT_PAGE_TITLE_LABELS "
        "contains 最强王国, which is a navigation tab on the measured frame at 0.0203, so "
        "adding that set would let a tab claim the page"
    )
    labels = re.search(
        r"EVENT_PAGE_TITLE_LABELS\s*=\s*frozenset\(\{([^}]*)\}\)", source)
    assert labels and "最强王国" in labels.group(1), (
        "if 最强王国 ever left EVENT_PAGE_TITLE_LABELS this test stops meaning what it says"
    )


def test_a_title_scale_registered_alias_identifies_the_page(detail_frame_reading):
    reading, frame_size, _ = detail_frame_reading
    assert reading.get("recognized") is True, (
        "the 峡谷会战 detail page was not recognised; measured tokens carried none of the "
        "seven time labels the old predicate required, which is the whole defect"
    )
    assert reading.get("event_id") == "CANYON_CLASH"
    assert reading.get("display_name") == "峡谷会战"
    assert frame_size == (720, 1280), "the measurement was taken at this size"


def test_identity_does_not_promote_a_countdown_into_a_battle_clock(detail_frame_reading):
    """The line this module has always held, and the reason the fix is safe.

    The countdown is preserved as a fact about the frame. It is not a time window: the
    client printed no date range here, so every window stays None. A preview must never
    become a battle clock, and identity is on the safe side of that line -- it says which
    activity the frame is, never when it runs.
    """
    reading, _, _ = detail_frame_reading
    assert reading.get("countdown_raw") == "07:53:19", (
        "the countdown is a real observation from this frame and should be kept verbatim"
    )
    for field in ("activity_open_start_raw", "activity_open_end_raw",
                  "battle_start_raw", "battle_end_raw",
                  "registration_start_raw", "registration_end_raw",
                  "preview_start_raw", "preview_end_raw"):
        assert reading.get(field) is None, (
            f"{field} was populated from a frame that printed no date range; identity must "
            "not become a schedule"
        )
    # The state is derived from the countdown, which is allowed: it says "not open yet",
    # not "opens at 07:53:19 on this date".
    assert reading.get("current_open_state") == "SCHEDULED_NOT_OPEN"


def test_a_small_tab_is_navigation_and_not_identity():
    """The half of the rule that keeps this from matching any registered label on screen.

    Measured on the same frame: 最强王国 sits at 26px (0.0203) while 峡谷会战 sits at 47px
    (0.0367). Both are registered activities and both are drawn, so presence alone would
    have picked the wrong one.
    """
    height = 1280
    rows = [
        (_token("最强王国", 300, 158, 371, 184), "最强王国"),    # 26px -> 0.0203
        (_token("峡谷会战", 102, 212, 148, 259), "峡谷会战"),    # 47px -> 0.0367
    ]
    assert ec._heading_scale_activity(rows, (720, height)) == "峡谷会战"


def test_no_frame_geometry_means_no_identity():
    """Without a frame height, "is this large" cannot be answered, so nothing is claimed."""
    rows = [(_token("峡谷会战", 0, 0, 40, 200), "峡谷会战")]
    assert ec._heading_scale_activity(rows, None) == ""
    assert ec._heading_scale_activity(rows, (720, 0)) == ""


def test_the_grid_is_not_mistaken_for_a_detail_page():
    """The direction that matters more: a false positive poisons the detail store.

    The negative direction is measured over real production frames by
    tools/detail_identity_negative_check.py -- 12 grid frames, 0 recognised. This asserts
    the shape of the reason rather than the count, so it keeps holding on a machine whose
    frames have been rotated away.
    """
    height = 1280
    grid_rows = [
        (_token("常规活动", 100, 20, 226, 62), "常规活动"),
        (_token("最强王国", 300, 158, 371, 184), "最强王国"),     # tab scale
        (_token("峡谷会战", 100, 160, 150, 186), "峡谷会战"),     # tab scale
        (_token("参赛人数：30/30", 160, 548, 293, 573), "参赛人数：30/30"),
    ]
    assert ec._heading_scale_activity(grid_rows, (720, height)) == ""


def test_the_live_negative_check_still_passes():
    """Run the measurement itself when the frames are still on disk."""
    import subprocess

    tool = ROOT / "tools/detail_identity_negative_check.py"
    if not tool.exists() or not DETAIL_FRAME.exists():
        pytest.skip("the live negative check and its frames are not both present")
    result = subprocess.run(
        [sys.executable, "-u", str(tool)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        "a real calendar-grid frame was mistaken for an event detail page:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "0 / " in result.stdout or "/ 0" in result.stdout
