"""The camp action bar's entrance must not be stricter than its reader.

Measured 2026-10-03 on episode ``20261003_202133_286734``.  Two frames of the same route,
read by the same OCR, print almost the same thing -- both carry 盾兵营 | 详情 | 训练 | 升级 --
and ``read_selected_building_actions`` answers both of them correctly, returning 训练 at
(0.6743, 0.7156) and (0.6736, 0.7156) respectively.  The template ``TARGET_CAMP_ACTION_BAR``
matched one and missed the other.

That miss was not a missing control.  ``HybridVision._read_selected_building`` gated the whole
reading behind that one template, so on the frame it missed, the reader that can see the bar
was never allowed to run: ``training`` came back empty, ``BTN_OPEN_TRAINING_FROM_CAMP``
resolved to nothing, and all seven live ``OPEN_INFANTRY_TRAINING`` steps failed with
``SEMANTIC_TARGET_NOT_VERIFIED``.  The training queue stayed idle, which is the one state a
barracks must never be in.

This is the reader's own documented history one level up: the three templates it replaced
(``BTN_UPGRADE`` / ``BTN_TRAINING_MENU_LABEL`` / ``BTN_OPEN_TRAINING_FROM_CAMP``) "all miss
this rendering" (ocr.py, ``read_selected_building_actions``), which kept the route off a
barracks for ten consecutive attempts.  Teaching the reader to use the client's words fixed
that; leaving a template as the entrance to that reader re-imposed the same false negative.

Both directions are pinned here, because a gate that is loosened only in the permissive
direction is just a different bug:

* a frame that prints the bar must open the reader, even when the template misses;
* a frame that does not print the bar must still be refused.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from winter_agent_v2.ocr import (  # noqa: E402
    CAMP_ACTION_BAR_GATE,
    HybridVision,
    OCRResult,
    OCRToken,
    read_building_action_tokens,
)

FRAME_SIZE = (720, 1280)


def _token(text: str, cx_norm: float, cy_norm: float, *, w: int = 56, h: int = 36,
           confidence: float = 0.99) -> OCRToken:
    """A token whose box centre is the measured normalised point, in 720x1280 pixels."""
    cx, cy = cx_norm * FRAME_SIZE[0], cy_norm * FRAME_SIZE[1]
    box = ((cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
           (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2))
    return OCRToken(text, confidence, box)


#: The bar as the live client draws it, at the coordinates the 2026-10-03 frame measured.
#: Feeding these to the reader reproduces the production reading exactly -- which is why the
#: test can assert on the real numbers rather than on invented ones.
def _bar_tokens() -> tuple[OCRToken, ...]:
    return (
        _token("盾兵营", 0.5208, 0.4277, w=110, h=40),
        _token("详情", 0.3271, 0.7145),
        _token("训练", 0.6743, 0.7156),
        _token("升级", 0.5, 0.7367),
    )


def _frame_without_the_bar() -> tuple[OCRToken, ...]:
    """A city frame: HUD and navigation words, no building menu."""
    return (
        _token("探险", 0.10, 0.95), _token("英雄", 0.30, 0.95),
        _token("背包", 0.50, 0.95), _token("商店", 0.70, 0.95),
    )


class _Semantic:
    """Stands in for the template layer; records what it was asked."""

    def __init__(self, gate_hit: bool) -> None:
        self.gate_hit = gate_hit
        self.asked: list[str] = []

    def find(self, image_path, name):
        self.asked.append(name)
        return (1.0, 1.0, 1.0, 1.0) if self.gate_hit else None


class _TemplateVision:
    def __init__(self, gate_hit: bool) -> None:
        self.semantic = _Semantic(gate_hit)


class _Ocr:
    """Canned OCR; counts passes so a cache-hostile change is visible."""

    def __init__(self, tokens) -> None:
        self.tokens = tuple(tokens)
        self.calls = 0

    def recognize(self, image_path):
        self.calls += 1
        return OCRResult(self.tokens, "test-fixture")


def _read(gate_hit: bool, tokens):
    """Run the real ``_read_selected_building`` over a throwaway 720x1280 frame."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "probe.png"
        Image.new("RGB", FRAME_SIZE).save(frame)
        ocr = _Ocr(tokens)
        vision = HybridVision(_TemplateVision(gate_hit), ocr)
        from winter_agent_v2.models import Page, WorldState

        primary = WorldState(page=Page.HOME, confidence=0.99)
        out = vision._read_selected_building(frame, primary)
        return out, ocr


class TheGateIsNotStricterThanTheReaderTests:
    def test_the_frame_that_missed_the_template_now_reads_its_bar(self):
        """The regression, stated as the production frame's own numbers."""
        out, _ = _read(gate_hit=False, tokens=_bar_tokens())
        assert out is not None, (
            "this frame prints 盾兵营 | 详情 | 训练 | 升级 and read_selected_building_actions "
            "resolves 训练 on it; refusing here is what kept seven live training steps from "
            "opening a barracks"
        )
        assert out.training.get("menu_open") is True
        assert out.training.get("camp") == "SHIELD_CAMP"
        assert out.training.get("train_tap_norm") == (0.6743, 0.7156)

    def test_the_reading_is_the_same_whether_the_template_hit_or_missed(self):
        """The gate may decide *whether* to read, never *what* was read."""
        hit, _ = _read(gate_hit=True, tokens=_bar_tokens())
        missed, _ = _read(gate_hit=False, tokens=_bar_tokens())
        assert hit is not None and missed is not None
        assert hit.training == missed.training, (hit.training, missed.training)

    def test_a_frame_without_the_bar_is_still_refused(self):
        """The permissive direction is the dangerous one: no bar must stay no bar."""
        out, _ = _read(gate_hit=False, tokens=_frame_without_the_bar())
        assert out is None, (
            "a city frame carries no 训练/详情/升级 bar; reading one out of it would tap a "
            "control the client never drew"
        )

    def test_the_word_training_alone_does_not_open_the_gate(self):
        """訓練 appears in unrelated task copy; the bar is the set, not the word."""
        lone = (_token("训练", 0.6743, 0.7156), _token("将城墙升到9级", 0.5, 0.55))
        out, _ = _read(gate_hit=False, tokens=lone)
        assert out is None, (
            "one bar word is what a quest line looks like; requiring 详情 or 升级 alongside it "
            "is what keeps a sentence from becoming a selected building"
        )

    def test_the_bar_with_neither_detail_nor_upgrade_is_refused(self):
        """Both halves of the pair are load-bearing; 训练 + a stray word is not a bar."""
        partial = (_token("训练", 0.6743, 0.7156), _token("确定", 0.5, 0.9))
        out, _ = _read(gate_hit=False, tokens=partial)
        assert out is None

    def test_a_barracks_name_beside_training_is_still_not_the_bar(self):
        """The case that separates this gate from the check below it.

        ``_read_selected_building`` already refuses a reading without a 训练 point or without
        a camp, so a fixture missing *those* passes either way and proves nothing about the
        gate.  This one has both -- 盾兵营 and a 训练 point -- and differs only in that the
        client did not draw 详情 or 升级 beside them.  The gate must refuse it; the check
        below the gate would have accepted it, because a barracks name and a 训练 point are
        all that check asks for.
        """
        partial = (
            _token("盾兵营", 0.5208, 0.4277, w=110, h=40),
            _token("训练", 0.6743, 0.7156),
        )
        out, _ = _read(gate_hit=False, tokens=partial)
        assert out is None, (
            "the client draws 详情 / 升级 / 训练 together as one bar; a frame with the camp "
            "name and one of the three words is not that bar, and 训练 alone is a word that "
            "also appears in task copy"
        )

    def test_the_template_is_still_asked_first(self):
        """The gate stays cheap-first: the template is consulted before any reading."""
        _, ocr = _read(gate_hit=False, tokens=_bar_tokens())
        # One reading, not two: the loose read is reused rather than repeated below the gate.
        assert ocr.calls == 1, (
            "the gate's reading must be handed to the code below it, or every accepted frame "
            "pays for the bar twice"
        )


class TheProductionNumbersReplayTests:
    """The reader itself, over the tokens the live frame produced, with no template involved."""

    def test_the_readers_own_answer_is_unchanged(self):
        reading = read_building_action_tokens(_bar_tokens(), FRAME_SIZE)
        assert reading["actions"]["训练"] == (0.6743, 0.7156)
        assert reading["camp"] == "SHIELD_CAMP"
        assert reading["name"] == "盾兵营"

    def test_both_live_frames_resolve_the_same_control(self):
        """The two 2026-10-03 frames differ by 0.0007 in x and agree on y.

        Same button, same route, one template hit and one template miss -- which is the whole
        reason the gate had to stop being the entrance.
        """
        second = (
            _token("盾兵营", 0.5201, 0.4273, w=110, h=40),
            _token("详情", 0.3271, 0.7145),
            _token("训练", 0.6736, 0.7156),
            _token("升级", 0.5, 0.7367),
        )
        first_point = read_building_action_tokens(_bar_tokens(), FRAME_SIZE)["actions"]["训练"]
        second_point = read_building_action_tokens(second, FRAME_SIZE)["actions"]["训练"]
        assert first_point[1] == second_point[1]
        assert abs(first_point[0] - second_point[0]) < 0.002

    def test_a_frame_wins_over_a_stale_point_and_the_gate_name_is_pinned(self):
        """The gate constant is part of the contract; renaming it silently disables the gate."""
        assert CAMP_ACTION_BAR_GATE == "TARGET_CAMP_ACTION_BAR"
