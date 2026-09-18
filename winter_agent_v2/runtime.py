from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Callable

from .brain import RuleBrain
from .executor import Executor
from .executor_router import BackendLedger, RoutingTable, build_router
from .learning import Episode, EpisodeStore
from .models import Decision, ExecutionResult, Page, VerificationResult, WorldState
from .scheduler import Scheduler
from .goal_library import GoalLibrary, GoalStateStore, progress_moved
from .capability_gate import CapabilityGate, Deferral
from .candidate_policy import CandidateAttemptPool
from .skills import SkillRegistry, v2_registry
from .verifier import verify_alliance_reward_dismissed, verify_ally_gift_claim_feedback, verify_intel_hero_dispatched, verify_intel_hero_march_open, verify_intel_hero_target_open, verify_daily_claim_feedback, verify_daily_reward_advanced, verify_daily_tab_selected, verify_exploration_claim_confirmed, verify_exploration_claim_feedback, verify_exploration_reward_dismissed, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_mail_read_or_claim, verify_offline_rewards_claimed, verify_open_alliance, verify_open_alliance_gifts, verify_open_daily, verify_open_exploration, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_intel_list_read, verify_alliance_gifts_claimed
from .verifier import verify_ally_gift_claim, verify_beast_dispatch, verify_beast_march_open, verify_beast_scan_observed, verify_beast_target_selected, verify_building_upgrade, verify_camp_menu_reobserved, verify_duplicate_target_cancelled, verify_environmental_wait, verify_intel_beast_dispatch, verify_intel_beast_march_open, verify_intel_claim_feedback, verify_intel_mission_selected, verify_intel_pin_opened, verify_intel_rescue_selected, verify_intel_rescue_started, verify_intel_rescue_target_open, verify_intel_reward_dismissed, verify_intel_target_open, verify_mail_alliance_tab_selected, verify_mail_claim_feedback, verify_mail_report_tab_selected, verify_mail_reward_dismissed, verify_mail_system_tab_selected, verify_march_count_readable, verify_march_page_open, verify_march_recall_dialog_open, verify_march_recalled, verify_open_home, verify_open_intel, verify_open_mail, verify_open_map, verify_popup_closed, verify_research_lab_focused, verify_research_page_open, verify_research_started, verify_resource_found, verify_resource_level_relaxed, verify_resource_search_open, verify_resource_selected, verify_free_stamina_claimed, verify_safe_back, verify_stamina_sources_open, verify_training_started, verify_wood_dispatch_from_march
from .runtime_snapshot import AgentState, RuntimeSnapshotStore, is_fatal_stop
from .resource_rotation import ResourceRotationStore
from .stamina_supply import StaminaSupplyStore
from .intel_pins import intel_pin_centers


@dataclass(frozen=True)
class LiveStep:
    index: int
    decision: Decision
    execution: ExecutionResult | None
    before: WorldState
    after: WorldState | None
    verification: VerificationResult | None


@dataclass(frozen=True)
class LiveRun:
    steps: tuple[LiveStep, ...]
    stop_reason: str
    # Goal paths this run refused to select, with the evidence for refusing.  Carried
    # out of the run rather than re-derived, so the escalation hook hands off exactly
    # what the scheduler decided and the two cannot disagree.
    deferrals: tuple[dict, ...] = ()


Verifier = Callable[[WorldState, WorldState], VerificationResult]


def _executor_label(execution: ExecutionResult | None) -> str:
    """Summarise one action's real backend chain for the episode.

    ``MAA``      MAA drove the screen and either MAA or nothing did the recognition
    ``HYBRID``   MAA drove the screen but the V2 semantic vision found the target
    ``ADB``      the historical path end to end
    ``""``       nothing was issued, so no backend can be credited
    """
    if execution is None or not execution.executed or not execution.backend:
        return ""
    if execution.backend == "MAA":
        return "MAA" if execution.recognition_backend in {"MAA", "NONE"} else "HYBRID"
    return execution.backend


class LiveRuntime:
    """Bounded production loop built around the one V2 Scheduler.

    Only skills with an explicit post-action verifier may execute. An UNKNOWN,
    unsupported skill, device failure, or failed verifier stops the run without
    guessing or repeating an action whose result is uncertain.
    """

    # Verifiers whose success means a fight has just been dispatched, so the client
    # may spend the next seconds rendering a battle the page model cannot name.
    # Derived from the registry rather than from a skill list: INTEL_HERO_DISPATCH
    # is the only skill carrying one today (grep verifier=".*_DISPATCHED" in
    # skills.py), which keeps the branch narrow.  Widening it is a data decision --
    # each addition weakens the ordinary unknown-page recovery, so it needs frames.
    FIGHT_STARTING_VERIFIERS = frozenset({"INTEL_HERO_DISPATCHED"})

    VERIFIED_ATOMIC: dict[str, Verifier] = {
        "WAIT": verify_environmental_wait,
        "CLOSE_POPUP": verify_popup_closed,
        "CANCEL_DUPLICATE_TARGET": verify_duplicate_target_cancelled,
        "RECONNECT_SESSION": verify_popup_closed,
        "DISMISS_BATTLEFIELD_REVIVAL": verify_popup_closed,
        "DISMISS_BATTLE_VICTORY": verify_popup_closed,
        "DISMISS_REAL_MONEY_OFFER": verify_popup_closed,
        "CLAIM_OFFLINE_REWARDS": verify_offline_rewards_claimed,
        "OPEN_DAILY": verify_open_daily,
        "DAILY_CLAIM_REWARDS": verify_daily_claim_feedback,
        "DISMISS_DAILY_REWARD": verify_daily_reward_advanced,
        "BACK": verify_safe_back,
        "DISMISS_INTEL_REWARD": verify_intel_reward_dismissed,
        "ALLIANCE_ALLY_GIFT_CLAIM": verify_ally_gift_claim,
        "OPEN_ALLIANCE_GIFTS": verify_open_alliance_gifts,
        # brain.py selects ALLIANCE_GIFTS whenever the gifts page reports
        # CLAIMABLE.  Without this entry the skill was never dispatched, so the
        # alliance gift chain always stopped one step short of claiming
        # anything (live Alliance home carried a 99+ unclaimed-gift badge).
        "ALLIANCE_GIFTS": verify_alliance_gifts_claimed,
        "DISMISS_ALLIANCE_GENERIC_REWARD": verify_alliance_reward_dismissed,
        "OPEN_MAP": verify_open_map,
        "OPEN_HOME": verify_open_home,
        "OPEN_INTEL": verify_open_intel,
        "READ_INTEL_LIST": verify_intel_list_read,
        "SEARCH_RESOURCE": verify_resource_search_open,
        "SELECT_RESOURCE": verify_resource_selected,
        "SUBMIT_RESOURCE_SEARCH": verify_resource_found,
        "RELAX_RESOURCE_LEVEL": verify_resource_level_relaxed,
        "OPEN_STAMINA_SOURCES": verify_stamina_sources_open,
        "CLAIM_FREE_STAMINA": verify_free_stamina_claimed,
        "OPEN_INTEL_HERO_JOURNEY_TARGET": verify_intel_hero_target_open,
        "INTEL_HERO_START_MARCH": verify_intel_hero_march_open,
        "INTEL_HERO_DISPATCH": verify_intel_hero_dispatched,
        "SELECT_MARCH_TO_RECALL": verify_march_recall_dialog_open,
        "RECALL_MARCH": verify_march_recalled,
        "START_GATHER": verify_march_page_open,
        # CHECK_MARCH taps nothing; it exists so the loop can take one more frame
        # when an overlay hid the march counter.  It was selectable by the brain
        # but absent here, so every run that needed it died with
        # SKILL_NOT_ENABLED_FOR_LIVE_LOOP instead of retrying.  See
        # verify_march_count_readable for the measurement.
        "CHECK_MARCH": verify_march_count_readable,
        "DISPATCH_MARCH": verify_wood_dispatch_from_march,
        "SELECT_BEAST_TARGET": verify_beast_target_selected,
        "SCAN_MAP_FOR_BEAST": verify_beast_scan_observed,
        "BEAST_HUNT": verify_beast_march_open,
        "DISPATCH_BEAST": verify_beast_dispatch,
        "INTEL_CLAIM_REWARDS": verify_intel_claim_feedback,
        "SELECT_INTEL_BEAST_MISSION": verify_intel_mission_selected,
        "SELECT_INTEL_FIREBEAST_MISSION": verify_intel_mission_selected,
        "SELECT_INTEL_RESCUE_SURVIVORS": verify_intel_rescue_selected,
        "SELECT_INTEL_PIN": verify_intel_pin_opened,
        "OPEN_INTEL_RESCUE_SURVIVORS_TARGET": verify_intel_rescue_target_open,
        "EXECUTE_INTEL_RESCUE_SURVIVORS": verify_intel_rescue_started,
        "OPEN_MAIL": verify_open_mail,
        "OPEN_ALLIANCE": verify_open_alliance,
        "OPEN_EXPLORATION": verify_open_exploration,
        "SELECT_MAIL_ALLIANCE_TAB": verify_mail_alliance_tab_selected,
        "SELECT_DAILY_TAB": verify_daily_tab_selected,
        "SELECT_MAIL_SYSTEM_TAB": verify_mail_system_tab_selected,
        "SELECT_MAIL_REPORT_TAB": verify_mail_report_tab_selected,
        "MAIL_CLAIM_REWARDS": verify_mail_read_or_claim,
        "DISMISS_MAIL_REWARD": verify_mail_reward_dismissed,
        "DISMISS_MAIL_GENERIC_REWARD": verify_mail_reward_dismissed,
        "DISMISS_DAILY_GENERIC_REWARD": verify_daily_reward_advanced,
        "DISMISS_INTEL_GENERIC_REWARD": verify_intel_reward_dismissed,
        "DISMISS_EXPLORATION_GENERIC_REWARD": verify_exploration_reward_dismissed,
        "EXPLORATION_IDLE_CLAIM": verify_exploration_claim_feedback,
        "CONFIRM_EXPLORATION_IDLE_CLAIM": verify_exploration_claim_confirmed,
        "DISMISS_EXPLORATION_REWARD": verify_exploration_reward_dismissed,
        "OPEN_INTEL_BEAST_TARGET": verify_intel_target_open,
        "INTEL_BEAST_START_MARCH": verify_intel_beast_march_open,
        "DISPATCH_INTEL_BEAST": verify_intel_beast_dispatch,
        "BUILDING_UPGRADE": lambda before, after: verify_building_upgrade(before, after, str(before.building.get("id", ""))),
        "RESEARCH": lambda before, after: verify_research_started(before, after, str(before.research.get("node", ""))),
        "TRAIN_TROOPS": lambda before, after: verify_training_started(before, after, str(before.training.get("troop_type", ""))),
        "OPEN_POWER_OVERVIEW": verify_power_overview_open,
        "OPEN_POWER_DETAILS": verify_power_details_open,
        "NAVIGATE_INFANTRY_CAMP": verify_infantry_camp_highlighted,
        "SELECT_INFANTRY_CAMP": verify_infantry_camp_selected,
        # Stage A of the training route (#28): after the camp highlight the radial
        # menu is not drawn yet, and tapping the camp there moves the client to the
        # map.  This skill sends no input and is the only action the brain takes in
        # that state.
        "WAIT_FOR_CAMP_MENU": verify_camp_menu_reobserved,
        "OPEN_INFANTRY_TRAINING": verify_training_page_open,
        "NAVIGATE_RESEARCH_LAB": verify_research_lab_focused,
        "OPEN_RESEARCH": verify_research_page_open,
    }

    def __init__(
        self,
        *,
        device,
        vision,
        semantic_vision,
        capture_dir: Path,
        registry: SkillRegistry | None = None,
        brain: RuleBrain | None = None,
        settle_seconds: float = 1.5,
        environmental_wait_seconds: float = 120.0,
        max_relax_attempts: int = 3,
        max_scroll_attempts: int = 3,
        max_resource_switches: int = 2,
        max_stamina_refusals: int = 1,
        max_unknown_page_backs: int = 2,
        max_battle_reobservations: int = 3,
        observation_retries: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
        episode_store: EpisodeStore | None = None,
        goal_store: GoalStateStore | None = None,
        candidate_pool: CandidateAttemptPool | None = None,
        runtime_store: RuntimeSnapshotStore | None = None,
        resource_rotation: ResourceRotationStore | None = None,
        stamina_supply: StaminaSupplyStore | None = None,
        maa_adapter=None,
        adb_device=None,
        routing=None,
        backend_ledger: BackendLedger | None = None,
        capability_gate: CapabilityGate | None = None,
        code_revision: str = "",
    ) -> None:
        self.device = device
        # The ADB device behind the fallback executor.  When MAA observation is
        # enabled ``device`` is the MaaExecutorAdapter, so without this the ADB
        # path would be gone and "fall back to ADB" would silently mean "fall back
        # to MAA".
        self.adb_device = adb_device if adb_device is not None else device
        # Optional MAA backend.  ``None`` means the loop behaves exactly as it did
        # before this existed - the state every machine without MaaFramework is in.
        self.maa_adapter = maa_adapter
        self.routing = routing or RoutingTable.load()
        self.backend_ledger = backend_ledger or BackendLedger()
        self.vision = vision
        self.semantic_vision = semantic_vision
        self.capture_dir = capture_dir
        self.registry = registry or v2_registry()
        self.brain = brain or RuleBrain()
        self.settle_seconds = settle_seconds
        self.environmental_wait_seconds = environmental_wait_seconds
        self.max_relax_attempts = max_relax_attempts
        self.max_scroll_attempts = max_scroll_attempts
        self.max_resource_switches = max_resource_switches
        self.max_stamina_refusals = max_stamina_refusals
        self.max_unknown_page_backs = max_unknown_page_backs
        self.max_battle_reobservations = max_battle_reobservations
        self.observation_retries = observation_retries
        self.sleeper = sleeper
        self.episode_store = episode_store
        self.goal_store = goal_store
        self.goal_library = GoalLibrary()
        self.candidate_pool = candidate_pool
        self.runtime_store = runtime_store
        self.resource_rotation = resource_rotation
        # Learns when the free stamina gift becomes claimable, from the panel's
        # own 下次补给 countdown.  ``None`` keeps the historical behaviour: the
        # check runs once per run because the instant is unknown.
        self.stamina_supply = stamina_supply
        # Intel pins already tapped in THIS run.  Pins stay on the board after
        # their mission is consumed (claimed / marching), so without this the
        # loop would tap the same pin forever.  Session-scoped on purpose: the
        # board changes between runs, and a pin that produced nothing may be
        # workable later (the hourly harness re-runs from a cold start).
        self._tapped_intel_pins: list[tuple[int, int]] = []
        # Which goal paths must step aside, projected from the escalation ledger and
        # the episode stream.  Built once per run (see ``_gate``) and injectable, so a
        # test can drive the scheduler's input without touching the real ledger.
        self.capability_gate = capability_gate
        # True once this run has taken its one hop toward a page where more goals are
        # observable, so leaving cannot become a two-page ping-pong.
        self._replan_attempted = False
        # The tree revision this process imported.  Read once by the caller (one git
        # call per run) and stamped on every episode, so a later reconciliation can
        # tell an episode that ran the *new* code from one that ran the code the job
        # was about to replace.
        self.code_revision = str(code_revision)

    @property
    def _semantic(self):
        """The semantic-ROI vision, whichever object the caller handed over.

        ``tools/run_live.py`` passes ``SemanticWorldVision.semantic`` (the ROI
        helper) while other callers pass the world vision itself.  Reaching for
        ``self.semantic_vision.semantic`` unconditionally therefore raised
        ``AttributeError: 'SemanticROIVision' object has no attribute 'semantic'``
        on the first TAP_SEMANTIC skill, which aborted every live run before it
        could record a single step.  Resolving the accessor once here keeps both
        wirings working.
        """
        vision = self.semantic_vision
        return getattr(vision, "semantic", vision)

    def _sync_stamina_supply(self, world: WorldState) -> None:
        """Persist the free gift's next supply instant and hand it to the brain.

        The panel is the only place the countdown is visible, so the instant is
        learned whenever that panel is seen and kept in a small file for the runs
        in between (measured cadence: every 7 hours, while the unattended loop
        runs up to 8 cycles an hour -- see ``winter_agent_v2/stamina_supply``).

        A claimable panel has no countdown at all; that is not "unknown", it is
        "available now", and the claim clears it.  So this only ever records.
        """
        if self.stamina_supply is None:
            return
        countdown = world.stamina.get("next_supply_in_seconds")
        if isinstance(countdown, int):
            self.stamina_supply.record(countdown)
        self.brain.next_supply_at = self.stamina_supply.next_supply_at()

    def _policy_allows(self, goal_id: str) -> bool:
        category = {
            "CLEAR_INTEL": "日常低保", "AVOID_STAMINA_WASTE": "PVE",
            "KEEP_TRAINING_PRODUCTIVE": "持续发展", "KEEP_RESEARCH_PRODUCTIVE": "持续发展",
            "KEEP_BUILDING_PRODUCTIVE": "持续发展", "EVENT_MINIMUM_GUARANTEE": "限时活动",
            "PARTICIPATE_BEAR": "实时活动",
        }.get(goal_id, "日常低保" if goal_id.startswith("CLAIM_FREE_") else None)
        if category is None:
            return True
        try:
            payload = json.loads((Path(__file__).resolve().parents[1] / "config/policy_state.json").read_text(encoding="utf-8"))
            return bool(payload.get("goal_categories", {}).get(category, True))
        except (OSError, json.JSONDecodeError, TypeError):
            return True

    def _runtime(self, **changes) -> None:
        if self.runtime_store is not None:
            try:
                self.runtime_store.update(**changes)
            except (OSError, TypeError, ValueError):
                pass

    def _gate(self) -> CapabilityGate:
        """The deferral projection, built once per run from this project's evidence.

        Anchored on the episode store, because that is the artifact that proves this
        loop is the one producing evidence: ``learning/episodes.jsonl`` sits at the
        root of the tree whose ledger is worth reading.  A caller with no episode
        store has no production evidence, and gets a gate that defers nothing rather
        than one that reads a ledger belonging to someone else's project.
        """
        if self.capability_gate is None:
            if self.episode_store is None:
                self.capability_gate = CapabilityGate.empty()
            else:
                self.capability_gate = CapabilityGate.load(Path(self.episode_store.path).resolve().parents[1])
        return self.capability_gate

    def _selectable(self, goals, deferrals: list[Deferral]):
        """The operator's policy and the deferral gate, applied to discovered goals.

        This is the single gate in front of the single Scheduler.  A goal is offered
        only when its category is enabled *and* nothing has decided its path must step
        aside; the reasons are collected rather than logged away, because "why is AUTO
        not doing this" has to be answerable from the artifacts afterwards.
        """
        out = []
        for goal in goals:
            if not self._policy_allows(goal.goal_id):
                continue
            blocked = self._gate().blocks(goal)
            if blocked is not None:
                if all(item.goal_id != blocked.goal_id for item in deferrals):
                    deferrals.append(blocked)
                continue
            out.append(goal)
        return out

    def _deferral_replan(self, world: WorldState, deferrals: list[Deferral]) -> Decision | None:
        """One hop toward the page where more goals are observable.

        A deferred goal is not a reason to stand still, and the map is a page with
        exactly one goal on it (measured 2026-09-18: a live MAP frame discovers
        ``AVOID_STAMINA_WASTE`` and nothing else).  HOME is where the queue goals are
        readable -- 97 HOME frames in the recorded corpus read
        ``KEEP_TRAINING_PRODUCTIVE`` -- so the run takes the hop the project already
        trusts (``OPEN_HOME``, ``verify_open_home``, VERIFIED) instead of re-entering
        the path that just stepped aside.

        Bounded to once per run, refused on any page but MAP, and silent when the hop
        is not actually ready: this is a recovery, not a new route engine.
        """
        if not deferrals or self._replan_attempted or world.page is not Page.MAP:
            return None
        home = self.registry.get("OPEN_HOME")
        if home is None or not home.ready(world):
            return None
        self._replan_attempted = True
        stepped_aside = deferrals[0]
        return Decision(
            "OPEN_HOME",
            f"deferred_{stepped_aside.capability or stepped_aside.goal_id}_left_nothing_to_do_here",
            world.confidence,
            "home_opened",
        )

    def _record_goals(self, world: WorldState):
        """Discover this frame's goals, persist the board, and hand them back.

        Returning them is what makes goal progress measurable: the caller compares
        the goals read before a step with the goals read after it, which is the only
        way to tell "the action worked" from "the goal advanced".
        """
        goals = self.goal_library.discover(world)
        if self.goal_store is None:
            return goals
        try:
            self.goal_store.write(world, goals)
        except (OSError, TypeError, ValueError):
            pass
        return goals

    def _record_episode(
        self,
        *,
        decision: Decision,
        before: WorldState,
        execution: ExecutionResult | None,
        after: WorldState | None,
        verification: VerificationResult | None,
        started_at: float,
        step_id: int = 0,
        goal_id: str = "",
        goal_progress: bool | None = None,
        before_screenshot: Path | None = None,
        after_screenshot: Path | None = None,
    ) -> None:
        if self.episode_store is None:
            return
        failure = None
        if execution is None or not execution.executed:
            failure = execution.error if execution else "NO_EXECUTION"
        elif verification is not None and not verification.ok:
            failure = verification.reason
        episode = Episode(
            skill=decision.skill,
            state_before=asdict(before),
            action=asdict(execution.action) if execution is not None else {},
            state_after=asdict(after) if after is not None else {},
            result="SUCCESS" if failure is None else "FAILURE",
            failure_type=failure,
            duration=max(0.0, time.monotonic() - started_at),
            mode="PRODUCTION",
            # Locate the evidence.  Retention reads these paths so a referenced
            # frame is never pruned, and an auditor can follow one episode from
            # goal to skill to the two frames that prove the state change.
            episode_id=self.capture_dir.name,
            goal_id=goal_id,
            goal_progress=goal_progress,
            step_id=step_id,
            before_screenshot=str(before_screenshot) if before_screenshot else "",
            after_screenshot=str(after_screenshot) if after_screenshot else "",
            verifier_ok=None if verification is None else bool(verification.ok),
            # The real call chain for this step. Empty when nothing was issued
            # (resolution refused, dry run) - that distinction is what keeps
            # "MAA is in production" an evidence claim rather than a hope.
            executor_backend=_executor_label(execution),
            # The channel that produced THIS episode's before/after frames, i.e.
            # the observation device - not the executor's device.  With MAA
            # observation enabled those differ: the ADB executor stays wired to
            # the ADB device so the fallback can actually reach ADB, while every
            # evidence frame comes from MAA.  Reporting the executor's device here
            # would have labelled MAA-captured frames as ADB.
            #
            # Gated on the frames existing, NOT on the action having executed.
            # Those are different questions and conflating them was a measured
            # defect (WB-EXECUTOR-EVIDENCE-AUDIT, 2026-09-15): six failed
            # TAP_SEMANTIC steps whose target never resolved -- every one of them
            # with a real before frame on disk -- reported capture_backend="",
            # so the field that exists to say "which channel produced these
            # frames" said nothing, while empty also meant "no action ran".  The
            # field now answers its own question; whether the action reached a
            # backend is still reported, separately and correctly, by
            # executor_backend.
            capture_backend=(getattr(self.device, "capture_backend", "ADB_EXEC_OUT")
                             if (before_screenshot or after_screenshot) else ""),
            recognition_backend=execution.recognition_backend if execution is not None else "",
            action_backend=execution.backend if execution is not None else "",
            executor_latency_ms=execution.latency_ms if execution is not None else None,
            repo_revision=self.code_revision,
        )
        try:
            self.episode_store.append(episode)
        except (OSError, TypeError, ValueError):
            # Learning persistence must never cause an already-issued action to
            # be repeated. The run result remains authoritative for this turn.
            pass

    def _capture_path(self, index: int, stage: str, *, suffix: str = "") -> Path:
        """Build the canonical screenshot name for one step.

        Layout: ``{episode_id}/{episode_id}_{step_id}_{stage}[_{suffix}]_{timestamp}.png``

        ``capture_dir`` is the per-episode folder, whose name already is the
        episode id, so embedding it again keeps each file self-describing when
        it is copied out of its folder for evidence review. The trailing
        timestamp defeats mtime collisions when a run is replayed over an
        existing directory.
        """
        episode_id = self.capture_dir.name
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        tail = f"_{suffix}" if suffix else ""
        return self.capture_dir / f"{episode_id}_step_{index:03d}_{stage}{tail}_{stamp}.png"

    def run(
        self,
        *,
        max_actions: int = 10,
        allowed_skills: set[str] | None = None,
        stop_after_skill: str | None = None,
    ) -> LiveRun:
        if max_actions < 1:
            raise ValueError("max_actions must be positive")
        allowed = allowed_skills or set(self.VERIFIED_ATOMIC)
        steps: list[LiveStep] = []
        # Goals this run refused to select, and the reason.  One list for the whole
        # run so the end-of-run escalation hook reads the scheduler's own decision
        # instead of re-deriving it from the stop reason.
        deferrals: list[Deferral] = []
        gate = self._gate()

        def finish(reason: str) -> LiveRun:
            return LiveRun(tuple(steps), reason, tuple(item.as_row() for item in deferrals))

        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._relax_attempts = 0
        self._scroll_attempts = 0
        self._resource_switches = 0
        self._stamina_refusals = 0
        self._unknown_page_backs = 0
        # Run-scoped: set once a step verifies that a fight has just been
        # dispatched, cleared as soon as a known page is observed again, so it
        # cannot outlive the fight it was armed for.
        self._fight_resolving = False
        self._runtime(agent_state=AgentState.AUTO_RUNNING.value, runtime_thread_alive=True,
                      scheduler_loop_alive=True, last_fatal_error=None, stop_reason=None)

        for index in range(1, max_actions + 1):
            before_path = self._capture_path(index, "before")
            self.device.screenshot(before_path)
            before = self.vision.observe(before_path)
            # A known page means whatever owned the screen has finished, so the
            # fight-aware branch of the unknown-page recovery is no longer needed.
            # Cleared here rather than where the fight is dispatched because this
            # is the single point where the runtime looks at the screen again.
            if before.page not in {Page.UNKNOWN, Page.LOADING, Page.MAINTENANCE}:
                self._fight_resolving = False
            # Use the same frame and candidate list for planning and execution.
            # Exhausting this run's attempts is not an empty/complete board and
            # must not become a fabricated semantic-target failure (0ba).
            untried_intel_pins = []
            if before.page is Page.INTEL and not before.intel.get("mission_type"):
                detected_pins = intel_pin_centers(before_path)
                untried_intel_pins = [
                    pin for pin in detected_pins
                    if all((pin.x - tx) ** 2 + (pin.y - ty) ** 2 > 40 ** 2
                           for tx, ty in self._tapped_intel_pins)
                ]
                before = replace(before, intel={
                    **before.intel,
                    "untried_pins": len(untried_intel_pins),
                    "detected_pins": len(detected_pins),
                })
            self._sync_stamina_supply(before)
            planned_resource = self.resource_rotation.target(before.resources) if self.resource_rotation else "WOOD"
            if before.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                before = replace(before, resource_target=planned_resource)
            self._runtime(last_tick_time=datetime.now(timezone.utc).isoformat(),
                          page=before.page.value, confidence=before.confidence,
                          vision="READY" if before.known else "UNKNOWN", screenshot_path=str(before_path),
                          march_used=before.march_used, march_max=before.march_max,
                          queues={"building": before.building, "research": before.research, "training": before.training,
                                  "intel": before.intel, "alliance": before.alliance, "events": before.events})
            self._record_goals(before)
            goals = self.goal_library.discover(before)
            best_goal = self.goal_library.best(self._selectable(goals, deferrals))
            if deferrals:
                # Written every run, not only when it changes: the panel and the
                # escalation hook both read the current answer, and a stale one would
                # make "why is it doing that" unanswerable from outside.
                self._runtime(deferred_goals=[item.as_row() for item in deferrals])
                for item in deferrals:
                    print(f"[schedule] deferred {item.describe()}", flush=True)
            if self.brain.current_goal is None and best_goal is not None:
                self.brain.current_goal = {
                    "CLEAR_INTEL": "INTEL", "AVOID_STAMINA_WASTE": "BEAST_HUNT",
                    "KEEP_TRAINING_PRODUCTIVE": "TRAIN", "KEEP_RESEARCH_PRODUCTIVE": "RESEARCH",
                }.get(best_goal.goal_id)
            if before.page in {Page.MAINTENANCE, Page.LOADING}:
                # Environmental states resolve on the game's own schedule. The
                # worker must hold, not exit: an exit here was counted as an
                # unexpected worker exit and restarted the client, which then
                # hit the same splash again. Record one waiting step and sleep
                # a long, bounded interval before re-observing.
                decision = self.brain.decide(before, self.registry)
                self._runtime(agent_state=AgentState.IDLE.value,
                              current_goal=best_goal.goal_id if best_goal else (self.brain.current_goal or "AUTO_DISCOVERY"),
                              current_skill=decision.skill, reason=decision.reason,
                              next_action=decision.expected_result, confidence=decision.confidence)
                steps.append(LiveStep(index, decision, None, before, None, None))
                if index < max_actions:
                    self.sleeper(self.environmental_wait_seconds)
                continue
            # Parked on a leaf page with nothing left to do.
            #
            # Goal discovery reads the page the client is standing on, so a run
            # that ends on TRAINING/RESEARCH makes the next run see that page
            # again and nothing else.  Measured 2026-09-18: with the research
            # queue busy, every unattended cycle stopped by name on
            # ``research_queue_busy`` and took no action at all for twenty
            # minutes -- the loop was alive and doing nothing.  ``_leave_or_stop``
            # cannot help here: it only leaves for a *named* goal, because
            # turning a busy queue into a Back while other observations have real
            # work waiting would displace them (tests/test_multitask_scheduler.py).
            # The runtime is the only place that knows the difference: discovery
            # found no goal at all, so one Back off the leaf page (the hop
            # measured in ``_leave_terminal_page_once``, HOME from either page)
            # puts the board back in view without spending a step on anything.
            leave = None
            if (best_goal is None and self.brain.current_goal is None
                    and before.page in {Page.TRAINING, Page.RESEARCH}):
                leave = self.brain.leave_terminal_page(before)
            if leave is None:
                leave = self._deferral_replan(before, deferrals)
            decision = leave if leave is not None else self.brain.decide(before, self.registry)
            self._runtime(agent_state=AgentState.GOAL_RUNNING.value,
                          current_goal=best_goal.goal_id if best_goal else (self.brain.current_goal or "AUTO_DISCOVERY"),
                          current_skill=decision.skill, reason=decision.reason,
                          next_action=decision.expected_result, confidence=decision.confidence)
            if decision.skill == "SAFE_STOP":
                # MASTER_RULES 7: an unrecognised screen must not stop the run.
                # Live 2026-09-14: a Hero Journey mission card rendered in a skin
                # no template matched.  The brain honestly answered SAFE_STOP
                # unknown_page (content is not understood, so nothing is clicked -
                # pages.json keeps unknown_action=NO_CLICK), but the run then ended
                # and, with it, the whole intel pin loop - while a workable mission
                # sat on the screen.  A screen nobody understands is exactly where
                # unattended operation dies, so back out of it once and re-observe.
                #
                # Recovery is deliberately narrow and honest:
                # - only for unknown_page, and never for a fatal stop;
                # - the system Back key, which is what this project already trusts
                #   for a blocker it refuses to touch (see the real-money offer
                #   handling below) and which is a STABLE 97.6% skill here;
                # - bounded per run, so it cannot become a Back-loop;
                # - if the screen is still unknown afterwards the original reason
                #   is reported unchanged.  Recovery must not hide the root cause.
                recovered = False
                if decision.reason == "unknown_page" and not is_fatal_stop(decision.reason):
                    if self._fight_resolving:
                        # A fight was dispatched and its animation owns the screen.
                        # The system Back key is this project's trusted recovery for
                        # a blocker it refuses to touch, but a battle is different:
                        # the effect of Back on a live fight is UNMEASURED, and this
                        # order forbids manufacturing one to find out.  The one
                        # recorded battle frame (2026-09-15 15:14:46, judged
                        # Page.UNKNOWN at confidence 0.0 -- the page model genuinely
                        # cannot name it) shows the client clears the screen unaided:
                        # the next probe 38 s later reads HOME.  So wait and
                        # re-observe instead of pressing Back.  Bounded exactly like
                        # the Back loop, and if the screen is still unknown the
                        # original reason is reported unchanged -- recovery must not
                        # hide the root cause.
                        for _ in range(self.max_battle_reobservations):
                            self.sleeper(self.settle_seconds)
                            recovery_path = self._capture_path(index, "after", suffix="battle_wait")
                            self.device.screenshot(recovery_path)
                            before = self.vision.observe(recovery_path)
                            self._record_goals(before)
                            if before.page not in {Page.UNKNOWN, Page.LOADING, Page.MAINTENANCE}:
                                recovered = True
                                break
                    else:
                        while self._unknown_page_backs < self.max_unknown_page_backs:
                            self._unknown_page_backs += 1
                            self.device.press_back()
                            self.sleeper(self.settle_seconds)
                            recovery_path = self._capture_path(
                                index, "after", suffix=f"unknown_page_back_{self._unknown_page_backs}"
                            )
                            self.device.screenshot(recovery_path)
                            before = self.vision.observe(recovery_path)
                            self._record_goals(before)
                            if before.page not in {Page.UNKNOWN, Page.LOADING, Page.MAINTENANCE}:
                                recovered = True
                                break
                    if recovered:
                        self._fight_resolving = False
                        continue
                steps.append(LiveStep(index, decision, None, before, None, None))
                self._runtime(agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(decision.reason) else AgentState.DEGRADED.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=decision.reason,
                              last_fatal_error=decision.reason if is_fatal_stop(decision.reason) else None)
                return finish(decision.reason)
            if decision.skill not in allowed or decision.skill not in self.VERIFIED_ATOMIC:
                steps.append(LiveStep(index, decision, None, before, None, None))
                return finish("SKILL_NOT_ENABLED_FOR_LIVE_LOOP")

            def resolve(semantic: str):
                if semantic == "RESOURCE_DYNAMIC":
                    # The strip scrolls, so the tap target is derived from the
                    # bracket anchor observed on the current frame (see
                    # SemanticROIVision.resource_cell_center_norm).  The previous
                    # hand-typed centres were only valid for one scroll offset and
                    # selected the wrong tab on live frames.  ``None`` means the
                    # cell is off-screen: the loop scrolls the strip instead of
                    # guessing a coordinate.
                    return self._semantic.resource_cell_center_norm(planned_resource)
                if semantic == "HUD_STAMINA_GAUGE":
                    # The gauge is drawn at a measured spot on every map frame.
                    # The page check is what keeps a popup or a loading screen
                    # from absorbing the tap.
                    #
                    # It used to *also* require ``stamina.current is not None``,
                    # i.e. that the number had been read.  Measured 2026-09-15:
                    # the two MAP frames in the recorded corpus whose gauge
                    # could not be read are both genuine ``0`` readings -- the
                    # pill is drawn and plainly shows 0
                    # (dataset/probe_output/map_gauge_unreadable/) -- and the
                    # OCR cannot read a lone 0 at any padding or scale (best
                    # confidence 0.73, and it flips between '0' and 'O'; see
                    # tools/probe_stamina_zero.py).  So that condition did not
                    # test "the gauge is there", it tested "the gauge is not
                    # empty", and it disabled the free-stamina check exactly
                    # when stamina was 0 -- the moment the free gift matters
                    # most.  The tap target is the pill's own centre either way.
                    if before.page.value != "MAP" or before.resource_search_open:
                        return None
                    return self._semantic.stamina_gauge_center
                if semantic == "MARCH_ROW_1":
                    # The march list is a fixed-pitch row list under the HUD, not
                    # a template: the row artwork changes with mission type and
                    # the list reflows.  Refuse when the list cannot be believed
                    # to be visible, because tapping row 1 on a frame without an
                    # active march would tap the bare map.
                    if before.page.value != "MAP" or before.resource_search_open:
                        return None
                    if before.march_used is None or before.march_used < 1:
                        return None
                    return self._semantic.march_row_1_center
                if semantic == "RESOURCE_LEVEL_MINUS":
                    # The level filter is a measured slider row, not a
                    # template: the minus control sits at a calibrated centre
                    # whose value was read live across every level 8 -> 1.
                    if not before.resource_search_open:
                        return None
                    return self._semantic.resource_level_minus
                if semantic == "INTEL_PIN":
                    # The intel board is a pin map, so the tap target is a
                    # *detected pin* rather than a template: the mission card
                    # that names the mission type does not exist until a pin is
                    # tapped.  Pins already tried in this run are skipped,
                    # because a pin stays on the board after its mission is
                    # consumed; when none is left the resolver refuses instead
                    # of re-tapping one, so the run ends honestly rather than
                    # looping on a consumed pin.
                    if before.page.value != "INTEL":
                        return None
                    status = self.device.status()
                    if not status.connected or status.resolution is None:
                        return None
                    width, height = status.resolution
                    if untried_intel_pins:
                        pin = untried_intel_pins.pop(0)
                        self._tapped_intel_pins.append((pin.x, pin.y))
                        return (pin.x / width, pin.y / height)
                    return None
                match = self._semantic.find(before_path, semantic)
                if match:
                    return match.center_norm
                # The Exploration chest is animated and its perceptual hash
                # varies between frames. A reviewed normalized fallback is
                # allowed only after independent page + green-state proof.
                if semantic == "BTN_EXPLORATION_IDLE_CLAIM" and before.page.value == "EXPLORATION" and before.exploration.get("status") == "CLAIMABLE":
                    return (0.86, 0.68)
                return None

            if (
                decision.skill == "SELECT_RESOURCE"
                and self._semantic.resource_tab_offset is not None
                and self._semantic.resource_cell_center_norm(planned_resource) is None
                and self._scroll_attempts < self.max_scroll_attempts
            ):
                # The requested resource tab is outside the visible strip (WOOD,
                # COAL and IRON sit past the right edge at the default offset).
                # Scroll it into view and re-observe on the next iteration; no
                # click is issued for a target whose position is unknown.
                delta = self._semantic.resource_tab_swipe_for(planned_resource)
                if delta:
                    self._scroll_attempts += 1
                    band_y = (self._semantic.resource_tab_band[0]
                              + self._semantic.resource_tab_band[1]) / 2
                    status = self.device.status()
                    if status.connected and status.resolution is not None:
                        width, height = status.resolution
                        # Dragging towards the negative delta moves content the
                        # opposite way, which reveals the tabs that are off-screen.
                        self.device.swipe(
                            round(0.60 * width), round(band_y * height),
                            round(0.60 * width + delta), round(band_y * height),
                            300,
                        )
                        self.sleeper(self.settle_seconds)
                        steps.append(LiveStep(index, decision, None, before, None, None))
                        self._runtime(
                            agent_state=AgentState.AUTO_RUNNING.value,
                            reason=f"scroll_resource_strip_to_{planned_resource}",
                            next_action="reevaluate_after_scroll",
                            verifier="PENDING",
                        )
                        continue
            adb_executor = Executor(
                production=True,
                dry_run=False,
                device=self.adb_device,
                target_resolver=resolve,
                backend="ADB",
            )
            # One executor boundary, one router decision per step.  With no MAA
            # adapter attached this returns ``adb_executor`` unchanged.
            executor = build_router(
                adb_executor=adb_executor,
                adb_resolver=resolve,
                maa_adapter=self.maa_adapter,
                skill_id=decision.skill,
                routing=self.routing,
                ledger=self.backend_ledger,
            )
            started_at = time.monotonic()
            # ``decision`` was already made above and the backend router below
            # was built from it, so it is handed to the scheduler rather than
            # recomputed.  ``RuleBrain.decide`` mutates run-scoped state (the
            # free-stamina once-per-run flag), so a second call for the same
            # frame answers differently and the verifier then judges a skill the
            # step never ran.  See ``Scheduler.tick`` for the live evidence.
            tick = Scheduler(self.brain, self.registry, executor, self.candidate_pool).tick(before, decision)
            self._runtime(last_action_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
            if tick.execution is None or not tick.execution.executed:
                self._record_episode(
                    decision=tick.decision, before=before, execution=tick.execution,
                    after=None, verification=None, started_at=started_at,
                    step_id=index,
                    goal_id=best_goal.goal_id if best_goal else (self.brain.current_goal or "AUTO_DISCOVERY"),
                    before_screenshot=before_path,
                )
                steps.append(LiveStep(index, tick.decision, tick.execution, before, None, None))
                reason = tick.execution.error if tick.execution else "NO_EXECUTION"
                self._runtime(agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(reason) else AgentState.DEGRADED.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=reason,
                              last_fatal_error=reason if is_fatal_stop(reason) else None)
                return finish(tick.execution.error if tick.execution else "NO_EXECUTION")

            self.sleeper(self.settle_seconds)
            after_path = self._capture_path(index, "after")
            self.device.screenshot(after_path)
            after = self.vision.observe(after_path)
            if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                after = replace(after, resource_target=planned_resource)
            # Some successful game actions are followed by a promotional
            # real-money offer. Never touch the purchase surface. A single
            # system Back is the only allowed recovery, after which the
            # original action verifier evaluates the real underlying state.
            for offer_recovery in range(1, 3):
                if after.page.value != "POPUP" or after.popup not in {"REAL_MONEY_OFFER", "PURCHASE_POPUP"}:
                    break
                self.device.press_back()
                self.sleeper(self.settle_seconds)
                recovery_path = self._capture_path(index, "after", suffix=f"payment_offer_closed_{offer_recovery}")
                self.device.screenshot(recovery_path)
                after = self.vision.observe(recovery_path)
                if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                    after = replace(after, resource_target=planned_resource)
                after_path = recovery_path
            goals_after = self._record_goals(after)
            verification = self.VERIFIED_ATOMIC[decision.skill](before, after)
            for refresh in range(1, self.observation_retries + 1):
                # A known page can still be an intermediate animation/frame.
                # Re-observe when the action-specific verifier is not yet
                # satisfied, but never repeat the click whose result is merely
                # delayed. This handles slow MAP -> RESOURCE_DETAIL transitions.
                if verification.ok:
                    break
                self.sleeper(self.settle_seconds)
                refresh_path = self._capture_path(index, "after", suffix=f"refresh_{refresh}")
                self.device.screenshot(refresh_path)
                after = self.vision.observe(refresh_path)
                if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                    after = replace(after, resource_target=planned_resource)
                goals_after = self._record_goals(after)
                verification = self.VERIFIED_ATOMIC[decision.skill](before, after)
                # The episode must point at the frame its recorded ``after``
                # state was actually read from.  ``after_path`` used to stay on
                # the first post-action frame, so a step whose refreshes changed
                # the reading recorded one picture and described another --
                # the escalated NAVIGATE_TO_MAP episode showed an unchanged HOME
                # screenshot next to ``after.page == UNKNOWN``, which was read
                # from ``..._after_refresh_2_...png``.  An audit of that episode
                # cannot be done from the picture it names, and that is what made
                # the escalation read as "V2 saw something it could not read"
                # with nothing to look at.
                after_path = refresh_path
            step_goal = best_goal.goal_id if best_goal else (self.brain.current_goal or "AUTO_DISCOVERY")
            self._record_episode(
                decision=tick.decision, before=before, execution=tick.execution,
                after=after, verification=verification, started_at=started_at,
                step_id=index,
                goal_id=step_goal,
                # The verifier passed means the action landed.  This says whether the
                # *goal* moved, and the two are not the same statement: 58 episodes
                # passed their verifier while stamina sat at 457 (2026-09-18).
                goal_progress=progress_moved(goals, goals_after, step_goal),
                before_screenshot=before_path, after_screenshot=after_path,
            )
            steps.append(LiveStep(index, tick.decision, tick.execution, before, after, verification))
            # Arm the fight-aware recovery.  The verifier is the evidence, not the
            # skill name: a step that verified "a fight has been dispatched" is the
            # only one after which a battle animation can legitimately be owning the
            # screen.  Arming is run-scoped and is cleared as soon as a known page is
            # observed, so it can never outlive the fight it was armed for.
            if verification.ok:
                _skill = self.registry.get(decision.skill)
                if _skill is not None and _skill.verifier in self.FIGHT_STARTING_VERIFIERS:
                    self._fight_resolving = True
            if (
                not verification.ok
                and decision.skill == "SUBMIT_RESOURCE_SEARCH"
                and verification.reason == "RESOURCE_NOT_FOUND"
                and before.resource_level is not None
                and before.resource_level > 1
                and self._relax_attempts < self.max_relax_attempts
            ):
                # The query came back empty at the current level filter. That is
                # the positive signal for an exhausted search, and it is
                # observable without a toast template (the toast is transient
                # and no live frame captured it). Loosen one step and retry in
                # the same run instead of returning a failure the operator has
                # to restart by hand.
                self._relax_attempts += 1
                self._runtime(
                    agent_state=AgentState.AUTO_RUNNING.value,
                    reason=f"resource_search_exhausted_at_level_{before.resource_level}",
                    next_action="relax_resource_level_and_research",
                    verifier=verification.reason,
                )
                continue
            if (
                not verification.ok
                and decision.skill == "SUBMIT_RESOURCE_SEARCH"
                and verification.reason == "RESOURCE_NOT_FOUND"
                and self.resource_rotation is not None
                and self._resource_switches < self.max_resource_switches
            ):
                # The level filter is already at its minimum (measured live: 1..8),
                # so there is nothing left to relax — the client is telling us there
                # is no eligible node of *this* resource in range right now.
                # Treating that as a hard failure made the whole goal stall: the
                # rotation only advanced on a successful dispatch, so it asked for
                # the same unavailable resource forever.  Mark it unavailable and
                # let the next iteration pick a different one, in the same run.
                self._resource_switches += 1
                self.resource_rotation.unavailable(planned_resource)
                self._runtime(
                    agent_state=AgentState.AUTO_RUNNING.value,
                    reason=f"resource_{planned_resource}_has_no_node_in_range",
                    next_action="switch_to_another_resource",
                    verifier=verification.reason,
                )
                continue
            if (
                not verification.ok
                and decision.skill == "INTEL_HERO_START_MARCH"
                and verification.reason == "INTEL_HERO_MARCH_REFUSED_FOR_STAMINA"
                and self._stamina_refusals < self.max_stamina_refusals
            ):
                # The client refused the camp fight and opened 获取更多 instead.
                # Measured live 2026-09-15T03:51:37Z: the camp panel's stamina
                # ROI read nothing on that frame (the gauge digit had drifted
                # left of HUD_STAMINA_ROI; 19 of 25 corpus frames read, and the
                # whole-frame fallback rescues 0 of the misses), so
                # RuleBrain's predictive affordability gate could not fire and
                # the tap went out anyway.  Because runtime returns on the first
                # failed verification, that ended a run which was one step away
                # from the free-stamina check.
                #
                # A wider ROI was measured and rejected: it lifted readability
                # to 25/26 but returned *different* numbers on 6 frames
                # (18->188, 36->136, and a known 9 read as 6) by catching
                # adjacent glyphs.  A wrong reading is worse than none here --
                # it would mis-authorise spending -- so the read is left
                # conservative and the refusal is treated as what it actually
                # is: the client's own affordability verdict, which needs no OCR.
                #
                # Recoverable rather than fatal, exactly like the two
                # RESOURCE_NOT_FOUND branches above: record the verdict on the
                # brain (so the next sight of this panel routes to the free
                # stamina instead of tapping again) and continue.  The runtime
                # presses nothing itself -- the refusal leaves
                # POPUP/GET_MORE_STAMINA on screen and RuleBrain already decides
                # that popup (claim the free gift if it is there, otherwise Back
                # to the map).  Bounded to one per run so a genuinely stuck
                # client still ends the run honestly.
                self._stamina_refusals += 1
                self.brain.camp_panel_refused = True
                self._runtime(
                    agent_state=AgentState.AUTO_RUNNING.value,
                    reason="camp_fight_refused_by_the_client_for_stamina",
                    next_action="claim_free_stamina_else_back_to_map",
                    verifier=verification.reason,
                )
                continue
            self._runtime(verifier="PASS" if verification.ok else verification.reason,
                          last_success_time=(datetime.now(timezone.utc).isoformat() if verification.ok else None),
                          page=after.page.value, confidence=after.confidence, screenshot_path=str(after_path),
                          march_used=after.march_used, march_max=after.march_max,
                          queues={"building": after.building, "research": after.research, "training": after.training,
                                  "intel": after.intel, "alliance": after.alliance, "events": after.events})
            if not verification.ok:
                self._runtime(agent_state=AgentState.DEGRADED.value, runtime_thread_alive=False,
                              scheduler_loop_alive=False, stop_reason=verification.reason)
                return finish(verification.reason)
            if decision.skill == "DISPATCH_MARCH" and self.resource_rotation is not None:
                self.resource_rotation.completed(planned_resource)
            if decision.skill == stop_after_skill:
                self._runtime(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                              scheduler_loop_alive=False, stop_reason="TARGET_SKILL_VERIFIED")
                return finish("TARGET_SKILL_VERIFIED")

        self._runtime(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                      scheduler_loop_alive=False, stop_reason="MAX_ACTIONS_REACHED")
        return finish("MAX_ACTIONS_REACHED")
