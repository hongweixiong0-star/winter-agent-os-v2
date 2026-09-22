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
    OPEN_WITH_ROWS = {
        "open": True,
        "camps": {"SHIELD_CAMP": {"status": "IDLE", "queue_available": True}},
        "rows": [
            {"kind": "CAMP", "key": "SHIELD_CAMP", "label": "盾兵", "status": "IDLE",
             "arrow_norm": [0.4569, 0.4266], "arrow_basis": "PANEL_RELATIVE_ESTIMATE"},
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
             "arrow_norm": [0.6, 0.4266]},
            {"kind": "CAMP", "key": "LANCER_CAMP", "label": "矛兵", "status": "IN_PROGRESS",
             "arrow_norm": [0.6, 0.4832]},
            {"kind": "CAMP", "key": "MARKSMAN_CAMP", "label": "射手", "status": "IDLE",
             "arrow_norm": [0.6, 0.5402]},
        ]
        frame = WorldState(page=Page.HOME, quick_panel={"open": True, "rows": rows})
        decision = _brain("MARKSMAN_CAMP_TRAINING").decide(frame, v2_registry())
        self.assertEqual(decision.skill, "OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN", decision.reason)


class TheTapLandsSomewhereRecordedTests(unittest.TestCase):
    """A tap that did nothing must still carry where it went.

    ``ExecutionResult.tap_point`` has existed since 2026-09-20 for exactly this, and the ledger --
    the artifact a post-mortem reads -- dropped it, so every row in
    ``learning/executor_backend.jsonl`` showed ``tap_point: None`` including the taps that worked.
    """

    class _StubExecutor:
        def __init__(self, tap_point):
            self._tap = tap_point
            self.device = None

        def execute(self, action):
            from winter_agent_v2.models import ExecutionResult

            return ExecutionResult(True, False, action, backend="ADB", tap_point=self._tap)

    def test_the_ledger_row_carries_the_landing_point(self):
        import tempfile

        from winter_agent_v2.executor_router import BackendLedger, ExecutorRouter, RoutingTable
        from winter_agent_v2.models import Action

        with tempfile.TemporaryDirectory() as folder:
            ledger_path = Path(folder) / "ledger.jsonl"
            router = ExecutorRouter(
                adb_executor=self._StubExecutor((441, 620)),
                routing=RoutingTable(),
                ledger=BackendLedger(ledger_path),
            )
            router.execute(Action("TAP_SEMANTIC", "QUICK_PANEL_ROW_LANCER_CAMP"),
                           "OPEN_TASK_FROM_QUICK_PANEL_LANCER")
            row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["action_target"], "QUICK_PANEL_ROW_LANCER_CAMP")
        self.assertEqual(row["tap_point"], [441, 620])


if __name__ == "__main__":
    unittest.main()
