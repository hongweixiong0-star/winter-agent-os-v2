from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from typing import Any, Callable, Iterable, Mapping

from .brain import RuleBrain
from . import control_experience
from . import goal_utility
from . import ui_collection
from . import page_knowledge
from . import unknown_advisor
from .executor import Executor
from .executor_router import BackendLedger, RoutingTable, build_router
from .learning import Episode, EpisodeStore
from .models import Decision, ExecutionResult, Page, VerificationResult, WorldState
from .ocr import find_printed_words, find_quick_panel_handle, read_tap_anywhere_instruction
from .camp_training import CAMP_LABELS, CAMP_ORDER
from .scheduler import Scheduler
from .goal_library import GoalLibrary, GoalStateStore, progress_moved, route_for
from .capability_gate import DEFERRED, CapabilityGate, Deferral
from .device_lease import OWNER_DEVELOPMENT_VALIDATION, OWNER_GAMEPLAY, DeviceLease
from .candidate_policy import CandidateAttemptPool
from .skills import SkillRegistry, v2_registry
from .verifier import verify_alliance_reward_dismissed, verify_ally_gift_claim_feedback, verify_intel_hero_dispatched, verify_intel_hero_march_open, verify_intel_hero_target_open, verify_daily_claim_feedback, verify_daily_reward_advanced, verify_daily_tab_selected, verify_exploration_claim_confirmed, verify_exploration_claim_feedback, verify_exploration_reward_dismissed, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_mail_read_or_claim, verify_offline_rewards_claimed, verify_open_alliance, verify_open_alliance_gifts, verify_open_daily, verify_open_exploration, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_training_camp_switched, verify_intel_list_read, verify_alliance_gifts_claimed
from .verifier import verify_ally_gift_claim, verify_beast_card_march_open, verify_beast_card_opened, verify_beast_dispatch, verify_beast_mammoth_target_selected, verify_beast_march_open, verify_beast_scan_observed, verify_beast_search_submitted, verify_beast_search_tab_selected, verify_beast_target_selected, verify_building_upgrade, verify_camp_menu_reobserved, verify_duplicate_target_cancelled, verify_environmental_wait, verify_intel_beast_dispatch, verify_intel_beast_march_open, verify_intel_claim_feedback, verify_intel_mission_selected, verify_intel_pin_opened, verify_intel_rescue_selected, verify_intel_rescue_started, verify_intel_rescue_target_open, verify_intel_reward_dismissed, verify_intel_target_open, verify_left_foreign_layer, verify_mail_alliance_tab_selected, verify_mail_claim_feedback, verify_mail_report_tab_selected, verify_mail_reward_dismissed, verify_mail_system_tab_selected, verify_march_count_readable, verify_march_page_open, verify_march_recall_dialog_open, verify_march_recalled, verify_open_home, verify_open_intel, verify_open_mail, verify_open_map, verify_panel_row_done_collected, verify_panel_row_research_bar_opened, verify_panel_row_task_bar_opened, verify_popup_closed, verify_research_lab_focused, verify_research_page_open, verify_research_started, verify_resource_found, verify_resource_level_relaxed, verify_resource_search_open, verify_resource_selected, verify_free_stamina_claimed, verify_safe_back, verify_stamina_sources_open, verify_training_started, verify_wood_dispatch_from_march, verify_ordinary_control_tried
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


#: Where the client's own names for its controls are written down.
#:
#: This is the one resolver input that is *knowledge* rather than a measurement of this device:
#: per semantic, the words the client prints on the control and the pages it is drawn on.
#: Wiring it in is the operator's rule for the ordinary case -- "no template, no skill, not
#: VERIFIED" must not mean "cannot be located" when the client has drawn the control's own name
#: on the screen being looked at.
#:
#: The client's own "tap anywhere" instruction is obeyed only where the dictionary does not say
#: the control belongs somewhere else.  It needs no further gate, and that is the client's own
#: logic rather than a relaxation: the phrase means *a tap anywhere on this screen dismisses it*,
#: so on such a screen no point can mean anything else.  What it must not do is answer for a
#: control that is declared for a different page -- ``BTN_ATTACK`` declares ["BEAST", "MAP"], so
#: a POPUP frame cannot satisfy it however loudly that popup asks to be tapped.  The page
#: declaration is therefore the whole gate, and it is data.
UI_DICTIONARY_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "ui" / "semantic_dictionary.json"

#: Cached per file *state*, not once per process.  The operator's rule is that ordinary learning
#: should arrive as data, so an edit to the dictionary has to take effect without a code change;
#: keying on mtime gives that inside a long-lived process.  A worker here is a fresh process per
#: cycle anyway, which is the other half of why this is safe.
_UI_DICTIONARY: tuple[float, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = (0.0, {})


def _declared_record(semantic: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """``(pages, the client's words)`` for one semantic, or ``None``.

    ``None`` means the dictionary says nothing about this name -- *not* that the control does
    not exist.  That distinction is load-bearing for the caller: an undeclared control must
    fall through to the layers that remember or derive a position, while a declared control
    whose words are missing from the frame is a control that is not on screen.
    """
    global _UI_DICTIONARY
    stamp = None
    try:
        stamp = UI_DICTIONARY_PATH.stat().st_mtime
    except OSError:
        return None
    if stamp != _UI_DICTIONARY[0]:
        table: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        try:
            payload = json.loads(UI_DICTIONARY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for record in payload.get("records") or ():
            if not isinstance(record, Mapping):
                continue
            name = str(record.get("id") or "")
            if not name:
                continue
            table[name] = (
                tuple(str(page) for page in (record.get("pages") or ())),
                tuple(str(word).strip() for word in (record.get("ocr") or ()) if str(word or "").strip()),
            )
        _UI_DICTIONARY = (stamp, table)
    return _UI_DICTIONARY[1].get(str(semantic))


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
        # The quick panel's row arrows are judged by the state after the tap, never by the tap
        # itself (operator §二: 不得仅以 Brain 输出展开动作或点击成功，代替真实面板展开结果) -- but by
        # the state they *really* produce.  Measured 2026-09-22 23:42:41: a barracks row's arrow
        # opens that barracks' action bar in the city (``training.menu_open``, ``camp`` named,
        # ``train_tap_norm`` present), not the training page; the training page is behind the bar's
        # own 训练 button, which is the next hop.  Binding these to ``verify_training_page_open``
        # made a working tap record FAILURE and the opened bar was abandoned.  Each is bound to its
        # own camp so a look-alike row that opens the wrong barracks is a real failure.
        "OPEN_TASK_FROM_QUICK_PANEL_SHIELD": lambda b, a: verify_panel_row_task_bar_opened(b, a, camp="SHIELD"),
        "OPEN_TASK_FROM_QUICK_PANEL_LANCER": lambda b, a: verify_panel_row_task_bar_opened(b, a, camp="LANCER"),
        "OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN": lambda b, a: verify_panel_row_task_bar_opened(b, a, camp="MARKSMAN"),
        "OPEN_TASK_FROM_QUICK_PANEL_RESEARCH": verify_panel_row_research_bar_opened,
        # Collecting a finished batch, judged by the tick disappearing from that row.
        "COLLECT_FINISHED_TRAINING_SHIELD": lambda b, a: verify_panel_row_done_collected(b, a, row_key="SHIELD_CAMP"),
        "COLLECT_FINISHED_TRAINING_LANCER": lambda b, a: verify_panel_row_done_collected(b, a, row_key="LANCER_CAMP"),
        "COLLECT_FINISHED_TRAINING_MARKSMAN": lambda b, a: verify_panel_row_done_collected(b, a, row_key="MARKSMAN_CAMP"),
        "COLLECT_MY_REWARDS_ROW": lambda b, a: verify_panel_row_done_collected(b, a, row_key="MY_REWARDS"),
        "OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION": verify_ordinary_control_tried,
        "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT": verify_ordinary_control_tried,
        "OPEN_TASK_FROM_QUICK_PANEL_MY_REWARDS": verify_ordinary_control_tried,
        # The hop that did not exist: switch the training page to another barracks when the
        # one on screen has its queue busy.  Operator §八, "一个兵营正在训练，不得阻止其他空闲
        # 兵营执行训练" -- without it the goal stopped at the first busy camp and 矛兵营 /
        # 射手营 were never trained once.
        "SELECT_TRAINING_CAMP": verify_training_camp_switched,
        # The generic ordinary-control attempt (operator directive 2026-09-22, third item).
        # The proof is the observed change itself: the control had no pre-registered
        # expectation to check against, so "did anything the state reader can see move" is
        # the whole verification -- the same classify_change the ledger already runs.
        "TRY_ORDINARY_CONTROL": verify_ordinary_control_tried,
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
        #
        # Measured 2026-09-23: that bound bounds *this* hop and nothing else.  The brain's goal-less
        # fallback makes the opposite hop, is not bounded by anything, and re-opens the cycle the
        # moment the run is back on the page this flag was supposed to have finished with -- so 18 of
        # the 75 runs since 16:00Z were nothing but OPEN_MAP / OPEN_HOME / OPEN_MAP.  ``_barren_pages``
        # below is what makes the bound hold for the pair.
        self._replan_attempted = False
        # Pages this run has stood on with nothing selectable on them.  Read by
        # ``_stop_instead_of_looking_again``: a look-around hop whose destination is already in here
        # is not a look-around, it is a repeat of one.
        self._barren_pages: set[str] = set()
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

        The map's resource-search panel is closed first, because it is drawn over the corner the
        城镇 door lives in while the page still reads MAP (issue #101), so the hop cannot land while
        it is up.  Measured 2026-09-23, and it is why this guard exists: eight consecutive runs --
        seven of them one step long -- took this exact hop, failed ``SEMANTIC_TARGET_NOT_VERIFIED``,
        ended, and were restarted by the panel half a minute later onto the same map.  Six minutes of
        livelock, ended only by an unrelated beast scan panning the map and closing the panel.  The
        brain's seven ``OPEN_HOME`` sites had closed the panel since commit c522bc9; this hop is
        issued by the runtime, so no brain-side guard could ever see it.
        """
        if best_goal is not None or not deferrals or self._replan_attempted or world.page is not Page.MAP:
            return None
        if world.resource_search_open:
            # ``_replan_attempted`` is deliberately not set here: closing a panel is the prerequisite
            # of the hop, not the hop.  The bound that flag exists for -- go home at most once per
            # run, and never while other work is selectable -- is unchanged, and the next step of
            # this same run re-enters this function with the panel gone.
            return Decision(
                "BACK",
                "close_resource_search_before_the_deferral_hop",
                world.confidence,
                "resource_search_closed",
            )
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

    def _stop_instead_of_looking_again(
        self, before: WorldState, decision: Decision, best_goal
    ) -> Decision:
        """A run that has already looked everywhere stops; it does not hop back.

        The failure this exists for is a *pair* of individually correct moves.  The brain's goal-less
        fallback answers ``OPEN_MAP`` on HOME (``first_ready_p0_skill``: "the map is where goals are
        observable") and ``_deferral_replan`` answers ``OPEN_HOME`` on MAP
        (``deferred_..._left_nothing_to_do_here``: "HOME is where the queue goals are readable"), so a
        run with nothing selectable walks one way, then the other, and ends where it began.

        Measured 2026-09-23 with the production reader and the production brain on the recorded frames
        (``tools/replay_run_decisions.py``; the reason is not in the episode stream, and the runtime
        log only keeps the newest run, so the frames are the only remaining witness):

            run 20260923_062948_568906   3/3 replay exactly
              22:30:26  HOME -> MAP   OPEN_MAP    brain.decide          first_ready_p0_skill
              22:31:28  MAP  -> HOME  OPEN_HOME   runtime._deferral_replan
                                                                       deferred_SPEND_STAMINA_ON_BEAST_left_nothing_to_do_here
              22:31:58  HOME -> MAP   OPEN_MAP    brain.decide          first_ready_p0_skill

            18 of the 75 runs since 16:00Z are nothing but this walk; run 20260923_060723_868796 ends
            the same way (steps 20/23/24: OPEN_MAP, OPEN_HOME, OPEN_MAP) after twenty steps of real
            work -- the last two hops are pure loss.

        ``_replan_attempted`` already bounds one half of it.  Its own comment says the bound is "so
        leaving cannot become a two-page ping-pong", and the measurement above is that it cannot:
        bounding one direction of a two-direction cycle leaves the cycle.  What was missing is not a
        second bound but the *memory* -- a hop is only a look-around if the page it lands on has not
        already been looked at this run.

        The rule, and its four deliberate edges:

        * only a step with **no selectable goal** is judged, because that is the only step for which
          the scheduler's silence at this page is known.  A hop carrying a goal is that goal's
          business and is returned untouched;
        * only the two hops whose entire purpose is to look for goals
          (:data:`PAGE_HOPS_THAT_ONLY_LOOK_FOR_GOALS`).  ``OPEN_MAP`` taken by a committed INTEL route
          is a different decision with a different reason, and this guard never sees it;
        * the page the client is standing on is recorded as fruitless whether or not the step is a
          hop, so a run that inspects the map (``CHECK_MARCH``) and finds nothing is remembered the
          same way;
        * the answer is a stop, not another hop.  ``best_goal`` is None, so ``_yield_to_next_goal``
          answers False by its own first line and the run ends with
          :data:`NOTHING_LEFT_TO_LOOK_AT` recorded -- which is the honest "nothing left in this
          cycle", the same sentence the refusal path uses when every goal has been held back once.
        """
        if best_goal is not None:
            return decision
        page = str(getattr(before.page, "value", before.page))
        destination = self.PAGE_HOPS_THAT_ONLY_LOOK_FOR_GOALS.get(str(decision.skill))
        if destination is None or destination not in self._barren_pages:
            self._barren_pages.add(page)
            return decision
        print(
            f"[schedule] {decision.skill} refused on {page}: it lands on {destination}, which this run "
            f"has already stood on with nothing selectable ({sorted(self._barren_pages)}) -- looking "
            f"there again is not looking, it is repeating the look",
            flush=True,
        )
        return Decision("SAFE_STOP", self.NOTHING_LEFT_TO_LOOK_AT, 1.0, "no_action")

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
        # When the step's own verifier named the change, that name is the record -- the ledger and
        # the verifier must not disagree about what happened, which is the same reason
        # ``classify_change`` is shared with the verifier in the first place.  Measured on the
        # 快捷面板 handle: the generic classifier reported NUMBER_CHANGED (its fallback for "the two
        # states differ") while the verifier, which knows what this control does, reported
        # QUICK_PANEL_OPENED -- and the weaker name had been written to the ledger.
        if verification is not None and verification.ok:
            named = str((verification.evidence or {}).get("change") or "")
            if named:
                observed_change = named
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
            verification_ok=bool(verification.ok) if verification is not None else False,
        )
        # The automatic UI collector reads the same evidence, one step later (operator
        # 2026-09-22): the frame this step already captured, the name it was aiming at, and the
        # verifier's own verdict.  It writes candidate records and, once a step's verifier has
        # proven an element's declared effect, a template into the one manifest.  It never
        # observes, decides or clicks on its own, and a bug in it must not cost a run -- hence
        # the swallow, the same trade ``_save_control_experience`` makes.
        try:
            self._collect_ui_evidence(
                decision=decision,
                before=before,
                after=after,
                execution=execution,
                verification=verification,
                observed_change=observed_change,
                before_screenshot=before_screenshot,
                after_screenshot=after_screenshot,
                episode_id=str(getattr(getattr(self, "capture_dir", None), "name", "") or ""),
                goal_id=goal_id,
            )
        except Exception:  # noqa: BLE001 - collection must never fail the step it reads
            pass
        # The same evidence, for the *pages* (operator directive 2026-09-22, "未知页面自主探索"):
        # an unnamed screen is kept with its picture, its title and its controls, and every step
        # that really executed is one learned transition.  Separate try, because the two records
        # are independent -- a page store that cannot be written must not cost the element
        # candidates this step also produced.
        try:
            self._collect_page_evidence(
                decision=decision,
                before=before,
                after=after,
                execution=execution,
                verification=verification,
                observed_change=observed_change,
                before_screenshot=before_screenshot,
                after_screenshot=after_screenshot,
                episode_id=str(getattr(getattr(self, "capture_dir", None), "name", "") or ""),
                goal_id=goal_id,
            )
        except Exception:  # noqa: BLE001 - collection must never fail the step it reads
            pass
        if self.episode_store is None:
            return
        failure = None
        if execution is None or not execution.executed:
            failure = self._failure_type_from(execution)
        elif verification is not None and not verification.ok:
            failure = verification.reason
        episode = Episode(
            skill=decision.skill,
            state_before=state_before,
            action=asdict(execution.action) if execution is not None else {},
            state_after=state_after,
            result="SUCCESS" if failure is None else "FAILURE",
            failure_type=failure,
            decision_reason=str(getattr(decision, "reason", "") or ""),
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
            # The verifier's own evidence, so an audit can read what a step was accepted on instead
            # of reconstructing it from the frames.  Kept verbatim: every verifier already reports
            # the fields it judged (control_before, panel_readable_after, menu_drawn, ...), and
            # dropping them at the write is what left 6574 of 6603 episodes unaccountable.
            verifier_evidence=({} if verification is None else dict(verification.evidence)),
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
        verification_ok: bool = False,
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
        # The one generic skill resolves WHICH control off the frame, so its ledger key has to
        # carry that choice: otherwise every element tried on a page would share one record, and
        # a control that worked could never be told apart from the one beside it.
        if semantic == "ORDINARY_CONTROL":
            last = getattr(self, "_ordinary_last", None) or {}
            if control_experience.label(last.get("page")) == page:
                refined = str(last.get("semantic") or "")
                if refined:
                    semantic = refined
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

        # One real step that reached its expected result is the whole bar for registering an L1
        # action -- the *step*, not the goal and not the skill.  The conditions it holds under,
        # the element's own features, how its region was located, what was issued and what
        # followed are stored; the absolute coordinate is not, because reuse re-derives the point
        # from the frame it is standing on.  The skill registry and the template manifest are
        # separate stores and are deliberately not touched here.
        context = getattr(self, "_l1_context", None)
        if (
            verification_ok
            and execution.executed
            and observed_change not in ("NO_OP", "UNKNOWN")
            and isinstance(context, Mapping)
            and control_experience.label(context.get("page")) == page
            and str(context.get("semantic") or "") == semantic
        ):
            features = control_experience.visual_features(
                text=str(context.get("text") or ""),
                box_norm=context.get("box_norm") if isinstance(context.get("box_norm"), Mapping)
                else None,
                read_from_frame=str(context.get("frame") or ""),
            )
            control_experience.register_l1(
                entry,
                goal=str(context.get("goal") or goal_id or ""),
                state=str(context.get("state") or ""),
                features=features,
                basis=str(context.get("basis") or ""),
                action={
                    "kind": str(getattr(execution.action, "kind", "") or ""),
                    "target": semantic,
                },
                expected_effect=str(context.get("expected_effect") or expected),
                observed_effect=observed_change,
                relocatable=bool(context.get("relocatable")),
            )
            print(
                f"[l1] registered {semantic} on {page} for goal "
                f"{context.get('goal') or goal_id} (basis {context.get('basis')}, effect {observed_change})",
                flush=True,
            )

    def _save_control_experience(self) -> None:
        try:
            control_experience.save(self._control_ledger)
        except Exception:  # noqa: BLE001 - a ledger write must never fail a run
            pass

    # ------------------------------------------------- automatic UI collection

    def _failure_type_from(self, execution: "ExecutionResult | None") -> str:
        """The failure type a step that did not execute gets, with the runtime's refusals named.

        The executor answers ``SEMANTIC_TARGET_NOT_VERIFIED`` whenever the resolver it was handed
        returns no point, and for a named control that is the right sentence: the frame did not show
        it.  For the one generic skill it can be the wrong one, because that resolver can also decline
        a control **the frame does draw** -- it has already been used in this run
        (``ORDINARY_CONTROL_ALREADY_USED_THIS_RUN``).  Recording the executor's verdict there is how a
        policy refusal becomes a puzzle ("the control is not on the frame") for whoever reads the
        failure table next, and how it gets classified as ``UNKNOWN_UI`` -- "the client showed
        something V2 could not read" -- which is a diagnosis no development agent can act on because
        nothing is unreadable.

        Operator §6: two defects with different root causes must not share a reason string.  This is
        that rule at the boundary where the strings are made.
        """
        error = str(getattr(execution, "error", "") or "") if execution is not None else ""
        if execution is None:
            return "NO_EXECUTION"
        declined = getattr(self, "_ordinary_declined", None)
        if (
            error == "SEMANTIC_TARGET_NOT_VERIFIED"
            and isinstance(declined, Mapping)
            and declined.get("reason")
            # ...and nothing was resolved *after* the refusal.  ``_ordinary_last`` is set by every
            # tier that finds a control, so a set one means this step did aim at something -- and for
            # a target that was aimed at, "the frame does not show it" is the true sentence.
            and getattr(self, "_ordinary_last", None) is None
        ):
            return str(declined["reason"])
        return error

    def _ui_store(self) -> "ui_collection.UiCandidateStore | None":
        """The candidate store, created once per run and never allowed to break one."""
        store = getattr(self, "_ui_candidates", None)
        if store is None:
            try:
                store = ui_collection.UiCandidateStore()
            except Exception:  # noqa: BLE001 - collection is optional, playing is not
                store = None
            self._ui_candidates = store
        return store

    def _page_store(self) -> "page_knowledge.PageCandidateStore | None":
        """The page-candidate store, created once per run and never allowed to break one."""
        store = getattr(self, "_ui_pages", None)
        if store is None:
            try:
                store = page_knowledge.PageCandidateStore()
            except Exception:  # noqa: BLE001 - collection is optional, playing is not
                store = None
            self._ui_pages = store
        return store

    def _transitions_store(self) -> "page_knowledge.TransitionLedger | None":
        """The transition ledger, the same one the resolver reads, or ``None``."""
        return getattr(self, "_transitions", None)

    def _page_title_of(self, frame_path: "Path | None") -> str:
        """The client's own largest word in the title band, or ``""``.

        Read only where it is load-bearing -- an unnamed screen, where the title is what keeps two
        of them apart in every key this project writes about pages.  A named page has a better
        identifier already (its label) and is not charged an OCR pass for one.
        """
        if frame_path is None:
            return ""
        ocr = self._ocr_service()
        if ocr is None:
            return ""
        info = page_knowledge.read_title_candidate(frame_path, ocr)
        return str((info or {}).get("text") or "")

    def _collect_page_evidence(
        self,
        *,
        decision: Decision,
        before: WorldState,
        after: "WorldState | None",
        execution: ExecutionResult | None,
        verification: VerificationResult | None,
        observed_change: str,
        before_screenshot: "Path | None",
        after_screenshot: "Path | None",
        episode_id: str,
        goal_id: str,
    ) -> None:
        """Keep what this step showed about *pages*: the unnamed screen, and where the step went.

        Operator directive 2026-09-22 ("未知页面自主探索").  Two records, both fed by the same
        evidence the element collector reads -- the frames this step captured and the verifier's
        own verdict -- and neither of them is allowed to observe, decide or click:

        * **the unnamed screen** (§四).  When either frame is ``Page.UNKNOWN``, the frame, its
          candidate title, its visible controls with boxes, what it was entered from and the
          trigger are written to ``knowledge/perception/pages/<id>/``.  The record is written
          **once per distinct screen** -- a second visit folds into it (attempt counts,
          ``last_seen_at``) instead of copying the picture again, which is both the storage bound
          of §九 and the "do not start over" of §六.
        * **the transition** (§五).  Every step that really executed, from a page this run could
          name, is one row: ``before page -> control -> action -> after page`` plus the verifier's
          verdict.  That row is what the resolver reads on the next visit, so an unnamed screen
          whose 领取 was proven once is tried with 领取 first the next time.

        The page's status and an element's status are separate (§四): a control working on a
        screen does not verify the screen, so ``candidate_page_semantics`` is never rewritten by
        an action result -- only ``recognition_method`` moves, from OCR to ACTION_RESULT.
        """
        store = self._page_store()
        ledger = self._transitions_store()
        label_before = control_experience.label(before.page)
        label_after = control_experience.label(after.page) if after is not None else ""
        # What this run last tried, for §二's "最近尝试的动作、预期结果与实际结果": a question asked about an
        # unnamed screen is much more useful when the reasoner is told what already failed there.
        self._last_attempt_summary = {
            "skill": str(decision.skill or ""),
            "reason": str(decision.reason or ""),
            "expected_result": str(decision.expected_result or ""),
            "executed": bool(execution is not None and execution.executed),
            "observed_change": str(observed_change or ""),
            "verified": bool(verification.ok) if verification is not None else None,
            "verification_reason": str(verification.reason) if verification is not None else "",
        }
        # (1) an unnamed screen, on either side of this step.
        #
        # Only the *before* side is an attempt on the screen: a step that merely landed here
        # (the after side) says nothing about whether this screen can be acted on, and folding it
        # in as a failure is how the first live record came out wrong -- 挂机收益 read FAILED with
        # two failures, both of them the steps that *opened* it from EXPLORATION.  A step that ran
        # on the screen and passed its verifier is what makes the screen VERIFIED (measured
        # 2026-09-22T07:26:34Z: TRY_ORDINARY_CONTROL on 挂机收益, UNKNOWN -> POPUP, SUCCESS).
        executed = execution is not None and bool(execution.executed)
        for state, frame in ((after, after_screenshot), (before, before_screenshot)):
            if state is None or frame is None or state.page is not Page.UNKNOWN:
                continue
            self._stage_unknown_page(
                store=store,
                frame=frame,
                entry_page=label_before if before.known else self._last_known_label,
                entry_trigger=f"{decision.skill}::{str(decision.reason or '')}",
                goal=goal_id or str(self.brain.current_goal or ""),
                episode_id=episode_id,
                world_state={"page": control_experience.label(state.page)},
                attempt=bool(executed and state is before),
                verified=bool(verification.ok) if verification is not None else False,
                observed_change=observed_change,
            )
        # The entry page for a screen reached from another unnamed screen: the last page this run
        # could actually name.  Updated after the read above so a step sees the page it left.
        if before.known:
            self._last_known_label = label_before
        # (2) the transition this step measured, when it really executed something.
        #
        # A step that *begins* on an unnamed screen is recorded too, and that is the interesting
        # one -- "this unnamed screen's 领取 led to EXPLORATION" is exactly the knowledge §五 asks
        # for.  What it needs is a key: a named page has one, and an unnamed screen has one only
        # once its title can be read.  Without a title the row would be filed under the bare label
        # ``UNKNOWN``, which is every unnamed screen at once, so it is not written.
        if (
            ledger is not None
            and execution is not None
            and execution.executed
            and after is not None
        ):
            title_before = self._page_title_of(before_screenshot) if not before.known else ""
            title_after = self._page_title_of(after_screenshot) if not after.known else ""
            if before.known or title_before:
                target = str(getattr(execution.action, "target", "") or "")
                if decision.skill == "TRY_ORDINARY_CONTROL" and self._ordinary_last:
                    control = f"ORDINARY_CONTROL[{self._ordinary_last.get('word', '')}]"
                elif target:
                    control = target
                else:
                    control = decision.skill
                ledger.record(
                    before_page=label_before,
                    before_title=title_before,
                    control=control,
                    after_page=label_after,
                    after_title=title_after,
                    verified=bool(verification.ok) if verification is not None else False,
                    skill=decision.skill,
                    action=str(execution.action.kind or "") if execution.action else "",
                    goal=goal_id or str(self.brain.current_goal or ""),
                    observed_change=observed_change,
                    expected_effect=str(decision.expected_result or ""),
                )
        if store is None:
            return
        try:
            # Saved per step rather than at ``finish``, unlike the element candidates: what this
            # store holds is the *screen itself*, and a worker that dies mid-run (this project's
            # workers are restarted routinely) would otherwise leave the screen unnamed for the
            # next run to rediscover from nothing.  The record set is one per distinct screen, so
            # the write is a few KB; the transition ledger keeps the once-per-run trade, because
            # nothing reads it from disk mid-run.
            store.prune()
            store.save()
        except Exception:  # noqa: BLE001 - a store write must never fail a run
            pass

    def _stage_unknown_page(
        self,
        *,
        store: "page_knowledge.PageCandidateStore | None",
        frame: Path,
        entry_page: str,
        entry_trigger: str,
        goal: str,
        episode_id: str,
        world_state: Mapping[str, Any],
        attempt: bool,
        verified: bool,
        observed_change: str,
    ) -> None:
        """Write one unnamed screen's record, or fold this sighting into the record it has.

        First sighting writes the picture and the reading; every later sighting is an attempt on
        the same screen, which is what ``attempt_count``/``success_count`` and ``last_seen_at``
        are for.  Nothing here needs a template, a skill or a VERIFIED status to *record* a
        screen -- recording is how the screen stops being unknown next time.
        """
        if store is None:
            return
        ocr = self._ocr_service()
        title = ""
        title_confidence: float | None = None
        controls: list[dict[str, Any]] = []
        texts: tuple[str, ...] = ()
        semantics: tuple[str, ...] = ()
        size = None
        if ocr is not None:
            try:
                from .ocr import read_frame_size

                size = read_frame_size(frame)
                result = ocr.recognize(frame)
                info = page_knowledge.read_title_candidate(frame, ocr, size) if size else None
                title = str((info or {}).get("text") or "")
                title_confidence = (info or {}).get("confidence")
                if size:
                    controls = page_knowledge.visible_controls(result.tokens, size)
                texts = page_knowledge.ocr_texts(result.tokens)
                semantics = page_knowledge.suggest_page_semantics(title, texts)
            except (OSError, ValueError):
                pass
        key = page_knowledge.page_key(control_experience.label(Page.UNKNOWN), title)
        # Whatever an on-demand analysis said about this screen travels with it (§五): the picture,
        # the boxes and the candidate semantics end up side by side, and the answer keeps its own
        # field so no reader can mistake a proposal for a measurement.  Matched by request id,
        # which is exactly "this screen, this question".
        advice: tuple[dict[str, Any], ...] = ()
        last_advice = getattr(self, "_last_advice", None)
        if last_advice and last_advice.get("request_id") == unknown_advisor.request_id(
            key, unknown_advisor.UNKNOWN_CONTROL
        ):
            advice = (dict(last_advice),)
        existing = store.find_key(key)
        if existing is not None and (
            not existing.page_image_path or not Path(existing.page_image_path).exists()
        ):
            # A record whose picture is gone cannot answer "what did this screen look like", so
            # this sighting re-stages instead of folding into it.  Measured 2026-09-22: an index
            # outlived its own directory, and until this check every later step re-saved the row
            # and skipped re-capturing the screen -- the record stayed useless forever.
            existing = None
        if existing is None:
            record = store.stage(
                frame_path=frame,
                page_label=control_experience.label(Page.UNKNOWN),
                title=title,
                title_confidence=title_confidence,
                candidate_page_semantics=semantics,
                ocr_texts=texts,
                controls=controls,
                entry_page=entry_page,
                entry_trigger=entry_trigger,
                goal=goal,
                world_state=world_state,
                ai_advice=advice,
                episode=episode_id,
                notes=f"first seen from {entry_page or 'UNKNOWN'} via {entry_trigger}",
            )
            if record is None:
                return
        if attempt:
            store.record_attempt(key=key, verified=verified, observed_effect=observed_change)

    def _record_serves_goal(self, goal: str, served: set[str]) -> bool:
        """Whether the running goal is one a dictionary record serves.

        A record's ``related_goals`` names goal **ids** (``KEEP_TRAINING_PRODUCTIVE``), while
        ``brain.current_goal`` holds the **route** the scheduler derived for this step (``TRAIN``)
        and ``brain.goal_id`` holds the concrete goal.  Comparing those names as strings is false for
        every goal in the project, and that is what left the 快捷面板 handle untappable: the record
        is measured, its reader is measured, the runtime tier that uses it exists, and no step ever
        asked for the tap.

        The list is not extended here.  Which goals belong to a route is the goal library's answer
        (``route_for``) -- the same derivation ``RuleBrain._owns_terminal_page`` uses -- so the three
        per-camp training goals count for the training entry without anyone editing this list, and a
        goal whose route nobody listed is still refused.
        """
        wanted = {item for item in served if item}
        if not wanted:
            return False
        candidates = {
            str(goal or "").strip().upper(),
            str(getattr(getattr(self, "brain", None), "goal_id", "") or "").strip().upper(),
        }
        candidates = {item for item in candidates if item}
        if candidates & wanted:
            return True
        from .goal_library import route_for

        routes = {route_for(item) for item in wanted}
        routes.discard(None)
        return bool(routes) and any(route_for(item) in routes for item in candidates)

    def _declared_goal_words(self, goal: str) -> tuple[str, ...]:
        """The words the dictionary ties to ``goal``, through each record's ``related_goals``.

        A goal is matched by name and by its parts, so ``KEEP_TRAINING_PRODUCTIVE`` also picks up a
        record that declares ``TRAINING``: the ids in this project's goal library are compound, and
        requiring an exact string would make the field useless for half of them.
        """
        wanted = str(goal or "").strip().upper()
        if not wanted:
            return ()
        parts = {part for part in wanted.split("_") if len(part) > 3}
        words: list[str] = []
        for record in self._semantic_records().values():
            declared = {str(item).strip().upper() for item in (record.get("related_goals") or ())}
            if not declared:
                continue
            if wanted in declared or any(part in declared for part in parts):
                words.extend(str(word).strip() for word in (record.get("ocr") or ()))
        return tuple(dict.fromkeys(word for word in words if word))

    def _declared_dictionary_words(self) -> set[str]:
        """Every word the semantic dictionary declares, whatever control it belongs to.

        Needed so the collector never re-stages a control the project already knows under a new
        name -- the dictionary is where "we know this button" lives, and a word in it is not news.
        """
        words: set[str] = set()
        try:
            payload = json.loads(UI_DICTIONARY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return words
        for record in payload.get("records") or ():
            if not isinstance(record, Mapping):
                continue
            for word in record.get("ocr") or ():
                value = str(word or "").strip()
                if value:
                    words.add(value)
        return words

    def _collect_printed_controls(
        self,
        *,
        store: "ui_collection.UiCandidateStore",
        frame: "Path | None",
        page: str,
        goal: str,
        episode_id: str,
        skip_words: Iterable[str],
    ) -> None:
        """Harvest ordinary action words on this frame that nobody has written down yet.

        Every step, because the alternative was measured and did not work: the first version
        rationed the scan to a couple of frames and collected nothing across three production
        cycles, the second sampled every fourth step and missed again (the qualifying frames sat
        at step 22-24 of one run and at 1/6/9 of others).  The cost is why it can be every step --
        0.31 s for a cold OCR pass on a frame the run already captured, 0.000 s when another layer
        already read it, against steps 20-40 s apart.  ``MAX_SCANS_PER_RUN`` stays as a safety
        valve so one pathological frame cannot make collection expensive.
        """
        if frame is None:
            return
        seen = getattr(self, "_ui_scans", 0)
        if seen >= ui_collection.MAX_SCANS_PER_RUN:
            return
        ocr = self._ocr_service()
        if ocr is None:
            return
        self._ui_scans = seen + 1
        try:
            found = ui_collection.find_plain_controls(frame, ocr, skip_words=skip_words)
        except Exception:  # noqa: BLE001 - a scan must never fail the step it rides on
            return
        staged = False
        for hit in found:
            record = store.stage(
                frame_path=frame,
                page=page,
                semantic="",
                box_norm=hit["box_norm"],
                goal=goal,
                episode=episode_id,
                ocr_text=hit["word"],
                ocr_confidence=hit["confidence"],
                recognition_method=ui_collection.METHOD_OCR_WORD,
                semantic_candidates=(f"OCR:{page}:{hit['word']}",),
                notes=(
                    "the client printed an ordinary action word the semantic dictionary does not "
                    "declare; the candidate semantic is a guess from the word and the page and is "
                    "kept unconfirmed until a real step exercises it"
                ),
            )
            staged = staged or record is not None
        if staged:
            store.save()

    def _save_ui_candidates(self) -> None:
        """Persist the candidate index and hold it to its bound, once per run.

        Same single-exit discipline as the ledger above, and the same trade: the shipped copy
        (``_collect_ui_evidence``) saves eagerly because a candidate whose crops exist but whose
        index does not is an orphan file nobody can read, while reaching the cap is a
        whole-run-scale event that belongs here.
        """
        store = getattr(self, "_ui_candidates", None)
        if store is None:
            return
        try:
            store.prune()
            store.save()
        except Exception:  # noqa: BLE001 - a store write must never fail a run
            pass

    def _save_page_candidates(self) -> None:
        """Persist the page candidates and the learned transitions, once per run.

        One write per run rather than one per step, the same trade ``_save_control_experience``
        makes and for the same reason: nothing reads either file mid-run (the resolver reads the
        in-memory ledger), while the whole file is rewritten on every save -- so a per-step write
        would put two processes' full rewrites in the same window and buy nothing.
        """
        store = getattr(self, "_ui_pages", None)
        if store is not None:
            try:
                store.prune()
                store.save()
            except Exception:  # noqa: BLE001 - a store write must never fail a run
                pass
        ledger = getattr(self, "_transitions", None)
        if ledger is not None:
            try:
                ledger.save()
            except Exception:  # noqa: BLE001 - a ledger write must never fail a run
                pass

    def _collect_ui_evidence(
        self,
        *,
        decision: Decision,
        before: WorldState,
        after: "WorldState | None",
        execution: ExecutionResult | None,
        verification: VerificationResult | None,
        observed_change: str,
        before_screenshot: "Path | None",
        after_screenshot: "Path | None",
        episode_id: str,
        goal_id: str,
    ) -> None:
        """Turn the evidence this step already paid for into a UI candidate (operator 2026-09-22).

        Four cases, and they are the four the directive names; nothing here observes, decides or
        clicks:

        (a) **named but unlocatable** -- template, ledger and printed words all failed, so the
            step died with ``SEMANTIC_TARGET_NOT_VERIFIED``.  The record keeps the page, the name
            and the frame; no crop, because no region was measured (inventing one is the mistake
            the directive forbids).
        (b) **located by the client's own printed words on this frame** -- there IS a measured
            region (the token's box), so the element and its context are cropped, and the step's
            own verifier decides whether that becomes a ``VERIFIED`` candidate.
        (c) **exercised** -- an executed step on a page that already has candidates for this
            semantic folds its outcome in: attempts counted, and a passed verifier promotes.
        (d) **promotion to a template** -- only for a candidate a step's verifier proved, only
            when the crop carries no countdown, and never over a protected record (the refusal
            is reported, not swallowed).

        The page is part of every key: the same icon on two pages is two controls, and a record
        that merged them would let one page's evidence answer for the other.
        """
        store = self._ui_store()
        if store is None:
            return
        page = control_experience.label(before.page)
        frame = after_screenshot or before_screenshot
        goal = goal_id or str(self.brain.current_goal or "")

        # (e) the positive source, and it runs first on purpose: it needs nothing to have gone
        # wrong, so gating it behind "this step aimed at a named control" would leave it silent
        # on exactly the steps that see the most of the game -- a BACK, an OBSERVE, a navigation
        # hop all carry a frame, and a frame is all this needs.  Bounded per run
        # (``MAX_SCANS_PER_RUN``) and skipped for words the dictionary already declares.
        self._collect_printed_controls(
            store=store,
            frame=frame,
            page=page,
            goal=goal,
            episode_id=episode_id,
            skip_words=self._declared_dictionary_words(),
        )

        target = ((execution.action.target if execution is not None else "") or "").strip()
        if not target:
            skill = self.registry.get(decision.skill)
            target = ((skill.action.target if skill is not None else "") or "").strip()
        if not target:
            return
        if target == "ORDINARY_CONTROL":
            # The one generic skill resolves WHICH control off the frame, so the name this
            # collector files it under has to carry that word.  Without it the two halves of the
            # same read never meet -- the resolver files the box as ``ORDINARY_CONTROL[领取]``
            # while this looks up ``ORDINARY_CONTROL`` -- and the unnamed screen's element
            # candidate is silently lost.  Measured 2026-09-22 on the live 挂机收益 frame: the
            # resolver returned the client's own 领取, `_printed_boxes` held the box, and no
            # candidate was written.
            chosen = str((getattr(self, "_ordinary_last", None) or {}).get("word") or "")
            if chosen:
                target = f"ORDINARY_CONTROL[{chosen}]"
        expected = decision.expected_result or ""

        # (a) named and unlocatable
        #
        # ...but not when the runtime declined the control by name: "unlocated" means no reader could
        # find it, and this case is the opposite -- the frame drew it, the runtime measured it, and
        # then refused to use it again.  Staging it as unlocated would file a false candidate (and the
        # collector's whole output is read as evidence of what the client shows).
        not_executed = execution is None or not execution.executed
        declined = getattr(self, "_ordinary_declined", None)
        declined_by_name = (
            isinstance(declined, Mapping)
            and bool(declined.get("reason"))
            and getattr(self, "_ordinary_last", None) is None
        )
        if (
            not_executed
            and not declined_by_name
            and (execution is None or execution.error == "SEMANTIC_TARGET_NOT_VERIFIED")
        ):
            store.stage_unlocated(
                page=page,
                semantic=target,
                goal=goal,
                episode=episode_id,
                source_frame=str(before_screenshot or ""),
                expected_effect=expected,
            )
            store.save()
            return

        proved = (
            verification is not None
            and verification.ok
            and observed_change not in ("NO_OP", "UNKNOWN")
        )

        # (b) located by the client's own words on this frame
        printed = (getattr(self, "_printed_boxes", None) or {}).get(f"{page}|{target}")
        if printed is not None and frame is not None:
            record = store.stage(
                frame_path=frame,
                page=page,
                semantic=target,
                box_norm=printed.get("box_norm") or {},
                goal=goal,
                episode=episode_id,
                ocr_text=str(printed.get("word") or ""),
                ocr_confidence=printed.get("confidence"),
                recognition_method=ui_collection.METHOD_OCR_WORD,
                expected_effect=expected,
                notes=(
                    "located on this frame by the client's own printed words; the element box is "
                    "that text padded to a control-sized region"
                ),
            )
            if record is not None:
                store.record_attempt(
                    page=page,
                    semantic=target,
                    verified=proved,
                    observed_effect=observed_change,
                    expected_effect=expected,
                )
                if proved:
                    store.ingest(record, ocr_text=str(printed.get("word") or ""))
                store.save()
                return

        # (c)/(d) fold an executed step's outcome into whatever is already known
        if execution is not None and execution.executed:
            touched = store.record_attempt(
                page=page,
                semantic=target,
                verified=proved,
                observed_effect=observed_change,
                expected_effect=expected,
            )
            for record in touched:
                if record.verification_status == ui_collection.STATUS_VERIFIED and not record.template_version:
                    store.ingest(record, ocr_text=record.ocr_text)
            if touched:
                store.save()

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

    def _observe(self, frame_path: Path) -> "WorldState":
        """Look at the screen once, with this step's goal deciding what is worth the seconds.

        Operator directive 2026-09-22 ("Goal 驱动的视觉注意力优化").  Everything the observation does
        is unchanged -- the full-frame classification, the popup detection, the risk checks -- and the
        attention only decides the *order and scope of the expensive lookups*:

        * the goal being pursued comes from the brain, and the page hint is the last page this run
          could actually **name** (``_last_known_label``).  A page is not a coordinate, so nothing
          here is a remembered position (§二);
        * the vision uses that to skip the map-field sweeps when the goal is not about the map and the
          last confirmed page was not the map -- the sweeps are the only lookups that cost seconds
          (measured: one of them, ``TARGET_INTEL_BEAST_MISSION``, is 3.6-3.8 s of a 6.2 s
          observation);
        * **and it widens by itself**: when a skipped sweep left the frame unnamed, the same frame is
          observed again with every sweep allowed, which is §五's 扩大观察范围 as a path through the
          code rather than a promise.  That second pass costs only the sweeps, because the per-frame
          answers are keyed to the picture and the chain is not repeated.

        A vision that has no ``focus`` (a test stub, a replay vision) is observed exactly as before.
        """
        vision = self.vision
        focus = getattr(vision, "focus", None)
        if focus is None:
            return vision.observe(frame_path)
        goal = str(getattr(getattr(self, "brain", None), "current_goal", "") or "")
        page_hint = str(getattr(self, "_last_known_label", "") or "")

        def look(*, widen: bool, reason: str):
            focus(goal=goal, page_hint=page_hint, reason=reason, widen=widen)
            return vision.observe(frame_path)

        state = look(widen=False, reason=f"goal {goal or '(none)'} from {page_hint or '(nowhere)'}")
        skipped = getattr(vision, "sweeps_skipped", None)
        pending = skipped() if callable(skipped) else {}
        if pending:
            # Audible whether or not it changes the outcome.  An attention that can only be seen when
            # it fails is an attention nobody can confirm is running -- and the directive is explicit
            # that this has to be verified as participating in the live observation, not inferred.
            print(
                f"[attention] {page_hint or '(no page)'} + goal {goal or '(none)'}: skipped "
                f"{len(pending)} map sweep(s) on this frame",
                flush=True,
            )
        if pending and state.page is Page.UNKNOWN:
            # §五: the focused look did not find a page, so the focus was too narrow and the full
            # observation is what happens next -- same frame, sweeps allowed, answers reused.
            print(
                f"[attention] {page_hint or '(no page)'} + goal {goal or '(none)'}: skipped "
                f"{len(pending)} map sweep(s) and the frame stayed unnamed -- widening to the full "
                f"look",
                flush=True,
            )
            state = look(widen=True, reason="widening after an unnamed frame")
        return state

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
        if semantic == "BTN_OPEN_TRAINING_FROM_CAMP":
            # The 训练 control of the selected camp, tapped where this frame's own OCR read
            # the client's label (see ``ocr.read_selected_building_actions``).
            #
            # Why not the template: ``BTN_OPEN_TRAINING_FROM_CAMP`` was cut from the older
            # rendering -- the camp highlighted with a radial menu -- and on the client of
            # 2026-09-22 it scores NO MATCH on the screen it names.  The label, read at
            # 0.986-0.997 across ten live frames spanning seven hours, is drawn by the
            # client at the control it belongs to, which is why it is the durable answer:
            # it moves with the layout instead of assuming it.
            #
            # The guard is that the frame must still be showing that bar: the point is a
            # fragment of the frame it was read from, and a frame whose reading carries no
            # ``train_tap_norm`` never had a 训练 control on it.  ``None`` -- wrong page,
            # no reading, or a point outside the frame -- ends the step honestly rather
            # than tapping an invented coordinate, which is also what stops a 训练 label
            # read on some later screen from being reused here.
            if frame.page is not Page.HOME:
                return None
            point = (frame.training or {}).get("train_tap_norm")
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return None
            return (x_norm, y_norm)
        if semantic == "ORDINARY_CONTROL":
            # The generic ordinary-control attempt (operator directive 2026-09-22, third
            # item): the brain said an unregistered control should be tried, and WHERE is
            # answered by this frame alone -- the client's own printed words, screened by
            # a whitelist of ordinary actions and a blacklist of spend words.  No
            # template, no ledger, no remembered coordinate can answer for a control that
            # was never registered, and none is consulted here: a screen that names
            # nothing tap-safe ends the step honestly instead of tapping an invented
            # point.
            return self._ordinary_control_candidate(frame, frame_path)
        if semantic == "TRAINING_CAMP_NEXT":
            # Another barracks on the training page, tapped where this frame drew its tab.
            #
            # Why a derived target and not three named controls: the page draws all three tab
            # labels at once on every camp page, so a template or a remembered coordinate cannot
            # say which one to tap -- only "which page am I on" can, and that is the title
            # (``camp_open_label``).  Choosing the *next* camp in the client's own order is what
            # keeps one busy barracks from ending the goal, and it needs no per-camp route.
            #
            # Measured 2026-09-22 on the live training page (720x1280): 盾兵营 (134,1260),
            # 矛兵营 (361,1260), 射手营 (586,1260), read at 0.990-0.997.
            #
            # The guard is that the frame must still be the training page AND must carry the
            # tabs' own positions: a point is a fragment of the frame it was measured on.  ``None``
            # -- wrong page, or a page whose tabs could not be read -- ends the step honestly
            # rather than tapping an invented coordinate.
            if frame.page is not Page.TRAINING:
                return None
            tabs = (frame.training or {}).get("camp_tab_norm") or {}
            if not isinstance(tabs, Mapping) or not tabs:
                return None
            present = [CAMP_LABELS[camp] for camp in CAMP_ORDER if CAMP_LABELS.get(camp) in tabs]
            if not present:
                return None
            # The goal's own pick first.  The brain chose it from the camps' measured
            # states (operator directive 2026-09-22: never switch mechanically), and it
            # is consulted only when the brain still wants it this frame -- a label the
            # tabs no longer draw cannot be tapped, so that falls through to the frame's
            # own order below rather than tapping an absent control.
            desired = getattr(getattr(self, "brain", None), "desired_camp_label", None)
            if isinstance(desired, str) and desired in present:
                point = tabs.get(desired)
                if isinstance(point, (tuple, list)) and len(point) == 2:
                    try:
                        x_norm, y_norm = float(point[0]), float(point[1])
                    except (TypeError, ValueError):
                        point = None
                    if point is not None and 0.0 <= float(point[0]) <= 1.0 and 0.0 <= float(point[1]) <= 1.0:
                        return (float(point[0]), float(point[1]))
            open_label = str((frame.training or {}).get("camp_open_label") or "")
            if open_label in present:
                at = present.index(open_label)
                candidates = present[at + 1:] + present[:at]
            else:
                # The open camp is unknown, so the first tab is as good a choice as any -- and
                # tapping it cannot make the situation worse than not acting at all.
                candidates = present
            for label in candidates:
                point = tabs.get(label)
                if isinstance(point, (tuple, list)) and len(point) == 2:
                    try:
                        x_norm, y_norm = float(point[0]), float(point[1])
                    except (TypeError, ValueError):
                        continue
                    if 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0:
                        return (x_norm, y_norm)
            return None
        match = self._semantic.find(frame_path, semantic) if frame_path is not None else None
        if match:
            return match.center_norm
        # The Exploration chest is animated and its perceptual hash
        # varies between frames. A reviewed normalized fallback is
        # allowed only after independent page + green-state proof.
        if semantic == "BTN_EXPLORATION_IDLE_CLAIM" and frame.page.value == "EXPLORATION" and frame.exploration.get("status") == "CLAIMABLE":
            return (0.86, 0.68)
        if semantic == "BTN_START_TRAINING":
            # The training page's own 训练 button, located from that frame's reading.
            #
            # It sits after the template and before the word scan, and both halves are measured:
            #
            # * after the template, because a frame the project can already read must keep resolving
            #   that way.  ``dataset/raw/live_train_selection_available.png`` resolves the button
            #   through the template tier, its reading carries no ``train_button_norm``, and an
            #   earlier version of this block ran *before* the template and returned None there --
            #   caught by the project's own test, in a frame that had worked for months.
            # * before the word scan, because that scan answers **ABSENT** when the client's word
            #   cannot be read, and ABSENT stops the chain rather than falling through (see the
            #   comment below).  The client paints its own hand cursor on this button as soon as the
            #   camp is entered, so on exactly the frame this exists for the word is unreadable while
            #   the button is drawn -- measured 2026-09-23 00:48:35 in the directed ``--goal TRAIN``
            #   run (20260923_004710_train_step_005_before_...png): the panel's 矛兵 row arrow opened
            #   that camp's bar, the bar opened this training page, the reading said AVAILABLE /
            #   trainable / BUTTON_CAPTION with the caption ``02:33:11`` at (0.760, 0.888), the brain
            #   emitted TRAIN_TROOPS, and the tap target resolved to nothing.
            #
            # What it answers with is the frame's own reading, so a page that drew no button leaves
            # this silent rather than tapping a remembered coordinate.
            if frame.page is Page.TRAINING:
                point = (frame.training or {}).get("train_button_norm")
                if isinstance(point, (tuple, list)) and len(point) == 2:
                    try:
                        x_norm, y_norm = float(point[0]), float(point[1])
                    except (TypeError, ValueError):
                        x_norm = y_norm = -1.0
                    if 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0:
                        return (x_norm, y_norm)
        # The client's own drawing of the control, tried before anything remembered.  Order is
        # the argument: a printed word or instruction is a statement about *this* frame, while
        # the ledger below is a coordinate measured on an earlier one.  The weaker layer is
        # consulted only when the stronger one has no opinion -- and ``ABSENT`` is how the
        # stronger one says it has an opinion and the answer is "not on this screen", which is
        # why it must stop here rather than fall through.  See ``_client_printed_control`` for
        # the frame that establishes it (a covered navigation bar whose remembered point would
        # have landed on 自动狩猎).
        # A quick-panel row's control is the blue arrow at the row's right edge, and it is read from
        # *this* frame (``panel["rows"][].arrow_norm``).  It is answered here, before the word scan,
        # because for these semantics the client's own word names the **row** and not the control: the
        # records' ``ocr`` field is 矛兵 / 科技研究, drawn in the panel's text column, so the scan below
        # found the label and never the button.  Measured 2026-09-23 across every panel-row tap in
        # ``learning/executor_backend.jsonl``: ``tap_point`` x was 225 (0.3125) on all of them while the
        # row's arrow is at x ~480 (0.666) -- and the same coordinate opened a barracks' action bar once
        # and left the city for the world map the next time, because it is the row's text.
        #
        # Ordering argument, same as the one below: this is a reading of the frame in hand, which is
        # stronger than a coordinate remembered from an earlier frame, so it must not be behind the
        # ledger either.
        if semantic.startswith("QUICK_PANEL_ROW_"):
            row_point = self._dictionary_hint(semantic, frame, frame_path)
            if row_point is not None:
                return row_point
        verdict, printed = self._client_printed_control(semantic, frame, frame_path)
        if verdict == "FOUND":
            return printed
        if verdict == "ABSENT":
            return None
        remembered = self._remembered_control_center(semantic, frame)
        if remembered is not None:
            return remembered
        # The weakest layer of all, and the only one that reads the semantic dictionary's own
        # ``position_hint`` (operator directive 2026-09-22 item 一: a field added to the file has to
        # have a reader).  A control the project has declared but cannot find -- no template yet, no
        # ledger entry, no printed word, no answer -- is still reachable, with the basis it was
        # located by recorded in ``_printed_reads`` so nobody can mistake a declared hint for a
        # measurement.  ``ABSENT``, the spend blacklist and the page gate all still apply.
        hinted = self._dictionary_hint(semantic, frame, frame_path)
        if hinted is not None:
            return hinted
        return None
        return None

    #: The ordinary actions this layer may try without a registered skill, in the
    #: client's own words (operator directive 2026-09-22, third item).  Each is an
    #: action whose worst measured cost in this project's vocabulary is LOW: a claim,
    #: a navigation, an open.  Deliberately absent: anything that can spend a resource
    #: or confirm a dialog (挑战 / 捐献 / 升级 / 扫荡 / 确认 all belong to registered,
    #: verifier-bound skills).
    #: Defined once, in ``ui_collection``, because the collector reads the same list to decide
    #: what is worth harvesting: a second copy here would let the two disagree about which
    #: printed words this project acts on.
    ORDINARY_CONTROL_WORDS: tuple[str, ...] = ui_collection.PLAIN_ACTION_WORDS

    #: The names this runtime gives the *gates* of the declared-control tier when one of them refuses.
    #:
    #: Named rather than left to the executor's generic verdict, for the same reason ``brain.py``'s
    #: unaffordable-dispatch branch exists ("Refusing here records what actually happened instead"):
    #: the executor answers ``SEMANTIC_TARGET_NOT_VERIFIED`` -- "the frame names no control" -- for
    #: *any* resolver that returns no point, and every gate below refuses a control the frame draws.
    #: Measured 2026-09-23 over the 69 live attempts of ``TRY_ORDINARY_CONTROL``
    #: (``tools/probe_ordinary_control_resolution.py``): 31 failed and all 31 were recorded as
    #: "the frame names no control"; for 15 of them the frame demonstrably draws the collapsed handle
    #: (7 refused by "already used this run", 8 by one of the structural gates below).
    #:
    #: Classification follows the names: none ends in ``escalation_queue``'s UI-unread suffixes, so
    #: they stop being reported as ``UNKNOWN_UI`` -- "the client showed something V2 could not read" --
    #: which is a diagnosis nothing can act on, because nothing is unreadable.
    ORDINARY_CONTROL_DECLINES: dict[str, str] = {
        # Measured: this run already tapped this control on this page, and a control already pressed
        # is not pressed again in the same run (operator §七.3).  The frame is fine; the run is not
        # allowed to use it twice.
        "already_used": "ORDINARY_CONTROL_ALREADY_USED_THIS_RUN",
        # The record says which pages the control exists on, and this is not one of them.
        "not_on_page": "ORDINARY_CONTROL_NOT_ON_THIS_PAGE",
        # The record names the goals the control serves (by goal id or by route); this run is another.
        "not_for_goal": "ORDINARY_CONTROL_NOT_FOR_THIS_GOAL",
        # The record's own risk is not one this project explores.
        "risk": "ORDINARY_CONTROL_RISK_NOT_EXPLORABLE",
        # The client has already drawn it in the state the goal wanted, so toggling it would undo
        # that state.
        "already_open": "ORDINARY_CONTROL_ALREADY_OPEN",
    }

    #: The two hops whose only reason to exist is "there may be goals on the other page".
    #:
    #: They are the ends of one pair, and that is the whole point of listing them: each is right on
    #: its own and the two together are a cycle.  The brain's goal-less fallback answers ``OPEN_MAP``
    #: on HOME ("the map is where goals are observable"), and ``_deferral_replan`` answers
    #: ``OPEN_HOME`` on MAP ("HOME is where the queue goals are readable"), so a run with nothing
    #: selectable walks one way and then the other for as long as its step budget lasts.  Measured
    #: 2026-09-23 (``tools/replay_run_decisions.py``, production vision + production brain on the
    #: recorded frames): run ``20260923_062948_568906`` replays 3/3 exactly -- OPEN_MAP by
    #: ``brain.decide`` / ``first_ready_p0_skill``, OPEN_HOME by ``runtime._deferral_replan`` /
    #: ``deferred_SPEND_STAMINA_ON_BEAST_left_nothing_to_do_here``, OPEN_MAP again by the same
    #: fallback -- and 18 of the 75 runs since 16:00Z are nothing but this walk.
    #:
    #: The value is the page the hop lands on, which is what the skill's own name says.  Read by
    #: ``_stop_instead_of_looking_again`` and by nothing else; it is a statement about what these two
    #: names mean, not a second route table (``goal_library.GOAL_ROUTES`` still owns which goal goes
    #: where).
    PAGE_HOPS_THAT_ONLY_LOOK_FOR_GOALS: dict[str, str] = {
        "OPEN_MAP": "MAP",
        "OPEN_HOME": "HOME",
    }

    #: The honest end of a run that has already stood on every page it can reach and been offered
    #: nothing there.  Not a refusal by a goal -- so not a reason to hand the cycle on, which is what
    #: ``NON_FATAL_STOPS`` is for -- and not a fault either: it is the answer to "what is left?".
    NOTHING_LEFT_TO_LOOK_AT = "every_page_this_run_was_fruitless"

    #: Words that refuse a candidate outright, wherever they appear on the frame: the
    #: real-money and irreversible boundary the directive restates ("保留真实货币、高代价
    #: 及不可逆风险操作限制").  The scan checks the whole token list, not just the hit,
    #: so a control named 免费领取 that sits on a dialog whose title says 特惠 is refused.
    ORDINARY_CONTROL_REFUSED_WORDS: tuple[str, ...] = (
        "充值",
        "购买",
        "支付",
        "钻石",
        "礼包",
        "特惠",
        "首充",
        "月卡",
        "基金",
        "招募",
        "加速",
        "花费",
        "消费",
        "立即完成",
    )

    #: The client's own way out of a screen, tried on an *unnamed* page after the goal's own
    #: words (operator §一: "如果页面无法理解或确实无法推进当前 Goal，则尝试已有的可靠返回路径",
    #: and §三 names the case outright -- "UNKNOWN 页面中出现明确的'返回'按钮，可以尝试返回").
    #:
    #: Deliberately not used on a named page: there, a registered skill or the brain owns
    #: navigation, and a wholesale 返回 tap would fight it.  The bare ✕ the client draws beside
    #: these is *not* in the list and is recorded rather than tapped (see page_knowledge), because
    #: a one-glyph word at confidence 0.776 is not a measured control -- the system Back key this
    #: project already trusts (STABLE, 97.6%) is what closes those screens.
    UNKNOWN_PAGE_EXIT_WORDS: tuple[str, ...] = tuple(page_knowledge.BACK_WORDS)

    def _semantic_records(self) -> dict[str, dict]:
        """The semantic dictionary as ``id -> record``, read once per run.

        The dictionary has declared this project's controls since before this layer existed, and
        until now the runtime read exactly one field of it -- ``ocr``, as the set of words that are
        not news.  This is the reader the directive's first requirement asks for, and the four
        consumers below are what use it: ``position_hint``, ``states``, ``related_goals`` and
        ``expected_transition``.
        """
        cached = getattr(self, "_semantic_records_cache", None)
        if cached is not None:
            return cached
        records: dict[str, dict] = {}
        try:
            payload = json.loads(UI_DICTIONARY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        for record in payload.get("records") or ():
            if isinstance(record, Mapping) and record.get("id"):
                records[str(record["id"])] = dict(record)
        self._semantic_records_cache = records
        return records

    def _declared_expectation(self, semantic: str, default: str = "") -> str:
        """What the dictionary says acting on this control should change, or ``default``.

        Consumes ``expected_transition``: an L1 step registered through this function records the
        *declared* expectation beside the effect that really followed, so the two can be compared
        later without re-reading the dictionary.
        """
        record = self._semantic_records().get(semantic) or {}
        declared = str(record.get("expected_transition") or "").strip()
        return declared or default

    def _dictionary_hint(
        self, semantic: str, frame: "WorldState", frame_path: "Path | None"
    ) -> tuple[float, float] | None:
        """Where the dictionary says this control is, or ``None`` (directive item 一 / item 四).

        Two kinds of hint are honoured, and both are ``PANEL_RELATIVE``/``ROW_RELATIVE`` rather
        than a screen coordinate:

        * a **row** of the quick panel (``QUICK_PANEL_ROW_<KEY>``): its point is the panel's own
          right-hand column on that row's live y, which is what ties an arrow to its task;
        * the **handle** (``QUICK_PANEL_HANDLE``): the panel's right edge at the block's middle --
          and it refuses outright while the panel is already in the state the record's
          ``expected_transition`` describes, because a tap there would close what the goal wants to
          read.  That refusal is ``states`` being consumed: what the record names as a state is
          matched against what the frame reads.

        A hint whose basis is a single-frame measurement is used as-is and labelled as such.  No
        hint is ever consulted for a semantic the dictionary does not declare, and a page gate that
        excludes the current page is honoured.
        """
        record = self._semantic_records().get(semantic)
        if not record:
            return None
        pages = [str(page) for page in (record.get("pages") or ())]
        page = control_experience.label(frame.page)
        if pages and page not in pages:
            return None
        hint = record.get("position_hint") or {}
        if not isinstance(hint, Mapping):
            return None
        basis = str(hint.get("basis") or "")
        panel = getattr(frame, "quick_panel", None) or {}
        point: tuple[float, float] | None = None

        if semantic.startswith("QUICK_PANEL_ROW_"):
            key = semantic[len("QUICK_PANEL_ROW_"):]
            # ``<KEY>_DONE`` asks for the row's done-marker instead of its enter-arrow: one row can
            # carry both kinds of task, and the tick's point is written only by a frame that drew one.
            want_done = key.endswith("_DONE")
            if want_done:
                key = key[: -len("_DONE")]
            for row in panel.get("rows") or ():
                if str(row.get("key")) != key:
                    continue
                if want_done:
                    point = row.get("done_norm")
                else:
                    point = row.get("arrow_norm")
                if isinstance(point, (tuple, list)) and len(point) == 2 and point:
                    point = (float(point[0]), float(point[1]))
                    break
                point = None
            if point is None:
                return None
        elif semantic == "QUICK_PANEL_HANDLE":
            handle = panel.get("handle") or {}
            if not handle:
                # The panel is not drawn, or not read: there is nothing to toggle from here.
                return None
            declared_states = record.get("states") or {}
            reached = str(handle.get("state") or "")
            body = declared_states.get(reached) if isinstance(declared_states, Mapping) else None
            satisfied = bool(body.get("satisfies_target_state")) if isinstance(body, Mapping) else False
            if reached and satisfied:
                print(
                    f"[hint] {semantic} refused: the panel is already {reached} "
                    f"(the goal wants it read, not toggled)",
                    flush=True,
                )
                return None
            point = tuple(float(value) for value in (handle.get("point_norm") or ())[:2])
            if len(point) != 2:
                return None
        else:
            values: list[float] = []
            for axis in ("x", "y"):
                raw = str(hint.get(axis) or "").strip()
                if not raw:
                    return None
                # A measurement can be a point (0.212) or a range (0.125-0.196, as the two quick
                # panel tabs are recorded): a range resolves to its centre, which is where a tap on
                # that control belongs.
                try:
                    if "-" in raw[1:]:
                        low, _, high = raw[1:].partition("-")
                        values.append((float(raw[0] + low) + float(high)) / 2.0)
                    else:
                        values.append(float(raw))
                except ValueError:
                    return None
            if len(values) != 2 or not (0.0 <= values[0] <= 1.0 and 0.0 <= values[1] <= 1.0):
                return None
            point = (values[0], values[1])

        if point is None or not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0):
            return None
        self._note_printed(
            semantic,
            page_knowledge.page_key(page, str((hint.get("anchor") or hint.get("basis") or ""))),
            f"the semantic dictionary's {basis or 'position_hint'} ({hint.get('anchor') or 'declared'})",
            point,
            label=page,
        )
        print(
            f"[hint] {semantic} located by the dictionary's {basis or 'position_hint'} "
            f"@ {point[0]:.4f},{point[1]:.4f}",
            flush=True,
        )
        return point

    def _ordinary_control_candidate(
        self, frame: "WorldState", frame_path: "Path | None"
    ) -> tuple[float, float] | None:
        """One tap-safe ordinary control this frame names, or ``None`` when it names none.

        Operator directive 2026-09-22, third item: an unregistered ordinary control must
        be attemptable through the existing executor -- no per-button skill, no brain
        hard-coding, no second execution chain.  The evidence is the strongest a control
        without a template can have: the client printed its name on this frame, read by
        the same exact-match OCR the declared controls use.

        The gates, in order:

        * known page, real frame, real OCR -- anything else cannot name a control;
        * the run's bounds -- at most ``MAX_ORDINARY_ATTEMPTS`` taps, and never the same
          ``(page, word)`` twice (operator §七.3: a tap that did nothing is not repeated);
        * the spend blacklist over every token the frame carries -- one refused word
          anywhere on the screen stops the whole attempt, because a whitelist word on a
          purchase dialog is exactly the trap the directive forbids walking into;
        * the whitelist, first untried hit wins.

        ``None`` also sets the brain's ``ordinary_scan_exhausted``, so the fallback
        stops asking this run for a tap the frames cannot name.

        Operator directive 2026-09-22 ("未知页面自主探索"): this used to require ``frame.known``,
        so an unnamed screen refused every control at once however clearly the client had drawn
        one.  Measured: 31 of the 87 steps that landed on ``UNKNOWN`` landed on 挂机收益, whose own
        largest control is 领取 and whose goal was to claim it.  The screen is now read like any
        other -- its title comes from ``page_knowledge`` and its controls from the same exact-match
        OCR -- while the two screens that genuinely cannot be tapped (maintenance, loading) still
        refuse.

        The learned reuse (§五/§六) rides here rather than in a second mechanism: the transition
        ledger says which control on *this screen* really left it and which one did nothing, so the
        order below prefers the first and skips the second instead of rediscovering the page.
        """
        if frame_path is None:
            return None
        # Cleared at the very top, before every early return: a refusal belongs to the call that made
        # it, and a step that resolved nothing must not inherit the previous step's reason any more
        # than it may inherit its control (``_ordinary_last`` is cleared for the same reason below).
        self._ordinary_declined = None
        if frame.page in (Page.MAINTENANCE, Page.LOADING):
            return None
        ocr = self._ocr_service()
        if ocr is None:
            return None
        if self._ordinary_attempts >= self.MAX_ORDINARY_ATTEMPTS:
            brain = getattr(self, "brain", None)
            if brain is not None:
                brain.ordinary_scan_exhausted = True
            return None
        page = control_experience.label(frame.page)
        unnamed = not frame.known
        title = ""
        # Which word this step chose, for the transition ledger: cleared first, so a step that
        # resolves nothing cannot be credited with the previous step's control.  The L1 evidence
        # is cleared with it, for the same reason: a step that resolved nothing must not register
        # what an earlier step proved.
        self._ordinary_last = None
        self._l1_context = None
        if unnamed:
            # The title is what keeps two unnamed screens apart in the ledger key and in a
            # question's id, so it is read before anything is asked about this screen.  One cached
            # OCR pass.
            title_info = page_knowledge.read_title_candidate(frame_path, ocr)
            title = str((title_info or {}).get("text") or "")
        # One OCR pass, cached by the service; the blacklist is checked over every
        # token so a spend word anywhere on the screen vetoes the attempt.
        try:
            tokens = [(t.text or "").strip() for t in ocr.recognize(frame_path).tokens]
        except (OSError, ValueError):
            return None
        joined = "".join(tokens)
        spend_refused = any(refused and refused in joined for refused in self.ORDINARY_CONTROL_REFUSED_WORDS)
        # A control the dictionary declares -- and declares as non-spending -- is judged by its own
        # identity, not by words printed elsewhere on the screen (operator directive 2026-09-22 §五:
        # 页面上出现"钻石""加速""购买"等文字，不代表这个页面上的返回、关闭或普通查看动作全部禁止).
        #
        # Measured, and it is why this had to change: the city view's own event entries print 首充 and
        # 玉魄流光礼包, so the veto below fired on *every* city frame and the whole ordinary-control path
        # was dead on the one screen the 快捷面板 handle lives on.  The rule now matches the directive:
        # the veto still covers every control this project names by its words (whitelist, interactive
        # boxes, on-demand answers), while a declared control carries its own risk and is refused by it.
        if frame.known:
            declared = self._declared_textless_control_point(page, title, frame)
            if declared is not None:
                return declared
        if spend_refused:
            # A screen that mentions a spend word is not tapped *by this tier*: neither a printed
            # word nor an ordinary hypothesis may press it, and that boundary is unchanged.  What
            # the follow-up directive §五 removes is the refusal of the whole page: such a screen
            # can still be understood, so the on-demand analysis runs here and its candidate is
            # judged on the candidate itself (``_advice_risk``) -- 关闭 or 返回 on a page that sells
            # gems is allowed through, and an answer pointing at the purchase is refused.  Every
            # other gate is unchanged: the device lease, the page check, the attempt budget and the
            # executor's own bounds.
            if unnamed:
                advised = self._advised_control(
                    page,
                    "",
                    frame_path,
                    frame,
                    unnamed=True,
                    confidence=float(frame.confidence or 0.0),
                )
                if advised is not None:
                    return advised
            brain = getattr(self, "brain", None)
            if brain is not None:
                brain.ordinary_scan_exhausted = True
            return None
        # (1) L1 reuse (operator directive 2026-09-22 section 11).  A single-step action
        # registered for this page, goal and state, whose element is *still drawn on this frame*,
        # is taken before anything is identified again -- that is what makes the second visit
        # cheaper than the first.  A frame that no longer draws it matches nothing, which is the
        # same sentence's "current frame does not match -> identify again", and the caller then
        # falls through to the tiers below.
        # Recorded before the tiers run, so a registration made by a tier that does not itself
        # receive the frame path (the declared-control tier) still knows which frame it proved its
        # action on -- the same discipline the printed tiers keep.
        self._l1_frame_hint = str(frame_path)
        reused = self._l1_action_point(
            page, title, frame, frame_path, ocr, tokens, spend_refused=spend_refused
        )
        if reused is not None:
            return reused
        order = self._ordinary_word_order(page, title, unnamed=unnamed)
        for word in order:
            if (page, word) in self._ordinary_tried:
                continue
            hit = find_printed_words(frame_path, (word,), ocr)
            if hit is None:
                continue
            self._ordinary_tried.add((page, word))
            self._ordinary_attempts += 1
            point = (float(hit["center_norm"][0]), float(hit["center_norm"][1]))
            self._ordinary_last = {
                "page": page,
                "title": title,
                "word": word,
                "point": (round(point[0], 4), round(point[1], 4)),
                "semantic": f"ORDINARY_CONTROL[{word}]",
                "basis": "PRINTED_WORD",
                "source": "PRINTED_WORD",
            }
            # Every tier that resolves a control leaves the same evidence behind, so a step that
            # proves what the control does registers an L1 action whichever tier found it -- the
            # directive's §七 is about the *step*, not about which reader supplied the point.
            self._l1_context = {
                "page": page,
                "goal": str(getattr(getattr(self, "brain", None), "current_goal", "") or ""),
                "state": self._l1_state(frame, title),
                "semantic": f"ORDINARY_CONTROL[{word}]",
                "text": word,
                "box_norm": dict(hit.get("box_norm") or {}),
                "basis": "PRINTED_WORD",
                "source": "PRINTED_WORD",
                "confidence": float(hit.get("confidence") or 0.0),
                "frame": str(frame_path),
                # What the dictionary says this control should do, beside what really happened.
                "expected_effect": self._declared_expectation(f"ORDINARY_CONTROL[{word}]"),
            }
            self._stage_interaction_candidate(
                page=page,
                title=title,
                goal=str(getattr(getattr(self, "brain", None), "current_goal", "") or ""),
                frame_path=frame_path,
                word=word,
                box_norm=dict(hit.get("box_norm") or {}),
                confidence=float(hit.get("confidence") or 0.0),
                basis="PRINTED_WORD",
                source="PRINTED_WORD",
            )
            self._note_printed(
                f"ORDINARY_CONTROL[{word}]",
                page_knowledge.page_key(page, title),
                f"the client's own printed {word!r}",
                point,
                box_norm=hit.get("box_norm"),
                text=word,
                confidence=hit.get("confidence"),
                # The label, so the element collector can file the crop under the same key it
                # looks up -- an unnamed screen's element candidates would otherwise be lost.
                label=page,
            )
            return point
        # (2.6) A control the semantic dictionary declares for this page that is drawn **without any
        # words at all**.  Operator 2026-09-22: 我用红色圈起来的地方就是快捷面板把手，点进去就可以
        # 看到很多功能快捷入口和状态等信息.  Every tier above resolves a control by what is written on
        # it, so a control with no text could not be resolved by any of them -- and the project's own
        # answer to that has always been "a registered crop plus a match", which is what the dictionary
        # record now carries (``locator``, read by ``ocr.find_quick_panel_handle``).
        #
        # Three things bound it, and all three come from the record rather than from this call site:
        # the record names the pages it exists on, the goals it serves, and the reader that locates
        # it.  A goal the record does not list cannot reach it, so this cannot hijack a route: it is
        # the last deterministic option before the on-demand analysis, and it costs one attribute read
        # when the vision layer already looked.
        declared = self._declared_textless_control_point(page, title, frame)
        if declared is not None:
            return declared

        # (3) The general case the directive asks for (sections 1-3): a control this frame draws,
        # that the semantic dictionary does not declare, that looks interactive from its own box
        # and wording, and whose words belong to the goal being pursued.  No whitelist, no skill,
        # no template -- and it is filed as a CANDIDATE *before* the tap (section 6), so the region
        # is on record even if the step never finishes.
        interactive = self._interactive_control_point(page, title, frame, frame_path, ocr)
        if interactive is not None:
            return interactive

        # Only now, with every method this project already has exhausted, does the on-demand
        # analysis get asked (directive §一: 现有方法足以推断就直接用，不足才调用 AI).  On a named
        # page it is not consulted at all: a named page's controls are the registry's business.
        if unnamed:
            # The bookkeeping an advised tap needs -- the ledger key, the L1 evidence, the attempt
            # count -- is done inside ``_advised_control``, so both callers (this one and the
            # spend-screen pass above) leave the same record behind and neither can drift.
            advised = self._advised_control(
                page, title, frame_path, frame, unnamed=True, confidence=float(frame.confidence or 0.0)
            )
            if advised is not None:
                return advised
        brain = getattr(self, "brain", None)
        if brain is not None:
            brain.ordinary_scan_exhausted = True
        return None

    def _advised_control(
        self,
        page: str,
        title: str,
        frame_path: Path,
        frame: "WorldState",
        unnamed: bool,
        confidence: float = 0.0,
    ) -> tuple[float, float] | None:
        """An on-demand reasoner's candidate for this screen, when one has already answered.

        Operator directive 2026-09-22 ("复用现有 UNKNOWN，接入按需 AI 分析"), extended by the same
        day's follow-up ("UNKNOWN AI 求助通道补齐").  This runs **after** every method the project
        already has -- templates, the ledger, the client's own printed words -- has failed, which is
        §一's order exactly:

            如果现有 OCR、模板、语义词典或历史经验已经足以推断下一步，直接使用现有 MAA 执行，不必调用 AI

        Four properties, each a rule from the directive rather than a preference:

        * **it cannot block.**  There is no call here -- an answer is a file that either exists or
          does not, so "正式 AUTO 不等待 AI 回复" is true by construction, and a request with no
          answer simply leaves the cycle to the chain that already works.
        * **it cannot invent a control.**  §三 allows three kinds of locating basis and all three are
          measured on *this* frame: a text box the OCR read, a template this project collected
          found here (``ui_collection.template_regions``), or a region derived from a text box by a
          bounded offset (``ui_collection.anchored_region``).  A point matching none of them is an
          unmeasured coordinate and is refused.
        * **it cannot be used on the wrong screen.**  §四: the request carries the page, the goal,
          the state signature and the frame; an answer whose screen or purpose has changed is filed
          as knowledge and re-asked, never acted on.
        * **it is judged on the candidate, not on the page.**  §五: the risk check is applied to the
          element being pressed (``_advice_risk``), so an answer may point at 关闭 on a page that
          sells gems, while an answer that points at the purchase itself is refused.

        The question is filed when there is no answer yet, so a WorkBuddy session reading
        ``learning/unknown_requests/`` -- or the dispatcher that asks one for it -- has something to
        answer.
        """
        advisor = getattr(self, "_advisor", None)
        if advisor is None:
            return None
        key = page_knowledge.page_key(page, title)
        goal = str(getattr(getattr(self, "brain", None), "current_goal", "") or "")
        situation = self._l1_state(frame, title)
        # Serialised once: the request needs it as the world state, the state signature and the
        # character are read out of it, and ``to_dict`` on a whole WorldState is not free on a path
        # that runs on every step of an unnamed screen.
        observed = frame.to_dict()
        player = observed.get("player")
        ocr = self._ocr_service()
        regions, boxes, texts, template_note = self._advice_evidence(page, frame_path, ocr)
        request = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL,
            page_label=page,
            page_key=key,
            frame_path=frame_path,
            goal=goal,
            page_confidence=confidence,
            ocr_texts=texts,
            ocr_boxes=boxes,
            entry_page=getattr(self, "_last_known_label", ""),
            world_state=observed,
            situation=situation,
            character=str(player.get("name")) if isinstance(player, Mapping) else "",
            template_match=template_note,
            ledger_match="; ".join(
                f"{control}->{row.after_page}"
                for row in (
                    getattr(getattr(self, "_transitions", None), "rows_for", lambda *a, **k: [])(page, title)
                    or []
                )
                for control in (row.control,)
            ),
            last_attempt=dict(getattr(self, "_last_attempt_summary", {}) or {}),
            question=(
                f"这张屏幕（页面模型读作 {page}，标题 {title or '未读出'}）上，与当前 Goal {goal or '(未定)'} "
                "相关的普通低风险控件在哪里？请给出定位依据与 proposed_action。"
            ),
        )
        advice = advisor.take(request.request_id, registry=self.registry)
        if advice is None:
            if advisor.ask(request) and unnamed:
                print(
                    f"[advisor] asked for help on {key}: {request.request_id} "
                    f"(no answer yet; the cycle continues without one)",
                    flush=True,
                )
            return None

        # §四: the answer has to be about *this* screen and *this* purpose.  An answer to a question
        # asked on another screen is knowledge about that screen, not an instruction for this one.
        stale = unknown_advisor.advice_staleness(
            advice, advisor.read_request(request.request_id), page_key=key, goal=goal
        )
        if stale:
            print(
                f"[advisor] {request.request_id}: the answer was made for a different screen or goal "
                f"({stale}); filed and re-asked, nothing is tapped",
                flush=True,
            )
            self._advice_knowledge(
                advice, key, page, note=f"stale:{stale}", frame_path=frame_path
            )
            advisor.ask(request, force=True)
            return None

        # §三: the third basis has to be resolved against *this* frame's own text before it can
        # justify anything, and it joins the same pool as the measured ones.  An answer that is only
        # an anchor carries no coordinate, so the region the anchor produced is what names the point.
        anchor_point: tuple[float, float] | None = None
        if advice.target_anchor:
            anchored = ui_collection.anchored_region(advice.target_anchor, regions)
            if anchored is not None:
                # Prepended, not appended: this region is the one the answer asked for, derived from
                # a text box this frame really drew, so it outranks a generic box that merely
                # overlaps it.  Measured on the real 燃霜矿区 frame: appending put the icon above 说明
                # behind a stray one-character OCR box 3 px away, and the tap was named after that
                # box instead of after the icon.
                regions = [anchored] + list(regions)
                box = anchored.get("box_norm") or {}
                anchor_point = (
                    round(float(box.get("x_norm", 0.0)) + float(box.get("w_norm", 0.0)) / 2, 4),
                    round(float(box.get("y_norm", 0.0)) + float(box.get("h_norm", 0.0)) / 2, 4),
                )
                print(
                    f"[advisor] {request.request_id}: the answer's anchor "
                    f"{str(advice.target_anchor.get('text'))!r} is on this frame -> "
                    f"{anchored['box_norm']}",
                    flush=True,
                )
        region = unknown_advisor.grounded_region(
            advice, regions, points=[anchor_point] if anchor_point else ()
        )
        if region is None:
            print(
                f"[advisor] {request.request_id}: the answer's point is over nothing this frame "
                f"measured -- refused, nothing is tapped",
                flush=True,
            )
            self._advice_knowledge(advice, key, page, note="ungrounded", frame_path=frame_path)
            return None
        point = (float(region["point"][0]), float(region["point"][1]))
        basis = str(region.get("basis") or "")

        # §五: the boundary is on *this candidate*, not on the page it sits on.
        reason = self._advice_risk(advice, region)
        if reason:
            print(
                f"[advisor] {request.request_id}: {reason} -- understood, filed, not tapped",
                flush=True,
            )
            self._advice_knowledge(advice, key, page, note=f"risk:{reason}", frame_path=frame_path)
            return None

        semantic = self._advice_semantic(advice, region)
        box_norm = dict(region.get("box_norm") or {})
        self._last_advice = {
            "request_id": request.request_id,
            "unknown_type": advice.unknown_type,
            "candidate_semantics": list(advice.candidate_semantics),
            "proposed_action": advice.proposed_action,
            "action_kind": advice.action_kind,
            "target_semantics": advice.target_semantics,
            "expected_result": advice.expected_result,
            "uncertainty": advice.uncertainty,
            "note": advice.note,
            "target_point": [point[0], point[1]],
            "basis": basis,
            "basis_detail": dict(region.get("detail") or {}),
            "box_norm": box_norm,
            "source": advice.source,
        }
        self._ordinary_tried.add((page, semantic))
        self._ordinary_attempts += 1
        self._ordinary_last = {
            "page": page,
            "title": title,
            "word": str(advice.proposed_action or ""),
            "point": (round(point[0], 4), round(point[1], 4)),
            "semantic": semantic,
            "basis": f"AI_ADVICE/{basis}",
            "source": "AI_ADVICE",
            "box_norm": box_norm,
        }
        # The advice's own region travels with it, so an advised tap registers an L1 action exactly
        # like a measured one -- while the answer itself stays a proposal in the page record.
        self._l1_context = {
            "page": page,
            "goal": goal,
            "state": situation,
            "semantic": semantic,
            "text": str(region.get("text") or advice.target_semantics or ""),
            "box_norm": box_norm,
            "basis": f"AI_ADVICE/{basis}",
            "source": "AI_ADVICE",
            "confidence": 0.0,
            "frame": str(frame_path),
        }
        self._note_printed(
            semantic,
            key,
            f"the on-demand analysis of {key} (basis {basis}, uncertainty: "
            f"{advice.uncertainty or 'unstated'})",
            point,
            box_norm=box_norm or None,
            text=str(region.get("text") or ""),
            confidence=float(region.get("score") or 0.0) or None,
            label=page,
        )
        print(
            f"[advisor] {request.request_id}: {advice.action_kind} -> {semantic} at "
            f"{point[0]:.4f},{point[1]:.4f} (basis {basis})",
            flush=True,
        )
        return point

    def _advice_evidence(
        self,
        page: str,
        frame_path: Path,
        ocr,
    ) -> tuple[list[dict], list[dict], tuple[str, ...], str]:
        """Everything this frame can justify a point with, and the record of it (§三).

        One place builds the three bases -- the text this frame read, the templates this project
        already collected and can find here, and (from a later step, against these) a region derived
        from one of those text boxes.  The request carries the first and a summary of the second, so
        a reasoner is told what the AUTO has already found rather than being asked to rediscover it.
        """
        regions: list[dict] = []
        boxes: list[dict] = []
        texts: tuple[str, ...] = ()
        note = ""
        if ocr is not None:
            try:
                regions = ui_collection.grounding_regions(frame_path, ocr)
                texts = tuple(
                    str(region.get("text") or "") for region in regions if region.get("text")
                )
                boxes = [
                    {
                        "text": str(region.get("text") or ""),
                        "confidence": float(region.get("score") or 0.0),
                        **dict(region.get("box_norm") or {}),
                    }
                    for region in regions
                    if region.get("text")
                ]
            except (OSError, ValueError, AttributeError):
                regions, boxes, texts = [], [], ()
        templates: list[dict] = []
        try:
            candidates = getattr(self, "_ui_store", lambda: None)()
            if candidates is not None:
                templates.extend(
                    ui_collection.template_entries_from_candidates(candidates.all(), page=page)
                )
        except Exception:  # noqa: BLE001 - collection must never fail a step
            pass
        try:
            templates.extend(
                ui_collection.template_entries_from_experience(
                    (getattr(self, "_control_ledger", {}) or {}).values(), page=page
                )
            )
        except Exception:  # noqa: BLE001
            pass
        if templates:
            try:
                hits = ui_collection.template_regions(frame_path, templates)
            except Exception:  # noqa: BLE001
                hits = []
            if hits:
                regions = list(regions) + hits
                note = "; ".join(
                    f"{hit['detail'].get('semantic') or 'template'}@{hit['score']}"
                    f"({hit['detail'].get('source')})"
                    for hit in hits
                )
        return regions, boxes, texts, note

    def _advice_risk(self, advice, region: Mapping[str, Any]) -> str:
        """Why this *candidate* may not be pressed, or ``""`` (§五).

        The boundary is the same list the ordinary-control resolver carries, but it is applied to
        the thing being pressed -- the anchored region's own wording, and the element the answer
        named -- instead of to every word on the screen.  A page that mentions 钻石 therefore stays
        analysable: an answer that points at 关闭 is accepted and an answer that points at the
        gem offer is refused, which is the distinction the directive asks for.  Real-money payment
        and unauthorised high-value or irreversible operations stay refused outright, and nothing
        here reaches the device lease, the page check or the executor's bounds.
        """
        identity = " ".join(
            [
                str(region.get("text") or ""),
                str(advice.target_semantics or ""),
                str(advice.grounding_ref or ""),
            ]
        ).lower()
        for word in unknown_advisor.REFUSED_WORDS:
            if word.lower() in identity:
                return f"the candidate itself is {word!r}"
        return ""

    def _advice_semantic(self, advice, region: Mapping[str, Any]) -> str:
        """What this advised tap is called in the ledger, in the project's own vocabulary.

        The naming is what lets an advised step be *learned* rather than re-asked: an answer that
        names a real element on the screen is filed as ``ORDINARY_CONTROL[<its own word>]``, which is
        the same key the interactive tier and the L1 reuse use -- so the next visit reuses the proven
        action with no reasoner involved.  An answer whose element has no wording at all (a textless
        icon anchored to a label) keeps its own ``AI_ADVICE`` name, because there is no screen word
        to key a reuse on.

        The word chosen is the **region's own text**, not the reasoner's label for the element, and
        that is deliberate: reuse requires the recorded wording to be among the words the next frame
        draws, so a key the screen never prints could never be found again.  What the reasoner called
        the element is kept beside it in ``_last_advice["target_semantics"]`` rather than replacing
        the screen's own word here.
        """
        if advice.action_kind == unknown_advisor.ACTION_L1:
            target = unknown_advisor.l1_target(advice.proposed_action)
            if target:
                return target
        word = str(region.get("text") or "").strip()
        if advice.action_kind == unknown_advisor.ACTION_ORDINARY and word:
            return f"ORDINARY_CONTROL[{word}]"
        return f"AI_ADVICE[{advice.proposed_action}]"

    def _advice_knowledge(
        self,
        advice,
        key: str,
        page: str,
        *,
        note: str,
        frame_path: Path,
    ) -> None:
        """Keep a reasoner answer that was *not* acted on, with why (§四/§五).

        A stale answer is still a claim about a screen this project has seen, and the directive says
        so: 过期建议可以保存为知识候选.  It is filed through the same ``_last_advice`` channel the
        page record already reads, with the reason it was not used, so the record says both what was
        answered and that nothing was pressed because of it.
        """
        self._last_advice = {
            "request_id": str(getattr(advice, "request_id", "") or ""),
            "unknown_type": str(getattr(advice, "unknown_type", "") or ""),
            "candidate_semantics": list(getattr(advice, "candidate_semantics", ()) or ()),
            "proposed_action": str(getattr(advice, "proposed_action", "") or ""),
            "action_kind": str(getattr(advice, "action_kind", "") or ""),
            "expected_result": str(getattr(advice, "expected_result", "") or ""),
            "uncertainty": str(getattr(advice, "uncertainty", "") or ""),
            "note": str(getattr(advice, "note", "") or ""),
            "filed_only": note,
            "source": str(getattr(advice, "source", "") or ""),
            "frame": str(frame_path),
        }

    def _ordinary_word_order(self, page: str, title: str, *, unnamed: bool) -> list[str]:
        """Which printed words to try on this screen, best evidence first.

        The order is what makes a second visit to the same screen cheaper than the first, and
        every step of it is a measured statement rather than a preference:

        * a control the transition ledger recorded as *really leaving this screen* comes first;
        * a control whose recorded attempts on this screen all did nothing is dropped -- that is
          §七.3 ("一次点击无响应时... 不得反复盲点同一位置") answered from the record rather than
          from a run-scoped set;
        * then the ordinary whitelist in its own order;
        * and on an unnamed screen only, the client's own exit words last (§一/§三).
        """
        ledger = getattr(self, "_transitions", None)
        learned: list[str] = []
        failed: set[str] = set()
        if ledger is not None:
            for control in ledger.preferred_controls(page, title):
                word = page_knowledge.word_from_control(control)
                if word and word not in learned:
                    learned.append(word)
            failed = {
                page_knowledge.word_from_control(control)
                for control in ledger.failed_controls(page, title)
            }
        order = [word for word in learned if word in self.ORDINARY_CONTROL_WORDS]
        order += [word for word in self.ORDINARY_CONTROL_WORDS if word not in order]
        if unnamed:
            order += [word for word in self.UNKNOWN_PAGE_EXIT_WORDS if word not in order]
        return [word for word in order if word not in failed]

    def _relocate_textless_control(
        self,
        entry,
        page: str,
        title: str,
        frame: "WorldState",
        frame_path: Path,
    ) -> tuple[float, float] | None:
        """Re-run the reader a textless L1 action was measured with, on the current frame.

        The record names its own ``basis`` (``HANDLE_TRIANGLE_SCAN`` for the 快捷面板 handle), and
        that is the reader to run -- so the second visit costs one scan and no guessing, and the point
        it returns belongs to the picture in front of us.  Reuse still obeys everything the printed
        path obeys: the same page, goal and state have to hold (``l1_for`` already decided that), the
        element has to still be drawn, and ``(page, semantic)`` is only tried once in a run.
        """
        basis = str(getattr(entry, "basis", "") or "")
        if basis != "HANDLE_TRIANGLE_SCAN":
            return None
        # No spend check here on purpose: this control has no wording, so the words printed elsewhere
        # on the frame say nothing about it, and the action it performs (a panel toggle) spends
        # nothing.  What is pressed is still bounded -- it is the tab the frame draws at its own left
        # edge, located by measurement on the frame it is about to be pressed on.
        handle = find_quick_panel_handle(frame_path, panel_open=False)
        if handle is None:
            print(
                f"[l1] {entry.control} is registered for {page} but this frame does not draw the "
                f"handle any more; re-identifying instead",
                flush=True,
            )
            return None
        if str(handle.get("state") or "") != "COLLAPSED":
            return None
        if (page, entry.control) in self._ordinary_tried:
            return None
        point = (round(float(handle["point_norm"][0]), 4), round(float(handle["point_norm"][1]), 4))
        self._ordinary_tried.add((page, entry.control))
        self._ordinary_attempts += 1
        self._ordinary_last = {
            "page": page,
            "title": title,
            "word": entry.control,
            "point": point,
            "semantic": entry.control,
            "basis": basis,
            "source": "L1_REUSE",
            "box_norm": dict(handle.get("box_norm") or {}),
        }
        print(
            f"[l1] reusing {entry.control} on {page_knowledge.page_key(page, title)} "
            f"@ {point[0]:.4f},{point[1]:.4f} -- re-located on this frame with {basis}",
            flush=True,
        )
        return point

    def _l1_state(self, frame: "WorldState", title: str) -> str:
        """The state a registration is conditional on, including *which* unnamed screen.

        ``state_signature`` reads the frame's own fields -- page, popup, and the two sub-states this
        client switches inside a page.  An unnamed screen has none of those, so every one of them
        would share the signature ``UNKNOWN`` and a registration made on 战斗已结束 would look like it
        applied to any other screen the model could not name.  The title the page reader already
        produced is what tells two unnamed screens apart -- it is what the page records and the
        transition ledger are keyed by -- so it joins the signature here.

        Registration and lookup both go through this one function, so the two can never hold
        different notions of "the same state".
        """
        state = control_experience.state_signature(frame.to_dict())
        if not frame.known and title:
            return f"{state}#{title}"
        return state

    def _declared_textless_control_point(
        self,
        page: str,
        title: str,
        frame: "WorldState",
    ) -> tuple[float, float] | None:
        """Tap a control the dictionary declares and this frame draws without words.

        The point is the one the vision layer **measured on this frame**,
        ``quick_panel.handle.point_norm``, whose basis says which reader produced it
        (``HANDLE_TRIANGLE_SCAN`` for the triangle scan).  Nothing here stores a position: if the
        frame does not draw the control, there is no handle in the reading and this returns ``None``,
        which is the same sentence the L1 reuse honours -- 当前画面不匹配时重新识别.

        The gates are the record's own, not this function's invention:

        * ``pages`` -- the record says where the control exists, and ``QUICK_PANEL_HANDLE`` names
          HOME and MAP.  A page that is not listed is not a page this control is on.
        * ``related_goals`` -- the reason to toggle the panel is the goal that needs what is inside
          it, and the operator lists them (training and research productivity).  Without a listed
          goal a tap here would be curiosity, which is not a thing a route should spend on.
        * ``states`` -- the same consumption the dictionary hint already does.  A state whose own
          record says it satisfies the target state (``EXPANDED`` satisfies ``QUICK_PANEL_OPEN``) is
          refused, which is what keeps "已经展开时直接读取状态，不重复点击" true.
        """
        goal = str(getattr(getattr(self, "brain", None), "current_goal", "") or "")
        if not goal:
            return None
        panel = getattr(frame, "quick_panel", None)
        if not isinstance(panel, Mapping):
            return None
        handle = panel.get("handle")
        if not isinstance(handle, Mapping):
            return None
        point_values = handle.get("point_norm")
        if not isinstance(point_values, (list, tuple)) or len(point_values) < 2:
            return None
        try:
            point = (round(float(point_values[0]), 4), round(float(point_values[1]), 4))
        except (TypeError, ValueError):
            return None
        if not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0):
            return None

        page_label = control_experience.label(page)

        def _declined(gate: str, semantic: str = "") -> None:
            """Name the gate that refused, once.

            The first gate to refuse is the reason reported: a later gate's answer would describe a
            control this one already ruled out, and the report has to name the cause that actually
            decided the step.  Every gate below is a refusal of a control the frame *draws* -- that is
            what makes the executor's generic "the frame names no control" the wrong sentence.

            ``getattr`` rather than a bare read: several harnesses call this method directly on a
            runtime built with ``object.__new__``, so a refusal must not require a run-scoped
            attribute to already exist.
            """
            if getattr(self, "_ordinary_declined", None) is None:
                self._ordinary_declined = {
                    "reason": self.ORDINARY_CONTROL_DECLINES[gate],
                    "semantic": str(semantic),
                    "page": str(page_label),
                }

        for semantic, record in self._semantic_records().items():
            locator = record.get("locator")
            if not isinstance(locator, Mapping) or str(locator.get("state_field") or "") != "quick_panel.handle":
                continue
            pages = [str(item) for item in (record.get("pages") or ())]
            if pages and page_label not in pages:
                print(
                    f"[declared] {semantic} refused: its record names {pages}, not {page_label}",
                    flush=True,
                )
                _declined("not_on_page", semantic)
                continue
            served = {str(item).strip().upper() for item in (record.get("related_goals") or ())}
            if not self._record_serves_goal(goal, served):
                print(
                    f"[declared] {semantic} refused: its record serves {sorted(served)}, and this run "
                    f"is {goal or '(no goal)'}",
                    flush=True,
                )
                _declined("not_for_goal", semantic)
                continue
            risk = str(record.get("risk") or "").upper()
            if risk not in control_experience.EXPLORABLE_RISKS:
                print(
                    f"[declared] {semantic} refused: its record declares risk {risk or '(none)'}, "
                    f"which is not one of {sorted(control_experience.EXPLORABLE_RISKS)}",
                    flush=True,
                )
                _declined("risk", semantic)
                continue
            states = record.get("states") or {}
            reached = str(handle.get("state") or "")
            body = states.get(reached) if isinstance(states, Mapping) else None
            if isinstance(body, Mapping) and bool(body.get("satisfies_target_state")):
                print(
                    f"[declared] {semantic} not tapped: the panel is already {reached} "
                    f"(the goal wants it read, not toggled)",
                    flush=True,
                )
                _declined("already_open", semantic)
                return None
            if (page_label, semantic) in self._ordinary_tried:
                # The frame draws it; this run has already used it.  Refusing is right -- a control
                # that was already pressed is not pressed again in the same run (operator §七.3).
                print(
                    f"[declared] {semantic} not tapped: this run already used it on {page_label} "
                    f"({len(self._ordinary_tried)} control(s) used this run)",
                    flush=True,
                )
                _declined("already_used", semantic)
                return None
            self._ordinary_tried.add((page_label, semantic))
            self._ordinary_attempts += 1
            box = handle.get("box_norm")
            box_norm = dict(box) if isinstance(box, Mapping) else {}
            basis = str(handle.get("basis") or locator.get("basis") or "DECLARED_CONTROL")
            self._ordinary_last = {
                "page": page_label,
                "title": title,
                "word": semantic,
                "point": point,
                "semantic": semantic,
                "basis": basis,
                "source": "DECLARED_CONTROL",
                "box_norm": box_norm,
            }
            self._l1_context = {
                "page": page_label,
                "goal": goal,
                "state": self._l1_state(frame, title),
                "semantic": semantic,
                "text": "",
                "box_norm": box_norm,
                "basis": basis,
                "source": "DECLARED_CONTROL",
                "confidence": 1.0,
                # This control is drawn with no words, so the registration has to say how it can be
                # found again: ``basis`` names the reader, and that is what turns "no wording" from
                # "cannot be re-confirmed" into "re-confirmed by measurement on the next frame".
                "relocatable": True,
                "frame": str(getattr(self, "_l1_frame_hint", "") or ""),
                "expected_effect": self._declared_expectation(semantic),
            }
            print(
                f"[declared] {page_knowledge.page_key(page_label, title)}: {semantic} is drawn "
                f"without words at {point[0]:.4f},{point[1]:.4f} (basis {basis}); tapping it for "
                f"goal {goal}",
                flush=True,
            )
            return point
        return None

    def _l1_action_point(
        self,
        page: str,
        title: str,
        frame: "WorldState",
        frame_path: Path,
        ocr,
        present_words: list[str],
        spend_refused: bool = False,
    ) -> tuple[float, float] | None:
        """Tap the L1 action already registered for this page, goal and state (directive section 11).

        The registration is a claim about a *control*, not about a coordinate, so the point is
        re-derived from this frame's own box for the element's wording.  That is the whole reason
        the record keeps ``visual_features`` instead of a stored position (section 8): the element
        is confirmed to be on the current picture before the tap, and the tap lands where the
        current picture draws it.

        Everything that made the first attempt safe still applies: the spend blacklist was checked
        over every word of this frame before this ran, the run's attempt budget is shared with the
        other tiers, and ``(page, word)`` is never used twice in one run.
        """
        goal = str(getattr(getattr(self, "brain", None), "current_goal", "") or "")
        if not goal:
            return None
        state = self._l1_state(frame, title)
        entry = control_experience.l1_for(
            self._control_ledger,
            page=page,
            goal=goal,
            state=state,
            present_words=present_words,
        )
        if entry is None:
            return None
        word = str(entry.visual_features.get("text") or "").strip()
        if not word:
            # A control with no wording cannot be looked up by wording.  What the registration does
            # carry is *how it was measured*, so the same reader is run again on this frame -- and a
            # frame that no longer draws it returns nothing, which is §十一's "当前画面不匹配时重新
            # 识别" applied to a textless element.  Measured on the handle: the second look re-derives
            # the point from the current frame rather than replaying a coordinate.
            return self._relocate_textless_control(entry, page, title, frame, frame_path)
        if spend_refused:
            # A recorded *word* on a screen that mentions spending stays refused: that is the trap
            # the blacklist exists for, and reuse must not become a way around it.  The textless
            # branch above is the exception, and only because the record itself declares the control
            # non-spending (see ``_ordinary_control_candidate``).
            return None
        if (page, word) in self._ordinary_tried:
            return None
        hit = find_printed_words(frame_path, (word,), ocr)
        if hit is None:
            # Registered, but the current picture does not draw it any more: re-identify rather
            # than tap where it used to be.
            print(
                f"[l1] {entry.control} is registered for {page} but this frame does not draw "
                f"{word!r}; re-identifying instead",
                flush=True,
            )
            return None
        self._ordinary_tried.add((page, word))
        self._ordinary_attempts += 1
        point = (float(hit["center_norm"][0]), float(hit["center_norm"][1]))
        self._ordinary_last = {
            "page": page,
            "title": title,
            "word": word,
            "point": (round(point[0], 4), round(point[1], 4)),
            "semantic": entry.control,
            "basis": str(entry.basis or "L1_REUSE"),
            "source": "L1_REUSE",
        }
        self._note_printed(
            entry.control,
            page_knowledge.page_key(page, title),
            f"the L1 action registered for {entry.control}",
            point,
            box_norm=hit.get("box_norm"),
            text=word,
            confidence=hit.get("confidence"),
            label=page,
        )
        print(
            f"[l1] reusing {entry.control} on {page_knowledge.page_key(page, title)} "
            f"@ {point[0]:.4f},{point[1]:.4f} (registered for goal {goal})",
            flush=True,
        )
        return point

    def _interactive_control_point(
        self,
        page: str,
        title: str,
        frame: "WorldState",
        frame_path: Path,
        ocr,
    ) -> tuple[float, float] | None:
        """One control this frame draws that nobody recorded, tried when the goal justifies it.

        This is the directive's central case: no Skill, no template and no VERIFIED record is
        required, and a control the dictionary does not declare is still attemptable once.  The
        evidence is what the project already has -- ``ui_collection.interactive_controls`` reads
        this frame's OCR boxes, their geometry and the page context -- and the judgement is the
        goal's: the wording has to belong to the goal being pursued, or be an exit that ends an
        interaction under any goal.

        The bounds are the ones already in force elsewhere, not new ones: the frame was checked
        against the spend blacklist by the caller, the run's attempt budget is shared, ``(page,
        word)`` is never used twice in a run, and a word that has twice produced nothing on this
        page is skipped.  A tap here is never a claim -- the step's own verifier decides, and only
        that can register the L1 action.
        """
        goal = str(getattr(getattr(self, "brain", None), "current_goal", "") or "")
        if not goal:
            return None
        rows = ui_collection.interactive_controls(
            frame_path,
            ocr,
            skip_words=self._declared_dictionary_words(),
            goal=goal,
            # The dictionary's own vocabulary for this goal (``related_goals``), so a word it ties
            # to the running goal counts as relevant without a code change.
            hints=self._declared_goal_words(goal),
        )
        if not rows:
            return None
        state = self._l1_state(frame, title)
        for row in rows:
            word = str(row.get("word") or "").strip()
            if not word or not row.get("goal_relevant"):
                continue
            if (page, word) in self._ordinary_tried:
                continue
            semantic = f"ORDINARY_CONTROL[{word}]"
            recorded = self._control_ledger.get(control_experience.control_key(page, semantic))
            if recorded is not None and recorded.attempts >= 2 and not recorded.known_result:
                # Twice with nothing to show is enough to stop repeating it here.
                continue
            box = row.get("box_norm")
            if not isinstance(box, Mapping):
                continue
            try:
                x_norm = float(box.get("x_norm", 0.0))
                y_norm = float(box.get("y_norm", 0.0))
                w_norm = float(box.get("w_norm", 0.0))
                h_norm = float(box.get("h_norm", 0.0))
            except (TypeError, ValueError):
                continue
            point = (round(x_norm + w_norm / 2, 4), round(y_norm + h_norm / 2, 4))
            if not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0):
                continue
            self._ordinary_tried.add((page, word))
            self._ordinary_attempts += 1
            self._ordinary_last = {
                "page": page,
                "title": title,
                "word": word,
                "point": point,
                "semantic": semantic,
                "basis": str(row.get("basis") or "OCR_BOX"),
                "source": "INTERACTIVE_CANDIDATE",
                "box_norm": dict(box),
            }
            self._l1_context = {
                "page": page,
                "goal": goal,
                "state": state,
                "semantic": semantic,
                "text": word,
                "box_norm": dict(box),
                "basis": str(row.get("basis") or "OCR_BOX"),
                "source": "INTERACTIVE_CANDIDATE",
                "confidence": float(row.get("confidence") or 0.0),
                "frame": str(frame_path),
                "expected_effect": self._declared_expectation(semantic),
            }
            self._stage_interaction_candidate(
                page=page,
                title=title,
                goal=goal,
                frame_path=frame_path,
                word=word,
                box_norm=dict(box),
                confidence=float(row.get("confidence") or 0.0),
                basis=str(row.get("basis") or "OCR_BOX"),
                source="INTERACTIVE_CANDIDATE",
            )
            self._note_printed(
                semantic,
                page_knowledge.page_key(page, title),
                f"the frame's own {word!r} (interactive box, goal {goal})",
                point,
                box_norm=dict(box),
                text=word,
                confidence=float(row.get("confidence") or 0.0),
                label=page,
            )
            print(
                f"[interactive] {page_knowledge.page_key(page, title)}: {word!r} was not in the "
                f"dictionary but looks like a control and matches goal {goal}; "
                f"tapping @ {point[0]:.4f},{point[1]:.4f}",
                flush=True,
            )
            return point
        return None

    def _stage_interaction_candidate(
        self,
        *,
        page: str,
        title: str,
        goal: str,
        frame_path: Path,
        word: str,
        box_norm: Mapping[str, Any],
        confidence: float,
        basis: str,
        source: str,
    ) -> None:
        """File the element as a CANDIDATE *before* the tap (directive section 6).

        The collector's hook in ``_record_episode`` runs after the step, which is right for folding
        an outcome in and too late for this clause: a step that dies -- a crash, a timeout, a killed
        cycle -- would leave nothing behind, and the region that was measured is exactly what a
        retry would need.  So the crop, the context image and the metadata are written here, with
        the page, the goal, the frame, the bbox, the candidate semantic and the basis.

        The after-step hook then folds the attempt and the verifier's verdict into the same record,
        so the two never disagree about which element was tried.
        """
        store = self._ui_store()
        if store is None:
            return
        try:
            store.stage(
                frame_path=frame_path,
                page=page,
                semantic=f"ORDINARY_CONTROL[{word}]",
                box_norm=box_norm,
                goal=goal,
                episode=str(getattr(getattr(self, "capture_dir", None), "name", "") or ""),
                ocr_text=word,
                ocr_confidence=confidence,
                recognition_method=ui_collection.METHOD_OCR_WORD,
                semantic_candidates=(f"OCR_WORD:{word}",),
                expected_effect="ordinary_control_observed",
                notes=(
                    f"staged before the tap; basis={basis}; source={source}; "
                    f"page_key={page_knowledge.page_key(page, title)}"
                ),
            )
            store.save()
        except Exception:  # noqa: BLE001 - collection must never fail a step
            pass

    def _remembered_control_center(self, semantic: str, frame: "WorldState"):
        """Where this device last saw ``semantic``, when the template can no longer find it.

        Operator §四.1/§四.3: "已知成功操作优先复用", "已知页面跳转结果用于规划导航".
        Until now the ledger was written on every step and read by nobody, so a control
        the machine had clicked thirty-five times successfully was still unusable the
        moment its template stopped matching -- which is the same wall
        ``TARGET_INFANTRY_CAMP_HIGHLIGHTED`` hits for a different reason.  This is the
        read.

        Four conditions, and each excludes a different way of being wrong:

        * **the page must match**, because the key is ``(page, semantic)``.  This is the
          same invariant the reviewed ``BTN_EXPLORATION_IDLE_CLAIM`` fallback above is
          written under: a normalized point is only allowed behind an independent proof
          of which page it is on.
        * **``resolved``**, i.e. at least one attempt produced an observed change.  A
          control whose only outcome was ``NO_OP`` or ``UNKNOWN`` has no known result and
          is not reused -- the operator's §四.7 forbids promoting UNKNOWN to known, and
          this is the place that would otherwise do it silently.
        * **not ``sterile``** and **no ``refused_reason``**: explored does not mean
          repeated forever, and a control policy already refused is refused again.
        * **no live cooldown**, so a control with a measured wait is not tapped early.

        A *recorded* risk label is honoured: if the ledger says this control is not one
        an ordinary tap may carry, the remembered position is refused and the caller
        falls through to its own refusal.  Nothing writes that label yet, so this costs
        nothing today -- but the field is in the ledger schema and round-trips, and the
        operator's boundary is that an expensive or irreversible outcome is identified
        *before* it is submitted, not after.  An *unlabelled* control is not refused:
        this branch is a named control the device has already exercised and measured,
        which is a stronger basis than the unrecognised-tap case ``explorable_risk``
        was written for.
        """
        page = control_experience.label(frame.page)
        entry = self._control_ledger.get(control_experience.control_key(page, semantic))
        if entry is None:
            return None
        if entry.position_norm is None or not entry.resolved:
            return None
        if entry.sterile or entry.refused_reason:
            return None
        if entry.cooldown_remaining() > 0:
            return None
        if entry.risk and not control_experience.explorable_risk(entry.risk):
            return None
        point = (float(entry.position_norm[0]), float(entry.position_norm[1]))
        if not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0):
            return None
        narration = f"{page}|{semantic}"
        self._remembered_reuse.append(
            f"{narration} <- {entry.known_change or entry.last_result} "
            f"@{point[0]:.3f},{point[1]:.3f} (attempts {entry.attempts})"
        )
        if narration not in self._printed_remembered:
            self._printed_remembered.add(narration)
            print(f"[experience] template missing, reusing a measured position for {page}|{semantic} "
                  f"({entry.known_change or entry.last_result}, attempts {entry.attempts})", flush=True)
        return point

    def _client_printed_control(
        self, semantic: str, frame: "WorldState", frame_path: "Path | None"
    ) -> tuple[str, tuple[float, float] | None]:
        """Where the client printed this control's own name, or that it is not on this screen.

        Operator §二.2/§五: "没有预定义模板，不等于禁止根据当前画面定位并尝试普通控件" -- and the
        strongest evidence available for an ordinary control is the client's own drawing of it.
        This is the general answer to the failure class that dominates the episode stream:
        measured 2026-09-22 over 2485 production steps, ``SEMANTIC_TARGET_NOT_VERIFIED`` is the
        single largest failure at 150, and its four biggest names are the most ordinary controls
        in the game -- ``POPUP_GENERIC_REWARD_HEADER`` (38), ``BTN_DISMISS_INTEL_REWARD`` (31),
        ``BTN_OPEN_HOME`` (16), ``BTN_CLOSE`` (14).  A route that names one of those had nothing
        to turn the name into a pixel with.

        Two sources, both a statement about *this* frame:

        * **the word the client printed on the control.**  The dictionary declares, per
          semantic, the client's own words for it; ``find_printed_words`` reads one off the
          frame.  Nothing is remembered, so nothing can go stale -- which is the operator's
          §六 rule that an absolute coordinate may never be the only basis for a tap.
        * **the instruction the client printed for the screen.**  Reward popups say
          ``点击任意位置退出`` (read at 0.9977 on two frames three days apart, both at
          (0.5000, 0.9227)), which is the client stating the interaction; the point used is the
          instruction's own box centre, so it is read rather than assumed.  Measured on the real
          device 2026-09-17: that phrase, one tap, and the frame afterwards was MAIL with
          ``popup = null``.

        Three answers, and the middle one is the one that matters:

        * ``("FOUND", point)``   -- the control is located on this frame.
        * ``("ABSENT", None)``   -- the dictionary declares words for this control and none of
          them is on this frame, so **the control is not on screen** and the caller must not fall
          through to a remembered position either.  This is measured, not cautious: on a MAP
          frame with the beast-search panel open, ``BTN_OPEN_HOME``'s remembered point
          (0.9236, 0.9539) lands on 自动狩猎, because the panel covers the navigation bar and the
          memory has no way to know that.  Refusing is what keeps a stale coordinate from being
          spent on a live control.
        * ``("UNDECLARED", None)`` -- the dictionary says nothing about this name, the page does
          not match its declaration, or this runtime has no OCR.  The next layer answers.

        Deliberately *not* asked: ``explorable_risk``.  Both sources are the client itself
        declaring the control, which is a stronger basis than the unrecognised-tap case that
        whitelist was written for.  The instruction half needs no dismissal-intent gate either,
        and leaving it out is the client's own logic rather than a relaxation: "tap anywhere to
        exit" means that on this screen *no* point can mean anything else.  Its first version did
        carry such a gate (a name matching CLOSE/DISMISS/LEAVE) and it was measured wrong on the
        largest class there is -- ``POPUP_GENERIC_REWARD_HEADER`` names no dismissal, is dismissed
        by the brain as one, and 38 steps died refusing to obey a screen that said outright what
        to do.  What guards the instruction instead is the page declaration below.
        """
        page = control_experience.label(frame.page)
        declared = _declared_record(semantic)
        if declared is not None:
            pages, words = declared
            page_ok = not pages or "*" in pages or page in pages
            if not page_ok:
                # The dictionary places this control on other pages, so what is on this screen
                # cannot be it.  Falling through (rather than refusing) is right here: the page
                # declaration is about *where it is drawn*, not about whether this runtime has
                # some other way to reach it.
                return "UNDECLARED", None
            if words:
                if frame_path is None:
                    return "UNDECLARED", None
                ocr = self._ocr_service()
                if ocr is None:
                    return "UNDECLARED", None
                hit = find_printed_words(frame_path, words, ocr)
                if hit is not None:
                    point = (float(hit["center_norm"][0]), float(hit["center_norm"][1]))
                    self._note_printed(
                        semantic,
                        page,
                        f"the word {hit['word']!r}",
                        point,
                        box_norm=hit.get("box_norm"),
                        text=str(hit.get("word") or ""),
                        confidence=hit.get("confidence"),
                    )
                    return "FOUND", point
                return "ABSENT", None
        if frame_path is None:
            return "UNDECLARED", None
        ocr = self._ocr_service()
        if ocr is None:
            return "UNDECLARED", None
        instruction = read_tap_anywhere_instruction(frame_path, ocr)
        if instruction is None:
            return "UNDECLARED", None
        point = (float(instruction["center_norm"][0]), float(instruction["center_norm"][1]))
        self._note_printed(
            semantic,
            page,
            f"the client's own {instruction['phrase']!r}",
            point,
            # No box: the client drew an *instruction*, not a control, so the only measured
            # region is the instruction's own text.  The point is what the caller taps; the
            # collector anchors its element box on the same point and says so.
            box_norm={
                "x_norm": round(point[0], 4),
                "y_norm": round(point[1], 4),
                "w_norm": 0.0,
                "h_norm": 0.0,
            },
            text=str(instruction.get("phrase") or ""),
            confidence=instruction.get("confidence"),
        )
        return "FOUND", point

    def _ocr_service(self):
        """The OCR this runtime may read a frame with, or ``None`` when it has none.

        Asked defensively rather than required: a harness with a fake vision has no OCR, and the
        honest answer there is that this layer cannot answer -- not an exception thrown in the
        middle of a live run.
        """
        for holder in (self.vision, self.semantic_vision):
            service = getattr(holder, "ocr", None)
            if service is not None:
                return service
        return None

    def _note_printed(
        self,
        semantic: str,
        page: str,
        source: str,
        point: tuple[float, float],
        *,
        box_norm: Mapping[str, Any] | None = None,
        text: str = "",
        confidence: float | None = None,
        label: str = "",
    ) -> None:
        """Record and narrate one read, once per control: the layer must not be silent.

        ``_printed_reads`` is what makes "did the client's own words change what the machine
        did" answerable from the run rather than from a log, which is the same reason the
        ledger reads are kept.

        ``box_norm``/``text``/``confidence`` are the same read's *shape*, kept because the
        automatic UI collector needs a region rather than a point to crop an element from
        (operator 2026-09-22).  They are optional so every existing caller is unchanged: a
        caller that knows only the point records only the point.
        """
        line = f"{page}|{semantic}"
        #: ``label`` is what the *collector* files the region under, and it is the page label
        #: (``UNKNOWN``), not the page key (``UNKNOWN::挂机收益``): ``_collect_ui_evidence`` looks
        #: the box up as ``<page label>|<semantic>``.  Measured 2026-09-22 -- narrating an
        #: ordinary control under its page key silently cost the unnamed screen its element
        #: candidate, because the two keys never met.
        box_line = f"{label}|{semantic}" if label else line
        self._printed_reads.append(
            f"{line} <- {source} @{point[0]:.4f},{point[1]:.4f}"
        )
        if box_norm is not None:
            boxes = getattr(self, "_printed_boxes", None)
            if boxes is None:
                boxes = {}
                self._printed_boxes = boxes
            boxes[box_line] = {
                "box_norm": dict(box_norm),
                "word": text,
                "confidence": confidence,
            }
        if line in self._printed_printed:
            return
        self._printed_printed.add(line)
        print(
            f"[printed] template and ledger both failed; {semantic} located by {source} "
            f"at {point[0]:.4f},{point[1]:.4f} on {page}",
            flush=True,
        )

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
            self._save_ui_candidates()
            self._save_page_candidates()
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
        # Every read of that ledger, so "did experience change what the machine did"
        # is answerable from the run rather than from a claim.  Printed once per
        # distinct reuse -- a route that reuses the same control twelve times is one
        # fact, not twelve lines.
        #
        # ``_printed_reads`` is the same record for the other non-template layer: a
        # position the client's own printed words supplied.  Kept apart from the ledger
        # reads because they are different evidence -- one is what this device measured
        # earlier, the other is what the client states now -- and a run that has to be
        # read back later must not blur them.
        self._remembered_reuse: list[str] = []
        self._printed_remembered: set[str] = set()
        self._printed_reads: list[str] = []
        self._printed_printed: set[str] = set()
        # The generic ordinary-control attempt (operator directive 2026-09-22, third
        # item).  Run-scoped bounds: at most ``MAX_ORDINARY_ATTEMPTS`` taps, and never
        # the same (page, word) twice -- a control whose tap did nothing must not be
        # re-tapped, and a screen with no untried whitelisted word sets the brain's
        # ``ordinary_scan_exhausted`` so the fallback stops asking this run.
        self.MAX_ORDINARY_ATTEMPTS = 2
        self._ordinary_attempts = 0
        self._ordinary_tried: set[tuple[str, str]] = set()
        #: Why the ordinary resolver declined this step, when the reason is the runtime's own rather
        #: than the frame's.  Set and cleared by ``_ordinary_control_candidate``, read by
        #: ``_failure_type_from`` and by the candidate collector -- so a refusal is recorded as the
        #: refusal it was, instead of as "the frame names no control" (measured: 17 of the 18 repeats
        #: inside one run failed that way while the frame demonstrably drew the handle).
        self._ordinary_declined: dict[str, Any] | None = None
        # Which control the ordinary resolver chose this step, for the transition ledger: the
        # word is known at resolution time and nowhere else, because "ORDINARY_CONTROL" is a
        # placeholder name by construction (operator 2026-09-22, unknown pages).
        self._ordinary_last: dict[str, Any] | None = None
        #: The evidence this step's ordinary-control resolution produced (page, goal, state,
        #: the element's own box and wording, and how it was located), so a step whose verifier
        #: passes can register an L1 single-step action without re-deriving any of it.
        self._l1_context: dict[str, Any] | None = None
        # The learned navigation (operator §五): loaded once per run, written back at ``finish``.
        # It is read through ``getattr`` by the resolver so a harness without it still runs.
        self._transitions = page_knowledge.TransitionLedger()
        # The last page this run could *name*, so a screen reached from another unnamed screen
        # still records what it was entered from (operator §四: "进入前的页面及触发动作").
        self._last_known_label = ""
        # On-demand UNKNOWN analysis (operator 2026-09-22).  The advisor writes questions and reads
        # answers; it has no client, so nothing here can block a cycle.  ``_last_advice`` is the
        # answer this step used, and ``_last_attempt_summary`` is the evidence §二 asks to hand over
        # with a question -- what was last tried here, what it was expected to do, what was seen.
        self._advisor = unknown_advisor.UnknownAdvisor()
        self._last_advice: dict[str, Any] | None = None
        self._last_attempt_summary: dict[str, Any] = {}
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
            before = self._observe(before_path)
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
            decision = self._stop_instead_of_looking_again(before, decision, best_goal)
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
                            before = self._observe(recovery_path)
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
                            before = self._observe(recovery_path)
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
            after = self._observe(after_path)
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
                after = self._observe(recovery_path)
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
                after = self._observe(refresh_path)
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
