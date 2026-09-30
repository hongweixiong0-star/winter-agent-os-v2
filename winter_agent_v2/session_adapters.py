"""The first four business adapters for GENERIC_SESSION_ENGINE_V1.

Each adapter answers the four questions the directive gives the business layer, and no
others (业务Adapter负责): **observe domain state / choose local next step / domain verifier
/ completion predicate**.  None of them can rank Goals, switch roles, or reach the
Scheduler — ``SessionHost`` does not expose those, so the boundary is a fact about the
types rather than a promise in a comment.

The four, and the measured reason each exists (all four were costing one AUTO round per
micro-step, plus a HOME round trip between them):

1. ``FishingSessionAdapter`` — one cast is a *sequence*: enter the level, steer it closed
   loop for tens of seconds, read the result, leave.  It reuses the existing pieces
   unchanged: ``FishingSessionController`` (the two policies), ``VisualServoSession`` (the
   closed inner loop), ``ContinuousTouchSession`` (the guaranteed finger release) and
   ``fishing_vision.detect_fishing`` (per-frame numbers, no OCR, no world state).
2. ``BearSessionAdapter`` — ``START_RALLY`` once, then ``JOIN_RALLY`` repeatedly while the
   list keeps offering rows, re-reading the list between joins.  The rally list mutates in
   seconds, so the adapter re-reads it every step and refuses to join a row it read too
   long ago (``rally.stale_frame_reason``).
3. ``StaminaSpendSessionAdapter`` — spend stamina legally, march after march, until the
   floor is reached or marching is blocked.
4. ``TrainingBatchSessionAdapter`` — work the current role's three barracks in one go
   instead of one barracks per arbitration.

Routing is by **Goal**, not by skill (``SESSION_ROUTES``).  That matters: ``JOIN_RALLY``
serves the bear Goal and also polar-terror and fortress, and only the bear Goal should get
a bear session.  A skill-only table would have put every rally in the bear adapter.

What is deliberately NOT here
-----------------------------
No queue, no ranking, no world state, no role switch, no coordinate.  Every step names
either a registered skill, or a control the *current frame* identifies — never a stored
point (宪法 A §24.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .fishing_session import FishingSessionController
from .fishing_vision import detect_fishing
from .rally import (
    RallyTarget,
    live_rally_join_point,
    rally_target_for_goal,
)
from .session_engine import (
    STEP_OBSERVE_ONLY,
    STEP_PRINTED_TAP,
    STEP_REALTIME,
    STEP_SKILL,
    RealtimeControl,
    SessionAdapter,
    SessionContext,
    SessionHost,
    SessionSpec,
    SessionStep,
    StepExecution,
    StepOutcome,
    StepVerdict,
)


# ==============================================================================
# Routing: Goal -> adapter.  Not a scheduler — a lookup table with no ranking in it.
# ==============================================================================

@dataclass(frozen=True)
class SessionRoute:
    """The declared link from one Goal to one adapter, plus that Goal's budgets.

    ``enabled`` exists so a route can be turned off for a measured reason without being
    deleted; a route that is off must say so, so ``disabled_reason`` is required with it.
    """

    goal_id: str
    adapter: str
    skills: frozenset[str] = frozenset()
    step_budget: int = 8
    time_budget_s: float = 180.0
    resource_budget: Mapping[str, float] = field(default_factory=dict)
    extras: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    disabled_reason: str = ""
    #: The lifecycle status of this route, in the project's own vocabulary.  All four start
    #: at CANDIDATE: unit-tested, not yet live-verified.  Nothing may be called
    #: LIVE_VERIFIED until a production episode says so (§1 of the master rules).
    lifecycle: str = "CANDIDATE"

    def accepts(self, skill_id: str) -> bool:
        if not self.enabled:
            return False
        if not self.skills:
            return True
        return str(skill_id or "") in self.skills


BEAR_SKILLS = frozenset({"START_RALLY", "JOIN_RALLY", "OPEN_BEAR_RALLY_LIST"})
STAMINA_SKILLS = frozenset({"DISPATCH_MARCH", "SEND_MARCH", "GATHER_RESOURCE"})
TRAINING_SKILLS = frozenset({"TRAIN_TROOPS", "SELECT_TRAINING_CAMP",
                             "TAP_FOCUSED_TRAINING_CAMP_SHIELD",
                             "TAP_FOCUSED_TRAINING_CAMP_LANCER",
                             "TAP_FOCUSED_TRAINING_CAMP_MARKSMAN"})

#: The stamina floor the operator's acceptance criterion names ("stamina<30 → 返回
#: Scheduler").  Declared once, read by both the spec and the adapter's own predicate.
STAMINA_FLOOR = 30.0

SESSION_ROUTES: tuple[SessionRoute, ...] = (
    SessionRoute(
        goal_id="USE_NORMAL_FISHING_BAIT", adapter="fishing",
        skills=frozenset({"USE_NORMAL_FISHING_BAIT", "PLAY_NORMAL_FISHING_LEVEL"}),
        # Three steps is one cast once the goal route has opened the tournament home:
        # enter the level, steer it, leave the result page.  Six leaves room for a popup.
        step_budget=6, time_budget_s=150.0,
        extras={"casts": 1},
    ),
    SessionRoute(
        goal_id="PLAY_NORMAL_FISHING_LEVEL", adapter="fishing",
        step_budget=6, time_budget_s=150.0, extras={"casts": 1},
    ),
    SessionRoute(
        goal_id="PARTICIPATE_BEAR", adapter="bear", skills=BEAR_SKILLS,
        # A bear rally window is minutes of joining; twelve steps is roughly the number of
        # rallies one role can join before its march slots are spent.
        step_budget=12, time_budget_s=240.0, extras={"target": "BEAR", "max_joins": 8},
    ),
    SessionRoute(
        goal_id="BEAR_HUNT", adapter="bear", skills=BEAR_SKILLS,
        step_budget=12, time_budget_s=240.0, extras={"target": "BEAR", "max_joins": 8},
    ),
    SessionRoute(
        goal_id="KEEP_MARCHES_PRODUCTIVE", adapter="stamina", skills=STAMINA_SKILLS,
        step_budget=6, time_budget_s=240.0,
        resource_budget={"stamina": STAMINA_FLOOR}, extras={"max_marches": 4},
    ),
    SessionRoute(
        goal_id="GATHER_RESOURCE", adapter="stamina", skills=STAMINA_SKILLS,
        step_budget=4, time_budget_s=180.0,
        resource_budget={"stamina": STAMINA_FLOOR}, extras={"max_marches": 2},
    ),
    SessionRoute(
        goal_id="LARGE_GATHER", adapter="stamina", skills=STAMINA_SKILLS,
        step_budget=4, time_budget_s=180.0,
        resource_budget={"stamina": STAMINA_FLOOR}, extras={"max_marches": 2},
    ),
    SessionRoute(
        goal_id="KEEP_TRAINING_PRODUCTIVE", adapter="training_batch", skills=TRAINING_SKILLS,
        step_budget=6, time_budget_s=180.0,
    ),
    SessionRoute(
        goal_id="SHIELD_CAMP_TRAINING", adapter="training_batch", skills=TRAINING_SKILLS,
        step_budget=3, time_budget_s=120.0, extras={"camps": ("SHIELD_CAMP",)},
    ),
    SessionRoute(
        goal_id="LANCER_CAMP_TRAINING", adapter="training_batch", skills=TRAINING_SKILLS,
        step_budget=3, time_budget_s=120.0, extras={"camps": ("LANCER_CAMP",)},
    ),
    SessionRoute(
        goal_id="MARKSMAN_CAMP_TRAINING", adapter="training_batch", skills=TRAINING_SKILLS,
        step_budget=3, time_budget_s=120.0, extras={"camps": ("MARKSMAN_CAMP",)},
    ),
)


def route_for(goal_id: str, skill_id: str = "") -> SessionRoute | None:
    """The route for this Goal, or ``None`` so the caller keeps the atomic path.

    ``skills`` empty means "whatever this Goal emits".  A route that names skills only fires
    for those skills, so a Goal with one session owning part of its work still gets the
    ordinary path for the rest.
    """
    key = str(goal_id or "").strip().upper()
    if not key:
        return None
    for route in SESSION_ROUTES:
        if route.goal_id.upper() != key:
            continue
        if route.accepts(skill_id):
            return route
    return None


@dataclass(frozen=True)
class SessionPlan:
    """Everything the runtime needs to start one session for one Goal.

    Returned as one object rather than a tuple so a caller cannot silently swap the budget
    and the deadline: they are two different facts and the order they came back in is not
    something a reader should have to remember.
    """

    route: SessionRoute
    spec: SessionSpec
    goal_deadline_s: float | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


def plan_for(route: SessionRoute, *, goal_id: str, role_id: str = "",
             goal_evidence: Mapping[str, Any] | None = None) -> SessionPlan:
    """Build the plan from the route's declaration plus what the Goal itself knows.

    The Goal's own deadline is deliberately *not* folded into ``time_budget_s``: a Goal with
    twelve minutes left does not license a twelve-minute session, and a session that used
    the whole of its Goal's remaining life would leave nothing for the Goal to finish with.
    It travels separately as ``goal_deadline_s`` so the two facts stay distinguishable.
    """
    evidence = goal_evidence if isinstance(goal_evidence, Mapping) else {}
    deadline = evidence.get("remaining_seconds")
    deadline_s = float(deadline) if isinstance(deadline, (int, float)) \
        and not isinstance(deadline, bool) else None
    spec = SessionSpec(
        goal_id=str(goal_id), adapter=str(route.adapter), role_id=str(role_id or ""),
        step_budget=int(route.step_budget), time_budget_s=float(route.time_budget_s),
        resource_budget=dict(route.resource_budget or {}),
    )
    return SessionPlan(route=route, spec=spec, goal_deadline_s=deadline_s,
                       extras=dict(route.extras or {}))


# ==============================================================================
# Shared helpers
# ==============================================================================

def _text(host: SessionHost, frame: Any, *, region: tuple[float, float, float, float] | None = None) -> str:
    """The client's own words on this frame, as one string.

    Wrapped so a host whose OCR is off, broken or slow returns "" instead of taking the
    session down: several of the predicates below degrade safely to "unknown", and an
    unreadable frame is exactly the situation where failing the session would be wrong.
    """
    try:
        tokens = host.ocr(frame, region=region) or []
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    for token in tokens:
        if isinstance(token, Mapping):
            parts.append(str(token.get("text") or ""))
        else:
            parts.append(str(token))
    return " ".join(part for part in parts if part)


def _int_match(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _stamina_of(world: Any) -> int | None:
    """The stamina the client drew, or ``None`` when this frame does not show it.

    ``None`` is load-bearing and must never be flattened to 0: §真值纪律 "空 ≠ 没有".  A
    session that read "no stamina" out of an unread panel would stop spending stamina on a
    frame that simply did not show the number.
    """
    stamina = getattr(world, "stamina", None)
    if isinstance(stamina, Mapping):
        for key in ("value", "current", "available", "amount", "remaining"):
            found = _as_int(stamina.get(key))
            if found is not None:
                return found
    return None


def _rally_rows(world: Any) -> tuple[Any, ...]:
    rally = getattr(world, "rally", None)
    if not isinstance(rally, Mapping):
        return ()
    rows = rally.get("rows")
    if not isinstance(rows, (list, tuple)):
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


# ==============================================================================
# 1. Fishing
# ==============================================================================

FISHING_HOME_WORD = "普通关卡"
FISHING_ENTRY_WORD = "钓鱼锦标赛"
FISHING_EXIT_WORD = "退出"
FISHING_RESULT_WORDS = ("本次收获", "下潜深度")
#: Only the *dismiss* prompts.  A reward popup is closed by tapping where it says to tap,
#: which is why the word itself is the target and no coordinate is stored anywhere.
FISHING_POPUP_WORDS = ("点击任意位置继续", "恭喜您获得新图鉴", "恭喜获得")
FISHING_POINTS_PATTERN = r"冰钓积分[:：]\s*(\d+)"
FISHING_BAIT_PATTERN = r"(\d+)\s*/\s*(\d+)"
FISHING_DEPTH_PATTERN = r"下潜深度[:：]\s*(\d+)"

#: The stages of one cast.  Explicit rather than inferred from the frame alone, because
#: "home is not printed" means different things before entering and after exiting.
STAGE_HOME = "HOME"
STAGE_ENTERING = "ENTERING"
STAGE_CONTROLLING = "CONTROLLING"
STAGE_LEAVING = "LEAVING"
STAGE_DONE = "DONE"


@dataclass
class FishingDomain:
    frame: Any = None
    text: str = ""
    bait: int | None = None
    bait_cap: int | None = None
    points: int | None = None
    depth_m: int | None = None
    on_home: bool = False
    popup_word: str = ""
    result_page: bool = False


class FishingSessionAdapter(SessionAdapter):
    """One cast, end to end, inside one Goal.

    Reuse, not rewrite: the level is steered by the *existing*
    ``FishingSessionController`` + ``VisualServoSession`` + ``ContinuousTouchSession`` +
    ``detect_fishing``, unchanged.  This class only decides when to enter, when to hand
    over, when to stop, and what makes the cast count.
    """

    name = "fishing"

    #: The servo's own config, copied from the live run that measured the fishing level
    #: (``tools/fishing_servo_run.py``): 20 Hz, 28 px per tick, a 5 px dead zone and a
    #: 1.5 s hold while the target is lost.  Kept here rather than re-tuned so the session
    #: path and the measured path steer identically.
    SERVO_DEFAULTS: Mapping[str, Any] = {
        "anchor_y": 800, "target_hz": 20.0, "dead_zone_px": 5, "max_move_per_tick_px": 28,
        "low_pass_alpha": 0.55, "engage_move_px": 22, "max_lost_frames": 8,
        "lost_target_timeout_s": 1.5, "hold_while_lost": True, "stale_frame_limit": 90,
    }
    #: Calibration legs before the real policy takes the line.  Measured on the live level:
    #: the actionable window is only a few seconds, so this must stay short.
    CALIBRATE_TICKS = 26

    def __init__(self, *, controller: Any = None, servo_config: Any = None) -> None:
        # Injected for tests; the defaults are the real measured objects.
        self._controller = controller
        self._servo_config = servo_config
        self.stage = STAGE_HOME
        self.casts = 0
        self.casts_target = 1
        self.bait_before: int | None = None
        self.bait_after: int | None = None
        self.points_before: int | None = None
        self.points_after: int | None = None
        self.depth_m: int | None = None
        self.cast_verified = False
        self.servo_report: Mapping[str, Any] = {}
        self.phase_trace: list[str] = []

    # --------------------------------------------------------------- budget

    def configure(self, extras: Mapping[str, Any],
                  resource_budget: Mapping[str, float] | None = None) -> None:
        casts = _as_int((extras or {}).get("casts"))
        if casts and casts > 0:
            self.casts_target = casts

    # --------------------------------------------------------------- observe

    def observe(self, context: SessionContext, host: SessionHost) -> Any:
        frame = host.capture()
        if frame is None:
            return None
        text = _text(host, frame)
        domain = FishingDomain(frame=frame, text=text)
        domain.on_home = FISHING_HOME_WORD in text
        domain.popup_word = next((word for word in FISHING_POPUP_WORDS if word in text), "")
        domain.result_page = any(word in text for word in FISHING_RESULT_WORDS)
        bait = re.search(FISHING_BAIT_PATTERN, text)
        if bait:
            domain.bait, domain.bait_cap = int(bait.group(1)), int(bait.group(2))
        domain.points = _int_match(FISHING_POINTS_PATTERN, text)
        domain.depth_m = _int_match(FISHING_DEPTH_PATTERN, text)
        if domain.on_home and self.bait_before is None and domain.bait is not None:
            self.bait_before = domain.bait
            self.points_before = domain.points
        elif domain.on_home and domain.bait is not None:
            self.bait_after = domain.bait
            if domain.points is not None:
                self.points_after = domain.points
        if domain.depth_m is not None:
            self.depth_m = domain.depth_m
        return domain

    # --------------------------------------------------------------- complete

    def is_complete(self, context: SessionContext, host: SessionHost, domain: Any) -> tuple[bool, str]:
        if self.casts >= self.casts_target and self.cast_verified and domain.on_home:
            return True, "FISHING_CASTS_DONE"
        if domain.bait is not None and domain.bait <= 0 and domain.on_home:
            # No bait left is a legitimate end of this Goal's work, not a failure: the
            # Goal is "use normal bait", and there is none.  Reported as ITS OWN reason so
            # it is not confused with having cast successfully.
            return True, "FISHING_NO_NORMAL_BAIT"
        return False, ""

    # --------------------------------------------------------------- choose

    def choose_step(self, context: SessionContext, host: SessionHost, domain: Any) -> SessionStep | None:
        if self.casts >= self.casts_target and self.cast_verified:
            if self.stage is STAGE_LEAVING and not domain.on_home:
                return SessionStep(0, STEP_PRINTED_TAP, target=FISHING_EXIT_WORD,
                                   reason="leave the result page")
            return None
        if domain.popup_word:
            return SessionStep(0, STEP_PRINTED_TAP, target=domain.popup_word,
                               reason="dismiss the modal the client printed")
        if self.stage is STAGE_LEAVING:
            return SessionStep(0, STEP_PRINTED_TAP, target=FISHING_EXIT_WORD,
                               reason="leave the result page")
        if self.stage is STAGE_CONTROLLING:
            return self._control_step(domain)
        if self.stage is STAGE_ENTERING:
            # Waiting for the level to draw.  OBSERVE_ONLY spends one step of the budget to
            # look again rather than re-tapping 普通关卡, which would restart the cutscene.
            return SessionStep(0, STEP_OBSERVE_ONLY, reason="waiting for the level to draw")
        if domain.on_home:
            if domain.bait is not None and domain.bait <= 0:
                return None
            return SessionStep(0, STEP_PRINTED_TAP, target=FISHING_HOME_WORD,
                               reason="enter one normal fishing level",
                               tags={"stage": STAGE_ENTERING})
        return SessionStep(0, STEP_PRINTED_TAP, target=FISHING_ENTRY_WORD,
                           reason="open the fishing tournament the client prints")

    def _control_step(self, domain: FishingDomain) -> SessionStep:
        controller = self._controller or FishingSessionController(
            mode="AUTO", calibrate_ticks=self.CALIBRATE_TICKS)
        config = self._servo_config
        if config is None:
            from .visual_servo import ServoConfig  # local: keeps import cost off the hot path

            config = ServoConfig(max_session_duration_s=30.0, **dict(self.SERVO_DEFAULTS))

        def detector(frame: Any) -> Any:
            state = detect_fishing(frame)
            controller.set_frame(frame)
            return state

        control = RealtimeControl(
            detector=detector, controller=controller, config=config,
            max_seconds=30.0, wait_for_line_s=45.0,
            start_words=FISHING_POPUP_WORDS + ("点击开始", "点击屏幕", "开始钓鱼"),
            start_signal=lambda state: bool(getattr(state, "found", False)),
            lost_ticks_to_end=16,
        )
        return SessionStep(0, STEP_REALTIME, params={"control": control},
                           reason="steer the level to its end",
                           expected="the level ends and the result page is drawn")

    # --------------------------------------------------------------- verify

    def verify_step(self, context: SessionContext, host: SessionHost, step: SessionStep,
                    execution: StepExecution) -> StepVerdict:
        if step.kind is STEP_REALTIME:
            report = dict(execution.evidence or {})
            self.servo_report = report
            frames = _as_int(report.get("frames")) or 0
            moves = _as_int(report.get("moves_sent")) or 0
            if frames > 0 and moves > 0:
                self.cast_verified = True
                self.casts += 1
                self.stage = STAGE_LEAVING
                return StepVerdict(StepOutcome.SUCCESS, "FISHING_CONTROL_SESSION_RAN",
                                   {"frames": frames, "moves_sent": moves,
                                    "control_hz": report.get("control_hz")})
            self.stage = STAGE_LEAVING
            return StepVerdict(StepOutcome.FAILED,
                               str(report.get("outcome") or "FISHING_CONTROL_SESSION_DID_NOT_RUN"),
                               {"frames": frames, "moves_sent": moves})
        if step.target == FISHING_HOME_WORD:
            self.stage = STAGE_CONTROLLING
            return StepVerdict(StepOutcome.PROGRESS, "FISHING_LEVEL_ENTRY_TAPPED")
        if step.target == FISHING_EXIT_WORD:
            self.stage = STAGE_DONE
            return StepVerdict(StepOutcome.PROGRESS, "FISHING_RESULT_LEFT")
        if step.kind is STEP_OBSERVE_ONLY:
            # Looking again is the adapter's own cheap read: one capture through the same
            # detector the servo uses, and the answer is whether the line is drawn yet.
            frame = host.capture()
            if frame is None:
                return StepVerdict(StepOutcome.AMBIGUOUS, "FISHING_NO_FRAME")
            state = detect_fishing(frame)
            if getattr(state, "found", False):
                self.stage = STAGE_CONTROLLING
                return StepVerdict(StepOutcome.PROGRESS, "FISHING_LINE_VISIBLE")
            return StepVerdict(StepOutcome.STILL_PENDING, "FISHING_WAITING_FOR_LEVEL")
        return StepVerdict(StepOutcome.PROGRESS, "FISHING_FRAME_ADVANCED")

    # --------------------------------------------------------------- recover

    def recover(self, context: SessionContext, host: SessionHost, step: SessionStep,
                verdict: StepVerdict) -> bool | None:
        """A cast that did not run is retried once through the entry, never by re-tapping.

        The one recovery that is genuinely a second chance: the level may simply not have
        drawn yet, so the adapter goes back to ENTERING and looks again.
        """
        if step.kind is STEP_REALTIME and self.casts == 0:
            self.stage = STAGE_ENTERING
            self.cast_verified = False
            return True
        return None

    def summarize(self) -> dict[str, Any]:
        return {
            "casts": self.casts, "casts_target": self.casts_target,
            "bait": f"{self.bait_before}->{self.bait_after}",
            "points": f"{self.points_before}->{self.points_after}",
            "depth_m": self.depth_m, "stage": self.stage,
            "cast_verified": self.cast_verified,
            "servo": dict(self.servo_report or {}),
        }


# ==============================================================================
# 2. Bear
# ==============================================================================

@dataclass
class BearDomain:
    world: Any = None
    rows: tuple[Any, ...] = ()
    target: str = RallyTarget.BEAR.value
    joinable: Any = None
    list_visible: bool = False
    idle_marches: int | None = None


@dataclass(frozen=True)
class JoinableRally:
    """The joinable rally the *current frame* shows, and which row it is.

    ``point`` is normalised and was produced by reading this frame (``live_rally_join_point``),
    never stored.  ``row_index`` exists so the episode can name the row that was joined --
    §25's "find the joinable row, identify its button, click the identified result" -- without
    the engine or the adapter ever carrying a coordinate forward.
    """

    point: tuple[float, float]
    row_index: int | None = None


def _row_index_for_point(rows: Iterable[Any], point: tuple[float, float]) -> int | None:
    """Which row's own join button this point is, matched by the row's declared bbox.

    Returns ``None`` when no row claims the point -- which is the honest answer and stays
    distinguishable from "row 0", because a row index of ``None`` means the identity could not
    be established from this frame.
    """
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        box = row.get("join_button_bbox")
        if not (isinstance(box, (list, tuple)) and len(box) == 4):
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in box)
        except (TypeError, ValueError):
            continue
        if x0 <= point[0] <= x1 and y0 <= point[1] <= y1:
            return index
    return None


class BearSessionAdapter(SessionAdapter):
    """``START_RALLY`` once, then ``JOIN_RALLY`` until the list stops offering rows.

    The list is re-read on **every** step (the runtime's observation), which is the
    "refresh ROI between joins" the directive asks for.  A row read more than three seconds
    ago is not clickable — ``rally.stale_frame_reason``'s measured window — so a join is
    only ever issued against the frame in hand.
    """

    name = "bear"

    def __init__(self, *, target: str = RallyTarget.BEAR.value, max_joins: int = 8,
                 start_once: bool = True) -> None:
        self.target = str(target or RallyTarget.BEAR.value)
        self.max_joins = max(1, int(max_joins))
        self.start_once = bool(start_once)
        self.joins = 0
        self.starts = 0
        self.refreshes = 0
        self.full_races = 0
        self.started = False

    def configure(self, extras: Mapping[str, Any],
                  resource_budget: Mapping[str, float] | None = None) -> None:
        data = extras or {}
        if data.get("target"):
            self.target = str(data["target"])
        joins = _as_int(data.get("max_joins"))
        if joins and joins > 0:
            self.max_joins = joins

    # --------------------------------------------------------------- observe

    def observe(self, context: SessionContext, host: SessionHost) -> Any:
        world = host.observe("session_bear")
        if world is None:
            return None
        rows = _rally_rows(world)
        # The target comes from the Goal when the Goal named one, and from the route
        # otherwise -- never from a row, because a row's target is what we are matching
        # against and reading the answer out of the thing being tested would be circular.
        goal_target = rally_target_for_goal(context.goal_id, dict(context.extras or {}))
        target = goal_target or self._declared_target()
        alliance = getattr(world, "alliance", None)
        # The joinable row is found by the *world-driven* reader (``live_rally_join_point``),
        # not by ``fastest_joinable_for``: the runtime publishes rally rows as Mappings and
        # ``fastest_joinable_for`` needs ``RallyRow`` objects, so feeding it the raw rows
        # raised ``AttributeError: 'dict' object has no attribute 'joinable_for'`` -- which the
        # engine's observation guard would have reported as ``SESSION_OBSERVE_FAILED`` on every
        # live bear session.  This reader takes the same rows, adds the two checks the runtime
        # already makes (the list is really on screen, and the reading came from this frame's
        # OCR), and answers with the point.
        point = live_rally_join_point(world, target)
        joinable = (JoinableRally(point=point, row_index=_row_index_for_point(rows, point))
                    if point is not None else None)
        return BearDomain(
            world=world, rows=rows, target=target.value,
            joinable=joinable,
            list_visible=bool(isinstance(alliance, Mapping)
                              and alliance.get("rally_list_visible") is True),
            idle_marches=getattr(world, "idle_marches", None),
        )

    def _declared_target(self) -> RallyTarget:
        try:
            return RallyTarget(str(self.target).strip().upper())
        except ValueError:
            return RallyTarget.UNKNOWN

    # --------------------------------------------------------------- complete

    def is_complete(self, context: SessionContext, host: SessionHost, domain: Any) -> tuple[bool, str]:
        if self.joins >= self.max_joins:
            return True, "BEAR_JOIN_BUDGET_REACHED"
        if self.refreshes >= 3 and not domain.rows:
            # Three re-reads of a list that keeps showing nothing is a statement about the
            # event, not about the frame: hand the device back rather than spin on it.
            #
            # Deliberately NOT conditioned on ``joins == 0``.  Requiring that meant a session
            # which had already joined some rallies never ended once the list emptied: measured
            # in the adapter smoke, two joins followed by an empty list produced nine
            # ``OPEN_BEAR_RALLY_LIST`` refreshes and ended only when the *step budget* ran out.
            # An empty list is equally final after a join, and the reason names the same fact.
            return True, "BEAR_LIST_HAS_NO_ROWS"
        return False, ""

    # --------------------------------------------------------------- choose

    def choose_step(self, context: SessionContext, host: SessionHost, domain: Any) -> SessionStep | None:
        if self.start_once and not self.started and self.starts == 0 and self.joins == 0:
            # One START per session, and it goes first: the bear special slot is what makes
            # the role a leader, and every later join benefits from the rally existing.
            return SessionStep(0, STEP_SKILL, skill_id="START_RALLY",
                               params={"rally_target": self.target},
                               expected="the bear rally is created",
                               reason="start the bear rally once")
        if domain.joinable is not None:
            return SessionStep(0, STEP_SKILL, skill_id="JOIN_RALLY",
                               params={"rally_target": self.target},
                               expected="the role is in the rally",
                               reason="join the fastest joinable row of this target",
                               tags={"row_index": getattr(domain.joinable, "row_index", None)})
        self.refreshes += 1
        return SessionStep(0, STEP_SKILL, skill_id="OPEN_BEAR_RALLY_LIST",
                           expected="the rally list is on screen",
                           reason="re-read the rally list; no joinable row in this frame")

    # --------------------------------------------------------------- verify

    def verify_step(self, context: SessionContext, host: SessionHost, step: SessionStep,
                    execution: StepExecution) -> StepVerdict:
        # The registered verifier is the domain verifier here: START_RALLY / JOIN_RALLY have
        # their own target-scoped checks in the runtime, and duplicating them would be the
        # second implementation the directive forbids.
        verdict = host.verify_step(step, execution)
        if verdict is None:
            return StepVerdict(StepOutcome.AMBIGUOUS, "BEAR_NO_VERDICT")
        if not verdict.ok:
            return StepVerdict(StepOutcome.FAILED, verdict.reason, dict(verdict.evidence or {}))
        if step.skill_id == "START_RALLY":
            self.starts += 1
            self.started = True
        elif step.skill_id == "JOIN_RALLY":
            self.joins += 1
        return StepVerdict(StepOutcome.SUCCESS, verdict.reason or "BEAR_STEP_VERIFIED",
                           dict(verdict.evidence or {}))

    # --------------------------------------------------------------- recover

    def recover(self, context: SessionContext, host: SessionHost, step: SessionStep,
                verdict: StepVerdict) -> bool | None:
        """A rally that filled between reading and clicking is re-read, not re-tapped.

        ``RALLY_FULL`` / ``ROW_GONE`` / ``TARGET_CHANGED`` are the three measured lost races
        and the only ones worth a second attempt; every other failure ends the session so
        the runtime can hand the cycle to a different Goal.
        """
        reason = str(verdict.reason or "").upper()
        if any(mark in reason for mark in ("FULL", "ROW_GONE", "TARGET_CHANGED")):
            self.full_races += 1
            return True
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "target": self.target, "starts": self.starts, "joins": self.joins,
            "refreshes": self.refreshes, "lost_races": self.full_races,
        }

    def summarize(self) -> dict[str, Any]:
        return self.summary()


# ==============================================================================
# 3. Stamina
# ==============================================================================

@dataclass
class StaminaDomain:
    world: Any = None
    stamina: int | None = None
    idle_marches: int | None = None


class StaminaSpendSessionAdapter(SessionAdapter):
    """Spend stamina legally, one march after another, until the floor or a blocked march.

    The floor (``stamina < 30``) is declared in **two** places on purpose and they mean
    different things: ``SessionSpec.resource_budget`` is the engine refusing to issue the
    *next* step, and ``is_complete`` is the Goal reporting that its work is finished.  Both
    are needed — a budget floor alone would end the session as a failure, and a predicate
    alone would issue one more march after the reading that should have stopped it.
    """

    name = "stamina"

    def __init__(self, *, floor: int = int(STAMINA_FLOOR), max_marches: int = 4,
                 skill_id: str = "DISPATCH_MARCH") -> None:
        self.floor = int(floor)
        self.max_marches = max(1, int(max_marches))
        self.skill_id = str(skill_id)
        self.marches = 0
        self.stamina_before: int | None = None
        self.stamina_after: int | None = None

    def configure(self, extras: Mapping[str, Any],
                  resource_budget: Mapping[str, float] | None = None) -> None:
        data = extras or {}
        marches = _as_int(data.get("max_marches"))
        if marches and marches > 0:
            self.max_marches = marches
        if data.get("skill_id"):
            self.skill_id = str(data["skill_id"])
        floor = (resource_budget or {}).get("stamina")
        if isinstance(floor, (int, float)) and not isinstance(floor, bool):
            self.floor = int(floor)

    # --------------------------------------------------------------- observe

    def observe(self, context: SessionContext, host: SessionHost) -> Any:
        world = host.observe("session_stamina")
        if world is None:
            return None
        stamina = _stamina_of(world)
        if stamina is not None:
            if self.stamina_before is None:
                self.stamina_before = stamina
            self.stamina_after = stamina
        return StaminaDomain(world=world, stamina=stamina,
                             idle_marches=getattr(world, "idle_marches", None))

    # --------------------------------------------------------------- complete

    def is_complete(self, context: SessionContext, host: SessionHost, domain: Any) -> tuple[bool, str]:
        if self.marches >= self.max_marches:
            return True, "STAMINA_MARCH_BUDGET_REACHED"
        if domain.stamina is not None and domain.stamina < self.floor:
            return True, f"STAMINA_BELOW_FLOOR:{domain.stamina}<{self.floor}"
        if domain.idle_marches == 0:
            return True, "STAMINA_MARCH_BLOCKED:NO_IDLE_SLOT"
        return False, ""

    # --------------------------------------------------------------- choose

    def choose_step(self, context: SessionContext, host: SessionHost, domain: Any) -> SessionStep | None:
        if domain.stamina is None and domain.idle_marches is None:
            # Nothing readable yet: look again rather than marching blind.
            return SessionStep(0, STEP_OBSERVE_ONLY, reason="stamina not readable on this frame")
        if domain.idle_marches is not None and domain.idle_marches <= 0:
            return None
        return SessionStep(0, STEP_SKILL, skill_id=self.skill_id,
                           expected="one more march is out",
                           reason="spend stamina while the floor is respected")

    # --------------------------------------------------------------- verify

    def verify_step(self, context: SessionContext, host: SessionHost, step: SessionStep,
                    execution: StepExecution) -> StepVerdict:
        if step.kind is STEP_OBSERVE_ONLY:
            return StepVerdict(StepOutcome.STILL_PENDING, "STAMINA_STILL_UNREADABLE")
        verdict = host.verify_step(step, execution)
        if verdict is None:
            return StepVerdict(StepOutcome.AMBIGUOUS, "STAMINA_NO_VERDICT")
        if not verdict.ok:
            return StepVerdict(StepOutcome.FAILED, verdict.reason, dict(verdict.evidence or {}))
        self.marches += 1
        return StepVerdict(StepOutcome.SUCCESS, verdict.reason or "STAMINA_MARCH_VERIFIED",
                           dict(verdict.evidence or {}))

    def summarize(self) -> dict[str, Any]:
        return {"marches": self.marches, "floor": self.floor,
                "stamina": f"{self.stamina_before}->{self.stamina_after}"}


# ==============================================================================
# 4. Training batch
# ==============================================================================

TRAINING_CAMP_ORDER: tuple[str, ...] = ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP")
TRAINING_CAMP_TAP: Mapping[str, str] = {
    "SHIELD_CAMP": "TAP_FOCUSED_TRAINING_CAMP_SHIELD",
    "LANCER_CAMP": "TAP_FOCUSED_TRAINING_CAMP_LANCER",
    "MARKSMAN_CAMP": "TAP_FOCUSED_TRAINING_CAMP_MARKSMAN",
}
#: Camp states that mean "this barracks is already working, do not tap it".
CAMP_BUSY_VALUES = frozenset({"训练中", "IN_PROGRESS", "BUSY", "RUNNING", "TRAINING"})
CAMP_DONE_VALUES = frozenset({"已完成", "COMPLETE", "DONE", "IDLE", "READY"})


@dataclass
class TrainingDomain:
    world: Any = None
    camps: Mapping[str, Any] = field(default_factory=dict)


class TrainingBatchSessionAdapter(SessionAdapter):
    """Work this role's three barracks in one arbitration.

    ``world.camps`` / ``world.quick_panel["camps"]`` are the two readings the project
    already has, and the quick panel answers all three camps in ONE frame — which is the
    whole reason this session is worth having: the ordinary path opens the panel (or the
    training page) once per arbitration, so three barracks cost three page visits.

    The camp order is fixed (shield → lancer → marksman) because the panel reads
    top-to-bottom and a stable order makes a partially-completed batch diagnosable.
    """

    name = "training_batch"

    #: How many readings that cannot name every declared barracks are tolerated before the
    #: session ends and says so.  Small on purpose: the alternative is waiting out the
    #: engine's ``max_wait_s`` to learn the same fact, and the reason for the bound is that
    #: a barracks the reader cannot see is not evidence that there is nothing to do.
    MAX_UNREADABLE_ROUNDS = 3

    def __init__(self, *, camps: Iterable[str] | None = None, max_camps: int = 3) -> None:
        wanted = tuple(str(c) for c in (camps or ()) if str(c) in TRAINING_CAMP_TAP)
        self.camps = wanted or TRAINING_CAMP_ORDER
        self.max_camps = max(1, int(max_camps))
        self.tapped: list[str] = []
        self.skipped: list[str] = []
        self.unreadable: list[str] = []
        self.unreadable_rounds = 0

    def configure(self, extras: Mapping[str, Any],
                  resource_budget: Mapping[str, float] | None = None) -> None:
        camps = (extras or {}).get("camps")
        if camps:
            wanted = tuple(str(c) for c in camps if str(c) in TRAINING_CAMP_TAP)
            if wanted:
                self.camps = wanted

    # --------------------------------------------------------------- observe

    def observe(self, context: SessionContext, host: SessionHost) -> Any:
        world = host.observe("session_training")
        if world is None:
            return None
        camps = getattr(world, "camps", None)
        if not isinstance(camps, Mapping) or not camps:
            panel = getattr(world, "quick_panel", None)
            if isinstance(panel, Mapping) and isinstance(panel.get("camps"), Mapping):
                camps = panel["camps"]
        return TrainingDomain(world=world, camps=camps if isinstance(camps, Mapping) else {})

    # --------------------------------------------------------------- complete

    def is_complete(self, context: SessionContext, host: SessionHost, domain: Any) -> tuple[bool, str]:
        pending = self._pending(domain)
        if pending is None:
            # A declared barracks could not be read at all.  That is a statement about the
            # reader, not about the work, so the session must not claim completion on it --
            # but it also must not wait out the engine's whole budget to learn nothing new.
            # Three readings is the bound, and the reason names what could not be read so the
            # end is never mistakable for the batch having been done.
            self.unreadable_rounds += 1
            if self.unreadable_rounds >= self.MAX_UNREADABLE_ROUNDS:
                return True, ("TRAINING_CAMPS_UNREADABLE:"
                              + "+".join(sorted(dict.fromkeys(self.unreadable))))
            return False, ""
        self.unreadable_rounds = 0
        if not pending:
            return True, "TRAINING_BATCH_DONE"
        return False, ""

    def _pending(self, domain: TrainingDomain) -> tuple[str, ...] | None:
        """Camps still worth a tap, or ``None`` when the frame cannot answer.

        ``None`` versus ``()`` is the whole distinction: the first says "ask me again", the
        second says "there is nothing left to do".

        "Nothing left to do" requires having read **every** declared barracks.  The first
        version returned ``()`` as soon as any one camp was readable and none of the readable
        ones needed a tap, so a frame where the only readable barracks happened to be busy
        reported the whole batch as done -- measured in the adapter smoke as
        ``TAPPED=[] SKIPPED=[LANCER] REASON=TRAINING_BATCH_DONE``, two never-tapped barracks
        silently counted as handled.  An unreadable barracks is unknown, not finished
        (§真值纪律 空 ≠ 没有).
        """
        pending: list[str] = []
        missing: list[str] = []
        for camp in self.camps:
            state = self._camp_state(domain, camp)
            if state is None:
                self.unreadable.append(camp)
                missing.append(camp)
                continue
            if str(state).upper() in {value.upper() for value in CAMP_BUSY_VALUES} \
                    or str(state) in CAMP_BUSY_VALUES:
                self.skipped.append(camp)
                continue
            if camp in self.tapped:
                continue
            pending.append(camp)
        if pending:
            return tuple(pending)
        if missing:
            return None
        return ()

    @staticmethod
    def _camp_state(domain: TrainingDomain, camp: str) -> Any:
        record = domain.camps.get(camp)
        if isinstance(record, Mapping):
            for key in ("state", "status", "training"):
                if record.get(key) is not None:
                    return record.get(key)
            # ``busy`` is the boolean form the quick-panel reader uses.
            if isinstance(record.get("busy"), bool):
                return "训练中" if record["busy"] else "已完成"
            return None
        return record

    # --------------------------------------------------------------- choose

    def choose_step(self, context: SessionContext, host: SessionHost, domain: Any) -> SessionStep | None:
        pending = self._pending(domain)
        if not pending:
            return None
        if len(self.tapped) >= self.max_camps:
            return None
        camp = pending[0]
        return SessionStep(0, STEP_SKILL, skill_id=TRAINING_CAMP_TAP[camp],
                           expected=f"{camp} starts training",
                           reason="work one barracks of this role's batch",
                           tags={"camp": camp})

    # --------------------------------------------------------------- verify

    def verify_step(self, context: SessionContext, host: SessionHost, step: SessionStep,
                    execution: StepExecution) -> StepVerdict:
        camp = str((step.tags or {}).get("camp") or "")
        verdict = host.verify_step(step, execution)
        if verdict is None:
            return StepVerdict(StepOutcome.AMBIGUOUS, "TRAINING_NO_VERDICT", {"camp": camp})
        if not verdict.ok:
            return StepVerdict(StepOutcome.FAILED, verdict.reason, {"camp": camp})
        if camp:
            self.tapped.append(camp)
        return StepVerdict(StepOutcome.SUCCESS, verdict.reason or "TRAINING_CAMP_TAPPED",
                           {"camp": camp, **dict(verdict.evidence or {})})

    def summarize(self) -> dict[str, Any]:
        return {"tapped": list(self.tapped), "skipped": list(self.skipped),
                "unreadable": list(dict.fromkeys(self.unreadable)),
                "camps": list(self.camps)}


# ==============================================================================
# Registry
# ==============================================================================

SESSION_ADAPTERS: dict[str, type[SessionAdapter]] = {
    FishingSessionAdapter.name: FishingSessionAdapter,
    BearSessionAdapter.name: BearSessionAdapter,
    StaminaSpendSessionAdapter.name: StaminaSpendSessionAdapter,
    TrainingBatchSessionAdapter.name: TrainingBatchSessionAdapter,
}


def make_adapter(name: str, *, extras: Mapping[str, Any] | None = None,
                 resource_budget: Mapping[str, float] | None = None) -> SessionAdapter | None:
    """A **fresh** adapter for one session, configured from its route.

    Freshness is a requirement, not tidiness: an adapter accumulates per-cast counters, and
    a shared instance would let one session's join count count for the next one's budget.
    """
    factory = SESSION_ADAPTERS.get(str(name or ""))
    if factory is None:
        return None
    adapter = factory()
    try:
        adapter.configure(dict(extras or {}), dict(resource_budget or {}))
    except Exception:  # noqa: BLE001 - a bad declaration must not take the runtime down
        pass
    return adapter


__all__ = [
    "BEAR_SKILLS", "BearDomain", "BearSessionAdapter", "CAMP_BUSY_VALUES", "CAMP_DONE_VALUES",
    "FISHING_BAIT_PATTERN", "FISHING_DEPTH_PATTERN", "FISHING_ENTRY_WORD", "FISHING_EXIT_WORD",
    "FISHING_HOME_WORD",
    "FISHING_POINTS_PATTERN", "FISHING_POPUP_WORDS", "FISHING_RESULT_WORDS",
    "FishingDomain", "FishingSessionAdapter", "JoinableRally", "SESSION_ADAPTERS",
    "SESSION_ROUTES",
    "STAMINA_FLOOR", "STAMINA_SKILLS", "STAGE_CONTROLLING", "STAGE_DONE", "STAGE_ENTERING",
    "STAGE_HOME", "STAGE_LEAVING", "SessionPlan", "SessionRoute", "StaminaDomain",
    "StaminaSpendSessionAdapter", "TRAINING_CAMP_ORDER", "TRAINING_CAMP_TAP",
    "TRAINING_SKILLS", "TrainingBatchSessionAdapter", "TrainingDomain", "make_adapter",
    "plan_for", "route_for",
]
