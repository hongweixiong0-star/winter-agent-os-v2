# -*- coding: utf-8 -*-
"""GAP-02 regression tests: the task board keeps its own title, and nothing else changes.

The defect, and the minimal condition that caused it

    `ocr.py:911-936` answers "which task tab is selected" from the board's CENTRED TOP-BAND heading,
    and its own comment says the inactive bottom tab label must not identify the page. But the generic
    keyword table then re-added that very label: `RULES` maps `每日任务` to `Page.DAILY`
    (`ocr.py:647`), and on the 成长任务 board that string is on screen as the inactive tab. Two
    candidates reached the decider at `ocr.py:1186`, `len(set(found)) != 1` returned
    `Page.UNKNOWN` with confidence 0.0, and the frame went unnamed.

    Witness: `dataset/evidence/daily_panel_observe_20261006T105705/p1_after_entry_tap.png`, whose own
    `production_reading.json` recorded exactly that on 2026-10-06.

    The fix is one condition, and it changes nothing else: when the precise top-band rule decided the
    task page, the task-board pair is removed from the generic table's votes and the precise answer is
    used; when a task label is on screen but the top band decided nothing, the task-board pair is
    removed and the frame stays UNKNOWN rather than being named from a tab that is always drawn.

The four cases this file pins

    1. the target frame gets the correct page identity;
    2. a similar page is not misread because it shares one text token;
    3. incomplete or conflicting evidence keeps UNKNOWN;
    4. the existing page mappings are unchanged (measured by an A/B elsewhere, asserted structurally
       here for the task pair).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRService, OCRToken, Page, RapidOCRBackend
from winter_agent_v2.runtime import read_frame_size

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "dataset" / "evidence" / "daily_panel_observe_20261006T105705" / "p1_after_entry_tap.png"

#: Page 720x1280. y_norm <= 0.16 is the top band the precise rule reads; the bottom band is the
#: always-visible tab strip near y_norm 0.887, which is where the real frame draws 每日任务/成长任务.
W, H = 720, 1280


def _tok(text: str, cx: float, cy: float, conf: float = 0.99) -> OCRToken:
    half = 40.0
    return OCRToken(text, conf, ((cx - half, cy - 12), (cx + half, cy - 12),
                                 (cx + half, cy + 12), (cx - half, cy + 12)))


def _classify(tokens) -> Page:
    result = OCRResult(tuple(tokens), "fixture")
    return OCRPageClassifier().classify(result, frame_size=(W, H)).page


@pytest.fixture(scope="module")
def frame_present():
    if not FRAME.is_file():
        pytest.skip(f"evidence frame not on disk: {FRAME}")


# ------------------------------------------------------------------ case 1: the target frame

def test_case1_the_target_frame_gets_the_page_it_prints(frame_present):
    """The frame prints 成长任务 as its centred heading; that is the answer."""
    result = OCRService(RapidOCRBackend()).recognize(FRAME)
    world = OCRPageClassifier().classify(result, frame_size=read_frame_size(FRAME))
    assert world.page is Page.GROWTH_TASKS, (
        f"expected 成长任务, got {world.page}. This is the GAP-02 fix; if it has been reverted the "
        "defect is back and the frame is again nameless"
    )
    assert world.confidence > 0.5, "the page must be named with real confidence, not a coin flip"


def test_case1b_the_ablation_still_shows_why(frame_present):
    """Removing the inactive bottom tab token used to be the only way to get the right answer; now
    the answer must be the same with or without it, which is the point of the fix."""
    result = OCRService(RapidOCRBackend()).recognize(FRAME)
    size = read_frame_size(FRAME)
    filtered = [t for t in result.tokens
                if not (str(t.text or "").strip() == "每日任务" and t.box
                        and t.centre[1] / size[1] > 0.5)]
    assert len(filtered) == len(result.tokens) - 1, "exactly one token should have been removed"
    with_tab = OCRPageClassifier().classify(result, frame_size=size).page
    without_tab = OCRPageClassifier().classify(
        type(result)(tuple(filtered), result.backend), frame_size=size).page
    assert with_tab is without_tab is Page.GROWTH_TASKS, (
        "the inactive tab label must no longer change the answer"
    )


# ------------------------------------------------------------------ case 2: a similar page

def test_case2_the_selected_daily_tab_is_still_daily():
    """The mirror image, and the case the fix must not break: 每日任务 as the TOP-BAND heading is a
    real answer, while 成长任务 sits below as the inactive tab."""
    tokens = [
        _tok("每日任务", W * 0.50, H * 0.098),          # centred heading, top band
        _tok("成长任务", W * 0.34, H * 0.887),          # inactive tab, bottom band
    ]
    assert _classify(tokens) is Page.DAILY


def test_case2b_sharing_a_token_does_not_make_two_pages_the_same():
    """Both boards draw BOTH words; only the top-band one may decide. So the two frames that differ
    only by which tab is centred must produce two different pages."""
    growth = [_tok("成长任务", W * 0.50, H * 0.098), _tok("每日任务", W * 0.66, H * 0.887)]
    daily = [_tok("每日任务", W * 0.50, H * 0.098), _tok("成长任务", W * 0.34, H * 0.887)]
    assert _classify(growth) is Page.GROWTH_TASKS
    assert _classify(daily) is Page.DAILY


# ------------------------------------------------------------------ case 3: UNKNOWN fallback

def test_case3_a_bottom_tab_alone_is_not_page_identity():
    """A tab that is always drawn cannot say which page this is. With no top-band heading the honest
    answer is UNKNOWN, not whichever tab happened to be read."""
    tokens = [
        _tok("成长任务", W * 0.34, H * 0.887),
        _tok("每日任务", W * 0.66, H * 0.887),
    ]
    assert _classify(tokens) is Page.UNKNOWN


def test_case3b_a_single_inactive_tab_is_still_not_page_identity():
    tokens = [_tok("每日任务", W * 0.66, H * 0.887)]
    assert _classify(tokens) is Page.UNKNOWN


def test_case3c_a_low_confidence_heading_is_not_a_heading():
    """Below the classifier's own confidence floor the token is not eligible, so the page must fall
    through to UNKNOWN rather than being named from the remaining tab."""
    tokens = [
        _tok("成长任务", W * 0.50, H * 0.098, conf=0.10),   # below minimum_confidence
        _tok("每日任务", W * 0.66, H * 0.887),
    ]
    assert _classify(tokens) is Page.UNKNOWN


# ------------------------------------------------------------------ case 4: no unrelated change

def test_case4_the_fix_touches_only_the_task_board_pair():
    """Structural check: the change is scoped to DAILY/GROWTH_TASKS and does not remove any other
    page from the generic table."""
    source = (ROOT / "winter_agent_v2" / "ocr.py").read_text(encoding="utf-8")
    # `if task_page is not None:` already existed in the file for the earlier append, so the marker
    # has to be the distinctive opening of THIS condition.
    marker = "The task board is the one page whose two identities"
    assert marker in source, "the GAP-02 condition (and its rationale) is gone"
    block = source.split(marker, 1)[1].split("calendar_entry =", 1)[0]
    assert "Page.DAILY" in block and "Page.GROWTH_TASKS" in block
    # No other page may be filtered out of `found` by this condition.
    others = [name for name in ("Page.HOME", "Page.MAP", "Page.EVENT", "Page.ALLIANCE",
                                "Page.BEAR", "Page.INTEL", "Page.MAIL")
              if name in block]
    assert not others, f"the GAP-02 condition now also filters {others}, which is out of scope"
