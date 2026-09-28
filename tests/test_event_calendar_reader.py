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
