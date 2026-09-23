"""The last step on a page that was reached: two reported faults, pinned on the frames that showed them.

Operator 2026-09-22, two live failures:

    故障 A：已经进入"挂机收益"弹窗，绿色"领取"按钮清楚可见，但游戏停留在弹窗没有完成领取。
    故障 B：已经进入射手营训练页面，蓝色"训练"按钮清楚可见，但 V2 没有点击训练，随后返回主城。

Both were traced to the same class of break -- the page model did not describe the state the frame was
actually in, so the brain had no action to emit and the route left a page it had just reached:

* the 挂机收益 dialog had **no recogniser at all** (``POPUP_EXPLORATION_IDLE_DIALOG`` exists in the
  template manifest with zero templates) while OCR reads its words at 1.00, so the claim verifier
  reported DIALOG_NOT_PROVEN on a tap that had in fact opened it;
* the training page set ``IN_PROGRESS``/``queue_available=False`` before reading a single token, and
  read the training button's **own caption** (the projected duration of the batch it would start) as a
  queue countdown -- and only the template path could ever set ``trainable``, which is the one key the
  brain's TRAIN_TROOPS gate reads.  A camp goal additionally did not *own* the training page at all.

These tests use the archived frames that produced the failures.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ocr as ocr_module  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402
from winter_agent_v2.verifier import (  # noqa: E402
    verify_exploration_claim_feedback,
    verify_panel_row_task_bar_opened,
)

AUTO = ROOT / "dataset/raw/control_panel/runtime_auto"
CONFIG = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))

#: The live frames: the exploration page, the dialog the client answered with, and the 射手营 page the
#: route walked away from.
CLAIM_BEFORE = sorted(AUTO.glob("*/" + "*_step_002_before_20260922T112112745827.png"))[-1]
CLAIM_DIALOG = sorted(AUTO.glob("*/" + "*_step_002_after_refresh_2_20260922T112144508334.png"))[-1]
MARKSMAN_PAGE = sorted(AUTO.glob("*/" + "*_step_010_before_20260922T112451123479.png"))[-1]
LANCER_PAGE = sorted(AUTO.glob("*/" + "*_step_009_before_20260922T112425181244.png"))[-1]

_OCR = None
_VISION = None


def _ocr():
    """One OCR service for the whole file: the frames are real and reading them is the point."""
    global _OCR
    if _OCR is None:
        _OCR = ocr_module.OCRService(
            ocr_module.ResilientOCRBackend(
                ocr_module.RapidOCRBackend(Path(CONFIG["ocr"]["module_path"]))
            )
        )
    return _OCR


def _vision():
    """The same page model production runs: template tier first, the OCR classifier behind it."""
    global _VISION
    if _VISION is None:
        _VISION = ocr_module.HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )
    return _VISION


def _brain(goal_id, goal=None):
    """A brain built the way the runtime builds it: the scheduler sets both fields."""
    brain = RuleBrain(current_goal=goal or goal_id)
    brain.goal_id = goal_id
    return brain


def _tokens(pairs, frame_size=(720, 1280)) -> OCRResult:
    return OCRResult(
        tuple(
            OCRToken(text=text, confidence=0.99, box=((x, y), (x + 40, y), (x + 40, y + 20), (x, y + 20)))
            for text, x, y in pairs
        ),
        "stub",
    )


class TheIdleIncomeDialogTests(unittest.TestCase):
    """故障 A: the dialog the client answers the claim with must be recognised as itself."""

    @classmethod
    def setUpClass(cls):
        cls.before = _ocr().recognize(CLAIM_BEFORE)
        cls.dialog = _ocr().recognize(CLAIM_DIALOG)

    def test_the_dialog_is_named_from_the_words_it_draws(self):
        state = OCRPageClassifier().classify(self.dialog, frame_size=(720, 1280))
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "EXPLORATION_IDLE_DIALOG")

    def test_the_claim_step_that_opened_it_now_verifies(self):
        """The measured failure: this pair produced EXPLORATION_IDLE_DIALOG_NOT_PROVEN."""
        before = WorldState(page=Page.EXPLORATION, exploration={"status": "CLAIMABLE"})
        from winter_agent_v2.ocr import HybridVision, RapidOCRBackend, ResilientOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision

        vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )
        before = vision.observe(CLAIM_BEFORE)
        after = vision.observe(CLAIM_DIALOG)
        result = verify_exploration_claim_feedback(before, after)
        self.assertTrue(result.ok, f"{result.reason} {result.evidence}")
        self.assertTrue(result.evidence["dialog_visible"])

    def test_the_brain_knows_which_skill_confirms_it(self):
        dialog = WorldState(page=Page.POPUP, popup="EXPLORATION_IDLE_DIALOG")
        decision = _brain("CLAIM_EXPLORATION_IDLE").decide(dialog, v2_registry())
        self.assertEqual(decision.skill, "CONFIRM_EXPLORATION_IDLE_CLAIM")

    def test_a_frame_without_those_words_is_not_this_dialog(self):
        """Only one of the two words is not enough, and neither is a frame that has neither."""
        title_only = _tokens([("挂机收益", 300, 280)])
        state = OCRPageClassifier().classify(title_only, frame_size=(720, 1280))
        self.assertNotEqual(state.popup, "EXPLORATION_IDLE_DIALOG")


class TheTrainingPageTests(unittest.TestCase):
    """故障 B: a barracks that can be started must be readable as startable."""

    @classmethod
    def setUpClass(cls):
        from winter_agent_v2.ocr import HybridVision
        from winter_agent_v2.vision import SemanticWorldVision

        cls.vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )

    def test_the_page_with_a_lit_training_button_is_startable(self):
        state = self.vision.observe(MARKSMAN_PAGE)
        self.assertIs(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("troop_type"), "MARKSMAN")
        self.assertEqual(state.training.get("status"), "AVAILABLE")
        self.assertTrue(state.training.get("queue_available"))
        self.assertTrue(state.training.get("trainable"), "the brain's own gate reads this key")
        self.assertIsNone(
            state.training.get("timer"),
            "the button's projected duration is not a queue countdown",
        )

    def test_a_running_queue_still_reads_as_busy(self):
        """The negative control: the word the client uses for a queue at work.

        Without this the fix would be "always call the camp startable", which is the opposite error
        and would retrain camps that are already working.
        """
        running = _tokens([
            ("英勇盾兵", 282, 20),
            ("盾兵营", 60, 1231),
            ("正在训练806位王牌盾兵", 200, 700),
            ("训练中", 200, 760),
        ])
        state = OCRPageClassifier().classify(running, frame_size=(720, 1280))
        self.assertIs(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("status"), "IN_PROGRESS")
        self.assertFalse(state.training.get("queue_available"))
        self.assertEqual(state.training.get("batch_count"), 806)
        self.assertIsNot(state.training.get("trainable"), True)

    def test_a_countdown_above_the_action_bar_is_still_a_queue_timer(self):
        """A queue's own countdown is drawn above the bar; the button's caption is inside it.

        Read on the real frame with one token added, so this isolates the one rule it is about: every
        other token is the frame the client actually drew.
        """
        base = _ocr().recognize(MARKSMAN_PAGE)
        with_countdown = OCRResult(
            tuple(base.tokens)
            + (OCRToken(text="02:33:11", confidence=0.99,
                        box=((520.0, 800.0), (560.0, 800.0), (560.0, 820.0), (520.0, 820.0))),),
            "real+one",
        )
        state = OCRPageClassifier().classify(with_countdown, frame_size=(720, 1280))
        self.assertIs(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("timer"), "02:33:11")
        self.assertEqual(state.training.get("status"), "IN_PROGRESS")
        self.assertFalse(state.training.get("queue_available"))


class TheCampGoalOwnsThePageTests(unittest.TestCase):
    """故障 B's second half: a camp goal may act on the page it navigated to."""

    @classmethod
    def setUpClass(cls):
        from winter_agent_v2.ocr import HybridVision
        from winter_agent_v2.vision import SemanticWorldVision

        cls.vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )
        cls.marksman = cls.vision.observe(MARKSMAN_PAGE)
        cls.lancer = cls.vision.observe(LANCER_PAGE)

    def test_the_goal_whose_camp_is_open_trains(self):
        for goal, state in (("MARKSMAN_CAMP_TRAINING", self.marksman),
                            ("LANCER_CAMP_TRAINING", self.lancer)):
            decision = _brain(goal).decide(state, v2_registry())
            self.assertEqual(decision.skill, "TRAIN_TROOPS", f"{goal}: {decision.reason}")

    def test_a_goal_never_trains_somebody_elses_camp(self):
        decision = _brain("LANCER_CAMP_TRAINING").decide(self.marksman, v2_registry())
        self.assertEqual(decision.skill, "SELECT_TRAINING_CAMP")
        self.assertIn("LANCER_CAMP", decision.reason)

    def test_the_aggregate_goal_owns_the_page_too(self):
        """``KEEP_TRAINING_PRODUCTIVE``'s route is TRAIN, so it may train what is idle there."""
        decision = _brain("KEEP_TRAINING_PRODUCTIVE").decide(self.marksman, v2_registry())
        self.assertEqual(decision.skill, "TRAIN_TROOPS", decision.reason)

    def test_a_goal_from_another_route_still_leaves_the_page(self):
        """The guard this replaced must keep working: a mail goal has no business on this page."""
        decision = _brain("MAIL_ROUTINE").decide(self.marksman, v2_registry())
        self.assertEqual(decision.skill, "BACK")


class TheCampSwitchBudgetTests(unittest.TestCase):
    """The live 2026-09-22 20:50 run, where the page answered BACK with an idle camp on screen.

    That run's own worker log, every step on the training page:

        12  TRY_ORDINARY_CONTROL  goal TRAIN, 盾兵营 open, status UNKNOWN
        13  SELECT_TRAINING_CAMP  goal MARKSMAN_CAMP_TRAINING -> 射手营 (AVAILABLE, trainable)
        14  TRAIN_TROOPS          -> after: IN_PROGRESS, batch 282, timer 03:28:51
        15  SELECT_TRAINING_CAMP  "training_queue_busy_switch_to_矛兵营" -> 矛兵营 (AVAILABLE, trainable)
        16  BACK                  "training_page_not_actionable_leaving_the_page"

    Step 16 stands on 矛兵营 with ``AVAILABLE``/``trainable`` in its own reading and leaves, because the
    two barracks switches had been spent by steps 13 and 15 -- *earlier goals'* switches, since the goal
    board is re-ranked every step (operator §四/§五).  The frames below are that run's own.
    """

    @classmethod
    def setUpClass(cls):
        from winter_agent_v2.ocr import HybridVision
        from winter_agent_v2.vision import SemanticWorldVision

        run = AUTO / "20260922_205021_021360"
        cls.vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )
        cls.shield_open = cls.vision.observe(run / "20260922_205021_021360_step_013_before_20260922T125450115785.png")
        cls.marksman_free = cls.vision.observe(run / "20260922_205021_021360_step_014_before_20260922T125515312326.png")
        cls.marksman_busy = cls.vision.observe(run / "20260922_205021_021360_step_015_before_20260922T125540200598.png")
        cls.lancer_free = cls.vision.observe(run / "20260922_205021_021360_step_016_before_20260922T125607147502.png")

    def test_the_frames_read_the_way_that_run_read_them(self):
        """If the reading differs, the rest of this class is testing another page."""
        self.assertTrue(self.marksman_free.training.get("trainable"), self.marksman_free.training)
        self.assertEqual(self.marksman_free.training.get("camp_open_label"), "射手营")
        self.assertIs(self.marksman_busy.training.get("queue_available"), False)
        self.assertTrue(self.lancer_free.training.get("trainable"), self.lancer_free.training)
        self.assertEqual(self.lancer_free.training.get("camp_open_label"), "矛兵营")

    def test_a_late_goal_still_reaches_its_own_camp(self):
        """The exact sequence above: two switches by one goal must not spend a third goal's chance."""
        brain = _brain("TRAIN")
        brain.goal_id = brain.current_goal = "MARKSMAN_CAMP_TRAINING"
        self.assertEqual(brain.decide(self.shield_open, v2_registry()).skill, "SELECT_TRAINING_CAMP")
        self.assertEqual(brain.decide(self.marksman_free, v2_registry()).skill, "TRAIN_TROOPS")
        self.assertEqual(brain.decide(self.marksman_busy, v2_registry()).skill, "SELECT_TRAINING_CAMP")
        brain.goal_id = brain.current_goal = "SHIELD_CAMP_TRAINING"
        decision = brain.decide(self.lancer_free, v2_registry())
        self.assertEqual(decision.skill, "SELECT_TRAINING_CAMP", decision.reason)
        self.assertIn("SHIELD_CAMP", decision.reason)

    def test_the_run_still_cannot_march_through_the_tabs_forever(self):
        """The per-run ceiling the per-goal count replaced is still there."""
        brain = _brain("TRAIN")
        switches = 0
        for goal in ("SHIELD_CAMP_TRAINING", "MARKSMAN_CAMP_TRAINING", "LANCER_CAMP_TRAINING") * 3:
            brain.goal_id = brain.current_goal = goal
            if brain.decide(self.lancer_free, v2_registry()).skill == "SELECT_TRAINING_CAMP":
                switches += 1
        self.assertLessEqual(switches, brain.MAX_CAMP_SWITCHES_PER_RUN)


class TheQuickPanelOpeningTests(unittest.TestCase):
    """The training route opens the 快捷面板 instead of stopping where it cannot see.

    Its states are the only in-city reading the client draws all at once, and the training page is
    not always legible: measured 2026-09-22 21:13, 盾兵营's page read ``UNKNOWN`` because the pointer
    covered the 训练 label.  The record for the handle, its reader and the runtime tier that taps it
    all existed; nothing ever asked, and 盾兵营's states stayed invisible.
    """

    def _home(self, panel, training=None):
        return WorldState(page=Page.HOME, quick_panel=panel, training=training or {})

    CLOSED = {"open": False, "handle": {"state": "COLLAPSED", "point_norm": [0.0181, 0.4301]}}
    OPEN = {
        "open": True,
        "camps": {
            "SHIELD_CAMP": {"status": "IDLE", "queue_available": True},
            "LANCER_CAMP": {"status": "IN_PROGRESS", "queue_available": False},
        },
        "handle": {"state": "EXPANDED", "point_norm": [0.4569, 0.5502]},
    }

    #: The same panel, with the rows the reader measures on a real frame (``arrow_norm`` per row).
    #:
    #: ``arrow_basis`` is ``ROW_BUTTON_SCAN`` and ``control`` is ``ARROW`` because that is what a real
    #: reading carries when the row can be entered: the button was located *on this frame*.  The
    #: estimate-only reading (``PANEL_RELATIVE_ESTIMATE`` / ``NONE``) is a separate state, tested
    #: below, and it is deliberately no longer a row to tap -- measured 2026-09-23 17:21:50, the tap
    #: at x 0.4042 landed on the row's own text and opened nothing.
    OPEN_WITH_ROWS = {
        "open": True,
        "camps": {"SHIELD_CAMP": {"status": "IDLE", "queue_available": True}},
        "rows": [
            {"kind": "CAMP", "key": "SHIELD_CAMP", "label": "盾兵", "status": "IDLE",
             "arrow_norm": [0.4569, 0.4266], "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
        ],
        "handle": {"state": "EXPANDED", "point_norm": [0.4569, 0.5502]},
    }

    #: The same row as the reader writes it when it could NOT locate the button: a hint, not a point.
    OPEN_WITH_AN_ESTIMATED_ROW = {
        "open": True,
        "camps": {"SHIELD_CAMP": {"status": "IDLE", "queue_available": True}},
        "rows": [
            {"kind": "CAMP", "key": "SHIELD_CAMP", "label": "盾兵", "status": "IDLE",
             "arrow_norm": [0.4042, 0.4266], "arrow_basis": "PANEL_RELATIVE_ESTIMATE", "control": "NONE"},
        ],
        "handle": {"state": "EXPANDED", "point_norm": [0.4569, 0.5502]},
    }

    def test_the_rows_own_arrow_is_preferred_to_the_power_route(self):
        """Operator §五: 如果对应快捷入口当前可见，优先使用对应行右侧箭头直接进入目标页面.

        Resolving the name is the runtime's job and it already does it per row
        (``QUICK_PANEL_ROW_<KEY>`` -> that row's own ``arrow_norm``), which is how the three
        look-alike arrows are told apart.
        """
        brain = _brain("TRAIN")
        decision = brain.decide(self._home(self.OPEN_WITH_ROWS), v2_registry())
        self.assertEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_SHIELD", decision.reason)
        row = next(r for r in self.OPEN_WITH_ROWS["rows"] if r["key"] == "SHIELD_CAMP")
        registry = v2_registry()
        self.assertEqual(registry.get(decision.skill).action.target, "QUICK_PANEL_ROW_SHIELD_CAMP")
        self.assertEqual(row["arrow_norm"], [0.4569, 0.4266])

    def test_a_row_whose_button_was_only_estimated_is_not_tapped(self):
        """The estimate is honest as a hint and worthless as a coordinate.

        This is the state the training route used to tap anyway: measured 2026-09-23 17:21:50, a row
        whose button scan found nothing still carried the reading's own fallback point (x 0.4042), the
        tap landed on the row's text, and no action bar opened.  The generic row picker refuses such a
        row on ``arrow_basis``; this pins that the route's own picker does too.
        """
        decision = _brain("TRAIN").decide(self._home(self.OPEN_WITH_AN_ESTIMATED_ROW), v2_registry())
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW", decision.reason)

    def test_a_row_the_panel_no_longer_draws_falls_back_to_the_proven_route(self):
        """``rows`` is read from *this* frame: no row means no arrow to tap, so the old hop runs."""
        panel = dict(self.OPEN_WITH_ROWS)
        panel["rows"] = []
        decision = _brain("TRAIN").decide(self._home(panel), v2_registry())
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW", decision.reason)

    def test_the_row_arrow_is_not_repeated_forever(self):
        """Bounded per run, so a row whose tap opens nothing cannot become a tap loop.

        The ceiling is read from the brain rather than written here twice: it is a per-run budget for
        the whole board (three barracks plus the research lab and the reward rows), so a literal 2 in
        the test would pin the old size of the panel rather than the property being tested.
        """
        brain = _brain("TRAIN")
        frame = self._home(self.OPEN_WITH_ROWS)
        seen = []
        for _ in range(brain.MAX_PANEL_ROW_ATTEMPTS_PER_RUN + 1):
            seen.append(brain.decide(frame, v2_registry()).skill)
        self.assertEqual(seen[0], "OPEN_TASK_FROM_QUICK_PANEL_SHIELD")
        self.assertEqual(
            seen[:brain.MAX_PANEL_ROW_ATTEMPTS_PER_RUN],
            ["OPEN_TASK_FROM_QUICK_PANEL_SHIELD"] * brain.MAX_PANEL_ROW_ATTEMPTS_PER_RUN,
        )
        self.assertIn("OPEN_POWER_OVERVIEW", seen,
                      "an arrow that does not open the page must hand back to the proven route")

    def test_a_closed_panel_is_opened_instead_of_stopping(self):
        brain = _brain("TRAIN")
        decision = brain.decide(self._home(self.CLOSED, {"queue_available": False}), v2_registry())
        self.assertEqual(decision.skill, "TRY_ORDINARY_CONTROL", decision.reason)
        self.assertIn("quick_panel", decision.reason)

    def test_the_open_panel_is_read_and_not_toggled_again(self):
        brain = _brain("TRAIN")
        decision = brain.decide(self._home(self.OPEN), v2_registry())
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW", decision.reason)
        self.assertEqual(brain.idle_camp_from_quick_panel, "SHIELD_CAMP")

    def test_a_frame_that_draws_no_handle_keeps_the_old_path(self):
        """Nothing to open means nothing to tap: the route is exactly what it was."""
        brain = _brain("TRAIN")
        decision = brain.decide(self._home({"open": False}), v2_registry())
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW", decision.reason)

    def test_the_opening_is_bounded(self):
        brain = _brain("TRAIN")
        frame = self._home(self.CLOSED, {"queue_available": False})
        for _ in range(brain.MAX_ORDINARY_ATTEMPTS):
            self.assertEqual(brain.decide(frame, v2_registry()).skill, "TRY_ORDINARY_CONTROL")
        decision = brain.decide(frame, v2_registry())
        self.assertNotEqual(decision.skill, "TRY_ORDINARY_CONTROL",
                            "the budget is what keeps this from becoming a tap loop")


class TheRowArrowOpensTheTaskBarTests(unittest.TestCase):
    """What a quick-panel row arrow really produces, measured on the frame after the tap.

    Operator 2026-09-22 23:42: the 矛兵 row's arrow was tapped from the panel and the client opened
    that barracks' **own action bar** in the city -- 详情 / 升级 / 训练 -- and the training page is
    behind that bar's 训练 button, one more hop.  The skill was judged by ``verify_training_page_open``,
    which demands ``after.page is Page.TRAINING``, so a working tap recorded
    FAILURE TRAINING_PAGE_NOT_PROVEN and the bar was left open: on the next step the goals re-ranked
    and nobody ever pressed it.
    """

    #: The archived frame the tap produced (23:42:41), and the panel frame it was tapped from.
    BAR_AFTER = sorted(AUTO.glob("*/" + "*_step_006_after_refresh_2_20260922T154326121610.png"))[-1]
    ROW_BEFORE = sorted(AUTO.glob("*/" + "*_step_006_before_20260922T154241186835.png"))[-1]

    @classmethod
    def setUpClass(cls):
        if not cls.BAR_AFTER.exists():
            raise unittest.SkipTest("the archived bar frame is not on this machine")
        cls.state = _vision().observe(cls.BAR_AFTER)

    def test_the_frame_says_which_bar_is_open_and_where_its_button_is(self):
        """The reading the launch of this whole hop depends on, on the frame itself."""
        self.assertEqual(self.state.page, Page.HOME)
        self.assertIs(self.state.training.get("menu_open"), True)
        self.assertEqual(self.state.training.get("camp"), "LANCER_CAMP")
        point = self.state.training.get("train_tap_norm")
        self.assertIsInstance(point, (list, tuple), "the 训练 label's own position must be read")

    def test_the_tap_that_opened_the_bar_verifies(self):
        before = _vision().observe(self.ROW_BEFORE)
        result = verify_panel_row_task_bar_opened(before, self.state, camp="LANCER")
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(result.evidence["task_bar_open_after"])
        self.assertFalse(result.evidence["task_page_open_after"],
                         "the training page is behind the bar, not behind the row's arrow")

    def test_a_look_alike_row_that_opened_another_camp_is_a_failure(self):
        """Operator §二: 不能因为多个箭头外观相同，就点击错误的任务行 -- and accepting it would say
        the same thing in the other direction."""
        result = verify_panel_row_task_bar_opened(self.state, self.state, camp="SHIELD")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "PANEL_ROW_OPENED_THE_WRONG_CAMP")

    def test_a_frame_with_no_bar_is_not_a_verified_row(self):
        """The proof is the state after the tap, never the tap: nothing opened means nothing proved."""
        before = _vision().observe(self.ROW_BEFORE)
        nothing = WorldState(page=Page.HOME, training={})
        result = verify_panel_row_task_bar_opened(before, nothing, camp="LANCER")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "PANEL_ROW_TASK_BAR_NOT_PROVEN")

    def test_the_goal_that_came_for_that_camp_finishes_the_bar(self):
        """§一: 当前 Goal 已在正确任务页面且仍可推进时，直接完成当前任务，不要返回主城."""
        for goal in ("LANCER_CAMP_TRAINING", "KEEP_TRAINING_PRODUCTIVE", "TRAIN"):
            with self.subTest(goal=goal):
                brain = _brain(goal)
                decision = brain.decide(self.state, v2_registry())
                self.assertEqual(decision.skill, "OPEN_INFANTRY_TRAINING", decision.reason)

    def test_the_bar_of_another_camp_is_left_to_its_own_goal(self):
        brain = _brain("SHIELD_CAMP_TRAINING")
        decision = brain.decide(self.state, v2_registry())
        self.assertNotEqual(
            decision.skill, "OPEN_INFANTRY_TRAINING",
            "SHIELD's goal must not press the LANCER bar's 訓練 button",
        )

    def test_a_per_camp_goal_picks_its_own_row_and_not_the_first_idle_one(self):
        """The regression this round found: the camp id was compared with ``f"{camp}_CAMP"``.

        ``_goal_camp()`` answers in the canonical form (``MARKSMAN_CAMP``) and that is what the panel
        reader puts in ``row["key"]``, so the extra suffix made the comparison unsatisfiable and every
        per-camp goal was handed no row at all.
        """
        rows = [
            {"kind": "CAMP", "key": "SHIELD_CAMP", "label": "盾兵", "status": "IN_PROGRESS",
             "arrow_norm": [0.6, 0.4266], "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
            {"kind": "CAMP", "key": "LANCER_CAMP", "label": "矛兵", "status": "IN_PROGRESS",
             "arrow_norm": [0.6, 0.4832], "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
            {"kind": "CAMP", "key": "MARKSMAN_CAMP", "label": "射手", "status": "IDLE",
             "arrow_norm": [0.6, 0.5402], "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
        ]
        frame = WorldState(page=Page.HOME, quick_panel={"open": True, "rows": rows})
        decision = _brain("MARKSMAN_CAMP_TRAINING").decide(frame, v2_registry())
        self.assertEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN", decision.reason)


#: An executor that reports a landing point without a device.  Module level, not nested in the test
#: case: the project's static check reads ``self.<Name>`` as a call it must find a definition for, and
#: a class defined inside a TestCase resolves through the instance, not the class.
class _StubExecutor:
    def __init__(self, tap_point):
        self._tap = tap_point
        self.device = None

    def execute(self, action):
        from winter_agent_v2.models import ExecutionResult

        return ExecutionResult(True, False, action, backend="ADB", tap_point=self._tap)


class TheTapLandsSomewhereRecordedTests(unittest.TestCase):
    """A tap that did nothing must still carry where it went.

    ``ExecutionResult.tap_point`` has existed since 2026-09-20 for exactly this, and the ledger --
    the artifact a post-mortem reads -- dropped it, so every row in
    ``learning/executor_backend.jsonl`` showed ``tap_point: None`` including the taps that worked.
    """

    def test_the_ledger_row_carries_the_landing_point(self):
        import tempfile

        from winter_agent_v2.executor_router import BackendLedger, ExecutorRouter, RoutingTable
        from winter_agent_v2.models import Action

        with tempfile.TemporaryDirectory() as folder:
            ledger_path = Path(folder) / "ledger.jsonl"
            router = ExecutorRouter(
                adb_executor=_StubExecutor((441, 620)),
                routing=RoutingTable(),
                ledger=BackendLedger(ledger_path),
            )
            router.execute(Action("TAP_SEMANTIC", "QUICK_PANEL_ROW_LANCER_CAMP"),
                           "OPEN_TASK_FROM_QUICK_PANEL_LANCER")
            row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["action_target"], "QUICK_PANEL_ROW_LANCER_CAMP")
        self.assertEqual(row["tap_point"], [441, 620])


    def test_a_row_the_table_cannot_name_is_never_offered_as_another_row(self):
        """Measured live 2026-09-23 00:42:30, and it tapped the wrong barracks.

        The reading offered the ``RESEARCH`` row and ``_QUICK_PANEL_ROW_SKILL`` held only the three camp
        keys, so ``.get(key, "..._SHIELD")`` substituted a real action aimed at the 盾兵 row --
        ``tap_point [225, 546]``, y 0.427, the 盾兵 row, while the goal was the research route.  A row
        with no skill must leave the decision to the route, not become somebody else's row.
        """
        rows = [
            {"kind": "CAMP", "key": "SOMETHING_NEW", "label": "新行", "status": "IDLE",
             "arrow_norm": [0.6, 0.5], "badge": "PRESENT", "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
        ]
        frame = WorldState(page=Page.HOME, quick_panel={"open": True, "rows": rows})
        decision = _brain("TRAIN").decide(frame, v2_registry())
        self.assertNotIn("QUICK_PANEL", decision.skill)
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW", decision.reason)

    def test_every_row_the_reader_can_name_has_its_own_skill(self):
        """The row table and the reader's keys must not drift apart in silence."""
        from winter_agent_v2.brain import _QUICK_PANEL_ROW_SKILL

        for key, skill in _QUICK_PANEL_ROW_SKILL.items():
            with self.subTest(row=key):
                entry = v2_registry().get(skill)
                self.assertIsNotNone(entry, f"{key} maps to {skill}, which does not exist")
                self.assertEqual(entry.action.target, f"QUICK_PANEL_ROW_{key}")

    def test_a_badged_idle_row_is_preferred_over_an_unmarked_one(self):
        """The red dot is the only per-row signal that separates two IDLE rows (operator §五)."""
        rows = [
            {"kind": "CAMP", "key": "LANCER_CAMP", "label": "矛兵", "status": "IDLE",
             "arrow_norm": [0.6, 0.4832], "badge": "ABSENT", "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
            {"kind": "CAMP", "key": "MARKSMAN_CAMP", "label": "射手", "status": "IDLE",
             "arrow_norm": [0.6, 0.5402], "badge": "PRESENT", "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
        ]
        frame = WorldState(page=Page.HOME, quick_panel={"open": True, "rows": rows})
        decision = _brain("KEEP_TRAINING_PRODUCTIVE").decide(frame, v2_registry())
        self.assertEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN", decision.reason)

    def test_the_route_is_read_from_the_route_not_from_a_stale_goal_id(self):
        """Measured 2026-09-23: a ``--goal TRAIN`` run kept the scheduler's ``goal_id``.

        The runtime writes ``brain.goal_id`` only when it also sets ``brain.current_goal``, so during a
        directed run ``goal_id`` held ``CLEAR_INTEL`` while ``current_goal`` was ``TRAIN`` -- and
        asking ``goal_id`` first made the run read as the INTEL route, which kept the panel branch from
        firing at all.
        """
        panel = {"open": True, "rows": [
            {"kind": "CAMP", "key": "LANCER_CAMP", "label": "矛兵", "status": "IDLE",
             "arrow_norm": [0.6, 0.4832], "badge": "PRESENT", "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"}]}
        frame = WorldState(page=Page.HOME, quick_panel=panel)
        brain = RuleBrain(current_goal="TRAIN")
        brain.goal_id = "CLEAR_INTEL"
        self.assertEqual(brain._goal_route(), "TRAIN")
        self.assertEqual(brain.decide(frame, v2_registry()).skill, "OPEN_TASK_FROM_QUICK_PANEL_LANCER")


class TheTrainingButtonPositionTests(unittest.TestCase):
    """The button's own place, read from the frame that drew it.

    Measured 2026-09-23 00:48:35: the quick panel's 矛兵 row arrow opened that barracks' bar, the bar
    opened its training page, the page read AVAILABLE / trainable, the brain emitted TRAIN_TROOPS -- and
    the target resolved to ``None``, so a lit button went unpressed.  The template for
    ``BTN_START_TRAINING`` is the whole button with its text, and the client's own hand cursor sits on
    that text as soon as the camp is entered, which is exactly what makes the template miss.
    """

    #: The two independently archived 矛兵营 training pages whose 訓練 label the hand covers.
    PAGE_WITH_HAND = sorted(AUTO.glob("*/" + "*_step_005_before_20260922T164827367068.png"))[-1]

    @classmethod
    def setUpClass(cls):
        if not cls.PAGE_WITH_HAND.exists():
            raise unittest.SkipTest("the archived training frame is not on this machine")
        cls.state = _vision().observe(cls.PAGE_WITH_HAND)

    def test_the_page_is_startable_even_though_its_label_is_covered(self):
        self.assertEqual(self.state.page, Page.TRAINING)
        self.assertEqual(self.state.training.get("status"), "AVAILABLE")
        self.assertIs(self.state.training.get("trainable"), True)
        # The label really is unreadable on this frame -- that is what makes the caption the answer.
        self.assertEqual(self.state.training.get("train_button_basis"), "BUTTON_CAPTION")

    @staticmethod
    def _resolver():
        """A runtime with only what the resolver path touches (no device, no cycle)."""
        from winter_agent_v2.runtime import LiveRuntime

        runtime = object.__new__(LiveRuntime)
        runtime._control_ledger = {}
        runtime._semantic_records_cache = None
        runtime._printed_reads = []
        runtime._printed_printed = set()
        runtime._printed_boxes = {}
        return runtime

    def test_the_button_is_located_from_that_reading(self):
        runtime = self._resolver()
        point = runtime._resolve_semantic_target("BTN_START_TRAINING", self.state)
        self.assertIsNotNone(point, "a lit button must resolve")
        x_norm, y_norm = point
        # Measured on this frame: the caption ``02:33:11`` at (0.7611, 0.8883); the button is the
        # right-hand control of the action bar, so the point has to be in its own band.
        self.assertGreater(x_norm, 0.5, "the button is the action bar's right-hand control")
        self.assertGreater(y_norm, 0.83, "inside the bar")
        self.assertLess(y_norm, 0.95, "still above the camp tab strip")

    def test_a_page_that_drew_no_button_is_not_tapped(self):
        runtime = self._resolver()
        bare = WorldState(page=Page.TRAINING, training={"status": "UNKNOWN"})
        self.assertIsNone(runtime._resolve_semantic_target("BTN_START_TRAINING", bare))

    def test_the_button_is_not_tapped_from_another_page(self):
        runtime = self._resolver()
        elsewhere = WorldState(page=Page.HOME, training=self.state.training)
        self.assertIsNone(
            runtime._resolve_semantic_target("BTN_START_TRAINING", elsewhere),
            "the point belongs to the page it was read from",
        )


    def test_a_row_whose_button_was_not_located_is_not_tapped(self):
        """Measured 2026-09-23 17:21:50 on the live panel, and it cost a wrong tap.

        The 盾兵 row read ``已完成`` -- the client draws a **green check** there where the other rows
        draw their blue arrow -- so the button scan found none and the reading fell back to its own
        estimate (``PANEL_RELATIVE_ESTIMATE``, x 0.4042).  The row was still offered and the tap landed
        at x 291, on the row's text, opening nothing.  An estimate is a hint, not a coordinate.
        """
        rows = [
            {"kind": "CAMP", "key": "SHIELD_CAMP", "label": "盾兵", "status": "IDLE",
             "source_word": "已完成", "badge": "UNKNOWN", "arrow_norm": [0.4042, 0.4262],
             "arrow_basis": "PANEL_RELATIVE_ESTIMATE", "control": "NONE"},
            {"kind": "CAMP", "key": "LANCER_CAMP", "label": "矛兵", "status": "IN_PROGRESS",
             "source_word": "02:22:00", "badge": "ABSENT", "arrow_norm": [0.6125, 0.4832],
             "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
            {"kind": "RESEARCH", "key": "RESEARCH", "label": "科技研究", "status": "IDLE",
             "source_word": "空闲中", "badge": "PRESENT", "arrow_norm": [0.6222, 0.6285],
             "arrow_basis": "ROW_BUTTON_SCAN", "control": "ARROW"},
        ]
        frame = WorldState(page=Page.HOME, quick_panel={"open": True, "rows": rows})
        decision = _brain("TRAIN").decide(frame, v2_registry())
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW", decision.reason)
        # The research row *was* located, so it is still offered to the goal that works from it.
        research = _brain("RESEARCH").decide(frame, v2_registry())
        self.assertEqual(research.skill, "OPEN_TASK_FROM_QUICK_PANEL_RESEARCH")


class TheDoneMarkerTests(unittest.TestCase):
    """已完成 is a tick to press, not a reward that was taken.

    Measured on three independent frames (2026-09-23, all 720x1280): a row whose task finished carries
    the client's green done-marker in its own control slot -- x 0.533-0.590, ~41x31 px, ~1270 green
    pixels -- and a frame whose every row is idle draws none.  Before this, the reader reported such a
    row as ``IDLE`` with its fallback estimate as the point, and the live run tapped that estimate at
    x 291 on the row's text (17:21:50) and opened nothing.
    """

    DONE_FRAME = sorted(AUTO.glob("*/" + "*_step_006_before_20260922T172143222865.png"))[-1]
    ALL_IDLE_FRAME = sorted(AUTO.glob("*/" + "*_step_003_before_20260922T161229012339.png"))[-1]

    @classmethod
    def setUpClass(cls):
        if not cls.DONE_FRAME.exists():
            raise unittest.SkipTest("the archived frames are not on this machine")
        cls.state = _vision().observe(cls.DONE_FRAME)

    def _row(self, state, key):
        return next((r for r in (state.quick_panel.get("rows") or []) if r.get("key") == key), {})

    def test_the_tick_is_read_as_the_rows_control(self):
        shield = self._row(self.state, "SHIELD_CAMP")
        self.assertEqual(shield.get("control"), "DONE")
        self.assertEqual(shield.get("source_word"), "已完成")
        # Measured on this frame: the green block's centre is (0.5618, 0.4375).
        done = shield.get("done_norm")
        self.assertIsInstance(done, list)
        self.assertAlmostEqual(done[0], 0.5618, places=2)
        self.assertAlmostEqual(done[1], 0.435, places=2)

    def test_the_other_rows_are_not_done(self):
        for key in ("LANCER_CAMP", "MARKSMAN_CAMP", "RESEARCH"):
            with self.subTest(row=key):
                self.assertEqual(self._row(self.state, key).get("control"), "ARROW")

    def test_a_frame_whose_rows_are_all_idle_draws_no_tick(self):
        state = _vision().observe(self.ALL_IDLE_FRAME)
        controls = {(r.get("key"), r.get("control")) for r in (state.quick_panel.get("rows") or [])}
        self.assertTrue(controls)
        self.assertNotIn("DONE", {control for _, control in controls})

    def test_the_enter_path_never_taps_the_tick(self):
        """Whatever else happens, a tick is not an enter-arrow: this is the wrong-action guard."""
        decision = _brain("SHIELD_CAMP_TRAINING").decide(self.state, v2_registry())
        self.assertNotIn("OPEN_TASK_FROM_QUICK_PANEL", decision.skill)
        self.assertNotEqual(decision.skill, "COLLECT_FINISHED_TRAINING_SHIELD")

    def test_the_collect_target_is_the_tick_itself(self):
        from winter_agent_v2.runtime import LiveRuntime

        runtime = object.__new__(LiveRuntime)
        runtime._control_ledger = {}
        runtime._semantic_records_cache = None
        runtime._printed_reads = []
        runtime._printed_printed = set()
        runtime._printed_boxes = {}
        point = runtime._resolve_semantic_target(
            "QUICK_PANEL_ROW_SHIELD_CAMP_DONE", self.state
        )
        self.assertIsNotNone(point, "the tick the frame drew must resolve")
        self.assertAlmostEqual(point[0], 0.5618, places=2)

    def test_a_done_row_is_not_offered_to_the_enter_path(self):
        """The two controls share a slot, so the arrow scan alone cannot tell them apart."""
        decision = _brain("RESEARCH").decide(self.state, v2_registry())
        self.assertEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_RESEARCH")

    def test_the_collect_skills_are_built_and_wired(self):
        """The capability exists; what is missing is a control that works, and that is stated below."""
        for key, skill in (
            ("SHIELD_CAMP", "COLLECT_FINISHED_TRAINING_SHIELD"),
            ("LANCER_CAMP", "COLLECT_FINISHED_TRAINING_LANCER"),
            ("MARKSMAN_CAMP", "COLLECT_FINISHED_TRAINING_MARKSMAN"),
            ("MY_REWARDS", "COLLECT_MY_REWARDS_ROW"),
        ):
            with self.subTest(row=key):
                entry = v2_registry().get(skill)
                self.assertIsNotNone(entry, f"{key} maps to {skill}, which does not exist")
                self.assertEqual(entry.action.target, f"QUICK_PANEL_ROW_{key}_DONE")

    def test_no_row_is_offered_for_collection_yet(self):
        """Measured 2026-09-23 17:51:02: the tick's own point collects nothing.

        The tap landed exactly on (404, 556), the panel closed, no reward dialog appeared, and the row
        still read 已完成 when the panel was re-read at 17:53:39.  So no row is claimable until what
        collects a finished batch is found -- an entry here would be one guaranteed failure per run and
        would eventually defer the whole training goal through this project's no-progress rule.
        """
        from winter_agent_v2.brain import _QUICK_PANEL_ROW_CLAIM_SKILL

        self.assertEqual(_QUICK_PANEL_ROW_CLAIM_SKILL, {})
        # ...and with an empty table the brain never emits a collect, however the frame reads.
        decision = _brain("SHIELD_CAMP_TRAINING").decide(self.state, v2_registry())
        self.assertNotIn("COLLECT", decision.skill)

    def test_collecting_is_proven_by_the_tick_going_away(self):
        from winter_agent_v2.verifier import verify_panel_row_done_collected

        def frame(control):
            return WorldState(page=Page.HOME, quick_panel={"open": True, "rows": [
                {"kind": "CAMP", "key": "SHIELD_CAMP", "status": "IDLE", "source_word": "已完成",
                 "control": control, "arrow_norm": [0.6, 0.42],
                 "arrow_basis": "ROW_BUTTON_SCAN", "done_norm": [0.5618, 0.435]}]})

        ok = verify_panel_row_done_collected(frame("DONE"), frame("ARROW"), row_key="SHIELD_CAMP")
        self.assertTrue(ok.ok, ok.reason)
        still = verify_panel_row_done_collected(frame("DONE"), frame("DONE"), row_key="SHIELD_CAMP")
        self.assertFalse(still.ok)
        self.assertEqual(still.reason, "PANEL_ROW_COLLECT_NOT_PROVEN")
        wrong_before = verify_panel_row_done_collected(frame("ARROW"), frame("ARROW"), row_key="SHIELD_CAMP")
        self.assertFalse(wrong_before.ok)
        self.assertEqual(wrong_before.reason, "PANEL_ROW_NOT_WAITING_TO_COLLECT")


class TheTickRowIsNotAnEnterTargetTest(unittest.TestCase):
    """Live 2026-09-23 18:54:27: a row the client marked done was tapped as an enter target.

    Goal MAIL, the 快捷面板 open, the 盾兵 row reading ``status=IDLE`` with ``control=DONE`` -- the
    client had drawn its green tick there -- and ``OPEN_TASK_FROM_QUICK_PANEL_SHIELD`` was issued.
    It failed ``PANEL_ROW_TASK_BAR_NOT_PROVEN``: the panel closed and no task bar appeared.  The
    generic row picker already refused such a row on ``control``; the TRAIN branch's own copy of the
    picker did not, which is what this pins.
    """

    def _state(self, control: str):
        row = {
            "key": "SHIELD_CAMP",
            "kind": "CAMP",
            "status": "IDLE",
            "control": control,
            "arrow_norm": [0.7097, 0.4262],
            "arrow_basis": "ROW_BUTTON_SCAN",
            # The client's own word for the row's state, as the reader records it: a barracks whose
            # queue finished draws 已完成 where an available one draws 空闲中.  Set here because the
            # reason names the word, and a fixture with no word would be testing a reading that cannot
            # happen -- both words are in ``QUICK_PANEL_IDLE_WORDS``, so both mean the camp is free.
            "source_word": "已完成" if control == "DONE" else "空闲中",
        }
        if control == "DONE":
            row["done_norm"] = [0.5618, 0.4344]
        return WorldState(
            page=Page.HOME,
            quick_panel={"open": True, "rows": [row], "camps": {"SHIELD_CAMP": {
                "status": "IDLE", "queue_available": True, "label": "盾兵"}}},
            confidence=0.99,
        )

    def test_a_done_row_is_not_entered(self):
        """A row the client marked done is not an enter target -- and not a reason to go and look.

        The second half changed 2026-09-23 (operator §五/§六).  What this test pinned before was that
        the tick row is refused, which it still is; what it asserted *instead* was
        ``OPEN_POWER_OVERVIEW`` with ``quick_panel_shield_camp_is_idle`` -- i.e. the refusal was
        expressed as the 加成总览 detour, and that detour is measured 100% failure
        (``POWER_DETAILS_NOT_PROVEN``, 20 of 20 in the corpus) while the panel had already said what
        the barracks' state is.  So the refusal is now a non-fatal stop: the goal steps aside and
        another selectable task gets the cycle.

        Note which state this is: ``control=DONE`` means the client *did* draw something in the row's
        control slot (its tick), which is why this is not the §一.6 fallback case.  A row the panel did
        not draw at all, or one whose slot is empty (``control=NONE``), still hands back to the proven
        route -- ``TheQuickPanelOpeningTests`` pins both of those.
        """
        from winter_agent_v2.brain import RuleBrain
        from winter_agent_v2.runtime_snapshot import is_fatal_stop
        from winter_agent_v2.skills import v2_registry

        brain = RuleBrain()
        brain.current_goal = "TRAIN"
        decision = brain.decide(self._state("DONE"), v2_registry())
        self.assertNotEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_SHIELD")
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(
            decision.reason,
            "quick_panel_row_shield_camp_reads_已完成_and_draws_no_enter_control",
        )
        self.assertFalse(is_fatal_stop(decision.reason), "it steps aside, it does not end the batch")

    def test_a_row_with_a_located_arrow_is_still_entered(self):
        from winter_agent_v2.brain import RuleBrain
        from winter_agent_v2.skills import v2_registry

        brain = RuleBrain()
        brain.current_goal = "TRAIN"
        decision = brain.decide(self._state("ARROW"), v2_registry())
        self.assertEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_SHIELD")


if __name__ == "__main__":
    unittest.main()
