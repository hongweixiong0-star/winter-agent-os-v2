"""Register the bear-chain templates §5.1 still had no asset for.

Why this exists
---------------
``tools/audit_bear_capability_inventory.py`` asks the task book's own question -- which of
the bear UI elements do we actually have -- and answered it for four of the five groups:

    A 活动入口   complete
    B 集结列表   complete
    C 编队       MISSING TARGET_TROOP_PRESET, BTN_HERO_SELECT, STATUS_TROOP_CAPACITY
    D 参与结果   MISSING STATUS_RALLY_JOINED, STATUS_BATTLE_RESULT, STATUS_TROOP_RETURNING
    E 异常       complete

This script closes the part of C and D that the project's **own live frames already
contain** and simply had not cut.  It is not new evidence and does not claim to be: every
box is measured off a frame already in ``dataset/raw/bear_live_20260909/``, so
``provenance`` is ``LIVE_CLIENT`` and the parent sha256 is recorded.

What it deliberately does NOT do
--------------------------------
``BTN_HERO_SELECT`` and ``STATUS_BATTLE_RESULT`` have no frame in the archive, so they are
**not** invented here -- an invented template is exactly the "假 UI 截图" the task book's
§13.1 forbids, and a guessed box is the coordinate hardcoding the constitution bans.  They
are recorded as gaps in ``knowledge/game/bear_ui_coverage.json`` instead.

Frames used and what each one proves
------------------------------------
``bear_troop_setup.png``  出征 page: 兵力 117,670/117,670; the preset strip; and the three
                          troop rows with their own counters and controls.
``bear_dispatched.png``   the left HUD *after a real join*: 采集中 06:02:47, then 特殊 with
                          集结中 00:04:58 underneath it.  This is the project's only
                          positive evidence that a rally really took a march slot, so it is
                          the right source for STATUS_RALLY_JOINED.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"E:\WinterAgent")
sys.path.insert(0, str(ROOT))

RAW = ROOT / "dataset/raw/bear_live_20260909"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
OUT_DIR = ROOT / "dataset/candidate/bear_rally"

# box: (left, top, right, bottom) in pixels on the 720x1280 live frame.
#
# Every box was measured off its own frame with a labelled pixel grid
# (``dataset/raw/bear_live_20260909/_grid/grid_troop_rows_all.png`` and
# ``grid_troop_row3.png`` and ``grid_dispatched_hud.png``), not estimated from a
# screenshot.  The three troop rows are the case that needs saying out loud: they are
# separated by ~136 px on this frame, and a box even 20 px too tall starts matching the
# neighbouring row's identical white-on-grey counter -- which for a troop page is the
# difference between loading the infantry preset and the archer one.
TEMPLATES: dict[str, dict] = {
    # -- C 编队：兵力与预设条 ------------------------------------------------
    "STATUS_TROOP_CAPACITY": {
        "frame": "bear_troop_setup.png",
        "box": (72, 192, 305, 248),
        "note": "出征頁 兵力 117,670/117,670; the capacity the preset is actually filling",
    },
    # The preset strip is a STRUCTURE element (§25.1 容器元素): it is read to learn *which*
    # preset is selected, and the selected one is drawn with an orange border.  It is
    # deliberately not treated as a tap target, because §25.2 requires a preset to be
    # chosen by its own name rather than by a position in the strip.
    "TAB_TROOP_PRESET_STRIP": {
        "frame": "bear_troop_setup.png",
        "box": (15, 92, 660, 162),
        "note": "the 8-slot preset strip (打野/书咏/杰西/杰塞尔/尼莫/熊6/熊7/开车); a container, "
                "read to identify the selected preset, never tapped as a whole",
    },
    # -- C 编队：三个兵种行 --------------------------------------------------
    # Each row is number+denominator on top and its own control pair below, so the box spans
    # both: the row identity is the pair, not the number alone (a bare counter is identical
    # on all three rows).
    "TARGET_TROOP_ROW_INFANTRY": {
        "frame": "bear_troop_setup.png",
        "box": (395, 636, 690, 752),
        "note": "frozen row 1: 51,774/82,951 with its own pause + '+' controls",
    },
    "TARGET_TROOP_ROW_LANCER": {
        "frame": "bear_troop_setup.png",
        "box": (395, 772, 690, 888),
        "note": "frozen row 2: 24,711/77,224; pitch from row 1 is 136 px, which is why the "
                "box must not be padded",
    },
    "TARGET_TROOP_ROW_MARKSMAN": {
        "frame": "bear_troop_setup.png",
        "box": (395, 918, 690, 1030),
        "note": "frozen row 3: 41,185/86,193",
    },
    # -- D 参与结果 ----------------------------------------------------------
    "STATUS_RALLY_JOINED": {
        "frame": "bear_dispatched.png",
        "box": (8, 342, 275, 388),
        "note": "left HUD 特殊 → 集结中 00:04:58: the project's own proof that a rally took a "
                "march slot, which is the join verifier's positive evidence",
    },
    "STATUS_MARCH_GATHERING": {
        "frame": "bear_dispatched.png",
        "box": (8, 240, 275, 282),
        "note": "left HUD 采集中 06:02:47; the ordinary-march read the rally status is "
                "distinguished against",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    crops: dict[str, tuple[Path, tuple[int, int, int, int], Image.Image, str]] = {}
    frames: dict[str, tuple[int, int, str]] = {}

    for semantic, spec in TEMPLATES.items():
        frame_path = RAW / spec["frame"]
        if not frame_path.is_file():
            raise SystemExit(f"missing live frame for {semantic}: {frame_path}")
        with Image.open(frame_path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            crop = image.crop(spec["box"])
            name = f"{semantic.lower()}__{frame_path.stem}__{_sha256(frame_path)[:8]}__0.png"
            path = OUT_DIR / name
            crop.save(path, format="PNG")
            crops[semantic] = (path, spec["box"], crop, spec["frame"])
            frames[spec["frame"]] = (width, height, _sha256(frame_path))
            print(f"{semantic}: {crop.size} px -> {path.name}")

    # A reviewer sheet per frame, so the box can be checked without opening the manifest.
    for frame_name in frames:
        with Image.open(RAW / frame_name) as opened:
            review = opened.convert("RGB")
        draw = ImageDraw.Draw(review)
        for semantic, (_p, box, _c, src) in crops.items():
            if src == frame_name:
                draw.rectangle(box, outline=(255, 0, 0), width=3)
                draw.text((box[0], max(0, box[1] - 14)), semantic, fill=(255, 0, 0))
        review.save(OUT_DIR / f"_review_{Path(frame_name).stem}_boxes.png")

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    existing = {(str(r.get("semantic")), str(r.get("template_path"))) for r in records}

    added = []
    for semantic, spec in TEMPLATES.items():
        path, box, _crop, frame_name = crops[semantic]
        if (semantic, str(path)) in existing:
            continue
        width, height, _sha = frames[frame_name]
        records.append({
            "template_id": path.stem,
            "semantic": semantic,
            "status": "CANDIDATE",
            "template_path": path.as_posix(),
            "parent_screenshot": (RAW / frame_name).as_posix(),
            "parent_sha256": _sha256(RAW / frame_name),
            "roi_norm": {
                "x_norm": round(box[0] / width, 6),
                "y_norm": round(box[1] / height, 6),
                "w_norm": round((box[2] - box[0]) / width, 6),
                "h_norm": round((box[3] - box[1]) / height, 6),
            },
            "width": box[2] - box[0],
            "height": box[3] - box[1],
            "confidence": 0.95,
            "source": f"live_20260909_bear_hunt/{frame_name}",
            "provenance": "LIVE_CLIENT",
            "game": "无尽冬日 (com.gof.china)",
            "page": "MARCH",
            "note": spec["note"],
        })
        added.append(semantic)

    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nmanifest records: {len(records)} (+{len(added)})")
    print("added:", ", ".join(added) or "-")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
