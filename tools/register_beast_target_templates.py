"""Re-register the beast target-card templates from a live frame.

Why the old ones stopped working (measured 2026-09-14):

    BTN_BEAST_START_MARCH   best distance 30   threshold 8
    DIALOG_BEAST_TARGET     best distance 14
    BTN_BEAST_DISPATCH      best distance 36

The beast target card moved: the old records put the 出征 button at
y_norm 0.713 and x_norm 0.44, while on the current client it sits at
y_norm 0.455 and x_norm 0.335 -- the card is higher and centred now.

This matters twice over, because ``BTN_BEAST_START_MARCH`` is both
  * the page evidence (``vision.py`` returns ``Page.BEAST`` when it matches,
    which is what ``verify_intel_target_open`` requires), and
  * the tap target of ``INTEL_BEAST_START_MARCH`` (the 出征 button).

The frame used here is a real live capture whose content is independently
verifiable: it shows 等级22大角鹿, 推荐实力 5,107,044 and a 10-stamina 出征 cost,
which are exactly the values ``vision.py`` and ``verify_intel_beast_march_open``
already assert for mission ``INTEL_BEAST_10``.  Nothing had to be invented.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
FRAME = (
    ROOT
    / "dataset/raw/control_panel/runtime_auto/live_stamina_intel_run2"
    / "live_stamina_intel_run2_step_002_after_20260914T061808057867.png"
)
OUT_DIR = ROOT / "dataset/candidate/beast_target"

# (left, top, right, bottom) in pixels on the 720x1280 frame, measured from the
# card crop rather than eyeballed: the orange button spans px 243-474 x 585-649.
TEMPLATES = {
    "BTN_BEAST_START_MARCH": {
        "box": (241, 583, 476, 651),
        "note": "current-client 出征 button of the 等级22大角鹿 Intel target card",
        "extra": {"recommended_power": 5107044, "stamina_cost": 10, "mission_id": "INTEL_BEAST_10"},
    },
}


def main() -> int:
    if not FRAME.is_file():
        raise SystemExit(f"missing live frame: {FRAME}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    existing = {(str(r.get("semantic")), str(r.get("template_path"))) for r in records}

    with Image.open(FRAME) as image:
        image = image.convert("RGB")
        width, height = image.size
        added = 0
        for semantic, spec in TEMPLATES.items():
            box = spec["box"]
            template = OUT_DIR / f"{semantic.lower()}__live_beast_target_card.png"
            image.crop(box).save(template)
            if (semantic, str(template)) in existing:
                print(f"already registered: {semantic}")
                continue
            records.append({
                "semantic": semantic,
                "template_path": str(template),
                "roi_norm": {
                    "x_norm": round(box[0] / width, 6),
                    "y_norm": round(box[1] / height, 6),
                    "w_norm": round((box[2] - box[0]) / width, 6),
                    "h_norm": round((box[3] - box[1]) / height, 6),
                },
                "source": "live_20260914_intel_beast_card/step_002_after",
                "provenance": "LIVE_CLIENT",
                "note": spec["note"],
                "measured": spec["extra"],
            })
            added += 1
            print(f"registered {semantic} roi={records[-1]['roi_norm']}")
        review = image.copy()
        draw = ImageDraw.Draw(review)
        for spec in TEMPLATES.values():
            draw.rectangle(spec["box"], outline=(255, 0, 0), width=2)
        review.crop((200, 320, 520, 700)).resize((640, 760), Image.LANCZOS).save(
            OUT_DIR / "_review_button_box.png"
        )

    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest records: {len(records)} (+{added})")

    # Replay verification against the same frame, plus a negative control on a
    # plain map frame (the button must not fire there).
    from winter_agent_v2.vision import SemanticWorldVision

    vision = SemanticWorldVision(MANIFEST)
    state = vision.observe(FRAME)
    print(f"\nframe now classifies as: page={state.page.value} beast={state.beast}")
    for spec_name in TEMPLATES:
        match = vision.semantic.find(FRAME, spec_name)
        print(f"  {spec_name}: distance={None if match is None else match.distance} centre={None if match is None else match.center_norm}")
    plain_map = ROOT / "dataset/truth_audit/hud_stamina_20260914/map_hud_with_stamina_200.png"
    if plain_map.is_file():
        control = vision.observe(plain_map)
        print(f"negative control (plain map): page={control.page.value} (must not be BEAST)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
