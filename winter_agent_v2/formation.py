# -*- coding: utf-8 -*-
"""Generic march/formation page reader (hero slots, troop rows, confirm control).

One page family, two measured renders:

* ordinary dispatch -- 英勇盾兵 rows, 出征 confirm (measured 2026-09-26 live
  AUTO frame ``20260926_055529_646039_step_004_after...png``);
* bear rally setup -- 王牌盾兵 rows, 储存 confirm (measured live 2026-09-09,
  ``dataset/raw/bear_live_20260909/auto_join_hero_select.png``).

Both share the footer 全部撤回 / 平均配置 / 比例分配 and a bottom-right confirm
control, which is what makes "is this the formation page" decidable from the
frame's own words.  The reader claims *layout facts read from the current
frame*; it never claims that a tap happened or that the march was sent.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

#: The formation footer draws all three; no other page in the corpus does.
FOOTER_WORDS: tuple[str, ...] = ("全部撤回", "平均配置", "比例分配")
#: Bottom-right confirm control, per render.
CONFIRM_WORDS: tuple[str, ...] = ("出征", "储存")
#: Troop-row labels carry the troop type; the row's + control sits at x≈0.91.
TROOP_ROW_WORDS: tuple[str, ...] = ("盾兵", "矛兵", "射手")
#: Hero slot x-centres, measured on both real renders (empty ``+`` slots on the
#: bear frame, filled cards on the ordinary frame agree to within half a slot
#: width).  Norms, so they are re-checked against the current frame's extent,
#: never used as absolute pixels.
HERO_SLOT_CENTRES: tuple[float, ...] = (0.253, 0.500, 0.747)
HERO_SLOT_BAND: tuple[float, float] = (0.13, 0.31)


def read_formation_state_tokens(
    tokens: Sequence[Any], frame_size: tuple[int, int] | None
) -> dict[str, Any]:
    """The pure half: formation-page facts from OCR tokens and a frame size."""
    empty: dict[str, Any] = {
        "is_formation": False, "footer": [], "confirm": None, "confirm_norm": None,
        "troop_rows": [], "hero_slot_norms": [],
    }
    if not frame_size:
        return empty
    width, height = int(frame_size[0]), int(frame_size[1])
    if width <= 0 or height <= 0:
        return empty

    footer: list[str] = []
    confirm = None
    confirm_norm: list[float] | None = None
    troop_rows: list[dict[str, Any]] = []
    for token in tokens:
        text = str(getattr(token, "text", "") or "").strip()
        box = getattr(token, "box", None)
        if not text or not box:
            continue
        xs: list[float]
        ys: list[float]
        if len(box) == 4 and all(isinstance(p, (int, float)) for p in box) and not any(
            isinstance(p, (list, tuple)) for p in box
        ):
            # x, y, w, h
            bx, by, bw, bh = (float(v) for v in box)
            xs = [bx, bx + bw]
            ys = [by, by + bh]
        else:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
        cx = (min(xs) + max(xs)) / 2.0 / width
        cy = (min(ys) + max(ys)) / 2.0 / height
        if text in FOOTER_WORDS and text not in footer:
            footer.append(text)
            continue
        if text in CONFIRM_WORDS and cy > 0.85 and confirm is None:
            confirm = text
            confirm_norm = [round(cx, 4), round(cy, 4)]
            continue
        if cy < 0.85 and any(w in text for w in TROOP_ROW_WORDS) and cy > 0.3:
            if not any(row["label"] == text for row in troop_rows):
                troop_rows.append({
                    "label": text,
                    "tap_norm": [round(0.912, 4), round(cy, 4)],
                    "source": "CURRENT_FRAME_OCR",
                })

    is_formation = len(footer) >= 2 and confirm is not None
    hero_slot_norms = (
        [[round(x, 4), round(sum(HERO_SLOT_BAND) / 2.0, 4)] for x in HERO_SLOT_CENTRES]
        if is_formation else []
    )
    return {
        "is_formation": is_formation,
        "footer": footer,
        "confirm": confirm,
        "confirm_norm": confirm_norm,
        "troop_rows": troop_rows,
        "hero_slot_norms": hero_slot_norms,
    }


def read_formation_state(image_path, ocr) -> dict[str, Any]:
    """Read the formation page from a real frame through the project's OCR."""
    from PIL import Image

    with Image.open(image_path) as source:
        frame_size = source.size
    result = ocr.recognize(image_path)
    return read_formation_state_tokens(result.tokens, frame_size)
