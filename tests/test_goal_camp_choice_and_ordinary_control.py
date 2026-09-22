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


if __name__ == "__main__":
    unittest.main()
