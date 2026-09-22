"""The goal-aware camp switch and the generic ordinary-control attempt.

Why this file, 2026-09-22 (operator directive, four items)
----------------------------------------------------------
Two capabilities land together and both answer the same operator sentence: the machine
must act on what the *goal* and *this frame* say, not on what a table pre-registered.

1.  ``TRAINING_CAMP_NEXT`` must not march through the tabs mechanically.  The switch
    target is the brain's answer, chosen from the camps' own measured states
    (``world.camps``) and the operator's priority (矛兵营 / 射手营 first); the resolver
    only turns the chosen label into the pixel its tab sits at.  A camp positively read
    busy is never a target, and when every other known camp is busy the brain refuses to
    switch at all instead of walking into the same wall twice.

2.  A control with no registered skill must still be attemptable: ONE generic skill
    (``TRY_ORDINARY_CONTROL``), whose target is read off the frame by the client's own
    printed words, screened by a whitelist of ordinary actions and a blacklist of spend
    words, bounded per run, verified by the observed change itself.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.control_experience import classify_change  # noqa: E402
from winter_agent_v2.models import Action, Page, SkillState, WorldState  # noqa: E402
from winter_agent_v2.skills import Skill, SkillRegistry  # noqa: E402
from winter_agent_v2.ocr import OCRResult, OCRToken  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.verifier import verify_ordinary_control_tried  # noqa: E402

#: A real captured frame -- the scan needs a real image so ``read_frame_size`` can turn
#: pixel boxes into normalized ones.  Kept outside ``dataset/raw`` (see the retention note
#: in test_training_camp_switch.py).
FRAME = ROOT / "dataset/truth_audit/camp_action_bar_20260922/training_page__three_camp_tabs_and_queue__live_20260921T0953.png"

TABS = {"盾兵营": [0.1861, 0.984], "矛兵营": [0.5007, 0.984], "射手营": [0.8146, 0.9844]}


def _training_page(open_camp: str, camps: dict | None = None) -> WorldState:
    return WorldState(
        page=Page.TRAINING,
        training={"camp_open_label": open_camp, "queue_available": False, "camp_tab_norm": TABS},
        camps=camps or {},
        confidence=0.99,
    )


def _camp(camp: str, *, training=None, queue_available=None, status="UNKNOWN") -> dict:
    return {
        "camp": camp,
        "training": training,
        "queue_available": queue_available,
        "status": status,
    }


# --------------------------------------------------------------- which camp the goal wants


class GoalCampChoiceTests(unittest.TestCase):
    def setUp(self):
        self.brain = RuleBrain(current_goal="TRAIN")

    def test_a_positively_idle_camp_beats_an_unseen_one(self):
        """射手营 was measured idle: it wins over the never-seen 矛兵营."""
        world = _training_page("盾兵营", camps={"MARKSMAN_CAMP": _camp("MARKSMAN_CAMP", queue_available=True, status="AVAILABLE")})
        self.assertEqual(self.brain._choose_target_camp(world), "射手营")

    def test_the_operator_priority_orders_the_idle_tier(self):
        """Both idle: 矛兵营 first, the operator's own order."""
        world = _training_page(
            "盾兵营",
            camps={
                "LANCER_CAMP": _camp("LANCER_CAMP", queue_available=True, status="AVAILABLE"),
                "MARKSMAN_CAMP": _camp("MARKSMAN_CAMP", queue_available=True, status="AVAILABLE"),
            },
        )
        self.assertEqual(self.brain._choose_target_camp(world), "矛兵营")

    def test_a_camp_never_seen_is_worth_a_look(self):
        """No readings at all: the priority order picks 矛兵营 -- unknown is not refusal."""
        self.assertEqual(self.brain._choose_target_camp(_training_page("盾兵营")), "矛兵营")

    def test_a_positively_busy_camp_is_never_the_target(self):
        """矛兵营 read busy: the unseen 射手营 is the target, not the known-busy one."""
        world = _training_page("盾兵营", camps={"LANCER_CAMP": _camp("LANCER_CAMP", training=True, status="IN_PROGRESS")})
        self.assertEqual(self.brain._choose_target_camp(world), "射手营")

    def test_the_open_camp_is_never_its_own_target(self):
        world = _training_page("矛兵营")
        choice = self.brain._choose_target_camp(world)
        self.assertNotEqual(choice, "矛兵营")

    def test_every_other_camp_positively_busy_means_no_switch(self):
        """Both other camps read busy: ``None`` -- the goal leaves instead of cycling."""
        world = _training_page(
            "盾兵营",
            camps={
                "LANCER_CAMP": _camp("LANCER_CAMP", training=True, status="IN_PROGRESS"),
                "MARKSMAN_CAMP": _camp("MARKSMAN_CAMP", training=True, status="IN_PROGRESS"),
            },
        )
        self.assertIsNone(self.brain._choose_target_camp(world))

    def test_the_decision_carries_the_chosen_camp(self):
        """The switch decision names the camp it chose, so the episode says why."""
        world = _training_page("盾兵营")
        decision = self.brain.decide(world, _registry_with_camp_skills())
        self.assertEqual(decision.skill, "SELECT_TRAINING_CAMP")
        self.assertIn("矛兵营", decision.reason)

    def test_a_per_camp_goal_switches_to_its_own_camp(self):
        """Goal LANCER_CAMP_TRAINING means 矛兵营, not "the operator's first preference"."""
        brain = RuleBrain(current_goal="TRAIN")
        brain.goal_id = "LANCER_CAMP_TRAINING"
        self.assertEqual(brain._choose_target_camp(_training_page("盾兵营")), "矛兵营")
        brain.goal_id = "MARKSMAN_CAMP_TRAINING"
        self.assertEqual(brain._choose_target_camp(_training_page("盾兵营")), "射手营")

    def test_a_per_camp_goal_does_not_walk_to_another_camp(self):
        """LANCER_CAMP_TRAINING with 矛兵营 busy: this goal is done here, so no switch."""
        brain = RuleBrain(current_goal="TRAIN")
        brain.goal_id = "LANCER_CAMP_TRAINING"
        world = _training_page(
            "盾兵营",
            camps={"LANCER_CAMP": _camp("LANCER_CAMP", training=True, status="IN_PROGRESS"),
                   "MARKSMAN_CAMP": _camp("MARKSMAN_CAMP", queue_available=True, status="AVAILABLE")},
        )
        self.assertIsNone(brain._choose_target_camp(world))


def _registry_with_camp_skills() -> SkillRegistry:
    return SkillRegistry([
        Skill("SELECT_TRAINING_CAMP", "switch camp", Page.TRAINING, Action("TAP_SEMANTIC", "TRAINING_CAMP_NEXT"), state=SkillState.CANDIDATE),
    ])


# --------------------------------------------------------------- the resolver obeys the goal


class ResolverDesiredCampTests(unittest.TestCase):
    def _runtime(self, desired: str | None):
        runtime = object.__new__(LiveRuntime)
        runtime.vision = object()
        runtime.semantic_vision = object()
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        runtime.brain = SimpleNamespace(desired_camp_label=desired)
        return runtime

    def test_the_goal_pick_wins_over_the_mechanical_next(self):
        """盾兵营 open: the mechanical next is 矛兵营, but the goal picked 射手营."""
        point = self._runtime("射手营")._resolve_semantic_target(
            "TRAINING_CAMP_NEXT", _training_page("盾兵营")
        )
        self.assertEqual(point, (0.8146, 0.9844))

    def test_a_desired_label_the_frame_does_not_draw_falls_back(self):
        """A stale pick cannot be tapped: the frame's own order answers instead."""
        point = self._runtime("射手营")._resolve_semantic_target(
            "TRAINING_CAMP_NEXT",
            _training_page("盾兵营", ) if False else WorldState(
                page=Page.TRAINING,
                training={"camp_open_label": "盾兵营", "queue_available": False,
                          "camp_tab_norm": {"盾兵营": [0.1861, 0.984], "矛兵营": [0.5007, 0.984]}},
                confidence=0.99,
            ),
        )
        self.assertEqual(point, (0.5007, 0.984))

    def test_no_desired_pick_keeps_the_measured_order(self):
        point = self._runtime(None)._resolve_semantic_target(
            "TRAINING_CAMP_NEXT", _training_page("盾兵营")
        )
        self.assertEqual(point, (0.5007, 0.984))


# --------------------------------------------------------------- the ordinary-control attempt


class _StubOCR:
    """An OCR service answering one canned token list, in the shape find_printed_words reads."""

    def __init__(self, *tokens: tuple[str, tuple[tuple[float, float], ...]]):
        self._tokens = [OCRToken(text=text, confidence=0.99, box=box) for text, box in tokens]

    def recognize(self, image_path, roi=None):
        return OCRResult(self._tokens, "stub")


_BOX = (((100.0, 900.0), (140.0, 900.0), (140.0, 920.0), (100.0, 920.0)),)


class OrdinaryControlScanTests(unittest.TestCase):
    def _runtime(self, ocr, brain=None):
        runtime = object.__new__(LiveRuntime)
        runtime.vision = SimpleNamespace(ocr=ocr)
        runtime.semantic_vision = SimpleNamespace(ocr=None)
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        runtime.MAX_ORDINARY_ATTEMPTS = 2
        runtime._ordinary_attempts = 0
        runtime._ordinary_tried = set()
        runtime.brain = brain or RuleBrain(current_goal="MAIL")
        return runtime

    def test_a_whitelisted_word_becomes_a_tappable_point(self):
        ocr = _StubOCR(("领取", _BOX[0]))
        point = self._runtime(ocr)._ordinary_control_candidate(
            WorldState(page=Page.EVENT), FRAME
        )
        self.assertIsNotNone(point)
        self.assertTrue(0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0)

    def test_a_spend_word_anywhere_on_the_frame_vetoes_the_attempt(self):
        """免费领取 next to 充值 is refused whole -- the directive's hard boundary."""
        ocr = _StubOCR(("领取", _BOX[0]), ("充值", _BOX[0]))
        brain = RuleBrain(current_goal="MAIL")
        runtime = self._runtime(ocr, brain)
        self.assertIsNone(runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME))
        self.assertTrue(brain.ordinary_scan_exhausted)

    def test_the_same_word_is_not_tried_twice_in_one_run(self):
        ocr = _StubOCR(("领取", _BOX[0]))
        runtime = self._runtime(ocr)
        first = runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME)
        self.assertIsNotNone(first)
        second = runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME)
        self.assertIsNone(second)

    def test_the_run_bound_stops_the_scan(self):
        ocr = _StubOCR(("领取", _BOX[0]), ("前往", _BOX[0]))
        runtime = self._runtime(ocr)
        first = runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME)
        second = runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME)
        third = runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(third)
        self.assertTrue(runtime.brain.ordinary_scan_exhausted)

    def test_no_named_control_disables_the_fallback_for_this_run(self):
        ocr = _StubOCR(("盾兵营", _BOX[0]))
        brain = RuleBrain(current_goal="MAIL")
        runtime = self._runtime(ocr, brain)
        self.assertIsNone(runtime._ordinary_control_candidate(WorldState(page=Page.EVENT), FRAME))
        self.assertTrue(brain.ordinary_scan_exhausted)


class OrdinaryControlVerifierTests(unittest.TestCase):
    def test_a_page_change_proves_the_tap_did_something(self):
        ok = verify_ordinary_control_tried(
            WorldState(page=Page.EVENT), WorldState(page=Page.HOME)
        )
        self.assertTrue(ok.ok)

    def test_an_identical_frame_is_a_no_op_not_a_success(self):
        before = WorldState(page=Page.EVENT)
        ok = verify_ordinary_control_tried(before, WorldState(page=Page.EVENT))
        self.assertFalse(ok.ok)
        self.assertEqual(ok.reason, "ORDINARY_CONTROL_NO_OP")

    def test_the_change_kind_matches_the_ledger_reading(self):
        """The verifier and the experience ledger must never disagree about what happened."""
        before = WorldState(page=Page.EVENT)
        after = WorldState(page=Page.HOME)
        self.assertEqual(
            verify_ordinary_control_tried(before, after).evidence["change"],
            classify_change(
                {
                    "page": before.page.value,
                    "popup": None,
                    "resources": {},
                    "resource_bank": {},
                    "stamina": {},
                    "marches": [],
                    "queues": {},
                    "goals": None,
                    "goal_state": None,
                    "progress": None,
                    "events": {},
                    "daily": {},
                },
                {
                    "page": after.page.value,
                    "popup": None,
                    "resources": {},
                    "resource_bank": {},
                    "stamina": {},
                    "marches": [],
                    "queues": {},
                    "goals": None,
                    "goal_state": None,
                    "progress": None,
                    "events": {},
                    "daily": {},
                },
            ),
        )


# --------------------------------------------------------------- the skill exists and is dispatchable


class WiringTests(unittest.TestCase):
    def test_the_generic_skill_is_registered(self):
        from winter_agent_v2.skills import v2_registry

        skill = v2_registry().get("TRY_ORDINARY_CONTROL")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.risk, "LOW")

    def test_the_runtime_has_a_verifier_for_it(self):
        from winter_agent_v2.runtime import LiveRuntime

        self.assertIn("TRY_ORDINARY_CONTROL", LiveRuntime.VERIFIED_ATOMIC)


# --------------------------------------------------------------- on the real frames, end to end


class RealFrameChainTests(unittest.TestCase):
    """The two hops of the training route, decided and resolved on the live frames.

    Offline, but the whole production chain: the same ``HybridVision`` the runtime builds
    (template layer + OCR), the brain, and the resolver.  The point is that neither hop
    depends on a coordinate written into this file -- both are read off the frame.
    """

    HOME_FRAME = ROOT / "dataset/truth_audit/camp_action_bar_20260922/camp_selected_action_bar__shield_camp__live_20260922T0747.png"

    @classmethod
    def setUpClass(cls):
        import json

        from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision

        cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        cls.vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
            OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"])))),
        )

    def _runtime(self, brain):
        runtime = object.__new__(LiveRuntime)
        runtime.vision = self.vision
        runtime.semantic_vision = self.vision
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        runtime.MAX_ORDINARY_ATTEMPTS = 2
        runtime._ordinary_attempts = 0
        runtime._ordinary_tried = set()
        runtime.brain = brain
        return runtime

    def test_the_selected_camp_frame_is_where_the_training_control_was_read(self):
        """The 训练 control's point comes off this frame, not off a template that misses it."""
        world = self.vision.observe(image_path=self.HOME_FRAME)
        self.assertEqual(world.page, Page.HOME)
        self.assertTrue(world.training.get("menu_open"))
        self.assertEqual(world.training.get("camp"), "SHIELD_CAMP")
        runtime = self._runtime(RuleBrain(current_goal="TRAIN"))
        point = runtime._resolve_semantic_target(
            "BTN_OPEN_TRAINING_FROM_CAMP", world, frame_path=self.HOME_FRAME
        )
        self.assertIsNotNone(point)
        self.assertEqual(point, tuple(world.training["train_tap_norm"]))

    def test_the_busy_camp_page_switches_to_the_camp_the_goal_picked(self):
        """盾兵营's queue is running on this frame: the brain asks for 矛兵营 and the tap follows."""
        world = self.vision.observe(image_path=FRAME)
        self.assertEqual(world.page, Page.TRAINING)
        self.assertIs(world.training.get("queue_available"), False)
        brain = RuleBrain(current_goal="TRAIN")
        decision = brain.decide(world, _registry_with_camp_skills())
        self.assertEqual(decision.skill, "SELECT_TRAINING_CAMP")
        runtime = self._runtime(brain)
        point = runtime._resolve_semantic_target("TRAINING_CAMP_NEXT", world, frame_path=FRAME)
        self.assertEqual(point, tuple(world.training["camp_tab_norm"]["矛兵营"]))


# --------------------------------------------------------------- the training page, second render


class TrainingPageSecondRenderTests(unittest.TestCase):
    """The queue line without 训练中, measured live 2026-09-22.

    The first time this project reached a barracks training page for real
    (``20260922_120820_865903_step_006_after_refresh_2``), the client drew the running queue as
    ``原始时间：03:28:53``, put a tutorial hand over the 训练 control (OCR read the label as ``训``
    alone, conf 1.000), and drew the three camp tabs at the foot of the page.  The classifier's
    only training rule keyed on the word 训练中, so a page that had been reached correctly was
    answered UNKNOWN and the step died as ``TRAINING_PAGE_NOT_PROVEN``.

    The tokens below are that frame's own reading, at the confidences the live OCR produced.
    """

    TOKENS = (
        ("英勇盾兵", 0.996, ((282.0, 20.0), (420.0, 20.0), (420.0, 48.0), (282.0, 48.0))),
        ("盾兵营", 0.997, ((60.0, 1231.0), (125.0, 1231.0), (125.0, 1255.0), (60.0, 1255.0))),
        ("矛兵营", 0.990, ((286.0, 1233.0), (350.0, 1233.0), (350.0, 1257.0), (286.0, 1257.0))),
        ("射手营", 0.995, ((512.0, 1233.0), (576.0, 1233.0), (576.0, 1257.0), (512.0, 1257.0))),
        ("原始时间：", 0.926, ((400.0, 1019.0), (466.0, 1019.0), (466.0, 1042.0), (400.0, 1042.0))),
        ("训", 1.000, ((487.0, 1078.0), (517.0, 1078.0), (517.0, 1102.0), (487.0, 1102.0))),
        ("03:28:53", 0.951, ((448.0, 1108.0), (514.0, 1108.0), (514.0, 1132.0), (448.0, 1132.0))),
    )

    def _result(self, tokens):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=conf, box=box) for text, conf, box in tokens),
            "stub",
        )

    def test_the_page_is_named_without_the_word_训练中(self):
        from winter_agent_v2.ocr import OCRPageClassifier

        state = OCRPageClassifier().classify(self._result(self.TOKENS), frame_size=(720, 1280))
        self.assertEqual(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("camp_open_label"), "盾兵营")
        self.assertEqual(state.training.get("timer"), "03:28:53")
        self.assertEqual(state.training.get("troop_type"), "INFANTRY")

    def test_it_would_still_be_unknown_without_the_camp_tabs(self):
        """The rule needs both halves: a title alone is not this page."""
        from winter_agent_v2.ocr import OCRPageClassifier

        without_tabs = tuple(t for t in self.TOKENS if not t[0].endswith("营"))
        state = OCRPageClassifier().classify(self._result(without_tabs), frame_size=(720, 1280))
        self.assertNotEqual(state.page, Page.TRAINING)

    def test_the_quick_panels_bare_words_are_not_this_page(self):
        """The panel draws 盾兵 / 矛兵 / 射手 without 营 -- that must stay a panel, not a page."""
        from winter_agent_v2.ocr import OCRPageClassifier

        panel = (
            ("部队训练", 0.99, ((60.0, 500.0), (150.0, 500.0), (150.0, 522.0), (60.0, 522.0))),
            ("盾兵", 0.99, ((70.0, 540.0), (110.0, 540.0), (110.0, 562.0), (70.0, 562.0))),
            ("矛兵", 0.99, ((70.0, 580.0), (110.0, 580.0), (110.0, 602.0), (70.0, 602.0))),
            ("射手", 0.99, ((70.0, 620.0), (110.0, 620.0), (110.0, 642.0), (70.0, 642.0))),
        )
        state = OCRPageClassifier().classify(self._result(panel), frame_size=(720, 1280))
        self.assertNotEqual(state.page, Page.TRAINING)


# --------------------------------------------------------------- the barracks' first-open reveal


class NewTroopRevealTests(unittest.TestCase):
    """The screen the client answers the first tap on a barracks tab with.

    Measured live 2026-09-22T04:39:04Z, run 20260922_123407_610951: tapping 射手营's tab opened
    the camp and the client drew its new-troop card over it -- ``新``, ``6级英勇射手``, and the
    instruction ``点击任意位置继续``.  The run read the frame as an unknown page and recorded the
    switch as ``TRAINING_CAMP_SWITCH_NOT_PROVEN``, on a tap that had worked.
    """

    TOKENS = (
        ("新", 1.000, ((522.0, 177.0), (565.0, 177.0), (565.0, 201.0), (522.0, 201.0))),
        ("6级英勇射手", 0.999, ((238.0, 951.0), (485.0, 951.0), (485.0, 977.0), (238.0, 977.0))),
        ("点击任意位置继续", 0.985, ((226.0, 1221.0), (495.0, 1221.0), (495.0, 1243.0), (226.0, 1243.0))),
    )

    def _result(self, tokens=TOKENS):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=conf, box=box) for text, conf, box in tokens),
            "stub",
        )

    def test_the_reveal_is_named_from_its_own_words(self):
        from winter_agent_v2.ocr import OCRPageClassifier

        state = OCRPageClassifier().classify(self._result(), frame_size=(720, 1280))
        self.assertEqual(state.page, Page.POPUP)
        self.assertEqual(state.popup, "NEW_TROOP_UNLOCK")
        self.assertEqual(state.rewards.get("unlocked_troop_title"), "6级英勇射手")

    def test_the_goal_neutral_close_is_what_the_brain_picks(self):
        """The card declares its own exit, so the decision is the existing declared-exit close."""
        state = WorldState(page=Page.POPUP, popup="NEW_TROOP_UNLOCK", confidence=0.99)
        decision = RuleBrain(current_goal="TRAIN").decide(state, _registry_with_camp_skills())
        self.assertEqual(decision.skill, "DISMISS_SHARED_REWARD")

    def test_a_title_without_the_instruction_is_not_a_reveal(self):
        """The instruction is half the evidence: a unit name alone must not name the screen."""
        from winter_agent_v2.ocr import OCRPageClassifier

        state = OCRPageClassifier().classify(
            self._result(self.TOKENS[:2]), frame_size=(720, 1280)
        )
        self.assertNotEqual(state.popup, "NEW_TROOP_UNLOCK")


class PrintedExitOnTheRealFrameTests(unittest.TestCase):
    """The OCR fallback path, on the frame it was needed for: no template, no ledger entry.

    ``BTN_DISMISS_INTEL_REWARD`` is the target the goal-neutral close aims at, and on this it has
    no template at all and no ledger entry for a POPUP page -- which is precisely the state the
    fallback exists for.  The point comes from the client's own printed instruction, read off
    this frame.
    """

    FRAME = ROOT / (
        "dataset/raw/control_panel/runtime_auto/20260922_123407_610951/"
        "20260922_123407_610951_step_011_after_refresh_2_20260922T043904261212.png"
    )

    def test_the_client_instruction_supplies_the_point(self):
        if not self.FRAME.exists():
            self.skipTest("the live capture was pruned by the retention policy")
        import json

        from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision

        cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        vision = HybridVision(
            template,
            OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"])))),
        )
        world = vision.observe(image_path=self.FRAME)
        self.assertEqual(world.popup, "NEW_TROOP_UNLOCK")

        runtime = object.__new__(LiveRuntime)
        runtime.vision = vision
        runtime.semantic_vision = template.semantic
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        runtime.brain = RuleBrain(current_goal="TRAIN")
        point = runtime._resolve_semantic_target(
            "BTN_DISMISS_INTEL_REWARD", world, frame_path=self.FRAME
        )
        self.assertIsNotNone(point)
        self.assertTrue(runtime._printed_reads, "the read must be visible, not silent")
        self.assertIn("点击任意位置继续", runtime._printed_reads[0])


if __name__ == "__main__":
    unittest.main()
