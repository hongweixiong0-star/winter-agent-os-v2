"""Does the production vision now read the screen the training route kept dying on?

End to end, on the ten live frames that failed, plus the gold-ring frames as negatives.

For every frame it runs the production ``HybridVision`` (template layer + OCR layer, the
same object ``tools/control_panel.py`` builds) and reports:

  * what page the frame reads as;
  * the ``training`` reading;
  * whether ``verify_infantry_camp_highlighted`` -- the verifier bound to
    ``NAVIGATE_INFANTRY_CAMP``, the hop that failed 12 times -- now passes on it;
  * and, on the two frames of the older render, that the *action bar* reading did not
    change: those frames pass by the gold ring, and a reader that also claimed an action
    bar on them would be reading two different screens as one.

Nothing is written except this tool's own stdout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402


def frames() -> list[tuple[str, Path]]:
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("execution_mode")) != "PRODUCTION":
            continue
        if str(row.get("skill")) != "NAVIGATE_INFANTRY_CAMP":
            continue
        recorded = str(row.get("recorded_at") or "")
        after = row.get("after_screenshot")
        if not after:
            continue
        kind = "EXPECT-OK" if recorded >= "2026-09-21T16:00" else "EXPECT-UNCHANGED"
        if recorded >= "2026-09-21T16:00" or recorded >= "2026-09-21T00:00":
            rows.append((f"{kind} {recorded[11:16]}", Path(str(after))))
    return rows[-14:]


def build():
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return HybridVision(template, ocr)


def main() -> int:
    from winter_agent_v2.verifier import verify_infantry_camp_highlighted

    vision = build()
    before = WorldState(page=Page.POPUP, popup="POWER_DETAILS", confidence=0.99)
    passed = failed = missing = 0
    wrong = []
    for label, path in frames():
        print("=" * 74)
        print(label, "|", path.name)
        if not path.exists():
            print("   MISSING ON DISK")
            missing += 1
            continue
        state = vision.observe(path)
        training = state.training or {}
        print(f"   page={state.page}  popup={state.popup}")
        print(f"   training={json.dumps(training, ensure_ascii=False)}")
        result = verify_infantry_camp_highlighted(before, state)
        print(f"   verify_infantry_camp_highlighted -> ok={result.ok} reason={result.reason}")
        print(f"      evidence={json.dumps(result.evidence, ensure_ascii=False)}")
        if label.startswith("EXPECT-OK"):
            if result.ok:
                passed += 1
            else:
                failed += 1
        elif training.get("source") == "ACTION_BAR":
            wrong.append(path.name)
    print("=" * 74)
    print(f"frames that must now pass : {passed} passed, {failed} still failing, {missing} missing on disk")
    print(f"older frames wrongly read as an action bar: {'none' if not wrong else wrong}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
