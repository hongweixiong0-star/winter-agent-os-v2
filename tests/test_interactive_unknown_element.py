"""An unknown element: judged interactive, tried through the one execution chain, and remembered.

Operator directive 2026-09-22 ("通用未知 UI 元素处理机制"):

    识别到元素 -> 查询词典与经验 -> 未命中时判断是否可交互 -> 结合 Goal 判断相关性与风险
    -> 合理的普通低风险候选直接通过现有 MAA 尝试 -> 观察实际结果 -> 单步成功立即登记为 L1 动作
    -> 下次在相同适用条件下直接复用

These tests pin the four parts of that sentence that can be checked without the game, plus the two
that cannot be faked:

* the interactivity judgement reads the frame's own boxes and wording -- and *refuses* the shapes
  this project's frames really produce that are not controls (a system toast, a countdown, a value);
* the candidate exists **before** the tap, so a step that dies still leaves the region on record;
* an L1 action is registered by a step whose own verifier passed and nothing else -- not by a tap
  that "succeeded", not by a page that changed;
* reuse requires the same page, goal and state *and* the element still being drawn on the frame;
  when the picture no longer matches, the mechanism identifies again instead of tapping where the
  control used to be;
* a failure does not delete anything and does not get repeated for ever;
* one experience store (``control_experience``), one candidate store (``ui_collection``), no second
  executor, and the skill registry and template manifest are not touched by any of it.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience, ui_collection  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Action, Decision, ExecutionResult, Page, VerificationResult, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: A real live capture of the training page (720x1280), already used elsewhere in this suite.
REAL_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_123407_610951/"
    "20260922_123407_610951_step_011_after_refresh_2_20260922T043904261212.png"
)

#: A button-shaped box in the middle of a 720x1280 frame: 120 px wide, 40 px tall.
BUTTON_BOX = ((300.0, 900.0), (420.0, 900.0), (420.0, 940.0), (300.0, 940.0))


class _StubOCR:
    """One canned token list in the shape the OCR readers consume.

    Module level: ``tools/check_wiring.py`` reads ``self.<Name>(...)`` as a call to a method of the
    enclosing class, and a nested helper would be reported as a dangling self-call.
    """

    def __init__(self, *tokens):
        self._tokens = tokens

    def recognize(self, image_path, roi=None):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=conf, box=box) for text, conf, box in self._tokens),
            "stub",
        )


def _runtime(*, ocr=None, ledger=None, store=None, goal="CLEAR_INTEL", frames=(REAL_FRAME,)):
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = ledger if ledger is not None else {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._l1_context = None
    runtime._transitions = None
    runtime._ui_candidates = store
    runtime.brain = SimpleNamespace(current_goal=goal)
    runtime.capture_dir = Path("dataset/raw/control_panel/runtime_auto/run_stub")
    # ``read_frame_size`` and the cropping helpers read the file, so a stub run needs a real
    # picture on disk: the frame is used as-is, and the boxes above are its own scale.
    runtime._test_frames = list(frames)
    return runtime


def _temp_store(root: Path):
    manifest = root / "manifest.json"
    return ui_collection.UiCandidateStore(root=root / "candidates", manifest=manifest), manifest


class InteractivityTests(unittest.TestCase):
    """The judgement itself: what the frame draws, and what it refuses to call a control."""

    def test_a_control_shaped_box_becomes_a_candidate(self):
        ocr = _StubOCR(("先锋调查", 0.99, BUTTON_BOX))
        rows = ui_collection.interactive_controls(
            REAL_FRAME, ocr, skip_words=(), goal="CLEAR_INTEL"
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["word"], "先锋调查")
        self.assertEqual(row["basis"], "OCR_BOX")
        self.assertTrue(row["goal_relevant"], "情报/线索/调查 is what CLEAR_INTEL looks for")
        box = row["box_norm"]
        self.assertAlmostEqual(box["x_norm"], 300 / 720, places=3)
        self.assertAlmostEqual(box["h_norm"], 40 / 1280, places=3)

    def test_the_shapes_this_client_really_draws_are_not_controls(self):
        """Every case here is a word taken from this project's own live frames."""
        ocr = _StubOCR(
            ("原始时间：03:28:53", 0.99, BUTTON_BOX),   # a countdown line
            ("您的部队已经返回", 0.99, BUTTON_BOX),       # a system toast (8 characters)
            ("-12.7", 0.99, BUTTON_BOX),                # a value
            ("系统消息：", 0.99, BUTTON_BOX),             # a caption
            ("[oi]联盟旗帜", 0.99, BUTTON_BOX),           # OCR debris on an overlay
        )
        rows = ui_collection.interactive_controls(REAL_FRAME, ocr, skip_words=(), goal="ALLIANCE_ROUTINE")
        self.assertEqual(rows, [], f"none of these is a control: {rows}")

    def test_a_word_the_dictionary_declares_is_not_a_discovery(self):
        ocr = _StubOCR(("领取", 0.99, BUTTON_BOX))
        self.assertEqual(
            ui_collection.interactive_controls(REAL_FRAME, ocr, skip_words=(), goal="MAIL_ROUTINE")[0][
                "word"
            ],
            "领取",
        )
        self.assertEqual(
            ui_collection.interactive_controls(
                REAL_FRAME, ocr, skip_words=("领取",), goal="MAIL_ROUTINE"
            ),
            [],
        )

    def test_relevance_is_the_licence_and_the_goal_is_required(self):
        self.assertTrue(ui_collection.goal_relevant("先锋调查", "CLEAR_INTEL"))
        self.assertFalse(ui_collection.goal_relevant("先锋调查", "MAIL_ROUTINE"))
        self.assertFalse(ui_collection.goal_relevant("背包", "CLEAR_INTEL"))
        # An exit ends an interaction under any goal, which is why it needs no goal at all.
        self.assertTrue(ui_collection.goal_relevant("关闭", ""))
        # ...and with no goal, nothing else qualifies: "有 Goal 明确" is a precondition.
        self.assertFalse(ui_collection.goal_relevant("先锋调查", ""))

    def test_the_real_frame_is_filtered_the_same_way(self):
        """On a real capture, every row is inside the frame and none is a declared word."""
        from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

        cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
        dictionary = json.loads(
            (ROOT / "knowledge/ui/semantic_dictionary.json").read_text(encoding="utf-8")
        )
        declared = {
            str(word).strip()
            for record in dictionary["records"]
            for word in (record.get("ocr") or [])
            if str(word or "").strip()
        }
        rows = ui_collection.interactive_controls(
            REAL_FRAME, ocr, skip_words=declared, goal="KEEP_TRAINING_PRODUCTIVE"
        )
        self.assertFalse([row for row in rows if row["word"] in declared])
        for row in rows:
            box = row["box_norm"]
            self.assertGreaterEqual(box["x_norm"], 0.0)
            self.assertGreaterEqual(box["y_norm"], ui_collection.CONTROL_TOP_MARGIN_NORM)
            self.assertLessEqual(box["x_norm"] + box["w_norm"], 1.0)
            self.assertLessEqual(box["y_norm"] + box["h_norm"], 1.0)


class L1RegistryTests(unittest.TestCase):
    """The single-step action: what is stored, and what may be reused (§八/§十一)."""

    def _entry(self):
        entry = control_experience.ControlExperience(page="MAP", control="ORDINARY_CONTROL[先锋调查]")
        control_experience.record_outcome(
            entry, change="PAGE_CHANGED", clicked=True, frame="dataset/raw/real.png"
        )
        control_experience.register_l1(
            entry,
            goal="CLEAR_INTEL",
            state=control_experience.state_signature({"page": "MAP", "popup": ""}),
            features=control_experience.visual_features(
                text="先锋调查",
                box_norm={"x_norm": 0.4, "y_norm": 0.7, "w_norm": 0.17, "h_norm": 0.03},
                read_from_frame="dataset/raw/real.png",
            ),
            basis="OCR_BOX",
            action={"kind": "TAP_SEMANTIC", "target": "ORDINARY_CONTROL[先锋调查]"},
            expected_effect="ordinary_control_observed",
            observed_effect="PAGE_CHANGED",
        )
        return entry

    def test_registration_keeps_conditions_features_basis_action_and_effects(self):
        entry = self._entry()
        self.assertEqual(entry.level, control_experience.LEVEL_L1)
        self.assertEqual(entry.conditions[control_experience.CONDITION_PAGE], "MAP")
        self.assertEqual(entry.conditions[control_experience.CONDITION_GOAL], "CLEAR_INTEL")
        self.assertEqual(entry.conditions[control_experience.CONDITION_STATE], "MAP")
        self.assertEqual(entry.visual_features["text"], "先锋调查")
        self.assertEqual(entry.basis, "OCR_BOX")
        self.assertEqual(entry.action["target"], "ORDINARY_CONTROL[先锋调查]")
        self.assertEqual(entry.expected_effect, "ordinary_control_observed")
        self.assertEqual(entry.observed_effect, "PAGE_CHANGED")
        self.assertEqual(entry.goal_help["CLEAR_INTEL"], "PAGE_CHANGED")
        # §九: the record is not an absolute coordinate -- the normalized box travels with the
        # frame it was measured on, and no pixel position is stored as the action's identity.
        self.assertIn("read_from_frame", entry.visual_features)
        self.assertEqual(entry.visual_features["box_norm"]["h_norm"], 0.03)

    def test_it_survives_a_round_trip_through_the_store(self):
        entry = self._entry()
        payload = entry.as_json()
        restored = control_experience.ControlExperience.from_json(payload)
        self.assertEqual(restored.level, "L1")
        self.assertEqual(restored.conditions, entry.conditions)
        self.assertEqual(restored.visual_features, entry.visual_features)
        self.assertEqual(restored.basis, entry.basis)
        self.assertEqual(restored.action, entry.action)
        self.assertEqual(restored.expected_effect, entry.expected_effect)
        self.assertEqual(restored.observed_effect, entry.observed_effect)

    def test_reuse_needs_the_page_and_the_state_and_the_element_on_the_frame(self):
        entry = self._entry()
        ledger = {"MAP|ORDINARY_CONTROL[先锋调查]": entry}
        hit = control_experience.l1_for(
            ledger, page="MAP", goal="CLEAR_INTEL", state="MAP", present_words=["先锋调查"]
        )
        self.assertIs(hit, entry)
        cases = (
            dict(page="HOME", goal="CLEAR_INTEL", state="MAP", present_words=["先锋调查"]),
            dict(page="MAP", goal="MAIL_ROUTINE", state="MAP", present_words=["先锋调查"]),
            dict(page="MAP", goal="CLEAR_INTEL", state="MAP|POPUP", present_words=["先锋调查"]),
            # §十一: 当前画面不匹配时重新识别 -- the screen no longer draws the element.
            dict(page="MAP", goal="CLEAR_INTEL", state="MAP", present_words=["关闭"]),
        )
        for case in cases:
            self.assertIsNone(control_experience.l1_for(ledger, **case), case)

    def test_a_registration_without_a_recorded_element_is_never_reused(self):
        entry = self._entry()
        entry.visual_features = {"box_norm": {"x_norm": 0.4, "y_norm": 0.7, "w_norm": 0.1, "h_norm": 0.03}}
        self.assertFalse(control_experience.l1_reusable(entry))
        self.assertIsNone(
            control_experience.l1_for(
                {"k": entry}, page="MAP", goal="CLEAR_INTEL", state="MAP", present_words=["先锋调查"]
            )
        )

    def test_a_no_op_retires_the_registration_without_deleting_it(self):
        entry = self._entry()
        self.assertTrue(control_experience.l1_reusable(entry))
        control_experience.record_outcome(entry, change="NO_OP", clicked=True)
        self.assertFalse(control_experience.l1_reusable(entry))
        # The history is still there: it stopped applying, it was not disproved for ever.
        self.assertEqual(entry.level, "L1")
        self.assertEqual(entry.observed_effect, "PAGE_CHANGED")
        self.assertEqual(entry.attempts, 2)

    def test_the_state_signature_is_narrow_on_purpose(self):
        self.assertEqual(
            control_experience.state_signature(
                {"page": "TRAINING", "popup": "", "training": {"camp_open_label": "盾兵营"}}
            ),
            "TRAINING|training.camp_open_label=盾兵营",
        )
        # A countdown or a counter must not enter it, or "the same state" would never recur.
        self.assertEqual(
            control_experience.state_signature({"page": "MAP", "popup": "", "stamina": {"value": 42}}),
            "MAP",
        )


class ResolutionTests(unittest.TestCase):
    """The chain: whitelist first, then the interactive candidate, staged before the tap (§六)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="l1-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.store, self.manifest = _temp_store(self.root)
        self.ledger = {}
        # A frame with one unrecorded, control-shaped, goal-relevant box and nothing else.
        self.ocr = _StubOCR(("先锋调查", 0.99, BUTTON_BOX))

    def _resolve(self, runtime, frame=REAL_FRAME):
        return runtime._ordinary_control_candidate(WorldState(page=Page.MAP), frame)

    def test_an_undictionary_word_is_tapped_and_filed_before_the_tap(self):
        runtime = _runtime(ocr=self.ocr, ledger=self.ledger, store=self.store)
        point = self._resolve(runtime)
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 360 / 720, places=3)
        self.assertAlmostEqual(point[1], 920 / 1280, places=3)
        self.assertEqual(runtime._ordinary_last["source"], "INTERACTIVE_CANDIDATE")
        self.assertEqual(runtime._ordinary_last["basis"], "OCR_BOX")
        # §六: the CANDIDATE exists now, with everything a later reader needs.
        candidates = self.store.all()
        self.assertEqual(len(candidates), 1)
        record = candidates[0]
        self.assertEqual(record.page, "MAP")
        self.assertEqual(record.semantic_id, "ORDINARY_CONTROL[先锋调查]")
        self.assertEqual(record.verification_status, ui_collection.STATUS_CANDIDATE)
        self.assertEqual(record.goal, "CLEAR_INTEL")
        self.assertEqual(record.ocr_text, "先锋调查")
        self.assertEqual(record.source_frame, REAL_FRAME.as_posix())
        self.assertIn("basis=OCR_BOX", record.notes)
        self.assertIn("staged before the tap", record.notes)
        self.assertTrue(Path(record.image_path).exists(), "the crop is on disk, not just a path")
        self.assertTrue(Path(record.context_image_path).exists())

    def test_a_spend_word_anywhere_stops_the_interactive_tier(self):
        runtime = _runtime(
            ocr=_StubOCR(("先锋调查", 0.99, BUTTON_BOX), ("钻石", 0.99, BUTTON_BOX)),
            ledger=self.ledger,
            store=self.store,
        )
        self.assertIsNone(self._resolve(runtime))
        self.assertEqual(self.store.all(), [], "nothing may be tried, or filed, on a spend screen")

    def test_an_irrelevant_word_is_left_alone(self):
        runtime = _runtime(
            ocr=_StubOCR(("梦境寻忆", 0.99, BUTTON_BOX), ("背包", 0.99, BUTTON_BOX)),
            ledger=self.ledger,
            store=self.store,
        )
        self.assertIsNone(self._resolve(runtime))
        self.assertEqual(self.store.all(), [])

    def test_the_same_word_is_not_tapped_twice_in_one_run(self):
        runtime = _runtime(ocr=self.ocr, ledger=self.ledger, store=self.store)
        self.assertIsNotNone(self._resolve(runtime))
        self.assertIsNone(self._resolve(runtime))


class ProvenStepTests(unittest.TestCase):
    """§七/§八: only a step whose verifier passed registers an L1, and the next visit reuses it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="l1-step-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.store, self.manifest = _temp_store(self.root)
        self.ledger = {}
        self.ocr = _StubOCR(("先锋调查", 0.99, BUTTON_BOX))

    def _step(self, *, verification_ok, change="PAGE_CHANGED", executed=True):
        runtime = _runtime(ocr=self.ocr, ledger=self.ledger, store=self.store)
        runtime._resolve_for_test = runtime._ordinary_control_candidate(
            WorldState(page=Page.MAP), REAL_FRAME
        )
        runtime.brain = RuleBrain(current_goal="CLEAR_INTEL")
        runtime._fold_control_experience(
            decision=Decision("TRY_ORDINARY_CONTROL", "test", 0.99, "ordinary_control_observed"),
            before_state={"page": "MAP", "popup": ""},
            after_state={"page": "INTEL", "popup": ""} if change == "PAGE_CHANGED" else {"page": "MAP", "popup": ""},
            execution=ExecutionResult(
                executed=executed,
                dry_run=False,
                action=Action("TAP_SEMANTIC", "ORDINARY_CONTROL"),
                backend="ADB",
                tap_point=(360, 920),
            ),
            observed_change=change,
            goal_id="CLEAR_INTEL",
            frame=REAL_FRAME,
            verification_ok=verification_ok,
        )
        return runtime

    def test_one_proven_step_registers_the_action_under_its_own_element(self):
        self._step(verification_ok=True)
        key = control_experience.control_key("MAP", "ORDINARY_CONTROL[先锋调查]")
        self.assertIn(key, self.ledger, "the element has its own record, not the shared placeholder")
        entry = self.ledger[key]
        self.assertEqual(entry.level, control_experience.LEVEL_L1)
        self.assertEqual(entry.conditions[control_experience.CONDITION_GOAL], "CLEAR_INTEL")
        self.assertEqual(entry.conditions[control_experience.CONDITION_STATE], "MAP")
        self.assertEqual(entry.visual_features["text"], "先锋调查")
        self.assertEqual(entry.basis, "OCR_BOX")
        self.assertEqual(entry.action["kind"], "TAP_SEMANTIC")
        self.assertEqual(entry.observed_effect, "PAGE_CHANGED")

    def test_a_step_whose_verifier_failed_registers_nothing(self):
        self._step(verification_ok=False)
        for entry in self.ledger.values():
            self.assertEqual(entry.level, "", "a tap is not a proof")
        self.assertFalse(self.manifest.exists(), "and no template was written by any of this")

    def test_a_no_op_registers_nothing_even_with_the_verifier_passing(self):
        self._step(verification_ok=True, change="NO_OP")
        for entry in self.ledger.values():
            self.assertEqual(entry.level, "")

    def test_the_registration_writes_no_template_and_no_second_store(self):
        self._step(verification_ok=True)
        self.assertFalse(self.manifest.exists(), "the L1 shelf and the template shelf are separate")
        self.assertEqual(
            [record.verification_status for record in self.store.all()],
            [ui_collection.STATUS_CANDIDATE],
            "a single step does not promote the element past CANDIDATE",
        )

    def test_the_second_visit_reuses_it_instead_of_identifying_again(self):
        self._step(verification_ok=True)
        again = _runtime(ocr=self.ocr, ledger=self.ledger, store=self.store)
        point = again._ordinary_control_candidate(WorldState(page=Page.MAP), REAL_FRAME)
        self.assertIsNotNone(point)
        self.assertEqual(again._ordinary_last["source"], "L1_REUSE")
        self.assertEqual(again._ordinary_last["semantic"], "ORDINARY_CONTROL[先锋调查]")
        self.assertEqual(
            [line for line in again._printed_reads if line.startswith("MAP|")],
            [f"MAP|ORDINARY_CONTROL[先锋调查] <- the L1 action registered for "
             f"ORDINARY_CONTROL[先锋调查] @{point[0]:.4f},{point[1]:.4f}"],
        )

    def test_a_frame_that_no_longer_draws_it_is_identified_again(self):
        """§十一: 当前画面不匹配时重新识别 -- not "tap where it used to be"."""
        self._step(verification_ok=True)
        other = _runtime(
            ocr=_StubOCR(("梦境寻忆", 0.99, BUTTON_BOX)), ledger=self.ledger, store=self.store
        )
        self.assertIsNone(other._ordinary_control_candidate(WorldState(page=Page.MAP), REAL_FRAME))
        self.assertIsNone(other._ordinary_last, "nothing was resolved, and nothing was reused")
        self.assertIsNotNone(
            control_experience.l1_for(
                self.ledger, page="MAP", goal="CLEAR_INTEL", state="MAP", present_words=["先锋调查"]
            ),
            "the registration is still there for a frame that does draw it",
        )

    def test_a_different_goal_does_not_reuse_another_goals_registration(self):
        self._step(verification_ok=True)
        other = _runtime(ocr=self.ocr, ledger=self.ledger, store=self.store, goal="MAIL_ROUTINE")
        other._ordinary_control_candidate(WorldState(page=Page.MAP), REAL_FRAME)
        self.assertNotEqual((other._ordinary_last or {}).get("source"), "L1_REUSE")


    def test_two_unnamed_screens_are_not_the_same_state(self):
        """§十一: the state a registration holds under must tell two unnamed screens apart.

        Measured need: the live L1 written on 2026-09-22 was registered with state ``UNKNOWN`` --
        the same signature every screen the model cannot name would produce -- so a registration
        made on 战斗已结束 would have claimed to apply to 挂机收益.  The title the page reader already
        produced is what the page records and the transition ledger are keyed by, so it joins the
        signature.
        """
        runtime = _runtime(ocr=_StubOCR(("退出", 0.99, BUTTON_BOX)), goal="DAILY")
        unnamed = WorldState(page=Page.UNKNOWN)
        self.assertEqual(runtime._l1_state(unnamed, "战斗已结束"), "UNKNOWN#战斗已结束")
        self.assertNotEqual(runtime._l1_state(unnamed, "挂机收益"), "UNKNOWN#战斗已结束")
        # A named page has its own fields; no title is needed and none is added.
        self.assertEqual(runtime._l1_state(WorldState(page=Page.MAP), "whatever"), "MAP")


class BrainReachabilityTests(unittest.TestCase):
    """§3: "no registered skill can advance the goal" must include "the only option is to leave".

    Measured before this was added: every known page has at least one ready skill, so the generic
    attempt could only ever fire on an unnamed screen -- a new panel drawn over a page the model
    *can* name would never be tried at all.

    The fixture is ``Page.MARCH_QUEUE``: a known page with **no branch of its own**, so the only
    thing the registry can offer is the generic BACK.  It used to be ``Page.EVENT``, which served
    purely as "some page with nothing to do" -- but EVENT acquired a declared behaviour of its own
    on 2026-09-24 (a just-opened 活动面板 is observed before any flow leaves it, pinned in
    ``tests/test_event_panel_observation.py``), so it is no longer an anonymous page and can no
    longer stand for one.  The property under test is unchanged; only its fixture moved.
    """

    def test_a_page_with_only_a_way_out_prefers_one_ordinary_attempt(self):
        brain = RuleBrain(current_goal="CLEAR_INTEL")
        decision = brain.decide(WorldState(page=Page.MARCH_QUEUE), v2_registry())
        self.assertEqual(decision.skill, "TRY_ORDINARY_CONTROL")
        self.assertIn("only_BACK_left", decision.reason)

    def test_a_page_with_a_registered_route_is_untouched(self):
        brain = RuleBrain(current_goal="CLEAR_INTEL")
        self.assertEqual(brain.decide(WorldState(page=Page.HOME), v2_registry()).skill, "OPEN_MAP")

    def test_the_attempt_is_bounded_and_then_the_page_is_left(self):
        brain = RuleBrain(current_goal="CLEAR_INTEL")
        decisions = [
            brain.decide(WorldState(page=Page.MARCH_QUEUE), v2_registry()).skill for _ in range(3)
        ]
        self.assertEqual(decisions[:2], ["TRY_ORDINARY_CONTROL"] * 2)
        self.assertEqual(decisions[2], "BACK", "budget spent -> the page is left exactly as before")

    def test_a_frame_that_offers_nothing_stops_asking(self):
        brain = RuleBrain(current_goal="CLEAR_INTEL")
        brain.ordinary_scan_exhausted = True
        self.assertEqual(brain.decide(WorldState(page=Page.MARCH_QUEUE), v2_registry()).skill, "BACK")


class WhitelistTierTests(unittest.TestCase):
    """The tier that found 挂机收益's 领取 live is a single step like any other (§七)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="l1-printed-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.store, self.manifest = _temp_store(self.root)
        self.ledger = {}
        self.ocr = _StubOCR(("领取", 0.99, BUTTON_BOX))

    def _resolve(self, runtime):
        return runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), REAL_FRAME)

    def test_a_printed_word_is_filed_before_the_tap_and_registers_its_own_l1(self):
        runtime = _runtime(
            ocr=self.ocr, ledger=self.ledger, store=self.store, goal="AVOID_STAMINA_WASTE"
        )
        point = self._resolve(runtime)
        self.assertIsNotNone(point)
        self.assertEqual(runtime._ordinary_last["basis"], "PRINTED_WORD")
        candidates = self.store.all()
        self.assertEqual(len(candidates), 1, "the candidate exists before the tap, as §六 asks")
        self.assertEqual(candidates[0].semantic_id, "ORDINARY_CONTROL[领取]")
        self.assertIn("basis=PRINTED_WORD", candidates[0].notes)

        runtime._fold_control_experience(
            decision=Decision("TRY_ORDINARY_CONTROL", "test", 0.99, "ordinary_control_observed"),
            before_state={"page": "UNKNOWN", "popup": ""},
            after_state={"page": "POPUP", "popup": "GENERIC_REWARD"},
            execution=ExecutionResult(
                executed=True,
                dry_run=False,
                action=Action("TAP_SEMANTIC", "ORDINARY_CONTROL"),
                backend="ADB",
                tap_point=(360, 920),
            ),
            observed_change="PAGE_CHANGED",
            goal_id="AVOID_STAMINA_WASTE",
            frame=REAL_FRAME,
            verification_ok=True,
        )
        key = control_experience.control_key("UNKNOWN", "ORDINARY_CONTROL[领取]")
        entry = self.ledger[key]
        self.assertEqual(entry.level, control_experience.LEVEL_L1)
        self.assertEqual(entry.basis, "PRINTED_WORD")
        self.assertEqual(entry.conditions[control_experience.CONDITION_GOAL], "AVOID_STAMINA_WASTE")
        self.assertEqual(entry.visual_features["text"], "领取")
        self.assertEqual(entry.observed_effect, "PAGE_CHANGED")

        again = _runtime(
            ocr=self.ocr, ledger=self.ledger, store=self.store, goal="AVOID_STAMINA_WASTE"
        )
        self.assertIsNotNone(self._resolve(again))
        self.assertEqual(again._ordinary_last["source"], "L1_REUSE")


if __name__ == "__main__":
    unittest.main()
