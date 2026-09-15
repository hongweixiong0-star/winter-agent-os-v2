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
from .goal_library import GoalLibrary, GoalStateStore
from .candidate_policy import CandidateAttemptPool
from .skills import SkillRegistry, v2_registry
from .verifier import verify_alliance_reward_dismissed, verify_ally_gift_claim_feedback, verify_intel_hero_dispatched, verify_intel_hero_march_open, verify_intel_hero_target_open, verify_daily_claim_feedback, verify_daily_reward_advanced, verify_exploration_claim_confirmed, verify_exploration_claim_feedback, verify_exploration_reward_dismissed, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_mail_read_or_claim, verify_offline_rewards_claimed, verify_open_alliance, verify_open_alliance_gifts, verify_open_daily, verify_open_exploration, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_intel_list_read
from .verifier import verify_ally_gift_claim, verify_beast_dispatch, verify_beast_march_open, verify_beast_target_selected, verify_building_upgrade, verify_duplicate_target_cancelled, verify_environmental_wait, verify_intel_beast_dispatch, verify_intel_beast_march_open, verify_intel_claim_feedback, verify_intel_mission_selected, verify_intel_pin_opened, verify_intel_rescue_selected, verify_intel_rescue_started, verify_intel_rescue_target_open, verify_intel_reward_dismissed, verify_intel_target_open, verify_mail_alliance_tab_selected, verify_mail_claim_feedback, verify_mail_report_tab_selected, verify_mail_reward_dismissed, verify_mail_system_tab_selected, verify_march_page_open, verify_march_recall_dialog_open, verify_march_recalled, verify_open_home, verify_open_intel, verify_open_mail, verify_open_map, verify_popup_closed, verify_research_started, verify_resource_found, verify_resource_level_relaxed, verify_resource_search_open, verify_resource_selected, verify_free_stamina_claimed, verify_safe_back, verify_stamina_sources_open, verify_training_started, verify_wood_dispatch_from_march
from .runtime_snapshot import AgentState, RuntimeSnapshotStore, is_fatal_stop
from .resource_rotation import ResourceRotationStore
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
        "DISPATCH_MARCH": verify_wood_dispatch_from_march,
        "SELECT_BEAST_TARGET": verify_beast_target_selected,
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
        "OPEN_INFANTRY_TRAINING": verify_training_page_open,
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
        max_unknown_page_backs: int = 2,
        observation_retries: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
        episode_store: EpisodeStore | None = None,
        goal_store: GoalStateStore | None = None,
        candidate_pool: CandidateAttemptPool | None = None,
        runtime_store: RuntimeSnapshotStore | None = None,
        resource_rotation: ResourceRotationStore | None = None,
        maa_adapter=None,
        adb_device=None,
        routing=None,
        backend_ledger: BackendLedger | None = None,
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
        self.max_unknown_page_backs = max_unknown_page_backs
        self.observation_retries = observation_retries
        self.sleeper = sleeper
        self.episode_store = episode_store
        self.goal_store = goal_store
        self.goal_library = GoalLibrary()
        self.candidate_pool = candidate_pool
        self.runtime_store = runtime_store
        self.resource_rotation = resource_rotation
        # Intel pins already tapped in THIS run.  Pins stay on the board after
        # their mission is consumed (claimed / marching), so without this the
        # loop would tap the same pin forever.  Session-scoped on purpose: the
        # board changes between runs, and a pin that produced nothing may be
        # workable later (the hourly harness re-runs from a cold start).
        self._tapped_intel_pins: list[tuple[int, int]] = []

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

    def _record_goals(self, world: WorldState) -> None:
        if self.goal_store is None:
            return
        try:
            self.goal_store.write(world, self.goal_library.discover(world))
        except (OSError, TypeError, ValueError):
            pass

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
            capture_backend=(getattr(self.device, "capture_backend", "ADB_EXEC_OUT")
                             if execution is not None and execution.executed else ""),
            recognition_backend=execution.recognition_backend if execution is not None else "",
            action_backend=execution.backend if execution is not None else "",
            executor_latency_ms=execution.latency_ms if execution is not None else None,
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
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._relax_attempts = 0
        self._scroll_attempts = 0
        self._resource_switches = 0
        self._unknown_page_backs = 0
        self._runtime(agent_state=AgentState.AUTO_RUNNING.value, runtime_thread_alive=True,
                      scheduler_loop_alive=True, last_fatal_error=None, stop_reason=None)

        for index in range(1, max_actions + 1):
            before_path = self._capture_path(index, "before")
            self.device.screenshot(before_path)
            before = self.vision.observe(before_path)
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
            best_goal = self.goal_library.best(goal for goal in goals if self._policy_allows(goal.goal_id))
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
            decision = self.brain.decide(before, self.registry)
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
                        continue
                steps.append(LiveStep(index, decision, None, before, None, None))
                self._runtime(agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(decision.reason) else AgentState.DEGRADED.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=decision.reason,
                              last_fatal_error=decision.reason if is_fatal_stop(decision.reason) else None)
                return LiveRun(tuple(steps), decision.reason)
            if decision.skill not in allowed or decision.skill not in self.VERIFIED_ATOMIC:
                steps.append(LiveStep(index, decision, None, before, None, None))
                return LiveRun(tuple(steps), "SKILL_NOT_ENABLED_FOR_LIVE_LOOP")

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
                    # Refuse unless the gauge was actually read on this frame, so
                    # a popup or a loading screen can never absorb the tap.
                    if before.page.value != "MAP" or before.resource_search_open:
                        return None
                    if before.stamina.get("current") is None:
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
                    for pin in intel_pin_centers(before_path):
                        if all((pin.x - tx) ** 2 + (pin.y - ty) ** 2 > 40 ** 2
                               for tx, ty in self._tapped_intel_pins):
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
            tick = Scheduler(self.brain, self.registry, executor, self.candidate_pool).tick(before)
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
                return LiveRun(tuple(steps), tick.execution.error if tick.execution else "NO_EXECUTION")

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
            self._record_goals(after)
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
                self._record_goals(after)
                verification = self.VERIFIED_ATOMIC[decision.skill](before, after)
            self._record_episode(
                decision=tick.decision, before=before, execution=tick.execution,
                after=after, verification=verification, started_at=started_at,
                step_id=index,
                goal_id=best_goal.goal_id if best_goal else (self.brain.current_goal or "AUTO_DISCOVERY"),
                before_screenshot=before_path, after_screenshot=after_path,
            )
            steps.append(LiveStep(index, tick.decision, tick.execution, before, after, verification))
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
            self._runtime(verifier="PASS" if verification.ok else verification.reason,
                          last_success_time=(datetime.now(timezone.utc).isoformat() if verification.ok else None),
                          page=after.page.value, confidence=after.confidence, screenshot_path=str(after_path),
                          march_used=after.march_used, march_max=after.march_max,
                          queues={"building": after.building, "research": after.research, "training": after.training,
                                  "intel": after.intel, "alliance": after.alliance, "events": after.events})
            if not verification.ok:
                self._runtime(agent_state=AgentState.DEGRADED.value, runtime_thread_alive=False,
                              scheduler_loop_alive=False, stop_reason=verification.reason)
                return LiveRun(tuple(steps), verification.reason)
            if decision.skill == "DISPATCH_MARCH" and self.resource_rotation is not None:
                self.resource_rotation.completed(planned_resource)
            if decision.skill == stop_after_skill:
                self._runtime(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                              scheduler_loop_alive=False, stop_reason="TARGET_SKILL_VERIFIED")
                return LiveRun(tuple(steps), "TARGET_SKILL_VERIFIED")

        self._runtime(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                      scheduler_loop_alive=False, stop_reason="MAX_ACTIONS_REACHED")
        return LiveRun(tuple(steps), "MAX_ACTIONS_REACHED")
