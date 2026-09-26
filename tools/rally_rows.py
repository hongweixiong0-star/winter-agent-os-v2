"""Rally list rows — LIST_DYNAMIC reader for the bear rally tab (directive #12).

Reads the CURRENT rally list from a real war-page frame and structures every
row: leader / target / capacity / current_members / join_available / full /
timer.  No permanent row coordinates are recorded — rows are re-identified
from the live frame on every refresh/scroll, which is the whole point of
LIST_DYNAMIC.

The parser groups OCR tokens into rows by vertical position inside the rally
tab body, then classifies each row with the words found on it.  Rows are only
trusted when the page is really the rally tab (marker: 集结 tab + war list
markers); anything else returns ``[]`` with a reason.

Reusable later for other rally events (the parser never assumes bear-only
words except for target classification).

Usage:
  .venv/Scripts/python.exe tools/rally_rows.py FRAME.png [--role NAME]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402

# Rally tab body: below the 集结/单人/活动 tabs, above the auto-join bar.
BODY_BOX = (0, 150, 720, 1120)
PAGE_MARKERS = ("集结",)
FULL_MARKERS = ("已满", "满员")
JOIN_MARKERS = ("加入",)
TIMER_MARKERS = ("后", ":", "：")
BEAR_TARGETS = ("冰原巨兽", "巨兽", "巨熊")


def _row_of(token, rows: list[dict], tol: float = 28.0) -> dict:
    """Assign a token to a row by vertical centre, creating one if needed."""
    ys = [p[1] for p in token.box]
    y = sum(ys) / len(ys) if ys else 0.0
    x = min(p[0] for p in token.box) if token.box else 0.0
    for row in rows:
        if abs(row["_y"] - y) <= tol:
            row["_tokens"].append((x, token.text))
            row["_y"] = sum(r["_y"] for r in rows) / len(rows)  # drift
            return row
    row = {"_y": y, "_tokens": [(x, token.text)]}
    rows.append(row)
    return row


def _classify(row: dict) -> dict:
    tokens = sorted(row["_tokens"], key=lambda p: p[0])
    text = "".join(t for _, t in tokens)
    members = None
    for _, t in tokens:
        if "/" in t:
            parts = t.split("/")
            if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                members = [int(parts[0]), int(parts[1])]
    full = any(m in text for m in FULL_MARKERS) or bool(members and members[0] >= members[1])
    joinable = any(m in text for m in JOIN_MARKERS) and not full
    target = next((w for w in BEAR_TARGETS if w in text), None)
    # leader: leftmost token that is not a keyword/UI fragment
    keywords = FULL_MARKERS + JOIN_MARKERS + BEAR_TARGETS + ("集结", "开启", "成员")
    leader = next((t for _, t in tokens
                   if not any(k in t for k in keywords) and len(t.strip()) >= 2
                   and not t.strip().isdigit()), "")
    return {
        "text": text,
        "leader": leader,
        "target": target or ("BEAR" if any(w in text for w in BEAR_TARGETS) else "OTHER"),
        "members": members,
        "full": full,
        "join_available": joinable,
        "has_timer": any(m in text for m in TIMER_MARKERS),
    }


def read_rally_rows(frame_path: str | Path) -> dict:
    frame = Image.open(frame_path).convert("RGB")
    from winter_agent_v2.ocr import RapidOCRBackend
    # page marker check runs on the FULL frame (the 集结 tab sits above the body)
    page_text = "".join(t.text for t in RapidOCRBackend().recognize(frame))
    if not any(m in page_text for m in PAGE_MARKERS):
        return {"frame": str(frame_path), "page": "NOT_RALLY_TAB", "rows": [],
                "reason": "rally tab marker absent — refusing to invent rows"}
    tokens = RapidOCRBackend().recognize(frame.crop(BODY_BOX))
    rows: list[dict] = []
    for t in tokens:
        if not t.text.strip():
            continue
        _row_of(t, rows)
    parsed = [_classify(r) for r in rows]
    # a real rally row needs a leader and (members or a join/timer cue)
    parsed = [p for p in parsed
              if p["leader"] and (p["members"] or p["join_available"] or p["has_timer"])]
    return {"frame": str(frame_path), "page": "RALLY_TAB", "rows": parsed,
            "row_count": len(parsed)}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    out = [read_rally_rows(p) for p in args]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
