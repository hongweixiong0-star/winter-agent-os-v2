"""The open Bear window, read as a duration so no timezone has to be assumed.

Measured 2026-10-10 on dataset/raw/bear_live_20260909/bear_trap_detail.png: the map's popup
draws 等级1变异巨熊 at 0.999 and 剩余时间：00:13:54 at 0.930, over a map that also draws
00:00:02, 00:00:07 and 06:04:48.  bear_trap_loaded.png is the same popup a second earlier
with the clock misread as 剩余时间：00：142.

bear_phase(None, None, N) answers ACTIVE for any N > 0, and goal_library already reads
world.events.bear.remaining_seconds -- so this one number is what turns a window the agent
is looking at into a PARTICIPATE_BEAR that is READY with JOIN_RALLY.  The reading is a
duration, never an instant: knowledge/events/timed_event_readiness.json's time_rule forbids
inferring the game's timezone from this machine's.
"""

from winter_agent_v2.ocr import OCRToken
from winter_agent_v2.rally import BearPhase, bear_phase, read_bear_popup_countdown


def token(text, x=0, y=0, w=120, h=26, confidence=0.99):
    return OCRToken(text, confidence, ((x, y), (x + w, y), (x + w, y + h), (x, y + h)))


#: The popup frame's tokens, in the order the reader hands them over. The map's other timers
#: are included on purpose: they are what makes the 剩余时间 label load-bearing.
REAL_POPUP_FRAME = [
    token("09-0921:16:07", 127, 14, 166, 25),      # the client's own clock
    token("剩余时间：00:13:54", 295, 541, 134, 22, 0.93),
    token("o将猎陷阱", 330, 568, 86, 19, 0.767),
    token("00:00:02", 610, 580, 99, 23),
    token("00:13:54", 468, 788, 69, 20, 0.983),
    token("等级1变异巨熊", 277, 822, 166, 30, 0.999),
]


def test_the_open_window_is_read_as_a_duration_and_the_phase_follows():
    got = read_bear_popup_countdown(REAL_POPUP_FRAME)
    assert got is not None
    assert got["event_id"] == "BEAR_HUNT"
    assert got["remaining_seconds"] == 13 * 60 + 54
    assert got["source"] == "LIVE_CLIENT_BEAR_POPUP_COUNTDOWN"
    assert bear_phase(None, None, got["remaining_seconds"]) is BearPhase.ACTIVE


def test_the_answer_is_a_duration_and_never_an_instant():
    """No field may look like an ISO instant: a naive one could not drive a wake anyway, and
    an offset one would mean a timezone had been assumed somewhere."""
    import re
    iso = re.compile(r"\d{4}-\d{2}-\d{2}[T ]")
    got = read_bear_popup_countdown(REAL_POPUP_FRAME)
    assert isinstance(got["remaining_seconds"], int)
    assert not any(iso.search(str(v)) for v in got.values())


def test_the_label_is_what_makes_the_clock_the_window_s():
    """The same screen draws bare 00:00:02 / 00:00:07 / 06:04:48; none of them may be taken."""
    frame = [t for t in REAL_POPUP_FRAME if "剩余时间" not in t.text]
    assert read_bear_popup_countdown(frame) is None


def test_a_clock_that_was_misread_is_refused_rather_than_repaired():
    """bear_trap_loaded.png really reads 剩余时间：00：142. Recovering '14:2' would be inventing."""
    frame = [t for t in REAL_POPUP_FRAME if "剩余时间" not in t.text]
    frame.append(token("剩余时间：00：142", 295, 543))
    assert read_bear_popup_countdown(frame) is None


def test_a_clock_without_the_identity_is_not_the_bear_s_window():
    frame = [t for t in REAL_POPUP_FRAME if "变异巨熊" not in t.text]
    assert read_bear_popup_countdown(frame) is None


def test_a_full_width_colon_in_the_clock_still_reads():
    frame = [token("等级1变异巨熊"), token("剩余时间：00：13：54")]
    got = read_bear_popup_countdown(frame)
    assert got is not None and got["remaining_seconds"] == 834


def test_the_bear_action_words_in_the_chat_log_are_not_an_identity_by_themselves():
    """The chat line names 变异巨熊 too, so the clock must carry the label to count."""
    frame = [token("麦田中央：快来集结一起击败变异巨熊！（598,462）"), token("00:13:54")]
    assert read_bear_popup_countdown(frame) is None
