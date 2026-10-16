"""Event card face reader -- pure functions over OCR text, wired to nothing.

Step 1 of the wiring plan in ``knowledge/skills/candidate/EVENT_READERS_SPEC.md``: the four
fields a live event card prints (my score / reward tiers / phase+timer / task table), read from
text alone.  No frame access, no clicks, no imports from vision or runtime -- which is exactly
why it can land before the wiring question is answered, and why its tests can use the verbatim
strings the client printed on 2026-10-16 rather than synthetic ones.

Samples these functions were written against (all measured live, r209-r210):

    我的积分：0
    100 / 37,500 / 75,000 / 125,000 / 187,500
    侦察阶段 13:27:18
    护送1次任意品质商旅 10,000点积分
    拦截1次任意品质商旅 10,000点积分
    领主装备最高评分提升1点（不包含领主宝石） 22点积分

Deliberately conservative: a field that cannot be read unambiguously is left out of the dict
rather than guessed (the spec's confidence rule).  Zero is a valid reading; absence is not zero.
"""

from __future__ import annotations

import re

#: ``我的积分：<N>`` -- the client prints a full-width colon and no space.
_MY_SCORE_RE = re.compile(r"我的积分\s*[：:]\s*([\d,]+)")

#: A phase name followed by HH:MM:SS.  The phase word is kept as printed (e.g. 侦察阶段).
_PHASE_TIMER_RE = re.compile(r"([\u4e00-\u9fff]{2,6}阶段)\s*(\d{1,2}:\d{2}:\d{2})")

#: One scoring row: any text ending in ``<number>点积分``; the description keeps its own
#: parentheses and other punctuation verbatim.
_TASK_ROW_RE = re.compile(r"(.+?)\s*([\d,]+)\s*点积分")

#: A tier value: thousands-separated or plain integer, at least three digits.
_TIER_VALUE_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{3,})\b")


def _to_int(token: str) -> int:
    return int(token.replace(",", ""))


def read_my_score(text: str) -> int | None:
    """The ``我的积分：N`` row.  ``0`` is a reading; no match means *unknown*, not zero."""
    m = _MY_SCORE_RE.search(text or "")
    return _to_int(m.group(1)) if m else None


def read_phase_timer(text: str) -> tuple[str, str] | None:
    """``<phase> HH:MM:SS`` as printed, or None.  The reader never converts to datetime:
    the countdown is a game-clock value and start times are not to be back-computed."""
    m = _PHASE_TIMER_RE.search(text or "")
    return (m.group(1), m.group(2)) if m else None


def read_task_rows(text: str) -> list[dict]:
    """Every ``<desc> <N>点积分`` row, description kept verbatim."""
    rows = []
    for m in _TASK_ROW_RE.finditer(text or ""):
        rows.append({"description": m.group(1).strip(), "points": _to_int(m.group(2))})
    return rows


def read_tiers(text: str) -> list[int]:
    """The tier ladder, ascending.  Returns [] unless the candidates already ascend -- a
    shuffled or half-read set is withheld rather than guessed (the spec's monotonicity check)."""
    values = [_to_int(m.group(1)) for m in _TIER_VALUE_RE.finditer(text or "")]
    if len(values) < 2:
        return []
    if any(b <= a for a, b in zip(values, values[1:])):
        return []
    return values


def read_event_card(text: str) -> dict:
    """All four fields that the frame's text supports; unsupported keys are absent."""
    out: dict = {}
    score = read_my_score(text)
    if score is not None:
        out["my_score"] = score
    pt = read_phase_timer(text)
    if pt is not None:
        out["phase"], out["remaining"] = pt
    tasks = read_task_rows(text)
    if tasks:
        out["tasks"] = tasks
    tiers = read_tiers(text)
    if tiers:
        out["tiers"] = tiers
    return out


#: The gate for "this frame is showing a live event card", deliberately stronger than any
#: single token: a lone 我的积分 row or a lone countdown can appear in other surfaces, so the
#: gate asks for a scoring row *and* one more card-shaped signal.  The strings are the ones
#: measured on 2026-10-16; the tabstrip-only frame (常规活动/联盟大作战/…) must fail it.
def looks_like_event_card(text: str) -> bool:
    """True when the frame's text carries a live event card, not just the tab strip."""
    t = text or ""
    has_score_row = "我的积分" in t
    has_points_row = "点积分" in t
    has_phase_timer = _PHASE_TIMER_RE.search(t) is not None
    has_ladder = len(read_tiers(t)) >= 2
    signals = sum((has_score_row, has_points_row, has_phase_timer, has_ladder))
    # A bare tab strip (names only) has none of these; a real card measured live had three.
    # 阶段+倒计时 is admitted on its own: the siege card (r210) carries it and nothing else
    # card-shaped, and "<汉字>阶段 HH:MM:SS" has not been observed outside a live card.
    return signals >= 2 or has_phase_timer
