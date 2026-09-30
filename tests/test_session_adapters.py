"""The four business adapters, and the routing that chooses between them.

Each adapter answers the four questions the directive gives the business layer -- observe the
domain, choose the local next step, verify it in domain terms, decide when the Goal's work is
done -- and each is measured here against a host that answers from a list, so the assertions
are about the domain rules rather than about the client.

What is deliberately *not* tested here: whether the fishing servo can steer a real line, or
whether the rally list is really on screen.  Those belong to the runtime's own components
(``VisualServoSession``, ``live_rally_join_point``) and are already covered where they live.
The adapters' job is the *sequencing and the counting*, and that is what these tests pin.

Three measured defects these tests exist for:

* ``BearSessionAdapter.observe`` fed the runtime's rally rows (Mappings) into
  ``rally.fastest_joinable_for``, which needs ``RallyRow`` objects.  Every live bear session
  would have failed at its first observation with ``SESSION_OBSERVE_FAILED``;
* the bear adapter never ended once it had joined something and the list then emptied: two
  joins followed by an empty list produced nine list refreshes and ended only on the step
  budget;
* ``TrainingBatchSessionAdapter`` reported ``TRAINING_BATCH_DONE`` with two barracks it had
  never read, because "nothing pending among the camps I could read" was treated as "nothing
  left to do" (§真值纪律 空 ≠ 没有).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, VerificationResult, WorldState  # noqa: E402
from winter_agent_v2.session_adapters import (  # noqa: E402
    FISHING_EXIT_WORD,
    FISHING_HOME_WORD,
    SESSION_ADAPTERS,
    SESSION_ROUTES,
    STAMINA_FLOOR,
    STAGE_CONTROLLING,
    STAGE_DONE,
    STAGE_ENTERING,
    STAGE_LEAVING,
    TRAINING_CAMP_ORDER,
    TRAINING_CAMP_TAP,
    BearSessionAdapter,
    FishingSessionAdapter,
    JoinableRally,
    SessionRoute,
    StaminaSpendSessionAdapter,
    TrainingBatchSessionAdapter,
    make_adapter,
    plan_for,
    route_for,
)
from winter_agent_v2.session_engine import (  # noqa: E402
    STEP_OBSERVE_ONLY,
    STEP_PRINTED_TAP,
    STEP_REALTIME,
    STEP_SKILL,
    RealtimeControl,
    SessionContext,
    SessionSpec,
    SessionStep,
    StepExecution,
    StepOutcome,
)


# ==========================================================================================
# A host that answers from a list
# ==========================================================================================

class AdapterHost:
    """The narrow slice of ``SessionHost`` an adapter actually uses, driven by two lists.

    ``worlds`` feeds ``observe`` (bear, stamina, training) and ``words`` feeds ``capture`` +
    ``ocr`` (fishing and printed taps).  The last element of ``worlds`` is sticky, because a
    session legitimately reads the same screen twice and an exhausted iterator would report a
    harness shortage as a product failure.
    """

    def __init__(self, *, worlds=(), words=(), verdict=(True, "VERIFIED"), ocr_raises=False):
        self.worlds = list(worlds)
        self.words = list(words)
        self.verdict = verdict
        self.ocr_raises = bool(ocr_raises)
        self.world_index = 0
        self.observations = 0
        self.captures = 0
        self.executed: list[SessionStep] = []
        self.clock = 0.0

    def note(self, event, **fields):
        pass

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.clock += max(0.0, float(seconds))

    def capture(self):
        self.captures += 1
        return f"frame-{self.captures}"

    def ocr(self, frame=None, *, region=None):
        if self.ocr_raises:
            raise RuntimeError("the OCR service is not available")
        return [{"text": word} for word in self.words]

    def observe(self, phase):
        if not self.worlds:
            return None
        world = self.worlds[min(self.world_index, len(self.worlds) - 1)]
        if self.world_index < len(self.worlds) - 1:
            self.world_index += 1
        self.observations += 1
        return world

    def verify_step(self, step, execution):
        ok, reason = self.verdict
        return VerificationResult(bool(ok), str(reason), {"from": "host"})

    def execute_step(self, step):
        self.executed.append(step)
        if step.kind == STEP_REALTIME:
            return StepExecution(executed=True, evidence=dict((step.params or {}).get("report") or {}))
        return StepExecution(executed=True, backend="ADB", before="B", after="A")


def context_for(goal_id: str, *, role_id: str = "R1", extras=None) -> SessionContext:
    spec = SessionSpec(goal_id=goal_id, adapter="x", role_id=role_id)
    return SessionContext(spec=spec, run_id="RUN1", started_at=0.0, extras=dict(extras or {}))


# ==========================================================================================
# Routing: by Goal, not by skill
# ==========================================================================================

class RoutingIsByGoalNotBySkillTests(unittest.TestCase):
    """``JOIN_RALLY`` serves the bear Goal and also polar-terror and fortress.

    A skill-only table would have put every rally in the bear adapter, which is why the route
    is keyed on the Goal.
    """

    def test_every_route_names_a_registered_adapter(self):
        self.assertEqual(len({route.goal_id for route in SESSION_ROUTES}), len(SESSION_ROUTES))
        for route in SESSION_ROUTES:
            with self.subTest(goal=route.goal_id):
                self.assertIn(route.adapter, SESSION_ADAPTERS)
                self.assertTrue(route.enabled)
                self.assertEqual(route.lifecycle, "CANDIDATE",
                                 "nothing may be called verified before an episode says so")

    def test_the_same_skill_routes_differently_for_different_goals(self):
        bear = route_for("PARTICIPATE_BEAR", "JOIN_RALLY")
        fishing = route_for("USE_NORMAL_FISHING_BAIT", "JOIN_RALLY")
        self.assertIsNotNone(bear)
        self.assertEqual(bear.adapter, "bear")
        self.assertIsNone(fishing, "the fishing Goal does not own JOIN_RALLY")

    def test_a_goal_with_a_partial_skill_set_keeps_the_atomic_path_for_the_rest(self):
        """A route that names skills only fires for those skills."""
        self.assertIsNotNone(route_for("PARTICIPATE_BEAR", "START_RALLY"))
        self.assertIsNotNone(route_for("PARTICIPATE_BEAR", "OPEN_BEAR_RALLY_LIST"))
        self.assertIsNone(route_for("PARTICIPATE_BEAR", "CLOSE_POPUP"))

    def test_a_goal_with_an_empty_skill_set_accepts_whatever_it_emits(self):
        """``PLAY_NORMAL_FISHING_LEVEL`` declares no skills, so it owns every step it emits."""
        route = route_for("PLAY_NORMAL_FISHING_LEVEL", "WHATEVER")
        self.assertIsNotNone(route)
        self.assertEqual(route.skills, frozenset())

    def test_an_unknown_goal_has_no_session(self):
        self.assertIsNone(route_for(""))
        self.assertIsNone(route_for("NOT_A_GOAL"))
        self.assertIsNone(route_for(None))

    def test_the_goal_is_matched_case_insensitively_but_the_skill_is_not(self):
        """Pinned as a decision rather than left as an accident.

        ``decision.skill`` comes from the brain and is always upper case, so a case-insensitive
        skill match would only ever paper over a caller that invented a skill name -- which is
        the opposite of what a route table is for.  The Goal is normalised because it arrives
        from a config-shaped source that has historically been written in either case.
        """
        self.assertIsNotNone(route_for("  participate_bear  ", "JOIN_RALLY"))
        self.assertIsNone(route_for("PARTICIPATE_BEAR", "join_rally"))

    def test_a_disabled_route_falls_back_to_the_atomic_path(self):
        route = SessionRoute(goal_id="X", adapter="bear", enabled=False,
                             disabled_reason="measured 2026-09-30: list reader unstable")
        self.assertFalse(route.accepts("START_RALLY"))

    def test_the_training_routes_narrow_to_one_barracks(self):
        for goal, camp in (("SHIELD_CAMP_TRAINING", "SHIELD_CAMP"),
                           ("LANCER_CAMP_TRAINING", "LANCER_CAMP"),
                           ("MARKSMAN_CAMP_TRAINING", "MARKSMAN_CAMP")):
            with self.subTest(goal=goal):
                route = next(r for r in SESSION_ROUTES if r.goal_id == goal)
                self.assertEqual(tuple(route.extras.get("camps") or ()), (camp,))
                self.assertIsNone(route_for(goal, 'SELECT_TRAINING_CAMP'))
                self.assertTrue(route.disabled_reason)

    def test_gather_routes_never_require_stamina_or_intercept_navigation(self):
        for goal in ("KEEP_MARCHES_PRODUCTIVE", "GATHER_RESOURCE", "LARGE_GATHER"):
            with self.subTest(goal=goal):
                route = route_for(goal, "DISPATCH_MARCH")
                self.assertEqual(route.adapter, "march_productivity")
                self.assertNotIn("stamina", route.resource_budget)
                self.assertIsNone(route_for(goal, "GATHER_RESOURCE"))

    def test_zero_stamina_gather_dispatch_still_requires_real_verifier(self):
        adapter = make_adapter("march_productivity")
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        host = AdapterHost(worlds=[WorldState(page=Page.MARCH, stamina={"value": 0},
                                             normal_idle_slots=1)], verdict=(False, "NOT_DISPATCHED"))
        domain = adapter.observe(context, host)
        self.assertFalse(adapter.is_complete(context, host, domain)[0])
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.skill_id, "DISPATCH_MARCH")
        adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertFalse(adapter.is_complete(context, host, domain)[0])
        host.verdict = (True, "OUTGOING_MARCH_VERIFIED")
        adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertTrue(adapter.is_complete(context, host, domain)[0])

    def test_full_queue_or_obsolete_formation_does_not_dispatch_or_complete_gather(self):
        adapter = make_adapter("march_productivity")
        context = context_for("GATHER_RESOURCE")
        for world in (WorldState(page=Page.MARCH, normal_idle_slots=0),
                      WorldState(page=Page.MAP, normal_idle_slots=2)):
            self.assertIsNone(adapter.choose_step(context, AdapterHost(), world))
            self.assertFalse(adapter.is_complete(context, AdapterHost(), world)[0])


class ThePlanKeepsTheGoalDeadlineSeparateTests(unittest.TestCase):
    def test_the_goal_deadline_is_not_folded_into_the_session_budget(self):
        """A Goal with twelve minutes left does not license a twelve-minute session."""
        route = route_for("PARTICIPATE_BEAR", "START_RALLY")
        plan = plan_for(route, goal_id="PARTICIPATE_BEAR", role_id="R1",
                        goal_evidence={"remaining_seconds": 720})
        self.assertEqual(plan.goal_deadline_s, 720.0)
        self.assertEqual(plan.spec.time_budget_s, route.time_budget_s)
        self.assertNotEqual(plan.spec.time_budget_s, 720.0)

    def test_an_absent_deadline_is_not_a_zero_one(self):
        """``None`` means the Goal carries no deadline, which is not "0 seconds left"."""
        route = route_for("USE_NORMAL_FISHING_BAIT", "USE_NORMAL_FISHING_BAIT")
        plan = plan_for(route, goal_id="USE_NORMAL_FISHING_BAIT")
        self.assertIsNone(plan.goal_deadline_s)

    def test_a_boolean_is_not_a_deadline(self):
        route = route_for("USE_NORMAL_FISHING_BAIT", "USE_NORMAL_FISHING_BAIT")
        plan = plan_for(route, goal_id="USE_NORMAL_FISHING_BAIT",
                        goal_evidence={"remaining_seconds": True})
        self.assertIsNone(plan.goal_deadline_s)


class EveryAdapterIsBuiltFreshTests(unittest.TestCase):
    def test_a_fresh_adapter_per_session(self):
        """A shared instance would spend one session's join count on the next session's budget."""
        first = make_adapter("bear", extras={"max_joins": 8})
        first.joins = 5
        second = make_adapter("bear", extras={"max_joins": 8})
        self.assertIsNot(first, second)
        self.assertEqual(second.joins, 0)

    def test_configure_applies_the_route(self):
        adapter = make_adapter("fishing", extras={"casts": 3})
        self.assertEqual(adapter.casts_target, 3)
        adapter = make_adapter("stamina", extras={"max_marches": 7},
                               resource_budget={"stamina": 40})
        self.assertEqual(adapter.max_marches, 7)
        self.assertEqual(adapter.floor, 40)

    def test_an_unknown_adapter_name_returns_nothing(self):
        """``None`` lets the caller keep the atomic path, which is the safe direction."""
        self.assertIsNone(make_adapter("no_such_adapter"))

    def test_a_bad_declaration_does_not_raise(self):
        adapter = make_adapter("bear", extras={"max_joins": "not a number"})
        self.assertEqual(adapter.max_joins, 8, "the default stands rather than the session dying")


# ==========================================================================================
# 1. Fishing: one cast, staged
# ==========================================================================================

HOME_WORDS = ["普通关卡", "冰钓积分:120", "5/10"]
RESULT_WORDS = ["本次收获", "下潜深度:42"]
SERVO_OK = {"frames": 120, "moves_sent": 88, "outcome": "COMPLETED", "control_hz": 20.0,
            "start_confirmed": True}


class FishingSessionAdapterTests(unittest.TestCase):
    def _adapter(self, **kwargs):
        return FishingSessionAdapter(**kwargs)

    def _execution(self, *, evidence=None, executed=True):
        return StepExecution(executed=executed, reason="REALTIME", backend="REALTIME",
                             evidence=dict(evidence or {}))

    def test_one_cast_is_enter_then_steer_then_leave(self):
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)

        domain = adapter.observe(context, host)
        self.assertTrue(domain.on_home)
        self.assertEqual((domain.bait, domain.bait_cap), (5, 10))
        self.assertEqual(domain.points, 120)
        self.assertEqual(adapter.bait_before, 5, "the frame before the cast is remembered")

        entry = adapter.choose_step(context, host, domain)
        self.assertEqual((entry.kind, entry.target), (STEP_PRINTED_TAP, FISHING_HOME_WORD))
        self.assertEqual(entry.tags.get("stage"), STAGE_ENTERING)
        entry_verdict = adapter.verify_step(context, host, entry, self._execution(evidence={}))
        self.assertEqual(entry_verdict.outcome, StepOutcome.PROGRESS)
        self.assertIs(adapter.stage, STAGE_CONTROLLING)

        control_step = adapter.choose_step(context, host, adapter.observe(context, host))
        self.assertEqual(control_step.kind, STEP_REALTIME)
        control = control_step.params["control"]
        self.assertIsInstance(control, RealtimeControl,
                              "the adapter owns the detector and the controller; the host drives")
        self.assertIn("点击任意位置继续", control.start_words,
                      "the start prompt is dismissed by the word the client printed")

        cast_verdict = adapter.verify_step(context, host, control_step,
                                           self._execution(evidence=SERVO_OK))
        self.assertEqual(cast_verdict.outcome, StepOutcome.PROGRESS)
        self.assertFalse(adapter.cast_verified)
        self.assertEqual(adapter.casts, 0)
        self.assertIs(adapter.stage, STAGE_LEAVING)

        host.words = RESULT_WORDS
        result = adapter.observe(context, host)
        self.assertTrue(result.result_page)
        self.assertFalse(result.on_home)
        self.assertEqual(adapter.depth_m, 42)

        leave = adapter.choose_step(context, host, result)
        self.assertEqual(leave.target, FISHING_EXIT_WORD)
        leave_verdict = adapter.verify_step(context, host, leave, self._execution(evidence={}))
        self.assertEqual(leave_verdict.outcome, StepOutcome.PROGRESS)
        self.assertIs(adapter.stage, STAGE_LEAVING)

        host.words = ["普通关卡", "冰钓积分:270", "4/10"]
        home_again = adapter.observe(context, host)
        verification = adapter.choose_step(context, host, home_again)
        checked = adapter.verify_step(context, host, verification, self._execution(executed=False))
        self.assertEqual(checked.outcome, StepOutcome.SUCCESS)
        self.assertEqual(checked.evidence["points_per_bait"], 150)
        done, reason = adapter.is_complete(context, host, home_again)
        self.assertTrue(done, "the cast is only complete once the client is back on the entry page")
        self.assertEqual(reason, "FISHING_CASTS_DONE")
        self.assertEqual(adapter.summarize()["bait"], "5->4")

    def test_a_servo_that_ran_but_never_moved_the_finger_is_not_a_cast(self):
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)
        adapter.stage = STAGE_CONTROLLING
        step = SessionStep(0, STEP_REALTIME, params={"report": {}})

        verdict = adapter.verify_step(context, host, step, self._execution(
            evidence={"frames": 40, "moves_sent": 0, "outcome": "TARGET_GONE_FOR_16_TICKS"}))
        self.assertEqual(verdict.outcome, StepOutcome.FAILED)
        self.assertEqual(verdict.reason, "TARGET_GONE_FOR_16_TICKS")
        self.assertFalse(adapter.cast_verified)
        self.assertEqual(adapter.casts, 0)

    def test_the_missing_execution_is_not_confused_with_a_short_cast(self):
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)
        step = SessionStep(0, STEP_REALTIME, params={"report": {}})
        verdict = adapter.verify_step(context, host, step,
                                      self._execution(evidence={}, executed=False))
        self.assertEqual(verdict.outcome, StepOutcome.FAILED)
        self.assertEqual(verdict.reason, "FISHING_CONTROL_SESSION_DID_NOT_RUN")

    def test_the_stage_is_left_behind_even_by_a_failed_cast(self):
        """A failure must not leave the adapter believing it is still steering."""
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)
        adapter.stage = STAGE_CONTROLLING
        step = SessionStep(0, STEP_REALTIME, params={"report": {}})
        adapter.verify_step(context, host, step, self._execution(evidence={"frames": 1}))
        self.assertIs(adapter.stage, STAGE_LEAVING)

    def test_a_failed_cast_is_recovered_through_the_entrance_not_by_re_tapping(self):
        """The one recovery that is genuinely a second chance: the level may not have drawn yet."""
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)
        adapter.stage = STAGE_CONTROLLING
        step = SessionStep(0, STEP_REALTIME, params={"report": {}})
        recovered = adapter.recover(context, host, step,
                                   type("V", (), {"reason": "no frames"})())
        self.assertTrue(recovered)
        self.assertIs(adapter.stage, STAGE_ENTERING)
        self.assertFalse(adapter.cast_verified)

    def test_a_cast_that_already_succeeded_is_not_recovered(self):
        adapter = self._adapter()
        adapter.casts = 1
        recovered = adapter.recover(context_for("USE_NORMAL_FISHING_BAIT"),
                                   AdapterHost(), SessionStep(0, STEP_REALTIME, params={}),
                                   type("V", (), {"reason": "x"})())
        self.assertIsNone(recovered)

    def test_no_bait_left_completes_the_goal_rather_than_failing_it(self):
        """The Goal is "use normal bait"; when there is none, its work is over and it says so."""
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=["普通关卡", "0/10"])
        domain = adapter.observe(context, host)
        done, reason = adapter.is_complete(context, host, domain)
        self.assertTrue(done)
        self.assertEqual(reason, "FISHING_NO_NORMAL_BAIT")
        self.assertIsNone(adapter.choose_step(context, host, domain),
                          "and it does not spend bait it does not have")

    def test_a_popup_is_dismissed_by_the_word_it_printed(self):
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=["普通关卡", "点击任意位置继续", "5/10"])
        domain = adapter.observe(context, host)
        self.assertEqual(domain.popup_word, "点击任意位置继续")
        step = adapter.choose_step(context, host, domain)
        self.assertEqual((step.kind, step.target), (STEP_PRINTED_TAP, "点击任意位置继续"))

    def test_waiting_for_the_level_draws_looks_again_instead_of_re_tapping(self):
        """Re-tapping 普通关卡 would restart the cutscene, so the wait is an OBSERVE_ONLY step."""
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)
        adapter.stage = STAGE_ENTERING
        step = adapter.choose_step(context, host, adapter.observe(context, host))
        self.assertEqual(step.kind, STEP_OBSERVE_ONLY)

    def test_the_tournament_entry_is_found_by_its_printed_name(self):
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=["钓鱼锦标赛"])
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.target, "钓鱼锦标赛")

    def test_an_unreadable_frame_is_not_a_crash(self):
        """Several predicates degrade to "unknown", and an unreadable frame is exactly that."""
        adapter = self._adapter()
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS, ocr_raises=True)
        domain = adapter.observe(context, host)
        self.assertIsNotNone(domain, "the observation survives a broken reader")
        self.assertEqual(domain.text, "")
        self.assertFalse(domain.on_home)

    def test_a_device_that_cannot_capture_yields_no_domain(self):
        adapter = self._adapter()
        host = AdapterHost()
        host.capture = lambda: None
        self.assertIsNone(adapter.observe(context_for("USE_NORMAL_FISHING_BAIT"), host),
                          "None from the adapter is the engine's retry signal")

    def test_the_route_can_ask_for_more_than_one_cast(self):
        adapter = make_adapter("fishing", extras={"casts": 2})
        context = context_for("USE_NORMAL_FISHING_BAIT")
        host = AdapterHost(words=HOME_WORDS)
        adapter.casts = 1
        adapter.cast_verified = True
        domain = adapter.observe(context, host)
        self.assertFalse(adapter.is_complete(context, host, domain)[0],
                         "one cast of two is not the Goal's work being done")
        adapter.casts = 2
        self.assertTrue(adapter.is_complete(context, host, domain)[0])


# ==========================================================================================
# 2. Bear: start once, then join while the list keeps offering
# ==========================================================================================

def bear_row(*, target="BEAR", state="JOINABLE", point=(0.80, 0.40), bbox=(0.70, 0.30, 0.90, 0.50),
             used=1, maximum=10, remaining=90):
    row = {"target_type": target, "state": state, "join_norm": point,
           "capacity_used": used, "capacity_max": maximum, "remaining_seconds": remaining}
    if bbox is not None:
        row["join_button_bbox"] = list(bbox)
    return row


def bear_world(rows, *, visible=True, section="RALLY_LIST", idle_slots=2):
    return WorldState(
        page=Page.ALLIANCE,
        alliance={"section": section, "rally_list_visible": visible},
        rally={"source": "LIVE_CLIENT_RALLY_LIST", "rows": list(rows)},
        normal_idle_slots=idle_slots,
        confidence=0.99,
    )


class BearSessionAdapterTests(unittest.TestCase):
    def _host(self, worlds, **kwargs):
        return AdapterHost(worlds=worlds, **kwargs)

    def test_production_join_entry_never_requires_start_rally(self):
        adapter = make_adapter('bear', extras={'entry_skill': 'JOIN_RALLY', 'target': 'BEAR'})
        context = context_for('PARTICIPATE_BEAR')
        host = self._host([bear_world([bear_row()])])
        step = adapter.choose_step(context, host, adapter.observe(context, host))
        self.assertEqual(step.skill_id, 'JOIN_RALLY')
        self.assertEqual(adapter.starts, 0)

    def test_start_rally_goes_first_and_only_once(self):
        adapter = BearSessionAdapter()
        context = context_for("PARTICIPATE_BEAR")
        host = self._host([bear_world([bear_row()])])
        domain = adapter.observe(context, host)

        first = adapter.choose_step(context, host, domain)
        self.assertEqual((first.kind, first.skill_id), (STEP_SKILL, "START_RALLY"))
        self.assertEqual(first.params.get("rally_target"), "BEAR")
        verdict = adapter.verify_step(context, host, first, StepExecution(executed=True))
        self.assertEqual(verdict.outcome, StepOutcome.SUCCESS)
        self.assertEqual(adapter.starts, 1)

        second = adapter.choose_step(context, host, domain)
        self.assertEqual(second.skill_id, "JOIN_RALLY",
                         "once the rally exists, joining is the work")

    def test_the_joinable_row_comes_from_the_world_reader_and_names_its_row(self):
        """The defect: the rows are Mappings, and ``fastest_joinable_for`` needs ``RallyRow``s.

        Feeding it the raw rows raised ``AttributeError: 'dict' object has no attribute
        'joinable_for'`` on every live bear session -- which the engine's observation guard
        would have reported as ``SESSION_OBSERVE_FAILED``, one step in, forever.
        """
        adapter = BearSessionAdapter(start_once=False)
        context = context_for("PARTICIPATE_BEAR")
        host = self._host([bear_world([bear_row()])])
        domain = adapter.observe(context, host)
        self.assertIsInstance(domain.joinable, JoinableRally)
        self.assertEqual(domain.joinable.point, (0.80, 0.40))
        self.assertEqual(domain.joinable.row_index, 0,
                         "§25: the row's own button, and which row it was")
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.tags.get("row_index"), 0)

    def test_the_fastest_remaining_row_wins(self):
        adapter = BearSessionAdapter(start_once=False)
        context = context_for("PARTICIPATE_BEAR")
        rows = [bear_row(remaining=300, point=(0.2, 0.2), bbox=(0.1, 0.1, 0.3, 0.3)),
                bear_row(remaining=30, point=(0.8, 0.8), bbox=(0.7, 0.7, 0.9, 0.9))]
        domain = adapter.observe(context, self._host([bear_world(rows)]))
        self.assertEqual(domain.joinable.point, (0.8, 0.8))
        self.assertEqual(domain.joinable.row_index, 1)

    def test_a_row_whose_own_button_cannot_be_identified_is_still_joinable(self):
        """``None`` is the honest answer and stays distinguishable from row 0."""
        adapter = BearSessionAdapter(start_once=False)
        domain = adapter.observe(context_for("PARTICIPATE_BEAR"),
                                 self._host([bear_world([bear_row(bbox=None)])]))
        self.assertIsNotNone(domain.joinable)
        self.assertIsNone(domain.joinable.row_index)

    def test_a_full_row_is_not_joinable(self):
        adapter = BearSessionAdapter(start_once=False)
        domain = adapter.observe(context_for("PARTICIPATE_BEAR"),
                                 self._host([bear_world([bear_row(state="FULL", used=10)])]))
        self.assertIsNone(domain.joinable)

    def test_a_target_the_goal_did_not_ask_for_is_not_joined(self):
        """The bear Goal must not join a polar-terror rally that happens to be on the list."""
        adapter = BearSessionAdapter(start_once=False)
        domain = adapter.observe(context_for("PARTICIPATE_BEAR"),
                                 self._host([bear_world([bear_row(target="POLAR_TERROR")])]))
        self.assertIsNone(domain.joinable)
        self.assertEqual(domain.target, "BEAR")

    def test_a_list_that_is_not_on_screen_is_not_read(self):
        adapter = BearSessionAdapter(start_once=False)
        domain = adapter.observe(context_for("PARTICIPATE_BEAR"),
                                 self._host([bear_world([bear_row()], visible=False)]))
        self.assertIsNone(domain.joinable)
        self.assertFalse(domain.list_visible)

    def test_a_reading_that_did_not_come_from_this_frame_is_not_used(self):
        """Only ``LIVE_CLIENT_RALLY_LIST`` is accepted: a remembered row is not a row."""
        world = bear_world([bear_row()])
        world.rally["source"] = "CACHE"
        domain = BearSessionAdapter(start_once=False).observe(
            context_for("PARTICIPATE_BEAR"), self._host([world]))
        self.assertIsNone(domain.joinable)

    def test_an_empty_list_ends_the_session_even_after_a_successful_join(self):
        """The defect: ``refreshes >= 3 and not rows and joins == 0`` never fired after a join.

        Measured in the adapter smoke: two joins then an empty list produced nine
        ``OPEN_BEAR_RALLY_LIST`` refreshes and ended only when the step budget ran out.  An
        empty list is equally final after a join.
        """
        adapter = BearSessionAdapter(start_once=False)
        context = context_for("PARTICIPATE_BEAR")
        host = self._host([bear_world([])])
        adapter.joins = 2
        domain = adapter.observe(context, host)

        self.assertFalse(adapter.is_complete(context, host, domain)[0],
                         "one empty reading is not yet a statement about the event")
        for _ in range(3):
            step = adapter.choose_step(context, host, domain)
            self.assertEqual(step.skill_id, "OPEN_BEAR_RALLY_LIST")
            adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(adapter.refreshes, 3)
        done, reason = adapter.is_complete(context, host, domain)
        self.assertTrue(done)
        self.assertEqual(reason, "BEAR_LIST_HAS_NO_ROWS")

    def test_the_join_budget_ends_the_session(self):
        adapter = BearSessionAdapter(start_once=False, max_joins=2)
        context = context_for("PARTICIPATE_BEAR")
        host = self._host([bear_world([bear_row()])])
        domain = adapter.observe(context, host)
        adapter.joins = 2
        self.assertEqual(adapter.is_complete(context, host, domain), (True, "BEAR_JOIN_BUDGET_REACHED"))

    def test_a_lost_race_is_re_read_and_anything_else_ends_the_session(self):
        """FULL / ROW_GONE / TARGET_CHANGED are the three measured races worth a second attempt."""
        adapter = BearSessionAdapter()
        context = context_for("PARTICIPATE_BEAR")
        host = self._host([bear_world([bear_row()])])
        step = SessionStep(0, STEP_SKILL, skill_id="JOIN_RALLY")
        for reason in ("RALLY_FULL", "ROW_GONE", "TARGET_CHANGED"):
            with self.subTest(reason=reason):
                self.assertTrue(adapter.recover(context, host, step,
                                                type("V", (), {"reason": reason})()))
        self.assertIsNone(adapter.recover(context, host, step,
                                         type("V", (), {"reason": "MARCH_SLOTS_EXHAUSTED"})()),
                          "everything else ends the session so another Goal gets the cycle")
        self.assertEqual(adapter.summary()["lost_races"], 3)

    def test_a_refused_join_counts_nothing(self):
        adapter = BearSessionAdapter(start_once=False)
        context = context_for("PARTICIPATE_BEAR")
        host = self._host([bear_world([bear_row()])], verdict=(False, "JOIN_RALLY_NOT_PROVEN"))
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        verdict = adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(verdict.outcome, StepOutcome.FAILED)
        self.assertEqual(adapter.joins, 0, "a join that did not happen is not counted")

    def test_an_unreadable_world_is_a_retry_not_an_empty_list(self):
        adapter = BearSessionAdapter()
        self.assertIsNone(adapter.observe(context_for("PARTICIPATE_BEAR"), self._host([])))

    def test_the_idle_march_count_reaches_the_domain(self):
        adapter = BearSessionAdapter()
        domain = adapter.observe(context_for("PARTICIPATE_BEAR"),
                                 self._host([bear_world([], idle_slots=3)]))
        self.assertEqual(domain.idle_marches, 3)


# ==========================================================================================
# 3. Stamina: one legal march after another
# ==========================================================================================

def stamina_world(value, *, idle_slots=2):
    return WorldState(stamina={"value": value}, normal_idle_slots=idle_slots, confidence=0.99)


class StaminaSpendSessionAdapterTests(unittest.TestCase):
    def _adapter(self, **kwargs):
        return StaminaSpendSessionAdapter(**kwargs)

    def test_a_march_is_verified_before_it_is_counted(self):
        adapter = self._adapter()
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        host = AdapterHost(worlds=[stamina_world(120)])
        domain = adapter.observe(context, host)
        self.assertEqual(domain.stamina, 120)
        self.assertEqual(adapter.stamina_before, 120)

        step = adapter.choose_step(context, host, domain)
        self.assertEqual((step.kind, step.skill_id), (STEP_SKILL, "DISPATCH_MARCH"))
        verdict = adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(verdict.outcome, StepOutcome.SUCCESS)
        self.assertEqual(adapter.marches, 1)

    def test_a_refused_march_is_not_counted(self):
        adapter = self._adapter()
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        host = AdapterHost(worlds=[stamina_world(120)], verdict=(False, "NO_IDLE_SLOT"))
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        verdict = adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(verdict.outcome, StepOutcome.FAILED)
        self.assertEqual(adapter.marches, 0)

    def test_the_floor_ends_the_goal_and_names_the_reading(self):
        """The operator's acceptance criterion, reported as the Goal's own ending."""
        adapter = self._adapter()
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        host = AdapterHost(worlds=[stamina_world(10)])
        domain = adapter.observe(context, host)
        done, reason = adapter.is_complete(context, host, domain)
        self.assertTrue(done)
        self.assertEqual(reason, f"STAMINA_BELOW_FLOOR:10<{int(STAMINA_FLOOR)}")

    def test_a_blocked_march_ends_the_goal(self):
        adapter = self._adapter()
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        host = AdapterHost(worlds=[stamina_world(120, idle_slots=0)])
        domain = adapter.observe(context, host)
        self.assertEqual(adapter.is_complete(context, host, domain),
                         (True, "STAMINA_MARCH_BLOCKED:NO_IDLE_SLOT"))
        self.assertIsNone(adapter.choose_step(context, host, domain),
                          "and no march is issued with nowhere to send it")

    def test_the_march_budget_ends_the_goal(self):
        adapter = self._adapter(max_marches=3)
        adapter.marches = 3
        self.assertEqual(adapter.is_complete(context_for("KEEP_MARCHES_PRODUCTIVE"),
                                             AdapterHost(), None),
                         (True, "STAMINA_MARCH_BUDGET_REACHED"))

    def test_an_unreadable_stamina_is_looked_at_rather_than_marched_on(self):
        """§真值纪律: an unread panel is unknown, and marching blind spends what cannot be seen."""
        adapter = self._adapter()
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        world = WorldState(stamina={}, confidence=0.99)
        host = AdapterHost(worlds=[world])
        domain = adapter.observe(context, host)
        self.assertIsNone(domain.stamina, "the reading stays unknown rather than becoming 0")
        self.assertIsNone(adapter.stamina_before)
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.kind, STEP_OBSERVE_ONLY)
        self.assertEqual(adapter.verify_step(context, host, step,
                                             StepExecution(executed=False)).outcome,
                         StepOutcome.STILL_PENDING)

    def test_a_stamina_that_is_shown_but_not_a_number_is_unknown(self):
        adapter = self._adapter()
        domain = adapter.observe(context_for("KEEP_MARCHES_PRODUCTIVE"),
                                 AdapterHost(worlds=[WorldState(stamina={"value": "很多"})]))
        self.assertIsNone(domain.stamina)

    def test_the_stamina_reading_moves_with_the_client(self):
        adapter = self._adapter()
        context = context_for("KEEP_MARCHES_PRODUCTIVE")
        host = AdapterHost(worlds=[stamina_world(120), stamina_world(90)])
        adapter.observe(context, host)
        adapter.observe(context, host)
        self.assertEqual((adapter.stamina_before, adapter.stamina_after), (120, 90))
        self.assertEqual(adapter.summarize()["stamina"], "120->90")

    def test_an_unreadable_world_is_a_retry(self):
        self.assertIsNone(self._adapter().observe(context_for("KEEP_MARCHES_PRODUCTIVE"),
                                                  AdapterHost()))

    def test_the_floor_the_route_declares_wins_over_the_default(self):
        adapter = make_adapter("stamina", extras={}, resource_budget={"stamina": 45})
        self.assertEqual(adapter.floor, 45)


# ==========================================================================================
# 4. Training: this role's three barracks in one go
# ==========================================================================================

def camp_world(states, *, panel_only=False):
    camps = {camp: ({"state": value} if isinstance(value, str) else dict(value))
             for camp, value in states.items()}
    if panel_only:
        return WorldState(quick_panel={"camps": camps}, confidence=0.99)
    return WorldState(camps=camps, confidence=0.99)


class TrainingBatchSessionAdapterTests(unittest.TestCase):
    def _adapter(self, **kwargs):
        return TrainingBatchSessionAdapter(**kwargs)

    def test_the_barracks_are_worked_in_a_stable_order(self):
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({camp: "已完成" for camp in TRAINING_CAMP_ORDER})])
        domain = adapter.observe(context, host)
        self.assertEqual(adapter.camps, TRAINING_CAMP_ORDER)

        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.skill_id, TRAINING_CAMP_TAP["SHIELD_CAMP"])
        self.assertEqual(step.tags.get("camp"), "SHIELD_CAMP")
        adapter.verify_step(context, host, step, StepExecution(executed=True))

        next_step = adapter.choose_step(context, host, domain)
        self.assertEqual(next_step.tags.get("camp"), "LANCER_CAMP")

    def test_an_already_training_barracks_is_left_alone(self):
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({"SHIELD_CAMP": "训练中", "LANCER_CAMP": "已完成",
                                               "MARKSMAN_CAMP": "训练中"})])
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.tags.get("camp"), "LANCER_CAMP",
                         "the only barracks with work left")
        self.assertIn("SHIELD_CAMP", adapter.skipped)

    def test_a_batch_where_everything_is_busy_is_done(self):
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({camp: "训练中" for camp in TRAINING_CAMP_ORDER})])
        domain = adapter.observe(context, host)
        self.assertEqual(adapter.is_complete(context, host, domain),
                         (True, "TRAINING_BATCH_DONE"))
        self.assertIsNone(adapter.choose_step(context, host, domain))

    def test_the_batch_is_done_once_every_declared_barracks_was_tapped(self):
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({camp: "已完成" for camp in TRAINING_CAMP_ORDER})])
        domain = adapter.observe(context, host)
        for _ in range(3):
            step = adapter.choose_step(context, host, domain)
            adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(adapter.tapped, list(TRAINING_CAMP_ORDER))
        self.assertEqual(adapter.is_complete(context, host, domain),
                         (True, "TRAINING_BATCH_DONE"))

    def test_a_barracks_nobody_could_read_is_never_counted_as_finished(self):
        """The defect: two never-tapped barracks silently counted as handled.

        The first version returned ``()`` ("nothing left to do") as soon as *any* camp was
        readable and none of the readable ones needed a tap -- so a frame where the only
        readable barracks happened to be busy reported the whole batch as done, with
        ``TAPPED=[] SKIPPED=[LANCER_CAMP] REASON=TRAINING_BATCH_DONE``.  An unreadable barracks
        is unknown, not finished.
        """
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        # Only the lancer camp can be read; the other two are absent from the panel.
        host = AdapterHost(worlds=[camp_world({"LANCER_CAMP": "训练中"})])
        domain = adapter.observe(context, host)

        done, _reason = adapter.is_complete(context, host, domain)
        self.assertFalse(done, "an unreadable barracks is not evidence there is nothing to do")
        self.assertIsNone(adapter.choose_step(context, host, domain),
                          "and nothing is tapped on a frame that cannot answer")

        done, _reason = adapter.is_complete(context, host, domain)
        self.assertFalse(done, "the second look is not yet the bound")
        done, reason = adapter.is_complete(context, host, domain)
        self.assertTrue(done, "the session ends rather than waiting out the whole time budget")
        self.assertEqual(reason, "TRAINING_CAMPS_UNREADABLE:MARKSMAN_CAMP+SHIELD_CAMP",
                         "and the reason names what could not be read")
        self.assertEqual(adapter.tapped, [], "nothing was tapped and the ending says so")

    def test_a_reading_that_returns_is_counted_again(self):
        """The unreadable streak resets: a transient bad frame must not end the batch."""
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({camp: "训练中" for camp in TRAINING_CAMP_ORDER})])
        adapter.unreadable_rounds = 2
        adapter.is_complete(context, host, adapter.observe(context, host))
        self.assertEqual(adapter.unreadable_rounds, 0,
                         "a frame that answers every barracks resets the streak")

    def test_the_quick_panel_answers_all_three_in_one_frame(self):
        """The whole reason this session is worth having: one panel read, three barracks."""
        adapter = self._adapter()
        host = AdapterHost(worlds=[camp_world({camp: "已完成" for camp in TRAINING_CAMP_ORDER},
                                              panel_only=True)])
        domain = adapter.observe(context_for("KEEP_TRAINING_PRODUCTIVE"), host)
        self.assertEqual(len(domain.camps), 3)

    def test_a_barracks_is_read_in_any_of_the_shapes_the_project_uses(self):
        """``_camp_state`` accepts the five shapes the project's readers actually emit.

        ``skipped`` is filled by ``_pending``, so the assertion has to come after a
        ``choose_step`` -- measured: an earlier version of this test observed and asserted
        immediately, and passed an empty ``skipped`` for the same reason it would have passed
        for a barracks the adapter had never looked at.
        """
        for record in ({"state": "训练中"}, {"status": "TRAINING"}, {"training": "训练中"},
                       {"busy": True}, "训练中"):
            with self.subTest(record=record):
                adapter = self._adapter()
                context = context_for("KEEP_TRAINING_PRODUCTIVE")
                host = AdapterHost(worlds=[camp_world({"SHIELD_CAMP": record,
                                                       "LANCER_CAMP": "已完成",
                                                       "MARKSMAN_CAMP": "已完成"})])
                domain = adapter.observe(context, host)
                step = adapter.choose_step(context, host, domain)
                self.assertIn("SHIELD_CAMP", adapter.skipped,
                              "a barracks already working is skipped, not tapped")
                self.assertEqual(step.tags.get("camp"), "LANCER_CAMP",
                                 "and the work moves on to the next barracks")

    def test_a_boolean_busy_flag_is_understood(self):
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({"SHIELD_CAMP": {"busy": False},
                                               "LANCER_CAMP": {"busy": True},
                                               "MARKSMAN_CAMP": {"busy": True}})])
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.tags.get("camp"), "SHIELD_CAMP")

    def test_a_refused_tap_is_not_counted(self):
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({camp: "已完成" for camp in TRAINING_CAMP_ORDER})],
                           verdict=(False, "CAMP_TAP_NOT_PROVEN"))
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        verdict = adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(verdict.outcome, StepOutcome.FAILED)
        self.assertEqual(adapter.tapped, [])
        self.assertEqual(verdict.evidence.get("camp"), "SHIELD_CAMP",
                         "the evidence still names which barracks was attempted")

    def test_the_camp_budget_bounds_the_batch(self):
        adapter = self._adapter(max_camps=1)
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({camp: "已完成" for camp in TRAINING_CAMP_ORDER})])
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertIsNone(adapter.choose_step(context, host, domain),
                          "one camp is this batch's whole budget")

    def test_a_single_camp_route_only_works_that_camp(self):
        adapter = make_adapter("training_batch", extras={"camps": ("LANCER_CAMP",)})
        context = context_for("LANCER_CAMP_TRAINING")
        host = AdapterHost(worlds=[camp_world({camp: "已完成" for camp in TRAINING_CAMP_ORDER})])
        domain = adapter.observe(context, host)
        self.assertEqual(adapter.camps, ("LANCER_CAMP",))
        step = adapter.choose_step(context, host, domain)
        self.assertEqual(step.tags.get("camp"), "LANCER_CAMP")
        adapter.verify_step(context, host, step, StepExecution(executed=True))
        self.assertEqual(adapter.is_complete(context, host, domain),
                         (True, "TRAINING_BATCH_DONE"))

    def test_one_readable_barracks_is_enough_to_act_on(self):
        """A readable frame is acted on; the missing ones only stop the batch being *called* done."""
        adapter = self._adapter()
        context = context_for("KEEP_TRAINING_PRODUCTIVE")
        host = AdapterHost(worlds=[camp_world({"SHIELD_CAMP": "已完成"})])
        domain = adapter.observe(context, host)
        step = adapter.choose_step(context, host, domain)
        self.assertIsNotNone(step, "there is real work on this frame")
        self.assertEqual(step.tags.get("camp"), "SHIELD_CAMP")

    def test_an_unreadable_world_is_a_retry(self):
        self.assertIsNone(self._adapter().observe(context_for("KEEP_TRAINING_PRODUCTIVE"),
                                                  AdapterHost()))


if __name__ == "__main__":
    unittest.main()
