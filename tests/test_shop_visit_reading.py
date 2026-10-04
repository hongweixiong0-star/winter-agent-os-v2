# -*- coding: utf-8 -*-
"""Pins for the 游荡商人 reader, written from what the live client actually did.

Every case here is a real failure or a real near-miss from the 2026-10-04 exploration:

  * ``15,000`` read as ``,000`` -- not a split, a *second OCR pass over the same pixels*;
  * the Exp bottle read as 统帅经验 -- it is 「1,000点英雄经验」, and the policy only allows
    diamonds to be spent on 统帅经验, so that misreading would have bought the forbidden item;
  * a resource priced in a resource (资源换资源) is a BUY, but a resource priced in diamonds
    is 其他钻石商品 and must be skipped -- the currency decides, and it is an icon;
  * anything the policy does not name must come back ASK, never a guess.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.shop_visit import (  # noqa: E402
    decide_mystery,
    decide_wandering,
    discount_percent,
    group_remaining,
    item_name_from_dialog,
    merge_fragments,
    prefer_whole,
    price_is_diamond,
    read_cards,
    top_bar_numbers,
)

BLUE = (30, 150, 240)          # H=103 -- the diamond's hue
GOLD = (230, 170, 40)          # H=21  -- medal / coin / wood
RED = (220, 60, 60)            # H=0   -- 生肉
DARK = (70, 72, 78)            # S=26  -- 煤, almost no saturated paint
PILL = (245, 248, 252)         # the white price pill


def frame_with(icon_rgb: tuple[int, int, int], x: int = 100, y: int = 60) -> np.ndarray:
    img = np.full((120, 260, 3), PILL, np.uint8)
    img[y - 10:y + 10, x - 10:x + 10] = icon_rgb
    return img


def tok(text: str, x: float, y: float, w: float = 40, h: float = 20, source: str = "whole"):
    return {"text": text, "centre": (x, y), "box": (x - w / 2, y - h / 2, w, h), "source": source}


def _flat(text: str | None) -> str:
    """Compare item names across the two bracket spellings OCR produces at different sizes."""
    return (text or "").replace("（", "(").replace("）", ")").replace(" ", "")


# --------------------------------------------------------------- currency, not text
def test_a_blue_price_icon_is_a_diamond_price():
    ok, ev = price_is_diamond(frame_with(BLUE), 100, 60)
    assert ok is True
    assert ev["blue_fraction"] == 1.0
    assert 85 <= ev["median_hue"] <= 125


@pytest.mark.parametrize("colour,what", [(GOLD, "gold"), (RED, "meat"), (DARK, "coal")])
def test_a_resource_price_icon_is_never_a_diamond(colour, what):
    ok, ev = price_is_diamond(frame_with(colour), 100, 60)
    assert ok is False, f"{what} was read as a diamond"
    assert ev["blue_fraction"] == 0.0


def test_a_dark_icon_is_rejected_for_having_no_ink_at_all_not_for_its_colour():
    _, ev = price_is_diamond(frame_with(DARK), 100, 60)
    assert ev["reason"] == "TOO_LITTLE_INK"


def test_a_diamond_on_the_orange_price_button_is_still_a_diamond():
    """The purchase overlay prints the price on a big ORANGE button.

    A fraction-of-saturated-pixels rule scored the diamond 0.21 there -- the orange paint
    dominated -- and so read a 140-diamond price as 资源, inverting the decision.  The count of
    blue pixels is what survives the change of surface.
    """
    img = np.full((120, 260, 3), (240, 150, 40), np.uint8)      # the orange confirm button
    img[50:70, 90:110] = BLUE
    ok, ev = price_is_diamond(img, 100, 60)
    assert ok is True
    assert ev["blue_px"] >= 150
    assert ev["blue_fraction"] < 0.5, "the fraction is small on this surface -- that is the point"


def test_a_resource_icon_on_the_orange_button_is_still_a_resource():
    img = np.full((120, 260, 3), (240, 150, 40), np.uint8)
    img[50:70, 90:110] = GOLD
    ok, _ = price_is_diamond(img, 100, 60)
    assert ok is False


# --------------------------------------------------------------- OCR band duplicates
def test_a_band_reread_of_a_price_never_replaces_the_whole_read():
    """15,000 read whole, ``,000`` read again by the right rail: keep the whole one."""
    toks = [tok("15,000", 605, 660, w=108), tok(",000", 622, 659, w=79, source="band:right_rail"),
            tok("剩余：1", 582, 608, w=94), tok("剩余：1", 361, 608, w=93),
            tok("剩余：1", 140, 608, w=93)]
    kept = [t["text"] for t in prefer_whole(toks)]
    assert "15,000" in kept
    assert ",000" not in kept, "the truncated band read survived"
    cards = read_cards(np.full((1280, 720, 3), PILL, np.uint8), toks)
    prices = {c.price_text for c in cards}
    assert "15,000" in prices
    assert ",000" not in prices


def test_a_band_read_is_kept_where_the_whole_pass_read_nothing():
    far = [tok("244,786", 636, 41, w=101),
           tok("2709.7万", 626, 339, w=101, source="band:right_rail")]
    kept = {t["text"] for t in prefer_whole(far)}
    assert kept == {"244,786", "2709.7万"}, "a band hit over an unread region was discarded"


def test_two_numbers_are_only_joined_when_their_boxes_actually_touch():
    touching = [tok("40", 10, 50, w=20), tok(",000", 36, 50, w=28)]
    assert [t["text"] for t in merge_fragments(touching)] == ["40,000"]
    apart = [tok("40", 10, 50, w=20), tok(",000", 130, 50, w=28)]
    assert {t["text"] for t in merge_fragments(apart)} == {"40", ",000"}


def test_a_join_that_does_not_form_a_number_keeps_both_fragments():
    """Losing a price is worse than failing to stitch it: the tokens must survive."""
    junk = [tok("1,2", 10, 50, w=20), tok("3", 34, 50, w=10)]
    out = sorted(t["text"] for t in merge_fragments(junk))
    assert out == ["1,2", "3"], out


def test_one_entry_per_card_even_when_the_label_is_split_across_bands():
    toks = [tok("剩余：1", 140, 608, w=93),
            tok("剩余", 118, 607, w=43, source="band:left_rail"),
            tok("：1", 603, 608, w=45, source="band:right_rail"),
            tok("剩余：1", 361, 608, w=93),
            tok("剩余：1", 582, 608, w=94)]
    groups = group_remaining(toks)
    assert len(groups) == 3, [g["x"] for g in groups]
    assert all(g["rest"] == 1 for g in groups)


# --------------------------------------------------------------- the item's real name
def test_the_name_is_the_item_line_not_the_icon_label_fragment():
    """The live dialog for 「10点统帅经验」 also OCRs the icon's own '10点统帅'."""
    toks = [tok("294,752", 636, 41, w=101), tok("X", 653, 431, w=24),
            tok("确定购买", 300, 391, w=160),
            tok("10", 108, 505, w=20), tok("10点统帅", 118, 505, w=60),
            tok("10点统帅经验", 230, 510, w=120),
            tok("使用后可获得：10点统帅经验", 260, 545, w=240)]
    name, desc = item_name_from_dialog(toks)
    assert name == "10点统帅经验"
    assert desc == "使用后可获得：10点统帅经验"


def test_a_speedup_dialog_names_the_speedup():
    toks = [tok("确定购买", 300, 391, w=160), tok("X", 653, 431, w=24),
            tok("5分钟", 112, 505, w=63), tok("5分钟研", 118, 505, w=55),
            tok("5分钟研究加速", 230, 510, w=120),
            tok("让1个[科研]队列倒计时减少5分钟。", 300, 545, w=260)]
    name, desc = item_name_from_dialog(toks)
    assert name == "5分钟研究加速"
    assert desc.startswith("让1个[科研]")


def test_the_read_only_tooltip_names_the_line_above_have_count():
    """The live tooltip is  name / 拥有数量：N / description  (seen on card r1c0)."""
    toks = [tok("5分钟训练加速", 210, 508, w=200),
            tok("拥有数量：15,018", 235, 545, w=180),
            tok("让1个[训练]队列倒计时减少5分钟。", 300, 580, w=300)]
    name, desc = item_name_from_dialog(toks)
    assert name == "5分钟训练加速"
    assert desc.startswith("让1个[训练]")


def test_a_tooltip_is_not_named_after_its_own_description():
    """英雄经验's description mentions 英雄经验; a fragment of it must never become the name."""
    toks = [tok("1,000点英雄经验", 200, 508, w=200),
            tok("拥有数量：1,064", 210, 545, w=160),
            tok("使用后获得1,000点英雄经验。", 300, 580, w=300),
            tok("英雄经验", 250, 585, w=80)]
    name, desc = item_name_from_dialog(toks)
    assert name == "1,000点英雄经验", name
    assert "使用后获得" in desc


def test_a_stopword_in_the_nav_must_not_blank_out_an_item_name():
    """``英雄`` is a HOME nav item AND part of 英雄经验 / 英雄组件自选箱."""
    for item in ("英雄经验", "英雄组件自选箱", "1,000点英雄经验"):
        toks = [tok(item, 200, 508, w=200), tok("拥有数量：1,064", 210, 545, w=160)]
        name, _ = item_name_from_dialog(toks)
        assert name == item, f"{item} was blanked out by a nav-name stopword"


# --------------------------------------------------------------- the operator's policy
@pytest.mark.parametrize("name,diamond,want", [
    ("10点统帅经验", True, "BUY"),          # the one authorised diamond spend
    ("1,000点英雄经验", True, "SKIP"),      # the measured near-miss: NOT 统帅经验
    ("5分钟研究加速", True, "SKIP"),
    ("史诗远征技能书", True, "SKIP"),
    ("铁矿 (安全)", True, "SKIP"),          # a resource, but paid for in diamonds
    ("生肉 （安全）", True, "SKIP"),
    ("生肉", False, "BUY"),                 # 资源换资源
    ("石头", False, "BUY"),
    ("木头", False, "BUY"),
    ("5分钟训练加速", False, "ASK"),        # resource price, item is not a resource
    (None, True, "ASK"),
])
def test_the_policy_table(name, diamond, want):
    assert decide_wandering(name, diamond)[0] == want


def test_a_diamond_price_is_only_ever_spent_on_commander_exp():
    for name in ("1,000点英雄经验", "5分钟治疗加速", "史诗远征技能书", "生肉"):
        verdict, reason = decide_wandering(name, True)
        assert verdict == "SKIP", f"{name} would have spent diamonds"
        assert "其他钻石商品" in reason


def test_an_uncovered_case_is_asked_not_guessed():
    verdict, reason = decide_wandering("5分钟训练加速", False)
    assert verdict == "ASK"
    assert "未覆盖" in reason


# --------------------------------------------------------------- reaching the store
class _FakeVisitor:
    """Drives ShopVisitor.enter over a scripted sequence of pages, with no device."""

    def __init__(self, pages: list[list[str]]) -> None:
        self.pages = pages
        self.i = 0
        self.backs = 0
        self.taps: list[tuple[float, float]] = []

    def see(self, tag, save=True):
        toks = [tok(x, 100 + 60 * n, 1258 if n else 500)
                for n, x in enumerate(self.pages[min(self.i, len(self.pages) - 1)])]
        self.i += 1
        return np.zeros((1280, 720, 3), np.uint8), toks

    def tap(self, xy):
        self.taps.append(tuple(xy))

    def back(self, why):
        self.backs += 1


HOME = ["探险", "英雄", "背包", "商店", "联盟", "野外"]
STORE = ["游荡商人", "神秘商店", "竞技商店", "统帅市", "免费刷新"]
UNKNOWN = ["古+5", "城墙", "110"]


def _run_enter(pages: list[list[str]]):
    from winter_agent_v2.shop_visit import ShopVisitor

    class V(ShopVisitor):
        def __init__(self):                     # no adapter needed
            self.out_dir = Path(".")
            self.log = lambda *a, **k: None
            self.trace = []
            self._back_used = 0
            self.fake = _FakeVisitor(pages)

        def see(self, tag, save=True):
            return self.fake.see(tag, save)

        def _tap_xy(self, xy):
            self.fake.tap(xy)
            return None

        def _back(self, why):
            self._back_used += 1
            self.fake.back(why)

    return V()


def test_entry_looks_at_the_frame_the_last_back_produced():
    """The live bug: HOME was reached by the final back press and then never checked."""
    v = _run_enter([UNKNOWN, UNKNOWN, HOME, STORE])
    img, toks = v.enter()
    assert v._back_used == 2, "should need two backs to reach HOME"
    assert v.fake.taps, "the 商店 nav was never tapped"


def test_entry_needs_no_back_when_already_in_the_store():
    v = _run_enter([STORE])
    v.enter()
    assert v._back_used == 0


def test_entry_keeps_the_store_it_reached_on_the_very_last_attempt():
    """Measured 2026-10-05 05:42 -- the entry off-by-one, on a real pass.

    AUTO was still driving when the pass began (a lease is a request, not a handover), so the
    tap on attempt 0 landed on the beast-hunt page and only the fourth and last attempt's
    re-tap reached the store.  That branch logged nothing, which is exactly how the evidence
    proves the post-tap check had *passed* -- and then it ``continue``d into an exhausted
    ``range`` and raised, throwing away the frame it had just verified.  The pass's own saved
    frame (``shop_observe_mystery_20261005T054052/01_shop_in3.png``) shows all four tabs read
    inside the tab band: 游荡商人 x=98, 神秘商店 x=302, 竞技商店 x=507, 统帅市 x=684, all y>=1241.
    """
    v = _run_enter([UNKNOWN, UNKNOWN, UNKNOWN, HOME, STORE])
    img, toks = v.enter()
    assert v._back_used == 3, "three backs are needed to get back to HOME"
    assert len(v.fake.taps) == 1, "商店 is tapped exactly once, on the last attempt"
    assert "游荡商人" in [t["text"] for t in toks], "the returned frame must be the store page"


def test_entry_reports_what_it_could_see_when_it_gives_up():
    v = _run_enter([UNKNOWN])
    with pytest.raises(RuntimeError) as e:
        v.enter()
    assert "SHOP_ENTRY_FAILED" in str(e.value)
    assert "城墙" in str(e.value), "the failure must name what was on screen"


def test_entry_cancels_the_exit_prompt_instead_of_pressing_back_again():
    v = _run_enter([["确认退出游戏吗？", "取消", "确定"], HOME, STORE])
    v.enter()
    assert v.fake.taps, "取消 and then 商店 should both have been tapped"
    assert v._back_used == 0, "the exit prompt must be cancelled, never backed out of"


def test_visit_reports_how_many_free_refreshes_it_actually_spent(monkeypatch, tmp_path):
    """The 3-free-refreshes-a-day rule had no counter behind it.

    ``run_shop_wandering`` incremented the day's tally only ``if report.get("refreshed")``, and
    ``visit`` never set that key -- so the cap the operator's policy names was never enforced.
    """
    import winter_agent_v2.shop_visit as sv

    blank = np.zeros((1280, 720, 3), np.uint8)

    class FakeVisitor:
        def __init__(self, ad, out_dir, log=print):
            self._back_used = 0
            self.trace = []
            self.refresh_calls = 0

        def enter(self):
            return blank, []

        def select_tab(self, tab):
            return blank, []

        def see(self, tag, save=True):
            return blank, []

        def _any(self, toks, words):
            return ["免费刷新"]

        def _dismiss_dialog(self):
            raise AssertionError("nothing should need dismissing on an empty roll")

        def free_refresh(self):
            self.refresh_calls += 1
            return self.refresh_calls <= 2

    class FakeAd:
        touch_balance = {"downs": 0, "ups": 0, "balanced": True, "stuck": 0}

    monkeypatch.setattr(sv, "ShopVisitor", FakeVisitor)
    report = sv.visit(FakeAd(), tmp_path, do_refresh=True, execute_buys=False, log=lambda *_: None)
    assert report["refreshed"] == 2, report["refreshed"]


def test_the_tooltip_is_not_in_the_decision_path(monkeypatch, tmp_path):
    """The read-only tooltip names the item but prints **no price**, so deciding from it splices a
    live name onto the card list's price.  On 2026-10-05 that produced a verdict on a card whose
    overlay had been showing a different item entirely.  The production pass must not call it.
    """
    import ast

    tree = ast.parse((ROOT / "winter_agent_v2" / "shop_visit.py").read_text(encoding="utf-8"))
    visited = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "visit")
    called = {n.func.attr for n in ast.walk(visited)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "read_name" not in called, "the pass must read names from the purchase overlay only"


# --------------------------------------------------------------- the second tap
def test_the_same_price_written_two_ways_compares_equal():
    """The decision is made on the overlay's ``16``; the client's confirm dialog says ``16钻石``.
    For a resource it writes ``25万`` where the overlay wrote ``25万`` too -- both spellings have
    to reduce to one number, or the guard would refuse honest spends."""
    from winter_agent_v2.shop_visit import _num_of
    assert _num_of("16") == 16
    assert _num_of("16钻石") == 16
    assert _num_of("您是否要花费16钻石?") == 16
    assert _num_of("1,500") == 1500
    assert _num_of("25万") == 250000
    assert _num_of("花费25万木材？") == 250000
    assert _num_of("没有数字") is None


BUY_DONE = (ROOT / "dataset" / "evidence" / "shop_visit_wandering_20261005T023330"
            / "r0_41_buy_r1c2_done.png")


@pytest.mark.skipif(not BUY_DONE.exists(), reason="the 2026-10-05 purchase frame is not present")
def test_the_purchase_dialog_is_recognised_and_quotes_the_authorised_amount():
    """This is the frame that exposed the whole problem: the first tap closed 确定购买 and looked
    like success, but on screen was 「购买确认」 asking 「您是否要花费16钻石?」 -- and nothing had
    been bought.  The reader has to see that dialog and find the 16 in it."""
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.shop_visit import CONFIRM_PHRASE, CONFIRM_TITLE, _num_of

    img = np.array(Image.open(BUY_DONE).convert("RGB"))
    toks = read_all(Image.fromarray(img))
    texts = " ".join(t["text"] for t in toks)
    assert CONFIRM_TITLE in texts or CONFIRM_PHRASE in texts, texts[:200]
    quoted = [v for v in (_num_of(t["text"]) for t in toks) if v is not None]
    assert 16 in quoted, quoted
    # ...and the overlay's own price button is still locatable on this dialog
    from winter_agent_v2.shop_visit import _inside, orange_price_button
    box = orange_price_button(img)
    assert box is not None
    assert any(_inside(box["bbox"], *t["centre"]) and t["text"].strip() == "16" for t in toks)


def test_confirm_makes_two_taps_and_guards_the_second_on_the_quoted_amount():
    """A structural pin: the spend must go through the client's own question, so ``confirm`` has to
    mention the confirmation dialog and the amount comparison.  Without this, a future edit can
    quietly go back to 'the first overlay closed, so it must have bought'."""
    src = (ROOT / "winter_agent_v2" / "shop_visit.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "ShopVisitor")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "confirm")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "CONFIRM_PHRASE" in names and "CONFIRM_TITLE" in names
    assert "_num_of" in names, "the second tap must be gated on the amount the client quotes"


# --------------------------------------------------------------- structural guard
def test_no_method_is_defined_twice_in_the_shop_module():
    """A rewritten ``buy`` was shadowed by the old one still below it.

    Python keeps the last definition, so the fixed method never ran and the live pass kept
    reporting the old failure string.  Nothing failed to import, nothing failed a test -- the
    only symptom was a reason code from code that had supposedly been replaced.
    """
    import ast
    import collections

    tree = ast.parse((ROOT / "winter_agent_v2" / "shop_visit.py").read_text(encoding="utf-8"))
    dupes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names = [f.name for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
            dupes += [f"{node.name}.{n}" for n, c in collections.Counter(names).items() if c > 1]
    assert dupes == [], f"shadowed definitions: {dupes}"


# --------------------------------------------------------------- the price button
def test_the_short_form_of_the_tooltips_own_quantity_line_is_not_the_item_name():
    """``拥有数量：N`` came back as ``有数量：N`` on the smaller render and beat 木材 (安全).

    The name reader picks the longest CJK candidate, and ``有数量：286,010,314`` carries three
    CJK characters against the real name's four -- except the real name is read at a smaller
    size and OCR splits it (``木材``, ``（安``, ``材 (安全)``), so the fragments each score lower
    and the quantity line wins.  That is exactly how a live pass decided on the string
    ``有数量：286,010,314``.
    """
    toks = [
        tok("木材 (安全)", 238, 487),
        tok("木材", 191, 487),
        tok("（安", 247, 486),
        tok("材 (安全)", 255, 486),
        tok("有数量：286,010,314", 309, 520, source="grid"),
        tok("拥有数量：", 216, 521, source="grid"),
        tok("主要从伐木场生产获得；可用于建造", 357, 573),
    ]
    name, desc = item_name_from_dialog(toks)
    assert name == "木材 (安全)"
    assert desc == "主要从伐木场生产获得；可用于建造"


def test_a_label_value_line_is_never_the_name():
    """A ``label：digits`` line is furniture.  Item names DO carry digits (``5,000点英雄经验``),
    so the rule cannot be "no digits" -- it has to be the colon immediately before them."""
    name, _ = item_name_from_dialog([
        tok("拥有数量：286,010,314", 309, 470),
        tok("煤 (安全)", 238, 440),
    ])
    assert name == "煤 (安全)"
    # ...and a name that legitimately contains digits survives
    name2, _ = item_name_from_dialog([tok("5,000点英雄经验", 300, 400)])
    assert name2 == "5,000点英雄经验"


def _orange_frame(width: int = 720, height: int = 1280) -> np.ndarray:
    """A stand-in for the purchase overlay: dark backdrop, one orange button at the measured
    place (bbox y 795-866), and orange scenery above the mid-line to be rejected."""
    img = np.full((height, width, 3), (60, 70, 90), np.uint8)
    img[60:300, 200:520] = (240, 130, 40)        # the merchant's art, above 0.45*H
    img[795:866, 222:498] = (247, 152, 30)       # the button, measured
    return img


def test_the_price_button_is_found_by_its_own_orange_paint():
    from winter_agent_v2.shop_visit import orange_price_button
    found = orange_price_button(_orange_frame())
    assert found is not None
    assert found["bbox"] == [222, 795, 276, 71]
    assert 795 <= found["centre"][1] <= 866


def test_the_orange_scenery_above_the_overlay_is_not_mistaken_for_the_button():
    from winter_agent_v2.shop_visit import orange_price_button
    img = _orange_frame()
    img[795:866, 222:498] = (60, 70, 90)         # remove the button, keep the merchant art
    assert orange_price_button(img) is None


def test_a_square_orange_blob_is_never_a_price_button():
    """Area alone let the shop's own orange paint through.

    The button is a wide, short pill -- measured 276x71, i.e. 3.89 wide per unit of height.  The
    shop also paints a gold hexagon icon for the 统帅经验 offer: 75x62, w/h 1.21, 3116 px.  Under
    a bare area floor that icon *was* a price button, and on 2026-10-05 it made a live probe
    answer "an overlay is open" on a plain shop page, dismiss a dialog that did not exist and
    press back out of the store.  The card it fires on is the one the policy says to buy.
    """
    from winter_agent_v2.shop_visit import orange_price_button
    img = np.full((1280, 720, 3), (60, 70, 90), np.uint8)

    # Clears the area floor, but an icon's shape -- rejected by aspect alone.
    img[700:800, 200:300] = (247, 152, 30)       # 100x100, 10000 px
    assert orange_price_button(img) is None, "a square blob is not a button"

    # The real hexagon icon's own size, under the old 3000 px floor.
    img[700:800, 200:300] = (60, 70, 90)
    img[788:850, 101:176] = (247, 152, 30)       # 75x62, 4650 px, where r1c0's icon sits
    assert orange_price_button(img) is None, "an icon is not a button"

    # ...and the button itself is still found, at the measured place.
    img[788:850, 101:176] = (60, 70, 90)
    img[795:866, 222:498] = (247, 152, 30)
    found = orange_price_button(img)
    assert found is not None and found["bbox"] == [222, 795, 276, 71]


HEXICON_FRAME = (ROOT / "dataset" / "evidence" / "shop_zone_map_20261005T033937"
                 / "map_03_tab_游荡商人.png")


@pytest.mark.skipif(not HEXICON_FRAME.exists(), reason="the 2026-10-05 gold-icon roll is absent")
def test_the_real_gold_hexagon_roll_is_not_read_as_an_open_overlay():
    """A pinned real frame: this roll's r1c0 is the 19💎 统帅经验 offer, whose icon is orange.

    The frames that *are* an open overlay all put the button at [222,795,276,71] with 15802-16380
    px; this page must produce nothing at all.
    """
    from PIL import Image

    from winter_agent_v2.shop_visit import orange_price_button
    img = np.array(Image.open(HEXICON_FRAME).convert("RGB"))
    assert orange_price_button(img) is None


def test_a_real_overlay_frame_still_yields_the_measured_button():
    """The other half of the same pin, so the aspect rule can never be widened to 'reject
    everything': four overlay frames from the 03:22 roll, all at the measured geometry."""
    from PIL import Image

    from winter_agent_v2.shop_visit import orange_price_button
    base = ROOT / "dataset" / "evidence" / "shop_visit_wandering_20261005T032229"
    frames = [base / "r0_40_card_r0c0_buy0_0.png", base / "r0_40_card_r0c1_buy0_0.png",
              base / "r0_40_card_r0c2_buy0_0.png", base / "r0_40_card_r1c0_buy0_0.png"]
    if not all(f.exists() for f in frames):
        pytest.skip("the 03:22 overlay frames are not present")
    for f in frames:
        got = orange_price_button(np.array(Image.open(f).convert("RGB")))
        assert got is not None, f.name
        assert got["bbox"] == [222, 795, 276, 71], f.name
        assert got["px"] >= 15000, f.name


def test_a_slider_duplicate_no_longer_makes_a_readable_overlay_ambiguous():
    """The live failure: the whole-frame pass read the slider as ``1`` and the grid pass read the
    same pixels as ``00``, so two numbers sat on two rows.  The price is inside the button; the
    duplicate is not, so it is not a candidate."""
    from winter_agent_v2.shop_visit import _inside, orange_price_button
    box = orange_price_button(_orange_frame())
    assert _inside(box["bbox"], 378, 831) is True       # the real price
    assert _inside(box["bbox"], 363, 703) is False      # the slider's duplicate


# --------------------------------------------------------------- merge, never delete
def test_a_resource_price_written_in_wan_survives_the_merge():
    """``67万`` and ``25万`` were *deleted* from the token stream by ``merge_fragments``.

    It selected the tokens it would join with ``[\\d,，]+`` and then rebuilt its return value out of
    that same selection -- so every ``N万`` price came out the other side missing.  ``read_cards``
    takes that output as its whole universe of numbers, so the cards that vanished were exactly
    the 资源换资源 ones the policy says to buy, and a pass could report "4 of 6 cards read".
    """
    toks = [tok("50", 163, 948), tok("67万", 383, 948), tok("25万", 603, 949)]
    out = {t["text"] for t in merge_fragments(toks)}
    assert out == {"50", "67万", "25万"}


def test_the_merge_still_joins_a_number_ocr_really_split():
    a = tok("15", 100, 500, w=24, h=20)
    b = tok(",000", 127, 501, w=40, h=20)
    out = merge_fragments([a, b])
    assert [t["text"] for t in out] == ["15,000"]


def test_a_fragment_that_cannot_be_joined_is_still_not_lost():
    a = tok("15", 100, 500, w=24, h=20)
    b = tok("000", 127, 500, w=40, h=20)
    out = merge_fragments([a, b])
    # 15000 is a well-formed number, so it joins; what matters is that nothing disappears.
    assert "".join(t["text"] for t in out).replace(",", "") == "15000"


def test_the_non_numeric_tokens_are_passed_through_untouched():
    toks = [tok("5,000点英雄经验", 300, 400), tok("煤 (安全)", 383, 948), tok("67万", 383, 948)]
    out = {t["text"] for t in merge_fragments(toks)}
    assert "5,000点英雄经验" in out and "煤 (安全)" in out


def test_a_card_whose_list_price_ocr_missed_is_still_a_card():
    """The list price is only for the report; the decision uses the overlay's own live price.

    ``read_cards`` used to ``continue`` -- i.e. drop the whole card -- when no price token sat
    under its anchor.  On the 2026-10-05 02:19 roll OCR missed r1c0's price pill and the pass
    logged "read 5 cards", so a card that could have been evaluated in full was never looked at.
    """
    frame = np.full((1280, 720, 3), PILL, np.uint8)
    toks = [
        tok("剩余：1", 140, 608), tok("140", 164, 659, source="whole"),
        tok("剩余：1", 361, 608), tok("470", 384, 659, source="whole"),
        tok("剩余：1", 140, 897),                      # <- OCR missed this one's price pill
        tok("剩余：1", 361, 897), tok("1,500", 383, 949, source="whole"),
    ]
    cards = read_cards(frame, toks)
    assert len(cards) == 4, [(c.row, c.col) for c in cards]
    by_pos = {(c.row, c.col): c for c in cards}
    assert by_pos[(1, 0)].price_text == ""
    assert by_pos[(1, 0)].currency_evidence["reason"] == "LIST_PRICE_UNREAD"
    assert by_pos[(1, 0)].tap_xy == (140, 897)
    assert by_pos[(1, 1)].price_text == "1,500"


BUTTON_FRAMES = ROOT / "dataset" / "evidence" / "shop_visit_wandering_20261005T024627"


@pytest.mark.skipif(not BUTTON_FRAMES.exists(), reason="the 2026-10-05 02:46 frames are absent")
@pytest.mark.parametrize("frame,price,item", [
    ("r1_40_card_r1c0_buy55_0.png", "19", "10点统帅经验"),   # the one that broke
    ("r0_40_card_r1c2_buy0_0.png", "16", "10点统帅经验"),
    ("r0_40_card_r0c0_buy0_0.png", "140", "稀有远征技能书"),
    ("r0_40_card_r0c2_buy0_0.png", "600", "1小时研究加速"),
])
def test_the_button_price_is_read_by_redrawing_the_glyphs(frame, price, item):
    """The price is white on orange, and OCR reading those pixels as they are MISreads them.

    ``r1_40_card_r1c0_buy55_0.png``'s button plainly says ``19``; as-is it comes back ``6L`` at 1x
    and ``V1`` at 3x, and the whole-frame pass returned no price token at all -- so a legitimate
    钻石换统帅经验 card was reported ``PRICE_NOT_IN_BUTTON`` and skipped.  Isolating the near-white
    glyphs and re-rendering them black-on-white reads the same bytes correctly.
    """
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.shop_visit import orange_price_button, read_button_price

    img = np.array(Image.open(BUTTON_FRAMES / frame).convert("RGB"))
    box = orange_price_button(img)
    assert box is not None, frame
    got, ev = read_button_price(img, box["bbox"])
    assert got == price, (frame, got, ev)
    assert price in ev["candidates"]
    assert item_name_from_dialog(read_all(Image.fromarray(img)))[0] == item


# --------------------------------------------------------------- pins on real pixels
EVID = ROOT / "dataset" / "evidence" / "shop_visit_wandering_20261005T010327"
LOAD_FRAME = (ROOT / "dataset" / "evidence" / "shop_tap_map_20261005T012942" / "00_locate.png")


@pytest.mark.skipif(not LOAD_FRAME.exists(), reason="the 2026-10-05 locate frame is not present")
def test_all_six_cards_are_read_including_the_two_priced_in_wan():
    """This frame has six cards on screen, and the pass that produced it read only four.

    The two it dropped were the two priced in resources for a six-figure amount -- the only two
    the operator's policy would have bought (煤 (安全) @ 25万 木材, and a 5分钟 speed-up @ 67万 肉).
    """
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    img = np.array(Image.open(LOAD_FRAME).convert("RGB"))
    cards = read_cards(img, read_all(Image.fromarray(img)))
    assert len(cards) == 6, [(c.row, c.col) for c in cards]
    by_pos = {(c.row, c.col): c for c in cards}
    assert by_pos[(1, 1)].price_text == "67万"
    assert by_pos[(1, 1)].price_is_diamond is False
    assert by_pos[(1, 2)].price_text == "25万"
    assert by_pos[(1, 2)].price_is_diamond is False
    assert by_pos[(0, 0)].price_text == "950" and by_pos[(0, 0)].price_is_diamond is True


@pytest.mark.skipif(not EVID.exists(), reason="the 2026-10-05 evidence frames are not present")
def test_on_the_real_overlay_frames_the_price_is_the_one_inside_the_button():
    """Read the actual live frames, not a mock: both of these aborted with
    ``PRICE_BUTTON_AMBIGUOUS(2)`` in the pass that produced them."""
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.shop_visit import _inside, orange_price_button

    for name, price, item in (("40_card_r0c0_buy0_0.png", "63", "5分钟训练加速"),
                              ("40_card_r1c0_buy0_0.png", "100", "铁矿 (安全)")):
        img = np.array(Image.open(EVID / name).convert("RGB"))
        toks = read_all(Image.fromarray(img))
        box = orange_price_button(img)
        assert box is not None, name
        re_read = [t for t in toks if t["text"].strip() == price]
        assert re_read, (name, price)
        assert all(_inside(box["bbox"], *t["centre"]) for t in re_read), name
        got, _ = item_name_from_dialog(toks)
        # OCR renders the bracket as ( or （ depending on the size it read the line at; both
        # spellings are the same item.
        assert _flat(got) == _flat(item), (name, got)


@pytest.mark.skipif(not EVID.exists(), reason="the 2026-10-05 evidence frames are not present")
def test_on_the_real_tooltip_frame_the_name_is_the_item_not_the_quantity():
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    img = np.array(Image.open(EVID / "10_card_r1c1_tip65.png").convert("RGB"))
    got, _ = item_name_from_dialog(read_all(Image.fromarray(img)))
    assert got == "木材 (安全)", got


@pytest.mark.skipif(not EVID.exists(), reason="the 2026-10-05 evidence frames are not present")
def test_the_anchor_is_the_remaining_label_and_that_is_where_it_points():
    """Nine taps at r1c1's anchor opened nothing while the same y on r1c0 and r1c2 opened the
    overlay, so the anchor itself is checked against the pixels: it must land inside the
    ``剩余：1`` box, not on the pill."""
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    img = np.array(Image.open(EVID / "03_tab_游荡商人.png").convert("RGB"))
    toks = read_all(Image.fromarray(img))
    cards = read_cards(img, toks)
    r1c1 = next(c for c in cards if (c.row, c.col) == (1, 1))
    ax, ay = r1c1.tap_xy
    rest = next(t for t in toks if t["text"].strip() == "剩余：1"
                and abs(t["centre"][0] - ax) < 40 and abs(t["centre"][1] - ay) < 40)
    x0, y0, w, h = rest["box"]
    assert x0 <= ax <= x0 + w and y0 <= ay <= y0 + h, (ax, ay, rest["box"])


# --------------------------------------------------------------- 神秘商店 (measured 2026-10-05)
ANCHOR = "第3代英雄组件自选箱"   # the name the client actually prints (shop_observe_mystery_…54637)


@pytest.mark.parametrize("name,disc,want", [
    # The operator's rule is a SUBSTRING rule, and the client's own name carries a generation
    # prefix.  Matching the whole string would never fire.
    (ANCHOR, "-50%", "BUY"),
    (ANCHOR, "-20%", "SKIP"),
    # No badge at all is *not* a reading failure: the badge prints the discount, so no badge
    # means full price, which is "otherwise" and therefore 跳过.  The operator said 否则跳过, and
    # BUY is reachable only from exactly 50 -- so every badge-reader failure lands on 跳过.
    (ANCHOR, None, "SKIP"),
    (ANCHOR, "%0L-", "SKIP"),         # OCR near-miss of the same badge, with no real percent
    ("5万经验(EXP)", "-20%", "SKIP"),
    # The one genuinely unanswerable case: if the name will not read, even "is this the item
    # the rule names" is unknown, so it is reported instead of silently skipped.
    (None, "-50%", "ASK"),
])
def test_the_mystery_policy_table(name, disc, want):
    verdict, reason = decide_mystery(name, disc)
    assert verdict == want, reason


@pytest.mark.parametrize("badge,want", [
    ("-50%", 50), ("-20%", 20), ("-10%", 10), ("-5 %", 5),
    (None, None), ("", None), ("%0L-", None), ("-", None), ("OL", None),
])
def test_a_discount_is_only_read_when_a_number_and_a_percent_sign_agree(badge, want):
    assert discount_percent(badge) == want


def test_the_gold_coin_is_the_second_number_on_the_top_bar():
    """神秘商店's prices are the gold coin, so the diamond wallet is not its spend witness.
    Measured top bar: 钻石 294,752 at x≈451, then the coin 3,290 at x≈630."""
    toks = [tok("294,752", 451, 43), tok("3,290", 630, 43)]
    assert [n[1] for n in top_bar_numbers(toks, 1280)] == [294752, 3290]


def test_an_ocr_fragment_of_the_diamond_count_is_not_a_third_currency():
    toks = [tok("294,752", 451, 43), tok("4,752", 461, 43), tok("3,290", 630, 43)]
    assert [n[1] for n in top_bar_numbers(toks, 1280)] == [294752, 3290]


MYSTERY_EVID = ROOT / "dataset/evidence/shop_observe_mystery_20261005T054637"


@pytest.mark.skipif(not MYSTERY_EVID.exists(), reason="the 2026-10-05 神秘商店 frame is absent")
def test_on_the_real_mystery_page_the_reader_finds_nine_slots_and_the_measured_badges():
    """The page is a 3x3 grid, not the merchant's 3x2, and the badges sit above each anchor.

    Read from the pass's own saved frame rather than from a fixture: this is the frame
    ``visit_mystery`` would have read, and the numbers (nine cards, -10% on r0c2, -20% on r1c0
    and r1c2) are what it must keep getting.
    """
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    img = np.array(Image.open(MYSTERY_EVID / "10_mystery_page_raw.png").convert("RGB"))
    cards = read_cards(img, read_all(Image.fromarray(img)))
    assert len(cards) == 9, [(c.row, c.col) for c in cards]
    got = {(c.row, c.col): c.discount for c in cards}
    assert got[(0, 2)] == "-10%", got
    assert got[(1, 0)] == "-20%", got
    assert got[(1, 2)] == "-20%", got
    # Row 2's prices fall below the fold, but its anchors and badges are still read: a card
    # with an unread price is still a card, which is the lesson the merchant's pass already paid for.
    assert all(c.rest == 1 for c in cards if c.row == 2), [c.to_dict() for c in cards]


@pytest.mark.skipif(not MYSTERY_EVID.exists(), reason="the 2026-10-05 神秘商店 overlay is absent")
def test_the_mystery_overlay_names_the_item_and_its_price_button_is_the_measured_one():
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.shop_visit import orange_price_button, read_button_price

    img = np.array(Image.open(MYSTERY_EVID / "20_card_overlay_raw.png").convert("RGB"))
    toks = read_all(Image.fromarray(img))
    name, _desc = item_name_from_dialog(toks)
    assert name == ANCHOR, name
    box = orange_price_button(img)
    assert box is not None, "the overlay's price button was not found"
    assert box["bbox"] == [222, 795, 276, 71], box      # identical to the merchant's overlay
    says, _ev = read_button_price(img, box["bbox"])
    assert says == "2,500", says


def test_the_body_ladder_never_reaches_into_the_bottom_tab_strip():
    """神秘商店 is 3x3, so its third row's anchor sits at y=1186 on a 1280 frame -- and the tab
    strip starts at 0.93*H = 1190, holding 游荡商人 / 神秘商店 / 竞技商店 / 统帅市 (all read at
    y=1241..1248 on the live page).  An unclamped ladder would put rungs at 1246 and 1266, i.e.
    *on another shop's tab*: the pass would go on reading a different shop's stock while still
    believing it was on the one it selected.  Reading the wrong shop silently is worse than
    failing to open one card, so the ladder is clamped, not shortened.
    """
    from winter_agent_v2.shop_visit import BODY_DY_LADDER, TAB_BAND, Card, ShopVisitor

    class V(ShopVisitor):
        def __init__(self):  # no adapter, no output dir: only the pure clamp is under test
            pass

    v = V()
    band_top = TAB_BAND * 1280

    def card(y: int) -> Card:
        return Card(row=2, col=0, rest=1, price_text="400", price_xy=(140, y + 45),
                    tap_xy=(140, y), price_is_diamond=False)

    low = v._body_ladder(card(1186), 1280)
    assert low, "the anchor itself is legal and must still be tappable"
    assert 0 in low
    assert all(1186 + dy < band_top for dy in low), [(dy, 1186 + dy) for dy in low]

    # A card high on the page keeps its whole spread: this is a clamp, not a shortening.
    assert v._body_ladder(card(609), 1280) == BODY_DY_LADDER

    # An anchor that is already inside the band yields nothing at all, so nothing is tapped.
    assert v._body_ladder(card(1250), 1280) == ()
