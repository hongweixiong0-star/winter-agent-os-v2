"""Alliance day-event reader -- pure functions over OCR text, wired to nothing.

Step 1 of the CHECK_ALLIANCE_EVENT chain (``knowledge/skills/candidate/VALIDATION_PLANS.md``):
the alliance landing page prints today's events as a numbered list, measured live on
2026-10-16:

    10月16日·周五
    1．【联盟大作战】&【军备竞演】
    2.【联盟争霸赛】

Note the client mixes full-width (１．) and half-width (2.) index forms and mixes 「．」 with
「.」 -- both are the same list to a reader, and the first capture showed both styles on
adjacent lines.  Names live inside 【】; a bare numbered line without brackets is still kept,
with its name as printed, because refusing it would hide a real row rather than a parse error.

Same discipline as ``event_card_reader``: fields that cannot be read are absent, never guessed.
"""

from __future__ import annotations

import re

#: One numbered row: index digit (either width), either dot, then the rest of the line.
_ROW_RE = re.compile(r"^\s*([0-9１-９]{1,2})\s*[.．、]\s*(?P<body>.+?)\s*$")

#: The event identities inside a row, e.g. 【联盟大作战】&【军备竞演】 -> both names.
_BRACKET_RE = re.compile(r"【(?P<name>[^】]+)】")

#: The date anchor the page prints above the list (e.g. 10月16日·周五).
_DATE_RE = re.compile(r"(\d{1,2}月\d{1,2}日)[·・\s]*(周[一二三四五六日])?")


def read_day_events(text: str) -> list[dict]:
    """Every numbered row of today's event list, with its 【】names extracted.

    Rows are returned in printed order; ``names`` is empty for a bracket-less row and
    ``raw`` keeps the line verbatim either way.
    """
    rows: list[dict] = []
    for line in (text or "").splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        body = m.group("body")
        names = [bm.group("name") for bm in _BRACKET_RE.finditer(body)]
        rows.append({
            "index": int(m.group(1).translate(str.maketrans("１２３４５６７８９", "123456789"))),
            "names": names,
            "raw": body,
        })
    return rows


def read_day_header(text: str) -> dict | None:
    """The date anchor line the page prints above the list, when the frame carries it."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    out = {"date": m.group(1)}
    if m.group(2):
        out["weekday"] = m.group(2)
    return out


def read_alliance_day(text: str) -> dict:
    """The day-events block: header plus rows; either half may be absent independently."""
    out: dict = {}
    header = read_day_header(text)
    if header:
        out["header"] = header
    rows = read_day_events(text)
    if rows:
        out["events"] = rows
    return out
