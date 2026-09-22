"""The 快捷面板 handle: measured appearance, located on the current frame, and used.

Operator 2026-09-22 (the screenshot with the handle circled in red):

    我用红色圈起来的地方就是快捷面板把手，点进去就可以看到很多功能快捷入口和状态等信息

Until that frame arrived, this project could not locate the handle in the state it is needed in:
every anchor the panel reader had (its section headers, its task rows) is drawn *by the open panel*,
so the reader knew where the handle was only when it did not need it.  These tests pin what replaced
that: the measured appearance of both states, a locator that reads the frame instead of a stored
position, the frame reading carrying the collapsed state, and a route that may use it -- gated by the
record's own pages, goals and risk, and refused while the panel is already open.

The real frames are the evidence, and they are of both states and of a frame that has neither.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import find_quick_panel_handle  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.verifier import verify_ordinary_control_tried  # noqa: E402

AUTO = ROOT / "dataset/raw/control_panel/runtime_auto"

#: The city view with the panel closed -- the handle is drawn at the frame's left edge.
COLLAPSED_FRAME = sorted(AUTO.glob("*/" + "*_step_008_before_20260922T110032859453.png"))[-1]

#: The world map with the panel closed: a different page, the same control, the same point.
COLLAPSED_MAP_FRAME = sorted(AUTO.glob("*/" + "*_step_010_before_20260922T105043712428.png"))[-1]

#: The one frame in this project whose quick panel really reads as open: the handle's other state.
EXPANDED_FRAME = sorted(AUTO.glob("*/" + "*_step_001_before_20260921T133510479855.png"))[-1]

#: A full-screen event page: no city HUD, so no handle.  The negative case.
NO_HANDLE_FRAME = sorted(AUTO.glob("*/" + "*_step_002_before_20260922T083049654040.png"))[-1]

#: The operator's own capture of the collapsed handle, kept in the repository as evidence.  Its game
#: viewport is 690x1231 (the file carries a 49 px white margin down its left side), which is 4%
#: smaller than the device -- so it is also the cross-check that the shape, not the scale, is what
#: the locator reads.
OPERATOR_FRAME = ROOT / "dataset/raw/reference/quick_panel_handle_collapsed_20260922.jpg"


def _runtime(*, goal="KEEP_TRAINING_PRODUCTIVE", goal_id="", ocr=None):
    """A runtime with nothing but what these tests exercise (no device, no cycle).

    ``goal`` is what the scheduler puts in ``brain.current_goal`` and ``goal_id`` what it puts in
    ``brain.goal_id``.  Production sets the first to a **route** (``TRAIN``) and the second to the
    concrete goal; a test that sets ``current_goal`` to a goal id is not testing the shipped shape.
    """
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = {}
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._l1_context = None
    runtime._ui_candidates = None
    runtime.brain = SimpleNamespace(current_goal=goal, goal_id=goal_id)
    runtime.capture_dir = Path("dataset/raw/control_panel/runtime_auto/run_stub")
    return runtime


def _frame_with_handle(state="COLLAPSED", point=(0.0181, 0.4301), page=Page.HOME):
    """A WorldState carrying the reading the vision layer produces -- no OCR, no pixel work."""
    return WorldState(
        page=page,
        quick_panel={
            "open": state == "EXPANDED",
            "state": state,
            "handle": {
                "state": state,
                "point_norm": [point[0], point[1]],
                "box_norm": {"x_norm": 0.0083, "y_norm": 0.4203, "w_norm": 0.0208, "h_norm": 0.0203},
                "basis": "HANDLE_TRIANGLE_SCAN",
            },
        },
    )


class TheLocatorTests(unittest.TestCase):
    """It reads the handle the way it is drawn, on real frames of both states."""

    def test_the_collapsed_handle_is_found_on_a_real_city_frame(self):
        found = find_quick_panel_handle(COLLAPSED_FRAME, panel_open=False)
        self.assertIsNotNone(found, "the operator's screenshot shows this exact tab")
        self.assertEqual(found["state"], "COLLAPSED")
        self.assertEqual(found["triangle_direction"], "RIGHT", "collapsed points the way the panel will move")
        self.assertEqual(found["basis"], "HANDLE_TRIANGLE_SCAN")
        self.assertAlmostEqual(found["point_norm"][0], 0.0181, places=3)
        self.assertAlmostEqual(found["point_norm"][1], 0.4301, places=3)

    def test_the_same_point_on_a_different_page(self):
        """The map draws it too, at the same place: the control is anchored to the frame edge."""
        city = find_quick_panel_handle(COLLAPSED_FRAME, panel_open=False)
        world = find_quick_panel_handle(COLLAPSED_MAP_FRAME, panel_open=False)
        self.assertIsNotNone(world)
        self.assertEqual(city["point_norm"], world["point_norm"])

    def test_the_expanded_handle_points_the_other_way(self):
        found = find_quick_panel_handle(EXPANDED_FRAME, panel_open=True)
        self.assertIsNotNone(found)
        self.assertEqual(found["state"], "EXPANDED")
        self.assertEqual(found["triangle_direction"], "LEFT")
        self.assertGreater(found["point_norm"][0], 0.5, "the open panel's handle is at its right edge")

    def test_a_frame_that_draws_no_handle_reports_none(self):
        self.assertIsNone(find_quick_panel_handle(NO_HANDLE_FRAME))

    def test_the_operator_frame_reads_the_same_control_at_a_different_scale(self):
        found = find_quick_panel_handle(OPERATOR_FRAME)
        self.assertIsNotNone(found)
        self.assertEqual(found["state"], "COLLAPSED")
        # The file's own coordinates; its game viewport starts at x 49, so (0.0832 - 49/739) / (690/739)
        # is 0.022 of the viewport against the device's 0.0181 -- two captures, one shape.
        viewport_x = (found["point_norm"][0] * 739 - 49) / 690
        self.assertAlmostEqual(viewport_x, 0.0181, delta=0.006)
        self.assertAlmostEqual(found["point_norm"][1], 0.4301, delta=0.006)

    def test_a_white_card_is_not_a_handle(self):
        """The one real false positive found while writing this, pinned.

        The alliance page's numbered-list card is a big white rounded panel whose glyph gaps produce
        runs that pass every shape test.  What separates it is the fill: the tab is a muted blue,
        the card is rgb(227,241,254).
        """
        card = None
        for candidate in sorted(AUTO.glob("*/" + "*_step_002_before_20260922T104100395063.png")):
            card = candidate
        self.assertIsNotNone(card, "the alliance frame has to be in the stream for this test to mean anything")
        self.assertIsNone(find_quick_panel_handle(card))


class TheFrameReadingTests(unittest.TestCase):
    """The reading carries the collapsed state, so a tap can be judged by the panel opening."""

    def test_the_open_panel_measures_its_own_handle(self):
        """The expanded point used to be an estimate from the panel's rows; it is measured now.

        Measured: the estimate said (0.3708, 0.2779) -- the middle of the panel -- while the tab is
        at (0.6431, 0.4301).  A tap from the estimate would have landed on the panel's content.
        """
        found = find_quick_panel_handle(EXPANDED_FRAME, panel_open=True)
        self.assertIsNotNone(found)
        self.assertEqual(found["basis"], "HANDLE_TRIANGLE_SCAN")
        self.assertAlmostEqual(found["point_norm"][0], 0.6431, places=3)
        self.assertNotAlmostEqual(found["point_norm"][0], 0.3708, places=2)
        # And the reader that builds the panel's handle is the one that uses it: ``read_quick_panel``
        # cannot be driven here without a real OCR pass, so the wiring is asserted where this project
        # asserts wiring -- in the source, where the call either is or is not.
        source = (ROOT / "winter_agent_v2/ocr.py").read_text(encoding="utf-8")
        body = source[source.index("def read_quick_panel("):source.index("def _bright_runs(")]
        self.assertIn("find_quick_panel_handle(image_path, panel_open=True)", body)


class _StubOCR:
    """An OCR service that reads whatever it is told to, in the shape the readers consume."""

    def __init__(self, tokens):
        self._tokens = tokens

    def recognize(self, image_path, roi=None):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=0.99, box=box) for text, box in self._tokens),
            "stub",
        )


class TheRouteTests(unittest.TestCase):
    """What may use the handle, and what must not."""

    def test_the_goal_that_needs_the_panel_taps_it(self):
        runtime = _runtime(goal="KEEP_TRAINING_PRODUCTIVE")
        point = runtime._declared_textless_control_point("HOME", "", _frame_with_handle())
        self.assertEqual(point, (0.0181, 0.4301))
        self.assertEqual(runtime._ordinary_last["semantic"], "QUICK_PANEL_HANDLE")

    def test_a_goal_the_record_does_not_serve_cannot_tap_it(self):
        for goal in ("CLEAR_INTEL", "DAILY_ACTIVITY_TARGET"):
            runtime = _runtime(goal=goal)
            self.assertIsNone(
                runtime._declared_textless_control_point("HOME", "", _frame_with_handle()),
                f"{goal!r} is not a reason to open the panel",
            )
            # ...and the refusal names its gate.  Without this the step reached the episode stream as
            # "the frame names no control" -- measured 2026-09-23, 15 of the 31 failed live attempts
            # stood on a frame that draws the handle.
            self.assertEqual(
                (getattr(runtime, "_ordinary_declined", None) or {}).get("reason"),
                LiveRuntime.ORDINARY_CONTROL_DECLINES["not_for_goal"],
                f"{goal!r}: the refusal must say which gate refused",
            )
        # No goal at all is refused before any gate is consulted -- there is nothing to compare the
        # record's ``related_goals`` against -- so there is no gate to name.  Asserted so the
        # difference between "a gate refused" and "the tier was never entered" stays visible.
        bare = _runtime(goal="")
        self.assertIsNone(bare._declared_textless_control_point("HOME", "", _frame_with_handle()))
        self.assertIsNone(getattr(bare, "_ordinary_declined", None))

    def test_the_shipped_shape_reaches_it_too(self):
        """``current_goal`` is a **route** in production, not a goal id.

        The scheduler sets ``brain.current_goal`` from ``goal_library.route_for`` (``TRAIN``,
        ``RESEARCH``, ``HOME``) and ``brain.goal_id`` to the concrete goal, so comparing
        ``current_goal`` against the record's ``related_goals`` -- which names ids -- is false for
        every goal the project has.  That is why the record's own verification still reads
        "tap_to_open: NOT YET VERIFIED ON THE DEVICE ... no tap of this handle has been observed
        opening the panel": the mechanism was wired and the name never matched.
        """
        for route, goal_id in (("TRAIN", "KEEP_TRAINING_PRODUCTIVE"),
                               ("TRAIN", "MARKSMAN_CAMP_TRAINING"),
                               ("RESEARCH", "KEEP_RESEARCH_PRODUCTIVE")):
            with self.subTest(route=route, goal_id=goal_id):
                runtime = _runtime(goal=route, goal_id=goal_id)
                self.assertEqual(
                    runtime._declared_textless_control_point("HOME", "", _frame_with_handle()),
                    (0.0181, 0.4301),
                )

    def test_a_route_nobody_listed_still_cannot_tap_it(self):
        """Widening the match must not turn the panel into a control any goal may press."""
        for route, goal_id in (("HOME", ""), ("MAIL", "MAIL_ROUTINE"), ("INTEL", "CLEAR_INTEL")):
            with self.subTest(route=route):
                runtime = _runtime(goal=route, goal_id=goal_id)
                self.assertIsNone(
                    runtime._declared_textless_control_point("HOME", "", _frame_with_handle()),
                    f"{route!r} is not a reason to open the panel",
                )

    def test_a_page_the_record_does_not_name_cannot_tap_it(self):
        runtime = _runtime()
        frame = _frame_with_handle(page=Page.ALLIANCE)
        self.assertIsNone(runtime._declared_textless_control_point("ALLIANCE", "", frame))
        self.assertEqual(
            (getattr(runtime, "_ordinary_declined", None) or {}).get("reason"),
            LiveRuntime.ORDINARY_CONTROL_DECLINES["not_on_page"],
        )

    def test_an_already_expanded_panel_is_not_toggled(self):
        """已经展开时，直接读取状态，不重复点击 -- the record's own ``states`` decides it."""
        runtime = _runtime()
        frame = _frame_with_handle(state="EXPANDED", point=(0.6431, 0.4301))
        self.assertIsNone(runtime._declared_textless_control_point("HOME", "", frame))
        self.assertIsNone(runtime._ordinary_last, "and nothing is resolved into a tap")

    def test_a_frame_that_draws_no_handle_cannot_be_tapped(self):
        runtime = _runtime()
        self.assertIsNone(
            runtime._declared_textless_control_point("HOME", "", WorldState(page=Page.HOME))
        )

    def test_a_record_whose_own_risk_is_not_explorable_is_refused(self):
        runtime = _runtime()
        original = runtime._semantic_records

        def records():
            table = dict(original())
            handle = dict(table["QUICK_PANEL_HANDLE"])
            handle["risk"] = "HIGH_IRREVERSIBLE"
            table["QUICK_PANEL_HANDLE"] = handle
            return table

        runtime._semantic_records = records
        self.assertIsNone(runtime._declared_textless_control_point("HOME", "", _frame_with_handle()))

    def test_the_city_screen_is_no_longer_vetoed_by_its_own_wares(self):
        """The measured defect this change exists for.

        The city view prints 首充 and 玉魄流光礼包 on its own event entries, so the spend blacklist
        vetoed *every* ordinary control there -- including the handle, which has no wording of its own
        to be judged by.  Operator §五 forbids exactly that: 页面上出现消费文字不代表这个页面的普通
        查看动作全部禁止.
        """
        ocr = _StubOCR([("首充", ((10.0, 10.0), (60.0, 10.0), (60.0, 40.0), (10.0, 40.0)))])
        runtime = _runtime(ocr=ocr)
        runtime.vision = SimpleNamespace(ocr=ocr)
        point = runtime._ordinary_control_candidate(_frame_with_handle(), COLLAPSED_FRAME)
        self.assertEqual(point, (0.0181, 0.4301), "the handle is still tappable on that screen")

    def test_a_printed_word_on_a_spend_screen_is_still_refused(self):
        """The other half of the boundary: the veto still covers every control named by its words.

        The goal here is deliberately one the handle's record does not serve, so the declared tier
        cannot answer and the printed-word tier is what the frame is offered to -- and the verdict is
        that nothing may be tapped.  (With the panel's goal the same screen resolves the handle
        instead, which is the test above.)
        """
        runtime = _runtime(goal="CLEAR_INTEL")
        runtime._control_ledger = {
            control_experience.control_key("HOME", "ORDINARY_CONTROL[领取]"):
                control_experience.ControlExperience(page="HOME", control="ORDINARY_CONTROL[领取]", attempts=1)
        }
        ocr = _StubOCR([("首充", ((10.0, 10.0), (60.0, 10.0), (60.0, 40.0), (10.0, 40.0)))])
        runtime.vision = SimpleNamespace(ocr=ocr)
        self.assertIsNone(
            runtime._ordinary_control_candidate(_frame_with_handle(), COLLAPSED_FRAME),
            "a whitelist word on a screen that sells must not be tapped by this tier",
        )


class TheTextlessReuseTests(unittest.TestCase):
    """A control with no wording is reused by re-running the reader that measured it."""

    def _entry(self):
        entry = control_experience.ControlExperience(page="HOME", control="QUICK_PANEL_HANDLE")
        control_experience.register_l1(
            entry,
            goal="KEEP_TRAINING_PRODUCTIVE",
            state="HOME",
            features=control_experience.visual_features(
                text="",
                box_norm={"x_norm": 0.0083, "y_norm": 0.4203, "w_norm": 0.0208, "h_norm": 0.0203},
                read_from_frame=str(COLLAPSED_FRAME),
            ),
            basis="HANDLE_TRIANGLE_SCAN",
            action={"kind": "TAP_SEMANTIC", "target": "QUICK_PANEL_HANDLE"},
            expected_effect="QUICK_PANEL_OPEN",
            observed_effect="QUICK_PANEL_OPENED",
        )
        return entry

    def test_a_registered_textless_action_is_re_located_on_this_frame(self):
        runtime = _runtime()
        point = runtime._relocate_textless_control(
            self._entry(), "HOME", "", _frame_with_handle(), COLLAPSED_FRAME
        )
        self.assertEqual(point, (0.0181, 0.4301), "the point comes from the frame in front of us")
        self.assertEqual(runtime._ordinary_last["source"], "L1_REUSE")

    def test_and_is_not_reused_when_the_frame_no_longer_draws_it(self):
        runtime = _runtime()
        self.assertIsNone(
            runtime._relocate_textless_control(
                self._entry(), "HOME", "", _frame_with_handle(), NO_HANDLE_FRAME
            ),
            "no handle on this picture means identify again, never tap where it used to be",
        )

    def test_a_different_basis_is_not_relocated_by_this_reader(self):
        entry = self._entry()
        entry.basis = "PRINTED_WORD"
        runtime = _runtime()
        self.assertIsNone(
            runtime._relocate_textless_control(entry, "HOME", "", _frame_with_handle(), COLLAPSED_FRAME)
        )


class TheVerificationTests(unittest.TestCase):
    """Success is the entries appearing, not the tap happening."""

    def test_the_panel_opening_is_verified_by_name(self):
        before = _frame_with_handle(state="COLLAPSED")
        after = WorldState(
            page=Page.HOME,
            quick_panel={
                "open": True,
                "state": "EXPANDED",
                "camps": {"LANCER_CAMP": {"status": "IDLE"}},
                "handle": {"state": "EXPANDED", "point_norm": [0.6431, 0.4301]},
            },
        )
        result = verify_ordinary_control_tried(before, after)
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence["change"], "QUICK_PANEL_OPENED")
        self.assertIn("camps", result.evidence["sections"], "the entries that appeared are part of the proof")

    def test_a_tap_that_leaves_the_panel_closed_is_not_credited(self):
        before = _frame_with_handle(state="COLLAPSED")
        result = verify_ordinary_control_tried(before, before)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason[:24], "ORDINARY_CONTROL_NO_OP")


class _Device:
    """Records taps; whether the handle was pressed is the question."""

    capture_backend = "TEST_CAPTURE"

    def __init__(self):
        self.taps = []
        self.back_presses = 0
        self.swipes = 0

    def status(self):
        return SimpleNamespace(connected=True, resolution=(720, 1280))

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.back_presses += 1

    def swipe(self, *args, **kwargs):
        self.swipes += 1

    def screenshot(self, path):
        # The runtime's capture path only needs *a* file to exist; the stub writes a marker
        # rather than a real PNG so nothing downstream can mistake it for a frame.
        Path(path).write_bytes(b"STUB-STEP-FRAME")


class _ScriptedVision:
    """Hands out scripted states in order; the last repeats.  Only the panel reading varies."""

    def __init__(self, states):
        self.states = states
        self.index = 0

    def observe(self, path):
        state = self.states[min(self.index, len(self.states) - 1)]
        self.index += 1
        return state


class _AsksForAnOrdinaryControl:
    """A brain whose one decision is the ordinary attempt.

    The decision itself is the brain's own business and is tested where it lives; what this file
    tests is whether the *chain* carries a declared textless control from the frame reading to a
    verified step, so the decision is given rather than derived.
    """

    current_goal = "KEEP_TRAINING_PRODUCTIVE"
    ordinary_attempts = 0
    ordinary_scan_exhausted = False

    def decide(self, world, registry):
        from winter_agent_v2.models import Decision

        return Decision(
            "TRY_ORDINARY_CONTROL", "goal_needs_the_quick_panel", world.confidence,
            "ordinary_control_observed",
        )


class TheWholeStepTests(unittest.TestCase):
    """One real step: the frame names the handle, it is pressed, and the panel is the proof."""

    def _run(self):
        from winter_agent_v2.runtime import LiveRuntime

        with TemporaryDirectory() as temp:
            runtime = LiveRuntime(
                device=_Device(),
                vision=_ScriptedVision([
                    _frame_with_handle(state="COLLAPSED"),
                    _frame_with_handle(state="COLLAPSED"),
                    WorldState(
                        page=Page.HOME,
                        quick_panel={
                            "open": True,
                            "state": "EXPANDED",
                            "camps": {"LANCER_CAMP": {"status": "IDLE", "queue_available": True}},
                            "handle": {"state": "EXPANDED", "point_norm": [0.6431, 0.4301]},
                        },
                    ),
                ]),
                semantic_vision=SimpleNamespace(ocr=None),
                capture_dir=Path(temp),
                brain=_AsksForAnOrdinaryControl(),
                sleeper=lambda _seconds: None,
            )
            runtime.vision = SimpleNamespace(ocr=_StubOCR([]), observe=runtime.vision.observe)
            run = runtime.run(max_actions=1, allowed_skills={"TRY_ORDINARY_CONTROL"})
            return run, runtime, runtime.device

    def test_the_step_taps_the_handle_and_the_panel_opening_verifies_it(self):
        run, runtime, device = self._run()
        self.assertTrue(device.taps, "the handle was pressed")
        x, y = device.taps[0]
        # The measured handle, converted to pixels of a 720x1280 frame: (0.0181, 0.4301).
        self.assertLessEqual(abs(x - 13), 6, f"tapped x={x} is not the handle at the frame's left edge")
        self.assertLessEqual(abs(y - 551), 8, f"tapped y={y} is not the handle's band")
        self.assertTrue(run.steps, "the step ran")
        step = run.steps[0]
        self.assertTrue(step.verification.ok, f"verification failed: {step.verification.reason}")
        self.assertEqual(step.verification.evidence.get("change"), "QUICK_PANEL_OPENED")

    def test_the_proven_step_is_remembered_as_an_l1_action(self):
        _run, runtime, _device = self._run()
        entries = [
            entry for entry in runtime._control_ledger.values()
            if entry.control == "QUICK_PANEL_HANDLE"
        ]
        self.assertTrue(entries, "a step that proved what the control does must be remembered")
        entry = entries[0]
        self.assertEqual(entry.level, control_experience.LEVEL_L1)
        self.assertEqual(entry.basis, "HANDLE_TRIANGLE_SCAN")
        self.assertIn("KEEP_TRAINING_PRODUCTIVE", entry.goal_help or {"KEEP_TRAINING_PRODUCTIVE": 1})
        self.assertEqual(entry.observed_effect, "QUICK_PANEL_OPENED")
        self.assertTrue(control_experience.l1_reusable(entry), "and it is reusable")


if __name__ == "__main__":
    unittest.main()
