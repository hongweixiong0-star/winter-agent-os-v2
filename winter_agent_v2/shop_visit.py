# -*- coding: utf-8 -*-
"""VISIT_WANDERING_MERCHANT -- read the merchant's stock on the real client and obey the
operator's spend policy.

Everything here is measured, and the measurements are recorded because three of them
contradicted a reasonable guess:

  1. **The cards print no item name.**  游荡商人, 神秘商店, 竞技商店 and 统帅市 all show
     icon + 剩余：N + price and nothing else.  So a rule keyed on a name cannot be evaluated
     from the card.
  2. **The name is available one tap deeper.**  Tapping a card opens 确定购买, which names
     the item and describes it.  A long press on the card's *icon* opens the same facts as a
     read-only tooltip; a long press on the *label* opens the purchase dialog.  This module
     uses the tap, because it always appears, and it dismisses the dialog by its own ✕ --
     the orange price button is never touched.
  3. **The Exp bottle is 英雄经验, not 统帅经验.**  Measured on the client:
     "1,000点英雄经验" / "50,000点英雄经验".  Reading it as 统帅经验 from the icon would have
     spent diamonds on the one item the operator's policy forbids.  The item the policy wants
     is the gold hexagon engraved "10" -- "10点统帅经验".

    Currency is read by colour, because it is an icon: the diamond is the only saturated blue
    thing a price pill ever contains.  Calibrated over 27 real price rows on saved frames
    (tools/shop_currency_hue_calibrate.py): 15/15 diamond rows scored blue_fraction 1.000,
    12/12 rows priced in 木/煤/肉/勋章/竞技币 scored 0.000.  A gap of 1.000, not a threshold
    picked by taste.

    ``press_back`` is bounded everywhere and never issued blind: in one exploration a blind
    loop of six of them walked out of the shop and raised the client's 「确认退出游戏吗？」.

The operator's policy, treated as CONFIRMED business input:

    游荡商人 : 资源换资源 -> 买 ; 钻石换统帅经验 -> 买 ; 其他钻石商品 -> 跳过
               只用免费刷新 (3/day), 绝不用钻石刷新
    Anything the policy does not cover is reported as ASK and is not acted on.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

# --------------------------------------------------------------------------- measured UI
NAV_SHOP = "商店"                     # exact text on the HOME bottom nav (6th of 6 items)
STORE_TABS = ("游荡商人", "神秘商店", "竞技商店", "统帅市")
TAB_BAND = 0.93                        # the store's tab strip lives in the bottom 7%
HOME_MARKERS = ("探险", "英雄", "背包", "联盟", "野外")
WANDERING_MARKERS = ("免费刷新", "下次刷新")
MYSTERY_MARKERS = ("刷新",)

# -- the alliance shop does NOT live behind the 商店 nav -------------------------------
# 联盟商店 is reached from the ALLIANCE page, which is a different branch of the bottom
# navigation entirely -- so the store-entry routine cannot be reused and the tab strip that
# holds 游荡商人/神秘商店/竞技商店/统帅市 is not involved at all.  The two hops were measured
# separately; each method below carries its own measurement.
NAV_ALLIANCE = "联盟"                  # exact text on the HOME bottom nav (5th of 6 items)
ALLIANCE_ENTRY = "联盟商店"             # the tile label on the ALLIANCE page
# The ALLIANCE page is a 2-column grid of eight labelled tiles.  Their names are the page's
# signature: measured 2026-10-05 from the saved live frame
# knowledge/perception/candidates/alliance_btn_shop__1ba620d5/context.png (720x1280), where all
# eight read cleanly, so the page is recognised from text and needs no template.
ALLIANCE_TILES = ("联盟战争", "联盟宝箱", "联盟领地", "据点争夺",
                  "联盟商店", "联盟科技", "实力排行", "联盟互助")
ALLIANCE_TILES_MIN = 4                 # 4 of 8 readable names is proof; OCR rarely gets all 8
# The shop behind that tile is its own page, and it is NOT a store tab: its bottom strip holds
# 今日 / 本周 (two different stocks), measured 2026-10-05.  It also carries a self-refresh
# banner -- 下次刷新：+ a countdown -- which is why the operator's 联盟商店 rule needs no
# refresh step at all: the shop re-rolls itself on a timer.
ALLIANCE_SHOP_TABS = ("今日", "本周")
ALLIANCE_SHOP_SELF_REFRESH = "下次刷新"
ALLIANCE_HEADER_BAND = 0.12            # the page's own 联盟商店 header sits at y=42/1280

DIALOG_TITLE = "确定购买"          # the purchase overlay, opened by tapping the card body
# Step two.  Tapping 确定购买's price button opens the client's own spend question
# (「购买确认」/「您是否要花费16钻石?」) with a second orange button; the goods only move on that
# second tap.  Measured 2026-10-05 -- the first attempt at a purchase "succeeded" while spending
# nothing, and only the diamond wallet exposed it.
CONFIRM_TITLE = "购买确认"
CONFIRM_PHRASE = "是否要花费"
# The read-only tooltip is keyed by its 「own quantity」 line.  OCR reads that line two ways --
# ``拥有数量：286,010,314`` and, on a smaller render, ``有数量：286,010,314`` (the 拥 dropped) --
# and the second form defeated the marker on 2026-10-05, which let the quantity line be mistaken
# for the item name.
TOOLTIP_MARKERS = ("拥有数量", "有数量")
TOOLTIP_MARKER = TOOLTIP_MARKERS[0]   # kept for callers that only need the canonical one
ICON_DY = 65                       # icon centre, measured: anchor_y-40/-70/-90 all hit it
ICON_DY_LADDER = (65, 45, 85)
BODY_DY_LADDER = (0, 15, 30, 45, 60, 80)   # the whole measured body zone, anchor+0 .. anchor+80
# Chrome that sits around the detail overlays, split by how it must be matched.  Substring
# matching is right for the overlay's own furniture; it is WRONG for the nav and tab names,
# because ``英雄`` appears inside ``英雄经验`` and inside the 神秘商店 rule's
# ``英雄组件自选箱`` -- a substring stopword there silently blanks out the two names the
# operator's policy is built on.
NAME_STOP_SUBSTR = (
    "确定购买", "拥有数量", "有数量", "获取来源", "使用后", "可用于", "可获得",
    "剩余", "下次刷新", "免费刷新", "购买", "取消", "关闭",
)
# A ``label：value`` line is furniture, never an item name.  Item names do contain digits
# (``5,000点英雄经验``, ``10点统帅经验``), so "no digits" would be wrong -- but a full-width colon
# immediately followed by digits appears only on label lines such as ``拥有数量：286,010,314``.
LABEL_VALUE = re.compile(r"^[^\d]{1,10}[:：]\s*[\d,]+$")
NAME_STOP_EXACT = (*STORE_TABS, *HOME_MARKERS, "商店", "刷新", "钻石商店", "确定")

CURRENCY_BLUE_MIN = 150                # absolute blue pixels; measured 0 vs 570-1048
CURRENCY_MIN_INK = 12                  # a dark icon (煤) has ~0 saturated pixels
BLUE_HUE = (85, 125)                   # OpenCV H, 0-179

RESOURCE_WORDS = ("肉", "食物", "木材", "木头", "木", "煤", "铁", "石", "钢")
COMMANDER_EXP = "统帅经验"

MAX_BACK_ON_ENTRY = 3
MAX_DIALOG_FRAMES = 3
FREE_REFRESH_PER_DAY = 3


@dataclass
class Card:
    """One purchasable slot, as read from the live card grid."""
    row: int
    col: int
    rest: int
    price_text: str
    price_xy: tuple[int, int]
    tap_xy: tuple[int, int]                  # point inside the card, from a recognised token
    price_is_diamond: bool
    discount: str | None = None
    currency_evidence: dict[str, Any] = field(default_factory=dict)
    name: str | None = None
    description: str | None = None
    verdict: str | None = None               # BUY | SKIP | ASK | NOT_EXECUTED
    reason: str = ""
    inspect_why: str | None = None           # why the purchase overlay could not be read

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "col": self.col, "rest": self.rest,
                "price": self.price_text, "price_xy": list(self.price_xy),
                "tap_xy": list(self.tap_xy), "diamond": self.price_is_diamond,
                "discount": self.discount, "currency": self.currency_evidence,
                "name": self.name, "description": self.description,
                "inspect_why": self.inspect_why,
                "verdict": self.verdict, "reason": self.reason}


# --------------------------------------------------------------------------- primitives
def _cjk(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def price_is_diamond(frame_rgb: np.ndarray, x: int, y: int) -> tuple[bool, dict[str, Any]]:
    """Is this price paid in diamonds?  Blue ink in the price area, counted in pixels.

    The test is an *absolute count* of blue pixels, not a fraction of the saturated pixels,
    because the price is printed on two different surfaces:

      * on the card, a white pill -- measured over 27 real price rows
        (tools/shop_currency_hue_calibrate.py): diamond rows carried 570-577 saturated blue
        pixels (fraction 1.000) and rows priced in 木/煤/肉/勋章/竞技币 carried 0-3
        (fraction 0.000);
      * on the purchase overlay, a large **orange** button, where the same diamond yields
        ~700 blue pixels but a fraction of only 0.21, because the orange paint dominates the
        saturated-pixel count.  A fraction rule therefore called a 140-diamond price "资源"
        and inverted the decision, which is how this was caught on 2026-10-05.
    """
    h_img, w_img = frame_rgb.shape[:2]
    hay = frame_rgb[max(0, y - 18):min(h_img, y + 18), max(0, x - 95):min(w_img, x + 40)]
    if hay.size == 0:
        return False, {"ink": 0, "blue_px": 0, "reason": "EMPTY_WINDOW"}
    hsv = cv2.cvtColor(hay, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sel = (s >= 120) & (v >= 130)
    ink = int(sel.sum())
    hue = h[sel]
    blue_px = int(((hue >= BLUE_HUE[0]) & (hue <= BLUE_HUE[1])).sum())
    evidence = {"ink": ink, "blue_px": blue_px,
                "blue_fraction": round(blue_px / ink, 3) if ink else 0.0,
                "median_hue": int(np.median(hue)) if ink else None}
    if blue_px >= CURRENCY_BLUE_MIN:
        return True, evidence
    evidence["reason"] = "TOO_LITTLE_INK" if ink < CURRENCY_MIN_INK else "NO_BLUE_INK"
    return False, evidence


# The purchase overlay's price lives on one big orange button.  Measured on the 2026-10-05 frames
# (tools/shop_overlay_diag.py): a single connected orange blob of 16,066-16,373 px at
# bbox=[222,795,276,71] -- i.e. x 222-498, y 795-866 -- with the price glyphs inside it.
ORANGE_HUE = (8, 28)
ORANGE_SAT_MIN = 120
ORANGE_VAL_MIN = 150
# Area alone does not separate the button from the shop's own orange paint.  Measured: the price
# button is a wide, short pill -- 276x71, w/h 3.89, 15800-16400 px on all five live overlays --
# while the gold hexagon icon of the 统帅经验 offer is a 75x62 blob at 3116 px, i.e. 1.21 wide per
# unit of height.  Under the old 3000 px floor that icon *was* a button, and on 2026-10-05 it made
# a live probe believe an overlay was open on a plain shop page
# (dataset/evidence/shop_zone_map_20261005T033937/map_03_tab_游荡商人.png, bbox [101,788,75,62]).
# The card it fires on is exactly the one the operator's policy says to buy.
ORANGE_MIN_PX = 8000
ORANGE_MIN_ASPECT = 2.0


def orange_price_button(frame_rgb: np.ndarray) -> dict[str, Any] | None:
    """Locate the purchase overlay's price button by its own paint colour.

    This exists because picking the price by *elimination* does not work.  The naive rule --
    "the lowest number in the overlay, and nothing else may be on another row" -- aborted with
    ``PRICE_BUTTON_AMBIGUOUS`` on two of six overlays in the 2026-10-05 pass, even though a human
    reads those overlays instantly as 铁矿 (安全) / 💎100.  The intruder was the quantity slider:
    the whole-frame pass read it as ``1`` (one character, filtered out) while the grid pass read
    the same pixels as ``00`` (two characters, not filtered out) -- so a duplicate at y 703
    collided with the real price at y 831.

    Locating the button positively removes that whole class of failure: the price is the number
    *inside the orange blob*, and a slider handle is never orange.

    "Orange blob" must also mean *wide and short*.  The shop's own offers include a gold hexagon
    whose icon is orange, and on the 2026-10-05 roll that icon cleared a bare area floor and was
    reported as a price button on a plain shop page -- so a probe that asked "is an overlay open?"
    answered yes, dismissed a dialog that did not exist, and walked out of the store.  The button
    and the icon are separated by shape, not by area: 3.89 wide per unit of height against 1.21.
    """
    h_img = frame_rgb.shape[0]
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = ((hue >= ORANGE_HUE[0]) & (hue <= ORANGE_HUE[1])
            & (sat >= ORANGE_SAT_MIN) & (val >= ORANGE_VAL_MIN)).astype(np.uint8)
    mask[: int(0.45 * h_img)] = 0          # the merchant's own orange art lives up there
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    best_i, best_area = None, 0
    for i in range(1, count):
        _x, _y, bw, bh, area = stats[i]
        if bh > 0.25 * h_img:              # a full-height orange field is scenery, not a button
            continue
        if area < ORANGE_MIN_PX or bw < ORANGE_MIN_ASPECT * bh:
            continue                        # an icon is roughly square; the button is a wide pill
        if area > best_area:
            best_i, best_area = i, int(area)
    if best_i is None:
        return None
    x, y, w, h, area = (int(v) for v in stats[best_i])
    return {"bbox": [x, y, w, h], "centre": [int(centroids[best_i][0]), int(centroids[best_i][1])],
            "px": area}


def _inside(box: list[int] | tuple[int, ...], x: float, y: float) -> bool:
    return box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]


BUTTON_ZOOM = 4
GLYPH_SAT_MAX = 80
GLYPH_VAL_MIN = 190


def _numbers_on_white(page_rgb: np.ndarray) -> list[str]:
    """OCR a black-on-white rendering and return the numeric tokens, longest digits first."""
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    toks = read_all(Image.fromarray(page_rgb))
    nums = [t["text"].strip() for t in toks
            if re.fullmatch(r"[\d,]+万?", (t["text"] or "").strip())]
    return sorted(nums, key=lambda s: -len(re.sub(r"\D", "", s)))


def read_button_price(frame_rgb: np.ndarray, box: list[int]) -> tuple[str | None, dict[str, Any]]:
    """Read the price off the purchase button by re-drawing its glyphs as black on white.

    Why this exists (measured 2026-10-05, ``dataset/evidence/shop_visit_wandering_20261005T024627``):
    the price on the button is **white with a dark outline, painted on orange**.  OCR reading those
    pixels as they are does not merely miss the number, it *misreads* it -- the frame whose button
    says ``19`` comes back as ``6L`` at 1x and ``V1`` at 3x, and the whole-frame pass returned no
    price token at all.  That is how a legitimate 钻石换统帅经验 purchase came back
    ``PRICE_NOT_IN_BUTTON(0 in, 1 total)`` and was skipped.

    Isolating the near-white, unsaturated glyphs and re-rendering them as black on white -- the
    polarity OCR expects -- reads the same frames correctly: ``19``, ``16``, ``140``, ``600``.

    The button's position is already known exactly, so the price never has to be found in the whole
    frame; a 276x71 crop is also far cheaper than another full-frame pass.
    """
    x, y, w, h = (int(v) for v in box)
    pad = 4
    crop = frame_rgb[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    if crop.size == 0:
        return None, {"reason": "EMPTY_CROP"}
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    glyph = (hsv[..., 1] <= GLYPH_SAT_MAX) & (hsv[..., 2] >= GLYPH_VAL_MIN)
    page = np.repeat(np.where(glyph[..., None], 0, 255).astype(np.uint8), 3, axis=2)
    page = cv2.resize(page, None, fx=BUTTON_ZOOM, fy=BUTTON_ZOOM, interpolation=cv2.INTER_NEAREST)
    found = _numbers_on_white(page)
    evidence = {"glyph_px": int(glyph.sum()), "candidates": found, "method": "glyph_mask"}
    return (found[0] if found else None), evidence


def group_remaining(tokens: list[dict]) -> list[dict]:
    """One entry per card from the 剩余：N labels, de-duplicated.

    OCR splits some labels into ``剩余`` and ``：1``; grouping by proximity restores one
    anchor per card without inventing any geometry.
    """
    raw = [t for t in tokens if "剩余" in t["text"]]
    groups: list[dict] = []
    for t in sorted(raw, key=lambda t: (t["centre"][1], t["centre"][0])):
        x, y = int(t["centre"][0]), int(t["centre"][1])
        for g in groups:
            if abs(g["x"] - x) < 45 and abs(g["y"] - y) < 26:
                g["tokens"].append(t)
                g["x"] = (g["x"] + x) // 2
                g["y"] = (g["y"] + y) // 2
                break
        else:
            groups.append({"x": x, "y": y, "tokens": [t]})
    for g in groups:
        m = re.search(r"(\d+)", "".join(t["text"] for t in g["tokens"]))
        g["rest"] = int(m.group(1)) if m else 0
    return groups


def _overlaps(a: dict, b: dict) -> bool:
    ax, ay, aw, ah = a["box"]
    bx, by, bw, bh = b["box"]
    ix = min(ax + aw, bx + bw) - max(ax, bx)
    iy = min(ay + ah, by + bh) - max(ay, by)
    return ix > 0 and iy > 0 and ix * iy > 0.5 * min(aw * ah, bw * bh)


def prefer_whole(tokens: list[dict]) -> list[dict]:
    """Drop the band re-reads of text the full-frame pass already read correctly.

    ``read_all`` runs OCR over several regions and reports each hit with its ``source``.  A
    region crop that severs a number reports only the tail: on 2026-10-04 the whole-frame pass
    read the price ``15,000`` while the right-rail band read the same pixels as ``,000``.
    Both are valid tokens, both are numeric, and the band one sat further right -- so a reader
    that simply takes "the numeric token under the 剩余 label" can pick the truncated one and
    believe a 15,000-meat price is a 3-digit number.  Band hits that duplicate a whole-frame
    hit are therefore discarded; band hits over regions the full pass missed are kept.
    """
    whole = [t for t in tokens if not str(t.get("source", "")).startswith("band:")]
    keep = list(whole)
    for t in tokens:
        if str(t.get("source", "")).startswith("band:") and not any(_overlaps(t, w) for w in whole):
            keep.append(t)
    return keep


def merge_fragments(tokens: list[dict]) -> list[dict]:
    """Join a number that OCR really did split, using the token boxes for adjacency.

    Only boxes that touch (a gap between -8 and 12 px) are joined, and only into a well-formed
    number.  Two earlier versions were wrong in opposite directions: one merged anything within
    70 px in the same row -- which produced ``15,000,000`` from two unrelated reads -- and one
    discarded the fragments outright when the join did not validate, which would *lose* a price
    rather than merely fail to stitch it.  Unjoined and unjoinable fragments are always kept.

    The third version, caught on 2026-10-05, was the worst of the three: it selected the tokens to
    *join* with ``[\\d,，]+`` and then rebuilt its return value out of that same selection, so every
    token that was not a bare digit run was **deleted** rather than passed through.  ``67万`` and
    ``25万`` are not bare digit runs.  Because ``read_cards`` takes this function's output as its
    entire universe of numbers, the effect was that every card priced in 肉/木/煤/铁 for a
    six-figure amount disappeared from the read -- and those are precisely the 资源换资源 cards the
    operator's policy says to **BUY**.  A pass could therefore look like it had read "4 of 6 cards"
    while the two it never saw were the only two it was supposed to buy.  It is a merger: the
    tokens it does not join must come out the other side untouched.
    """
    nums = [t for t in tokens if re.fullmatch(r"[\d,，]+", t["text"].strip())]
    num_ids = {id(t) for t in nums}
    merged = [dict(t, text=t["text"].strip().replace("，", ","), centre=tuple(t["centre"]))
              for t in tokens if id(t) not in num_ids]
    used: set[int] = set()
    for t in sorted(nums, key=lambda t: t["centre"][0]):
        if id(t) in used:
            continue
        group = [t]
        used.add(id(t))
        while True:
            right = max(group, key=lambda g: g["box"][0] + g["box"][2])
            nxt = [o for o in nums
                   if id(o) not in used
                   and abs(o["centre"][1] - right["centre"][1]) < 14
                   and -8 < o["box"][0] - (right["box"][0] + right["box"][2]) < 12]
            if not nxt:
                break
            pick = min(nxt, key=lambda o: o["box"][0])
            group.append(pick)
            used.add(id(pick))
        text = "".join(g["text"].strip() for g in sorted(group, key=lambda g: g["box"][0]))
        text = text.replace("，", ",")
        if not re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", text):
            merged.extend(dict(g, text=g["text"].strip().replace("，", ","),
                               centre=tuple(g["centre"])) for g in group)
            continue
        xs = [g["centre"][0] for g in group]
        ys = [g["centre"][1] for g in group]
        merged.append({"text": text, "centre": (sum(xs) / len(xs), sum(ys) / len(ys)),
                       "box": group[0]["box"], "source": group[0].get("source")})
    return merged


def read_cards(frame_rgb: np.ndarray, tokens: list[dict]) -> list[Card]:
    """Pair each card's 剩余 anchor with the price printed beneath it, and read the currency."""
    tokens = prefer_whole(tokens)
    h_img = frame_rgb.shape[0]
    numbers = [t for t in merge_fragments(tokens)
               if re.fullmatch(r"[\d,]+万?", t["text"].strip())
               and t["centre"][1] > 0.28 * h_img]
    discounts = [t for t in tokens if re.fullmatch(r"-\s*\d+\s*%", t["text"].strip().replace(" ", ""))]

    anchors = group_remaining(tokens)
    rows = sorted({g["y"] // 130 for g in anchors})
    cols = sorted({g["x"] // 150 for g in anchors})
    cards: list[Card] = []
    for g in anchors:
        below = [t for t in numbers
                 if t["centre"][1] > g["y"] + 10 and abs(t["centre"][0] - g["x"]) < 95]
        if below:
            price = min(below, key=lambda t: t["centre"][1])
            px, py = int(price["centre"][0]), int(price["centre"][1])
            diamond, evidence = price_is_diamond(frame_rgb, px, py)
            price_text = price["text"].strip()
        else:
            # No price token under this anchor.  The card is still kept.
            #
            # The list price is only ever used to *print* the report: the verdict comes from the
            # purchase overlay's own name and price, read live, moments before buying.  Dropping
            # the card here -- which is what this function did -- therefore discarded a card that
            # could still be evaluated in full.  On 2026-10-05 that was not hypothetical: OCR
            # missed r1c0's price pill on the 02:19 roll and the pass reported "read 5 cards".
            price, px, py = None, g["x"], g["y"]
            diamond, evidence = False, {"reason": "LIST_PRICE_UNREAD"}
            price_text = ""
        # The -N% badge is printed at the card's top-left, i.e. ABOVE its 剩余 anchor.  So the
        # badge belongs to the first anchor below it in the same column -- no fixed offset,
        # which is what the first live pass got wrong (it looked 146 px up and found nothing).
        same_col = [a for a in anchors if abs(a["x"] - g["x"]) < 110 and a["y"] > g["y"] - 10]
        mine = min(same_col, key=lambda a: a["y"]) if same_col else None
        disc = None
        if mine is g:
            above = [d for d in discounts
                     if abs(d["centre"][0] - g["x"]) < 110
                     and g["y"] - 220 < d["centre"][1] < g["y"] + 10]
            if above:
                disc = max(above, key=lambda d: d["centre"][1])["text"].replace(" ", "")
        cards.append(Card(
            row=rows.index(g["y"] // 130), col=cols.index(g["x"] // 150),
            rest=g["rest"], price_text=price_text,
            price_xy=(px, py), tap_xy=(g["x"], g["y"]),
            price_is_diamond=diamond, discount=disc, currency_evidence=evidence))
    return cards


def item_name_from_dialog(tokens: list[dict]) -> tuple[str | None, str | None]:
    """Pull the item name and its description out of whichever detail overlay is open.

    Two overlays name the item and they lay out differently, so the reader keys on the line
    structure rather than on the overlay:

      * the read-only tooltip (「拥有数量」) is  name / 拥有数量：N / 使用后获得…  -- so the name
        is the item line immediately ABOVE 拥有数量;
      * the purchase overlay (「确定购买」) is  确定购买 / name / description -- so the name is
        the item line at the top.

    Ties go to the longest token on that line, which is what separates ``10点统帅经验`` from
    the icon label's OCR fragment ``10点统帅`` printed on the very same line.
    """
    toks = prefer_whole(tokens)
    cands = [t for t in toks
             if _cjk(t["text"]) >= 2
             and not LABEL_VALUE.match(t["text"].strip())
             and not any(w in t["text"] for w in NAME_STOP_SUBSTR)
             and t["text"].strip() not in NAME_STOP_EXACT]
    if not cands:
        return None, None
    own = [t for t in toks if any(m in t["text"] for m in TOOLTIP_MARKERS)]
    anchor_y = min(int(t["centre"][1]) for t in own) if own else None
    if anchor_y is not None:
        above = [t for t in cands if int(t["centre"][1]) < anchor_y]
        if above:
            line = max(int(t["centre"][1]) for t in above)
            cands = [t for t in above if int(t["centre"][1]) >= line - 14]
        else:
            cands = []
    else:
        top = min(int(t["centre"][1]) for t in cands)
        cands = [t for t in cands if int(t["centre"][1]) <= top + 14]
    name = max(cands, key=lambda t: (_cjk(t["text"]), len(t["text"])))["text"] if cands else None
    desc = next((t["text"] for t in toks
                 if any(w in t["text"] for w in ("使用后", "让1个", "可用于", "可获得"))), None)
    return name, desc


def decide_wandering(name: str | None, diamond: bool) -> tuple[str, str]:
    """The operator's 游荡商人 policy, applied literally; uncovered -> ASK, never a guess."""
    if name is None:
        return "ASK", "no_name_readable"
    if diamond:
        if COMMANDER_EXP in name:
            return "BUY", "钻石换统帅经验"
        return "SKIP", f"其他钻石商品({name})"
    if any(w in name for w in RESOURCE_WORDS):
        return "BUY", f"资源换资源({name})"
    return "ASK", f"资源计价但商品不是资源({name}) —— 策略未覆盖"


# -- 神秘商店 -------------------------------------------------------------------------------
# The operator's rule, treated as CONFIRMED business input:
#
#     名称含「英雄组件自选箱」 且 折扣 = 50%  ->  买 ; 否则跳过
#     只用免费刷新（基础 1 次/天；有艾格尼丝后最多 5 次），绝不用钻石刷新
#
# Measured on the live client 2026-10-05 (dataset/evidence/shop_observe_mystery_20261005T054637):
#
#   * the page is a **3 x 3 grid -- nine slots**, not the merchant's six; anchors at
#     y=609 / 898 / 1186, columns x≈140 / 361 / 582, and the third row's *prices* fall below
#     the fold (its badges and 剩余 still read);
#   * its prices are the **gold coin**, not diamonds -- so the diamond wallet is not the spend
#     witness here and a diamond-shaped reading of "did it cost anything" would be wrong;
#   * the cards print **no item name**, exactly like the merchant's;
#   * tapping the card body opens the same 确定购买 overlay, with the price button at the very
#     same bbox [222,795,276,71] (276x71, 15,901 px) -- the same dialog component;
#   * the name the client prints is 「第3代英雄组件自选箱」, which *contains* 英雄组件自选箱, so
#     the rule is matched as a substring and never against the whole string;
#   * the refresh control reads **免费刷新** here.  (The docstring on ``free_refresh`` claimed
#     神秘商店's control reads 刷新 💎100; that was never measured on this page and is wrong for
#     the free one.  Requiring the literal 免费 is still the right guard, and is kept.)
MYSTERY_NAME = "英雄组件自选箱"
MYSTERY_DISCOUNT = 50


def discount_percent(badge: str | None) -> int | None:
    """The card's own -N% badge as an integer, or None if it does not really say one.

    OCR reads the badge correctly on 神秘商店 (measured: -10% and -20% on five of nine cards)
    but also emits near-miss fragments of the same badge (``%0L-``, ``-10``, ``OL``).  The
    badge is trusted only when a number and a percent sign actually appear together, because
    the whole point of the rule is that 50 has to mean 50.
    """
    if not badge:
        return None
    m = re.search(r"(\d{1,3})\s*%", str(badge))
    return int(m.group(1)) if m else None


def decide_mystery(name: str | None, discount: str | None) -> tuple[str, str]:
    """The operator's 神秘商店 policy, applied literally.

    名称含「英雄组件自选箱」且折扣=50% -> 买；否则跳过。

    A card with **no badge at all** is not a reading failure: the badge prints the discount, so
    no badge means full price, which is "otherwise" and therefore 跳过.  That distinction was
    paid for on the first live pass (2026-10-05 05:55): three of the nine cards carry no badge,
    and answering ASK for them would have buried the four cards that *do* say -10%/-20% under
    three pieces of noise.  ASK is kept for the one case that really is unanswerable -- a name
    that could not be read, where even "is this the item the rule names" is unknown.

    The never-overspend direction is structural rather than argued: BUY is reachable only from
    ``pct == 50`` exactly, so every failure mode of the badge reader (missing, garbled, absent)
    lands on 跳过.  The cost of a badge that exists but will not read is a *missed* buy, never a
    wrong one, and the report prints what each card's badge actually said.
    """
    if name is None:
        return "ASK", "no_name_readable"
    if MYSTERY_NAME not in name:
        return "SKIP", f"规则外商品({name})"
    pct = discount_percent(discount)
    if pct == MYSTERY_DISCOUNT:
        return "BUY", f"{MYSTERY_NAME} 且折扣={pct}%({name})"
    if pct is None:
        return "SKIP", (f"{MYSTERY_NAME} 但卡上没有折扣徽标（读到 {discount!r}）"
                        f"—— 不是{MYSTERY_DISCOUNT}%就不买")
    return "SKIP", f"{MYSTERY_NAME} 但折扣={pct}%（不是{MYSTERY_DISCOUNT}%）"


def decide_alliance(name: str | None) -> tuple[str, str]:
    """联盟商店's rule, exactly as the operator stated it: 名称含「统帅经验」-> 买, 其他跳过。

    This reuses ``COMMANDER_EXP``, the constant the 游荡商人 rule already keys on, because the
    client prints the same string -- and that reuse is load-bearing.  The live client carries
    *two* similarly named experience bottles: 英雄经验 ("50,000点英雄经验", measured 2026-10-05)
    and 统帅经验 ("10点统帅经验").  英雄经验 does **not** contain 统帅经验, so a rule written
    against the operator's words skips it without a special case.  Two rules that look alike are
    not alike; neither is two items whose icons look alike.

    No refresh branch exists here: the operator's 联盟商店 policy has none, and this shop has no
    refresh control to spend on.
    """
    if name is None:
        return "ASK", "no_name_readable"
    if COMMANDER_EXP in name:
        return "BUY", f"名称含「{COMMANDER_EXP}」({name})"
    return "SKIP", f"规则外商品({name})"


def top_bar_numbers(tokens: list[dict], height: int) -> list[tuple[int, int, str]]:
    """The top bar's large comma-grouped numbers, left to right, de-duplicated.

    The store's top bar carries **two** currencies and the order is fixed: 钻石 first, the
    gold coin second (measured 2026-10-05: 294,752 at x≈451 then 3,290 at x≈630).  ``visit``
    reads only the first, which is correct for a diamond shop and wrong for 神秘商店 -- so
    this returns both and the caller says which one it means by position, not by guessing.
    """
    rows = [t for t in tokens
            if re.fullmatch(r"[\d,]{3,}", t["text"].strip()) and t["centre"][1] < 0.06 * height]
    rows.sort(key=lambda t: t["centre"][0])
    out: list[tuple[int, int, str]] = []
    for t in rows:
        n = _amount([t["text"]])
        if n is None:
            continue
        if out and abs(t["centre"][0] - out[-1][0]) < 30:
            continue            # an OCR fragment of the number that was just read
        out.append((int(t["centre"][0]), n, t["text"].strip()))
    return out


# --------------------------------------------------------------------------- the visitor
class ShopVisitor:
    """Drives the store with recognised elements only; no click position is ever stored."""

    def __init__(self, ad, out_dir: Path, log: Callable[[str], None] = print) -> None:
        self.ad = ad
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log = log
        self.trace: list[dict[str, Any]] = []
        self._back_used = 0
        self._tap_refused = 0
        # Evidence filenames carry the round.  Without it, round 2's ``40_card_r0c2_buy0_0``
        # overwrote round 1's, and a re-read of the evidence then reconstructed the wrong roll.
        self.tag_prefix = ""

    # -- frame helpers -----------------------------------------------------
    def _frame(self) -> np.ndarray:
        """Capture one frame, no OCR.

        A full ``read_all`` on a 720x1280 shop frame is ~20 s of CPU, and a purchase attempt can
        need a dozen tries -- so the *decision* to read a frame must come before the reading.
        """
        for _ in range(3):
            f = self.ad.capture()
            if f is not None:
                return np.asarray(f)
            time.sleep(0.4)
        raise RuntimeError("SCREENCAP_FAILED")

    def see(self, tag: str, save: bool = True) -> tuple[np.ndarray, list[dict]]:
        from winter_agent_v2.ocr_full import read_all
        from PIL import Image
        img = self._frame()
        tag = f"{self.tag_prefix}{tag}"
        if save:
            Image.fromarray(img).save(self.out_dir / f"{tag}.png")
        toks = read_all(Image.fromarray(img))
        self.trace.append({"step": tag, "tokens": [t["text"] for t in toks]})
        return img, toks

    def relocate(self, card: Card) -> tuple[int, int] | None:
        """Re-derive a card's tap point from a fresh frame.

        The anchor read at the top of a round is a *reading*, not a coordinate to keep: the shop
        re-rolls slots on its own (three different items in one slot inside three minutes, measured
        2026-10-05), and a re-render can move what is where.  Used only after a tap has failed, so
        the ordinary path never pays for it.
        """
        img, toks = self.see("39_relocate", save=False)
        fresh = next((c for c in read_cards(img, toks) if (c.row, c.col) == (card.row, card.col)),
                     None)
        return fresh.tap_xy if fresh else None

    @staticmethod
    def _at(toks: list[dict], text: str, *, band: float | None = None, h: int = 0,
            exact: bool = True) -> dict | None:
        hits = []
        for t in toks:
            s = t["text"].strip()
            if (s == text) if exact else (text in s):
                if band is not None and t["centre"][1] < band * h:
                    continue
                hits.append(t)
        return max(hits, key=lambda t: t["centre"][1]) if hits else None

    @staticmethod
    def _any(toks: list[dict], words: tuple[str, ...]) -> list[str]:
        return [t["text"] for t in toks if any(w in t["text"] for w in words)]

    def _tap_xy(self, xy) -> None:
        """One tap, with its *delivery* checked.

        ``ad.click`` returns ``(ok, why)`` and this used to discard it -- so a refused click was
        indistinguishable from a click the client simply ignored.  That is exactly the ambiguity
        the 2026-10-05 passes left behind: two cards absorbed 9 and 12 taps without producing an
        overlay, while the same coordinates opened it in a probe twenty minutes later.  Now a
        refusal is counted, logged, and reported, so "nothing happened" can be told apart from
        "the tap never left the host".
        """
        res = self.ad.click(int(xy[0]), int(xy[1]))
        if isinstance(res, tuple) and res and not res[0]:
            self._tap_refused += 1
            self.log(f"      !! tap at {[int(xy[0]), int(xy[1])]} REFUSED ({res[1]})")
        time.sleep(1.6)

    def _back(self, why: str) -> None:
        """A counted, purposeful back press.  Never issued in a loop without a re-check."""
        self._back_used += 1
        self.log(f"      back #{self._back_used} ({why})")
        self.ad.press_back()
        time.sleep(1.5)

    # -- steps -------------------------------------------------------------
    def on_store_page(self, toks: list[dict], h: int) -> bool:
        return any(self._at(toks, tab, band=TAB_BAND, h=h) for tab in STORE_TABS)

    def on_home(self, toks: list[dict], h: int) -> bool:
        return sum(bool(self._at(toks, m, band=0.86, h=h)) for m in HOME_MARKERS) >= 3

    def on_alliance_page(self, toks: list[dict], h: int) -> bool:
        """Is this the ALLIANCE page?  Counted from its own tile labels, not from a template.

        The eight tiles are a stable, high-contrast block of text, so the page identifies
        itself from OCR alone -- the same discipline ``on_home`` uses.  Note the band: the
        bottom bar on this page holds 成员/激励/设置, so a stray 联盟 in the *bottom* strip
        would mean we are somewhere else (HOME, whose nav has 联盟) and must not count here.
        """
        body = [t for t in toks if t["centre"][1] < 0.90 * h]
        return sum(1 for m in ALLIANCE_TILES
                   if any(m in t["text"] for t in body)) >= ALLIANCE_TILES_MIN

    def on_alliance_shop_page(self, toks: list[dict], h: int) -> bool:
        """Is this the 联盟商店 page (the one behind the ALLIANCE tile)?

        Two independent markers, both measured 2026-10-05 on frame
        ``20_alliance_shop_page_raw.png``, and both required:

          * the page's own header reads **联盟商店** at y=42, i.e. inside the top 12% -- while
            the ALLIANCE page's *tile* of the same name sits at y=938, so the band keeps the
            two apart;
          * the self-refresh banner reads **下次刷新：** at y=151, which no other observed page
            carries.

        Requiring both is what stops this from becoming a substring trap: ``联盟商店`` alone
        appears on the ALLIANCE page too.
        """
        header = any("联盟商店" in t["text"]
                     for t in toks if t["centre"][1] < ALLIANCE_HEADER_BAND * h)
        banner = any(ALLIANCE_SHOP_SELF_REFRESH in t["text"] for t in toks)
        return header and banner

    def _clear_exit_prompt(self, toks: list[dict]) -> bool:
        """The client raises 「确认退出游戏吗？」 when back presses stack up.  Cancel it."""
        if "退出游戏" not in " ".join(t["text"] for t in toks):
            return False
        cancel = self._at(toks, "取消", exact=True)
        if cancel is not None:
            self.log("      exit prompt detected -- tapping its 取消")
            self._tap_xy(cancel["centre"])
        else:
            self._back("exit prompt without a readable 取消")
        return True

    def _clear_spend_dialogs(self, toks: list[dict]) -> bool:
        """Close a spend dialog left open by an interrupted pass -- and never tap its button.

        A pass can be stopped between the two taps (measured: the 2026-10-05 02:33 pass ended with
        「购买确认」/「您是否要花费16钻石?」 still on screen).  Leaving that armed is both untidy and
        dangerous: the next tap anywhere near its button would spend without a fresh decision.
        """
        texts = " ".join(t["text"] for t in toks)
        if not any(k in texts for k in (DIALOG_TITLE, CONFIRM_TITLE, CONFIRM_PHRASE)):
            return False
        close = next((t for t in toks if t["text"].strip() in ("X", "x", "✕", "×", "╳")), None)
        if close is None:
            return False
        self.log("   a leftover spend dialog was open -- closing it with its ✕"
                 " (its own button is never tapped)")
        self._tap_xy(close["centre"])
        return True

    def enter(self) -> tuple[np.ndarray, list[dict]]:
        """Reach the store from wherever the client happens to be.

        The first live pass checked ``商店`` *before* each back press and raised after the last
        one, so the frame the last back produced -- HOME, with 商店 plainly readable at
        (420,1258) -- was captured and then never looked at.  Every navigation is now followed
        by a check, and the loop is allowed one more check than it is backs.
        """
        img, toks = self.see("00_entry")
        h, w = img.shape[:2]
        for attempt in range(MAX_BACK_ON_ENTRY + 1):
            if self._clear_spend_dialogs(toks):
                img, toks = self.see(f"00_after_leftover{attempt}")
                continue
            if self.on_store_page(toks, h):
                self.log(f"   reached the store page ({self._any(toks, STORE_TABS)})")
                return img, toks
            if self._clear_exit_prompt(toks):
                img, toks = self.see(f"00_after_exit{attempt}")
                continue
            nav = self._at(toks, NAV_SHOP, band=0.86, h=h)
            if nav is not None:
                self.log(f"   tapping the HOME nav 商店 at {list(map(int, nav['centre']))}"
                         f"  (frame {w}x{h}, attempt {attempt})")
                self._tap_xy(nav["centre"])
                img, toks = self.see(f"01_shop_in{attempt}")
                if self.on_store_page(toks, h):
                    # The store can appear on the *last* attempt, and this used to `continue`
                    # into an exhausted ``range`` and raise -- discarding the frame it had just
                    # verified.  Measured 2026-10-05 05:42: AUTO was still driving the client
                    # when the pass began, so the tap on attempt 0 landed on the beast page and
                    # only attempt 3's re-tap reached the store.  The pass then reported
                    # ``SHOP_ENTRY_FAILED at unknown page`` while its own evidence frame
                    # (``01_shop_in3.png``) showed all four tabs, 游荡商人 x=98 / 神秘商店 x=302 /
                    # 竞技商店 x=507 / 统帅市 x=684, every one inside the tab band.  The absence
                    # of the "did not appear" line is what proved this branch had been taken.
                    self.log(f"   reached the store page ({self._any(toks, STORE_TABS)})")
                    return img, toks
                self.log("   tapped 商店 but the store page did not appear")
                continue
            if self.on_home(toks, h) and attempt >= MAX_BACK_ON_ENTRY:
                break
            if attempt < MAX_BACK_ON_ENTRY:
                self._back(f"no 商店 nav visible (attempt {attempt})")
                img, toks = self.see(f"01_before_shop{attempt}")
        raise RuntimeError(
            "SHOP_ENTRY_FAILED at {}: visible {}".format(
                "HOME" if self.on_home(toks, h) else "unknown page",
                [t["text"] for t in toks][:24]))

    def enter_alliance(self) -> tuple[np.ndarray, list[dict]]:
        """Reach the ALLIANCE page from wherever the client happens to be.

        Same shape as ``enter`` and for the same measured reason: every action is followed by a
        check, and the loop is allowed one more check than it is backs, because the frame an
        action produced is evidence and discarding it is exactly how the 商店 entry lost a pass
        on 2026-10-05.

        One extra rule here that the store entry does not need: the store page's bottom bar has
        no 联盟 item, so being on the store page means the 联盟 nav cannot be tapped from here
        and the page must be left first.  Pressing back off the store lands on HOME, which does
        carry it.
        """
        img, toks = self.see("A0_entry")
        h, w = img.shape[:2]
        for attempt in range(MAX_BACK_ON_ENTRY + 1):
            if self._clear_spend_dialogs(toks):
                img, toks = self.see(f"A0_after_leftover{attempt}")
                continue
            if self.on_alliance_page(toks, h):
                self.log(f"   reached the ALLIANCE page ({self._any(toks, ALLIANCE_TILES)})")
                return img, toks
            if self.on_store_page(toks, h):
                self._back("on the store page, whose bottom bar has no 联盟")
                img, toks = self.see(f"A1_left_store{attempt}")
                continue
            if self._clear_exit_prompt(toks):
                img, toks = self.see(f"A0_after_exit{attempt}")
                continue
            nav = self._at(toks, NAV_ALLIANCE, band=0.86, h=h)
            if nav is not None:
                self.log(f"   tapping the HOME nav 联盟 at {list(map(int, nav['centre']))}"
                         f"  (frame {w}x{h}, attempt {attempt})")
                self._tap_xy(nav["centre"])
                img, toks = self.see(f"A2_alliance_in{attempt}")
                if self.on_alliance_page(toks, h):
                    self.log(f"   reached the ALLIANCE page"
                             f" ({self._any(toks, ALLIANCE_TILES)})")
                    return img, toks
                self.log("   tapped 联盟 but the alliance page did not appear")
                continue
            if self.on_home(toks, h) and attempt >= MAX_BACK_ON_ENTRY:
                break
            if attempt < MAX_BACK_ON_ENTRY:
                self._back(f"no 联盟 nav visible (attempt {attempt})")
                img, toks = self.see(f"A1_before_alliance{attempt}")
        raise RuntimeError(
            "ALLIANCE_ENTRY_FAILED at {}: visible {}".format(
                "HOME" if self.on_home(toks, h) else "unknown page",
                [t["text"] for t in toks][:24]))

    def open_alliance_shop(self) -> tuple[np.ndarray, list[dict]]:
        """Tap the ALLIANCE page's 联盟商店 tile, and say what came up.

        The tile is *read from a fresh frame*, never remembered.  The prior measurement lives in
        ``knowledge/perception/candidates/alliance_btn_shop__1ba620d5/metadata.yaml``: on a
        720x1280 frame the label box is ``x_norm 0.2361, y_norm 0.7039, w_norm 0.2111,
        h_norm 0.0578``, i.e. rectangle (170,901)-(322,975), centre **(246, 938)**, with the row's
        red dot measured at (335,884).  That is a prior to *check*, not a coordinate to fire at,
        so the tap target is the freshly OCR'd label and the value above is only used by the
        observer to confirm the two agree.

        Finding the label is allowed more than one frame: the page fades in its tile grid, and a
        capture taken mid-fade has no labels to read -- the same failure ``select_tab`` records.
        """
        node = None
        for attempt in range(3):
            img, toks = self.see(f"A3_at_{ALLIANCE_ENTRY}", save=attempt == 2)
            node = self._at(toks, ALLIANCE_ENTRY, exact=False)
            if node is not None:
                break
            time.sleep(0.9)
        if node is None:
            raise RuntimeError(f"ALLIANCE_SHOP_TILE_NOT_FOUND:{ALLIANCE_ENTRY}")
        self.log(f"   tapping {ALLIANCE_ENTRY} at {list(map(int, node['centre']))}")
        self._tap_xy(node["centre"])
        img, toks = self.see("A4_alliance_shop_page")
        if self.on_alliance_page(toks, img.shape[0]):
            raise RuntimeError("ALLIANCE_SHOP_DID_NOT_OPEN: the tile grid is still on screen")
        if not self.on_alliance_shop_page(toks, img.shape[0]):
            # Not fatal on its own -- the header can be mid-fade -- but it must not pass silently,
            # because everything downstream reads this frame as the shop's stock.
            self.log("   WARNING: the 联盟商店 page's own markers did not read on this frame")
        else:
            self.log(f"   on the 联盟商店 page (tabs {self._any(toks, ALLIANCE_SHOP_TABS)},"
                     f" self-refresh banner present)")
        return img, toks

    def select_tab(self, tab: str) -> tuple[np.ndarray, list[dict]]:
        # The tab is found by its own text, and finding it is allowed to take more than one frame:
        # the strip slides in when the store page appears, and a capture taken mid-slide has no
        # tab text to read.  On 2026-10-05 04:25 that cost a whole pass -- ``enter`` reported the
        # store page, then this raised TAB_NOT_FOUND:游荡商人 on the first frame it looked at.
        node = None
        for attempt in range(3):
            img, toks = self.see(f"02_at_{tab}", save=attempt == 2)
            node = self._at(toks, tab, band=TAB_BAND, h=img.shape[0])
            if node is not None:
                break
            time.sleep(0.9)
        if node is None:
            raise RuntimeError(f"TAB_NOT_FOUND:{tab}")
        before = img.copy()
        self.log(f"   selecting tab {tab} at {list(map(int, node['centre']))}")
        self._tap_xy(node["centre"])
        img, toks = self.see(f"03_tab_{tab}")
        if np.array_equal(before, img):
            raise RuntimeError(f"TAB_TAP_DID_NOT_CHANGE_THE_PAGE:{tab}")
        return img, toks

    def read_name(self, card: Card) -> tuple[str | None, str | None, list[dict]]:
        """Read the item's name from the client's own detail surface.

        Measured on 2026-10-05 (tools/shop_tap_probe.py, card r1c0): inside a shop card the
        **icon** is the tappable zone -- taps 40, 70 and 90 px above the 剩余 label all opened
        the read-only tooltip -- while the 剩余 label itself and the price pill produced
        nothing at all.  That is why the earlier passes, which tapped the label, read only two
        cards out of six and read a description fragment as a name.

        The tooltip is also the safer of the two overlays: it has no buttons, so there is
        nothing to mis-tap, and the system back key closes it.
        """
        for dy in ICON_DY_LADDER:
            xy = (card.tap_xy[0], card.tap_xy[1] - dy)
            self._tap_xy(xy)
            img, toks = self.see(f"10_card_r{card.row}c{card.col}_tip{dy}")
            if TOOLTIP_MARKER in " ".join(t["text"] for t in toks):
                name, desc = item_name_from_dialog(toks)
                self.log(f"      tooltip @-{dy}: name={name!r} desc={desc!r}")
                self._dismiss_tooltip()
                return name, desc, toks
        self.log("      no tooltip at any point on the icon -- card unreadable")
        return None, None, toks

    def _dismiss_tooltip(self) -> None:
        """A tooltip has no ✕, so the back key is the only way out -- bounded, then checked."""
        self._back("closing the item tooltip")
        img, toks = self.see("11_after_tooltip")
        if TOOLTIP_MARKER in " ".join(t["text"] for t in toks):
            raise RuntimeError("TOOLTIP_WOULD_NOT_CLOSE")
        h = img.shape[0]
        if not self.on_store_page(toks, h):
            raise RuntimeError("LEFT_THE_STORE_WHILE_DISMISSING")

    def _body_ladder(self, card: Card, h_img: int,
                     ladder: tuple[int, ...] = BODY_DY_LADDER) -> tuple[int, ...]:
        """The body offsets that are actually legal on this card, top to bottom.

        The ladder used to be the fixed ``BODY_DY_LADDER``.  On 神秘商店 the grid is 3x3 (measured
        2026-10-05) and the third row's anchor sits at y=1186 on a 1280-tall frame, so the last two
        rungs land at 1246 and 1266 -- **inside the bottom tab strip**, which begins at 0.93*H =
        1190 and holds 游荡商人 / 神秘商店 / 竞技商店 / 统帅市 (all read at y=1241..1248).  A tap
        that lands there selects a different shop, and the pass would then read another shop's
        stock while still believing it was on the one it selected: silently reading the wrong shop
        is worse than failing to open one card, so the ladder is clamped to stay strictly above the
        band.  It is a clamp and not a shortening, so a tall card keeps its whole spread.
        """
        band_top = TAB_BAND * h_img
        keep = tuple(dy for dy in ladder if card.tap_xy[1] + dy < band_top)
        return keep

    def open_purchase(self, card: Card,
                      on_page: Callable[[list[dict], int], bool] | None = None
                      ) -> tuple[bool, np.ndarray | None, list[dict]]:
        """Open the 确定购买 overlay by tapping the card body.

        The card's tappable zones were re-measured properly on 2026-10-05 with
        ``tools/shop_zone_map.py``, which walks one fine ladder across a card's whole vertical
        extent and reports what each offset produced -- on a resource-priced card *and* on a
        diamond-priced one, because the two earlier probes disagreed and each had only seen one
        card.  Both cards came back identical, and the boundaries are sharp:

            anchor-110 .. anchor-30   -> the read-only 拥有数量 tooltip (5 of 6 offsets)
            anchor-10                 -> nothing on one card, the overlay on the other
            anchor+0  .. anchor+80    -> 确定购买, on every offset, on both cards
            anchor+100 and beyond     -> nothing (the card has ended)

        So the body is a wide, forgiving target whose top edge is the 剩余 label itself, and the
        ladder now *covers* it rather than sampling it.  Covering it is affordable because the
        overlay is detected from its own orange price button (``orange_price_button``) on a raw
        capture, with no OCR: a miss costs ~2 s instead of ~20 s, which is what made a six-step
        ladder too expensive to be worth trying before.

        What makes this flaky is *time*, not geometry: on some taps the client takes nothing at all,
        and that can run for several taps in a row (card r0c2 in the 2026-10-05 01:50 pass was
        tapped nine times across three offsets and the overlay never appeared, while the very next
        card opened on its eighth tap).  Hence two cycles: the second one re-derives the anchor from
        a fresh frame first, so a re-rendered page cannot leave the ladder aiming at where the card
        used to be.
        """
        img: np.ndarray | None = None
        toks: list[dict] = []
        # Refuse to read an overlay this card did not open.
        #
        # If an orange price button is ALREADY on screen before anything is tapped, an earlier
        # card's overlay is still up -- and proceeding would attribute that card's item and its
        # price to *this* card.  The reading would look completely well-formed, which is what
        # makes it dangerous: measured 2026-10-05 (evidence
        # shop_visit_alliance_20261005T063527), where r0c2's overlay survived into r1c0, r1c1 and
        # r1c2 and all three reported r0c2's own 100点统帅经验; two of the frames are byte-identical.
        # The caller-side fix is to always dismiss, and this is the primitive-side one: a leftover
        # is closed here, so no caller's branch shape can reintroduce the ghost.
        if orange_price_button(self._frame()) is not None:
            self.log(f"      r{card.row}c{card.col}: an overlay is ALREADY open before any tap"
                     " -- closing the leftover so it cannot be read as this card's")
            self._dismiss_dialog(on_page)
        # The frame height is needed to clamp the ladder off the tab strip; this capture does no
        # OCR, so it is cheap, and it is taken before any tap rather than after.
        h_img = self._frame().shape[0]
        rungs = self._body_ladder(card, h_img)
        if not rungs:
            self.log(f"      r{card.row}c{card.col}: anchor {list(card.tap_xy)} is inside the tab"
                     f" band (y>={TAB_BAND * h_img:.0f}) -- refusing to tap")
            return False, None, toks
        if len(rungs) != len(BODY_DY_LADDER):
            self.log(f"      r{card.row}c{card.col}: ladder clamped above the tab band"
                     f" (y<{TAB_BAND * h_img:.0f}): {list(rungs)}")
        # Put the absolute targets in the log.  The evidence filenames carry only the offset, and
        # when a card's overlay will not open the first question is always "where did it tap?" --
        # which the frames alone cannot answer if the anchor was re-derived mid-way.
        self.log(f"      opening r{card.row}c{card.col} from anchor {list(card.tap_xy)}:"
                 f" taps at {[(card.tap_xy[0], card.tap_xy[1] + dy) for dy in rungs]}")
        for cycle in range(2):
            # The second cycle is a single tap at a freshly derived anchor: the point of it is the
            # anchor, not another spread.  It is clamped the same way, because the re-derived
            # anchor is exactly where an unclamped 20 could slip into the band.
            if cycle:
                rungs = self._body_ladder(card, h_img, ladder=(20,))
            for dy in rungs:
                self._tap_xy((card.tap_xy[0], card.tap_xy[1] + dy))
                for attempt in range(MAX_DIALOG_FRAMES):
                    probe = self._frame()
                    if orange_price_button(probe) is None:
                        time.sleep(0.6)
                        continue
                    # The price button is on screen, so this is the purchase overlay -- and only
                    # now is a full read of the frame worth paying for.
                    img, toks = self.see(f"40_card_r{card.row}c{card.col}_buy{dy}_{attempt}")
                    if DIALOG_TITLE in " ".join(t["text"] for t in toks):
                        return True, img, toks
                    self.log(f"      an orange button but no {DIALOG_TITLE} on it"
                             " -- not the purchase overlay")
                    break
            if cycle == 0:
                moved = self.relocate(card)
                if moved is None:
                    break
                # Only a real move counts.  OCR puts the anchor on the same label to within a
                # pixel or two every time, and a 1 px difference is not a reason to log anything.
                if abs(moved[0] - card.tap_xy[0]) >= 10 or abs(moved[1] - card.tap_xy[1]) >= 10:
                    self.log(f"      the card moved {list(card.tap_xy)} -> {list(moved)};"
                             " retrying there")
                    card.tap_xy = moved
        return False, None, toks

    def inspect(self, card: Card,
                on_page: Callable[[list[dict], int], bool] | None = None) -> dict:
        """Read one card from its purchase overlay: name, description, price, currency.

        The overlay is used as the *reader* as well as the purchase step, for three measured
        reasons: it names the item (the tooltip does too, but reaching it needs a back press,
        and a run of those is what stopped the next card's tap from landing at all); it prints
        the price with the live currency icon, so the decision is made on current pixels rather
        than on a card list the shop may already have re-rolled; and its ✕ closes it without
        touching anything else.

        ``on_page`` is the predicate describing the page this card was listed on; it is handed to
        ``_dismiss_dialog`` so the overlay's disappearance is verified against the right page.
        """
        ok, img, toks = self.open_purchase(card, on_page)
        if not ok or img is None:
            return {"ok": False, "why": "PURCHASE_OVERLAY_NOT_OPENED"}
        name, desc = item_name_from_dialog(toks)
        button_box = orange_price_button(img)
        if button_box is None:
            self._dismiss_dialog(on_page)
            return {"ok": False, "why": "PRICE_BUTTON_NOT_FOUND"}
        # The price is read off the button itself (white glyphs re-drawn as black on white), and
        # the tap is the button's own centre -- which is what a person does, and it keeps the
        # whole-frame pass, with its slider artefacts, off the critical path.
        price_text, price_ev = read_button_price(img, button_box["bbox"])
        how = price_ev.get("method", "glyph_mask")
        if price_text is None:
            inside = [t for t in prefer_whole(toks)
                      if re.fullmatch(r"[\d,]+万?", t["text"].strip())
                      and _inside(button_box["bbox"], *t["centre"])]
            if inside:
                price_text = max(inside,
                                 key=lambda t: len(re.sub(r"\D", "", t["text"])))["text"].strip()
                how = "whole_frame_inside_button"
        if price_text is None:
            self._dismiss_dialog(on_page)
            return {"ok": False, "why": "PRICE_UNREADABLE_ON_BUTTON"}
        bx, by = button_box["centre"]
        diamond, ev = price_is_diamond(img, bx, by)
        return {"ok": True, "name": name, "desc": desc, "price": price_text,
                "price_xy": (int(bx), int(by)), "price_is_diamond": diamond, "currency": ev,
                "price_source": how, "price_evidence": price_ev, "price_button": button_box}

    def confirm(self, card: Card, inspected: dict,
                on_page: Callable[[list[dict], int], bool] | None = None) -> tuple[bool, str]:
        """Spend.  This is TWO taps, not one.

        Measured 2026-10-05 (``r0_41_buy_r1c2_done.png``): tapping 确定购买's orange price button
        does **not** buy anything -- it opens a second dialog, 购买确认, asking
        ``您是否要花费16钻石?`` with its own orange button.  The first attempt reported success
        because ``确定购买`` had indeed gone; the diamond wallet said otherwise, which is exactly
        what the verifier is for.

        The second dialog restates the amount, so it doubles as the last gate: it is tapped only
        when the client's own sentence names **exactly** the price this decision was made on.  An
        amount that cannot be read is not confirmed -- a spend that cannot be checked is not made.

        ``on_page`` names the page the card came from and is handed to every recovery path, so a
        refused purchase closes its dialog and returns a clean failure.  All three of those paths
        used to assume the store, which on 联盟商店 would have raised
        ``LEFT_THE_PAGE_WHILE_DISMISSING`` in the middle of a *safely refused* purchase -- a
        crash standing in for the failure report.  The read-only passes could not surface it,
        because a read-only pass never calls ``confirm`` at all.
        """
        xy = inspected["price_xy"]
        self.log(f"      confirming with the price button at {list(xy)}"
                 f" ({inspected['price']}{'钻石' if inspected['price_is_diamond'] else '资源'})")
        self._tap_xy(xy)
        img, after = self.see(f"41_buy_r{card.row}c{card.col}_done")
        texts = " ".join(t["text"] for t in after)
        if DIALOG_TITLE in texts:
            return False, "DIALOG_STILL_OPEN_AFTER_CONFIRM"
        if CONFIRM_PHRASE not in texts and CONFIRM_TITLE not in texts:
            return True, "CONFIRMED_IN_ONE_TAP"
        want = _num_of(inspected["price"])
        quoted = [v for v in (_num_of(t["text"]) for t in after) if v is not None]
        if want is None or want not in quoted:
            self.log(f"      购买确认 quotes {quoted} but the decision was made on {want};"
                     " refusing and closing")
            self._dismiss_dialog(on_page)
            return False, f"CONFIRM_AMOUNT_NOT_MATCHED({quoted} != {want})"
        # The second button is located by its own paint, never by finding its digits.  Searching
        # for a numeric token inside the button box is what failed on 2026-10-05 04:13: the
        # client's sentence was read correctly and the amount matched, but no numeric token could
        # be found inside the box, so a legitimate 钻石换统帅经验 purchase came back
        # CONFIRM_BUTTON_NOT_FOUND (evidence shop_visit_wandering_20261005T041329).  That is the
        # same white-on-orange misread ``read_button_price`` exists to solve -- and the amount that
        # actually gates the spend was already checked against the client's own sentence above.
        # This dialog carries exactly one orange button, so the paint is unambiguous here.
        box = orange_price_button(img)
        if box is None:
            self._dismiss_dialog(on_page)
            return False, "CONFIRM_BUTTON_NOT_FOUND"
        # The button's own number is corroboration, not a second gate: a *disagreement* stops the
        # spend, but a number that cannot be read does not, because the client's sentence already
        # named the amount and OCR noise must not block an authorised purchase.
        says, _ev = read_button_price(img, box["bbox"])
        if says is not None and _num_of(says) != want:
            self.log(f"      购买确认's button says {says} but the dialog quotes {want};"
                     " refusing and closing")
            self._dismiss_dialog(on_page)
            return False, f"CONFIRM_BUTTON_DISAGREES({says} != {want})"
        self.log(f"      购买确认: the client asks for {want}; tapping its own button"
                 f" at {box['centre']} (button reads {says})")
        self._tap_xy(box["centre"])
        _img2, after2 = self.see(f"43_bought_r{card.row}c{card.col}")
        texts2 = " ".join(t["text"] for t in after2)
        if CONFIRM_PHRASE in texts2 or CONFIRM_TITLE in texts2:
            return False, "CONFIRM_DIALOG_STILL_OPEN"
        return True, "CONFIRMED"

    def _dismiss_dialog(self, on_page: Callable[[list[dict], int], bool] | None = None) -> None:
        """Close the purchase overlay by its own ✕.  The orange price button is never a candidate.

        ``on_page`` states which page the overlay was opened *from*, so its disappearance can be
        checked against the right page.  It defaults to the store, which is where every caller
        lived until 联盟商店 arrived; the alliance shop is not the store, so a hard-coded
        ``on_store_page`` here would raise ``LEFT_THE_STORE_WHILE_DISMISSING`` on a perfectly
        well-behaved alliance pass -- an assertion that is right about the shape of the check and
        wrong about which page it is checking.
        """
        _, toks = self.see("50_dismiss_probe", save=False)
        close = next((t for t in toks if t["text"].strip() in ("X", "x", "✕", "×", "╳")), None)
        if close is not None:
            self.log(f"      closing the overlay with its ✕ at {list(map(int, close['centre']))}")
            self._tap_xy(close["centre"])
        else:
            self._back("no ✕ token readable on the purchase overlay")
        img, toks = self.see("51_after_dismiss")
        if DIALOG_TITLE in " ".join(t["text"] for t in toks):
            raise RuntimeError("PURCHASE_OVERLAY_WOULD_NOT_CLOSE")
        h = img.shape[0]
        back_on = on_page or self.on_store_page
        if not back_on(toks, h):
            raise RuntimeError("LEFT_THE_PAGE_WHILE_DISMISSING")

    def free_refresh(self) -> bool:
        """Refresh only when the control literally says 免费刷新.  神秘商店's control reads
        刷新 💎100 -- tapping that would be an unapproved diamond spend."""
        img, toks = self.see("20_refresh_probe", save=False)
        btn = self._at(toks, "免费刷新", exact=False)
        if btn is None:
            self.log("   no 免费刷新 on this page -- not refreshing (a paid 刷新 is never used)")
            return False
        self.log(f"   tapping 免费刷新 at {list(map(int, btn['centre']))}")
        self._tap_xy(btn["centre"])
        img, toks = self.see("21_after_refresh")
        return True


# --------------------------------------------------------------------------- orchestration
def _amount(tokens: list[str] | None) -> int | None:
    """The diamond count is a plain comma-grouped number on the client's top bar."""
    for text in (tokens or []):
        digits = re.sub(r"\D", "", text)
        if digits:
            return int(digits)
    return None


def _num_of(text: str | None) -> int | None:
    """A price as the client writes it, including the 万 suffix: ``25万`` -> 250000.

    Used to compare the amount a purchase dialog *asks for* against the amount the decision was
    made on.  ``25万`` and ``250000`` are the same price and must compare equal.
    """
    m = re.search(r"([\d,]+)\s*(万?)", text or "")
    if not m:
        return None
    value = int(m.group(1).replace(",", ""))
    return value * 10000 if m.group(2) else value


def _verify_purchases(v: ShopVisitor, report: dict[str, Any],
                      log: Callable[[str], None]) -> None:
    """Did the goods actually change hands?  Answer from the client's numbers, not from our taps.

    A closing overlay is not a receipt.  Two independent readings are available:

      * **a diamond price** -- the top bar shows the diamond total, and diamonds are not produced
        by the base, so a purchase must move that number by exactly the price.  Decisive.
      * **a resource price** -- the four resource totals are shown in 亿/万, so a 10,000 铁
        purchase is invisible against 27 million, and those totals also *rise* on their own.
        Not usable; instead the purchased card's own 剩余 is re-read.  That is weaker evidence:
        the merchant re-rolls slots on its own (measured 2026-10-05 -- one slot held three
        different items inside three minutes), so a changed card is reported as "changed", and
        only an explicit 剩余 0 is called verified.
    """
    purchases = report.get("purchases") or []
    if not purchases:
        return
    before_a, after_a = report.get("wallet_before_amount"), report.get("wallet_after_amount")
    expected = sum(int(re.sub(r"\D", "", p["card"]["price"]) or 0)
                   for p in purchases if p["ok"] and p["card"]["diamond"])
    observed = (before_a - after_a) if (before_a is not None and after_a is not None) else None
    report["diamond_expected_spend"] = expected
    report["diamond_observed_spend"] = observed

    diamond_rows = [p for p in purchases if p["ok"] and p["card"]["diamond"]]
    if diamond_rows and expected:
        ok = observed == expected
        report["purchase_verified"] = ok
        note = f"钻石 {before_a} -> {after_a}, 实际消耗 {observed}, 期望 {expected}"
        for p in diamond_rows:
            p["verified"] = ok
            p["verify_note"] = note
        log(f"   verifier: diamond wallet {before_a} -> {after_a} (spent {observed},"
            f" expected {expected}) -> {'VERIFIED' if ok else 'MISMATCH'}")

    resource_rows = [p for p in purchases if p["ok"] and not p["card"]["diamond"]]
    if resource_rows:
        _img2, toks2 = v.see("31_after_purchases")
        now = {(c.row, c.col): c for c in read_cards(_img2, toks2)}
        for p in resource_rows:
            card = now.get((p["card"]["row"], p["card"]["col"]))
            p["after_purchase"] = card.to_dict() if card else None
            if card is None:
                p["verified"] = None
                p["verify_note"] = "该位置已读不到卡片"
            elif card.rest == 0:
                p["verified"] = True
                p["verify_note"] = f"该位置现在 剩余=0（原 {p['card']['rest']}）"
            elif card.price_text != p["card"]["price"] or card.name != p["card"]["name"]:
                p["verified"] = None
                p["verify_note"] = (f"该位置已变成 剩余={card.rest} 价格={card.price_text}"
                                    "（商店自身会换货，不能据此断言购买成功）")
            else:
                p["verified"] = False
                p["verify_note"] = f"该位置仍为 剩余={card.rest} 价格={card.price_text}"
            log(f"   verifier: r{p['card']['row']}c{p['card']['col']} -> {p['verify_note']}")


LEASE_YIELD_REASON = "device_leased_for_development"


def wait_for_the_device(root: Path, *, timeout: float = 45.0,
                        log: Callable[[str], None] = print) -> bool:
    """Wait until AUTO has actually handed the device over -- a lease is not a handover.

    Acquiring the lease is a *request*; the production loop only honours it at its next safe
    point, and it keeps acting until then.  Measured 2026-10-05: the lease was written at
    05:40:52 and AUTO recorded ``device_leased_for_development`` at 05:41:14 (~22 s later).
    The pass's first tap was issued in between and landed on the beast-hunt page the loop was
    still working on, so the 商店 nav press did nothing at all -- and then the store only
    appeared on the pass's *last* allowed attempt, which is what exposed the entry off-by-one.

    Two files say whether the handover has happened; either is enough:

      * ``learning/runtime_snapshot.json`` -> ``stop_reason == device_leased_for_development``
        with a ``reason`` naming the development owner;
      * ``learning/auto_uptime.jsonl``     -> the newest round's ``stop_reason``.

    A missing snapshot means no panel is running, which is also "nothing is driving the
    device", so that counts as a handover too.  On timeout this returns False and says so;
    the caller's page check (``enter``) remains the real safety net either way.
    """
    snap = Path(root) / "learning" / "runtime_snapshot.json"
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            state = json.loads(snap.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- "no panel" and "unreadable" are the same here
            log("   device handover: no readable runtime snapshot -- nothing is driving")
            return True
        if str(state.get("stop_reason") or "") == LEASE_YIELD_REASON:
            log(f"   device handover: AUTO yielded ({state.get('reason') or LEASE_YIELD_REASON})"
                f"  after {(timeout - (deadline - time.monotonic())):.0f}s")
            return True
        if time.monotonic() >= deadline:
            log(f"   device handover NOT seen within {timeout:.0f}s"
                f" (stop_reason={state.get('stop_reason')!r}) -- going on anyway")
            return False
        time.sleep(1.5)


def visit(ad, out_dir: Path, *, do_refresh: bool = False, execute_buys: bool = False,
          log: Callable[[str], None] = print) -> dict[str, Any]:
    """One full VISIT_WANDERING_MERCHANT pass.  Reads, decides, reports; buys only BUY."""
    v = ShopVisitor(ad, out_dir, log=log)
    report: dict[str, Any] = {"skill": "VISIT_WANDERING_MERCHANT", "cards": [],
                              "wallet_before": None, "wallet_after": None,
                              "execute_buys": execute_buys, "purchases": [], "asks": [],
                              "unreadable": []}
    img, toks = v.enter()
    h0 = img.shape[0]

    def wallet(t):
        return [x["text"] for x in t
                if re.fullmatch(r"[\d,]{3,}", x["text"].strip()) and x["centre"][1] < 0.06 * h0]

    report["wallet_before"] = wallet(toks)

    img, toks = v.select_tab("游荡商人")
    if not v._any(toks, WANDERING_MARKERS):
        raise RuntimeError("WANDERING_TAB_NOT_CONFIRMED")

    refreshes = 0
    for round_no in range(3):
        v.tag_prefix = f"r{round_no}_"
        cards = read_cards(img, toks)
        log(f"   round {round_no}: read {len(cards)} cards")
        round_report = []
        bought = 0
        # Inspect the resource-priced offers first.  A pass costs roughly two minutes per card
        # (each one needs its overlay, its name, and a dismissal) while the merchant re-rolls on a
        # ~20 minute timer of its own -- so the *order* decides whether the pass still reaches a
        # BUY candidate before the roll it just read has been replaced.  Working row-major puts
        # that candidate behind up to five cards that will all be skipped.  The verdict still
        # comes from each card's own overlay, so this changes nothing about correctness.
        for card in sorted(cards, key=lambda c: (c.price_is_diamond, c.row, c.col)):
            if card.rest <= 0:
                card.verdict, card.reason = "SKIP", "sold out"
                round_report.append(card.to_dict())
                log(f"   [r{card.row}c{card.col}] 剩余=0 -> SKIP (sold out)")
                continue
            log(f"   [r{card.row}c{card.col}] 剩余={card.rest}"
                f" price={card.price_text or '?(列表未读到)'}"
                f"{'💎' if card.price_is_diamond else ''} 折扣={card.discount}")
            # Read the card from its own purchase overlay: it names the item AND prints the
            # live price with its currency, so the decision never rests on a stale card list.
            got = v.inspect(card)
            if not got.get("ok"):
                why = got.get("why")
                # There is deliberately NO read-only-tooltip fallback here any more.  The tooltip
                # names the item but prints no price at all, so deciding there means splicing a
                # live name onto the card list's price -- and the card list is exactly the thing
                # the 2026-10-05 pass proved can be stale: the *same slot* held 建造加速 for
                # 33,000 铁, then 煤 for 10,000 铁, then 木材 for 💎100, all inside three minutes
                # and all with 22 minutes left on the merchant's own countdown.  A card whose
                # overlay will not open is reported, never guessed at.
                card.inspect_why = why
                card.verdict, card.reason = "NOT_EXECUTED", f"overlay not usable ({why})"
                log(f"      overlay not usable ({why}) -> NOT_EXECUTED, nothing tapped")
                report["unreadable"].append(card.to_dict())
                round_report.append(card.to_dict())
                continue
            card.name, card.description = got["name"], got["desc"]
            card.price_text = got["price"]
            card.price_is_diamond = got["price_is_diamond"]
            card.verdict, card.reason = decide_wandering(card.name, card.price_is_diamond)
            log(f"      overlay: name={card.name!r} price={card.price_text}"
                f"{'💎' if card.price_is_diamond else '资源'} 折扣={card.discount}")
            log(f"      -> {card.verdict}  ({card.reason})")
            if card.verdict == "ASK":
                report["asks"].append(card.to_dict())
            if card.verdict == "BUY" and execute_buys:
                ok, why = v.confirm(card, got)
                card.reason = f"{card.reason} -> {why}"
                report["purchases"].append({"card": card.to_dict(), "ok": ok, "why": why})
                bought += 1 if ok else 0
                log(f"      purchase: {'OK' if ok else 'FAILED'} ({why})")
            else:
                # Every path that does NOT spend must still close the overlay it opened.
                #
                # This used to read ``elif card.verdict != "BUY"``, which left the overlay open
                # on exactly one combination: a **BUY verdict in a read-only pass** (no
                # ``--buy``).  Measured 2026-10-05 on 联盟商店 (evidence
                # shop_visit_alliance_20261005T063527): card r0c2 decided BUY, its 确定购买
                # overlay stayed up, and the *next* card's inspection found an orange button
                # already on screen -- so it returned the frame it found and reported r0c2's own
                # name and price as r1c0's, then r1c1's.  Byte-identical frames prove it
                # (s0_40_card_r0c2_buy0_0.png == s0_40_card_r1c0_buy0_0.png).  Worse, the taps
                # aimed at those later cards landed *inside the open dialog*, and one hit its
                # quantity "+" : r1c2 was read as the same item at 20,000 instead of 4,000, i.e.
                # the decision was made against an amount a stray tap had set.  The pass also
                # ended with the dialog still armed on screen.  The measured cost: that roll has
                # 3 统帅经验 slots and the bug reported 6, so three non-统帅经验 items would have
                # been bought as if they were.
                #
                # A stale overlay is the single worst failure mode this module has, because it
                # makes a wrong reading look like a right one.  Closing on ``else`` removes the
                # combination instead of documenting it.
                v._dismiss_dialog()
            round_report.append(card.to_dict())
        report["cards"].append({"round": round_no, "cards": round_report})
        if not (do_refresh and round_no < 2):
            break
        if not v.free_refresh():
            break
        refreshes += 1
        img, toks = v.see(f"22_round{round_no + 1}_list")

    img, toks = v.see("30_final")
    report["refreshed"] = refreshes
    report["wallet_after"] = wallet(toks)
    if not report["wallet_after"]:
        # The top bar can be occluded for a moment (a spend dialog, a purchase toast).  The wallet
        # is the spend witness, so one retry is worth it; if it still will not read, the verifier
        # reports MISMATCH rather than assuming the purchase worked.
        time.sleep(1.6)
        _img3, toks = v.see("30_final_retry")
        report["wallet_after"] = wallet(toks)
    report["wallet_before_amount"] = _amount(report["wallet_before"])
    report["wallet_after_amount"] = _amount(report["wallet_after"])
    _verify_purchases(v, report, log)
    report["backs_used"] = v._back_used
    report["tap_refused"] = getattr(v, "_tap_refused", 0)
    report["touch_balance"] = ad.touch_balance
    report["steps"] = [s["step"] for s in v.trace]
    (out_dir / "visit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return report


def visit_mystery(ad, out_dir: Path, *, do_refresh: bool = False, execute_buys: bool = False,
                  max_refreshes: int = 4, log: Callable[[str], None] = print) -> dict[str, Any]:
    """One full VISIT_MYSTERY_SHOP pass.  Reads and decides; buys only a 50%-off 组件自选箱.

    Same shape as the merchant's pass (one overlay per card, verdict from the overlay, the
    client's own confirmation gates the spend), with the three measured differences: nine
    slots instead of six, the **gold coin** instead of diamonds, and a rule keyed on the card's
    own discount badge rather than on the currency.  Because the currency is not the diamond,
    ``wallet_before``/``wallet_after`` keep meaning diamonds and ``gold_before``/``gold_after``
    carry the number a purchase here would actually move -- a verifier reading the wrong one
    would report \"(spent 0, expected 2500)\" on a perfectly good purchase.
    """
    v = ShopVisitor(ad, out_dir, log=log)
    report: dict[str, Any] = {"skill": "VISIT_MYSTERY_SHOP", "cards": [],
                              "wallet_before": None, "wallet_after": None,
                              "gold_before": None, "gold_after": None,
                              "execute_buys": execute_buys, "purchases": [], "asks": [],
                              "unreadable": [], "refreshed": 0}
    img, toks = v.enter()
    h0 = img.shape[0]

    def wallets(t):
        nums = top_bar_numbers(t, h0)
        return ([nums[0][2]] if nums else []), (nums[-1][2] if len(nums) > 1 else None)

    report["wallet_before"], report["gold_before"] = wallets(toks)

    img, toks = v.select_tab("神秘商店")
    if not v._any(toks, MYSTERY_MARKERS):
        raise RuntimeError("MYSTERY_TAB_NOT_CONFIRMED")

    for round_no in range(int(max_refreshes) + 1):
        v.tag_prefix = f"r{round_no}_"
        cards = read_cards(img, toks)
        log(f"   round {round_no}: read {len(cards)} cards")
        round_report = []
        # A 50%-off 组件自选箱 is the only thing worth reaching and the shop re-rolls its own
        # slots, so cards whose badge says 50% are opened first; the verdict still comes from
        # each card's own overlay, never from the list.
        for card in sorted(cards, key=lambda c: (discount_percent(c.discount) != MYSTERY_DISCOUNT,
                                                 c.row, c.col)):
            if card.rest <= 0:
                card.verdict, card.reason = "SKIP", "sold out"
                round_report.append(card.to_dict())
                log(f"   [r{card.row}c{card.col}] 剩余=0 -> SKIP (sold out)")
                continue
            got = v.inspect(card)
            if not got.get("ok"):
                card.inspect_why = got.get("why")
                card.verdict, card.reason = "NOT_EXECUTED", f"overlay not usable ({got.get('why')})"
                log(f"   [r{card.row}c{card.col}] 折扣={card.discount}"
                    f" overlay 打不开 ({got.get('why')}) -> NOT_EXECUTED，什么都没点")
                report["unreadable"].append(card.to_dict())
                round_report.append(card.to_dict())
                continue
            card.name, card.description = got["name"], got["desc"]
            card.price_text, card.price_is_diamond = got["price"], got["price_is_diamond"]
            card.verdict, card.reason = decide_mystery(card.name, card.discount)
            log(f"   [r{card.row}c{card.col}] 折扣={card.discount} 浮层名={card.name!r}"
                f" 价={card.price_text}{'💎' if card.price_is_diamond else ''}"
                f" -> {card.verdict}  ({card.reason})")
            if card.verdict == "ASK":
                report["asks"].append(card.to_dict())
            if card.verdict == "BUY" and execute_buys:
                ok, why = v.confirm(card, got)
                card.reason = f"{card.reason} -> {why}"
                report["purchases"].append({"card": card.to_dict(), "ok": ok, "why": why})
                log(f"      purchase: {'OK' if ok else 'FAILED'} ({why})")
            else:
                # A BUY verdict in a read-only pass must still close its overlay -- see the
                # measured stale-overlay failure written up in ``visit``.
                v._dismiss_dialog()
            round_report.append(card.to_dict())
        report["cards"].append({"round": round_no, "cards": round_report})
        if not (do_refresh and round_no < int(max_refreshes)):
            break
        if not v.free_refresh():
            break
        report["refreshed"] += 1
        img, toks = v.see(f"22_round{round_no + 1}_list")

    img, toks = v.see("30_final")
    report["wallet_after"], report["gold_after"] = wallets(toks)
    report["backs_used"] = v._back_used
    report["tap_refused"] = getattr(v, "_tap_refused", 0)
    report["touch_balance"] = ad.touch_balance
    report["steps"] = [s["step"] for s in v.trace]
    (out_dir / "visit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return report


def visit_alliance(ad, out_dir: Path, *, execute_buys: bool = False, max_swipes: int = 2,
                   tab: str | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """One full VISIT_ALLIANCE_SHOP pass.  Reads every slot; buys only a 名称含统帅经验 line.

    Three measured differences from the two store passes, each of which would break a copy-paste
    of ``visit_mystery``:

      * **The page is not the store.**  There is no 游荡商人/神秘商店 tab strip and no 免费刷新
        control; the bottom strip holds **今日 / 本周**, i.e. two different stocks, and the shop
        re-rolls itself on a timer (banner ``下次刷新：`` + countdown).  That banner is precisely
        why the operator's 联盟商店 rule has no refresh step.
      * **The list is longer than the screen.**  Measured 2026-10-05: the unscrolled frame shows
        three complete rows (anchor y 381/665/948) and *clips* a fourth; one swipe up reveals it
        (anchor y=1101) and a second swipe changes nothing.  A name-based rule therefore cannot
        be evaluated from one screen, so the pass sweeps.  Which rows are "new" is derived from
        the frame at run time (anchors below the deepest one already seen) and never from a
        stored coordinate -- and the sweep terminates on its own when a swipe reveals nothing.
      * **The top bar carries one number, not two.**  The store's 钻石 slot (x~451) is not
        rendered on this page; the single number sits at x~630.  So ``coin_before``/``coin_after``
        carry the only wallet this page shows.  *Which* currency that is was NOT settled in the
        read-only pass (a purchase is what would settle it), so it is reported, not asserted.

    The verdict comes from each card's own 确定购买 overlay, because -- like every other shop
    page measured so far -- the cards print icon + 剩余 + price and **no item name**.  The
    operator's rule is about a name, so the list alone can never evaluate it.
    """
    v = ShopVisitor(ad, out_dir, log=log)
    report: dict[str, Any] = {"skill": "VISIT_ALLIANCE_SHOP", "cards": [], "tab": tab,
                              "top_bar_before": None, "top_bar_after": None,
                              "coin_before": None, "coin_after": None,
                              "execute_buys": execute_buys, "purchases": [], "asks": [],
                              "unreadable": [], "swipes": 0, "rounds": []}
    img, toks = v.enter_alliance()
    img, toks = v.open_alliance_shop()
    h0, w0 = img.shape[:2]
    on_page = v.on_alliance_shop_page

    if tab and tab != ALLIANCE_SHOP_TABS[0]:
        node = v._at(toks, tab, band=TAB_BAND, h=h0)
        if node is None:
            raise RuntimeError(f"ALLIANCE_TAB_NOT_FOUND:{tab}")
        v.log(f"   selecting the {tab} tab at {list(map(int, node['centre']))}")
        v._tap_xy(node["centre"])
        img, toks = v.see(f"A5_tab_{tab}")

    report["top_bar_before"] = top_bar_numbers(toks, h0)
    report["coin_before"] = report["top_bar_before"][-1][2] if report["top_bar_before"] else None

    seen_y: list[int] = []
    floor = 0
    for round_no in range(int(max_swipes) + 1):
        v.tag_prefix = f"s{round_no}_"
        cards = read_cards(img, toks)
        todo = cards if round_no == 0 else [c for c in cards if c.tap_xy[1] > floor]
        log(f"   round {round_no}: {len(cards)} slot(s) on screen,"
            f" {len(todo)} not yet inspected (floor y>{floor})")
        round_report = []
        for card in sorted(todo, key=lambda c: (c.tap_xy[1], c.tap_xy[0])):
            if card.rest <= 0:
                card.verdict, card.reason = "SKIP", "sold out"
                round_report.append(card.to_dict())
                log(f"   [y{card.tap_xy[1]}c{card.col}] 剩余=0 -> SKIP (sold out)")
                continue
            got = v.inspect(card, on_page=on_page)
            if not got.get("ok"):
                card.inspect_why = got.get("why")
                card.verdict, card.reason = "NOT_EXECUTED", f"overlay not usable ({got.get('why')})"
                log(f"   [y{card.tap_xy[1]}c{card.col}] overlay 打不开 ({got.get('why')})"
                    " -> NOT_EXECUTED，什么都没点")
                report["unreadable"].append(card.to_dict())
                round_report.append(card.to_dict())
                continue
            card.name, card.description = got["name"], got["desc"]
            card.price_text, card.price_is_diamond = got["price"], got["price_is_diamond"]
            card.verdict, card.reason = decide_alliance(card.name)
            log(f"   [y{card.tap_xy[1]}c{card.col}] 浮层名={card.name!r}"
                f" 价={card.price_text}{' diamond' if card.price_is_diamond else ''}"
                f" -> {card.verdict}  ({card.reason})")
            if card.verdict == "ASK":
                report["asks"].append(card.to_dict())
            if card.verdict == "BUY" and execute_buys:
                ok, why = v.confirm(card, got, on_page=on_page)
                card.reason = f"{card.reason} -> {why}"
                report["purchases"].append({"card": card.to_dict(), "ok": ok, "why": why})
                log(f"      purchase: {'OK' if ok else 'FAILED'} ({why})")
            else:
                # Same stale-overlay fix as ``visit``.  It matters most here: on the measured
                # 今日 roll 3 of the 9 slots decide BUY, and before the fix the pass reported 6 --
                # i.e. three items that are not 统帅经验 (1小时研究加速 @ 26,000,
                # 5分钟训练加速 @ 1,300, 5分钟治疗加速 @ 2,200) would have been bought as if they
                # were.  See the write-up in ``visit`` for the frames.
                v._dismiss_dialog(on_page=on_page)
            round_report.append(card.to_dict())
        report["cards"].extend(round_report)
        report["rounds"].append({"round": round_no, "on_screen": len(cards),
                                 "inspected": len(todo)})
        seen_y.extend(c.tap_xy[1] for c in cards)
        floor = max(seen_y) + 40 if seen_y else 0
        if round_no >= int(max_swipes) or not todo:
            break
        # Swipe inside the grid, above the 今日/本周 strip, so no control is ever touched.
        log(f"   swiping up inside the grid (floor for the next round: y>{floor})")
        ad.swipe(w0 // 2, 1050, w0 // 2, 420, 420)
        time.sleep(1.8)
        report["swipes"] += 1
        img, toks = v.see(f"A6_after_swipe{round_no}")

    img, toks = v.see("A9_final")
    report["top_bar_after"] = top_bar_numbers(toks, h0)
    report["coin_after"] = report["top_bar_after"][-1][2] if report["top_bar_after"] else None
    report["backs_used"] = v._back_used
    report["tap_refused"] = getattr(v, "_tap_refused", 0)
    report["touch_balance"] = ad.touch_balance
    report["steps"] = [s["step"] for s in v.trace]
    (out_dir / "visit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return report
