"""The activity strip needs a crop, because whole-frame OCR loses its small labels.

Measured 2026-10-02 on the pinned production frame
``20261002_135741_630328_step_005_after_20261002T055825254675.png`` (role 1061663148),
same frame ``test_regular_event_activity_strip`` uses:

    whole-frame OCR -> 联盟总动员 only  (CANYON_CLASH absent)
    strip crop      -> 联盟总动员 0.999, 峡谷会战 0.941

and on the second role's frame
``20261002_040522_770261_step_015_after_20261001T200642498127.png``:

    strip crop      -> 联盟总动员 0.999, 峡谷会战 0.941, plus 30 / 兵 which map to nothing

This is the same class of miss the project already recorded in ``ocr_roi.py`` for the
gather panel's 22-px resource tabs, and it has the same fix: crop the text band before
recognition.  The engine normalises the candidate region, so cropping turns the miss into
a hit.  **Upscaling is not what fixes it** -- measured up=1 already reads 峡谷会战 at 0.941,
up=2 at 0.968, up=3 at 0.930.  The gain is inside the noise and the resampling costs a
resize per frame, so this reader does not upscale.  Recording that matters: the tempting
fix here is a magic upscale factor, and the measurement says it buys nothing.

Why the crop is not optional here but was for the grid: the grid's bars are ~30 px tall and
land at 0.995 on a whole frame, while the strip's labels are ~23 px and sit in a dense row
beside a large page clock.  Both facts come from the same frame's own token dump.
"""

from pathlib import Path

import pytest

from winter_agent_v2.event_calendar import (
    ACTIVITY_STRIP_ROI,
    read_regular_event_activity_strip,
    strip_tokens_from_crop,
)

FRAME_SIZE = (720, 1280)


class _Token:
    """The minimal token shape the reader touches, so no OCR engine is needed here."""

    def __init__(self, text, confidence, box):
        self.text = text
        self.confidence = confidence
        self.box = box


def _crop_token(label, y_centre_norm, x_centre_norm, confidence, *, frame=FRAME_SIZE):
    """A token positioned the way the strip draws it, in the frame's own pixels.

    ``y_centre_norm`` is measured against the WHOLE frame, because that is the coordinate
    system the reader's ROI and its callers both speak.
    """
    width, height = frame
    x = x_centre_norm * width
    y = y_centre_norm * height
    half_w, half_h = 60.0, 15.0
    return _Token(
        label, confidence,
        ((x - half_w, y - half_h), (x + half_w, y - half_h),
         (x + half_w, y + half_h), (x - half_w, y + half_h)),
    )


def strip_crop_tokens():
    """What the production engine returned from the strip crop, in frame coordinates.

    The 30 and 兵 are what the same crop really contained on the second role's frame; they
    are here to prove the reader reports neither.
    """
    return (
        _crop_token("30", 0.119, 0.201, 0.999),
        _crop_token("峡谷会战", 0.134, 0.470, 0.941),
        _crop_token("联盟总动员", 0.134, 0.742, 0.999),
        _crop_token("兵", 0.135, 0.900, 0.999),
    )


def whole_frame_tokens():
    """The same labels as whole-frame tokens, on the same frame's own geometry.

    This is the path ``classify`` can take: it never sees an image, only tokens.  It is
    weaker on purpose -- on the real frame 峡谷会战 is absent from this token set, which is
    the entire reason the crop exists -- and the reader must still recover 联盟总动员.
    """
    return (
        _crop_token("常规活动", 0.032, 0.226, 0.995),
        _crop_token("30", 0.119, 0.201, 0.998),
        _crop_token("联盟总动员", 0.133, 0.742, 0.999),
        _crop_token("2026-10-0213:58:28", 0.202, 0.501, 0.982),
    )


def test_roi_covers_the_measured_strip_band_and_nothing_else():
    """The ROI is a measured window: it must contain the strip and exclude the grid."""
    assert ACTIVITY_STRIP_ROI["y_norm"] < 0.119
    assert ACTIVITY_STRIP_ROI["y_norm"] + ACTIVITY_STRIP_ROI["h_norm"] > 0.135
    # The page clock (0.202) and the calendar's first date row (0.267) stay outside it, so
    # a clock digit can never be read as an activity and a grid bar never doubles as one.
    assert ACTIVITY_STRIP_ROI["y_norm"] + ACTIVITY_STRIP_ROI["h_norm"] < 0.202
    assert ACTIVITY_STRIP_ROI["x_norm"] == 0.0
    assert ACTIVITY_STRIP_ROI["w_norm"] == 1.0


def test_crop_tokens_are_reported_in_whole_frame_coordinates():
    """A crop token's y is relative to the crop; the goal layer speaks whole-frame.

    Getting this wrong would place every strip tap inside the calendar grid, which is a
    page this reader never measured.  The rebasing step and the classification step are
    separate on purpose -- one owns geometry, one owns meaning -- so this asserts the
    geometry through the classification that consumes it.
    """
    crop_top_px = round(ACTIVITY_STRIP_ROI["y_norm"] * FRAME_SIZE[1])
    crop_height_px = round(ACTIVITY_STRIP_ROI["h_norm"] * FRAME_SIZE[1])
    # A token the engine placed at the very top of the crop: crop-relative y is 0, so
    # whole-frame y must land at the crop's own top edge.
    top_of_crop = _Token(
        "联盟总动员", 0.999,
        ((0.0, 0.0), (100.0, 0.0), (100.0, 20.0), (0.0, 20.0)),
    )
    result = read_regular_event_activity_strip(
        (top_of_crop,), frame_size=FRAME_SIZE, crop_top_px=crop_top_px,
        crop_height_px=crop_height_px,
    )
    entry = result["entries"][0]
    # The token's own centre sits 10 px into the crop, so the reported tap is just below
    # the crop's top edge -- and, critically, nowhere near the calendar grid at 0.267.
    assert entry["tap_norm"][1] == pytest.approx(
        (crop_top_px + 10) / FRAME_SIZE[1], abs=1e-3
    )
    assert entry["tap_norm"][1] < 0.20


def test_both_measured_activities_are_recovered_from_the_crop():
    """The point of the crop: 峡谷会战 is invisible to a whole frame and present here."""
    crop_top = round(ACTIVITY_STRIP_ROI["y_norm"] * FRAME_SIZE[1])
    crop_height = round(ACTIVITY_STRIP_ROI["h_norm"] * FRAME_SIZE[1])
    result = read_regular_event_activity_strip(
        strip_crop_tokens(), frame_size=FRAME_SIZE,
        crop_top_px=crop_top, crop_height_px=crop_height,
    )
    ids = {entry["event_id"] for entry in result["entries"]}
    assert ids == {"CANYON_CLASH", "ALLIANCE_MOBILIZATION"}


def test_the_whole_frame_path_still_reads_what_it_can_see():
    """Without an image there is no crop, and the reader degrades honestly.

    It must not invent 峡谷会战 -- that label is simply not in these tokens -- and it must
    still report 联盟总动员, because that is genuinely visible without a crop.  A reader
    that returned nothing here would be the more dangerous failure: the whole-frame path is
    the one ``classify`` can actually take today.
    """
    result = read_regular_event_activity_strip(
        whole_frame_tokens(), frame_size=FRAME_SIZE, already_in_frame_coordinates=True
    )
    ids = {entry["event_id"] for entry in result["entries"]}
    assert ids == {"ALLIANCE_MOBILIZATION"}


def test_unregistered_labels_stay_unreported_even_at_full_confidence():
    """0.999 on 兵 and 30 is not evidence of anything; the registry is the filter."""
    crop_top = round(ACTIVITY_STRIP_ROI["y_norm"] * FRAME_SIZE[1])
    crop_height = round(ACTIVITY_STRIP_ROI["h_norm"] * FRAME_SIZE[1])
    result = read_regular_event_activity_strip(
        strip_crop_tokens(), frame_size=FRAME_SIZE,
        crop_top_px=crop_top, crop_height_px=crop_height,
    )
    assert {entry["display_name"] for entry in result["entries"]} == {"峡谷会战", "联盟总动员"}


def test_strip_rows_never_carry_a_window():
    """A strip advertises.  Promoting its label to a schedule is the failure this avoids."""
    crop_top = round(ACTIVITY_STRIP_ROI["y_norm"] * FRAME_SIZE[1])
    crop_height = round(ACTIVITY_STRIP_ROI["h_norm"] * FRAME_SIZE[1])
    result = read_regular_event_activity_strip(
        strip_crop_tokens(), frame_size=FRAME_SIZE,
        crop_top_px=crop_top, crop_height_px=crop_height,
    )
    for entry in result["entries"]:
        assert entry["start"] is None
        assert entry["end"] is None
        assert entry["preview_only"] is True


def test_an_empty_crop_is_an_honest_empty_answer():
    tokens = tuple(t for t in strip_crop_tokens() if t.text not in ("峡谷会战", "联盟总动员"))
    crop_top = round(ACTIVITY_STRIP_ROI["y_norm"] * FRAME_SIZE[1])
    crop_height = round(ACTIVITY_STRIP_ROI["h_norm"] * FRAME_SIZE[1])
    result = read_regular_event_activity_strip(
        tokens, frame_size=FRAME_SIZE, crop_top_px=crop_top, crop_height_px=crop_height,
    )
    assert result["recognized"] is False
    assert result["entries"] == []


def test_the_heading_is_required_where_the_frame_can_show_it():
    """A strip outside the 常规活动 screen proves nothing, even if the labels match.

    The heading is what makes this band the activity strip rather than some other row of
    Chinese text that happens to sit at the same height -- and the whole-frame path is the
    only one that can check it, because a crop excludes the heading by construction.
    """
    result = read_regular_event_activity_strip(
        tuple(t for t in whole_frame_tokens() if t.text != "常规活动"),
        frame_size=FRAME_SIZE, already_in_frame_coordinates=True,
    )
    assert result["recognized"] is False
    assert result["reason"] == "NO_UNAMBIGUOUS_LARGE_TOP_HEADING"


def test_real_frame_recovers_both_activities_when_ocr_is_available():
    """The live measurement, run against the pinned frame if it is still on disk.

    Skipped rather than faked when the frame is absent: a test that invents its own
    "evidence" is the exact habit that hid this defect.  What it asserts is the measured
    recall, not the code's opinion of itself.
    """
    frame = Path(
        r"C:\Users\xhw\.codex\worktrees\winter-prod-pinned\无尽冬日智能体\dataset\raw"
        r"\control_panel\runtime_auto\20261002_135741_630328"
        r"\20261002_135741_630328_step_005_after_20261002T055825254675.png"
    )
    if not frame.exists():
        pytest.skip("pinned production frame is not on this machine")
    from PIL import Image

    from winter_agent_v2.ocr import RapidOCRBackend

    with Image.open(frame) as source:
        image = source.convert("RGB")
    width, height = image.size
    top = round(ACTIVITY_STRIP_ROI["y_norm"] * height)
    bottom = round((ACTIVITY_STRIP_ROI["y_norm"] + ACTIVITY_STRIP_ROI["h_norm"]) * height)
    crop = image.crop((0, top, width, bottom))
    result = read_regular_event_activity_strip(
        RapidOCRBackend().recognize(crop), frame_size=(width, height),
        crop_top_px=top, crop_height_px=bottom - top,
    )
    ids = {entry["event_id"] for entry in result["entries"]}
    assert "ALLIANCE_MOBILIZATION" in ids
    assert "CANYON_CLASH" in ids
