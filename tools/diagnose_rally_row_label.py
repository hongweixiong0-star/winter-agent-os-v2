"""Why does one role read no rally-row target label while another reads every one?

Read-only diagnostic.  No device, no lease, no tap -- it opens a recorded frame and runs the
production reader over it.

The question this answers is narrow and decisive: for a row whose green + is visible and whose
countdown is read, is the target label
  (a) absent from the frame's OCR tokens at all, or
  (b) present, but outside the band the reader assigns to that row?

(a) is an OCR/rendering problem and no geometry change can fix it.  (b) is the reader's band
arithmetic and is fixable here.  Guessing between them is how a "reader is broken" conclusion gets
written without evidence, so this prints both sides.

usage:
    python tools/diagnose_rally_row_label.py <frame.png> [<frame.png> ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.rally import (  # noqa: E402
    BEAR_TARGET_WORDS,
    RALLY_ROW_HEADER_WORD,
    read_rally_list_image,
)


def _matches_bear(text: str) -> bool:
    return any(word in text for word in BEAR_TARGET_WORDS)


def diagnose(frame: Path) -> None:
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend

    print("=" * 78)
    print(f"frame: {frame}")
    if not frame.exists():
        print("  MISSING -- cannot diagnose")
        return

    ocr = OCRService(RapidOCRBackend())
    result = ocr.recognize(frame)
    tokens = [t for t in getattr(result, "tokens", ()) if getattr(t, "text", "").strip()]
    print(f"  OCR tokens: {len(tokens)}")

    headers = [t for t in tokens if RALLY_ROW_HEADER_WORD in t.text]
    bear_tokens = [t for t in tokens if _matches_bear(t.text)]
    print(f"  row headers ({RALLY_ROW_HEADER_WORD!r}): {len(headers)}")
    for token in headers:
        print(f"     y={token.centre[1]:7.1f}  {token.text.strip()!r}")
    print(f"  tokens naming the bear {BEAR_TARGET_WORDS}: {len(bear_tokens)}")
    for token in bear_tokens:
        print(f"     y={token.centre[1]:7.1f}  x={token.centre[0]:7.1f}  {token.text.strip()!r}")
    if not bear_tokens:
        print("     (none -- showing every token so the frame's real text is visible)")

    reading = read_rally_list_image(frame, tokens)
    print(f"  reader -> rows={len(reading.rows)}")
    for row in reading.rows:
        print(f"     row{row.row_index} band=({row.band_norm[0]:.0f}..{row.band_norm[1]:.0f}) "
              f"target={row.target_text!r} type={row.target_type.value} "
              f"state={row.state.value} join={row.join_norm is not None} "
              f"members={row.capacity_used}/{row.capacity_max}")

    # (b) test: is a bear token present but outside every band the reader used?
    if bear_tokens and not any(row.target_text for row in reading.rows):
        print("  >>> a bear token EXISTS but no row claimed it: this is a BAND problem")
        for token in bear_tokens:
            inside = [row.row_index for row in reading.rows
                      if row.band_norm[0] <= token.centre[1] <= row.band_norm[1]]
            print(f"      bear token y={token.centre[1]:.1f} falls in rows {inside or 'NONE'}")
    elif not bear_tokens:
        print("  >>> no bear token on this frame: this is an OCR/READING problem, not geometry")

    print("  --- every token (y, x, text) ---")
    for token in sorted(tokens, key=lambda t: (t.centre[1], t.centre[0])):
        mark = " <== BEAR" if _matches_bear(token.text) else (
            " <== HEADER" if RALLY_ROW_HEADER_WORD in token.text else "")
        print(f"     y={token.centre[1]:7.1f} x={token.centre[0]:7.1f} {token.text.strip()!r}{mark}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", nargs="+")
    args = parser.parse_args(argv)
    for name in args.frames:
        diagnose(Path(name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
