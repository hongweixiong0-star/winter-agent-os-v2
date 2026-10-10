from winter_agent_v2.event_calendar import read_calendar_entry
from winter_agent_v2.ocr import OCRToken


def token(text, x, y, width=80, height=24, confidence=0.99):
    return OCRToken(
        text,
        confidence,
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height)),
    )


def test_calendar_entry_uses_the_unique_current_frame_label():
    entry = read_calendar_entry(
        [token("常规活动", 620, 420)], frame_size=(720, 1280)
    )

    assert entry is not None
    assert entry["visible"] is True
    assert entry["source"] == "CURRENT_FRAME_OCR"
    assert entry["tap_norm"] == [0.91667, 0.3375]


def test_calendar_entry_refuses_ambiguous_duplicate_labels():
    entry = read_calendar_entry(
        [token("常规活动", 620, 420), token("常规活动", 100, 200)],
        frame_size=(720, 1280),
    )

    assert entry is None


# ---------------------------------------------------------------------------------------------
# The preview card a grid tap opens.
#
# Measured 2026-10-10 on the live client: tapping the 除雪 row opens a card headed 除雪小分队
# reading "2026-10-13 00:00 -2026-10-15 24:00" and "距离开始：2天15:09:21", with no 活动时间
# label, no 前往 and no registered name.  All three previous predicates answered False, so the
# frame the tap had just opened produced no `calendar_detail` at all -- the verifier could never
# pass, the row was never credited, and DISCOVER_EVENT_CALENDAR was re-selected every few
# minutes (26 of the last 55 failures).
# ---------------------------------------------------------------------------------------------

from winter_agent_v2.event_calendar import read_event_detail  # noqa: E402


def _card_tokens(*, title=True, date_range=True, countdown=True):
    tokens = [token("常规活动", 300, 40, 120, 30)]
    if title:
        tokens.append(token("除雪小分队", 300, 490, 120, 30))
    if date_range:
        tokens.append(token("2026-10-13 00:00 -2026-10-15 24:00", 150, 550, 420, 26))
    if countdown:
        tokens.append(token("距离开始：2天15:09:21", 250, 600, 220, 26))
    return tokens


def _recognised(**kwargs) -> dict:
    return read_event_detail(_card_tokens(**kwargs), event_label=None, frame_size=(720, 1280))


def test_a_preview_card_printing_its_own_window_and_countdown_is_a_detail():
    detail = _recognised()
    assert detail["recognized"] is True
    # The name comes from the geometry -- the title immediately above the printed range -- and
    # not from the recognition predicate, which must never be used for naming.
    assert detail["display_name"] == "除雪小分队"
    assert detail["preview_start_raw"] == "2026-10-13 00:00"
    assert detail["preview_end_raw"] == "2026-10-15 24:00"


def test_a_countdown_without_a_date_range_is_not_a_detail():
    """Both halves are required: a window alone is a preview and never became a clock here."""
    assert _recognised(date_range=False)["recognized"] is False


def test_a_date_range_without_a_countdown_is_not_a_detail():
    assert _recognised(countdown=False)["recognized"] is False


def test_a_bare_window_naming_no_activity_is_not_a_detail():
    """A stray range and countdown must not promote a frame that names nothing."""
    assert _recognised(title=False)["recognized"] is False
