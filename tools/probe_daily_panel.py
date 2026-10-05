"""Replay one frame through the production observer and print what it says about 每日任务.

Why this exists
---------------
`DAILY_ACTIVITY_TARGET` is 已发现 on the console and its capability `READ_DAILY_PROGRESS` is
BLOCKED with zero attempts.  Two producers can write ``WorldState.daily`` for a daily frame:

  * ``vision.SemanticWorldVision`` -- template matching.  Its branch for
    ``BTN_DAILY_GO_HERO_RECRUIT`` (``vision.py:2340``) returns a *literal* dict
    ``{"status": "AVAILABLE", "task_id": "HERO_RECRUIT_1", "progress": 0, "target": 1,
    "activity": 270}`` -- constants, not measurements, at confidence 0.99.
  * ``ocr.OCRPageClassifier`` -- the OCR reader, whose ``Page.DAILY`` branch
    (``ocr.py:1392``) writes ``daily["tasks"]`` from the rows actually drawn.

``ocr.HybridVision`` is documented as "template-first observation with OCR only as a
conservative fallback", and merges only when both agree on the page
(``ocr.py:6032``).  So the question "why does the console's daily evidence have no task
rows" is answerable only by seeing both verdicts side by side on one frame.

This tool re-implements nothing.  It calls the same ``recognize``, the same
``OCRPageClassifier.classify`` and the same ``HybridVision.observe`` the runtime calls, and
prints all three, plus the raw tokens of the panel so a reader can see the drawn wording
rather than the conclusion.

Read-only: no device, no tap, no write.

Usage
-----
    python tools/probe_daily_panel.py --frame dataset/raw/live_daily_after_beast.png
    python tools/probe_daily_panel.py --frame <any>.png --tokens
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    HybridVision,
    OCRPageClassifier,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    read_frame_size,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

#: Words the daily panel is built from.  Used only to *select* tokens to print -- never to
#: decide anything, so a word missing from this list costs visibility, not correctness.
KEYWORDS = (
    "每日", "章节", "成长", "任务", "活跃", "前往", "领取", "宝箱", "剩余",
    "进度", "已完成", "刷新",
)


def _dump(label: str, value: object) -> None:
    print(f"  {label}: {json.dumps(value, ensure_ascii=False, default=str)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True)
    parser.add_argument("--manifest", default="dataset/candidate/template_manifest.json")
    parser.add_argument("--max-distance", type=int, default=8)
    parser.add_argument("--tokens", action="store_true", help="print the panel's own OCR tokens")
    parser.add_argument(
        "--min-confidence", type=float, default=0.5,
        help="token floor for the token dump only",
    )
    args = parser.parse_args()

    frame = Path(args.frame)
    if not frame.is_absolute():
        frame = ROOT / frame
    if not frame.is_file():
        print("frame absent:", frame)
        return 2

    manifest = ROOT / args.manifest
    frame_size = read_frame_size(frame)
    print(f"frame      : {frame}")
    print(f"frame_size : {frame_size}")
    print()

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))

    result = ocr.recognize(frame)
    tokens = tuple(result.tokens)
    print(f"OCR tokens : {len(tokens)}")

    # ---- producer A: the OCR classifier, called exactly as _observe_inner calls it --------
    classifier = OCRPageClassifier()
    classified = classifier.classify(result, frame_size=frame_size)
    print()
    print("[A] OCRPageClassifier.classify")
    _dump("page", getattr(classified.page, "value", classified.page))
    _dump("confidence", classified.confidence)
    _dump("daily", classified.daily or None)

    rows = classifier._read_daily_task_rows(tokens, frame_size)  # noqa: SLF001 - diagnostic
    print(f"  _read_daily_task_rows -> {len(rows)} row(s)")
    for row in rows:
        print(
            f"    {row.get('task_id'):32} state={row.get('state'):9} "
            f"progress={row.get('progress')} label={row.get('label')!r} "
            f"btn={row.get('action_type')}"
        )

    # ---- producer B + the production entry point ----------------------------------------
    hybrid = HybridVision(
        SemanticWorldVision(manifest, max_distance=args.max_distance), ocr
    )
    primary = hybrid.template_vision.observe(frame)
    print()
    print("[B] SemanticWorldVision.observe (template-first)")
    _dump("page", getattr(primary.page, "value", primary.page))
    _dump("confidence", primary.confidence)
    _dump("daily", primary.daily or None)

    state = hybrid.observe(frame)
    print()
    print("[C] HybridVision.observe  <- the production entry point")
    _dump("page", getattr(state.page, "value", state.page))
    _dump("confidence", state.confidence)
    _dump("daily", state.daily or None)
    _dump("red_dots", state.red_dots or None)
    print(f"  tasks key present: {'tasks' in (state.daily or {})}")

    if state.daily and state.daily.get("tasks"):
        print("  -> the production reading carries task rows")
    else:
        print("  -> the production reading carries NO task rows")

    # ---- the frame's own wording, so the conclusion can be checked ----------------------
    if args.tokens:
        width, height = frame_size or (0, 0)
        print()
        print("[D] tokens the panel draws (x_norm, y_norm from token centre)")
        for token in sorted(
            (t for t in tokens if t.confidence >= args.min_confidence and t.box),
            key=lambda t: (t.centre[1], t.centre[0]),
        ):
            text = str(token.text or "").strip()
            if not text or not any(word in text for word in KEYWORDS):
                continue
            x = token.centre[0] / width if width else 0.0
            y = token.centre[1] / height if height else 0.0
            print(
                f"    ({x:.4f}, {y:.4f})  conf={token.confidence:.2f}  {text!r}"
            )
        print()
        print("    every token, in reading order:")
        for token in sorted(tokens, key=lambda t: (t.centre[1], t.centre[0])):
            text = str(token.text or "").strip()
            if text and token.confidence >= args.min_confidence:
                print(f"      conf={token.confidence:.2f}  {text!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
