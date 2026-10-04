"""LOOP_WATCH_V1's boundary: the main path's half of the loop detector, and what it may not be.

Three clauses are asserted here, and each is one that erodes quietly.

1. 「Loop Detector 只能阻止当前局部流程，不得停止整个 AUTO」 -- the strongest ending this seam
   can produce is ``yield_goal``, which asks the run's own ``_yield_to_next_goal`` to hand *one
   Goal* back.  Asserted as an absence in the source (no ``finish``, no ``sys.exit``, no
   ``AgentState``) *and* as a property of the projection (every rung resolves to an intent in a
   closed set that contains no ending).

2. 「不得新增：第二 Scheduler / 第二 Executor / 第二 WorldState / 第二本地模型」 -- held to
   ``loop_detector``'s own rule and checked the same three ways: what it imports, what it
   defines, and what it binds at module level.

3. **The projection must be total and loud.**  ``RECOVERY_LADDER`` may grow; the failure mode to
   forbid is a new rung that a ``.get(rung, ...)`` default silently degrades into "issue the
   same step once more".  So an unmapped rung is a test failure, and an unknown rung raises.

The regression that matters most is the last class: the seam exists because the main path's
``progress`` is the *Goal*-level fact, so a step that passed its verifier while the Goal stood
still must fire the detector -- and the engine's fallback (``progress_from_outcome``) must not.
That pair is measured here rather than argued.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import loop_watch  # noqa: E402
from winter_agent_v2.loop_detector import (  # noqa: E402
    RECOVERY_LADDER,
    RUNG_DEFER_GOAL,
    RUNG_FEATURE_REOPEN,
    progress_from_outcome,
)
from winter_agent_v2.loop_watch import (  # noqa: E402
    INTENT_GO_HOME,
    INTENT_SAME_STEP,
    INTENT_WIDEN,
    INTENT_YIELD_GOAL,
    LoopWatch,
    resolve,
    unmapped_rungs,
)

MODULE = "loop_watch"
#: Every remedy the projection may name.  A closed set on purpose: an ending added to it would
#: have to be added here too, where the ``cannot end a run`` test would then see it.
ALLOWED_INTENTS = (INTENT_SAME_STEP, INTENT_WIDEN, INTENT_GO_HOME, INTENT_YIELD_GOAL)
BANNED_IMPORTS = ("subprocess", "socket", "http", "urllib", "requests", "ctypes",
                  "torch", "numpy", "cv2", "onnxruntime", "openai", "adb")


def source_of(module: str) -> str:
    return (ROOT / "winter_agent_v2" / f"{module}.py").read_text(encoding="utf-8")


def imported_roots(text: str) -> set[str]:
    """Every top-level module name a real ``import`` statement names.

    Parsed rather than split line-by-line, and that is not pedantry.  A line-scanning version of
    this function is defeated by a *docstring line* that happens to begin with ``from `` -- this
    module's own ``resolve`` docstring contains one, and the scanner read it as an import of
    "the named rung to the first one this path can carry out".  ``loop_detector``'s boundary test
    uses the line-scanning form; it passes only because that module's prose does not start a line
    that way, which means its "standard library only" claim is one docstring edit away from being
    unverifiable.  Reading the AST removes the whole class of mistake.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def code_names(text: str) -> set[str]:
    """Every bare identifier the module's *code* mentions.  Docstrings are not code."""
    return {node.id for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Name)}


def used_attributes(text: str) -> set[str]:
    """Every ``obj.attr`` the module's code reads, as ``"obj.attr"``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            found.add(f"{node.value.id}.{node.attr}")
    return found


def called_names(text: str) -> set[str]:
    """Every function name the module's code calls, by its last component."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                found.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                found.add(node.func.attr)
    return found


def module_level(text: str) -> tuple[set[str], set[str]]:
    """Module-level ``class``/``def`` names, and names bound by a module-level assignment."""
    defined: set[str] = set()
    assigned: set[str] = set()
    for node in ast.parse(text).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
    return defined, assigned


def mutable_module_state(text: str) -> set[str]:
    """Module-level names bound to a *mutable* container -- the thing the discipline forbids."""
    mutable_calls = {"set", "list", "dict", "deque", "bytearray", "defaultdict", "Counter"}
    offenders: set[str] = set()
    for node in ast.parse(text).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            is_mutable = (
                isinstance(value, (ast.List, ast.Dict, ast.Set))
                or (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id in mutable_calls)
            )
            if is_mutable:
                offenders.update(t.id for t in targets
                                 if isinstance(t, ast.Name) and not t.id.startswith("__"))
    return offenders


class _RaisingPage:
    """A state whose page read blows up, so the seam's refusal path can be driven."""

    @property
    def page(self):
        raise RuntimeError("the frame was unreadable")


def _loop(watch: LoopWatch, *, times: int, goal: str = "HERO_RECRUIT_ADVANCED",
          progress=False, outcome: str = "SUCCESS", skill: str = "OPEN_QUICK_PANEL",
          target: str = "QUICK_PANEL_ROW_HERO_RECRUIT", after=None):
    """Feed ``times`` identical steps, returning the last verdict."""
    verdict = None
    for _ in range(times):
        verdict = watch.observe_step(
            role_id="A", goal_id=goal, skill_id=skill, semantic_target=target,
            after={"page": "HOME"} if after is None else after,
            outcome=outcome, progress=progress)
    return verdict


# ==========================================================================================
# 1. The projection is total, and it is loud when it is not
# ==========================================================================================

class TheProjectionCoversTheWholeLadderTests(unittest.TestCase):
    def test_every_rung_of_the_ladder_is_accounted_for(self):
        self.assertEqual(unmapped_rungs(), (),
                         "a ladder rung with neither a remedy nor a declaration of "
                         "unavailability would degrade into 'issue the same step once more'")

    def test_a_seventh_rung_would_be_reported_rather_than_quietly_skipped(self):
        """The check has teeth: drive it with a ladder that really does have a stray rung."""
        extended = tuple(RECOVERY_LADDER) + ("a_rung_nobody_projected",)
        with patch.object(loop_watch, "RECOVERY_LADDER", extended):
            self.assertEqual(unmapped_rungs(), ("a_rung_nobody_projected",))

    def test_a_rung_that_is_not_in_the_ladder_at_all_raises(self):
        with self.assertRaises(KeyError):
            resolve("a_rung_that_does_not_exist")

    def test_every_rung_resolves_to_one_of_the_declared_intents(self):
        for rung in RECOVERY_LADDER:
            with self.subTest(rung=rung):
                intent, _skipped = resolve(rung)
                self.assertIn(intent, ALLOWED_INTENTS)
                self.assertTrue(intent, "an empty intent is 'carry on', which is not a remedy")

    def test_the_projection_names_no_ending_of_its_own(self):
        """The clause「不得停止整个 AUTO」as a property of the table, not only of the source."""
        allowed = set(ALLOWED_INTENTS)
        self.assertNotIn("stop", allowed)
        self.assertNotIn("end_run", allowed)
        self.assertNotIn("finish", allowed)
        for _name, intent in loop_watch.RUNG_INTENTS:
            self.assertIn(intent, allowed)

    def test_the_only_unavailable_rung_is_the_one_that_needs_an_adapter(self):
        """``feature_reopen`` is the adapter's ``recover`` -- the main path has no adapter."""
        self.assertEqual(loop_watch.UNAVAILABLE_ON_MAIN_PATH, (RUNG_FEATURE_REOPEN,))
        for rung in loop_watch.UNAVAILABLE_ON_MAIN_PATH:
            self.assertFalse(loop_watch._intent_of(rung),
                             "a rung cannot be both unavailable and mapped")

    def test_an_unavailable_rung_is_stepped_over_and_says_so(self):
        intent, skipped = resolve(RUNG_FEATURE_REOPEN)
        self.assertEqual(intent, INTENT_GO_HOME)
        self.assertEqual(skipped, (RUNG_FEATURE_REOPEN,),
                         "the trace must say the ladder had one fewer step here")

    def test_only_the_skipped_rung_reports_skips(self):
        for rung in RECOVERY_LADDER:
            if rung == RUNG_FEATURE_REOPEN:
                continue
            with self.subTest(rung=rung):
                self.assertEqual(resolve(rung)[1], ())

    def test_the_last_rung_yields_a_goal_and_nothing_stronger(self):
        self.assertEqual(resolve(RUNG_DEFER_GOAL), (INTENT_YIELD_GOAL, ()))


# ==========================================================================================
# 2. It is not a second Scheduler / Executor / WorldState / model
# ==========================================================================================

class TheSeamIsNotASecondAnythingTests(unittest.TestCase):
    def test_it_imports_only_the_standard_library_and_the_detector(self):
        roots = imported_roots(source_of(MODULE))
        self.assertTrue(roots, "the parse must actually find imports")
        foreign = sorted(r for r in roots
                         if r not in sys.stdlib_module_names
                         and r not in ("__future__", "winter_agent_v2"))
        self.assertEqual(foreign, [], f"imports outside the standard library: {foreign}")
        self.assertIn("winter_agent_v2", roots,
                      "the seam is supposed to reuse the detector, not re-implement one")

    def test_it_cannot_reach_a_device_or_a_model(self):
        roots = imported_roots(source_of(MODULE))
        for banned in BANNED_IMPORTS:
            with self.subTest(banned=banned):
                self.assertNotIn(banned, roots)

    def test_importing_it_does_not_load_a_runtime_scheduler_or_device(self):
        """The strongest available guarantee, asserted in a fresh interpreter.

        ``loop_detector``'s own boundary test proves "it cannot reach a runtime" by proving it
        imports nothing outside the standard library.  A seam that *does* import a project module
        (it must -- it reuses the detector) needs the stronger statement: importing it must not
        pull the runtime, the Scheduler, the Executor or a device layer into the process.  That is
        checked by loading it in a subprocess and asking the interpreter what it actually loaded,
        because a module object bound behind a conditional would satisfy any source scan.
        """
        probe = (
            "import sys, json; import winter_agent_v2.loop_watch as m; "
            "print(json.dumps(sorted(n for n in sys.modules "
            "if n.startswith('winter_agent_v2'))))"
        )
        completed = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT),
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        loaded = set(ast.literal_eval(completed.stdout.strip()))
        forbidden = sorted(n for n in loaded
                           if n.split(".")[-1] in ("runtime", "scheduler", "executor",
                                                   "global_scheduler_state", "device", "ocr",
                                                   "brain", "session_engine", "session_host"))
        self.assertEqual(forbidden, [], f"importing the seam loaded {forbidden}")
        self.assertEqual(loaded, {"winter_agent_v2", "winter_agent_v2.loop_detector",
                                 "winter_agent_v2.loop_watch"},
                         "the seam must depend on the detector and on nothing else of ours")

    def test_it_defines_no_scheduler_executor_world_state_registry_or_model(self):
        """The directive's forbidden list, as a definition scan over *code*, not over prose."""
        forbidden = {"Scheduler", "Executor", "Registry", "SkillRegistry", "GoalLibrary",
                     "GoalEngine", "Brain", "WorldState", "StateStore", "Manager",
                     "Orchestrator", "Queue", "TaskQueue", "Model", "Planner"}
        defined, _assigned = module_level(source_of(MODULE))
        self.assertEqual(sorted(forbidden & defined), [], "the seam defines a forbidden layer")
        self.assertTrue(defined, "the parse must actually find definitions")

    def test_it_keeps_no_module_level_mutable_state(self):
        offenders = sorted(mutable_module_state(source_of(MODULE)))
        self.assertEqual(offenders, [], f"module-level mutable state: {offenders}")

    def test_it_restates_no_threshold_of_its_own(self):
        """A repeat count written here would be a second definition of what a loop is."""
        text = source_of(MODULE)
        for borrowed in ("AAA_REPEATS", "ABAB_ENTRIES", "NO_PROGRESS_REPEATS", "NAV_REPEATS",
                         "WINDOW"):
            with self.subTest(threshold=borrowed):
                self.assertNotIn(borrowed, text)


class TheSeamCannotEndARunTests(unittest.TestCase):
    def test_the_source_cannot_reach_a_run_ending(self):
        """Read off the *code*: a docstring that says "no ``sys.exit`` here" is not a ``sys.exit``.

        This is why the scan is AST-based.  ``loop_detector``'s boundary test asserts over raw
        source text, which works for that module only because its prose never happens to contain
        the banned spellings -- so its check would start failing, or worse start passing, on a
        documentation edit rather than on a code edit.
        """
        text = source_of(MODULE)
        attributes = used_attributes(text)
        names = code_names(text)
        calls = called_names(text)
        for banned in ("sys.exit", "os._exit", "signal.raise_signal"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, attributes)
        for banned in ("AgentState", "FATAL_STOPPED", "SystemExit", "exit"):
            with self.subTest(name=banned):
                self.assertNotIn(banned, names)
        for banned in ("finish", "exit", "_exit", "raise_signal", "DEGRADED"):
            with self.subTest(call=banned):
                self.assertNotIn(banned, calls)

    def test_the_scan_has_teeth(self):
        """Drive it with a source that really does reach an ending, so it is not vacuous."""
        bad = "import sys\n\ndef stop():\n    sys.exit(1)\n    return AgentState.DEGRADED\n"
        self.assertIn("sys.exit", used_attributes(bad))
        self.assertIn("AgentState", code_names(bad))
        self.assertIn("exit", called_names(bad))

    def test_the_runtime_feeds_it_and_consumes_it_once_each(self):
        """Structural, and it is the property that keeps 'a loop' defined in one place."""
        text = source_of("runtime")
        self.assertEqual(text.count("self._loop_watch.observe_step("), 1)
        self.assertEqual(text.count("self._loop_watch.take("), 1)

    def test_the_watch_is_built_per_run_and_not_at_module_level(self):
        text = source_of("runtime")
        self.assertIn("self._loop_watch = LoopWatch()", text)
        # ... and outside ``run``'s body it must not exist at all, or a run's ledger would
        # leak into the next one.
        self.assertEqual(text.count("LoopWatch()"), 1)


# ==========================================================================================
# 3. The regression the seam exists for: the Goal fact, not the step's outcome
# ==========================================================================================

class TheSeamFiresOnTheGoalFactAndNotOnTheOutcomeTests(unittest.TestCase):
    def test_a_verifier_passing_step_with_no_goal_progress_is_a_loop(self):
        """The measured shape: HERO_RECRUIT_ADVANCED, 171 steps, all SUCCESS, all False."""
        watch = LoopWatch()
        verdict = _loop(watch, times=3, progress=False, outcome="SUCCESS")
        self.assertTrue(verdict.detected,
                        "three identical verifier-passing steps with no Goal progress is "
                        "exactly the case the detector exists for")
        self.assertEqual(verdict.pattern, "AAA")
        self.assertEqual(watch.detector.counts["LOOP_DETECTED"], 1)

    def test_the_shipped_fallback_would_have_seen_nothing(self):
        """Why this seam hands over ``progress`` instead of letting the detector guess.

        ``progress_from_outcome("SUCCESS") is True``, so a block of identical *successful*
        steps fails ``no_progress_block`` -- the detector is fed honest work.  This is the
        engine's situation (no adapter assigns ``StepVerdict.progress``), and it is the reason
        Fix A is not a one-line change.
        """
        self.assertIs(progress_from_outcome("SUCCESS"), True)
        watch = LoopWatch()
        verdict = _loop(watch, times=6, progress=progress_from_outcome("SUCCESS"))
        self.assertFalse(verdict.detected)
        self.assertEqual(watch.detector.counts["LOOP_DETECTED"], 0)

    def test_an_unread_goal_is_never_a_loop(self):
        """``None`` is 'not observable', not 'no progress'.  Ten identical steps prove it."""
        watch = LoopWatch()
        verdict = _loop(watch, times=10, progress=None)
        self.assertFalse(verdict.detected)
        self.assertEqual(watch.detector.counts["LOOP_DETECTED"], 0)

    def test_progress_clears_the_ladder(self):
        watch = LoopWatch()
        _loop(watch, times=5, progress=False)
        top_before = watch.detector._top_rung()
        self.assertNotEqual(top_before, "")
        _loop(watch, times=1, progress=True)
        self.assertEqual(watch.detector._top_rung(), "",
                         "a Goal that moved must not start the next flow a rung up")

    def test_the_ladder_escalates_one_rung_per_repeat_and_saturates(self):
        """Bounded by design: 3 identical answers, then one rung per repeat, then the ending."""
        watch = LoopWatch()
        rungs = []
        for _ in range(8):
            verdict = watch.observe_step(
                role_id="A", goal_id="HERO_RECRUIT_ADVANCED", skill_id="S",
                semantic_target="T", after={"page": "HOME"}, outcome="SUCCESS", progress=False)
            rungs.append(verdict.rung)
        self.assertEqual(rungs[:3], ["", "", "semantic_retry"])
        self.assertEqual(rungs[-1], RUNG_DEFER_GOAL)
        self.assertLessEqual(len(rungs), 3 + len(RECOVERY_LADDER),
                             "a loop can never outlive 3 + the ladder, whatever the budget says")

    def test_the_rungs_that_only_look_again_collapse_onto_the_runs_own_next_step(self):
        """Rungs 1 and 2 have no distinct surface here, and the projection says so.

        The main path takes exactly one observation per step, deliberately, so "retry the same
        step" and "look at the current page again, cheaply" are both already what the next
        iteration does.  Collapsing them is the honest answer; inventing a second observation
        purely so the ladder can look like it has six effects would put a wasted look on the hot
        path.  The rung the ladder asked for is still recorded in ``Watch.rung``.
        """
        self.assertEqual(resolve("semantic_retry"), (INTENT_SAME_STEP, ()))
        self.assertEqual(resolve("local_reobserve"), (INTENT_SAME_STEP, ()))

    def test_the_widen_rung_is_reachable_so_its_attention_surface_has_a_caller(self):
        """``runtime._observe(widen=True)``'s own docstring names this rung as its caller."""
        watch = LoopWatch()
        intents = []
        for _ in range(5):
            watch.observe_step(role_id="A", goal_id="G", skill_id="S", semantic_target="T",
                               after={"page": "HOME"}, outcome="SUCCESS", progress=False)
            intents.append(watch.take(goal_id="G").intent)
        self.assertIn(INTENT_WIDEN, intents)
        self.assertEqual(intents[2], INTENT_SAME_STEP)
        self.assertEqual(intents[3], INTENT_SAME_STEP)
        self.assertEqual(intents[4], INTENT_WIDEN)


class TheWatchHandsOverOneClaimAtATimeTests(unittest.TestCase):
    def test_a_claim_is_handed_over_once(self):
        watch = LoopWatch()
        _loop(watch, times=3)
        self.assertEqual(watch.take(goal_id="HERO_RECRUIT_ADVANCED").intent, INTENT_SAME_STEP)
        self.assertEqual(watch.take(goal_id="HERO_RECRUIT_ADVANCED").intent, "",
                         "the same claim must not be carried out twice")

    def test_a_claim_for_another_goal_is_dropped_rather_than_carried_out(self):
        watch = LoopWatch()
        _loop(watch, times=3, goal="HERO_RECRUIT_ADVANCED")
        handed = watch.take(goal_id="AVOID_STAMINA_WASTE")
        self.assertEqual(handed.intent, "",
                         "the flow moved to another Goal; acting on the old claim would spend "
                         "a rung on a loop that already ended")
        self.assertEqual(watch.take(goal_id="HERO_RECRUIT_ADVANCED").intent, "",
                         "and it was dropped, not parked")

    def test_only_a_carried_out_intent_is_counted(self):
        watch = LoopWatch()
        _loop(watch, times=3)
        watch.take(goal_id="HERO_RECRUIT_ADVANCED")
        self.assertEqual(watch.summary()["LOOP_WATCH_ACTED"], {},
                         "taking a claim is not carrying it out")
        watch.note_acted(INTENT_SAME_STEP)
        self.assertEqual(watch.summary()["LOOP_WATCH_ACTED"], {INTENT_SAME_STEP: 1})

    def test_a_skipped_rung_is_recorded_on_the_run(self):
        watch = LoopWatch()
        # Walk far enough that the ladder reaches the unavailable rung.  Detections start at
        # the third repeat and escalate one rung each, and ``feature_reopen`` is the fourth.
        for _ in range(6):
            watch.observe_step(role_id="A", goal_id="G", skill_id="S", semantic_target="T",
                               after={"page": "HOME"}, outcome="SUCCESS", progress=False)
        self.assertIn(RUNG_FEATURE_REOPEN, watch.summary()["LOOP_WATCH_SKIPPED_RUNGS"])

    def test_a_rung_stepped_over_is_reported_with_the_remedy_that_replaced_it(self):
        """``feature_reopen`` has no surface here, so the run does the HOME remedy instead --
        and both halves of that decision are on the watch it handed over."""
        watch = LoopWatch()
        handed = None
        for _ in range(6):
            watch.observe_step(role_id="A", goal_id="G", skill_id="S", semantic_target="T",
                               after={"page": "HOME"}, outcome="SUCCESS", progress=False)
            handed = watch.take(goal_id="G")
        self.assertEqual(handed.rung, RUNG_FEATURE_REOPEN)
        self.assertEqual(handed.intent, INTENT_GO_HOME)
        self.assertEqual(handed.skipped, (RUNG_FEATURE_REOPEN,))


class ARefusedObservationIsCountedRatherThanSwallowedTests(unittest.TestCase):
    def test_an_unreadable_state_does_not_raise_and_is_recorded(self):
        watch = LoopWatch()
        verdict = watch.observe_step(role_id="A", goal_id="G", skill_id="S", semantic_target="T",
                                     after=_RaisingPage(), outcome="SUCCESS", progress=False)
        self.assertIsNone(verdict)
        self.assertEqual(watch.broken, 1)
        self.assertTrue(watch.warnings, "a detector that broke quietly is worse than none")
        self.assertEqual(watch.detector.counts["LOOP_DETECTED"], 0)

    def test_the_original_failure_sentence_is_kept_verbatim(self):
        watch = LoopWatch()
        watch.observe_step(role_id="A", goal_id="G", skill_id="S", semantic_target="T",
                           after=_RaisingPage(), outcome="SUCCESS", progress=False)
        self.assertIn("RuntimeError", watch.warnings[0])
        self.assertIn("the frame was unreadable", watch.warnings[0])

    def test_one_warning_per_distinct_failure_not_one_per_step(self):
        watch = LoopWatch()
        for _ in range(4):
            watch.observe_step(role_id="A", goal_id="G", skill_id="S", semantic_target="T",
                               after=_RaisingPage(), outcome="SUCCESS", progress=False)
        self.assertEqual(watch.broken, 4, "every refusal is counted")
        self.assertEqual(len(watch.warnings), 1, "but the sentence is printed once")


class TheSignatureMatchesTheLedgerSpellingTests(unittest.TestCase):
    def test_the_page_is_spelled_the_way_the_engine_and_the_ledger_spell_it(self):
        """``Page`` is a ``(str, Enum)``: ``str(Page.HOME)`` is ``"Page.HOME"``, value is "HOME"."""
        from winter_agent_v2.models import Page
        self.assertEqual(Page.HOME.value, "HOME")
        self.assertEqual(loop_watch._page_of({"page": "HOME"}), "HOME")
        state = types.SimpleNamespace(page=Page.HOME)
        self.assertEqual(loop_watch._page_of(state), "HOME")
        self.assertEqual(loop_watch._page_of(None), "")

    def test_a_state_with_no_page_reads_as_empty_rather_than_raising(self):
        self.assertEqual(loop_watch._page_of(types.SimpleNamespace()), "")


if __name__ == "__main__":
    unittest.main()
