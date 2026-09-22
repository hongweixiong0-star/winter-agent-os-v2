"""Read-only probe: can the client's own printed words locate the controls the routes name?

Two candidate sources are measured on live frames, both read off *this* frame rather than
remembered from another one:

  * ``ocr.read_tap_anywhere_instruction`` -- the client's own "tap anywhere" instruction, on
    the reward popups whose dismissal failed 97 times (the largest single class in the
    episode stream);
  * ``ocr.find_printed_words`` -- the word the client prints on a control, for the named
    controls the dictionary declares words for (``BTN_OPEN_HOME`` = 城镇 / City on MAP).

Every token on each frame is printed too, so a verdict can be checked rather than trusted,
and the frames where the word is ABSENT are included on purpose: a reader that finds a word
that is not there would be worse than no reader.

Usage:
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/probe_printed_words.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from winter_agent_v2.ocr import (  # noqa: E402
    find_printed_words,
    read_tap_anywhere_instruction,
)
from live_stack import production_vision  # noqa: E402

RAW = ROOT / "dataset" / "raw"
TRUTH = ROOT / "dataset" / "truth_audit"

#: ``(label, frame, words the route names, expect_found)``
CASES = (
    (
        "MAP without the search panel / BTN_OPEN_HOME",
        RAW / "control_panel" / "runtime_auto" / "20260922_101948_054413"
        / "20260922_101948_054413_step_010_before_20260922T022230092501.png",
        ("城镇", "City"),
        True,
    ),
    (
        "MAP with the search panel open / BTN_OPEN_HOME",
        RAW / "control_panel" / "runtime_auto" / "20260921_213842_443057"
        / "20260921_213842_443057_step_001_before_20260921T133846478992.png",
        ("城镇", "City"),
        False,
    ),
    (
        "HOME / the 联盟 navigation cell",
        RAW / "control_panel" / "runtime_auto" / "20260921_095040_726092"
        / "20260921_095040_726092_step_003_before_20260921T015109182497.png",
        ("联盟", "Alliance"),
        True,
    ),
    (
        "POPUP reward / the client's dismissal instruction",
        RAW / "control_panel" / "runtime_auto" / "20260919_171501_633313"
        / "20260919_171501_633313_step_007_before_20260919T091636010866.png",
        (),
        True,
    ),
    (
        "POPUP reward (intel) / the client's dismissal instruction",
        RAW / "control_panel" / "runtime_auto" / "20260922_102539_122690"
        / "20260922_102539_122690_step_002_before_20260922T022551064551.png",
        (),
        True,
    ),
)


def main() -> int:
    vision = production_vision()
    ocr = vision.ocr
    wrong: list[str] = []
    for label, frame, words, expect_found in CASES:
        print("=" * 78)
        print(f"{label}\n  {frame.name}")
        if not frame.exists():
            print("  MISSING ON DISK")
            wrong.append(f"{label} (missing)")
            continue
        size = None
        from PIL import Image

        with Image.open(frame) as opened:
            size = opened.size
        print(f"  frame size: {size}")

        result = ocr.recognize(frame)
        print("  every token at conf >= 0.70, as (x_norm, y_norm):")
        for token in sorted(result.tokens, key=lambda t: -float(t.confidence or 0)):
            if not token.box or float(token.confidence or 0) < 0.70:
                continue
            xs = [float(point[0]) for point in token.box]
            ys = [float(point[1]) for point in token.box]
            cx = round((min(xs) + max(xs)) / 2 / size[0], 4)
            cy = round((min(ys) + max(ys)) / 2 / size[1], 4)
            print(f"    ({cx:.4f}, {cy:.4f}) conf={float(token.confidence):.3f} {token.text!r}")

        if words:
            hit = find_printed_words(frame, words, ocr)
            print(f"  find_printed_words({words}) -> {hit}")
            found = hit is not None
            if found != expect_found:
                wrong.append(f"{label} (expected found={expect_found}, got {found})")
        instruction = read_tap_anywhere_instruction(frame, ocr)
        print(f"  read_tap_anywhere_instruction -> {instruction}")
        if expect_found and not words and instruction is None:
            wrong.append(f"{label} (no instruction read)")
        print()

    print("=" * 78)
    print("cases that did not behave as measured:", wrong or "none")
    return 0 if not wrong else 1


if __name__ == "__main__":
    raise SystemExit(main())
