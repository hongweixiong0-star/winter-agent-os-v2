"""Register the Bear Hunt / rally templates cut from the 2026-09-09 live frames.

Why this exists
---------------
``JOIN_RALLY`` and ``START_RALLY`` are declared in the registry with verifier names
(``RALLY_JOINED`` / ``RALLY_CREATED``) that have **no entry in
``LiveRuntime.VERIFIED_ATOMIC``**, and ``dataset/candidate/templates`` holds 280
templates of which **zero** name a rally or a bear.  So the one activity with a
30-minute window was the one activity the loop could not see.

The operator's directive is explicit that a template the project already owns is
preferred over anything new, and that a template cut from the real client is worth
more than a re-drawn one.  This script therefore cuts each semantic out of the
already-collected live frame it was actually drawn in -- no redrawing, no guessed
coordinates.

Frames and what each one proves
-------------------------------
``alliance_main_now.png``   联盟 home: the 联盟战争 entry (badge 21).
``special_buildings.png``   联盟领地/特殊建筑: 狩猎陷阱 row, its own 剩余时间, 前往 button.
``bear_trap_detail.png``    the bear detail panel: 等级1变异巨熊 title, 集结 button.
``bear_rally_next.png``     发起集结 dialog: the 5/10 minute choice + 发起集结 confirm.
``join_list_now.png``       集结 tab: a rally row (目标 + 等级1变异巨熊 + 人数 n/15).
``bear_rally_panel.png``    the same list with the 自动加入 footer.
``bear_troop_setup.png``    出征 page: preset strip + the 出征 confirm button.
``bear_dispatched.png``     proof of a live join: 特殊 / 集结中 with its own countdown.

These are the project's own collected frames, so ``provenance`` is
``LIVE_CLIENT`` throughout.  ``source`` names the exact file.
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
# Every box was read off its own frame, and the note names the one thing that
# makes the crop unambiguous.  A crop is deliberately tight: a wide box around a
# row would match the *next* row's identical left column as well as this one,
# which for a rally list is the difference between joining a rally and tapping
# empty space.
TEMPLATES: dict[str, dict] = {
    # -- navigation ---------------------------------------------------------
    "BTN_ALLIANCE_WAR": {
        "frame": "alliance_main_now.png",
        "box": (30, 636, 300, 716),
        "note": "联盟 home tile 联盟战争 (badge 21); the entry to the rally list",
    },
    "TAB_RALLY_LIST": {
        "frame": "join_list_now.png",
        "box": (30, 100, 200, 174),
        "note": "联盟战争 / 集结 tab; a bear rally list only exists under this tab",
    },
    # -- the bear itself ----------------------------------------------------
    # The title row, not the species art.  On the 720x1280 live frame the
    # 等级1变异巨熊 caption sits at y 800..846; the earlier 570..700 window
    # landed on the bear illustration inside the panel, which every large
    # beast panel also shows -- that is the exact confusion between a bear and
    # a plain beast that the directive forbids.
    "TARGET_BEAR_TRAP": {
        "frame": "bear_trap_detail.png",
        "box": (232, 796, 486, 850),
        "note": "等级1变异巨熊 caption row; names the activity, not the species art",
    },
    "ROW_TARGET_BEAR_COLUMN": {
        "frame": "join_list_now.png",
        "box": (34, 236, 164, 420),
        "note": "one rally row's 目标 column: 等级1变异巨熊 + 距离11公里",
    },
    "STATUS_RALLY_COUNTDOWN": {
        "frame": "join_list_now.png",
        "box": (430, 176, 610, 212),
        "note": "row header 集结中: with the row's own MM:SS",
    },
    # -- join (member / 车身) ------------------------------------------------
    # Must be the green + itself.  The first attempt spanned 508..580 and on the
    # review sheet that is the *fourth hero portrait* of the row, i.e. a tap
    # there opens a hero card instead of joining.  Measured off the grid the +
    # lives at x 600..660, y 355..432 (its centre ~630,393) -- the right edge of
    # row 1, level with the hero strip.
    "BTN_JOIN_ROW": {
        "frame": "bear_rally_panel.png",
        "box": (600, 356, 662, 430),
        "note": "the green + on a rally row (centre ~631,393); the join affordance itself",
    },
    "BTN_AUTO_JOIN": {
        "frame": "bear_rally_panel.png",
        "box": (196, 1164, 524, 1244),
        "note": "the 自动加入 footer button (official 8h auto-join)",
    },
    # -- leader (车头) -------------------------------------------------------
    # The orange 集结 button sits beside 伤害排行 at the foot of the bear panel.
    # Measured off the grid: x 366..566, y 982..1040.  The earlier 842..906
    # window was above the buttons and clipped the reward-icon strip instead.
    "BTN_START_RALLY": {
        "frame": "bear_trap_detail.png",
        "box": (368, 982, 564, 1040),
        "note": "the orange 集结 button (right of 伤害排行) in the bear detail panel",
    },
    "POPUP_TITLE_START_RALLY": {
        "frame": "bear_rally_next.png",
        "box": (238, 372, 482, 420),
        "note": "发起集结 dialog title; separates it from every other confirm",
    },
    "BTN_CONFIRM_START_RALLY": {
        "frame": "bear_rally_next.png",
        "box": (184, 658, 536, 734),
        "note": "the 发起集结 confirm inside that dialog",
    },
    # -- entry, on the territory page ---------------------------------------
    "BTN_BEAR_GO": {
        "frame": "special_buildings.png",
        "box": (452, 288, 580, 340),
        "note": "狩猎陷阱 前往 (blue button, x 452..580); the last hop before the bear panel",
    },
    # On the territory page the 狩猎陷阱 row shows its *own* countdown.  The
    # earlier box caught the row label instead; the client's own 剩余时间 is the
    # one datum that tells us the hunt is actually open, so the box must hold it.
    "STATUS_BEAR_WINDOW": {
        "frame": "special_buildings.png",
        "box": (168, 294, 430, 336),
        "note": "狩猎陷阱 剩余时间 (00:15:39); the client's own countdown for the hunt",
    },
    # -- the march page ------------------------------------------------------
    "PAGE_TITLE_MARCH": {
        "frame": "bear_troop_setup.png",
        "box": (86, 26, 176, 66),
        "note": "出征 page title (wordmark left of the belt icon); the preset+army page",
    },
    "BTN_CONFIRM_MARCH": {
        "frame": "bear_troop_setup.png",
        "box": (480, 1192, 668, 1246),
        "note": "the 出征 confirm (right of 全部撤回/平均配置/比例分配); sends the joined march",
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

    # A reviewer sheet per frame, so the box can be checked without opening the
    # manifest.  Cheap, and it is what makes "the crop is authoritative" auditable.
    for frame_name, (width, height, _sha) in frames.items():
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
            "page": "ALLIANCE_WAR" if "join" in frame_name or "rally" in frame_name else "BEAR",
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
