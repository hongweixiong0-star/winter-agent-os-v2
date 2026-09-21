from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from typing import Any, Callable, Mapping

from .brain import RuleBrain
from . import control_experience
from . import goal_utility
from .executor import Executor
from .executor_router import BackendLedger, RoutingTable, build_router
from .learning import Episode, EpisodeStore
from .models import Decision, ExecutionResult, Page, VerificationResult, WorldState
from .scheduler import Scheduler
from .goal_library import GoalLibrary, GoalStateStore, progress_moved, route_for
from .capability_gate import DEFERRED, CapabilityGate, Deferral
from .device_lease import OWNER_DEVELOPMENT_VALIDATION, OWNER_GAMEPLAY, DeviceLease
from .candidate_policy import CandidateAttemptPool
from .skills import SkillRegistry, v2_registry
from .verifier import verify_alliance_reward_dismissed, verify_ally_gift_claim_feedback, verify_intel_hero_dispatched, verify_intel_hero_march_open, verify_intel_hero_target_open, verify_daily_claim_feedback, verify_daily_reward_advanced, verify_daily_tab_selected, verify_exploration_claim_confirmed, verify_exploration_claim_feedback, verify_exploration_reward_dismissed, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_mail_read_or_claim, verify_offline_rewards_claimed, verify_open_alliance, verify_open_alliance_gifts, verify_open_daily, verify_open_exploration, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_intel_list_read, verify_alliance_gifts_claimed
from .verifier import verify_ally_gift_claim, verify_beast_card_march_open, verify_beast_card_opened, verify_beast_dispatch, verify_beast_mammoth_target_selected, verify_beast_march_open, verify_beast_scan_observed, verify_beast_search_submitted, verify_beast_search_tab_selected, verify_beast_target_selected, verify_building_upgrade, verify_camp_menu_reobserved, verify_duplicate_target_cancelled, verify_environmental_wait, verify_intel_beast_dispatch, verify_intel_beast_march_open, verify_intel_claim_feedback, verify_intel_mission_selected, verify_intel_pin_opened, verify_intel_rescue_selected, verify_intel_rescue_started, verify_intel_rescue_target_open, verify_intel_reward_dismissed, verify_intel_target_open, verify_left_foreign_layer, verify_mail_alliance_tab_selected, verify_mail_claim_feedback, verify_mail_report_tab_selected, verify_mail_reward_dismissed, verify_mail_system_tab_selected, verify_march_count_readable, verify_march_page_open, verify_march_recall_dialog_open, verify_march_recalled, verify_open_home, verify_open_intel, verify_open_mail, verify_open_map, verify_popup_closed, verify_research_lab_focused, verify_research_page_open, verify_research_started, verify_resource_found, verify_resource_level_relaxed, verify_resource_search_open, verify_resource_selected, verify_free_stamina_claimed, verify_safe_back, verify_stamina_sources_open, verify_training_started, verify_wood_dispatch_from_march
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


#: Failures that belong to the DEVICE, not to any goal.
#:
#: The distinction is the operator's, and it is not cosmetic.  Every reason in
#: ``NON_FATAL_STOPS`` is a statement about ONE goal -- "this queue is busy", "this panel
#: has nothing to collect" -- and the runtime answers those by handing the cycle to the
#: next goal.  A device that has gone away says nothing about any goal: the adb endpoint
#: dropped, MuMu was closed, the emulator is restarting.  Handing THAT to the next goal
#: produces a run that walks goal to goal issuing nothing while the real problem sits
#: unchanged underneath, and then reports each goal as merely blocked.
#:
#: These markers are the exact strings ``device.py`` raises (``ADB_FAILED:``,
#: ``DEVICE_NOT_CONNECTED``, ``DEVICE_AMBIGUOUS``, ``ADB_DISCOVERY_FAILED``) plus the
#: screenshot failures a half-dead transport produces.  They are matched case-sensitively
#: as substrings because the devices layer carries its own return codes in the message.
#:
#: The response is a separate state, not a longer yield list: the run ends as
#: ``RECOVERING`` with the device's own reason, the GUI's existing classifier already
#: reads that as ENVIRONMENT (so it restarts the watchdog without counting a worker crash),
#: and the next cycle re-runs ``_ensure_device`` against a client that has had time to come
#: back.  See ``_device_gone``.
DEVICE_FAILURE_MARKERS = (
    "DEVICE_NOT_CONNECTED", "DEVICE_AMBIGUOUS", "ADB_DISCOVERY_FAILED", "ADB_FAILED",
    "SCREENSHOT_NOT_PNG", "SCREENSHOT_DAMAGED",
    "device offline", "device unauthorized", "no devices/emulators found",
)


def _device_gone(exc: BaseException) -> bool:
    """Is this exception the device leaving, rather than a goal declining to act?"""
    text = str(exc)
    return any(marker in text for marker in DEVICE_FAILURE_MARKERS)


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

    #: The skills whose job is to leave a page the current goal does not own.  A failed
    #: verification from one of these is the first half of a two-step exit rather than a
    #: dead end, because the brain answers the layer's own second exit on the next step.
    #: See the branch that reads it for the measured frame.
    LEAVING_SKILLS = frozenset({"BACK", "LEAVE_FOREIGN_LAYER"})

    VERIFIED_ATOMIC: dict[str, Verifier] = {
        "WAIT": verify_environmental_wait,
        "CLOSE_POPUP": verify_popup_closed,
        "LEAVE_FOREIGN_LAYER": verify_left_foreign_layer,
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
        # The goal-neutral close of the same dialog, for goals that cannot name
        # the page it covers.  It reuses verify_popup_closed deliberately: the
        # proof that has to hold is "the dialog is gone", not "a particular page
        # came back", because the dialog covers whichever page was underneath.
        # Without this entry the skill would never be dispatched, which is the
        # failure mode #45 already recorded for another capability.
        "DISMISS_SHARED_REWARD": verify_popup_closed,
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
        "SELECT_BEAST_TARGET_MAMMOTH": verify_beast_mammoth_target_selected,
        # The species-agnostic twin.  A skill with no entry here is never dispatched,
        # and this one has to be dispatchable or the labelled-beast hop is dead code
        # (the failure mode #45 already recorded).
        "SELECT_BEAST_TARGET_LABELLED": verify_beast_card_opened,
        "SCAN_MAP_FOR_BEAST": verify_beast_scan_observed,
        # The client's own beast search.  A skill with no entry here is never
        # dispatched, so leaving these two out would make the whole search route
        # dead code while every test still passed (the failure mode #45 records).
        "OPEN_BEAST_SEARCH_TAB": verify_beast_search_tab_selected,
        "SUBMIT_BEAST_SEARCH": verify_beast_search_submitted,
        "ATTACK_BEAST_CARD": verify_beast_card_march_open,
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
        # One per run above the pair's own bound of two, so the second exit is always
        # reachable but a layer that answers neither exit still ends the run.
        max_leave_retries: int = 2,
        max_unknown_page_backs: int = 2,
        # How many times one run may hand the cycle to another task after a step
        # failed its verifier (operator §二.5).  Small on purpose: this exists so a
        # single failed step stops taking the whole run with it, not so a run can
        # grind through every goal it has.
        max_verification_retries: int = 2,
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
        role_id: str = "",
        role_scope: str = "",
        device_lease: DeviceLease | None = None,
        execution_mode: str = "PRODUCTION",
        trace_id: str = "",
        job_id: str = "",
        capability: str = "",
        expected_after_version: str = "",
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
        # The goal this run has already committed to.  See ``_step_goal``: it is the
        # label an episode gets for a step taken on a page whose own discovery finds
        # no goal at all, which is the case on every step of the gather route after
        # the search result opens.
        self._committed_goal = ""
        self.settle_seconds = settle_seconds
        self.environmental_wait_seconds = environmental_wait_seconds
        self.max_relax_attempts = max_relax_attempts
        self.max_scroll_attempts = max_scroll_attempts
        self.max_resource_switches = max_resource_switches
        self.max_stamina_refusals = max_stamina_refusals
        self.max_leave_retries = max_leave_retries
        self.max_unknown_page_backs = max_unknown_page_backs
        self.max_verification_retries = max_verification_retries
        self.max_battle_reobservations = max_battle_reobservations
        self.observation_retries = observation_retries
        self.sleeper = sleeper
        #: Set by ``_device_lost`` when the transport dies mid-run, and read by the
        #: ``return finish(self._device_stop_reason)`` that follows it.  A placeholder rather
        #: than only being written on failure: a guard that can raise AttributeError on its
        #: own failure path is not a guard, and the attribute has to exist from construction
        #: so the value is also readable by anyone inspecting a run that never lost its device.
        self._device_stop_reason = "DEVICE_NOT_CONNECTED"
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
        # Which account this run's episodes belong to, read once by the caller from the
        # persisted role artifact (one small file per run, the same shape as
        # ``code_revision``).  ``""`` means the role was never read off the client, and it
        # stays empty rather than being filled with a configured or default name -- the
        # whole point is that an unscoped metric must be *visible* as unscoped, because
        # the corpus was already pooled from two accounts without anyone noticing.
        self.role_id = str(role_id or "")
        self.role_scope = str(role_scope or "")
        # Which kind of cycle this is, and -- for a Development Validation cycle -- the trace
        # it is examining (operator §2).  Stamped on every episode this runtime writes, because
        # the operator's §8 rule is that a validation episode must never be readable as
        # production reuse: the distinction has to survive on the row, not in the caller's
        # intentions.  ``PRODUCTION`` is the default, which is what an AUTO cycle is.
        self.execution_mode = str(execution_mode or "PRODUCTION")
        self.trace_id = str(trace_id or "")
        self.job_id = str(job_id or "")
        self.capability = str(capability or "")
        self.expected_after_version = str(expected_after_version or "")
        # The single-UI-owner lock (operator §8/§19).  Injectable so a test can hold it
        # without touching the real file; ``None`` means "no lease file exists", which is
        # the same as gameplay owning the device and keeps the guard free in tests that
        # do not care about it.
        self.device_lease = device_lease

    def _owns_the_lease(self, held: object) -> bool:
        """Is the lease this run is looking at *its own*?

        Only a development validation may answer yes, and only about a
        ``DEVELOPMENT_VALIDATION`` lease.  Both halves are load-bearing:

        * ``execution_mode`` is what makes this process an examination.  An AUTO cycle is
          PRODUCTION by declaration, so it answers no and keeps yielding -- the operator's §19
          property that gameplay steps aside for an examination is untouched.
        * the holder's owner is the record's own field, i.e. the same value
          ``escalation_queue`` and ``capability_bootstrap`` already compare against.  Not
          re-derived from the trace id or the capability, because those are what the lease is
          *about* rather than who holds it.

        Why this exists at all: the window takes the lease and then spawns ``run_live`` as a
        child, so the examining process is the child while the lease was written by the parent.
        Without this check the child reads its own lock as a foreign one, yields with
        ``device_leased_for_development`` and ``steps: []``, and the examination can never run
        -- measured 2026-09-21, every validation cycle for 6.5 hours.

        The mode is compared against ``OWNER_DEVELOPMENT_VALIDATION`` rather than against a
        second constant spelled out here: it is the same string, the project already treats
        ``device_lease`` as the one place that names the owner, and a parallel literal is how
        two disagreeing names for one mode start.  ``escalation_queue`` reads episodes by the
        literal for a different reason (episode rows are data, not owners).
        """
        if self.execution_mode != OWNER_DEVELOPMENT_VALIDATION:
            return False
        return str(getattr(held, "owner", "") or "") == OWNER_DEVELOPMENT_VALIDATION

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

        The refused-claim cooldown travels on the same wiring and for the same
        reason: it too is learned from the panel and has to survive the runs in
        between, and it is the only thing that stops a panel whose 领取 control is
        drawn but inert from being re-tapped once per cycle forever (see
        ``DEFAULT_CLAIM_COOLDOWN_SECONDS``).
        """
        if self.stamina_supply is None:
            return
        countdown = world.stamina.get("next_supply_in_seconds")
        if isinstance(countdown, int):
            self.stamina_supply.record(countdown)
        self.brain.next_supply_at = self.stamina_supply.next_supply_at()
        self.brain.free_stamina_claim_cooling = self.stamina_supply.claim_cooling_down()

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

        Execution limits are **not** applied here, and that is deliberate rather than an
        omission.  The obvious test -- "does the run allow one of ``goal.available_skills``" --
        is unsound, and measuring it is how I found out: ``AVOID_STAMINA_WASTE`` declares
        ``(BEAST_HUNT, INTEL_CLAIM_REWARDS)``, but the skill it actually runs on its route is
        ``SCAN_MAP_FOR_BEAST``, which is in ``GATHER_ROUTE`` while the two it declares are not.
        Filtering here therefore refused a goal that runs perfectly well.  Those fields name the
        goal's *entry* capability, not the skills the route will use, and a gate built on them
        is worse than no gate.  The limit is applied after the decision instead, where the skill
        is a fact -- see ``_yield_to_next_goal``.
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
            if goal.goal_id in self._yielded_goals:
                # Already offered this run and already found unusable; the line was written the
                # first time, so this pass stays quiet rather than repeating it.
                continue
            out.append(goal)
        return out

    def _narrate_once(self, line: str) -> None:
        """Print one scheduling fact per distinct reason, not once per step.

        A twelve-step run printed the identical deferral line twelve times (measured
        2026-09-18), which buries the signal it exists to provide.  Same rule here, and the
        same set, because these lines belong in one stream.
        """
        if line in self._printed_deferrals:
            return
        self._printed_deferrals.add(line)
        print(f"[schedule] {line}", flush=True)

    def _yield_to_next_goal(self, goal, deferrals: list[Deferral], decision, why: str) -> bool:
        """Hold one goal back for the rest of this run so the next one can be tried.

        Returns True only when a *new* goal was held back -- i.e. when the caller may go round
        again.  False means there is nothing new to hold back, and the caller keeps the
        behaviour it had, because a run must not spin on the same refusal.

        This is the operator's Rule A applied where it actually bites in production: the
        decision is only known after the brain has answered, so the run finds out here that the
        chosen goal cannot be carried out.  Ending the cycle at that point makes one
        unexecutable task stop every other task, which is the failure the rule names
        ("不能选中任务后才发现无法执行并停止整轮 AUTO").  Yielding instead lets the next
        selectable task have the cycle.

        Clearing ``brain.current_goal`` is the load-bearing part: the route is a run-scoped
        commitment derived from the goal that was picked, and leaving it set would make the next
        pass re-derive the same decision from the goal that was just refused.
        """
        if goal is None:
            return False
        if goal.goal_id in self._yielded_goals:
            return False
        self._yielded_goals.add(goal.goal_id)
        self._narrate_once(
            f"yield {goal.goal_id} -> {DEFERRED} on {getattr(decision, 'skill', '')}: {why}"
        )
        self.brain.current_goal = None
        self._committed_goal = ""
        return True

    def _deferral_replan(self, world: WorldState, deferrals: list[Deferral], best_goal) -> Decision | None:
        """One hop toward the page where more goals are observable.

        Only when the deferral left *nothing* to do here.  A deferred goal is not a
        reason to leave a page that still has real work on it, and getting this wrong
        is visible in the live log: measured 2026-09-18 08:55, the guard was missing,
        so the first step of a run whose gather goal was selectable hopped HOME anyway
        and the run paid a round trip to come back to the same map.

        The map is a page with one goal on it (measured: a live MAP frame discovers
        AVOID_STAMINA_WASTE and nothing else), and HOME is where the queue goals are
        readable -- 97 HOME frames in the recorded corpus read
        ``KEEP_TRAINING_PRODUCTIVE`` -- so the hop is the existing trusted one
        (``OPEN_HOME``, ``verify_open_home``, VERIFIED) rather than a new route engine.

        Bounded to once per run, refused on any page but MAP, and silent when
        ``best_goal`` exists or the hop is not actually ready.
        """
        if best_goal is not None or not deferrals or self._replan_attempted or world.page is not Page.MAP:
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

    def _remember_goal_meters(self, goals) -> None:
        """Record every goal's meter as this run reads it.

        Run-scoped on purpose: several goals are only observable on one page, and the
        step that satisfies them ends somewhere else (``DISPATCH_MARCH`` reads the
        march counter only after it lands back on MAP).
        """
        for goal in goals or ():
            self._goal_meters[goal.goal_id] = goal.distance

    def _step_goal(self, best_goal) -> str:
        """The goal an episode is recorded under.

        Goal discovery reads the page the client is standing on, which is right for
        *choosing* and wrong for *attributing*.  A route leaves the page that
        discovered its goal almost immediately, and on the pages where it finishes
        nothing is discoverable at all, so the label used to fall straight through to
        the synthetic ``AUTO_DISCOVERY`` placeholder.  That placeholder owns no meter:
        the steps filed under it could be neither called progress nor called stalled.

        Measured 2026-09-18: this is what deferred ``KEEP_MARCHES_PRODUCTIVE``.  Its
        whole route ran -- ``SEARCH_RESOURCE`` -> ``SELECT_RESOURCE`` ->
        ``SUBMIT_RESOURCE_SEARCH`` -> ``START_GATHER`` -> ``DISPATCH_MARCH``, every
        verifier passing -- but only the three MAP steps carried the goal's own name
        while the two that advanced it carried ``AUTO_DISCOVERY``.  No episode of the
        goal ever showed ``goal_progress=True``, so after three such runs the
        capability gate filed a ``NO_GOAL_PROGRESS`` deferral naming
        ``OPEN_MARCH_FORMATION``: the one step of that route which works (16/16 live
        attempts that day) and the one that is therefore not the wall.  The run's own
        commitment is the honest label for a step taken on the way to the goal it
        committed to.

        ``brain.current_goal`` still wins where it exists.  It is the named task mode a
        run was launched under, and overriding it would relabel evidence the other
        routes are already recorded under.
        """
        if best_goal is not None:
            return best_goal.goal_id
        return self.brain.current_goal or self._committed_goal or "AUTO_DISCOVERY"

    def _observations_for_engine(self) -> dict:
        """The store's records, shaped for the goal engine.

        Not filtered to fresh ones here: the engine needs to know *how overdue* a domain is to
        price a visit (``observation_store.as_observation_input``).  Measured 2026-09-19 -- with
        only "fresh readings" passed in, a due routine was worth a flat 20 against 2450 for the
        stamina goal and 70 for gathering, so nothing was ever swept.
        """
        from . import observation_store

        try:
            return dict(observation_store.as_observation_input(observation_store.load()))
        except Exception:  # noqa: BLE001 - a broken store means "nothing is fresh", never a crash
            return {}

    def _stored_stamina_value(self) -> int | None:
        """The stamina this project last believed, from its own observation store."""
        from . import observation_store

        try:
            domains = (observation_store.load() or {}).get("domains") or {}
            reading = (domains.get("stamina") or {}).get("reading") or {}
            value = reading.get("current")
            return int(value) if isinstance(value, (int, float)) else None
        except Exception:  # noqa: BLE001 - a broken store must not stop a run
            return None

    def _reject_a_dropped_digit(self, world: WorldState) -> WorldState:
        """Refuse a HUD stamina reading that is the leading digits of the last one.

        The recogniser stops early on the small HUD number -- the frame said 527 and it returned
        52 -- and a dropped digit reads as "nearly empty" while stamina is plentiful, which is
        the direction that silently stops ``AVOID_STAMINA_WASTE`` from spending.  The rule and
        its deliberate narrowness live in :func:`winter_agent_v2.ocr.looks_like_a_dropped_digit`;
        this is where it is applied, and it is applied to the world the brain and the verifiers
        read, not only to the copy that gets stored -- a correction that stopped at the ledger
        would leave the run itself acting on the bad number.

        The value is replaced, not cleared: keeping the last good reading is strictly more
        informative than "unknown", and the frame still carries ``dropped_digit_suspected`` so
        the substitution is visible in the evidence rather than looking like a measurement.
        """
        from .ocr import looks_like_a_dropped_digit

        stamina = world.stamina or {}
        current = stamina.get("current")
        if not isinstance(current, int):
            return world
        if current == self._last_stamina_read:
            return world
        if looks_like_a_dropped_digit(self._last_stamina_read, current):
            self._narrate_once(
                f"stamina {self._last_stamina_read} -> {current} looks like a dropped digit "
                f"(not a collapse); keeping {self._last_stamina_read} and flagging the frame"
            )
            return replace(world, stamina={
                **stamina,
                "current": self._last_stamina_read,
                "dropped_digit_suspected": current,
            })
        self._last_stamina_read = current
        return world

    def _record_observations(self, world: WorldState, frame: Path | str | None = None) -> None:
        """Write down what this frame actually read, so the next run need not re-open it.

        Only the panel domains are recorded, and an empty reading is recorded too on purpose:
        "we looked and it said nothing" is information, and without it the domain looks
        never-visited and gets opened again on the very next run.  A frame that did not touch
        a panel must not overwrite that panel's record, which is why this writes only the
        domains this WorldState carries.

        ``frame`` is passed to the store so every reading keeps a pointer to the picture it came
        from.  It matters most for the readings that outlive their frame: the stamina goal reads
        the store when the HUD gauge is off screen, so a wrong number there is not merely a stale
        cell on a board -- it decides whether the goal believes there is anything left to spend.
        """
        from . import observation_store
        from .goal_library import PANEL_ROUTINES, SWEEP_ROUTINES

        for routine in (*PANEL_ROUTINES, *SWEEP_ROUTINES):
            reading = getattr(world, routine.field, None)
            if reading:
                try:
                    observation_store.record(routine.field, reading, frame=frame)
                except Exception:  # noqa: BLE001 - observing must never fail a run
                    pass
        # The HUD gauge is read on many frames but is a *domain* like the others: the stamina goal
        # exists only while it is readable, so the last reading has to outlive the frame that
        # produced it or the goal disappears from the board whenever the gauge is off screen.
        if world.stamina:
            try:
                observation_store.record("stamina", world.stamina, frame=frame)
            except Exception:  # noqa: BLE001
                pass

    def _record_goals(self, world: WorldState, frame: Path | str | None = None):
        """Discover this frame's goals, persist the board, and hand them back.

        Returning them is what makes goal progress measurable: the caller compares
        the goals read before a step with the goals read after it, which is the only
        way to tell "the action worked" from "the goal advanced".

        This is also the one place observation is both consumed and recorded -- the frame in
        hand IS the observation, so a second call site that discovered again from the same
        world would only be a second chance for the two answers to disagree.
        """
        self._record_observations(world, frame=frame)
        goals = self.goal_library.discover(world, observations=self._observations_for_engine())
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
        state_before = asdict(before)
        state_after = asdict(after) if after is not None else {}
        observed_change = (
            control_experience.classify_change(state_before, state_after)
            if after is not None else "UNKNOWN"
        )
        # Folded before the episode store is consulted: what the control did is what
        # the *next* decision reads, so losing it because the evidence stream happens
        # to be switched off would be the worse of the two trades.
        self._fold_control_experience(
            decision=decision,
            before_state=state_before,
            after_state=state_after,
            execution=execution,
            observed_change=observed_change,
            goal_id=goal_id,
            frame=after_screenshot or before_screenshot,
        )
        if self.episode_store is None:
            return
        failure = None
        if execution is None or not execution.executed:
            failure = execution.error if execution else "NO_EXECUTION"
        elif verification is not None and not verification.ok:
            failure = verification.reason
        episode = Episode(
            skill=decision.skill,
            state_before=state_before,
            action=asdict(execution.action) if execution is not None else {},
            state_after=state_after,
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
            role_id=self.role_id,
            role_scope=self.role_scope,
            execution_mode=self.execution_mode,
            trace_id=self.trace_id,
            job_id=self.job_id,
            capability=self.capability,
            expected_after_version=self.expected_after_version,
            # Operator §六/§十二: the causal half of the row.  ``control`` is what the
            # action aimed at, ``expected_result`` is what the decision said would
            # happen, and ``observed_change`` is what the two states actually differ
            # by -- one of ``control_experience.CHANGE_KINDS``, so the answer has a
            # vocabulary instead of being re-derived from two JSON blobs by hand.
            #
            # ``control`` is empty for an action with no semantic target (Back, wait),
            # and ``observed_change`` is UNKNOWN when the run could not observe the
            # state afterwards -- which is a statement about the reading and must not
            # be read as "nothing happened".
            control=(execution.action.target or "") if execution is not None else "",
            expected_result=decision.expected_result,
            observed_change=observed_change,
        )
        try:
            self.episode_store.append(episode)
        except (OSError, TypeError, ValueError):
            # Learning persistence must never cause an already-issued action to
            # be repeated. The run result remains authoritative for this turn.
            pass

    # --------------------------------------------------- per-control experience

    def _fold_control_experience(
        self,
        *,
        decision: Decision,
        before_state: Mapping[str, Any],
        after_state: Mapping[str, Any],
        execution: ExecutionResult | None,
        observed_change: str,
        goal_id: str = "",
        frame: Path | None = None,
    ) -> None:
        """Record what the control that was aimed at actually did (operator §四/§六).

        Keyed by ``(page, semantic)`` -- never by a coordinate.  The position is
        stored **with the frame it was read from**, so a later reader can see that
        it is a measurement off one picture and cannot be reused as if it were a
        semantic fact (``00_MASTER_RULES.md`` §5).

        The decision's own ``expected_result`` goes in as a **hypothesis**, not as
        the outcome.  That is the point of the distinction: an expectation confirmed
        by a real change is settled and dropped, while one that produced ``NO_OP``
        stays on the record as a hypothesis that failed -- which is what stops the
        same guess being made again with the same confidence (§七).
        """
        if execution is None:
            return
        semantic = (execution.action.target or "").strip()
        if not semantic:
            return
        page = control_experience.label(before_state.get("page"))
        key = control_experience.control_key(page, semantic)
        entry = self._control_ledger.get(key)
        if entry is None:
            entry = control_experience.ControlExperience(page=page, control=semantic)
            self._control_ledger[key] = entry

        expected = (decision.expected_result or "").strip()
        if expected and expected not in entry.hypotheses and not entry.resolved:
            entry.hypotheses = entry.hypotheses + (expected,)

        control_experience.record_outcome(
            entry,
            change=observed_change,
            before=before_state,
            after=after_state,
            clicked=bool(execution.executed),
            frame=str(frame) if frame else "",
        )
        landed = execution.tap_point
        if landed is not None:
            entry.position_norm = (landed[0] / 720.0, landed[1] / 1280.0)
        if goal_id and observed_change not in ("NO_OP", "UNKNOWN"):
            entry.goal_help[goal_id] = observed_change

    def _save_control_experience(self) -> None:
        try:
            control_experience.save(self._control_ledger)
        except Exception:  # noqa: BLE001 - a ledger write must never fail a run
            pass

    # ------------------------------------------------- utility bookkeeping

    def _note_the_choice(self, board, world) -> None:
        """Record the fairness facts of one ranking, and log a change of mind.

        Operator §四.6 (waiting compensation) needs a fact the goal board cannot hold:
        ``GoalState`` is a frozen value rebuilt from the world every frame, so "how long
        has this goal been eligible without winning" has to survive across frames.  That
        is the whole reason for the ledger -- every goal on the board is counted as
        *offered*, and only the winner's clock is reset.

        The decision log gets one row per **change of the chosen goal**, not per step
        (§九: "避免高频输出重复日志，重点记录真实决策变化").  A twelve-step run that
        works one goal writes one row; a run that is forced to switch writes the switch.
        """
        if not board:
            return
        moment = datetime.now(timezone.utc)
        for goal, _breakdown in board:
            goal_utility.entry(self._fairness, str(goal.goal_id)).offered += 1
        chosen_goal, chosen = board[0]
        chosen_row = goal_utility.entry(self._fairness, str(chosen_goal.goal_id))
        chosen_row.last_selected_at = moment.isoformat()
        chosen_row.selected += 1

        if str(chosen_goal.goal_id) == self._logged_goal:
            return
        goal_utility.append_decision(goal_utility.decision_row(
            role_id=self.role_id,
            page=str(getattr(getattr(world, "page", ""), "value", getattr(world, "page", ""))),
            ranked=board,
            chosen=str(chosen_goal.goal_id),
            runner_up=str(board[1][0].goal_id) if len(board) > 1 else "",
            reason=chosen.why(),
            now=moment,
        ))
        self._logged_goal = str(chosen_goal.goal_id)
        print(f"[utility] chose {chosen_goal.goal_id} "
              f"({chosen.total:.0f}; {chosen.why()})", flush=True)

    def _note_deferrals(self, deferrals) -> None:
        """Persist each deferral's own retry window, for the log and the panel (§五).

        ``Deferral`` already carries everything §五 asks a blocked task to record --
        ``goal_id``, ``reason``, ``until``, ``streak``, ``last_attempt``, ``last_skill``
        -- but all of it lived only in the runtime snapshot for the current cycle.  This
        keeps the last one per goal so "when will this be looked at again" survives the
        run.  It is deliberately **not** used to block selection: the gate owns
        eligibility, and a second window here could only extend a block (see
        ``goal_utility.rank``).

        ``until`` is frequently empty in production -- measured 2026-09-21, four goals
        deferred with ``until=""`` and nothing to bring them back.  For those the
        estimate is the gate's own ``probe_minutes``; when that is zero too, the entry
        says so by leaving the window unset rather than inventing one.
        """
        moment = datetime.now(timezone.utc)
        for item in deferrals:
            goal_id = str(getattr(item, "goal_id", "") or "")
            if not goal_id:
                continue
            row = goal_utility.entry(self._fairness, goal_id)
            row.last_block_reason = str(getattr(item, "reason", "") or "")
            until = getattr(item, "until", None)
            if until is not None:
                row.retry_after = until.isoformat()
                continue
            minutes = int(getattr(item, "probe_minutes", 0) or 0)
            row.retry_after = (
                (moment + timedelta(minutes=minutes)).isoformat() if minutes > 0 else ""
            )

    def _save_fairness(self) -> None:
        try:
            goal_utility.save(self._fairness)
        except Exception:  # noqa: BLE001 - a ledger write must never fail a run
            pass

    def _device_lost(self, call, *args) -> bool:
        """Run one device call; answer True if the DEVICE left rather than the goal failing.

        Every capture in this loop used to call ``self.device.screenshot`` bare, so a
        transport that died mid-run raised straight out of ``run()``.  What the operator got
        was a worker crash report whose cause was classified ENVIRONMENT -- correct, but the
        run in between recorded nothing about WHERE it was standing when the device went,
        and the next cycle met the same screen.

        The distinction this method exists to draw is the one the operator named: a goal
        refusing is a statement about that goal and hands the cycle over; a device that has
        gone away is a statement about the environment and cannot be handed to anybody.  So
        a device failure is neither yielded nor allowed to escape -- it ends the run as
        ``RECOVERING`` with the device's own words as the reason, which is the state the GUI
        already reads as ENVIRONMENT and restarts the watchdog for without counting a worker
        crash.  The next cycle re-runs ``_ensure_device`` against a client that has had a
        full restart interval to come back.

        An exception that is NOT a device failure is re-raised unchanged: this is a
        device guard, not a blanket ``except`` that would swallow real defects.
        """
        try:
            call(*args)
        except Exception as exc:  # noqa: BLE001 -- inspected below; only device failures are handled
            if not _device_gone(exc):
                raise
            self._device_stop_reason = str(exc) or "DEVICE_NOT_CONNECTED"
            self._runtime(
                agent_state=AgentState.RECOVERING.value,
                runtime_thread_alive=False, scheduler_loop_alive=False,
                stop_reason=self._device_stop_reason,
                reason="the device left mid-run; this is not a goal declining to act",
                next_action="the next cycle re-checks the device before observing",
            )
            return True
        return False

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

    def _resolve_semantic_target(
        self,
        semantic: str,
        frame: "WorldState",
        *,
        frame_path: "Path | None" = None,
        resource: str | None = None,
        untried_intel_pins: list | None = None,
    ):
        """Answer where on ``frame`` the named semantic control is, or ``None``.

        This was a closure inside ``run`` until 2026-09-21.  Nothing about what it
        decides changed; it was lifted onto the class for one measured reason: a
        tap target that is *read off the frame* (a label position, a detected pin,
        a selection ring) is exactly the part of a live run most worth testing
        without a device, and a closure cannot be reached from a test.  The frame is
        now an argument instead of a captured local, which is also what makes the
        page/panel guards testable -- they are the whole reason a stale coordinate
        cannot be reused.

        ``frame_path`` stays a separate argument rather than a field on ``WorldState``
        because the observed state deliberately does not carry where it was read from:
        the template fallback at the bottom is the one branch that needs the pixels,
        and inventing a field so this branch could reach it would put a path on every
        state object the rest of the pipeline compares and serialises.

        ``None`` is always the honest answer to "the client did not draw this
        where it could be read": the caller ends the step rather than tapping an
        invented point.  Every guard below exists because a real frame made the
        guess wrong at least once.
        """
        if semantic == "RESOURCE_DYNAMIC":
            # The strip scrolls, so the tap target is derived from the
            # bracket anchor observed on the current frame (see
            # SemanticROIVision.resource_cell_center_norm).  The previous
            # hand-typed centres were only valid for one scroll offset and
            # selected the wrong tab on live frames.  ``None`` means the
            # cell is off-screen: the loop scrolls the strip instead of
            # guessing a coordinate.
            return self._semantic.resource_cell_center_norm(resource)
        if semantic == "BEAST_SEARCH_TAB":
            # The 野兽 tab, tapped where this frame's own OCR read its printed label
            # (see ``ocr.read_resource_tab_labels``).
            #
            # This replaces a template pinned to a strip position, and the reason is
            # measured rather than theoretical: on 2026-09-21 the live client had 野兽
            # in the leftmost slot, where the archived frame (and therefore the
            # registered ``BTN_SEARCH_BEAST_TAB`` control) expected 冰原巨兽.  All three
            # beast-search templates scored NO MATCH on the live frame, the second hop
            # of the search chain returned SEMANTIC_TARGET_NOT_VERIFIED, and the goal
            # yielded without ever reaching a beast.  ``vision.resource_tab_order``
            # already warns that this part of the strip drifts and that reading the
            # label is the durable answer; this is that answer.
            #
            # The page and panel checks keep a stale point from being reused: the
            # fragment belongs to the MAP frame it was read from, and only an open
            # search panel draws the strip at all.  ``None`` -- wrong page, no panel, or
            # the tab not on screen -- ends the loop honestly rather than tapping an
            # invented point, which is also what stops a client without a 野兽 tab from
            # being tapped somewhere arbitrary.
            #
            # The strip geometry is preferred over the label box, and it must be a cell
            # that is FULLY on screen.  Measured live 2026-09-21 on
            # ``live_runtime_step_001_after_20260921T105247039793.png``: the strip sat at
            # offset 197, putting 野兽's cell left at -30, and a tap on its visible sliver
            # at x=42 left **冰原巨兽** anchored -- the client selects the neighbour, not the
            # cell that is showing a sliver of itself.  Revealing the cell is therefore the
            # runtime's job (see its scroll branch), and this resolver must not hand the
            # executor a clipped point in the first place: a partial cell whose position the
            # geometry cannot confirm is exactly the "invented point" the guards below exist
            # to refuse.  When the cell is clipped the resolver returns ``None`` and the
            # runtime swipes instead; the label box below is the fallback for a frame whose
            # strip could not be located at all.
            geometry = None
            if frame_path is not None:
                # ``selected_resource`` records ``resource_tab_offset`` on the vision
                # instance, and the instance outlives a frame -- so the offset is
                # re-resolved from THIS frame before it is used, and a frame whose
                # strip cannot be located leaves the geometry branch to fall through
                # to the label box below.
                self._semantic.selected_resource(frame_path)
                geometry = self._semantic.resource_cell_center_norm("BEAST")
            if geometry is not None:
                return geometry
            if frame.page is not Page.MAP or not frame.resource_search_open:
                return None
            point = frame.resource_beast_tab_norm
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return None
            return (x_norm, y_norm)
        if semantic == "BTN_BEAST_CARD_ATTACK":
            # The 攻击 control on the card the client's own beast search drew.  Its
            # coordinate comes from that card's reading (see
            # ``ocr.read_beast_search_result_card``), not from a template, and the
            # reason is measured on the very frame this branch exists for:
            # ``live_runtime_step_001_after_refresh_1_20260921T110723901682.png`` is
            # the ``等级10 麝牛`` result card, and the registered
            # ``BTN_BEAST_CARD_ATTACK`` scored NO MATCH on it -- the template was cut
            # from a world-map card and this one is drawn over the open search panel.
            # A route that named the control but had no coordinate would have ended
            # its run one hop short of a beast it had already found.
            #
            # The guard is that the frame must still be showing that card: the point
            # is a fragment of the frame it was measured on, and only a verified
            # solo-attack result makes it meaningful.  ``None`` -- wrong page, no card,
            # or a card offering 集结 instead -- ends the loop honestly rather than
            # tapping an invented point, which is also what keeps a rally target from
            # ever being entered through the ordinary-attack control.
            #
            # The page is ``MAP`` or ``BEAST``, and requiring ``MAP`` alone was
            # measured wrong live 2026-09-21T12:09:41Z.  The card carries the search
            # panel open behind it, and ``HybridVision.observe`` classifies that frame
            # ``Page.BEAST`` -- the same page it emits for the card itself (see the
            # card branch in ``observe``).  With the guard written against ``MAP`` the
            # resolver refused the very frame the reading came from:
            #
            #     step 003 before   page = BEAST
            #                       beast_search_result = {title_level: 10,
            #                           title_text: 蔚牛, solo_attack: True,
            #                           attack_centre_norm: (0.5007, 0.4688)}
            #     decision          ATTACK_BEAST_CARD
            #     execution         SEMANTIC_TARGET_NOT_VERIFIED, tap_point = null
            #
            # so the route found an ordinary-attack target, decided correctly, and
            # could not tap it -- one word short of the dispatch.  Accepting BEAST
            # keeps what the guard is for (the point belongs to a frame that carries
            # the card) without rejecting the page the card is actually read on.
            if frame.page not in {Page.MAP, Page.BEAST}:
                return None
            result = frame.beast_search_result or {}
            if not result.get("solo_attack"):
                return None
            point = result.get("attack_centre_norm")
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return None
            return (x_norm, y_norm)
        if semantic == "BEAST_ON_MAP":
            # The beast the client's own label named, tapped where this frame
            # measured that label (see ocr.beast_from_its_label).  It cannot be a
            # template: the whole point is that the target need not be a species
            # anyone has cut a sprite for, and a hardcoded coordinate would be a
            # guess about where the animal happens to stand.
            #
            # The page check is what keeps a stale point from being reused: the
            # fragment is only meaningful on the MAP frame it was read from, so a
            # tap_norm left over from an earlier observation cannot land on
            # whatever page the run has since reached.  ``None`` means the label
            # carried no box (or no frame size was available) and the loop ends
            # honestly rather than tapping an invented point.
            if frame.page is not Page.MAP:
                return None
            point = frame.beast.get("tap_norm")
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return None
            return (x_norm, y_norm)
        if semantic == "TRAINING_CAMP_IN_RING":
            # The selected camp's own centre, read off the frame by camp_ring.py.
            #
            # The template this replaces resolved to (346, 682) on all 46 live stage A
            # frames -- 103 px below the selection ring, on bare ground between the
            # buildings.  Tapping there is a map tap, which is what took the client to
            # the MAP on the one attempt that ever tried it.  The ring's centre is a
            # measurement of the same frame rather than a correction applied to a
            # remembered point, so it follows the camera instead of assuming it.
            #
            # The page check is what keeps a stale point from being reused, exactly as
            # for the beast above: the fragment belongs to the HOME frame it was read
            # from.  ``None`` -- wrong page, no ring, or no frame size -- ends the loop
            # honestly rather than tapping a point nobody measured.
            if frame.page is not Page.HOME:
                return None
            point = frame.training.get("camp_tap_norm")
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return None
            return (x_norm, y_norm)
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
            if frame.page.value != "MAP" or frame.resource_search_open:
                return None
            return self._semantic.stamina_gauge_center
        if semantic == "MARCH_ROW_1":
            # The march list is a fixed-pitch row list under the HUD, not
            # a template: the row artwork changes with mission type and
            # the list reflows.  Refuse when the list cannot be believed
            # to be visible, because tapping row 1 on a frame without an
            # active march would tap the bare map.
            if frame.page.value != "MAP" or frame.resource_search_open:
                return None
            if frame.march_used is None or frame.march_used < 1:
                return None
            return self._semantic.march_row_1_center
        if semantic == "RESOURCE_LEVEL_MINUS":
            # The level filter is a measured slider row, not a
            # template: the minus control sits at a calibrated centre
            # whose value was read live across every level 8 -> 1.
            if not frame.resource_search_open:
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
            if frame.page.value != "INTEL":
                return None
            status = self.device.status()
            if not status.connected or status.resolution is None:
                return None
            width, height = status.resolution
            if untried_intel_pins is not None:
                pin = untried_intel_pins.pop(0)
                self._tapped_intel_pins.append((pin.x, pin.y))
                return (pin.x / width, pin.y / height)
            return None
        match = self._semantic.find(frame_path, semantic) if frame_path is not None else None
        if match:
            return match.center_norm
        # The Exploration chest is animated and its perceptual hash
        # varies between frames. A reviewed normalized fallback is
        # allowed only after independent page + green-state proof.
        if semantic == "BTN_EXPLORATION_IDLE_CLAIM" and frame.page.value == "EXPLORATION" and frame.exploration.get("status") == "CLAIMABLE":
            return (0.86, 0.68)
        return None

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
        # One narration per distinct deferral reason, not one per step: the reason is
        # recomputed per step, and a twelve-step run printed the identical line twelve
        # times (measured 2026-09-18).
        self._printed_deferrals: set[str] = set()
        # The meters this run has read so far; see _remember_goal_meters.
        self._goal_meters: dict[str, float] = {}
        self._committed_goal = ""
        gate = self._gate()

        def finish(reason: str) -> LiveRun:
            # One write per run, not one per step: the ledger is folded in memory as
            # each step is recorded and persisted here, where the run has a single
            # exit.  A per-step rewrite of a JSON file would put disk I/O inside the
            # action loop for no gain -- nothing reads the ledger mid-run.
            self._save_control_experience()
            self._save_fairness()
            return LiveRun(tuple(steps), reason, tuple(item.as_row() for item in deferrals))

        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._relax_attempts = 0
        self._scroll_attempts = 0
        self._resource_switches = 0
        self._stamina_refusals = 0
        self._leave_retries = 0
        self._unknown_page_backs = 0
        # Operator §二.5/§二.7 (2026-09-21): a failed step hands the cycle to the next
        # goal instead of ending the run, bounded here.  Two is enough to reach a
        # different task; a third failure in one run is a statement about the run's
        # situation, not about the goal it happened to be holding.
        self._verification_retries = 0
        # Controls whose step failed its verifier in THIS run, mapped to the reason it
        # failed with.  Operator §七.3: a tap that did nothing must not be repeated at
        # the same position.  The reason is kept so that when this is what ends the run,
        # the run reports the verifier's own reason rather than a new stop reason that
        # nothing else knows how to classify.
        self._failed_controls: dict[str, str] = {}
        # What each visible control actually did, keyed by (page, semantic).  Folded
        # per step, written once at ``finish``.  Loaded per run so a fresh process
        # still has last run's experience.
        self._control_ledger = control_experience.load()
        # Utility inputs (operator §四).  All three are loaded once per run: the route
        # card is a measured artefact that does not change inside a run, and the
        # fairness ledger is written back at ``finish``.  Kept on the instance so
        # every ranking in this run reads the same factors.
        self._routes = goal_utility.load_routes()
        self._fairness = goal_utility.load()
        # The last goal this run actually committed to, so the decision log records
        # *changes* of mind rather than one row per step (§九: no high-frequency noise).
        self._logged_goal = ""
        # Goals this run has already offered and found it could not execute.  Run-scoped on
        # purpose: the reason is "this cycle cannot run it" (a skill this run may not use, a
        # skill that is not ready, or a candidate pool that is spent), which says nothing about
        # the next cycle.  Without it, yielding would re-pick the same goal forever.
        self._yielded_goals: set[str] = set()
        # The last stamina the run believes, seeded from the store so a misread in *this* run
        # can still be judged against what the previous run read.  See
        # ``_reject_a_dropped_digit``.
        self._last_stamina_read: int | None = self._stored_stamina_value()
        # Run-scoped: set once a step verifies that a fight has just been
        # dispatched, cleared as soon as a known page is observed again, so it
        # cannot outlive the fight it was armed for.
        self._fight_resolving = False
        self._runtime(agent_state=AgentState.AUTO_RUNNING.value, runtime_thread_alive=True,
                      scheduler_loop_alive=True, last_fatal_error=None, stop_reason=None)

        for index in range(1, max_actions + 1):
            # The single-UI-owner boundary (operator §8/§19), checked at the only moment
            # when no input is in flight: the previous step's action and verification are
            # finished and the next one has not begun.  A lease held by anyone else ends
            # the run here, so V2 yields the device at a safe point instead of being
            # interrupted mid-transaction -- which is why this is at the top of an
            # iteration and not inside one.
            #
            # "Anyone else" is the load-bearing word, and it was wrong for six hours
            # (measured 2026-09-21).  A development validation is performed *by this
            # process*: the window acquires the lease as DEVELOPMENT_VALIDATION and then
            # spawns run_live, so the child's first iteration found a lease it did not
            # recognise, concluded a developer owned the device, and yielded -- to itself.
            # Every validation cycle produced ``steps: []`` and ``EXIT_2`` with
            # ``device_leased_for_development``, which looked like the operator's AUTO
            # correctly deferring and was in fact the examination refusing to examine.
            # The lease was never the obstacle; not knowing whose it is was.
            #
            # So the question is not "does gameplay hold it" but "does *someone else* hold
            # it".  A validation cycle legitimately owns the device -- that is what the
            # lease is FOR -- and must run while it does, or the examination can never
            # happen.  The identity is the one the lease record already carries and that
            # ``escalation_queue`` and ``capability_bootstrap`` already compare against:
            # this process is that validation iff its own ``execution_mode`` says so and
            # the holder is a DEVELOPMENT_VALIDATION.  Both halves are required, because
            # an AUTO cycle must still yield to a real examination -- that is the §19
            # property this guard exists for, and it stays exactly as it was.
            held = self.device_lease.holder() if self.device_lease is not None else None
            if held is not None and held.owner != OWNER_GAMEPLAY and not self._owns_the_lease(held):
                reason = "device_leased_for_development"
                self._runtime(
                    agent_state=AgentState.PAUSED.value, runtime_thread_alive=False,
                    scheduler_loop_alive=False, stop_reason=reason,
                    reason=f"{held.owner} owns the device for {held.capability_id or 'validation'}",
                    next_action="yielded at a safe point; resumes when the lease is released",
                )
                return finish(reason)
            before_path = self._capture_path(index, "before")
            if self._device_lost(self.device.screenshot, before_path):
                return finish(self._device_stop_reason)
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
            before = self._reject_a_dropped_digit(before)
            goals = self._record_goals(before, frame=before_path)
            self._remember_goal_meters(goals)
            # Operator §四/§五: the board is re-ranked here, on every step, against the
            # frame we are standing on -- not once per run.  ``rank`` returns the whole
            # board with each term, and ``best`` is the same ordering, so the choice and
            # the explanation can never disagree.
            board = self.goal_library.rank(
                self._selectable(goals, deferrals),
                before,
                fairness=self._fairness,
                routes=self._routes,
            )
            best_goal = board[0][0] if board else None
            self._note_the_choice(board, before)
            if best_goal is not None:
                self._committed_goal = best_goal.goal_id
            if deferrals:
                # Written every run, not only when it changes: the panel and the
                # escalation hook both read the current answer, and a stale one would
                # make "why is it doing that" unanswerable from outside.  Printed once
                # per distinct reason, though -- the test is per step, and a twelve-step
                # run repeated the same line twelve times, which buries the signal it
                # exists to provide (measured 2026-09-18).
                self._runtime(deferred_goals=[item.as_row() for item in deferrals])
                self._note_deferrals(deferrals)
                for item in deferrals:
                    if item.describe() in self._printed_deferrals:
                        continue
                    self._printed_deferrals.add(item.describe())
                    print(f"[schedule] deferred {item.describe()}", flush=True)
            if self.brain.current_goal is None and best_goal is not None:
                # The one place a goal id becomes a brain route.  A goal that is missing here
                # is not "handled elsewhere" -- it is scheduled, given no route, and quietly
                # does nothing, which is how four panel routines stayed invisible while their
                # capabilities worked.
                #
                # The table itself now lives in ``goal_library`` (``GOAL_ROUTES``): the panel's
                # Development Validation cycle needs the same translation to build a command
                # line, and a second copy drifted the moment a goal was added -- measured
                # 2026-09-21, every calibration run died on argparse with EXIT_2 while the map
                # here was correct.  One table, two readers.
                route = route_for(best_goal.goal_id)
                if best_goal.goal_id == "AVOID_STAMINA_WASTE":
                    # The goal declares three ways to spend stamina and the beast one is the
                    # blocked one, so routing it to BEAST_HUNT would send the run down the path
                    # that cannot run: five pans, no target, stop -- and the operator's standing
                    # requirement is that stamina stays under 30.  The intel missions spend the
                    # same stamina through a route that is LIVE_VERIFIED, measured live at 10-15
                    # per mission, so the goal rides that one while the beast path is off.
                    beast = (gate.capabilities.get("SPEND_STAMINA_ON_BEAST") or (None,))[0]
                    if beast in {"BLOCKED", "COOLDOWN", "DEFERRED", "DEVELOPMENT_PENDING"}:
                        # Its own route name, not "INTEL": the two share the intel flow but are
                        # different goals, and the spend goal must not claim free stamina (which
                        # raises the number it exists to lower).  See `RuleBrain._intel_like`.
                        route = "SPEND_STAMINA"
                self.brain.current_goal = route
                # The route name does not say which goal chose it, and one decision
                # downstream needs exactly that: only the spend goal may hand over to the
                # intel flow when no beast is in view.
                self.brain.goal_id = best_goal.goal_id
            if before.page in {Page.MAINTENANCE, Page.LOADING}:
                # Environmental states resolve on the game's own schedule. The
                # worker must hold, not exit: an exit here was counted as an
                # unexpected worker exit and restarted the client, which then
                # hit the same splash again. Record one waiting step and sleep
                # a long, bounded interval before re-observing.
                decision = self.brain.decide(before, self.registry)
                self._runtime(agent_state=AgentState.IDLE.value,
                              current_goal=self._step_goal(best_goal),
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
                leave = self._deferral_replan(before, deferrals, best_goal)
            decision = leave if leave is not None else self.brain.decide(before, self.registry)
            self._runtime(agent_state=AgentState.GOAL_RUNNING.value,
                          current_goal=self._step_goal(best_goal),
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
                            if self._device_lost(self.device.screenshot, recovery_path):
                                return finish(self._device_stop_reason)
                            before = self.vision.observe(recovery_path)
                            before = self._reject_a_dropped_digit(before)
                            self._record_goals(before, frame=recovery_path)
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
                            if self._device_lost(self.device.screenshot, recovery_path):
                                return finish(self._device_stop_reason)
                            before = self.vision.observe(recovery_path)
                            before = self._reject_a_dropped_digit(before)
                            self._record_goals(before, frame=recovery_path)
                            if before.page not in {Page.UNKNOWN, Page.LOADING, Page.MAINTENANCE}:
                                recovered = True
                                break
                    if recovered:
                        self._fight_resolving = False
                        continue
                # A refusal is not an ending: it ends the TASK, not the CYCLE.
                #
                # ``SAFE_STOP`` is how the brain says "this goal has nothing to do on this
                # screen", and every reason it carries is a statement about ONE goal: the
                # reserved slot may not be taken by this task, the training queue is busy,
                # the beast is not visible, the mail is all clear, an unknown panel belongs
                # to nobody.  The runtime answered all of them the same way -- record
                # DEGRADED and ``return finish(reason)`` -- so one task declining, correctly
                # declining, ended every other task in the cycle as well.
                #
                # Measured live, twice, both on that shape:
                #
                #   * 2026-09-21T03:17:51Z, stop_reason 'reserved_march_for_stamina'.  The
                #     round ran one action (EXECUTE_INTEL_RESCUE_SURVIVORS, 187 -> 175) and
                #     then stopped, after reading marches=["GATHERING","RETURNING"],
                #     march_used=2, march_max=3 -- exactly ONE free slot, which is exactly
                #     the reserved one, so the reservation was doing its job.  Replayed
                #     through the production chain on that same frame with the production
                #     reserve (march_policy.reserve_for_stamina=2, effective 1 at capacity
                #     3): goal=None / GATHER_RESOURCE gave the stop, but goal=BEAST_HUNT
                #     gave SCAN_MAP_FOR_BEAST.  The reservation never blocked the stamina
                #     goal; the stop blocked everything.  (Incident frame:
                #     dataset/truth_audit/march_reservation_20260921/key/.)
                #
                #   * 2026-09-21T03:44:56Z, stop_reason 'alliance_state_unknown', goal label
                #     KEEP_TRAINING_PRODUCTIVE, page ALLIANCE -- a panel that plainly showed
                #     联盟科技 carrying a 25 badge.  Nothing moved the client off the panel,
                #     so the next cycle opened on the same screen and repeated it.
                #
                # The operator's rule is explicit: a goal that cannot run says only that
                # THAT goal must step aside; it does not say the work cycle is over.  And
                # the runtime already owns the mechanism that says exactly that --
                # ``_yield_to_next_goal``, the same Rule A hop the unexecutable-skill path
                # below uses.  So the question is no longer "which reason?", it is "is this
                # a reason to end the whole cycle at all?", and ``is_fatal_stop`` is the
                # project's own single answer: only FATAL_/ACCOUNT_/PAYMENT_ reasons end
                # the run.  Everything in NON_FATAL_STOPS yields.
                #
                # Bounded by the same two guards as the path below, which is what keeps it
                # from becoming a spin: one iteration must remain, and a goal is held back
                # at most once per run.  Once every selectable goal has been held back the
                # call answers False and the stop happens -- and THAT is the honest "nothing
                # left to do in this cycle", rather than the first goal that said no.
                #
                # No task is renamed, no reason is reclassified, no second scheduler is
                # introduced: the runtime simply stops treating one goal's refusal as
                # everyone's.
                if (
                    not is_fatal_stop(decision.reason)
                    and index < max_actions
                    and self._yield_to_next_goal(
                        best_goal,
                        deferrals,
                        decision,
                        "this goal refused on this screen, and the refusal says nothing about "
                        "the other goals; it steps aside so any other selectable goal -- "
                        "including the owner of a resource it was holding back -- can use the "
                        "cycle",
                    )
                ):
                    continue
                steps.append(LiveStep(index, decision, None, before, None, None))
                self._runtime(agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(decision.reason) else AgentState.DEGRADED.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=decision.reason,
                              last_fatal_error=decision.reason if is_fatal_stop(decision.reason) else None)
                return finish(decision.reason)
            if decision.skill not in allowed or decision.skill not in self.VERIFIED_ATOMIC:
                # Rule A: a task this run cannot carry out yields to the next one.  Only when
                # there is no goal to hold back -- a named run's own route, or a goal already
                # tried this run -- does an unusable skill end the cycle, which is the honest
                # answer there because nothing else in this run was going to change it.
                #
                # ``index < max_actions`` is load-bearing: yielding costs one iteration, so a run
                # with no iteration left to re-select in would spend its whole budget and issue
                # nothing.  Measured 2026-09-19 on a one-action run: the yield was taken, the loop
                # ended, and the run finished with zero steps -- strictly worse than the stop it
                # replaced.  With budget left, yielding is the improvement it is meant to be.
                if index < max_actions and self._yield_to_next_goal(
                    best_goal,
                    deferrals,
                    decision,
                    f"{decision.skill} may not run in this run (reason: {decision.reason}); "
                    f"this task yields to the next selectable one",
                ):
                    continue
                steps.append(LiveStep(index, decision, None, before, None, None))
                return finish("SKILL_NOT_ENABLED_FOR_LIVE_LOOP")

            # The executor and the backend router both take this one callable.  It binds
            # the run-scoped arguments (the frame this step observed, the resource this
            # step planned, the pins this run has not tried) to the class-level resolver
            # so a test can call the resolver the same way without a device.
            def resolve(semantic: str):
                return self._resolve_semantic_target(
                    semantic,
                    before,
                    frame_path=before_path,
                    resource=planned_resource,
                    untried_intel_pins=untried_intel_pins,
                )

            if (
                decision.skill in ("SELECT_RESOURCE", "OPEN_BEAST_SEARCH_TAB")
                and self._semantic.resource_tab_offset is not None
                and self._semantic.resource_cell_center_norm(
                    "BEAST" if decision.skill == "OPEN_BEAST_SEARCH_TAB" else planned_resource
                ) is None
                and self._scroll_attempts < self.max_scroll_attempts
            ):
                # The requested resource tab is outside the visible strip (WOOD,
                # COAL and IRON sit past the right edge at the default offset).
                # Scroll it into view and re-observe on the next iteration; no
                # click is issued for a target whose position is unknown.
                #
                # ``OPEN_BEAST_SEARCH_TAB`` is included because 野兽 clips on the LEFT
                # edge just as routinely, and the measured consequence of tapping a
                # clipped cell instead of revealing it is that the client selects the
                # NEIGHBOUR: measured live 2026-09-21,
                # ``live_runtime_step_001_after_20260921T105247039793.png`` shows a tap
                # at x=42 (野兽's own visible sliver, offset 197) leaving 冰原巨兽
                # anchored, and the verifier's honest ``BEAST_SEARCH_TAB_NOT_PROVEN``
                # is what stopped the run from searching the wrong tab.  A controlled
                # swipe of +34 px then moved the strip to offset 237.5, put 野兽's cell
                # left on a stroke at 10.5 -- an exact match with its nominal position --
                # and the same frame read ``anchored_tab_kind == "BEAST"``.
                target_tab = "BEAST" if decision.skill == "OPEN_BEAST_SEARCH_TAB" else planned_resource
                delta = self._semantic.resource_tab_swipe_for(target_tab)
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
                            reason=f"scroll_resource_strip_to_{target_tab}",
                            next_action="reevaluate_after_scroll",
                            verifier="PENDING",
                        )
                        continue
            # Operator §七.3, and the guard has to be HERE rather than after the
            # verifier: "a control that already failed in this run is not tapped again
            # at the same position".  The first version of this check ran after the tap
            # and therefore stopped the *third* attempt while the second -- the one the
            # rule is about -- had already been issued.  Measured on the two-goal
            # scenario: one failed control, two identical taps.
            #
            # The decision is still the brain's; this only refuses to *repeat* one that
            # this run has already tried and failed.  Yielding first means the next goal
            # gets the cycle; when there is nobody to hand to, the run ends with the
            # verifier's own reason, so nothing new has to be classified downstream.
            planned_target = ""
            _planned_skill = self.registry.get(decision.skill)
            if _planned_skill is not None:
                planned_target = (_planned_skill.action.target or "")
            if planned_target and planned_target in self._failed_controls:
                if index < max_actions and self._yield_to_next_goal(
                    best_goal,
                    deferrals,
                    decision,
                    f"{planned_target} already failed its verifier in this run "
                    f"({self._failed_controls[planned_target]}); it is not tapped twice",
                ):
                    continue
                steps.append(LiveStep(index, decision, None, before, None, None))
                return finish(self._failed_controls[planned_target])

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
                    goal_id=self._step_goal(best_goal),
                    # Nothing ran, so there is no after-frame for ``progress_moved``
                    # to measure and no verifier verdict either -- but the goal
                    # still did not advance, and this field is what feeds
                    # ``_streak_and_last`` in the capability gate.  Leaving it
                    # ``None`` reads there as "not measured", which stops the
                    # streak instead of counting it, so the no-progress deferral
                    # could never fire for this case.  Measured 2026-09-20: a goal
                    # that could not resolve its tap target produced 30 and then
                    # 29 consecutive episodes that all recorded ``None`` against a
                    # threshold of 3, and re-occupied every round for ~2 hours.
                    # A run with no goal at all keeps ``None``: there is no goal
                    # here to hold accountable for the round.
                    goal_progress=False if best_goal is not None else None,
                    before_screenshot=before_path,
                )
                steps.append(LiveStep(index, tick.decision, tick.execution, before, None, None))
                reason = tick.execution.error if tick.execution else "NO_EXECUTION"
                # A step that issued no action has not failed the run -- it has failed to find
                # work for the goal that was picked, and this branch is already exactly that
                # class (``not tick.execution.executed``).  Ending the cycle here lets one
                # unexecutable task stop every other task, which is the operator's "不能选中任务后
                # 才发现无法执行并停止整轮 AUTO".
                #
                # Measured live 2026-09-20 18:02-18:14, ten rounds: five of them performed exactly
                # one action and failed it, CLOSE_POPUP failed three rounds in a row, and not one
                # DISPATCH/MARCH episode appeared anywhere in the window -- because each of those
                # rounds ended right here.
                #
                # Rule A already exists for this and is applied at the pre-decision site above
                # (``index < max_actions``).  This is the same holding-back applied where the
                # answer only becomes known after the brain has answered.  ``_yield_to_next_goal``
                # holds a goal back for the rest of the run and returns True only for a goal it has
                # not already held back, so this cannot spin on the same refusal; a fatal stop, an
                # exhausted budget or a goal already yielded all fall through to the ending below.
                if (
                    index < max_actions
                    and not is_fatal_stop(reason)
                    and self._yield_to_next_goal(best_goal, deferrals, tick.decision, reason)
                ):
                    self._runtime(agent_state=AgentState.DEGRADED.value, stop_reason=reason)
                    continue
                self._runtime(agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(reason) else AgentState.DEGRADED.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=reason,
                              last_fatal_error=reason if is_fatal_stop(reason) else None)
                return finish(tick.execution.error if tick.execution else "NO_EXECUTION")

            self.sleeper(self.settle_seconds)
            after_path = self._capture_path(index, "after")
            if self._device_lost(self.device.screenshot, after_path):
                return finish(self._device_stop_reason)
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
                if self._device_lost(self.device.screenshot, recovery_path):
                    return finish(self._device_stop_reason)
                after = self.vision.observe(recovery_path)
                if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                    after = replace(after, resource_target=planned_resource)
                after_path = recovery_path
            after = self._reject_a_dropped_digit(after)
            goals_after = self._record_goals(after, frame=after_path)
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
                if self._device_lost(self.device.screenshot, refresh_path):
                    return finish(self._device_stop_reason)
                after = self.vision.observe(refresh_path)
                if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                    after = replace(after, resource_target=planned_resource)
                after = self._reject_a_dropped_digit(after)
                goals_after = self._record_goals(after, frame=refresh_path)
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
            if (
                not verification.ok
                and decision.skill == "CLAIM_FREE_STAMINA"
                and verification.reason == "FREE_STAMINA_CLAIM_NOT_PROVEN"
                and self.stamina_supply is not None
            ):
                # A negative result, and the only place it can be observed: the tap
                # was sent and the panel came back identical.  Measured live
                # 2026-09-19T05:17Z with a bounded probe (``tools/probe_power_route.py
                # --tap 581,383 --leave``): the 领取 control is still drawn and still
                # matches its template at distance 0, the tap changes nothing, and one
                # Back lands on MAP.  The run ends here (a failed verifier always does),
                # so the memory has to outlive this interpreter or the next cycle
                # re-decides the same dead tap -- which is what the whole agent did for
                # eight consecutive runs across four goals.
                self.stamina_supply.record_claim_refused()
                self.brain.free_stamina_claim_cooling = True
            step_goal = self._step_goal(best_goal)
            # Operator §四.5: a candidate that keeps being chosen and keeps making no
            # progress drops in the order.  ``None`` (the goal's own meter was not
            # observable on both frames) leaves the streak alone -- unobservable is not
            # failure, and counting it would penalise a goal for the camera, not for
            # itself.  Bounded in ``goal_utility``, so this lowers a candidate and never
            # removes it: a starved goal must still be able to come back (§八E).
            progress = progress_moved(self._goal_meters, goals_after, step_goal)
            if step_goal:
                row = goal_utility.entry(self._fairness, str(step_goal))
                if progress is True:
                    row.no_progress_streak = 0
                elif progress is False:
                    row.no_progress_streak += 1
            self._record_episode(
                decision=tick.decision, before=before, execution=tick.execution,
                after=after, verification=verification, started_at=started_at,
                step_id=index,
                goal_id=step_goal,
                # The verifier passed means the action landed.  This says whether the
                # *goal* moved, and the two are not the same statement: 58 episodes
                # passed their verifier while stamina sat at 457 (2026-09-18).
                goal_progress=progress,
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
            if (
                not verification.ok
                and decision.skill in self.LEAVING_SKILLS
                and verification.reason in {"SAFE_BACK_NOT_PROVEN", "FOREIGN_LAYER_NOT_LEFT"}
                and index < max_actions
                and self._leave_retries < self.max_leave_retries
            ):
                # A Back that moved nothing is not a dead cycle, it is the first half of a
                # two-step exit.  Measured live 2026-09-21: KEEP_TRAINING_PRODUCTIVE opened on
                # the alliance chest layer, PRESS_BACK left page ALLIANCE reading ALLIANCE, the
                # verifier answered SAFE_BACK_NOT_PROVEN, and the run ended -- taking every
                # other goal with it.  The failing skill is a statement about ONE layer, which
                # is the same class the SAFE_STOP handover above already refuses to treat as
                # everyone's ending.
                #
                # Nothing new is decided here: the brain owns the ordered exit and answers
                # ``LEAVE_FOREIGN_LAYER`` on the next sight of the same layer, so ``continue``
                # simply lets it take its own second step.  ``max_leave_retries`` is what keeps
                # this from becoming a spin -- the pair itself is bounded at two, and this
                # budget sits above that so a layer that answers neither exit still ends the
                # run honestly instead of burning the whole action budget on retries.
                #
                # Deliberately not a general "retry any failed skill" branch: every other
                # failed verification has either its own measured recovery above or is a real
                # failure that must end the run.  This one is scoped to the leaving skills,
                # where the recovery is the brain's own declared second exit.
                self._leave_retries += 1
                self._runtime(
                    agent_state=AgentState.AUTO_RUNNING.value,
                    reason=f"{decision.skill.lower()}_did_not_move_the_client",
                    next_action="brain_takes_its_second_exit_for_this_layer",
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
                # Operator §二.5 / §二.7, 2026-09-21: one step that did not reach its
                # final state no longer ends the whole run.  Measured cause: the run
                # held one goal, that goal's step failed its verifier, and every other
                # goal lost the cycle with it -- including the ones whose work was
                # unaffected.  The failure is a statement about *this* step, which is
                # the same class the SAFE_STOP handover above already refuses to treat
                # as everyone's ending.
                #
                # What is relaxed, exactly: the cycle is handed to the next goal
                # through the existing ``_yield_to_next_goal`` -- the goal that failed
                # is held back for the rest of the run, so the next iteration selects a
                # *different* task rather than retrying the same step.  That is the
                # operator's "允许尝试其他候选", and it needs no new retry machinery
                # because the brain owns the re-selection.
                #
                # What is NOT relaxed, and each of these was measured by writing it the
                # other way first:
                #
                # * §七.3 "避免重复点击同一错误位置" -- a control that failed its
                #   verifier is recorded in ``_failed_controls`` and never tapped again
                #   in this run.  Without this the handover did exactly what the rule
                #   forbids: the next goal's route landed on the same control and the
                #   same failing tap was issued three times, once per goal.
                # * paid and irreversible outcomes (``is_fatal_stop``), a run out of
                #   action budget, and a repeat budget.  ``_verification_retries`` is
                #   what keeps the handover from becoming a spin.
                #
                # The "do not tap the same control twice" half of §七.3 is enforced
                # earlier, before the executor -- see the guard above ``adb_executor``.
                # Putting it here instead was measured wrong: a check after the tap
                # stops the third attempt while the second, which is the one the rule
                # is about, has already been issued.
                semantic = (tick.execution.action.target or "") if tick.execution is not None else ""
                if semantic:
                    self._failed_controls.setdefault(semantic, verification.reason)
                if (
                    index < max_actions
                    and self._verification_retries < self.max_verification_retries
                    and not is_fatal_stop(verification.reason)
                    and self._yield_to_next_goal(
                        best_goal,
                        deferrals,
                        decision,
                        f"{decision.skill} failed its verifier ({verification.reason}); "
                        f"one step is not the whole run, so this task yields to the next one",
                    )
                ):
                    self._verification_retries += 1
                    self._runtime(
                        agent_state=AgentState.AUTO_RUNNING.value,
                        reason=f"{decision.skill.lower()}_did_not_reach_its_state",
                        next_action="brain_picks_another_task_for_this_cycle",
                        verifier=verification.reason,
                    )
                    continue
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
