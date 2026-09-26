"""BEAR_AUTO_JOIN_STATE — read the auto-join switch state from real client frames.

Evidence sources (real UI only, no guessing):
  1. Context text on the alliance-war rally page: "自动加入" button and the
     hint line "开启后自动加入冰原巨兽集结".
  2. Red badge dot at the top-right of the button. Observed on frame
     dataset/raw/autogen/r14_war.png at pixel bbox x[481..488] y[1182..1197],
     center ~(484, 1189), diameter ~12px. Red dot == switch OFF (未开启).

Decision rule:
  button context missing            -> UNKNOWN (we are not on the right page)
  button present + red dot present  -> OFF
  button present + no red dot       -> ON
  anything contradictory            -> UNKNOWN

Policy (winter_agent_v2.skills BEAR_AUTO_JOIN):
  state == OFF     -> click allowed (MAA BTN_BEAR_AUTO_JOIN), verifier expects OFF -> ON
  state == ON      -> SUCCESS/NOOP, must NOT click again (clicking again would turn it off)
  state == UNKNOWN -> never click

Usage:
  .venv/Scripts/python.exe tools/bear_auto_join_state.py FRAME.png [FRAME2.png ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402

# Red badge dot search window (PIL box x1, y1, x2, y2), calibrated on r14_war.png.
DOT_BOX = (468, 1170, 512, 1212)
# Minimum red pixels to accept "dot present" (dot has ~60 core pixels at r>200).
DOT_RED_MIN = 8
# Bottom strip that must OCR-contain the button/hint text (PIL box).
CONTEXT_BOX = (140, 1090, 580, 1280)
CONTEXT_WORDS = ("自动加入",)


def _count_red_dots(frame: Image.Image, box: tuple[int, int, int, int]) -> int:
    """Count strongly red pixels inside *box* (r high, g/b low)."""
    x1, y1, x2, y2 = box
    x2 = min(x2, frame.width)
    y2 = min(y2, frame.height)
    count = 0
    for yy in range(max(0, y1), y2):
        for xx in range(max(0, x1), x2):
            r, g, b = frame.getpixel((xx, yy))[:3]
            if r > 140 and (r - g) > 60 and (r - b) > 60:
                count += 1
    return count


def _context_text(frame: Image.Image) -> str:
    """OCR the bottom strip; returns the concatenated text ('' on failure)."""
    try:
        from winter_agent_v2.ocr import RapidOCRBackend
    except Exception:
        return ""
    try:
        strip = frame.crop(CONTEXT_BOX)
        tokens = RapidOCRBackend().recognize(strip)
    except Exception:
        return ""
    return "".join(token.text for token in tokens)


def read_state(frame_path: str | Path) -> dict:
    """Read BEAR auto-join switch state from one real frame."""
    frame = Image.open(frame_path).convert("RGB")
    context = _context_text(frame)
    context_hit = any(word in context for word in CONTEXT_WORDS)
    red = _count_red_dots(frame, DOT_BOX)

    if not context_hit:
        state = "UNKNOWN"
        reason = "auto-join button context not found on page (not rally page or OCR miss)"
    elif red >= DOT_RED_MIN:
        state = "OFF"
        reason = f"red badge dot present in dot ROI ({red} red px)"
    elif red == 0:
        state = "ON"
        reason = "button present with zero red pixels in dot ROI"
    else:
        state = "UNKNOWN"
        reason = f"ambiguous red pixel count ({red})"

    return {
        "frame": str(frame_path),
        "state": state,
        "reason": reason,
        "red_pixels": red,
        "dot_box": list(DOT_BOX),
        "context_text": context[:80],
        "context_hit": context_hit,
        "dot_red_min": DOT_RED_MIN,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = [read_state(p) for p in argv[1:]]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
