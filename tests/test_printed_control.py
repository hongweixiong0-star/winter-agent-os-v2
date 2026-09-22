"""The layer that turns "the route named a control" into "and here is where the client drew it".

What this is for, 2026-09-22
----------------------------
Over 2485 production steps the single largest failure is ``SEMANTIC_TARGET_NOT_VERIFIED`` at
150, and its four biggest names are the most ordinary controls in the game --

    POPUP_GENERIC_REWARD_HEADER   38      BTN_OPEN_HOME   16
    BTN_DISMISS_INTEL_REWARD      31      BTN_CLOSE       14

-- every one of them a case of the brain deciding correctly and nothing being able to turn the
*name* into a pixel.  The resolver had two ways to do that: a pixel template, or a position the
device had tapped before.  A control with neither was unreachable however plainly the client had
drawn it.

This adds the third, and it is the one the operator's §二.2/§五 ask for: **read the client.**
Two sources, both a statement about the current frame:

* the word the client prints on the control (``知识库/ui/semantic_dictionary.json`` declares
  which words, per semantic, and per page);
* the instruction the client prints for the screen (``点击任意位置退出``, read at 0.9977).

Four things decide whether that is safe, and these tests are those four:

1. **the word is matched exactly** -- measured on a MAP frame whose navigation bar is covered
   by the search panel, where a substring match "found" ``城镇`` inside ``我的城镇``, a
   different control on the other side of the screen;
2. **the page declaration is respected**, so ``BTN_ATTACK`` (declared for BEAST/MAP) cannot be
   satisfied by a popup that asks to be tapped;
3. **a declared control whose words are absent is ABSENT, and that stops the search** -- it must
   not fall through to a remembered coordinate, because the memory cannot see that the bar is
   covered;
4. **no OCR means no answer**, not a crash and not a guess.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    CLIENT_TAP_ANYWHERE_PHRASES,
    OCRToken,
    find_printed_words,
    read_tap_anywhere_instruction,
)
from winter_agent_v2.runtime import LiveRuntime, _declared_record  # noqa: E402

FRAME = (720, 1280)

#: Kept outside ``dataset/raw``: the retention policy prunes captured frames, and a test that
#: points at a prunable file is a test that will one day fail for the wrong reason.
EVIDENCE = ROOT / "dataset/truth_audit/printed_controls_20260922"
MAP_FRAME = EVIDENCE / "map_nav_bar__city_cell_printed__live_20260922T0222.png"
MAP_COVERED_FRAME = EVIDENCE / "map_nav_bar_covered__search_panel_open__live_20260921T1338.png"
HOME_FRAME = EVIDENCE / "home_nav_bar__alliance_cell_printed__live_20260921T0151.png"
POPUP_FRAME = EVIDENCE / "reward_popup__tap_anywhere_to_exit__live_20260919T0916.png"
POPUP_INTEL_FRAME = EVIDENCE / "reward_popup_intel__tap_anywhere_to_exit__live_20260922T0225.png"
ALLIANCE_FRAME = EVIDENCE / "alliance_page__no_popup_close_control__live_20260921T0700.png"


def token(text: str, centre: tuple[float, float], confidence: float = 0.99) -> OCRToken:
    """A token whose box is a 40x30 px rectangle around ``centre``, in frame pixels."""
    cx, cy = centre
    return OCRToken(
        text=text,
        confidence=confidence,
        box=((cx - 20, cy - 15), (cx + 20, cy - 15), (cx + 20, cy + 15), (cx - 20, cy + 15)),
    )


@dataclass(frozen=True)
class _Reading:
    tokens: tuple[OCRToken, ...]


class _FakeOCR:
    """The readings a frame would produce, injected so the rules are testable without pixels."""

    def __init__(self, tokens: tuple[OCRToken, ...]) -> None:
        self._tokens = tuple(tokens)
        self.reads: list[dict | None] = []

    def recognize(self, image_path, roi=None):
        self.reads.append(roi)
        return _Reading(self._tokens)


def _frame_path(name: str) -> Path:
    """A real 720x1280 frame is needed only for its size; the reading itself is injected."""
    return ROOT / "dataset/truth_audit/printed_controls_20260922" / name


class _Holder:
    """Stands in for the vision: no template matches, and the frame is read by the fake OCR.

    ``find`` answering ``None`` is not a convenience -- it is the precondition of the layer
    under test, which only runs after the template layer has already failed.
    """

    def __init__(self, ocr) -> None:
        self.ocr = ocr

    def find(self, frame_path, semantic):
        return None


def _runtime_with(tokens: tuple[OCRToken, ...], ledger: dict | None = None) -> tuple[LiveRuntime, _FakeOCR]:
    fake = _FakeOCR(tokens)
    runtime = object.__new__(LiveRuntime)
    runtime.vision = _Holder(fake)
    runtime.semantic_vision = _Holder(fake)
    runtime._control_ledger = ledger or {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    return runtime, fake


def _ledger_entry(page: str, control: str, point: tuple[float, float]):
    from winter_agent_v2.control_experience import ControlExperience

    return ControlExperience(
        page=page,
        control=control,
        position_norm=point,
        known_result="PAGE_CHANGED",
        known_change="PAGE_CHANGED",
        last_result="PAGE_CHANGED",
        attempts=30,
        read_from_frame=str(_frame_path("map_nav_bar__city_cell_printed__live_20260922T0222.png")),
    )


# --------------------------------------------------------------- what the dictionary declares


class VocabularyTests(unittest.TestCase):
    def test_a_declared_control_carries_the_client_words_and_the_pages(self):
        self.assertEqual(_declared_record("BTN_OPEN_HOME"), (("MAP",), ("城镇", "City")))

    def test_an_undeclared_name_says_nothing_rather_than_no(self):
        """``None`` means "not written down", which is what lets the next layer answer."""
        self.assertIsNone(_declared_record("NO_SUCH_CONTROL"))
        self.assertIsNone(_declared_record(""))

    def test_a_control_the_client_prints_no_word_on_declares_no_words(self):
        """``BTN_CLOSE`` is an icon; the dictionary says so instead of inventing a word."""
        pages, words = _declared_record("BTN_CLOSE")
        self.assertEqual(pages, ("POPUP",))
        self.assertEqual(words, ())


# ------------------------------------------------------- matching the client's printed word


class PrintedWordTests(unittest.TestCase):
    def test_the_word_locates_the_control_and_returns_the_box_centre(self):
        hit = find_printed_words(
            MAP_FRAME, ("城镇", "City"), _FakeOCR((token("城镇", (648, 1256), 0.9994),))
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["word"], "城镇")
        self.assertTrue(hit["exact"])
        self.assertAlmostEqual(hit["center_norm"][0], 648 / 720, places=4)
        self.assertAlmostEqual(hit["center_norm"][1], 1256 / 1280, places=4)

    def test_a_substring_is_not_the_control(self):
        """Measured: on a covered navigation bar, ``我的城镇`` "supplied" 城镇 at (0.51, 0.49).

        That is the town hall in the middle of the map, not the navigation cell at the bottom.
        The default is therefore exact, and this is the frame that establishes it.
        """
        reading = _FakeOCR((token("我的城镇", (364, 633), 0.9954),))
        self.assertIsNone(find_printed_words(MAP_FRAME, ("城镇",), reading))
        allowed = find_printed_words(MAP_FRAME, ("城镇",), reading, allow_containment=True)
        self.assertIsNotNone(allowed)
        self.assertFalse(allowed["exact"])

    def test_the_most_confident_reading_wins(self):
        hit = find_printed_words(
            HOME_FRAME,
            ("联盟",),
            _FakeOCR((token("联盟", (200, 400), 0.80), token("联盟", (536, 1257), 1.000))),
        )
        self.assertAlmostEqual(hit["center_norm"][0], 536 / 720, places=4)
        self.assertAlmostEqual(hit["confidence"], 1.0, places=4)

    def test_a_band_keeps_a_page_title_out_of_the_answer(self):
        """For a control whose word is also a heading, the caller can say where to look."""
        reading = _FakeOCR((token("联盟", (300, 60), 1.000), token("联盟", (536, 1257), 1.000)))
        hit = find_printed_words(
            HOME_FRAME, ("联盟",), reading, band={"x_norm": 0.0, "y_norm": 0.9, "w_norm": 1.0, "h_norm": 0.1}
        )
        self.assertAlmostEqual(hit["center_norm"][1], 1257 / 1280, places=4)

    def test_a_frame_with_no_words_answers_nothing(self):
        self.assertIsNone(find_printed_words(MAP_FRAME, ("城镇",), _FakeOCR(())))
        self.assertIsNone(find_printed_words(MAP_FRAME, (), _FakeOCR((token("城镇", (648, 1256)),))))

    def test_the_whole_frame_is_read_not_a_crop(self):
        """A word can be anywhere on an unfamiliar screen, so this layer may not assume a band."""
        probe = _FakeOCR((token("城镇", (648, 1256)),))
        find_printed_words(MAP_FRAME, ("城镇",), probe)
        self.assertEqual(probe.reads, [None])


# ------------------------------------------------------- the client's instruction for a screen


class InstructionTests(unittest.TestCase):
    def test_the_instruction_is_read_with_its_own_position(self):
        hit = read_tap_anywhere_instruction(
            POPUP_FRAME, _FakeOCR((token("点击任意位置退出", (360, 1181), 0.9977),))
        )
        self.assertEqual(hit["phrase"], "点击任意位置退出")
        self.assertAlmostEqual(hit["center_norm"][0], 0.5, places=4)
        self.assertAlmostEqual(hit["center_norm"][1], 1181 / 1280, places=4)

    def test_an_ordinary_screen_has_no_instruction(self):
        self.assertIsNone(
            read_tap_anywhere_instruction(MAP_FRAME, _FakeOCR((token("最高可挑战13级野兽", (360, 1145)),)))
        )

    def test_every_declared_phrase_is_recognised(self):
        for phrase in CLIENT_TAP_ANYWHERE_PHRASES:
            with self.subTest(phrase=phrase):
                hit = read_tap_anywhere_instruction(POPUP_FRAME, _FakeOCR((token(phrase, (360, 1181)),)))
                self.assertIsNotNone(hit, phrase)
                self.assertEqual(hit["phrase"], phrase)

    def test_the_instruction_is_matched_inside_a_longer_line(self):
        """The client may append punctuation; a long, specific phrase inside a token is still it."""
        hit = read_tap_anywhere_instruction(
            POPUP_FRAME, _FakeOCR((token("点击任意位置退出。", (360, 1181), 0.97),))
        )
        self.assertIsNotNone(hit)


# ------------------------------------------------------------------- the three verdicts


class VerdictTests(unittest.TestCase):
    def test_the_clients_word_answers_first(self):
        runtime, _ocr = _runtime_with((token("城镇", (648, 1256), 0.9994),))
        verdict, point = runtime._client_printed_control(
            "BTN_OPEN_HOME", WorldState(page=Page.MAP, confidence=0.99), MAP_FRAME
        )
        self.assertEqual(verdict, "FOUND")
        self.assertAlmostEqual(point[0], 648 / 720, places=4)

    def test_declared_words_that_are_absent_mean_the_control_is_not_on_screen(self):
        runtime, _ocr = _runtime_with((token("我的城镇", (364, 633), 0.9954),))
        verdict, point = runtime._client_printed_control(
            "BTN_OPEN_HOME", WorldState(page=Page.MAP, confidence=0.99), MAP_COVERED_FRAME
        )
        self.assertEqual(verdict, "ABSENT")
        self.assertIsNone(point)

    def test_an_undeclared_name_leaves_the_answer_to_the_next_layer(self):
        runtime, _ocr = _runtime_with((token("城镇", (648, 1256)),))
        verdict, point = runtime._client_printed_control(
            "SOMETHING_NOBODY_DECLARED", WorldState(page=Page.MAP, confidence=0.99), MAP_FRAME
        )
        self.assertEqual(verdict, "UNDECLARED")
        self.assertIsNone(point)

    def test_a_control_declared_for_another_page_is_not_answered_here(self):
        """``BTN_CLOSE`` is declared for POPUP; on the alliance page it is not the same control."""
        runtime, _ocr = _runtime_with((token("点击任意位置退出", (360, 1181)),))
        verdict, _point = runtime._client_printed_control(
            "BTN_CLOSE", WorldState(page=Page.ALLIANCE, confidence=0.99), ALLIANCE_FRAME
        )
        self.assertEqual(verdict, "UNDECLARED")

    def test_the_instruction_answers_a_control_that_declares_no_word(self):
        runtime, _ocr = _runtime_with((token("点击任意位置退出", (360, 1181), 0.9977),))
        verdict, point = runtime._client_printed_control(
            "BTN_DISMISS_INTEL_REWARD", WorldState(page=Page.POPUP, confidence=0.99), POPUP_FRAME
        )
        self.assertEqual(verdict, "FOUND")
        self.assertAlmostEqual(point[1], 1181 / 1280, places=4)

    def test_the_client_saying_tap_anywhere_needs_no_dismissal_in_the_name(self):
        """Measured wrong in the first version: this name declares no dismissal and is one.

        38 steps died refusing to obey a screen that stated outright what to do, because the
        first version gated the instruction on the name matching CLOSE/DISMISS/LEAVE.
        """
        runtime, _ocr = _runtime_with((token("点击任意位置退出", (360, 1181), 0.9977),))
        verdict, _point = runtime._client_printed_control(
            "POPUP_GENERIC_REWARD_HEADER", WorldState(page=Page.POPUP, confidence=0.99), POPUP_FRAME
        )
        self.assertEqual(verdict, "FOUND")

    def test_an_instruction_does_not_answer_for_a_control_declared_for_another_page(self):
        """``BTN_ATTACK`` is declared for BEAST/MAP: a popup asking for a tap cannot satisfy it."""
        runtime, _ocr = _runtime_with((token("点击任意位置退出", (360, 1181), 0.9977),))
        verdict, _point = runtime._client_printed_control(
            "BTN_ATTACK", WorldState(page=Page.POPUP, confidence=0.99), POPUP_FRAME
        )
        self.assertEqual(verdict, "UNDECLARED")

    def test_no_ocr_means_no_answer_rather_than_an_exception(self):
        runtime = object.__new__(LiveRuntime)
        runtime.vision = object()
        runtime.semantic_vision = object()
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        verdict, point = runtime._client_printed_control(
            "BTN_OPEN_HOME", WorldState(page=Page.MAP, confidence=0.99), MAP_FRAME
        )
        self.assertEqual(verdict, "UNDECLARED")
        self.assertIsNone(point)

    def test_no_frame_means_no_answer(self):
        runtime, _ocr = _runtime_with((token("点击任意位置退出", (360, 1181)),))
        verdict, _point = runtime._client_printed_control(
            "POPUP_GENERIC_REWARD_HEADER", WorldState(page=Page.POPUP, confidence=0.99), None
        )
        self.assertEqual(verdict, "UNDECLARED")


# ------------------------------------------------- and what the resolver does with the verdict


class ResolverOrderTests(unittest.TestCase):
    """The layer is only worth having if its answer outranks the weaker one -- and if its
    refusal does too.  Both halves are pinned here, against the ledger itself."""

    def _runtime(self, tokens):
        ledger = {"MAP|BTN_OPEN_HOME": _ledger_entry("MAP", "BTN_OPEN_HOME", (0.9236, 0.9539))}
        return _runtime_with(tokens, ledger=ledger)

    def test_a_printed_word_outranks_a_remembered_position(self):
        runtime, _ocr = self._runtime((token("城镇", (648, 1256), 0.9994),))
        point = runtime._resolve_semantic_target(
            "BTN_OPEN_HOME", WorldState(page=Page.MAP, confidence=0.99), frame_path=MAP_FRAME
        )
        self.assertAlmostEqual(point[0], 648 / 720, places=4)
        self.assertNotAlmostEqual(point[0], 0.9236, places=3)

    def test_and_its_refusal_outranks_it_too(self):
        """The point that matters most in this file.

        On the covered frame the ledger's remembered (0.9236, 0.9539) sits on 自动狩猎 -- the
        panel covers the navigation bar and a coordinate measured on another frame cannot know
        that.  ``ABSENT`` has to stop the search here, or the feature would tap the wrong
        control and call it experience.
        """
        runtime, _ocr = self._runtime((token("我的城镇", (364, 633), 0.9954),))
        point = runtime._resolve_semantic_target(
            "BTN_OPEN_HOME", WorldState(page=Page.MAP, confidence=0.99), frame_path=MAP_COVERED_FRAME
        )
        self.assertIsNone(point)

    def test_the_ledger_still_answers_a_control_nothing_is_printed_on(self):
        """An undeclared, wordless control must not lose the layer that already worked."""
        runtime, _ocr = _runtime_with(
            (),
            ledger={
                "MAP|BTN_NEVER_DECLARED": _ledger_entry("MAP", "BTN_NEVER_DECLARED", (0.9236, 0.9539))
            },
        )
        point = runtime._resolve_semantic_target(
            "BTN_NEVER_DECLARED", WorldState(page=Page.MAP, confidence=0.99), frame_path=MAP_FRAME
        )
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 0.9236, places=3)

    def test_nothing_answers_a_control_no_layer_knows(self):
        runtime, _ocr = self._runtime(())
        point = runtime._resolve_semantic_target(
            "BTN_NEVER_DECLARED", WorldState(page=Page.MAP, confidence=0.99), frame_path=MAP_FRAME
        )
        self.assertIsNone(point, "no printed word, no instruction and no memory: nothing to tap")

    def test_the_read_is_visible_and_not_silent(self):
        """The ledger reads are held to this contract; this layer is held to it too.

        ``test_remembered_control`` states it as "the reuse must be visible, not silent", and
        the reason is the same here: a layer that changes where a tap lands has to be
        answerable from the run, not only from whatever the log happened to keep.
        """
        runtime, _ocr = self._runtime((token("城镇", (648, 1256), 0.9994),))
        runtime._resolve_semantic_target(
            "BTN_OPEN_HOME", WorldState(page=Page.MAP, confidence=0.99), frame_path=MAP_FRAME
        )
        self.assertTrue(runtime._printed_reads, "the read must be visible, not silent")
        self.assertIn("城镇", runtime._printed_reads[0])
        self.assertIn("MAP|BTN_OPEN_HOME", runtime._printed_reads[0])


# ------------------------------------------------------------------ on the frames themselves


class RealFrameTests(unittest.TestCase):
    """The same verdicts, but with the frames' real pixels through the production OCR."""

    @classmethod
    def setUpClass(cls):
        cls._vision = None

    def _production(self):
        if RealFrameTests._vision is None:
            sys.path.insert(0, str(ROOT / "tests"))
            from live_stack import production_vision

            RealFrameTests._vision = production_vision()
        return RealFrameTests._vision

    def _runtime(self):
        vision = self._production()
        runtime = object.__new__(LiveRuntime)
        runtime.vision = vision
        runtime.semantic_vision = vision.template_vision
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        return runtime

    def verdict(self, semantic: str, page: Page, frame: Path):
        self.assertTrue(frame.exists(), f"evidence frame missing: {frame}")
        return self._runtime()._client_printed_control(
            semantic, WorldState(page=page, confidence=0.99), frame
        )

    def test_the_map_navigation_cell_is_located_by_its_printed_word(self):
        verdict, point = self.verdict("BTN_OPEN_HOME", Page.MAP, MAP_FRAME)
        self.assertEqual(verdict, "FOUND")
        self.assertAlmostEqual(point[0], 0.9007, places=2)
        self.assertAlmostEqual(point[1], 0.9816, places=2)

    def test_the_same_control_is_absent_when_the_bar_is_covered(self):
        verdict, _point = self.verdict("BTN_OPEN_HOME", Page.MAP, MAP_COVERED_FRAME)
        self.assertEqual(verdict, "ABSENT")

    def test_the_alliance_cell_is_located_on_home_and_on_the_map(self):
        for frame, page in ((HOME_FRAME, Page.HOME), (MAP_FRAME, Page.MAP)):
            with self.subTest(frame=frame.name):
                verdict, point = self.verdict("BTN_OPEN_ALLIANCE", page, frame)
                self.assertEqual(verdict, "FOUND")
                self.assertAlmostEqual(point[0], 0.7444, places=2)

    def test_the_reward_popup_instruction_is_read_on_both_popups(self):
        """Two frames three days apart, same phrase, same place: (0.5000, 0.9227)."""
        for frame in (POPUP_FRAME, POPUP_INTEL_FRAME):
            with self.subTest(frame=frame.name):
                verdict, point = self.verdict("BTN_DISMISS_INTEL_REWARD", Page.POPUP, frame)
                self.assertEqual(verdict, "FOUND")
                self.assertAlmostEqual(point[0], 0.5, places=2)
                self.assertAlmostEqual(point[1], 0.9227, places=2)

    def test_the_alliance_page_refuses_a_popup_close_control(self):
        verdict, _point = self.verdict("BTN_CLOSE", Page.ALLIANCE, ALLIANCE_FRAME)
        self.assertEqual(verdict, "UNDECLARED")


if __name__ == "__main__":
    unittest.main()
