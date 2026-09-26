"""BEAR auto-join switch state — production reader.

Reads the toggle state from a real client frame.  Moved here from
``tools/bear_auto_join_state.py`` so the ExecutorRouter guard (production
dispatch path) and the CLI share one implementation.

Evidence sources (real UI only):
  1. Context text on the alliance-war rally page: 「自动加入」 button and the
     hint line 「开启后自动加入冰原巨兽集结」.
  2. Red badge dot at the button's top-right — calibrated on
     dataset/raw/autogen/r14_war.png (bbox x[481..488] y[1182..1197],
     center ~(484,1189)); red dot == switch OFF (未开启).

Decision:
  button context missing            -> UNKNOWN (not the right page / OCR miss)
  button present + red dot present  -> OFF
  button present + no red dot       -> ON

Policy enforced by ExecutorRouter for BEAR_AUTO_JOIN:
  ON     -> SUCCESS / NOOP — never click again (would turn it off)
  OFF    -> click allowed; verifier expects OFF -> ON
  UNKNOWN-> never click

The reader never caches: every call re-reads the current frame, so the state
is inherently per-role (role_01 / role_02 never share a reading).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Red badge dot search window (PIL box x1, y1, x2, y2), calibrated on r14_war.png.
DOT_BOX = (468, 1170, 512, 1212)
# Minimum red pixels to accept "dot present" (dot has ~60 core pixels at r>200).
DOT_RED_MIN = 8
# Bottom strip that must OCR-contain the button/hint text (PIL box).
CONTEXT_BOX = (140, 1090, 580, 1280)
CONTEXT_WORDS = ("自动加入",)


def _count_red_dots(frame: Image.Image, box: tuple[int, int, int, int]) -> int:
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
    try:
        from .ocr import RapidOCRBackend
    except Exception:  # noqa: BLE001
        return ""
    try:
        strip = frame.crop(CONTEXT_BOX)
        tokens = RapidOCRBackend().recognize(strip)
    except Exception:  # noqa: BLE001
        return ""
    return "".join(token.text for token in tokens)


def read_state_from_image(frame: Image.Image) -> dict:
    """Read the switch state from an already-open RGB frame."""
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
        "state": state,
        "reason": reason,
        "red_pixels": red,
        "dot_box": list(DOT_BOX),
        "context_text": context[:80],
        "context_hit": context_hit,
        "dot_red_min": DOT_RED_MIN,
    }


def read_state(frame_path: str | Path) -> dict:
    """Read the switch state from one real frame file."""
    frame = Image.open(frame_path).convert("RGB")
    out = read_state_from_image(frame)
    out["frame"] = str(frame_path)
    return out
