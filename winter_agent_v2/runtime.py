from __future__ import annotations

import time
import os
import inspect
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from typing import Any, Callable, Iterable, Mapping

from .brain import RuleBrain
from . import action_latency
from .settle_policy import FrameChangeProbe, choose as choose_settle_policy
from .rally import RallyTarget, live_rally_join_point, rally_target_for_goal
from .verifier import verify_bear_rally_list_open
from . import control_experience
from . import goal_utility
from . import ui_collection
from . import page_knowledge
from . import event_schedule
from .capability_bootstrap import DEFAULT_BUDGET, project_runtime_discovery
from . import unknown_advisor
from . import skill_repair
from . import unknown_learning
from . import ui_venus_repair
from .executor import Executor
from .policy import SafetyPolicy
from . import semantic_executor as click_retry
from .executor_router import DEFAULT_ROUTING_PATH, BackendLedger, RoutingTable, build_router
from .learning import ActionOutcome, Episode, EpisodeStore
from .models import Decision, ExecutionResult, Page, VerificationResult, WorldState
from .ocr import (
    find_printed_words, find_quick_panel_handle, read_frame_size,
    read_power_details_action_tokens, read_tap_anywhere_instruction,
)
from .camp_training import CAMP_LABELS, CAMP_ORDER
from .scheduler import ACTIVE_ROLE_NO_CANDIDATE, Scheduler
# The Goal -> session-adapter table, and nothing else from the session engine: the runtime
# asks "does this Goal have a session?" and, if it does, lets ``_run_goal_session`` build it.
# Imported at module level because it has no dependency back on this module, so there is no
# cycle to dodge -- and a lazy import here would just hide a routing defect until run time.
from . import session_adapters

#: Selections that mean "finish this step and re-observe the SAME role".  Every member is
#: a no-switch verdict, so the runtime must never fall through to executing a decision
#: built from the frame captured before it.  ``ACTIVE_ROLE_NO_CANDIDATE`` is directive
#: §3/§4/§9: the active role produced no candidate while its Role Session was still
#: locked, so it keeps the device and is observed again.
ROLE_REFRESH_ONLY_REASONS = frozenset({
    "GLOBAL_WAIT",
    "GLOBAL_CAPABILITY_GAP_NO_EXECUTABLE_CANDIDATE",
    "GLOBAL_CANDIDATE_GENERATION_GAP",
    "GLOBAL_REFRESH_REQUIRED_NO_SAFE_CANDIDATE",
    ACTIVE_ROLE_NO_CANDIDATE,
})

#: How many consecutive re-observations of the same role one run may pay for in-process before
#: it ends and lets the control plane decide again.  TASK THROUGHPUT V1 §23/§24: re-observing
#: the same account is the wanted behaviour, but the *way* it was obtained was to end the run,
#: and a panel round costs a subprocess restart plus, for this reason, a 30-second breather
#: before it.  Measured 2026-09-30 on pin 7055f02: a run ended at 03:14:37 after three
#: successful actions and the next round's first action never came at all.  Bounded rather
#: than unlimited because a role that can never produce a candidate must still end its run;
#: the Role Session's own ``no_work_streak`` (2) opens the switch gate within this bound.
MAX_ROLE_REFRESH_TICKS_PER_RUN = 3

#: The operator's own verdict, used verbatim as the refusal reason so that it cannot be
#: mistaken for a missing capability.  Directive FISHING TOURNAMENT — NORMAL BAIT MAX SCORE
#: POLICY V2 §4 (2026-09-30) asks for exactly this string, and asks in the same breath that it
#: NOT be reported as ``CAPABILITY_GAP``: a forbidden action is not work to be built.
POLICY_DISABLED_BY_USER = "POLICY_DISABLED_BY_USER"
#: Refused because its whole category is switched off in the panel.  Distinct from the above
#: because it *is* reversible by the operator and is not a standing prohibition.
POLICY_CATEGORY_DISABLED = "POLICY_CATEGORY_DISABLED"
#: The operator's policy file.  A module attribute rather than an inline expression so that a
#: test can point it at a scratch file, and so the one place that decides "what may run" has
#: its input named in one place.
POLICY_STATE_PATH = Path(__file__).resolve().parents[1] / "config/policy_state.json"

from .goal_library import (
    GoalLibrary, GoalStateStore, action_relevant_goal_ids,
    newly_completed_goal_ids, progress_moved, route_for,
)
from .global_scheduler_state import GlobalSchedulerStateStore
from .task_completion import TaskCompletionStore
from .capability_gate import DEFERRED, CapabilityGate, Deferral
from .device_lease import OWNER_DEVELOPMENT_VALIDATION, OWNER_GAMEPLAY, DeviceLease
from .candidate_policy import CandidateAttemptPool
from .skills import SkillRegistry, v2_registry
from .verifier import verify_alliance_reward_dismissed, verify_ally_gift_claim_feedback, verify_intel_hero_dispatched, verify_intel_hero_march_open, verify_intel_hero_target_open, verify_daily_claim_feedback, verify_daily_reward_advanced, verify_daily_tab_selected, verify_exploration_claim_confirmed, verify_exploration_claim_feedback, verify_exploration_reward_dismissed, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_mail_read_or_claim, verify_offline_rewards_claimed, verify_open_alliance, verify_open_alliance_gifts, verify_open_daily, verify_open_exploration, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_training_camp_switched, verify_intel_list_read, verify_alliance_gifts_claimed
from .verifier import verify_panel_building_queue_opened, verify_ally_gift_claim, verify_beast_card_march_open, verify_beast_card_opened, verify_beast_dispatch, verify_beast_mammoth_target_selected, verify_beast_march_open, verify_beast_scan_observed, verify_beast_search_submitted, verify_beast_search_tab_selected, verify_beast_target_selected, verify_building_upgrade, verify_camp_menu_reobserved, verify_duplicate_target_cancelled, verify_environmental_wait, verify_intel_beast_dispatch, verify_intel_beast_march_open, verify_intel_claim_feedback, verify_intel_mission_selected, verify_intel_pin_opened, verify_intel_rescue_selected, verify_intel_rescue_started, verify_intel_rescue_target_open, verify_intel_reward_dismissed, verify_intel_target_open, verify_left_foreign_layer, verify_login_gift_claimed, verify_login_gift_panel_open, verify_mail_alliance_tab_selected, verify_mail_claim_feedback, verify_mail_report_tab_selected, verify_mail_reward_dismissed, verify_mail_system_tab_selected, verify_march_count_readable, verify_march_page_open, verify_march_recall_dialog_open, verify_march_recalled, verify_open_home, verify_open_intel, verify_open_mail, verify_open_map, verify_panel_row_done_collected, verify_panel_row_research_bar_opened, verify_panel_row_task_bar_opened, verify_popup_closed, verify_rally_created, verify_rally_joined, verify_research_lab_focused, verify_research_page_open, verify_research_started, verify_resource_found, verify_resource_level_relaxed, verify_resource_search_open, verify_resource_selected, verify_free_stamina_claimed, verify_safe_back, verify_stamina_sources_open, verify_training_started, verify_wood_dispatch_from_march, verify_ordinary_control_tried
from .runtime_snapshot import (
    AgentState, RuntimeSnapshotStore, StopCategory, is_fatal_stop, state_for_stop_reason,
)
from .verifier import (verify_alliance_tech_opened, verify_alliance_tech_node_opened,
                     verify_alliance_tech_details_closed, verify_alliance_tech_contribution,
                     verify_daily_task_followed)
from .verifier import can_reobserve_focused_training_camp_after_nonmenu_tap

from .resource_rotation import ResourceRotationStore
from .stamina_supply import StaminaSupplyStore
from .camp_ring import reproject_point_on_static_city_view

from .intel_pins import intel_pin_centers
from .verifier import (
    verify_research_node_inspected,
    verify_completed_training_camp_inspected,
    verify_focused_training_camp_action_bar_opened,
)
from .verifier import (
    verify_gather_hero_picker_open,
    verify_gather_hero_picker_selected,
    verify_gather_hero_removed,
    verify_gather_specialist_assigned,
)
from .verifier import (
    verify_event_calendar_open, verify_event_calendar_tab_open,
    verify_event_calendar_read, verify_event_calendar_detail_open,
    verify_event_calendar_returned, verify_training_batch_claimed,
    verify_free_hero_recruit, verify_quick_panel_scrolled,
    verify_quick_panel_pet_entry_opened, verify_gathering,
)


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


def _declared_record(semantic: str) -> tuple[tuple[str, ...], tuple[str, ...], bool] | None:
    """``(pages, the client's words, whether the reading may contain the word)`` for one semantic.

    ``None`` means the dictionary says nothing about this name -- *not* that the control does
    not exist.  That distinction is load-bearing for the caller: an undeclared control must
    fall through to the layers that remember or derive a position, while a declared control
    whose words are missing from the frame is a control that is not on screen.

    The third element is the record's own ``ocr_merged`` declaration: the client draws a control's
    name together with its icon (``icon_semantic`` in the same dictionary is that fact stated as a
    label), and OCR returns the two as **one token**.  Measured 2026-09-23 on the 加成总览 panel: the
    实力详情 button is read as ``三实力详情`` at confidence 0.901 with its centre 3 px from the
    button's own centre, so an exact match finds nothing and the route that needs that button
    reports the control is not on screen -- 14 live frames, all on that popup.  The flag is **per
    record** rather than a change to ``find_printed_words``' default, because that default is exact
    for a measured reason (the ``城镇``/``我的城镇`` false positive its docstring records), and only a
    control whose word has actually been observed merged may relax it.
    """
    global _UI_DICTIONARY
    stamp = None
    try:
        stamp = UI_DICTIONARY_PATH.stat().st_mtime
    except OSError:
        return None
    if stamp != _UI_DICTIONARY[0]:
        table: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool]] = {}
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
                bool(record.get("ocr_merged", False)),
            )
        _UI_DICTIONARY = (stamp, table)
    return _UI_DICTIONARY[1].get(str(semantic))


def _verify_rally_action(skill_id: str, before: WorldState, after: WorldState, target: str):
    target_id = str(getattr(target, "value", target) or "UNKNOWN").strip().upper()
    supported_targets = {item.value for item in RallyTarget if item is not RallyTarget.UNKNOWN}
    if target_id not in supported_targets:
        return VerificationResult(False, "RALLY_TARGET_UNKNOWN", {"target": target_id})
    if skill_id == "JOIN_RALLY":
        return verify_rally_joined(before, after, target_id)
    if skill_id == "START_RALLY":
        return verify_rally_created(before, after, target_id)
    raise ValueError(f"not a rally action: {skill_id}")


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
        "PLAY_NORMAL_FISHING_LEVEL": lambda before, after: VerificationResult(False, "FISHING_SESSION_REQUIRED"),
        "READ_FISHING_STATE": lambda before, after: VerificationResult(False, "FISHING_SESSION_REQUIRED"),
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
        # The quick-panel handle is a bounded navigation/exploration action. Its
        # shared verifier has a dedicated QUICK_PANEL_OPENED check when the panel
        # state flips on; without this binding, GoalLibrary can select
        # DISCOVER_QUICK_PANEL_TASKS but the live loop rejects it before MAA runs.
        "OPEN_QUICK_PANEL": verify_ordinary_control_tried,
        "FOLLOW_DAILY_TASK": verify_daily_task_followed,
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
        # The 超值活动 / 登录好礼 day reward.  Measured 2026-09-24T14:31+08:00 on the real client:
        # one tap on the node the client itself highlights, and from 0.5 s later the highlighted
        # node is no longer drawn while the panel is still EVENT.  Without an entry here the skill
        # is registered but never dispatched -- the failure mode #45 already recorded.
        "CLAIM_LOGIN_GIFT": verify_login_gift_claimed,
        "OPEN_LOGIN_GIFT": verify_login_gift_panel_open,
        # These steps already have a reader, Goal/Brain route and atomic action.
        # Bind their real observed postconditions so the live loop can dispatch
        # them; calendar registration or a sent tap alone proves none of them.
        "OPEN_EVENT_CALENDAR_FROM_HOME": verify_event_calendar_open,
        "OPEN_EVENT_CALENDAR_FROM_MAP": verify_event_calendar_open,
        "OPEN_EVENT_CALENDAR_TAB": verify_event_calendar_tab_open,
        "READ_EVENT_CALENDAR": verify_event_calendar_read,
        "OPEN_EVENT_CALENDAR_DETAIL": verify_event_calendar_detail_open,
        "RETURN_EVENT_CALENDAR": verify_event_calendar_returned,
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
        "VERIFY_GATHERING": lambda b, a: verify_gathering(a),
        "CLEAR_GATHER_HEROES": verify_gather_hero_removed,
        "OPEN_GATHER_HERO_PICKER": verify_gather_hero_picker_open,
        "SELECT_GATHER_HERO": verify_gather_hero_picker_selected,
        "ASSIGN_GATHER_HERO": verify_gather_specialist_assigned,
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
        "SELECT_GIANT_BEAST_TAB": lambda before,after: VerificationResult(
            before.resource_search_open and after.resource_selected_tab == 'GIANT_BEAST',
            'GIANT_BEAST_TAB_SELECTED' if after.resource_selected_tab == 'GIANT_BEAST' else 'GIANT_BEAST_TAB_NOT_PROVEN'),
        "SUBMIT_GIANT_BEAST_SEARCH": lambda before,after: VerificationResult(
            before.resource_selected_tab == 'GIANT_BEAST' and bool(after.beast_search_result.get('title_text') or after.beast_search_result.get('has_rally')),
            'GIANT_BEAST_SEARCH_RESULT' if after.beast_search_result else 'GIANT_BEAST_SEARCH_NOT_PROVEN'),
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
        "OPEN_ALLIANCE_TECH_FROM_HOME": verify_alliance_tech_opened,
        "OPEN_ALLIANCE_RECOMMENDED_TECH_NODE": verify_alliance_tech_node_opened,
        "CLOSE_ALLIANCE_TECH_DONATION_DETAILS": verify_alliance_tech_details_closed,
        "ALLIANCE_TECH_CONTRIBUTE": lambda b, a: verify_alliance_tech_contribution(b, a, a),
        "OPEN_BEAR_RALLY_LIST": verify_bear_rally_list_open,
        "OPEN_EXPLORATION": verify_open_exploration,
        # ------------------------------------------------------------------
        # START_RALLY and JOIN_RALLY share target-parameterized verifiers. Keep the
        # registry's Bear default for legacy callers; the live loop binds the target
        # from the selected Goal before dispatch and verification.
        "JOIN_RALLY": lambda before, after: verify_rally_joined(before, after, "BEAR"),
        "START_RALLY": lambda before, after: verify_rally_created(before, after, "BEAR"),
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
        # Opening the selected upgrade sheet is navigation, distinct from
        # BUILDING_UPGRADE's queue-start proof. Unknown identity/cost still
        # cannot authorize the separate resource-spending action.
        "OPEN_BUILDING_UPGRADE": lambda b, a: VerificationResult(
            b.page is Page.HOME and a.page is Page.BUILDING
            and a.building.get("upgrade_dialog_visible") is True,
            "BUILDING_UPGRADE_PANEL_OPENED" if a.page is Page.BUILDING
            and a.building.get("upgrade_dialog_visible") is True
            else "BUILDING_UPGRADE_PANEL_NOT_PROVEN",
            {"page_before": b.page.value, "page_after": a.page.value,
             "upgrade_dialog_visible": a.building.get("upgrade_dialog_visible")}),
        "RESEARCH": lambda before, after: verify_research_started(before, after, str(before.research.get("node", ""))),
        "TRAIN_TROOPS": lambda before, after: verify_training_started(before, after, str(before.training.get("troop_type", ""))),
        "COLLECT_TRAINING_BATCH": verify_training_batch_claimed,
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
        "OPEN_TASK_FROM_QUICK_PANEL_BUILDING": verify_panel_building_queue_opened,
        "OPEN_TASK_FROM_QUICK_PANEL_RESEARCH": verify_panel_row_research_bar_opened,
        # Collecting a finished batch, judged by the tick disappearing from that row.
        "COLLECT_FINISHED_TRAINING_SHIELD": lambda b, a: verify_panel_row_done_collected(b, a, row_key="SHIELD_CAMP"),
        "COLLECT_FINISHED_TRAINING_LANCER": lambda b, a: verify_panel_row_done_collected(b, a, row_key="LANCER_CAMP"),
        "COLLECT_FINISHED_TRAINING_MARKSMAN": lambda b, a: verify_panel_row_done_collected(b, a, row_key="MARKSMAN_CAMP"),
        "OPEN_COMPLETED_TRAINING_CAMP_SHIELD": lambda b, a: verify_completed_training_camp_inspected(b, a, camp="SHIELD"),
        "OPEN_COMPLETED_TRAINING_CAMP_LANCER": lambda b, a: verify_completed_training_camp_inspected(b, a, camp="LANCER"),
        "OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN": lambda b, a: verify_completed_training_camp_inspected(b, a, camp="MARKSMAN"),
        # A completed-row tap focuses the camp first. This second, current-frame tap
        # must prove that the same named camp's action bar (including its 训练 control)
        # actually opened before the route can continue.
        "TAP_FOCUSED_TRAINING_CAMP_SHIELD": lambda b, a: verify_focused_training_camp_action_bar_opened(b, a, camp="SHIELD"),
        "TAP_FOCUSED_TRAINING_CAMP_LANCER": lambda b, a: verify_focused_training_camp_action_bar_opened(b, a, camp="LANCER"),
        "TAP_FOCUSED_TRAINING_CAMP_MARKSMAN": lambda b, a: verify_focused_training_camp_action_bar_opened(b, a, camp="MARKSMAN"),
        "COLLECT_MY_REWARDS_ROW": lambda b, a: verify_panel_row_done_collected(b, a, row_key="MY_REWARDS"),
        "OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION": verify_ordinary_control_tried,
        "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT": verify_ordinary_control_tried,
        "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT_EPIC": lambda b, a: VerificationResult(
            b.page is Page.HOME and b.quick_panel.get("open") is True
            and a.page is Page.HERO and a.quick_panel.get("open") is not True,
            "HERO_RECRUIT_PAGE_OPENED" if a.page is Page.HERO
            else "HERO_RECRUIT_PAGE_NOT_PROVEN",
            {"page_before": b.page.value, "page_after": a.page.value}),
        "OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE": verify_quick_panel_pet_entry_opened,
        "FREE_HERO_RECRUIT_ADVANCED": lambda b, a: verify_free_hero_recruit(b, a, "HERO_RECRUIT_ADVANCED"),
        "FREE_HERO_RECRUIT_EPIC": lambda b, a: verify_free_hero_recruit(b, a, "HERO_RECRUIT_EPIC"),
        # The daily task's 前往 button opens recruitment. It does not itself
        # perform a draw or complete/claim the daily task.
        "DAILY_HERO_RECRUIT": lambda b, a: VerificationResult(
            b.page is Page.DAILY and a.page is Page.HERO,
            "HERO_RECRUIT_PAGE_OPENED" if a.page is Page.HERO
            else "HERO_RECRUIT_PAGE_NOT_PROVEN",
            {"page_before": b.page.value, "page_after": a.page.value}),
        "SCROLL_QUICK_PANEL_TASKS": verify_quick_panel_scrolled,
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
        # The lab radial-menu 研究 control opens the tech tree; the proof is the
        # same arrival state OPEN_RESEARCH is judged by (Page.RESEARCH observed).
        "OPEN_TECH_TREE": verify_research_page_open,
        "SELECT_RESEARCH_NODE": verify_research_node_inspected,
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
        max_semantic_click_retry: int = click_retry.MAX_SEMANTIC_CLICK_RETRY,
        sleeper: Callable[[float], None] = time.sleep,
        episode_store: EpisodeStore | None = None,
        goal_store: GoalStateStore | None = None,
        global_scheduler_state_store: GlobalSchedulerStateStore | None = None,
        role_catalog: Iterable[Mapping[str, Any]] = (),
        role_switch_controller: Any | None = None,
        role_switch_cost: float = 30.0,
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
        expected_lease_id: str = "",
        expected_after_version: str = "",
        latency_trace_path: Path | None = None,
        fruitless_audit_path: Path | None = None,
        #: Who answers the on-demand question for a screen no skill can advance.
        #:
        #: Injected rather than built here for the same reason ``maa_adapter`` and ``routing``
        #: are: the runtime has no config dict, and the choice between "the retired
        #: answer-file channel" and "the local planner" is a deployment decision that
        #: belongs where the config is read.
        #:
        #: A **factory** (zero-argument callable), or an instance, or ``None``.  The advisor is
        #: created inside ``run()`` -- not here -- because it is run-scoped: the answer-file
        #: reader and the planner both carry per-run budgets (``max_steps_per_run``), and an
        #: advisor reused across runs would hand the second run a spent budget.  Passing a
        #: factory is therefore the form that means what the parameter name suggests.
        #:
        #: ``None`` keeps the pre-existing advisor, so a caller that knows nothing about
        #: planners behaves exactly as before.
        advisor=None,
        #: ROLE_SESSION_POLICY knobs (operator directive 2026-09-30 §15).  The runtime has
        #: no config dict of its own, so like ``maa_adapter`` and ``routing`` this is a
        #: deployment decision injected from where the config is read.  ``None`` keeps the
        #: Scheduler's own defaults, which are the directive's first-version parameters.
        role_session_policy: Mapping[str, Any] | None = None,
        validation_scope: Mapping[str, str] | None = None,
    ) -> None:
        self.device = device
        self.latency_trace_path = Path(latency_trace_path) if latency_trace_path else None
        self.fruitless_audit_path = Path(fruitless_audit_path) if fruitless_audit_path else None
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
        #: Where UNKNOWN steps that the verifier passed are written, and where the learned
        #: actions for a screen are read back from.  Rooted at the package's parent rather than at
        #: ``capture_dir`` for the reason every other store here is: a production run's capture
        #: directory is per-episode, so learning filed under it would be invisible to the next
        #: run -- which is the whole point of learning.  Held on the instance so a test can point
        #: it at a temp directory without patching a module global.
        self.learned_ledger = unknown_learning.VerifiedStepLedger(
            Path(__file__).resolve().parents[1] / unknown_learning.LEARNED_STEPS_PATH
        )
        #: Read once per run and cached: the ledger only grows *after* a step this run verifies,
        #: and a re-read on every step of an unnamed screen would be a disk read per step for a
        #: file that the same run appends to at most a handful of times.  Invalidated by the
        #: append in ``_settle_advised_step``.
        self._learned_cache: list[dict[str, Any]] | None = None
        #: What the step currently being resolved learned at accept time.  Cleared at the top of
        #: every resolution with ``_advised_request_id``, for the same reason: a step that resolved
        #: nothing must not be credited with the previous step's answer.
        self._advised_learn_context: dict[str, Any] = {}
        #: Section 15's numerator and denominator, counted where the decision is actually made:
        #: ``_learned_model_calls`` counts model consultations on a screen this project had already
        #: solved, and ``_learned_unknown_screens`` counts every solved screen reached.  Two
        #: counters rather than a ratio computed in one place, because the ratio is only meaningful
        #: over a run and the run is what owns them.
        self._learned_reuse_hits = 0
        self._learned_model_calls_on_known = 0
        #: §16's repair channel: the trailing failures of this run, per skill, and the set of skills
        #: already asked about.  Run-scoped rather than durable because the *durable* record of a
        #: failure is the episode stream, and a second persistent counter would be the second source
        #: of truth this project keeps measuring as a defect.
        self._skill_failures: dict[str, list[dict[str, Any]]] = {}
        self._repair_asked: set[str] = set()
        self._repair_root = Path(__file__).resolve().parents[1] / skill_repair.REQUEST_DIR
        #: Kept, not consumed here: ``run()`` builds the advisor because it is run-scoped.
        #: Held under its own name so the parameter and the live attribute cannot be confused --
        #: the first version of this injection set ``self._advisor`` from ``__init__``'s
        #: parameter *inside* ``run()``, where that parameter does not exist, and every run
        #: raised ``NameError``.  ``check_wiring`` did not catch it (it never calls ``run``);
        #: ``tests/test_refusal_yields_the_cycle.py`` did, which is why that file is in the
        #: regression set for anything that touches the runtime's entry point.
        self._advisor_factory = advisor
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
        # TASK THROUGHPUT V1 §23: in-process re-observation of the same role, in place of ending
        # the run and paying a panel round for it.  See MAX_ROLE_REFRESH_TICKS_PER_RUN.
        self.max_role_refresh_ticks = MAX_ROLE_REFRESH_TICKS_PER_RUN
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
        task_data_dir = (
            Path(goal_store.path).parent if goal_store is not None
            else Path(episode_store.path).parent if episode_store is not None else None
        )
        self.task_completion_store = (
            TaskCompletionStore(task_data_dir / "task_completion_matrix.json")
            if task_data_dir is not None else None
        )
        self.global_scheduler_state_store = global_scheduler_state_store
        self.role_session_policy = (
            dict(role_session_policy) if isinstance(role_session_policy, Mapping) else None
        )
        self._fairness_store_path: Path | None = None
        self.role_catalog = tuple(dict(row) for row in role_catalog if isinstance(row, Mapping))
        self.role_switch_controller = role_switch_controller
        self.role_switch_cost = max(0.0, float(role_switch_cost or 0.0))
        self._multi_role_enabled = (
            len(self.role_catalog) > 1
            and role_switch_controller is not None
            and str(execution_mode).upper() == "PRODUCTION"
        )
        self._role_identity_confirmed = not self._multi_role_enabled
        self._role_identity_bootstrapped = False
        self._role_catalog_by_id = {
            str(row.get("role_id") or ""): row for row in self.role_catalog
            if row.get("role_id")
        }
        # One central Scheduler per runtime. The executor is rebound for each atomic action.
        self._scheduler: Scheduler | None = None
        self.max_semantic_click_retry = min(2, max(0, int(max_semantic_click_retry)))
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
        self.validation_focus_route = str(getattr(self.brain, 'current_goal', '') or '')
        self.validation_scope = dict(validation_scope or {})
        self.trace_id = str(trace_id or "")
        self.job_id = str(job_id or "")
        self.capability = str(capability or "")
        self.expected_lease_id = str(expected_lease_id or "")
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
        if str(getattr(held, "owner", "") or "") != OWNER_DEVELOPMENT_VALIDATION:
            return False
        # A validation subprocess may act only under the exact lease requested for its
        # trace/job/capability. Owner type alone would let a second development process
        # share Codex's device lease and send concurrent input.
        return bool(
            self.expected_lease_id
            and str(getattr(held, "lease_id", "") or "") == self.expected_lease_id
            and str(getattr(held, "trace_id", "") or "") == self.trace_id
            and str(getattr(held, "job_id", "") or "") == self.job_id
            and str(getattr(held, "capability_id", "") or "") == self.capability
        )

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

    def _policy_refusal(self, goal_id: str) -> str | None:
        """Why the operator's policy refuses this goal; ``None`` when it is allowed.

        Two different questions live in ``config/policy_state.json`` and they are asked in a
        fixed order, because they mean different things:

        1. ``disabled_goals`` -- goals the operator has forbidden **outright**.  Directive
           FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 §4 (2026-09-30): special-mode
           fishing is not to be developed, not to be scheduled, and not to be spent on *even
           when the attempt is free*.  A forbidden goal must therefore be refused by name,
           before any category default can let it through, and the refusal must read as a
           policy verdict (:data:`POLICY_DISABLED_BY_USER`) rather than as missing capability --
           otherwise the operator's decision shows up as a queue of work to build.
        2. ``goal_categories`` -- the per-category switches the panel exposes.

        An unreadable or malformed file allows everything, which is this project's long-standing
        trade for a knowledge/config file: a file a run cannot parse is a gap in the policy, not a
        reason to die.  This is why the answer is returned as a *reason* rather than a bool: the
        caller that has to explain "why is AUTO not doing this" can then print the operator's own
        verdict instead of a generic flag.  Returning ``None`` only when the file was readable and
        silent about the goal is what makes that distinction possible.
        """
        category = {
            "CLEAR_INTEL": "日常低保", "AVOID_STAMINA_WASTE": "PVE",
            "KEEP_TRAINING_PRODUCTIVE": "持续发展", "KEEP_RESEARCH_PRODUCTIVE": "持续发展",
            "KEEP_BUILDING_PRODUCTIVE": "持续发展", "EVENT_MINIMUM_GUARANTEE": "限时活动",
            "PARTICIPATE_BEAR": "实时活动",
        }.get(goal_id, "日常低保" if goal_id.startswith("CLAIM_FREE_") else None)
        try:
            payload = json.loads(POLICY_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        # Read before the category default can return early.  A goal the operator forbade by name
        # has to be refused even when it carries no category, and a goal that arrives from a path
        # the registry does not own -- a red dot, the UI planner -- still has to meet this gate.
        disabled = payload.get("disabled_goals")
        if isinstance(disabled, dict) and goal_id in disabled:
            return str(disabled.get(goal_id) or POLICY_DISABLED_BY_USER)
        if category is None:
            return None
        if payload.get("goal_categories", {}).get(category, True):
            return None
        return POLICY_CATEGORY_DISABLED

    def _policy_allows(self, goal_id: str) -> bool:
        """The operator's yes/no for one goal.  The reason lives in ``_policy_refusal``."""
        return self._policy_refusal(goal_id) is None

    def _runtime(self, **changes) -> None:
        if self.runtime_store is not None:
            try:
                changes.setdefault("role_id", self.role_id or None)
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

    def _validation_route_scope_active(self) -> bool:
        return self.execution_mode == 'DEVELOPMENT_VALIDATION' and bool(
            self.validation_focus_route or getattr(self, 'validation_scope', {}))

    def _focus_validation_goals(self, goals):
        """Bound a leased development probe; production keeps its full global board."""
        if not self._validation_route_scope_active():
            return goals
        from .goal_library import route_for
        scope = getattr(self, 'validation_scope', {})
        requested_role = scope.get('role_id')
        if requested_role and str(getattr(self, 'role_id', '')) != requested_role:
            return []  # A validation may never borrow another role's live state.
        requested_route = scope.get('route') or self.validation_focus_route
        if scope.get('goal_id'):
            goals = [g for g in goals if g.goal_id == scope['goal_id']]
            if (not goals and requested_route == 'TRAIN'
                    and scope['goal_id'] in {'SHIELD_CAMP_TRAINING', 'LANCER_CAMP_TRAINING', 'MARKSMAN_CAMP_TRAINING'}):
                # The panel supplies the first queue observation. An exact camp
                # probe must be able to reach it without authorizing training.
                from .goal_library import GoalState, GoalStatus
                goals = [GoalState(scope['goal_id'], GoalStatus.READY,
                    available_skills=('OPEN_QUICK_PANEL',), distance=1.0,
                    evidence={'observation_only': True, 'source': 'DEVELOPMENT_FRESH_READ'})]
        if scope.get('capability_id') or scope.get('target_skill'):
            from .goal_library import GOAL_CAPABILITY_MAP
            try:
                definitions = json.loads((Path(__file__).resolve().parents[1] / GOAL_CAPABILITY_MAP).read_text(encoding='utf-8'))['goals']
            except (OSError, ValueError, KeyError):
                return []  # Missing mapping cannot authorize an unrelated fallback.
            def relevant(goal):
                capabilities = definitions.get(goal.goal_id, {}).get('capabilities', [])
                return any(
                    (not scope.get('capability_id') or c.get('capability') == scope['capability_id'])
                    and (not scope.get('target_skill') or scope['target_skill'] in c.get('alternatives', []))
                    for c in capabilities)
            goals = [g for g in goals if relevant(g)]
        if not requested_route:
            return goals
        if requested_route == 'DAILY':
            return [goal for goal in goals if goal.goal_id == 'DAILY_ACTIVITY_TARGET'
                    or getattr(goal, 'evidence', {}).get('source') == 'LIVE_DAILY_TASK_ROW']
        scoped = [goal for goal in goals if route_for(goal.goal_id) == requested_route]
        if requested_route == 'TRAIN' and not scoped and not any(
                scope.get(key) for key in ('goal_id', 'capability_id', 'target_skill')):
            # An unread camp is not a consumptive training authorization. Permit
            # the existing training navigation to inspect the current role's panel;
            # only subsequent live queue/strategy checks may authorize TRAIN_TROOPS.
            from .goal_library import GoalState, GoalStatus
            scoped.append(GoalState('KEEP_TRAINING_PRODUCTIVE', GoalStatus.READY,
                          available_skills=('OPEN_QUICK_PANEL',), distance=1.0,
                          evidence={'observation_only': True, 'source': 'DEVELOPMENT_FRESH_READ'}))
        if requested_route == 'FISHING' and not any(
                getattr(goal.status, 'value', goal.status) == 'READY' for goal in scoped):
            # A bait-blocked probe can still ask the existing read-only session to
            # confirm the client counter. Never synthesize a spendable bait Goal.
            from .goal_library import GoalState, GoalStatus
            readonly_scope = all(not scope.get(key) or scope[key] == expected
                for key, expected in (('goal_id', 'OBSERVE_FISHING_STATE'),
                                      ('capability_id', 'READ_FISHING_STATE'),
                                      ('target_skill', 'READ_FISHING_STATE')))
            if readonly_scope:
                scoped.append(GoalState('OBSERVE_FISHING_STATE', GoalStatus.READY,
                          available_skills=('READ_FISHING_STATE',), distance=1.0,
                          evidence={'only_allowed_spend':'NONE','source':'DEVELOPMENT_FRESH_READ'}))
        return scoped

    def _validation_skill_allowed(self, skill_id: str) -> bool:
        scope = getattr(self, 'validation_scope', {})
        target = scope.get('target_skill')
        if self.execution_mode != 'DEVELOPMENT_VALIDATION' or not target:
            return True
        # Preparation/observation/recovery may support the requested concrete
        # action. Another transaction cannot substitute for executing that action.
        return skill_id == target or skill_id.startswith(('OPEN_', 'READ_', 'CHECK_', 'SELECT_', 'OBSERVE_', 'CLOSE_')) or skill_id in {'BACK', 'OPEN_HOME', 'SAFE_STOP'}

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
            if goal.goal_id == 'AVOID_STAMINA_WASTE':
                self._stamina_route(goal,self._gate())
            if not self._policy_allows(goal.goal_id):
                continue
            gate = self._gate()
            validation_goal = str(getattr(self, 'validation_scope', {}).get('goal_id') or '')
            lease = getattr(self, 'device_lease', None)
            held = lease.holder() if lease is not None else None
            if (self.execution_mode == 'DEVELOPMENT_VALIDATION' and validation_goal
                    and held is not None and self._owns_the_lease(held)):
                blocked = gate.blocks(goal, validation_goal_id=validation_goal)
            else:
                blocked = gate.blocks(goal)
            if ((goal.evidence or {}).get("bootstrap_observation_only") is True
                    and blocked is not None and blocked.state != "DEVELOPMENT_PENDING"
                    and not gate.reload_pending):
                # A capability gap still blocks ordinary execution, while this
                # bounded projection can only observe or open a safe entry.
                blocked = None
            if blocked is not None and goal.goal_id == 'AVOID_STAMINA_WASTE' and blocked.capability == 'SPEND_STAMINA_ON_BEAST' and (goal.evidence or {}).get('stamina_sink') in {'INTEL','GIANT_BEAST'}:
                blocked = None  # a failed solo-beast path cannot veto another stamina sink
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

    def _event_readiness_for_goals(self, goals, *, now=None) -> dict[str, float]:
        """Apply live countdown priority only to this runtime's observed role.

        The readiness file is a role-scoped clock, not a second activity calendar.  A saved
        reservation may affect ranking only when this role has a currently actionable goal
        whose own live evidence names the same event.  It cannot synthesize a goal, open a
        page, or transfer one account's event window to another account.
        """
        role_id = self._calendar_role_id()
        if not role_id:
            return {}
        try:
            schedules = event_schedule.load()
        except Exception:  # noqa: BLE001 -- an unreadable clock must leave normal ranking intact
            return {}
        if not schedules:
            return {}
        moment = now or datetime.now(timezone.utc)
        out: dict[str, float] = {}
        for goal in goals or ():
            if not getattr(goal, "available_skills", ()) or goal.priority == float("-inf"):
                continue
            if route_for(str(getattr(goal, "goal_id", "") or "")) is None:
                # Readiness cannot rescue a goal that the live brain has no route for.
                # In particular, BEAR_HUNT remains recorded but must not be promoted as
                # runnable until its alliance navigation/decision path is connected.
                continue
            evidence = getattr(goal, "evidence", None)
            event_id = str(evidence.get("event_id") or "") if isinstance(evidence, Mapping) else ""
            if not event_id:
                continue
            schedule = schedules.get(f"{role_id}|{event_id}")
            if schedule is None or schedule.role_id != role_id or schedule.event_id != event_id:
                continue
            phase = schedule.phase_at(moment)
            # The clock can wake this runtime at the reservation boundary, but it cannot
            # prove that the event is actually open. A past reservation stays useful as
            # evidence and for audit; only a fresh same-role client observation may grant
            # the OPEN production bonus.
            if phase is event_schedule.ReadinessPhase.OPEN:
                if schedule.live_window_state != event_schedule.LiveWindowState.OPEN.value:
                    continue
                try:
                    seen = datetime.fromisoformat(str(schedule.live_window_observed_at or ""))
                    if seen.tzinfo is None:
                        seen = seen.replace(tzinfo=timezone.utc)
                    if (moment - seen).total_seconds() > 15 * 60:
                        continue
                except (TypeError, ValueError):
                    continue
            bonus = event_schedule.PHASE_PRIORITY[phase]
            if bonus > 0:
                out[str(goal.goal_id)] = bonus
        return out

    def _stamina_route(self, best_goal, gate):
        from .operations_policy import choose_stamina_goal
        data = best_goal.evidence or {}
        intel = data.get('intel_state') or {}
        blocked_states = {'BLOCKED','COOLDOWN','DEFERRED','DEVELOPMENT_PENDING'}
        intel_blocked = (gate.capabilities.get('READ_INTEL_LIST') or (None,))[0] in blocked_states
        beast_blocked = (gate.capabilities.get('SPEND_STAMINA_ON_BEAST') or (None,))[0] in blocked_states
        runnable_intel = (not intel_blocked and intel.get('status') == 'AVAILABLE'
                          and intel.get('untried_pins', intel.get('pins', 1)) != 0)
        own = data.get('own_rally') or {}
        sink = choose_stamina_goal(data.get('current'), 'AVAILABLE' if runnable_intel else 'NOT_AVAILABLE',
            not getattr(self,'_giant_stamina_failed',False), not beast_blocked,
            idle_slots=data.get('idle_marches'), own_rally=bool(own.get('dispatch_pending') or own.get('waiting_rally')) or
                (own.get('ownership') == 'SELF' and isinstance(own.get('remaining_seconds'),int)
                 and own['remaining_seconds'] > 0))
        route = {'INTEL':'SPEND_STAMINA','GIANT_BEAST':'GIANT_BEAST','BEAST_HUNT':'BEAST_HUNT',
                 'OBSERVE_STAMINA':'STAMINA_OBSERVE'}.get(sink.goal,'STAMINA_WAIT')
        data.update(stamina_sink=sink.goal, stamina_sink_reason=sink.reason)
        if sink.goal == 'GIANT_BEAST':
            data['rally_target'] = 'POLAR_TERROR'
        else:
            data.pop('rally_target',None)
        return route

    def _sync_brain_goal(self, best_goal, gate) -> None:
        """Keep the brain's route and task identity aligned with this scheduler tick.

        The board is re-ranked after every action. Keeping the first selected route for the
        whole bounded run lets a later Goal inherit the previous task's page logic (for
        example, a training Goal opening the research row). The concrete goal id is the
        authority for row ownership; clear both fields when the board has no runnable Goal.
        """
        self._bootstrap_context = dict(getattr(best_goal, "evidence", {}) or {}) if best_goal is not None else {}
        if best_goal is None:
            changed = self.brain.current_goal is not None or bool(getattr(self.brain, "goal_id", ""))
            self.brain.current_goal = None
            self.brain.goal_id = ""
            self.brain.daily_task_id = ""
            if changed:
                self.brain.terminal_page_left = False
            return

        route = route_for(best_goal.goal_id)
        if best_goal.goal_id == "AVOID_STAMINA_WASTE":
            route = self._stamina_route(best_goal, gate)

        changed = (
            self.brain.current_goal != route
            or str(getattr(self.brain, "goal_id", "") or "") != str(best_goal.goal_id)
        )
        self.brain.current_goal = route
        self.brain.goal_id = best_goal.goal_id
        self.brain.daily_task_id = str((getattr(best_goal, "evidence", {}) or {}).get("daily_task_id") or "")
        if changed:
            # A terminal-page refusal belongs to the previous task instance. It must not
            # prevent a newly selected Goal from trying its own measured route.
            self.brain.terminal_page_left = False

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
            return dict(observation_store.as_observation_input(
                observation_store.load(self._role_observation_store_path())
            ))
        except Exception:  # noqa: BLE001 - a broken store means "nothing is fresh", never a crash
            return {}

    def _stored_stamina_value(self) -> int | None:
        """The stamina this project last believed, from its own observation store."""
        from . import observation_store

        try:
            domains = (observation_store.load(self._role_observation_store_path()) or {}).get("domains") or {}
            reading = (domains.get("stamina") or {}).get("reading") or {}
            value = reading.get("current")
            return int(value) if isinstance(value, (int, float)) else None
        except Exception:  # noqa: BLE001 - a broken store must not stop a run
            return None

    def _fishing_pressures(self) -> dict:
        """Per-role bait verdict for the fishing event, per FISHING POLICY V2 §3/§14/§15.

        Read once per discovery (i.e. once per tick), so the store is reloaded only when its
        mtime moves -- the answer changes when a bait reading, a finished run or a
        regeneration is written, and at no other time.

        A missing or unreadable store yields ``{}`` -- **no verdict** -- which is the point:
        ``goal_library`` then leaves the fishing event exactly as the generic path would have
        left it, rather than receiving an urgency nobody measured.  §3 wants a *reason* to
        interrupt the running Role Session, and an unread file is not one.
        """
        from . import fishing_pressure, fishing_state

        path = Path(fishing_state.DEFAULT_PATH)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            self._fishing_pressure_cache = (None, {})
            return {}
        cached = getattr(self, "_fishing_pressure_cache", None)
        state = None
        try:
            state = cached[1] if cached is not None and cached[0] == stamp else fishing_state.FishingState.load(path)
            pressures = fishing_pressure.pressures_by_role_id(
                state, datetime.now(timezone.utc),
            )
        except Exception:  # noqa: BLE001 - an unreadable store is "no reading", never a crash
            pressures = {}
        if state is not None:
            self._fishing_pressure_cache = (stamp, state)
        return pressures

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

        store_path = self._role_observation_store_path()

        for routine in (*PANEL_ROUTINES, *SWEEP_ROUTINES):
            reading = getattr(world, routine.field, None)
            if reading:
                try:
                    observation_store.record(routine.field, reading, frame=frame, path=store_path)
                except Exception:  # noqa: BLE001 - observing must never fail a run
                    pass
        # The HUD gauge is read on many frames but is a *domain* like the others: the stamina goal
        # exists only while it is readable, so the last reading has to outlive the frame that
        # produced it or the goal disappears from the board whenever the gauge is off screen.
        stamina_reading = world.stamina
        if not isinstance(stamina_reading.get('current'), int) and isinstance(world.intel.get('stamina'), int):
            stamina_reading = {'current': world.intel['stamina'], 'source': 'LIVE_INTEL_HUD'}
        if isinstance(stamina_reading.get('current'), int):
            try:
                observation_store.record("stamina", stamina_reading, frame=frame, path=store_path)
            except Exception:  # noqa: BLE001
                pass

    def _calendar_role_id(self) -> str:
        """Use role-scoped calendar state only when the current role is freshly confirmed."""
        if (getattr(self, "_multi_role_enabled", False)
                and not getattr(self, "_role_identity_confirmed", False)):
            return ""
        role_id = str(getattr(self, "role_id", "") or "")
        if not role_id:
            return ""
        role_scope = str(getattr(self, "role_scope", "") or "").upper()
        if role_scope and role_scope not in {"LIVE_OBSERVED", "FRESH_RUNTIME"}:
            return ""
        return role_id

    def _role_observation_store_path(self) -> Path | None:
        """Keep sticky panel readings separate by account in multi-role mode."""
        role_id = self._calendar_role_id()
        if not role_id:
            return None
        return Path(__file__).resolve().parents[1] / "learning" / "roles" / role_id / "observation_state.json"

    def _activate_role_persistent_state(self, role_id: str) -> None:
        """Bind account-specific counters after the current frame proves its role."""
        if not self._multi_role_enabled or role_id not in self._role_catalog_by_id:
            return
        directory = Path(__file__).resolve().parents[1] / "learning" / "roles" / role_id
        self.resource_rotation = ResourceRotationStore(directory / "resource_rotation.json")
        self.stamina_supply = StaminaSupplyStore(directory / "stamina_supply.json")
        self._fairness_store_path = directory / "goal_fairness.json"
        self._fairness = goal_utility.load(self._fairness_store_path)

    def _global_role_observations(
        self,
        world: WorldState,
        goals: Iterable[Any],
        decision: Decision,
        *,
        role_switch_cost: float | None = None,
    ) -> tuple[Any, ...]:
        """Build one current live row plus logical-only rows for every other role."""
        if not self._multi_role_enabled or not self._calendar_role_id():
            return ()
        from .goal_library import GoalState, GoalStatus
        from .scheduler import RoleObservation

        moment = datetime.now(timezone.utc)
        goals = tuple(goals)
        effective_switch_cost = (self.role_switch_cost if role_switch_cost is None
                                 else max(0.0, float(role_switch_cost)))
        active_id = self._calendar_role_id()
        snapshots = self.goal_store.read_roles() if self.goal_store is not None else {}
        global_state = (self.global_scheduler_state_store.load()
                        if self.global_scheduler_state_store is not None else None)
        stored_roles = getattr(global_state, "roles", {}) if global_state is not None else {}
        result: list[RoleObservation] = []

        def cached_wakeup(value: Any, reference: datetime | None) -> datetime | None:
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            text = str(value or "").strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            seconds = None
            if text.isdigit():
                seconds = int(text)
            else:
                countdown = re.fullmatch(
                    r"(?:(\d+)\s*(?:天|d)\s*)?(\d{1,3}):(\d{2}):(\d{2})",
                    text,
                    re.IGNORECASE,
                )
                if countdown:
                    days, hours, minutes, remainder = countdown.groups()
                    hours_value, minutes_value, seconds_value = (
                        int(hours), int(minutes), int(remainder)
                    )
                    if minutes_value < 60 and seconds_value < 60:
                        seconds = (
                            int(days or 0) * 86400
                            + hours_value * 3600
                            + minutes_value * 60
                            + seconds_value
                        )
                elif ":" in text and all(part.isdigit() for part in text.split(":")):
                    parts = [int(part) for part in text.split(":")]
                    if len(parts) == 2:
                        seconds = parts[0] * 60 + parts[1]
                    elif len(parts) == 3:
                        seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            return (reference + timedelta(seconds=max(0, seconds))
                    if seconds is not None and reference is not None else None)

        def queue_reading_wakeup(goal: GoalState, evidence: Mapping[str, Any],
                                 reference: datetime | None) -> datetime | None:
            queue_goals = {
                "KEEP_TRAINING_PRODUCTIVE",
                "KEEP_RESEARCH_PRODUCTIVE",
                "KEEP_BUILDING_PRODUCTIVE",
            }
            goal_id = str(goal.goal_id)
            if goal_id not in queue_goals and not goal_id.endswith("_CAMP_TRAINING"):
                return None
            reading = evidence.get("reading")
            if not isinstance(reading, Mapping):
                return None
            busy = (str(reading.get("status") or "").upper() == "IN_PROGRESS"
                    or reading.get("queue_available") is False)
            if not busy:
                return None
            return cached_wakeup(reading.get("timer") or reading.get("source_word"), reference)

        for role_id, identity in self._role_catalog_by_id.items():
            if role_id == active_id:
                active_waits: list[datetime] = []
                for goal in goals:
                    evidence = goal.evidence if isinstance(goal.evidence, Mapping) else {}
                    candidates = [cached_wakeup(goal.retry_after, moment)]
                    candidates.extend(cached_wakeup(evidence.get(key), moment) for key in (
                        "next_action_at", "wait_until", "expected_finish_at",
                    ))
                    candidates.append(queue_reading_wakeup(goal, evidence, moment))
                    condition = str(evidence.get("condition") or "").lower()
                    if (goal.status is GoalStatus.BLOCKED
                            and condition in {"queue_busy", "camp_queue_busy"}
                            and goal.remaining_seconds is not None):
                        candidates.append(moment + timedelta(seconds=max(0, int(goal.remaining_seconds))))
                    active_waits.extend(
                        value for value in candidates if value is not None and value > moment
                    )
                result.append(RoleObservation(
                    role_id=role_id,
                    confirmed_role_id=active_id,
                    world=world,
                    observed_at=world.timestamp or moment,
                    decision=decision,
                    goals=tuple(goals),
                    next_action_at=min(active_waits).isoformat() if active_waits else None,
                    switch_cost=0.0,
                ))
                continue

            snapshot = snapshots.get(role_id) if isinstance(snapshots, Mapping) else None
            saved_role = stored_roles.get(role_id) if isinstance(stored_roles, Mapping) else None
            saved_role = saved_role or {}
            observed_at = ((snapshot or {}).get("observed_at")
                           or getattr(saved_role, "last_observed_at", None)
                           or identity.get("identity_observed_at"))
            stamp = None
            if observed_at:
                try:
                    stamp = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    stamp = None
            age_seconds = ((moment - stamp).total_seconds() if stamp else float("inf"))
            parsed_goals: list[Any] = []
            for row in (snapshot or {}).get("goals", ()):
                if not isinstance(row, Mapping) or not row.get("goal_id"):
                    continue
                try:
                    status = GoalStatus(str(row.get("status") or "UNKNOWN").upper())
                except ValueError:
                    status = GoalStatus.UNKNOWN
                remaining = row.get("remaining_seconds")
                if remaining is not None and age_seconds >= 0:
                    remaining = max(0, int(remaining) - int(age_seconds))
                values = {
                    name: row.get(name)
                    for name in (
                        "completion", "reward_value", "daily_loss", "event_synergy",
                        "development_value", "resource_cost", "risk", "retry_after",
                        "evidence", "distance",
                    )
                    if row.get(name) is not None
                }
                parsed_goals.append(GoalState(
                    goal_id=str(row["goal_id"]),
                    status=status,
                    remaining_seconds=remaining,
                    available_skills=tuple(str(item) for item in (row.get("available_skills") or ())),
                    **values,
                ))
            retry_times: list[datetime] = []
            for goal in parsed_goals:
                candidates = [cached_wakeup(goal.retry_after, stamp)]
                evidence = goal.evidence if isinstance(goal.evidence, Mapping) else {}
                candidates.extend(cached_wakeup(evidence.get(key), stamp) for key in (
                    "next_action_at", "wait_until", "expected_finish_at",
                ))
                candidates.append(queue_reading_wakeup(goal, evidence, stamp))
                condition = str(evidence.get("condition") or "").lower()
                if (goal.status is GoalStatus.BLOCKED
                        and condition in {"queue_busy", "camp_queue_busy"}
                        and goal.remaining_seconds is not None and stamp is not None):
                    candidates.append(stamp + timedelta(seconds=max(0, int(goal.remaining_seconds))))
                retry_times.extend(
                    value for value in candidates if value is not None and value > moment
                )
            result.append(RoleObservation(
                role_id=role_id,
                confirmed_role_id=role_id,
                world=None,
                observed_at=observed_at,
                goals=tuple(parsed_goals),
                next_action_at=min(retry_times).isoformat() if retry_times
                else getattr(saved_role, "next_action_at", None),
                switch_cost=effective_switch_cost,
                switch_blocked_until=getattr(saved_role, "blocked_until", None),
                failure_streak=int(getattr(saved_role, "switch_failure_streak", 0) or 0),
                needs_initial_refresh=(not snapshot or age_seconds > 30 * 60),
            ))
        return tuple(result)

    def _measured_role_switch_cost(self, state: Any | None) -> float:
        """Map observed median switch latency to the same explainable score penalty."""
        samples = getattr(state, "role_switch_durations_ms", ()) if state is not None else ()
        valid = sorted(float(value) for value in samples
                       if isinstance(value, (int, float)) and float(value) >= 0)
        if not valid:
            return self.role_switch_cost
        median_ms = valid[(len(valid) - 1) // 2]
        # A second of real loading time is one score point, with the configured
        # baseline protecting the first measured rounds and a cap preventing an
        # unhealthy device from making account switching mathematically impossible.
        return max(self.role_switch_cost, min(180.0, median_ms / 1000.0))

    def _bootstrap_state(self):
        """Cooldowns for observation attempts, not another task queue or WorldState."""
        if not hasattr(self, "_bootstrap_cooldowns"):
            path = getattr(self, "bootstrap_state_path", None)
            self._bootstrap_cooldowns = {}
            if path is None and getattr(self, "episode_store", None) is not None:
                path = Path(self.episode_store.path).resolve().parent / "capability_bootstrap/runtime_discovery.json"
                self.bootstrap_state_path = path
            if path is not None:
                try:
                    payload = json.loads(Path(path).read_text(encoding="utf-8"))
                    self._bootstrap_cooldowns = {
                        key: {"cooldown_until": value.get("cooldown_until")}
                        for key, value in payload.items() if isinstance(value, dict)
                        and value.get("cooldown_until")
                    }
                except (OSError, ValueError, TypeError):
                    pass
        return self._bootstrap_cooldowns

    def _learning_window_open(self) -> bool:
        """May this run spend one step preparing safe discovery while real work exists?

        Operator directive 2026-10-01 §二十四: "让无人值守时间变成自动补能力时间".  The rule
        this replaces -- *prepare discovery only when there is no known executable work at all*
        (``if not known_work``) -- is correct about priority and, measured 2026-10-01, it never
        fires in production: the board always has something runnable, so the element table was
        never built, ``capability_bootstrap`` was never given a candidate step, and
        ``learning/capability_bootstrap/runtime_discovery.json`` had never been written once in
        the project's history.  The learning window was closed permanently and nothing said so.

        One shot per process, not per step: preparing candidates costs a full-frame OCR and this
        module's own rule is "do not widen OCR or call a model merely to prepare a coverage
        report".  Note the flag is set *before* the answer is known -- a run that opens the window
        and then finds nothing to offer does not get to pay for it on every subsequent step.

        Everything that bounds the attempt downstream stays where it already is: one visit per
        run and a 300 s cooldown come from ``capability_bootstrap``'s own budget (read here rather
        than restated), and consumption, rally and purchase verbs are refused inside the
        projection.  This function grants no permission; it only stops the door being welded shut.
        """
        if getattr(self, "_learning_window_used", False):
            return False
        self._learning_window_used = True
        try:
            state = self._bootstrap_state()
        except Exception:  # noqa: BLE001 - an unreadable ledger must not open a window
            return False
        row = state.get("__run__") if isinstance(state, dict) else None
        visits = int((row or {}).get("visits_this_run") or 0) if isinstance(row, dict) else 0
        return visits < DEFAULT_BUDGET["max_bootstrap_visits_per_run"]

    def _project_capability_discovery(self, goals, world, frame):
        """Offer safe current-frame discovery to the existing Goal/Scheduler board."""
        from .goal_library import GoalStatus
        registry = getattr(self, "registry", None)
        if registry is None:
            return goals
        role = self._calendar_role_id()
        if not role or not frame or world.page in {Page.LOADING, Page.MAINTENANCE}:
            return goals
        from .ui_venus_online import FrameIdentity
        try:
            identity = FrameIdentity.of(Path(frame))
        except (OSError, ValueError):
            return goals
        registered = {skill.id for skill in registry.all()
                      if skill.state.value != "BLOCKED" and not skill.session_only}
        enabled = {goal.goal_id for goal in goals if self._policy_allows(goal.goal_id)}
        cooldowns = self._bootstrap_state()
        known_work = any(
            goal.goal_id in enabled and goal.status in {GoalStatus.READY, GoalStatus.DISCOVERED}
            and route_for(goal.goal_id) and goal.goal_id not in getattr(self, "_yielded_goals", set())
            and any(sid in registered and sid in self.VERIFIED_ATOMIC for sid in goal.available_skills)
            and self._gate().blocks(goal) is None for goal in goals
        )
        elements, steps = [], {}
        # Do not widen OCR or call a model merely to prepare a coverage report.
        # Safe discovery gets the device only after the known executable work yields.
        #
        # ...and once per run even when it does not yield (2026-10-01 §二十四).  The original
        # condition made the learning window unreachable in production, which is the opposite of
        # "unattended time is learning time" -- see ``_learning_window_open`` for the measurement.
        if not known_work or self._learning_window_open():
            try:
                elements = ui_collection.build_element_table(Path(frame), self._ocr_service(), page=world.page.value)
            except (OSError, ValueError, AttributeError):
                elements = []
            row_regions, _ = self._quick_panel_advice_regions(world, Path(frame))
            elements = list(elements) + [
                {"id": f"ROW_{index}", "kind": "INTERACTIVE_CONTROL", "executable": True,
                 "semantic": row["detail"]["semantic"], "text": row["text"]}
                for index, row in enumerate(row_regions)
            ]
            hints = {
                "ARENA": ("竞技场",), "RESEARCH": ("学院", "研究"),
                "BUILDING": ("建筑", "建设"), "TRAINING": ("兵营", "训练营"),
                "MAIL": ("邮件",), "DAILY": ("日常任务", "任务"),
                "ALLIANCE": ("联盟",), "EVENT": ("常规活动",),
            }
            for goal in goals:
                if goal.goal_id not in enabled or goal.goal_id in getattr(self, "_yielded_goals", set()):
                    continue
                candidates = []
                for sid in goal.available_skills:
                    skill = registry.get(sid)
                    if (skill is None or sid not in registered or sid not in self.VERIFIED_ATOMIC
                            or not skill.ready(world)):
                        continue
                    action_type = "OBSERVE" if skill.action.kind == "OBSERVE" else "OPEN" if sid.startswith("OPEN_") else ""
                    if not action_type or sid.startswith("OPEN_MARCH"):
                        continue
                    target_id = ""
                    if action_type == "OPEN":
                        point = self._resolve_semantic_target(str(skill.action.target or ""), world, frame_path=Path(frame))
                        if point is None:
                            continue
                        target_id = f"SKILL_{sid}"
                        elements.append({"id": target_id, "kind": "INTERACTIVE_CONTROL", "executable": True,
                                         "semantic": skill.action.target})
                    candidates.append({"skill_id": sid, "action_type": action_type,
                        "semantic_target": str(skill.action.target or ""), "target_id": target_id,
                        "role_id": role, "frame_id": identity.frame_id})
                route = route_for(goal.goal_id)
                labels = list(hints.get(str(route or ""), ()))
                if "ARENA" in goal.goal_id:
                    labels.extend(hints["ARENA"])
                evidence = goal.evidence or {}
                labels += [str(evidence[key]) for key in ("event_name", "display_name", "activity_name") if evidence.get(key)]
                if goal.goal_id.startswith("SCHEDULED_") and evidence.get("event_id"):
                    # Activity registration uses name/aliases; these authorize only
                    # the same bounded entry observation, never participation.
                    if evidence.get("name"):
                        labels.append(str(evidence["name"]))
                    labels.extend(str(label) for label in evidence.get("aliases", ())
                                  if isinstance(label, str) and label)
                for index, element in enumerate(elements):
                    text = str(element.get("text") or "").strip()
                    if (not text or text not in labels or element.get("executable") is not True
                            or element.get("kind") not in {"INTERACTIVE_CONTROL", "COMPOSITE_CONTROL", "ICON"}):
                        continue
                    element.setdefault("id", f"ENTRY_{index}")
                    candidates.append({"skill_id": "TRY_ORDINARY_CONTROL", "action_type": "OPEN",
                        "semantic_target": str(element.get("semantic") or ""),
                        "target_id": element["id"], "role_id": role, "frame_id": identity.frame_id,
                        "entry_label": text, "model_required": True})
                if candidates:
                    steps[goal.goal_id] = candidates
        projection = project_runtime_discovery(
            goals, world, role_id=role, frame_id=identity.frame_id,
            current_frame_elements={"frame_id": identity.frame_id, "role_id": role, "elements": elements},
            enabled_goal_ids=enabled, safe_steps_by_goal=steps, cooldowns=cooldowns,
            registry_ids=registered, verifier_bindings=self.VERIFIED_ATOMIC,
        )
        projected = list(projection.goals)
        for goal in projected:
            if not (goal.evidence or {}).get("bootstrap_stage"):
                continue
            step = next(item for item in steps[goal.goal_id] if item["skill_id"] == goal.evidence["bootstrap_skill_id"]
                        and item["target_id"] == goal.evidence["bootstrap_target_id"])
            goal.evidence["bootstrap_entry_label"] = step.get("entry_label", "")
            goal.evidence["bootstrap_goal_id"] = goal.goal_id
        self._bootstrap_diagnostics = list(projection.diagnostics)
        self._runtime(capability_discovery=list(projection.diagnostics))
        return projected

    def _bootstrap_decision(self, goal, world):
        evidence = dict(getattr(goal, "evidence", {}) or {})
        if not evidence.get("bootstrap_stage"):
            return None
        skill = self.registry.get(str(evidence.get("bootstrap_skill_id") or ""))
        if skill is None or not skill.ready(world):
            return Decision("WAIT", "BOOTSTRAP_ENTRY_NOT_READY", world.confidence, "fresh observation required")
        return Decision(skill.id, f"CAPABILITY_BOOTSTRAP:{evidence['bootstrap_gap']}",
                        world.confidence, "safe entry/state observation; goal completion remains unproven")

    def _mark_bootstrap_attempt(self, goal):
        evidence = dict(getattr(goal, "evidence", {}) or {})
        if not evidence.get("bootstrap_stage"):
            return
        state = self._bootstrap_state()
        key = f"{self._calendar_role_id()}|{goal.goal_id}"
        row = state.setdefault(key, {})
        row["attempts_this_run"] = int(row.get("attempts_this_run") or 0) + 1
        row["cooldown_until"] = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
        state.setdefault("__run__", {})["visits_this_run"] = 1
        path = getattr(self, "bootstrap_state_path", None)
        if path is not None:
            try:
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                pending = path.with_suffix(".tmp")
                pending.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(pending, path)
            except OSError as exc:
                self._narrate_once(f"bootstrap cooldown persistence failed: {type(exc).__name__}")
        self._record_session_timeline("CAPABILITY_BOOTSTRAP_ATTEMPT", goal_id=goal.goal_id,
            role_id=self._calendar_role_id(), skill_id=evidence.get("bootstrap_skill_id"),
            frame_id=evidence.get("bootstrap_frame_id"), stage=evidence.get("bootstrap_stage"))

    def _read_due_calendar_entry(self, world: WorldState, frame: Path) -> WorldState:
        """Read calendar UI on this frame only when maintenance or a return is due."""
        from . import event_calendar
        role = self._calendar_role_id()
        pending = event_schedule.calendar_detail_return_pending(role)
        if world.page is Page.UNKNOWN:
            return replace(world, events={**world.events, "calendar_detail_return_pending": True}) if pending else world
        if world.page not in {Page.HOME, Page.MAP, Page.EVENT}:
            return world
        if not (pending or event_schedule.calendar_scan_due(role)):
            return world
        ocr = self._ocr_service()
        if ocr is None:
            return world
        result = ocr.recognize(frame)
        size = read_frame_size(frame)
        events = dict(world.events or {})
        if world.page in {Page.HOME, Page.MAP}:
            entry = event_calendar.read_calendar_entry(result.tokens, frame_size=size)
            if entry:
                events["calendar_entry"] = entry
            if pending:
                event_schedule.clear_calendar_detail_return_pending(role,
                    observed_at=world.timestamp or datetime.now(timezone.utc),
                    reason=f"fresh_known_page_{world.page.value}", evidence_ref=str(frame))
            return replace(world, events=events)
        calendar = event_calendar.read_event_calendar(result.tokens, frame_size=size)
        detail = event_calendar.read_event_detail(result.tokens, event_label=None, frame_size=size)
        if detail.get("recognized") is True:
            if calendar.get("details_visible") is True or pending:
                events.pop("calendar", None)
                events["calendar_overlay_detected"] = True
                saved = event_schedule.latest_calendar_snapshot(role, kind="EVENT_DETAIL") or {}
                prior = saved.get("observation") or {}
                if prior.get("event_id") == detail.get("event_id"):
                    detail = {**detail, **{key: prior[key] for key in (
                        "matched_event_id", "matched_occurrence_key", "calendar_origin") if key in prior}}
                if not detail.get("matched_occurrence_key"):
                    grid = event_schedule.latest_calendar_snapshot(role) or {}
                    candidates = [row for row in grid.get("entries") or []
                                  if row.get("event_id") == detail.get("event_id")
                                  and row.get("details_observed") is not True]
                    if len(candidates) == 1:
                        detail.update(matched_event_id=candidates[0].get("event_id"),
                                      matched_occurrence_key=candidates[0].get("occurrence_key"))
                detail["calendar_origin"] = "GRID_ENTRY"
            events["calendar_detail"] = detail
        elif calendar.get("recognized") is True:
            events["calendar"] = event_schedule.annotate_calendar_observation(role, calendar)
        return replace(world, events=events)

    def _record_calendar_observation(self, world: WorldState, frame=None) -> None:
        role = self._calendar_role_id()
        events = world.events or {}
        stamp = world.timestamp or datetime.now(timezone.utc)
        calendar, detail = events.get("calendar"), events.get("calendar_detail")
        if isinstance(detail, Mapping) and detail.get("recognized") is True:
            event_schedule.record_calendar_detail(role_id=role, observation=detail,
                observed_at=stamp, evidence_ref=str(frame or ""))
        elif isinstance(calendar, Mapping) and calendar.get("recognized") is True:
            event_schedule.record_calendar_snapshot(role_id=role, observation=calendar,
                observed_at=stamp, evidence_ref=str(frame or ""))

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
        self._record_calendar_observation(world, frame)
        role_id = self._calendar_role_id()
        calendar_snapshot = event_schedule.latest_calendar_snapshot(role_id)
        event_rows = world.events if isinstance(world.events, Mapping) else {}
        live_calendar = event_rows.get("calendar")
        if role_id and isinstance(live_calendar, Mapping) and live_calendar.get("recognized") is True:
            calendar_snapshot = {
                **event_schedule.annotate_calendar_observation(role_id, live_calendar),
                "role_id": role_id,
                "observed_at": str(world.timestamp or datetime.now(timezone.utc).isoformat()),
            }
        discover = self.goal_library.discover
        discover_kwargs = {
            "observations": self._observations_for_engine(),
            # A completed quick-panel row closes the panel and removes the camp's
            # queue row from this frame.  GoalLibrary already knows how to keep
            # that selected camp runnable while the current-frame focus halo is
            # present; pass the role's committed goal so the scheduler can take
            # the action-bar hop before unrelated discovery work replaces it.
            "training_continuation_goal_id": str(
                getattr(self, "_committed_goal", "") or ""
            ),
            "role_id": role_id,
            "calendar_snapshot": calendar_snapshot,
            # FISHING POLICY V2 §3/§14/§15: the bait budget, not the event countdown,
            # decides how urgently the fishing event may claim the device.
            "fishing_pressures": self._fishing_pressures(),
        }
        # Preserve lightweight GoalLibrary adapters used by older integrations and
        # deterministic runtime tests. The real GoalLibrary accepts the full context;
        # adapters receive only the named parameters they implement.
        try:
            parameters = inspect.signature(discover).parameters.values()
            accepts_kwargs = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters)
            accepted_names = {item.name for item in parameters}
            if not accepts_kwargs:
                discover_kwargs = {key: value for key, value in discover_kwargs.items()
                                   if key in accepted_names}
        except (TypeError, ValueError):
            pass
        goals = discover(world, **discover_kwargs)
        goals = self._project_capability_discovery(goals, world, frame)
        for goal in goals:
            if goal.goal_id == 'AVOID_STAMINA_WASTE':
                self._stamina_route(goal, self._gate())
        if self.goal_store is not None:
            try:
                self.goal_store.write(world, goals, role_id=role_id)
            except (OSError, TypeError, ValueError):
                pass
        if self.task_completion_store is not None and role_id:
            try:
                identity = self._role_catalog_by_id.get(role_id, {})
                self.task_completion_store.observe_role(
                    role_id=role_id,
                    role_key=str(identity.get("role_key") or ""),
                    goals=goals,
                    observed_at=world.timestamp or datetime.now(timezone.utc),
                )
            except Exception:  # noqa: BLE001 - reporting must never stop the game loop
                # This board is a readout of the production loop; its writer must
                # never become a reason to repeat or stop a game action.
                pass
            global_store = getattr(self, "global_scheduler_state_store", None)
            if self._multi_role_enabled and role_id and global_store is not None:
                try:
                    summaries = [
                        {
                            "goal_id": goal.goal_id,
                            "status": goal.status.value,
                            "priority": None if goal.priority == float("-inf") else goal.priority,
                            "remaining_seconds": goal.remaining_seconds,
                            "available_skills": list(goal.available_skills),
                            "completion": goal.completion,
                            "distance": goal.distance,
                            "retry_after": goal.retry_after,
                            "evidence": dict(goal.evidence) if isinstance(goal.evidence, Mapping) else {},
                        }
                        for goal in goals
                    ]
                    global_store.record_role_observation(
                        role_id=role_id,
                        observed_at=world.timestamp or datetime.now(timezone.utc),
                        page=world.page.value,
                        page_confidence=world.confidence,
                        goal_summaries=summaries,
                        current_goal=str(getattr(self, "_committed_goal", "") or ""),
                    )
                except (OSError, TypeError, ValueError):
                    pass
        return goals

    def _retry_semantic_click(self, *, decision, before, before_path, after, after_path,
                              execution, verify, resource, rally_target, index, settle, latency=None):
        """Delivery retries stay inside one selected Skill and the existing executor."""
        skill = self.registry.get(decision.skill)
        if skill is None or skill.action.kind != "TAP_SEMANTIC":
            return after, after_path, execution, verify(before, after), None
        action = skill.action
        role_id = self._calendar_role_id()

        def authorized(world):
            held = self.device_lease.holder() if self.device_lease else None
            if held is not None and not self._owns_the_lease(held):
                return False
            if self.execution_mode == OWNER_DEVELOPMENT_VALIDATION and not self._owns_the_lease(held):
                return False
            if self._calendar_role_id() != role_id:
                return False
            goal_id = str(getattr(self, "_committed_goal", "") or "")
            if goal_id and not self._policy_allows(goal_id):
                return False
            if self._multi_role_enabled:
                state = self.global_scheduler_state_store.load()
                if state.role_switch_pending or state.active_role_id != role_id:
                    return False
            return skill.ready(world) and SafetyPolicy().evaluate(action).allowed

        rally_row_id = None
        if action.target == "RALLY_ROW_JOIN_BUTTON" and execution.tap_point:
            size = self.device.status().resolution
            if size:
                x, y = execution.tap_point[0] / size[0], execution.tap_point[1] / size[1]
                rows = before.rally.get("rows") or ()
                selected = [r for r in rows if isinstance(r, dict)
                            and isinstance(r.get("join_button_bbox"), (list, tuple))
                            and len(r.get("join_button_bbox")) == 4
                            and r["join_button_bbox"][0] <= x <= r["join_button_bbox"][2]
                            and r["join_button_bbox"][1] <= y <= r["join_button_bbox"][3]]
                if len(selected) == 1:
                    rally_row_id = selected[0].get("row_id")

        def resolve_current(world, path, semantic):
            if semantic == "RALLY_ROW_JOIN_BUTTON":
                rows = world.rally.get("rows") or ()
                selected = [r for r in rows if rally_row_id and r.get("row_id") == rally_row_id
                            and r.get("state") == "JOINABLE" and r.get("full") is not True]
                return selected[0].get("join_norm") if len(selected) == 1 else None
            if semantic == "ORDINARY_CONTROL":
                # This resolver marks exploration attempts; do not mutate that budget
                # by probing an already executed action for retry evidence.
                return None
            return self._resolve_semantic_target(
                semantic, world, frame_path=path, resource=resource, rally_target=rally_target)

        def target(world, path):
            point = resolve_current(world, path, action.target)
            if point is None:
                return None
            context = {"role_id": role_id, "page": world.page.value,
                       "popup": world.popup, "semantic": action.target}
            for field in ("training", "research", "building", "beast_search_result",
                          "resource_target", "hero_troop", "inventory"):
                context[field] = click_retry.stable_context(getattr(world, field))
            label = f"{decision.skill} {action.target}".upper()
            pending = not any(word in label for word in ("CONFIRM", "RECALL", "USE_ITEM", "PURCHASE"))
            if "TRAIN_TROOPS" in label or "PROMOTE" in label:
                pending = world.training.get("queue_available") is True
            elif decision.skill == "RESEARCH":
                pending = world.research.get("queue_available") is True
            elif decision.skill == "BUILDING_UPGRADE":
                pending = world.building.get("queue_available") is True
            elif "DISPATCH" in label or "ATTACK" in label or "START_RALLY" in label:
                pending = world.has_free_march_slot is True and bool(
                    world.beast_search_result or world.hero_troop or world.rally)
            elif action.target == "RALLY_ROW_JOIN_BUTTON":
                rows = world.rally.get("rows") or world.alliance.get("rally", {}).get("rows") or ()
                selected = []
                for row in rows:
                    box = row.get("join_button_bbox")
                    if (isinstance(box, (list, tuple)) and len(box) == 4
                            and box[0] <= point[0] <= box[2]
                            and box[1] <= point[1] <= box[3]):
                        selected.append(row)
                if len(selected) != 1:
                    return None
                row = selected[0]
                context["rally_target"] = {
                    key: row.get(key) for key in ("row_id", "target_type", "target", "leader")}
                pending = bool(row.get("leader") and row.get("state") == "JOINABLE"
                               and world.has_free_march_slot is True)
            elif "CLAIM" in label or "COLLECT" in label:
                # A claimable badge on an unrelated page is not this claim's state.
                domain = next((name.lower() for name in (
                    "TRAINING", "DAILY", "MAIL", "ALLIANCE", "STAMINA", "EXPLORATION", "INTEL")
                    if name in label), None)
                if "ALLY_GIFT" in label:
                    domain = "alliance"
                domain = domain or {Page.EVENT: "events", Page.POPUP: "rewards"}.get(world.page)
                readings = [getattr(world, domain)] if domain else []
                pending = any(r.get("claimable") is True
                              or r.get("free_claim_available") is True
                              or r.get("status") in {"CLAIMABLE", "COMPLETED"} for r in readings)
            elif "USE_ITEM" in label or "PURCHASE" in label:
                pending = any(key in world.inventory for key in ("item_id", "selected_item")) and any(
                    isinstance(world.inventory.get(key), int)
                    for key in ("quantity", "item_count", "count"))
            return click_retry.TargetEvidence(str(action.target), True, context, pending)

        def observation(world, path, verdict):
            return click_retry.ClickObservation(
                world, str(path), None if verdict.ok else target(world, path),
                verdict, authorized(world))

        verdict = verify(before, after)
        initial = (click_retry.ClickObservation(before, str(before_path), None,
                   VerificationResult(False, "BEFORE_CLICK")) if verdict.ok
                   else observation(before, before_path, VerificationResult(False, "BEFORE_CLICK")))
        current = observation(after, after_path, verdict)
        captures = 0

        def observe():
            nonlocal captures
            captures += 1
            self.sleeper(settle)
            path = self._capture_path(index, "after", suffix=f"semantic_retry_observe_{captures}")
            if self._device_lost(self.device.screenshot, path):
                return click_retry.ClickObservation(
                    WorldState(), str(path), None,
                    VerificationResult(False, self._device_stop_reason), False)
            world = self._reject_a_dropped_digit(self._observe(path, latency=latency, phase="semantic_retry"))
            if self._multi_role_enabled:
                identified = self.role_switch_controller.identify_current_role(path)
                if identified is not None and identified[0] != role_id:
                    return click_retry.ClickObservation(world, str(path), None,
                        VerificationResult(False, "ROLE_IDENTITY_CHANGED_DURING_RETRY"), False)
            if world.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                world = replace(world, resource_target=resource)
            return observation(world, path, verify(before, world))

        def execute(fresh):
            world, path = fresh.world, Path(fresh.frame)
            if not authorized(world):
                return None
            # Rebind every lookup to this observation; never reuse the first tap's closure.
            def resolve(semantic):
                return resolve_current(world, path, semantic) if authorized(world) else None
            adb = Executor(production=True, dry_run=False, device=self.adb_device,
                           target_resolver=resolve, backend="ADB")
            self._scheduler.executor = build_router(
                adb_executor=adb, adb_resolver=resolve, maa_adapter=self.maa_adapter,
                skill_id=skill.id, routing=self.routing, ledger=self.backend_ledger,
                rally_target=rally_target)
            router = self._scheduler.executor
            if self.maa_adapter is not None and hasattr(router, "maa_resolver"):
                router.retry_rally_row_id = rally_row_id
                def maa_resolve(semantic):
                    if not authorized(world):
                        return None
                    from PIL import Image
                    import numpy as np
                    with Image.open(path) as image:
                        pixels = np.asarray(image.convert("RGB"))
                    return router.maa_resolver(semantic, skill.id, frame=pixels)
                router.maa_executor.target_resolver = maa_resolve
            return self._scheduler.tick(world, decision).execution

        result = click_retry.retry_authorized_semantic_click(
            action=action, before=initial, after=current, execution=execution,
            observe=observe, execute=execute,
            max_retries=self.max_semantic_click_retry, max_observations=0,
            timeout_seconds=min(12.0, max(0.0, skill.timeout)),
        )
        detail = {"semantic_click": {
            "outcome": result.outcome.value, "metric": result.metric,
            "retries": result.retries, "attempts": result.attempts,
            "stop_reason": result.stop_reason,
        }}
        execution = replace(result.execution, detail={**(result.execution.detail or {}), **detail})
        self._record_click_delivery(skill.id, role_id, before_path, result)
        latest = result.observation
        return latest.world, Path(latest.frame), execution, latest.verification, result


    def _record_click_delivery(self, skill_id, role_id, before_path, result):
        """One append per semantic action; transient attempts do not become Skill failures."""
        base = (Path(self.episode_store.path).parent if self.episode_store is not None
                else self.capture_dir)
        try:
            base.mkdir(parents=True, exist_ok=True)
            row = {"timestamp": datetime.now(timezone.utc).isoformat(), "role_id": role_id,
                   "skill": skill_id, "before_frame": str(before_path),
                   "after_frame": result.observation.frame, "repo_revision": self.code_revision,
                   "outcome": result.outcome.value, "metric": result.metric,
                   "retries": result.retries, "attempts": result.attempts,
                   "stop_reason": result.stop_reason}
            with (base / "semantic_click_retry.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            metrics_path = base / "semantic_click_retry_metrics.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
            if result.metric:
                metrics[result.metric] = int(metrics.get(result.metric, 0)) + 1
            metrics["updated_at"] = row["timestamp"]
            metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError):
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
        goal_progress: bool | None = None,
        attached_goal_ids: Iterable[str] = (),
        goal_progress_by_id: Mapping[str, bool | None] | None = None,
        completed_goal_ids: Iterable[str] = (),
        before_screenshot: Path | None = None,
        after_screenshot: Path | None = None,
        session_outcome: str = "",
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
        attached_ids = tuple(dict.fromkeys(
            str(item).strip() for item in attached_goal_ids if str(item).strip()
        ))
        progress_by_goal = {
            str(key): value if isinstance(value, bool) else None
            for key, value in (goal_progress_by_id or {}).items()
            if str(key).strip()
        }
        completed_ids = tuple(dict.fromkeys(
            str(item).strip() for item in completed_goal_ids if str(item).strip()
        ))
        if self._multi_role_enabled and self._role_identity_confirmed:
            verifier_result = (
                "NOT_RUN" if verification is None else "PASS" if verification.ok else "FAIL"
            )
            failure_reason = (
                str(verification.reason) if verification is not None and not verification.ok
                else str(getattr(execution, "error", "") or "")
            )
            credited_ids = tuple(
                item for item in attached_ids
                if (progress_by_goal.get(item) is True or item in completed_ids)
                and execution is not None and execution.executed
                and verification is not None and verification.ok
            )
            try:
                if self.global_scheduler_state_store is not None:
                    outcome = ActionOutcome(
                        action_id=(
                            f"{getattr(getattr(self, 'capture_dir', None), 'name', '')}:{int(step_id)}"
                        ),
                        role_id=self._calendar_role_id(),
                        skill_id=str(decision.skill),
                        goal_id=str(goal_id or ""),
                        attached_goal_ids=attached_ids,
                        action_sent=bool(execution is not None and execution.executed),
                        post_action_observed=after is not None,
                        observed_change=observed_change,
                        verifier_result=verifier_result,
                        goal_progress_by_id=progress_by_goal,
                        credited_goal_ids=credited_ids,
                        completed_goal_ids=tuple(item for item in completed_ids if item in credited_ids),
                        failure_reason=failure_reason,
                    )
                    self.global_scheduler_state_store.record_action_outcome(asdict(outcome))
            except (OSError, TypeError, ValueError):
                # Outcome telemetry must never cause a physical action to repeat.
                pass
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
            operation_id=(
                f"{getattr(getattr(self, 'capture_dir', None), 'name', '')}:{int(step_id)}"
                if getattr(getattr(self, "capture_dir", None), "name", "") else ""
            ),
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
        # ...and the same step again, for the *planner's* memory of this session.
        #
        # Operator directive 2026-09-30 §6: the next UNKNOWN question must carry what this
        # session has already tried, so the model stops re-proposing a control that has changed
        # nothing.  The history is fed here, on every completed step, rather than from the
        # advised-step settlement: a memory that only held model-driven steps would report "this
        # was tried once" about a session whose rules-based skills had already tried it six times,
        # which is exactly the repetition the directive is about.  Its own try, because a
        # planner-side ledger must never cost a step that has already been issued and verified.
        self._note_step_for_planner(decision, execution, verification, observed_change)
        if self.episode_store is None:
            return
        failure = None
        if execution is None or not execution.executed:
            failure = self._failure_type_from(execution)
        elif verification is not None and not verification.ok:
            failure = verification.reason
        result = "SUCCESS" if failure is None else "FAILURE"
        # Sessions also record observations and unfinished, progressing actions.
        # An observation is not a missed click; progress is not a verifier PASS.
        #
        # ``STILL_PENDING`` belongs in this chain because leaving it out was a measured
        # defect, not an oversight in wording: it fell through to the ``"FAILURE"`` default,
        # so 44 production rows called a fishing cast that was still swimming a failed cast,
        # and ``failure`` was set to ``"NO_EXECUTION"`` -- true of an observe-only step and
        # meaningless as a verdict.  ``STILL_PENDING`` and ``AMBIGUOUS`` share ``INCOMPLETE``
        # deliberately: ``result`` answers "did this step finish", and the exact verdict now
        # travels separately in ``session_outcome``, so one column stops carrying two facts.
        if session_outcome == "PROGRESS":
            result, failure = "PROGRESS", None
        elif session_outcome in {"AMBIGUOUS", "STILL_PENDING"}:
            result, failure = "INCOMPLETE", None
        elif session_outcome == "SUCCESS" and verification is not None and verification.ok:
            result, failure = "SUCCESS", None
        episode = Episode(
            skill=decision.skill,
            state_before=state_before,
            action=asdict(execution.action) if execution is not None else {},
            state_after=state_after,
            result=result,
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
            attached_goal_ids=attached_ids,
            goal_progress_by_id=progress_by_goal,
            completed_goal_ids=completed_ids,
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
            # The verdict this fold was derived from.  Kept beside the fold rather than only
            # inside it: ``result`` is a coarse class (three values, shared with goal-driven
            # steps), and the session engine's five-way verdict is the finer fact that a
            # reader -- or a replay -- actually needs.
            session_outcome=session_outcome,
        )
        try:
            self.episode_store.append(episode)
        except (OSError, TypeError, ValueError):
            # Learning persistence must never cause an already-issued action to
            # be repeated. The run result remains authoritative for this turn.
            pass
        if self.task_completion_store is not None:
            try:
                self.task_completion_store.record_episode(episode)
            except Exception:  # noqa: BLE001 - a derived board cannot stop production
                pass
        learn_context = getattr(self, "_advised_learn_context", None) or {}
        if learn_context and execution is not None and execution.executed:
            self._learning_event("MAA_EXECUTED" if execution.backend == "MAA" else "INPUT_SENT",
                learn_context, action_backend=execution.backend, skill_id=decision.skill)
            if verification is not None:
                self._learning_event("VERIFIER_SUCCESS" if verification.ok else "VERIFIER_FAILED",
                    learn_context, verifier_reason=verification.reason,
                    verifier_evidence=dict(verification.evidence))
                if verification.ok and observed_change not in {"NONE", "UNKNOWN", ""}:
                    self._learning_event("VERIFIER_PROGRESS", learn_context,
                        observed_change=observed_change)
        self._settle_advised_step(decision, verification, result)
        # ...and the same step again, for the durable record §11/§12 ask for.  Its own call for
        # the same reason the three above have their own: a step that has already been issued and
        # judged must never be lost because a learning write failed.  Only a verifier PASS reaches
        # the ledger -- the gate is in the callee, stated once.
        self._note_learned_step(
            decision=decision,
            verification=verification,
            result=result,
            observed_change=observed_change,
            after=after,
            step_id=step_id,
        )
        # ...and one more time for the *failing* skill (directive 2026-10-01 §16): a skill that has
        # just failed several times in a row is a candidate for repair analysis.  This only *files
        # the question* -- it never calls a model and never blocks, so a repair request cannot
        # become a reason the AUTO waits.
        self._maybe_request_repair(
            decision=decision,
            verification=verification,
            result=result,
            before=before,
            frame=before_screenshot,
        )

    def _note_step_for_planner(self, decision: Any, execution: Any,
                               verification: Any, observed_change: str) -> None:
        """Hand this step's Action -> Feedback to the planner's session memory.

        The planner builds its question from evidence, and until 2026-09-30 the only evidence
        about the session was the *current* screen: ``last_action``/``last_result`` were never
        set by anything, so every question looked like a first attempt and the model had no way
        to know that its last proposal had already been tried and changed nothing.

        What is handed over is measured, not claimed.  ``observed_change`` is the difference
        between the two frames (the same fold the episode carries) and ``verifier_ok`` is the
        verifier's verdict, so the model never reads its own opinion of itself back as fact.
        ``control`` comes from the executed action's own target, which is what the model would
        have to name again to repeat it.
        """
        advisor = getattr(self, "_advisor", None)
        note = getattr(advisor, "note_step", None)
        if not callable(note):
            return
        try:
            action = getattr(execution, "action", None) if execution is not None else None
            note(
                skill=str(getattr(decision, "skill", "") or ""),
                control=str(getattr(action, "target", "") or ""),
                expected_result=str(getattr(decision, "expected_result", "") or ""),
                observed_change=str(observed_change or ""),
                verifier_ok=None if verification is None else bool(verification.ok),
            )
        except Exception:  # noqa: BLE001 - a memory must never fail a step that already ran
            pass

    def _settle_advised_step(self, decision: Any, verification: Any, result: str) -> None:
        """Tell the planner what the verifier said about the step its answer drove.

        The two halves of an advised step used to live in two files that nothing joined: the
        planner's ledger held the proposal, ``episodes.jsonl`` held the verdict.  That made the
        operator's question -- "did the local model act, and did the game agree?" -- unanswerable
        from record, and it made a model's own claim of success indistinguishable from a verified
        one.  This closes the join at the only place that knows both, and only for the step that
        actually consumed the answer (``_advised_request_id`` is set when an answer is accepted
        and cleared at the top of every step's resolution).

        Cleared unconditionally: a settlement that could not be written must not stay pending and
        attach itself to the next step.
        """
        request_id = self._advised_request_id
        if not request_id:
            return
        self._advised_request_id = ""
        advisor = getattr(self, "_advisor", None)
        note = getattr(advisor, "note_outcome", None)
        if not callable(note):
            return
        try:
            note(
                request_id,
                verifier_ok=None if verification is None else bool(verification.ok),
                skill=str(getattr(decision, "skill", "") or ""),
                result=str(result),
                evidence={} if verification is None else dict(verification.evidence),
            )
        except Exception:  # noqa: BLE001 - a ledger must never fail an already-issued action
            pass

    # --------------------------------------------------- UNKNOWN -> skill bridge
    def _maybe_request_repair(self, *, decision: Any, verification: Any, result: str,
                              before: Any, frame: Any) -> None:
        """File a SKILL_REPAIR_ANALYSIS question when a known skill keeps failing (§16).

        Three things this deliberately does *not* do, each for a stated reason:

        * **it does not call the model.**  The question is a file, exactly like the UNKNOWN channel,
          so "AUTO 永不等待 AI" survives contact with repair as well;
        * **it does not decide the repair.**  :func:`skill_repair.should_escalate` decides whether
          the failures are the kind a screenshot can explain at all -- a full march queue escalates
          nothing -- and everything downstream is a candidate patch (§17);
        * **it does not touch a skill.**  No template, no registry entry, no route: the output is a
          question, and the existing deterministic recovery paths keep owning the step.

        The run-scoped counter is bounded per skill, so a skill failing fifty times files one
        question rather than fifty.
        """
        try:
            skill = str(getattr(decision, "skill", "") or "")
            if not skill:
                return
            failures = getattr(self, "_skill_failures", None)
            if failures is None:
                failures = self._skill_failures = {}
            if str(result) not in ("FAILURE", "INCOMPLETE"):
                failures.pop(skill, None)
                return
            history = failures.setdefault(skill, [])
            history.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "verifier_ok": None if verification is None else bool(verification.ok),
                "result": str(result),
                "failure_type": str(
                    getattr(verification, "reason", "")
                    or getattr(decision, "reason", "")
                    or "NO_EXECUTION"
                ),
                "before_screenshot": str(frame or ""),
                "goal_id": str(getattr(getattr(self, "brain", None), "current_goal", "") or ""),
            })
            if len(history) > 12:
                del history[:-12]
            asked = getattr(self, "_repair_asked", None)
            if asked is None:
                asked = self._repair_asked = set()
            trigger = skill_repair.should_escalate(skill, history)
            if trigger is None or skill in asked:
                return
            asked.add(skill)
            self._write_repair_request(trigger, before=before, frame=frame)
        except Exception:  # noqa: BLE001 - a repair *question* must never fail a live step
            pass

    def _write_repair_request(self, trigger: Any, *, before: Any, frame: Any) -> None:
        """Write one repair question, unless the same one is already on file and fresh."""
        request_id = skill_repair.request_id(trigger.skill_id, trigger.page_key)
        repair_root = getattr(self, "_repair_root", None) or (
            Path(__file__).resolve().parents[1] / skill_repair.REQUEST_DIR
        )
        self._repair_root = repair_root
        path = repair_root / f"{request_id}.json"
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                created = str(existing.get("created_at") or "")
                if created:
                    moment = datetime.fromisoformat(created)
                    if moment.tzinfo is None:
                        moment = moment.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - moment).total_seconds()
                    if age < skill_repair.REPAIR_REQUEST_COOLDOWN_SECONDS:
                        return
            except (OSError, ValueError, AttributeError, TypeError):
                pass
        known = None
        try:
            known = self.registry.get(trigger.skill_id)
        except Exception:  # noqa: BLE001 - an unknown skill id is not an error worth failing on
            known = None
        page = str(getattr(before, "page", "") or "")
        request = skill_repair.RepairRequest(
            request_id=request_id,
            skill_id=trigger.skill_id,
            page_key=trigger.page_key or control_experience.label(page),
            goal_id=trigger.goal_id,
            frame_path=str(frame or ""),
            old_semantic=str(getattr(known, "semantic_goal", "") or trigger.skill_id),
            old_target_text=", ".join(
                str(item) for item in (getattr(known, "semantic_requirements", ()) or ())
            ),
            old_success_pages=tuple(
                str(item) for item in (getattr(known, "target_pages", ()) or ())
            ),
            verifier_expectation=str(getattr(known, "success_condition", "") or ""),
            failure_kinds=tuple(trigger.failure_kinds),
            consecutive_failures=int(trigger.consecutive_failures),
            failure_frames=tuple(trigger.failure_frames),
            role_id=str(getattr(self, "role_id", "") or ""),
            created_at=datetime.now(timezone.utc).isoformat(),
            question=(
                f"技能 {trigger.skill_id} 连续失败 {trigger.consecutive_failures} 次"
                f"（{', '.join(trigger.failure_kinds)}）。当前画面里，它要找的目标还在吗？"
                "是位置变了、文字变了，还是这个技能本身已经过时？"
            ),
        )
        try:
            repair_root.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(request.as_row(), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            print(
                f"[repair] filed an analysis question for {trigger.skill_id} "
                f"({trigger.consecutive_failures} failures): {request_id}",
                flush=True,
            )
        except (OSError, TypeError, ValueError):
            pass
        # ...and the same question typed through §14's packet, so the contract is exercised on the
        # live path rather than only in its own tests.
        self._note_repair_contract(request, skill_id=trigger.skill_id, before=before, frame=frame)

    def _note_repair_contract(self, request: Any, *, skill_id: str, before: Any,
                              frame: Any) -> None:
        """Type one repair question through section 14's packet and record whether it is askable.

        Not a gate and not a second flow.  The request file is written either way and
        ``skill_repair`` still owns "when is a skill escalated"; what this adds is *evidence* -- the
        contract's own validator, run against live data once per escalation, so a packet the model
        could not really be asked with (no current frame, a skill that states neither its aim nor
        its verifier's requirement) becomes a ledger row instead of a silence.

        The success evidence is the skill's *own* verified steps, read from the same ledger the
        reuse path reads: section 14's whole point is that the model must be told this worked
        before, and this project already has exactly that, keyed by screen and goal rather than by
        frame.  A handful are attached -- section 14 asks for representative successes, not the
        history.
        """
        try:
            page_key = str(getattr(request, "page_key", "") or "")
            goal_id = str(getattr(request, "goal_id", "") or "")
            maturity = ""
            try:
                known = getattr(self, "registry", None)
                entry = known.get(skill_id) if known is not None else None
                maturity = str(getattr(entry, "maturity", "") or "")
            except Exception:  # noqa: BLE001 - an unknown skill id is not an error on this path
                maturity = ""
            successes = unknown_learning.learned_steps_for(
                self._learned_ledger_rows(), page_key=page_key, goal_id=goal_id
            )[:3]
            packet = ui_venus_repair.packet_from_request(
                request,
                maturity=maturity,
                success_evidence=successes,
                elements={"frame_id": Path(str(frame)).stem, "items": []},
            )
            verdict = packet.validate()
            ui_venus_repair.RepairLedger(self._repair_ledger_path()).record_packet(
                packet, verdict=verdict, trace_id=str(getattr(request, "request_id", "") or ""))
        except Exception:  # noqa: BLE001 - a measurement must never fail an already-filed question
            pass

    def _repair_ledger_path(self) -> Path:
        """Where this mode's ledger goes.  Overridable so a test never writes into the repo."""
        explicit = getattr(self, "_repair_contract_ledger", None)
        if explicit:
            return Path(explicit)
        return Path(__file__).resolve().parents[1] / ui_venus_repair.REPAIR_LEDGER_PATH


    def _learning_event(self, stage: str, context: Mapping[str, Any], **evidence: Any) -> None:
        """Append causal evidence to the existing online ledger; never fail gameplay."""
        if not context.get("trace_id"):
            return
        try:
            from .ui_venus_online import OnlineLedger, unknown_state_identity
            store = getattr(self, "episode_store", None)
            root = Path(store.path).resolve().parents[1] if store else Path(__file__).resolve().parents[1]
            OnlineLedger(root / "learning/ui_venus_online.jsonl").append({
                "recorded_at": datetime.now(timezone.utc).isoformat(), "stage": stage,
                "trace_id": context["trace_id"], "parent_trace_id": context.get("parent_trace_id", ""),
                "call_id": context.get("call_id", ""), "role_id": context.get("role_id", ""),
                "goal_id": context.get("goal", ""), "page_key": context.get("page_key", ""),
                "frame_id": context.get("frame_id", ""), "frame_hash": context.get("frame_hash", ""),
                "episode_id": context.get("episode_id", ""), "model_used": context.get("model_used"),
                "reused_from_trace_id": context.get("reused_from_trace_id", ""),
                "unknown_identity": context.get("unknown_identity") or unknown_state_identity(goal_id=str(context.get("goal", "")),
                    page=str(context.get("page_key", "")), semantic=str(context.get("semantic", "")),
                    state_signature=str(context.get("relevant_state_signature", ""))), **evidence,
            })
        except (OSError, TypeError, ValueError):
            pass

    def _note_learned_step(self, *, decision: Any, verification: Any, result: str,
                           observed_change: str, after: Any, step_id: int = 0) -> None:
        """File the step the model drove, if the verifier passed it (§11/§12).

        The two gates are stated here rather than trusted to the caller:

        * **the verifier must have passed.**  This is §39's "模型 confidence 不是证据" applied to
          the one place it could leak back in: a step the model proposed and the game did not
          agree with teaches nothing, and an unverified step would make the compiled skill a
          record of what the model *said* rather than of what *happened*;
        * **there must be an accept context**, i.e. a model answer actually drove this step.  A
          step the rules resolved is already learned by the tiers that resolved it (the transition
          ledger, the L1 experiences) and filing it here would inflate every count in the console
          with work the model never did.

        What lands in the ledger is the semantic record; the frames ride along as evidence paths,
        and the *point* does not appear anywhere.  §10's "模型 bbox 生命周期仅当前 frame" is
        therefore satisfied by construction.
        """
        context = getattr(self, "_advised_learn_context", None) or {}
        self._advised_learn_context = {}
        if not context:
            return
        if verification is None or not verification.ok:
            # A failed advised step is still worth knowing about, and it is *not* discarded: the
            # failure patterns the offline learner groups (§23) come from the episode stream, which
            # already recorded this step.  This ledger's contract is narrower on purpose -- it is
            # the set of things V2 may henceforth do without a model.
            return
        try:
            page_after = ""
            if after is not None:
                page_after = control_experience.label(getattr(after, "page", "") or "")
            episode_id = str(getattr(getattr(self, "capture_dir", None), "name", "") or "")
            step = unknown_learning.record_verified_step(
                request_id=str(context.get("request_id")
                               or getattr(self, "_last_advice", {}).get("request_id", "") or ""),
                session_id=episode_id,
                episode_id=episode_id,
                step_index=int(step_id or 0),
                goal_id=str(context.get("goal") or ""),
                role_id=str(getattr(self, "role_id", "") or ""),
                page_before=str(context.get("page_key") or ""),
                page_after=page_after,
                no_progress=str(observed_change or "") in ("NONE", "UNKNOWN", ""),
                semantic_target=str(context.get("semantic") or ""),
                action_type="CLICK_ELEMENT",
                basis=str(context.get("basis") or ""),
                grounding_basis=str(context.get("grounding_basis") or ""),
                area="",
                visual_evidence=dict(context.get("visual_evidence") or {}),
                verifier_ok=True,
                verifier_reason=str(getattr(verification, "reason", "") or ""),
                expected_result=str(context.get("expected_result") or ""),
                actual_result=str(observed_change or ""),
                attempts_before_success=int(context.get("attempts") or 0),
                source_frames=[str(context.get("frame") or "")],
                trace_id=str(context.get("trace_id") or ""),
                parent_trace_id=str(context.get("parent_trace_id") or ""),
                frame_id=str(context.get("frame_id") or ""),
                frame_hash=str(context.get("frame_hash") or ""),
                relevant_state_signature=str(context.get("relevant_state_signature") or ""),
                verifier_evidence=dict(getattr(verification, "evidence", {}) or {}),
                model_used=context.get("model_used"),
                reused_from_trace_id=str(context.get("reused_from_trace_id") or ""),
                unknown_identity=str(context.get("unknown_identity") or ""),
                ledger=getattr(self, "learned_ledger", None) or unknown_learning.VerifiedStepLedger(
                    Path(__file__).resolve().parents[1] / unknown_learning.LEARNED_STEPS_PATH
                ),
            )
            # Invalidate the per-run cache, or the rest of this run would keep re-asking for an
            # action it has just learned.  That would be §15's defect reproduced inside a single
            # run, which is the one place it would be hardest to notice.
            self._learned_cache = None
            self._learning_event("CANDIDATE_STEP_CREATED", context)
            if context.get("model_used") is False:
                self._learning_event("SECOND_VERIFIER_SUCCESS", context,
                    verifier_evidence=dict(getattr(verification, "evidence", {}) or {}))
            print(
                f"[learned] verified step filed: {step.semantic_target or step.action_type} "
                f"on {step.page_before} -> {step.page_after or '(no page change)'} "
                f"[{step.risk_route}]",
                flush=True,
            )
            # §11/§13: the bridge is closed *here*, not left to someone remembering to run a CLI.
            # A verified step that is filed but never compiled is a step the project cannot reuse,
            # and the whole point of the ledger is that the same screen gets cheaper next time --
            # so the candidate skills are recompiled the moment the evidence changes.
            #
            # Compiling is cheap (the ledger is small; it writes one JSON per candidate) and it is
            # explicitly *not* a promotion: what lands in ``knowledge/skills/candidates/`` is a
            # CANDIDATE with ``not_yet`` saying it is neither registered nor runnable (§39), so the
            # only thing automatic here is the bookkeeping the directive already called for.
            try:
                compiled = unknown_learning.compile_candidate_skills(
                    self._learned_ledger_rows(),
                    # ``getattr`` for the same reason as everywhere else in this file: the suites
                    # build the runtime without ``__init__``, and a test must be able to point the
                    # compile at its own sandbox rather than writing candidates into the repo.
                    out_dir=Path(getattr(self, "_candidate_skill_dir", None)
                                 or (Path(__file__).resolve().parents[1]
                                     / unknown_learning.CANDIDATE_SKILL_DIR)),
                )
                if compiled:
                    print(
                        f"[learned] candidate skills recompiled ({len(compiled)} in the pool; "
                        "CANDIDATE only, nothing is registered)",
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 - a compile must never fail a finished step
                print(f"[learned] candidate compile skipped ({type(exc).__name__}: {exc})",
                      flush=True)
        except Exception:  # noqa: BLE001 - a learning write must never fail a finished step
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
        operation_id: str = "",
    ) -> None:
        """Record what the control that was aimed at actually did (operator §四/§六).

        Keyed by the **screen** and the semantic -- never by a coordinate, and no longer by the page
        class alone: ``POPUP`` names 22 different overlays, so a key of ``(page, semantic)`` handed
        one popup's coordinate to another (issue #109).  Where the page fully describes its screen
        the key is unchanged to the byte, so only the entries the page cannot name move.  The
        position is stored **with the frame it was read from and the screen it was measured on**, so
        a later reader can see that it is a measurement off one picture and cannot be reused as if
        it were a semantic fact (``00_MASTER_RULES.md`` §5).

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
        # The screen, not just the page: a coordinate learned on one overlay is not a coordinate on
        # another, and the page cannot tell them apart (issue #109).
        screen = control_experience.state_signature(before_state)
        key = control_experience.control_key(page, semantic, screen)
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
            operation_id=operation_id,
        )
        landed = execution.tap_point
        if landed is not None:
            entry.position_norm = (landed[0] / 720.0, landed[1] / 1280.0)
            # Recorded in the same breath as the position: a stored coordinate without the screen
            # it was measured on is a coordinate that will be handed to a different overlay.
            entry.screen = screen
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

    def _decision_target(self, decision: "Decision") -> str:
        """The control a decision aims at, or ``""``.

        One place, because two guards need it: the one that refuses a control this run already
        failed its verifier on, and the one that refuses to re-derive a control this run resolved
        nothing for.  A decision whose skill is not registered aims at nothing and both guards stand
        down, which is the honest answer -- there is no control to hold against it.
        """
        skill = self.registry.get(decision.skill)
        return (skill.action.target or "") if skill is not None else ""


    # ------------------------------------------------- runtime pipeline self-generation
    def _maybe_autogen_node(self, semantic: str, skill_id: str, attempts: int, reason: str) -> None:
        """Generate and wire a recognition node for a control this run could not find.

        This is the runtime half of ``winter_agent_v2.pipeline_autogen``: the derivation a
        missing control always waited on a person for. The whole thing is best-effort and
        must never change what the surrounding step does -- its only effect is that a later
        step resolving the same semantic may now find something.

        Guarded three ways, each for something that was learned the hard way:

        * once per semantic per run, because deriving twice either repeats the node or
          overwrites a good crop with a worse one;
        * only when the failure really is "nothing was located" -- a run blocked for
          another reason (dry run, device busy) has no frame worth reading and would
          produce a node from the wrong screen;
        * only when the semantic has known Chinese text, since the OCR node is built
          from what the control says, not from guesswork about its appearance.

        The node goes through ``PipelineAutoGen.wire``, which writes via ``RoutingTable``,
        so ``policy`` / ``device`` / ``not_migrated`` in that file survive -- the mistake
        that cost an afternoon when the semantic dictionary was rewritten wholesale.
        """
        if not semantic or not self._autogen_enabled:
            return
        if "SEMANTIC_TARGET_NOT_VERIFIED" not in str(reason):
            return
        if self.routing is not None and self.routing.recognition_node(skill_id, semantic) is not None:
            # There already is a node for this control, so the failure is drift rather
            # than absence. That is AutoRepair's input, not AutoGen's: bounded, once per
            # semantic per run, re-crop the node's template from the current frame and
            # wire it only when a negative frame proves the crop is page-specific --
            # the same no-negative-frame guard the harvest tool learned the hard way.
            self._maybe_repair_node(semantic, skill_id, attempts, str(reason))
            return

        text = self._semantic_cn_text(semantic)
        if not text:
            return
        if semantic in self._autogen_attempted:
            return
        # A different refusal can precede a genuine missing-control failure in
        # the same run. Spend the one-shot budget only after all eligibility
        # checks pass, regardless of the earlier refusal count.
        self._autogen_attempted.add(semantic)

        try:
            from datetime import datetime as _dt, timezone as _tz
            from winter_agent_v2.pipeline_autogen import GenerationRequest, PipelineAutoGen

            stamp = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
            frame = Path(self.capture_dir) / "autogen" / f"{stamp}_{semantic}.png"
            gen = PipelineAutoGen(device=self.adb_device,
                                  routing_path=Path(self.routing.path or DEFAULT_ROUTING_PATH))
            captured = gen.capture(frame)
            if captured is None:
                return
            node = gen.generate(GenerationRequest(semantic=semantic, cn_text=text,
                                                  skill_id=skill_id or semantic, want="auto"),
                                frame=captured)
            if node is None:
                # The text was not on the current screen. That is a fact worth keeping,
                # not an error worth raising: the control may simply be off-page.
                return
            node.evidence["trigger"] = f"runtime unresolved after {attempts + 1} attempt(s): {reason}"
            node.evidence["validation"] = "GENERATED_ONLY"
            ok, verdict = gen.wire(node, note="runtime-derived from an unresolved control")
            if ok:
                self.recently_autogen.append({"semantic": semantic, "skill_id": skill_id,
                                              "kind": node.kind, "verdict": verdict,
                                              "frame": str(captured)})
        except Exception as exc:  # noqa: BLE001 - a heuristic must not stop a production run
            # A derivation that fails must never end a real run, but "silently
            # nothing happened" is its own failure mode: the first version of this
            # hook swallowed a missing import here and every test had to guess.
            # The record below is the whole audit trail; the run continues either way.
            self.recently_autogen.append({"semantic": semantic, "skill_id": skill_id,
                                          "kind": "ERROR", "verdict": f"{type(exc).__name__}: {exc}",
                                          "frame": ""})

    def _semantic_cn_text(self, semantic: str) -> str:
        """The client's own label for a semantic, or ``""`` when nothing is declared.

        Reuses the module's declared-record loader rather than re-reading the JSON,
        so this inherits its mtime cache and, more importantly, agrees with what the
        reading layer already believes the control says. Building a node from a
        second, privately parsed copy of the dictionary is how the two drift apart.
        """
        record = _declared_record(semantic)
        # Reuse a reviewed page label when a button semantic lacks its own OCR label.
        if record is None and semantic.startswith("BTN_"):
            record = _declared_record(f"PAGE_{semantic[4:]}")
        if record is None:
            # Skill-target semantics (OPEN_INTEL, SELECT_BEAST_TARGET_MAMMOTH, ...)
            # are declared by the gap queue, not by the dictionary -- measured
            # 2026-09-26, the dictionary declared none of the 81 gap semantics and
            # that empty string is why the hook never fired. The gap queue's
            # visible_words are reviewed declarations of what the control prints,
            # so falling back to them is still "what was declared", not guessing.
            from winter_agent_v2.pipeline_autogen import declared_gap_words

            words = declared_gap_words(semantic)
            return str(words[0]) if words else ""
        _pages, words, _merged = record
        return str(words[0]) if words else ""

    def _maybe_repair_node(self, semantic: str, skill_id: str, attempts: int,
                           reason: str) -> None:
        """One bounded repair attempt for a node that exists but no longer finds.

        The chain the operator named -- MAA/verifier failure, classify, re-observe,
        adjust the crop, update the candidate, re-execute -- starts here: the run
        already classified the failure (``SEMANTIC_TARGET_NOT_VERIFIED``) and this
        runs only after a first failure of a node-owning control, once per semantic
        per run. The repaired crop must beat the old one honestly: it has to hit
        the current frame AND miss a recent frame that is not this page -- without
        that negative the harvest tool wired 联盟 in a map nav bar as a mail tab,
        so a repair without one is not a repair, it is a second way to lie.
        """
        if semantic in self._autogen_repaired:
            from winter_agent_v2.pipeline_autogen import record_repair_event
            record_repair_event(semantic, skill_id, stage="SKIP",
                                detail="ALREADY_ATTEMPTED_THIS_ROUND",
                                page=str(getattr(self, "page", "")),
                                failure_type=str(reason))
            return
        self._autogen_repaired.add(semantic)
        try:
            from datetime import datetime as _dt, timezone as _tz

            from winter_agent_v2.pipeline_autogen import (GenerationRequest,
                                                          PipelineAutoGen,
                                                          record_repair_event)

            def _log(stage: str, detail: str = "", **extra: object) -> None:
                record_repair_event(semantic, skill_id, stage=stage, detail=detail,
                                    page=str(getattr(self, "page", "")),
                                    failure_type=str(reason), extra=dict(extra))

            _log("ENTER", f"attempts={attempts + 1}")

            stamp = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
            frame = Path(self.capture_dir) / "autogen" / f"{stamp}_repair_{semantic}.png"
            gen = PipelineAutoGen(device=self.adb_device,
                                  routing_path=Path(self.routing.path or DEFAULT_ROUTING_PATH))
            captured = gen.capture(frame)
            if captured is None:
                self.recently_autogen.append({"semantic": semantic, "skill_id": skill_id,
                                              "kind": "REPAIR", "verdict": "NO_FRAME",
                                              "frame": ""})
                _log("SKIP", "NO_FRAME")
                return
            text = self._semantic_cn_text(semantic)
            if not text:
                _log("SKIP", "NO_DECLARED_TEXT")
                return
            node = gen.generate(GenerationRequest(semantic=semantic, cn_text=text,
                                                  skill_id=skill_id or semantic, want="auto"),
                                frame=captured)
            if node is None:
                self.recently_autogen.append({"semantic": semantic, "skill_id": skill_id,
                                              "kind": "REPAIR", "verdict": "TEXT_NOT_ON_FRAME",
                                              "frame": str(captured)})
                _log("SKIP", "TEXT_NOT_ON_FRAME", declared_text=text, frame=str(captured))
                return
            # Negative frames: recent autogen captures that are not this capture --
            # whatever pages the run passed through on its way here. A template that
            # also "hits" one of those describes a word common to many pages, and a
            # node built from it would fire everywhere.
            negatives = sorted(
                (p for p in (Path(self.capture_dir) / "autogen").glob("*.png")
                 if p != captured),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )[:3]
            # The same live MAA adapter the executor runs — validation without a
            # real matcher always answered NO_ADAPTER and rejected every repair
            # (measured 2026-09-26T07:50Z on BTN_EXPLORATION_IDLE_CLAIM).
            report = gen.validate(node, positives=[captured], negatives=negatives,
                                  adapter=getattr(self, "maa_adapter", None))
            node.evidence["repair"] = (f"runtime repair after {attempts + 1} attempt(s): "
                                       f"{reason}")
            node.evidence["validation_report"] = report
            ok = (report.get("positive_hits") == report.get("positives")
                  and report.get("negative_hits") == 0
                  and report.get("positives", 0) >= 1)
            if ok and negatives:
                wired, verdict = gen.wire(node, note="runtime-repaired from a failing node")
            else:
                wired, verdict = False, "REJECTED_NO_NEGATIVE_OR_MISMATCH"
            _log("WIRED" if wired else "SKIP", verdict,
                 declared_text=text, validation=report, frame=str(captured),
                 negatives=[str(p) for p in negatives])
            self.recently_autogen.append({"semantic": semantic, "skill_id": skill_id,
                                          "kind": "REPAIR",
                                          "verdict": verdict if wired else f"{verdict} (not wired)",
                                          "frame": str(captured)})
        except Exception as exc:  # noqa: BLE001 - a repair must never stop a production run
            try:
                from winter_agent_v2.pipeline_autogen import record_repair_event as _rre
                _rre(semantic, skill_id, stage="ERROR",
                     detail=f"{type(exc).__name__}: {exc}",
                     page=str(getattr(self, "page", "")), failure_type=str(reason))
            except Exception:  # noqa: BLE001
                pass
            self.recently_autogen.append({"semantic": semantic, "skill_id": skill_id,
                                          "kind": "REPAIR_ERROR",
                                          "verdict": f"{type(exc).__name__}: {exc}",
                                          "frame": ""})

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
        if self._multi_role_enabled and not self._role_identity_confirmed:
            return
        try:
            goal_utility.save(self._fairness, self._fairness_store_path)
        except Exception:  # noqa: BLE001 - a ledger write must never fail a run
            pass

    def _observe(self, frame_path: Path, *, latency: dict | None = None, phase: str = "before",
                 widen: bool = False) -> "WorldState":
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

        ``widen=True`` asks for that same second pass *deliberately*, on a fresh frame, and it is
        what LOOP_DETECTOR_V1's ``widen_observe`` rung drives.  The two callers share one code path
        on purpose: there is exactly one widened look in this runtime, and adding a second entry
        point that re-implemented it would be the second reader §二 forbids.  The flag only decides
        *when* the pass happens -- the auto case guards on an unnamed frame, the forced case is a
        caller that has already concluded the focused look is not enough.

        A vision that has no ``focus`` (a test stub, a replay vision) is observed exactly as before.
        """
        vision = self.vision
        # TASK THROUGHPUT V1 §24 ("必须能看出：时间到底浪费在哪").  ``reobserve_ms`` is one number
        # built from two observations, and this method held a third cost nobody could see: the
        # gather-formation read that only happens on MARCH frames.  Measured 2026-09-30 on pin
        # 553d8df, a MARCH->UNKNOWN step recorded ``reobserve_ms`` 10375 ms while the same two
        # frames replayed offline at 93 ms + 2270 ms, so the archive alone could not attribute it.
        # Account per phase and per component instead of guessing.
        accounting = latency if isinstance(latency, dict) else None

        def account(component: str, ms: float) -> None:
            if accounting is None:
                return
            key = f"observe_{phase}_{component}_ms"
            accounting[key] = (accounting.get(key) or 0.0) + ms

        def count_call() -> None:
            if accounting is None:
                return
            key = f"observe_{phase}_calls"
            accounting[key] = int(accounting.get(key) or 0) + 1

        focus = getattr(vision, "focus", None)
        if focus is None:
            count_call()
            started = time.monotonic()
            state = vision.observe(frame_path)
            account("vision", (time.monotonic() - started) * 1000)
            self._record_live_event_reservation(state)
            started = time.monotonic()
            state = self._annotate_gather_formation(state, frame_path)
            account("formation", (time.monotonic() - started) * 1000)
            return self._read_due_calendar_entry(state, frame_path)
        goal = str(getattr(getattr(self, "brain", None), "current_goal", "") or "")
        page_hint = str(getattr(self, "_last_known_label", "") or "")

        def look(*, widen: bool, reason: str):
            focus(goal=goal, page_hint=page_hint, reason=reason, widen=widen)
            return vision.observe(frame_path)

        count_call()
        started = time.monotonic()
        state = look(widen=False, reason=f"goal {goal or '(none)'} from {page_hint or '(nowhere)'}")
        account("vision", (time.monotonic() - started) * 1000)
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
            count_call()
            started = time.monotonic()
            state = look(widen=True, reason="widening after an unnamed frame")
            account("vision", (time.monotonic() - started) * 1000)
            if accounting is not None:
                widened_key = f"observe_{phase}_widened"
                accounting[widened_key] = int(accounting.get(widened_key) or 0) + 1
        elif widen:
            # LOOP_DETECTOR_V1 asked for the widened look on purpose: the caller has already
            # decided this frame needs it, so the auto case's "stayed unnamed" guard does not
            # apply and would make the rung a no-op on exactly the frames it exists for.
            # Audible for the same reason as the auto case -- a rung whose only visible symptom
            # is a failing recovery is a rung nobody can confirm is running.
            print(
                f"[attention] {page_hint or '(no page)'} + goal {goal or '(none)'}: widened look "
                f"requested by the loop detector",
                flush=True,
            )
            count_call()
            started = time.monotonic()
            state = look(widen=True, reason="widening on a loop-detector request")
            account("vision", (time.monotonic() - started) * 1000)
            if accounting is not None:
                widened_key = f"observe_{phase}_widened"
                accounting[widened_key] = int(accounting.get(widened_key) or 0) + 1
        self._record_live_event_reservation(state)
        started = time.monotonic()
        state = self._annotate_gather_formation(state, frame_path)
        account("formation", (time.monotonic() - started) * 1000)
        return self._read_due_calendar_entry(state, frame_path)

    def _annotate_gather_formation(self, world: WorldState, frame_path: Path) -> WorldState:
        """Attach current-frame hero identities with role-scoped availability."""
        if world.page is Page.POPUP and world.popup == "HERO_PICKER":
            if str(getattr(getattr(self, "brain", None), "current_goal", "") or "") == "GATHER_RESOURCE":
                return self._annotate_gather_picker(world, frame_path)
            return world
        if world.page is not Page.MARCH:
            return world
        try:
            from PIL import Image
            from .formation import read_formation_hero_identities

            with Image.open(frame_path) as opened:
                observation = read_formation_hero_identities(opened.convert("RGB"))
        except Exception as exc:  # optional portrait recognition must not break general observation
            return replace(world, hero_troop={
                **dict(world.hero_troop or {}),
                "gather_formation": {
                    "status": "UNAVAILABLE",
                    "reason": f"PORTRAIT_READER_ERROR:{type(exc).__name__}",
                    "source_frame": str(frame_path),
                    "observed_at": str(world.timestamp or datetime.now(timezone.utc).isoformat()),
                },
            })
        role_scope = str(getattr(self, "role_scope", "") or "").upper()
        live_scope = role_scope in {"LIVE_OBSERVED", "FRESH_RUNTIME"}
        record = {
            **observation,
            "role_id": str(getattr(self, "role_id", "") or "") if live_scope else None,
            "role_scope": role_scope or "UNKNOWN",
            "observed_at": str(world.timestamp or datetime.now(timezone.utc).isoformat()),
            "source_frame": str(frame_path),
            "resource_type": str(
                world.resource_target or getattr(self, "_active_gather_resource", "") or ""
            ).upper() or None,
            "specialist_availability": "UNKNOWN",
        }
        return replace(world, hero_troop={**dict(world.hero_troop or {}), "gather_formation": record})

    def _annotate_gather_picker(self, world: WorldState, frame_path: Path) -> WorldState:
        """Match only the exact resource specialist on the current role's picker frame."""
        from PIL import Image
        from .hero_portraits import gather_hero_for_resource, match_picker_hero, picker_card_selected

        role_scope = str(getattr(self, "role_scope", "") or "").upper()
        live_scope = role_scope in {"LIVE_OBSERVED", "FRESH_RUNTIME"}
        resource = str(world.resource_target or getattr(self, "_active_gather_resource", "") or "").upper()
        target = gather_hero_for_resource(resource)
        try:
            with Image.open(frame_path) as opened:
                image = opened.convert("RGB")
            match = match_picker_hero(
                image,
                target or "",
                picker_page_verified=world.page is Page.POPUP and world.popup == "HERO_PICKER",
            ) if target else {"status": "UNKNOWN_RESOURCE", "hero_id": None}
            selected = bool(match.get("status") == "MATCHED" and picker_card_selected(image, match))
        except Exception as exc:
            match = {"status": "READER_ERROR", "error": type(exc).__name__, "hero_id": target}
            selected = False
        picker = {
            "open": True,
            "resource_type": resource or None,
            "hero_id": target,
            "match_status": str(match.get("status") or "UNKNOWN"),
            "specialist_availability": "SELECTABILITY_UNVERIFIED" if match.get("status") == "MATCHED" else "UNKNOWN",
            "selected": selected,
            "match": dict(match),
            "source_frame": str(frame_path),
            "observed_at": str(world.timestamp or datetime.now(timezone.utc).isoformat()),
            "role_id": str(getattr(self, "role_id", "") or "") if live_scope else None,
            "role_scope": role_scope or "UNKNOWN",
        }
        return replace(world, resource_target=resource or world.resource_target,
                       hero_troop={**dict(world.hero_troop or {}), "hero_picker": picker})

    def _record_live_event_reservation(self, world: WorldState) -> None:
        """Persist or clear role-scoped event reservations from current client evidence."""
        role_id = self._calendar_role_id()
        if not role_id:
            return
        events = world.events if isinstance(world.events, Mapping) else {}
        def event_seconds(value: object) -> int | None:
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        observations: list[tuple[str, int | None, str, str, str | None]] = []
        bear = events.get("bear")
        if isinstance(bear, Mapping):
            bear_status = str(bear.get("status") or "").upper()
            bear_seconds = event_seconds(bear.get("seconds_to_start"))
            if bear_seconds is not None and bear_seconds > 0:
                window_state = event_schedule.LiveWindowState.SCHEDULED_NOT_OPEN.value
            elif bear_status == "ACTIVE" or bear_seconds == 0:
                window_state = event_schedule.LiveWindowState.OPEN.value
            elif bear_status in {"FINISHED", "COOLDOWN"}:
                window_state = event_schedule.LiveWindowState.EXPIRED.value
            else:
                window_state = event_schedule.LiveWindowState.UNKNOWN.value
            observations.append((
                "BEAR_HUNT", bear_seconds, window_state,
                str(bear.get("role") or "AUTO"),
                str(bear.get("alliance")) if bear.get("alliance") else None,
            ))
        minimum = events.get("minimum_guarantee")
        if isinstance(minimum, Mapping):
            raw_event_id = str(minimum.get("event_id") or "")
            if raw_event_id:
                from .event_goal import known_activities

                activity = next((
                    item for item in known_activities()
                    if raw_event_id == item.event_id or raw_event_id in item.aliases
                ), None)
                if activity is not None:
                    seconds = event_seconds(minimum.get("seconds_to_start"))
                    remaining = event_seconds(minimum.get("remaining_seconds"))
                    if seconds is not None and seconds > 0:
                        window_state = event_schedule.LiveWindowState.SCHEDULED_NOT_OPEN.value
                    elif seconds == 0 or (remaining is not None and remaining > 0):
                        window_state = event_schedule.LiveWindowState.OPEN.value
                    elif remaining is not None and remaining <= 0:
                        window_state = event_schedule.LiveWindowState.EXPIRED.value
                    else:
                        window_state = event_schedule.LiveWindowState.UNKNOWN.value
                    observations.append((
                        activity.event_id, seconds, window_state, "AUTO", None,
                    ))
        if not observations:
            return
        try:
            observed = datetime.fromisoformat(str(world.timestamp))
        except (TypeError, ValueError):
            observed = datetime.now(timezone.utc)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        try:
            schedules = event_schedule.load()
            for event_id, seconds, window_state, role, alliance in observations:
                if seconds is not None and seconds > 0:
                    event_schedule.record_live_countdown(
                        schedules,
                        role_id=role_id,
                        event_id=event_id,
                        seconds_to_start=seconds,
                        source="LIVE_CLIENT_EXPLICIT_START_COUNTDOWN",
                        role=role,
                        alliance=alliance,
                        now=observed,
                    )
                event_schedule.record_live_window_observation(
                    schedules, role_id=role_id, event_id=event_id,
                    state=window_state, source="LIVE_CLIENT_EVENT_WINDOW_OBSERVATION",
                    role=role, alliance=alliance, now=observed,
                )
            event_schedule.save(schedules)
        except Exception:  # noqa: BLE001 -- event-clock persistence must never block AUTO
            return

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
        rally_target: str | None = None,
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
        if semantic == "QUICK_PANEL_SCROLL_CURRENT":
            # A semantic swipe needs four current-frame endpoints, not a string
            # of historical coordinates. Reread the visible panel before using
            # the gesture its row/container reader measured from this screenshot.
            if frame.page is not Page.HOME or frame_path is None or (frame.quick_panel or {}).get("open") is not True:
                return None
            ocr = self._ocr_service()
            if ocr is None:
                return None
            from .ocr import read_quick_panel
            try:
                panel = read_quick_panel(Path(frame_path), ocr)
                point = panel.get("scroll_swipe_norm") if panel.get("open") is True else None
                if not isinstance(point, (tuple, list)) or len(point) != 4:
                    return None
                gesture = tuple(float(value) for value in point)
            except (OSError, TypeError, ValueError):
                return None
            return gesture if all(0.0 <= value <= 1.0 for value in gesture) and gesture[1] > gesture[3] else None
        if semantic in {"BTN_FREE_RECRUIT_ADVANCED", "BTN_FREE_RECRUIT_EPIC"}:
            # The HOME quick panel repeats these labels. Only the current hero
            # recruit cards' own explicit free counts and Free control authorize
            # a target; a cached card/template never supplies this spending tap.
            if frame.page is not Page.HERO or frame_path is None:
                return None
            ocr = self._ocr_service()
            if ocr is None:
                return None
            from .ocr import OCRPageClassifier
            try:
                fresh = OCRPageClassifier().classify(
                    ocr.recognize(Path(frame_path)), frame_size=read_frame_size(Path(frame_path))
                )
                if fresh.page is not Page.HERO:
                    return None
                key = "HERO_RECRUIT_" + semantic.removeprefix("BTN_FREE_RECRUIT_")
                rows = [row for row in (fresh.rewards or {}).get("hero_recruit_rows", ())
                        if isinstance(row, Mapping) and row.get("key") == key]
                if len(rows) != 1:
                    return None
                row = rows[0]
                if (row.get("free_available") is not True or int(row.get("free_remaining") or 0) <= 0
                        or row.get("source") != "LIVE_CLIENT_OCR"
                        or "今日免费招募剩余" not in str(row.get("free_source_word") or "")):
                    return None
                point = row.get("free_button_norm")
                if not isinstance(point, (tuple, list)) or len(point) != 2:
                    return None
                target = tuple(float(value) for value in point)
            except (OSError, TypeError, ValueError):
                return None
            return target if all(0.0 <= value <= 1.0 for value in target) else None
        if semantic == "EVENT_CALENDAR_NEXT_DETAIL":
            # The store supplies only inspected-state attribution. Positions and
            # occurrence identity are reread from the current visible calendar;
            # stale taps from a prior scan never enter this resolver.
            events = frame.events or {}
            calendar = events.get("calendar") or {}
            detail = events.get("calendar_detail") or {}
            if (frame.page is not Page.EVENT or frame_path is None
                    or not isinstance(calendar, Mapping) or calendar.get("recognized") is not True
                    or (isinstance(detail, Mapping) and detail.get("recognized") is True)):
                return None
            role_id = self._calendar_role_id()
            ocr = self._ocr_service()
            if not role_id or ocr is None:
                return None
            from .event_calendar import read_event_calendar
            try:
                current = read_event_calendar(
                    ocr.recognize(Path(frame_path)).tokens,
                    frame_size=read_frame_size(Path(frame_path)), frame_path=Path(frame_path),
                )
                if current.get("recognized") is not True or current.get("details_visible") is True:
                    return None
                row = event_schedule.calendar_next_entry(role_id, current.get("entries") or ())
                if (not isinstance(row, Mapping) or not row.get("occurrence_key")
                        or not row.get("event_id") or not row.get("title_box")):
                    return None
                point = row.get("tap_norm")
                if not isinstance(point, (tuple, list)) or len(point) != 2:
                    return None
                target = tuple(float(value) for value in point)
            except (OSError, TypeError, ValueError):
                return None
            return target if all(0.0 <= value <= 1.0 for value in target) else None
        if semantic == "EVENT_CALENDAR_TAB":
            # Its template art also appears on HOME. The tab exists only inside
            # the recognized regular-event detail or calendar page.
            events = frame.events or {}
            if (frame.page is not Page.EVENT or not any(
                    isinstance(events.get(key), Mapping) and events[key].get("recognized") is True
                    for key in ("calendar", "calendar_detail"))):
                return None
        if semantic == "RALLY_ROW_JOIN_BUTTON":
            if frame.page is not Page.ALLIANCE:
                return None
            target = getattr(rally_target, "value", rally_target) or "BEAR"
            alliance = frame.alliance if isinstance(frame.alliance, Mapping) else {}
            if alliance.get("section") == "RALLY_LIST" or alliance.get("rally_list_visible") is True:
                return live_rally_join_point(frame, target)
            # Preserve the old, current-frame Bear detail-panel fallback. It is not
            # target-generic, so an explicit Polar/unknown Goal must never use it.
            if str(target).strip().upper() != "BEAR" or frame_path is None:
                return None
            match = self._semantic.find(Path(frame_path), "BTN_JOIN_ROW")
            return match.center_norm if match is not None else None
        if semantic == "BTN_DAILY_TASK_GO":
            # The task row and its adjacent 前往 control are read from this exact
            # screenshot. A cached row, unpositioned OCR result, or different task
            # is never allowed to supply the tap target.
            if frame.page is not Page.DAILY or frame_path is None:
                return None
            target_task_id = str(getattr(getattr(self, "brain", None), "daily_task_id", "") or "")
            if not target_task_id:
                return None
            try:
                current_frame = Path(frame_path).resolve()
            except (OSError, TypeError, ValueError):
                return None
            row = next((
                item for item in (frame.daily or {}).get("tasks", ())
                if isinstance(item, Mapping)
                and item.get("task_id") == target_task_id
                and str(item.get("state") or "").upper() == "AVAILABLE"
                and item.get("source_frame")
                and Path(str(item.get("source_frame"))).resolve() == current_frame
                and isinstance(item.get("action_button"), Mapping)
                and item["action_button"].get("semantic_id") == semantic
                and item["action_button"].get("basis") == "CURRENT_FRAME_OCR_BOX_AND_ADJACENT_TASK_ROW"
            ), None)
            if row is None:
                return None
            box = row["action_button"].get("bbox_norm")
            if not isinstance(box, (tuple, list)) or len(box) != 4:
                return None
            try:
                x, y, width, height = (float(value) for value in box)
            except (TypeError, ValueError):
                return None
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1 or y + height > 1:
                return None
            return (x + width / 2.0, y + height / 2.0)
        if semantic == "BTN_ALLIANCE_TECH_RECOMMENDED_NODE":
            # This tap only opens the currently recommended unfinished Alliance
            # Technology node. Resolve its box from the exact live screenshot and
            # require the page classifier to have seen the same actionable node.
            # The contribution button in the detail dialog remains a separate step.
            if (frame.page is not Page.ALLIANCE
                    or frame.alliance.get("section") != "TECHNOLOGY"
                    or frame.alliance.get("recommended_tech_visible") is not True
                    or frame.alliance.get("status") != "UNKNOWN"
                    or frame_path is None):
                return None
            hit = self._semantic.find(Path(frame_path), semantic)
            if hit is None or hit.distance > 8:
                return None
            point = hit.center_norm
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            return (x_norm, y_norm) if 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0 else None
        if semantic == "BTN_ALLIANCE_TECH_DETAILS_CLOSE":
            if (frame.page is not Page.ALLIANCE
                    or frame.alliance.get("section") != "TECHNOLOGY"
                    or frame.alliance.get("donation_detail_open") is not True
                    or frame_path is None):
                return None
            hit = self._semantic.find(Path(frame_path), semantic)
            if hit is None or hit.distance > 8:
                return None
            point = hit.center_norm
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            return (x_norm, y_norm) if 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0 else None
        if semantic.startswith("QUICK_PANEL_ROW_") and semantic.endswith("_DONE"):
            # This green marker was tapped on the live client and closed the panel
            # without collecting the batch. It is a state indicator, not a control.
            # Keep the candidate in the evidence catalog, but never let an L1 or Qwen
            # action turn that disproved target back into a production tap.
            return None
        if semantic == "BTN_LAB_RESEARCH":
            # The selected 科研所's radial-menu 研究 control: the one hop from the
            # lab bar to the tech tree.  Navigation only (the tree itself spends
            # nothing); resolved exclusively from the current frame's OCR read of
            # that control -- never a stored coordinate, because the menu position
            # depends on where the lab sits in the city.
            research = frame.research or {}
            if frame.page is not Page.HOME or research.get("menu_open") is not True:
                return None
            point = research.get("research_action_tap_norm")
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            return (x_norm, y_norm) if 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0 else None
        if semantic == "OPEN_GATHER_HERO_PICKER":
            if frame.page is not Page.MARCH or frame_path is None:
                return None
            observation = (frame.hero_troop or {}).get("gather_formation")
            if not isinstance(observation, Mapping) or observation.get("source_frame") != str(frame_path):
                return None
            if observation.get("role_scope") not in {"LIVE_OBSERVED", "FRESH_RUNTIME"}:
                return None
            slots = [item for item in (observation.get("slots") or ()) if isinstance(item, Mapping)]
            if len(slots) != 3 or any(item.get("state") != "EMPTY" for item in slots):
                return None
            from PIL import Image
            from .hero_portraits import formation_slot_boxes
            try:
                with Image.open(frame_path) as opened:
                    width, height = opened.size
            except OSError:
                return None
            if width <= 0 or height <= 0:
                return None
            box = formation_slot_boxes((width, height))[0]
            return ((box[0] + box[2] / 2) / width, (box[1] + box[3] / 2) / height)
        if semantic == "PICK_EXACT_GATHER_HERO":
            if frame.page is not Page.POPUP or frame.popup != "HERO_PICKER" or frame_path is None:
                return None
            picker = (frame.hero_troop or {}).get("hero_picker")
            if not isinstance(picker, Mapping) or picker.get("source_frame") != str(frame_path):
                return None
            if picker.get("role_scope") not in {"LIVE_OBSERVED", "FRESH_RUNTIME"}:
                return None
            from PIL import Image
            from .hero_portraits import gather_hero_for_resource, match_picker_hero
            target = gather_hero_for_resource(str(resource or frame.resource_target or ""))
            if not target or picker.get("hero_id") != target:
                return None
            try:
                with Image.open(frame_path) as opened:
                    result = match_picker_hero(opened.convert("RGB"), target, picker_page_verified=True)
            except OSError:
                return None
            if result.get("status") != "MATCHED":
                return None
            point = result.get("tap_norm")
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            return (x_norm, y_norm) if 0 <= x_norm <= 1 and 0 <= y_norm <= 1 else None
        if semantic == "ASSIGN_EXACT_GATHER_HERO":
            if frame.page is not Page.POPUP or frame.popup != "HERO_PICKER" or frame_path is None:
                return None
            picker = (frame.hero_troop or {}).get("hero_picker")
            if not isinstance(picker, Mapping) or picker.get("source_frame") != str(frame_path):
                return None
            if picker.get("role_scope") not in {"LIVE_OBSERVED", "FRESH_RUNTIME"}:
                return None
            from PIL import Image
            from .hero_portraits import gather_hero_for_resource, match_picker_hero, picker_card_selected
            target = gather_hero_for_resource(str(resource or frame.resource_target or ""))
            if not target or picker.get("hero_id") != target:
                return None
            try:
                with Image.open(frame_path) as opened:
                    image = opened.convert("RGB")
                    result = match_picker_hero(image, target, picker_page_verified=True)
            except OSError:
                return None
            if result.get("status") != "MATCHED" or not picker_card_selected(image, result):
                return None
            ocr_service = self._ocr_service()
            hit = find_printed_words(
                frame_path,
                ("派遣",),
                ocr_service,
                band={"x_norm": 0.45, "y_norm": 0.72, "w_norm": 0.48, "h_norm": 0.15},
            ) if ocr_service is not None else None
            point = hit.get("center_norm") if isinstance(hit, Mapping) else None
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            return (x_norm, y_norm) if 0 <= x_norm <= 1 and 0 <= y_norm <= 1 else None
        if semantic == "REMOVE_GATHER_HERO":
            if frame.page is not Page.MARCH or frame_path is None:
                return None
            observation = (frame.hero_troop or {}).get("gather_formation")
            if not isinstance(observation, Mapping) or observation.get("source_frame") != str(frame_path):
                return None
            if observation.get("role_scope") not in {"LIVE_OBSERVED", "FRESH_RUNTIME"}:
                return None
            from .hero_portraits import evaluate_gather_formation
            from .hero_badge import remove_button_point
            from PIL import Image
            target_resource = resource or frame.resource_target or observation.get("resource_type")
            decision = evaluate_gather_formation(str(target_resource or ""), observation)
            slots = decision.get("remove_slots") or []
            if decision.get("status") != "CLEANUP_REQUIRED" or not slots:
                return None
            try:
                with Image.open(frame_path) as opened:
                    point = remove_button_point(opened.convert("RGB"), int(slots[0]))
                    width, height = opened.size
            except (OSError, TypeError, ValueError):
                return None
            if not point or width <= 0 or height <= 0:
                return None
            return (point[0] / width, point[1] / height)
        if semantic == "RESOURCE_DYNAMIC":
            # The strip scrolls, so the tap target is derived from the
            # bracket anchor observed on the current frame (see
            # SemanticROIVision.resource_cell_center_norm).  The previous
            # hand-typed centres were only valid for one scroll offset and
            # selected the wrong tab on live frames.  ``None`` means the
            # cell is off-screen: the loop scrolls the strip instead of
            # guessing a coordinate.
            return self._semantic.resource_cell_center_norm(resource)
        if semantic == "RESEARCH_NODE_NEXT":
            # Inspect one unfinished technology node at the location OCR read from
            # this exact research frame.  The guard makes the operation navigation
            # only: a named, progressed node is required;
            # this semantic never resolves the resource-spending 研究 control.
            if frame.page is not Page.RESEARCH:
                return None
            candidate = next((
                node for node in (frame.research.get("node_candidates") or ())
                if isinstance(node, Mapping)
                and node.get("status") == "UNFINISHED"
                and int(node.get("level") or 0) > 0
                and int(node.get("level_max") or 0) > int(node.get("level") or 0)
                and isinstance(node.get("tap_norm"), (tuple, list))
                and len(node.get("tap_norm")) == 2
            ), None)
            if candidate is None:
                return None
            try:
                point = (float(candidate["tap_norm"][0]), float(candidate["tap_norm"][1]))
            except (TypeError, ValueError):
                return None
            return point if all(0.0 <= coordinate <= 1.0 for coordinate in point) else None
        if semantic == "BTN_START_RESEARCH":
            # This is a resource-spending action. Resolve it only from the current
            # research detail frame after OCR proved the selected node, idle queue,
            # readable affordable costs, and the duration printed on the start
            # control. Never fall back to a stored/template coordinate here.
            research = frame.research or {}
            if (
                frame.page is not Page.RESEARCH
                or research.get("queue_available") is not True
                or research.get("node_detail_visible") is not True
                or not research.get("node")
                or research.get("researchable") is not True
                or research.get("costs_readable") is not True
                or research.get("costs_affordable") is not True
                or research.get("start_control_present") is not True
            ):
                return None
            point = research.get("research_control_norm")
            if not (isinstance(point, (tuple, list)) and len(point) == 2):
                return None
            try:
                x_norm, y_norm = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                return None
            return (x_norm, y_norm) if 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0 else None
        if semantic in {"BTN_POWER_TROOP_IMPROVE", "BTN_POWER_RESEARCH_IMPROVE"}:
            # Category rows move as an account unlocks more systems. Resolve only the
            # current screenshot's row label + adjacent 提升 control; never fall back
            # to a candidate crop from a different progression stage.
            if (frame.page is not Page.POPUP or frame.popup != "POWER_DETAILS"
                    or frame_path is None):
                return None
            category = (
                "部队实力" if semantic == "BTN_POWER_TROOP_IMPROVE" else "科技实力"
            )
            ocr = self._ocr_service()
            if ocr is None:
                return None
            try:
                reading = ocr.recognize(frame_path)
                located = read_power_details_action_tokens(
                    reading.tokens, read_frame_size(frame_path)
                )
            except Exception:
                return None
            point = (located.get("actions") or {}).get(category)
            if not located.get("recognized") or not point:
                return None
            return point
        if semantic == 'GIANT_BEAST_SEARCH_TAB':
            return frame.resource_giant_beast_tab_norm if frame.page is Page.MAP and frame.resource_search_open else None
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
        if semantic == "TRAINING_CAMP_BODY_FROM_FOCUS":
            # The quick-panel DONE tile first focuses a barracks. Resolve the next tap
            # from this exact screenshot's halo; never reuse the older ring centre or a
            # cached screen point. The OCR reader must have positively classified the
            # intermediate panel-focus state on HOME.
            training = frame.training or {}
            if (
                frame.page is not Page.HOME
                or frame_path is None
                or training.get("navigation") != "PANEL_CAMP_FOCUSED"
            ):
                return None
            if training.get("camp_focus_source") == "REOBSERVED_STATIC_CITY_VIEW":
                # The bounded retry already registered this exact new frame
                # against the original city view. It is an ephemeral reading,
                # not a persistent locator or a point from a different capture.
                if (str(training.get("camp_focus_current_frame") or "") != str(frame_path)
                        or training.get("camp_focus_retry_attempt") != 1):
                    return None
                point = training.get("camp_focus_tap_norm")
                if (isinstance(point, (tuple, list)) and len(point) == 2
                        and all(isinstance(v, (float, int)) and 0 <= v <= 1 for v in point)):
                    return tuple(point)
                return None
            if training.get("camp_focus_source") != "CURRENT_FRAME_SELECTION_HALO":
                return None
            from .camp_ring import focused_camp_body_tap_norm

            return focused_camp_body_tap_norm(Path(frame_path))
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
        # ------------------------------------------------------------------
        # REMOVED 2026-09-24: a literal (0.86, 0.68) for BTN_EXPLORATION_IDLE_CLAIM.
        #
        # It returned a *written-down* point gated only by "this frame says the chest
        # is CLAIMABLE".  That is a fixed screen percentage deciding a click target,
        # which the constitutional amendment forbids outright and -- explicitly --
        # does not allow as a fallback when the template misses:
        #
        #   §一.2  固定屏幕百分比点击
        #   §一.5  模板、OCR 或语义识别失败后，回退到历史坐标
        #   §二   本约束不设置生产点击例外
        #
        # It was not theoretical.  Measured over the real executor ledger
        # (``learning/executor_backend.jsonl``), BTN_EXPLORATION_IDLE_CLAIM tapped
        # **10/10 times at exactly (0.86, 0.68)** -- every single tap this target ever
        # made came from the constant, never from the frame.
        #
        # Why it existed: the chest is animated, so its perceptual hash varies between
        # frames and no template can match it.  That is a true statement about the
        # template tier; it is not a licence to write down a coordinate.  The
        # constitutional answer is the same for every control that cannot be located:
        # ``None``, and the step ends honestly instead of tapping an invented point
        # (§五: 模板未命中、目标身份不明确或页面状态不符合预期时，不生成点击动作).
        #
        # The claim is not lost.  The verified dialog route is untouched: the idle
        # dialog declares its own controls (``BTN_EXPLORATION_IDLE_CONFIRM``,
        # ``POPUP_EXPLORATION_REWARD``), both located from the frame.  What is missing
        # is a *current-frame* locator for the chest itself (a detector over the frame,
        # which §五 explicitly permits as a recognition method) -- registered as a
        # capability gap rather than papered over with a constant.
        # ------------------------------------------------------------------
        if semantic == "BTN_EXPLORATION_IDLE_CLAIM":
            return None
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
            panel = getattr(frame, "quick_panel", None) or {}
            row_key = semantic[len("QUICK_PANEL_ROW_"):]
            if row_key.endswith("_DONE"):
                row_key = row_key[:-len("_DONE")]
            if row_key in {"SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP"}:
                if any(
                    str(row.get("key")) == row_key
                    and str(row.get("control") or "") == "DONE"
                    for row in panel.get("rows") or ()
                ) and not semantic.endswith("_DONE"):
                    # A production tap on the OCR label closed the panel without opening the
                    # camp task page. Do not let the printed-word fallback turn that failed
                    # candidate into another executable target.
                    return None
            row_point = self._dictionary_hint(semantic, frame, frame_path, frame_derived_only=True)
            if row_point is not None:
                return row_point
        verdict, printed = self._client_printed_control(semantic, frame, frame_path)
        if verdict == "FOUND":
            return printed
        if verdict == "ABSENT":
            return None
        # ------------------------------------------------------------------
        # REMOVED 2026-09-24: the remembered-coordinate tier
        # (``self._remembered_control_center(semantic, frame)``).
        #
        # It handed the executor a point measured on an *earlier* frame, gated by
        # page/screen agreement, ``resolved``, not-``sterile`` and a cooldown.  Those
        # guards were good ones and they are why this tier is removed *last* rather
        # than first -- but no arrangement of guards makes a stored coordinate a
        # reading of the current frame.  The amendment names this exact pattern:
        #
        #   §一.3  复用历史截图或历史操作中的点击坐标
        #   §一.5  模板、OCR 或语义识别失败后，回退到历史坐标
        #   §一.6  根据某类页面的历史坐标记忆，直接生成当前页面的点击位置
        #   §六   现有坐标台账如仍承担生产点击定位，应停止其直接输出点击目标的能力
        #
        # Measured over the real runtime logs before removal: the tier printed
        # ``[experience] ... reusing a measured position`` **21 times** -- 21 production
        # taps whose target was a coordinate, not a control.  It refused 8 more
        # (``refused: the stored point``), which is the tier's own record that it was
        # already reaching for a screen it did not belong to.
        #
        # NOT deleted, deliberately: ``_remembered_control_center`` and the ledger stay,
        # because §六 keeps positions for *audit and failure reproduction*
        # ("历史 Episode 可以保存实际点击位置用于审计和故障复现").  What stops is the
        # only thing the amendment forbids -- its output reaching a tap.  The method is
        # now called by nothing in the tap chain; it answers questions, not clicks.
        #
        # Consequence, stated rather than hidden: a control that has a template but is
        # missed on this frame no longer gets a second chance from the ledger.  It must
        # be located on the frame (template, printed word, or a detector) or not tapped
        # -- §二: 即使按钮外观、页面类型或任务完全相同，也不得跳过当前 UI 识别.
        # ------------------------------------------------------------------
        # The weakest layer: the semantic dictionary's DECLARED point.
        #
        # Only the frame-derived branches may answer.  The else-branch of
        # ``_dictionary_hint`` parses ``position_hint.x`` / ``.y`` -- a constant typed
        # into a JSON file -- and a constant in a config file is still a constant
        # (§一.2, and §八: 将坐标移入配置文件同样属于违规).  ``_dictionary_hint`` is
        # therefore asked only for the two branches that read the frame in hand
        # (``QUICK_PANEL_ROW_*`` from ``row.arrow_norm``/``done_norm``, and
        # ``QUICK_PANEL_HANDLE`` from ``handle.point_norm``); it refuses everything else
        # itself.  See its docstring for the guard.
        hinted = self._dictionary_hint(semantic, frame, frame_path, frame_derived_only=True)
        if hinted is not None:
            return hinted
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

    #: How many times one run may ask for the same control and be handed no point before the attempt
    #: is held against *that control* instead of being re-derived for the next goal.
    #:
    #: Two, and the second is not decoration: each attempt resolves against a freshly captured frame,
    #: and the reader this project trusts most -- the client's own printed word -- is only ~94%
    #: readable per frame (measured over 245 加成总览 frames: 231 read the 实力详情 label, 14 did not),
    #: so a second attempt is a real second chance rather than a repeat.
    #:
    #: A **class** constant rather than a per-run assignment, and that is on purpose: it is
    #: instrumentation as much as policy.  An attribute set inside ``run`` shadows anything a test or
    #: an A/B sets beforehand -- measured the hard way on 2026-09-23, when a plugin that lifted this
    #: bound to compare both behaviours in one tree silently changed nothing and the two legs came
    #: back identical for a reason that had nothing to do with the change under test.
    MAX_UNRESOLVED_ATTEMPTS = 2

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
        self, semantic: str, frame: "WorldState", frame_path: "Path | None",
        *, frame_derived_only: bool = True,
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

        ``frame_derived_only`` (default ``True``, added 2026-09-24)
        ----------------------------------------------------------
        The third branch below parses ``position_hint.x`` / ``position_hint.y`` -- literals typed
        into ``semantic_dictionary.json``.  That is a constant, and a constant in a config file is
        still a constant: the constitutional amendment forbids it by name and refuses to let it be
        a fallback (``§一.2`` 固定屏幕百分比点击, ``§八`` 将坐标移入配置文件同样属于违规,
        ``§二`` 本约束不设置生产点击例外).

        So with the default the declared branch is **refused**, and only the two branches that read
        the frame in hand may answer.  Measured before the change: only two semantics ever carried a
        numeric ``x``/``y`` (``QUICK_PANEL_TAB_CITY``, ``QUICK_PANEL_TAB_WILDERNESS``, both
        ``MEASURED_ON_ONE_FRAME`` ranges), and the runtime log shows this tier located a control
        exactly **once** in the project's history.  Both tabs are still reachable the constitutional
        way -- by reading the strip on the current frame -- which is the capability gap this refusal
        records rather than hides.
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
                elif (
                    str(row.get("control") or "") == "DONE"
                    and key in {"SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP"}
                ):
                    # The label entry candidate was disproved in production: the panel closed
                    # without opening a camp page. Only the explicit done-marker semantic may
                    # target this row; the generic row semantic must not fall back to its label.
                    point = None
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
            # A DECLARED point -- ``position_hint.x`` / ``.y`` read as literals.  Refused under
            # the constitutional amendment (see the docstring's ``frame_derived_only`` note):
            # nothing here is a reading of the frame in hand, so nothing here may become a tap.
            #
            # Kept as an explicit refusal rather than deleted, so the record stays visible as a
            # *declaration* while being denied its ability to output a click target -- the
            # amendment's §六 sentence about the coordinate ledger, applied to the dictionary.
            if frame_derived_only:
                if hint.get("x") is not None and hint.get("y") is not None:
                    # ``getattr`` because harnesses construct ``LiveRuntime`` with
                    # ``object.__new__`` to exercise one method without a run, and a refusal
                    # message must never be the thing that raises: the refusal itself is the
                    # safety property, the print is only bookkeeping.
                    refusals = getattr(self, "_printed_declared_refusals", None)
                    if refusals is None:
                        refusals = set()
                        self._printed_declared_refusals = refusals
                    if str(semantic) not in refusals:
                        refusals.add(str(semantic))
                        print(
                            f"[hint] {semantic} refused: it carries only a declared position_hint "
                            f"({basis or 'no basis'}), which is a constant and not a reading of this "
                            f"frame (constitution §一.2/§一.5)",
                            flush=True,
                        )
                return None
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
        bootstrap = getattr(self, "_bootstrap_context", {}) or {}
        if bootstrap.get("bootstrap_stage"):
            self._ordinary_last = {}
            self._l1_context = None
            self._advised_request_id = ""
            self._advised_learn_context = {}
            if (bootstrap.get("bootstrap_goal_id") != str(getattr(self, "_committed_goal", "") or "")
                    or bootstrap.get("bootstrap_role_id") != self._calendar_role_id()
                    or not bootstrap.get("bootstrap_entry_label")):
                return None
            self._unknown_semantic_target = str(bootstrap.get("bootstrap_semantic_target") or bootstrap["bootstrap_entry_label"])
            self._unknown_skill_id = "TRY_ORDINARY_CONTROL"
            try:
                return self._advised_control(frame.page.value, "", Path(frame_path), frame,
                                             unnamed=not frame.known, confidence=frame.confidence)
            finally:
                self._unknown_semantic_target = ""
                self._unknown_skill_id = ""
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
        # Which model answer this step is allowed to settle.  Cleared here with the other two,
        # for the reason those are cleared: a step that resolved nothing must not be credited
        # with the previous step's answer, and (measured 2026-09-30) a request id that outlived
        # its step would attach a later verifier verdict to a step the model never touched.
        self._advised_request_id = ""
        # Cleared with it, and for the same reason: a step that resolved nothing must not be
        # credited with the previous step's answer, which would file a learned step for a semantic
        # this step never pressed.
        self._advised_learn_context = {}
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
                    title,
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

    def _unknown_navigation_target(
        self, semantic: str, frame: WorldState, frame_path: Path, *, skill_id: str,
    ) -> tuple[float, float] | None:
        """Use the existing planner only after a registered navigation locator misses."""
        navigation = (skill_id.startswith("OPEN_")
                      or skill_id.startswith("TAP_FOCUSED_TRAINING_CAMP_"))
        if not navigation or frame.page in {Page.LOADING, Page.MAINTENANCE}:
            return None
        if not getattr(self, "_committed_goal", "") or not self._calendar_role_id():
            return None
        lease = getattr(self, "device_lease", None)
        held = lease.holder() if lease is not None else None
        if held is not None and held.owner != OWNER_GAMEPLAY and not self._owns_the_lease(held):
            return None
        if (getattr(self, "execution_mode", "") == OWNER_DEVELOPMENT_VALIDATION
                and (held is None or not self._owns_the_lease(held))):
            return None
        # This is a missing control on a known page, not a missing page identity.
        # Keep the selected Goal/Skill and its real verifier; no alternative Goal
        # or model-declared COMPLETE can satisfy this navigation step.
        self._unknown_semantic_target = semantic
        self._unknown_skill_id = skill_id
        self._advised_learn_context = {}
        self._advised_request_id = ""
        try:
            return self._advised_control(frame.page.value, "", frame_path, frame,
                                         unnamed=not frame.known, confidence=frame.confidence)
        except Exception as exc:  # noqa: BLE001 - one optional provider cannot stop AUTO
            print(f"[advisor] {skill_id}/{semantic} deferred: {type(exc).__name__}: {exc}", flush=True)
            self._advised_learn_context = {}
            return None
        finally:
            self._unknown_semantic_target = ""
            self._unknown_skill_id = ""

    def _take_failed_navigation_retry(self, goal_id: str, frame: WorldState, allowed):
        """One model-backed navigation recovery after the Scheduler selects that same Goal."""
        key = (self._calendar_role_id(), goal_id)
        pending = getattr(self, "_navigation_unknown_pending", {}).pop(key, None)
        if not pending or frame.page != pending["page"]:
            return None
        skill_id = pending["skill"]
        skill = self.registry.get(skill_id)
        if (skill_id not in allowed or not self._validation_skill_allowed(skill_id)
                or skill is None or not skill.ready(frame)):
            return None
        self._force_unknown_navigation_target = pending["semantic"]
        self._failed_controls.pop(pending["semantic"], None)
        return Decision(skill_id, f"ONLINE_UNKNOWN_NAVIGATION:{pending['reason']}",
                        frame.confidence, "registered_navigation_verifier")

    def _refresh_advised_region(self, page, title, before, region, *, anchor=None):
        """Re-identify a proposal's measured element after inference, without old geometry."""
        path = self._capture_path(int(getattr(self, "_ordinary_attempts", 0)), "model_reground")
        if self._device_lost(self.device.screenshot, path):
            return None
        fresh = self._observe(path)
        if fresh.page != before.page or self._l1_state(fresh, title) != self._l1_state(before, title):
            return None
        if getattr(self, "_multi_role_enabled", False):
            identified = self.role_switch_controller.identify_current_role(path)
            if identified is not None and identified[0] != self._calendar_role_id():
                return None
        lease = getattr(self, "device_lease", None)
        held = lease.holder() if lease is not None else None
        if held is not None and held.owner != OWNER_GAMEPLAY and not self._owns_the_lease(held):
            return None
        if (getattr(self, "execution_mode", "") == OWNER_DEVELOPMENT_VALIDATION
                and (held is None or not self._owns_the_lease(held))):
            return None
        skill_id = str(getattr(self, "_unknown_skill_id", "") or "")
        if skill_id:
            skill = self.registry.get(skill_id)
            if skill is None or not skill.ready(fresh):
                return None
        measured, _, _, _ = self._advice_evidence(page, path, self._ocr_service())
        row_regions, _ = self._quick_panel_advice_regions(fresh, path)
        measured = row_regions + measured
        if anchor:
            hit = ui_collection.anchored_region(anchor, measured)
            hits = [hit] if hit is not None else []
        else:
            text = str(region.get("text") or "").strip()
            detail = region.get("detail") or {}
            template = str(detail.get("template_path") or "")
            hits = [hit for hit in measured
                    if hit.get("basis") == region.get("basis") and (
                        (template and str((hit.get("detail") or {}).get("template_path") or "") == template)
                        or (not template and text and str(hit.get("text") or "").strip() == text))]
        # Repeated labels are not an identity. A changed/ambiguous target defers.
        if len(hits) != 1:
            return None
        hit = dict(hits[0])
        box = hit.get("box_norm") or {}
        if not all(key in box for key in ("x_norm", "y_norm", "w_norm", "h_norm")):
            return None
        hit["point"] = [float(box["x_norm"]) + float(box["w_norm"]) / 2,
                        float(box["y_norm"]) + float(box["h_norm"]) / 2]
        return hit, path, fresh

    @staticmethod
    def _quick_panel_advice_regions(frame: WorldState, path: Path):
        """Expose actual row buttons, not their non-interactive OCR labels."""
        panel = frame.quick_panel or {}
        source = str((panel.get("handle") or {}).get("measured_on") or "")
        if not panel.get("open") or not source or Path(source).resolve() != Path(path).resolve():
            return [], []
        regions, boxes = [], []
        for row in panel.get("rows") or []:
            box = row.get("arrow_box_norm") or {}
            if row.get("arrow_basis") != "ROW_BUTTON_SCAN" or not all(
                    isinstance(box.get(k), (int, float)) for k in ("x_norm", "y_norm", "w_norm", "h_norm")):
                continue
            if (box["w_norm"] <= 0 or box["h_norm"] <= 0 or box["x_norm"] < 0
                    or box["y_norm"] < 0 or box["x_norm"] + box["w_norm"] > 1
                    or box["y_norm"] + box["h_norm"] > 1):
                continue
            key = str(row.get("key") or "")
            semantic = "QUICK_PANEL_ROW_" + key
            text = str(row.get("label") or key)
            regions.append({"text": text, "box_norm": dict(box),
                            "basis": "CURRENT_FRAME_QUICK_PANEL_ROW", "score": 0.9,
                            "detail": {"semantic": semantic, "locator": "ROW_BUTTON_SCAN"}})
            boxes.append({"text": text, "confidence": 0.9, **dict(box),
                          "element_kind": "INTERACTIVE_CONTROL", "element_semantic": semantic,
                          "element_executable": True})
        return regions, boxes

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

        Before any of that, though, the *learned* actions for this screen are tried
        ---------------------------------------------------------------------------
        Operator directive 2026-10-01 §15: 相同 UNKNOWN 每次都重新问 UI-Venus 是禁止的.  A screen
        whose action the verifier already passed once is a screen this project has solved, so the
        recorded semantic element is re-located on **this** frame and taken without a model call.
        The re-location is the same printed-word measurement every other tier uses, so nothing
        here is a stored coordinate: what was learned is "this screen's 关闭 does that", and the
        point is produced from the frame in front of us.

        Two properties worth stating because they are easy to get wrong:

        * the learned attempt runs **first**, before the question is even built, so a solved screen
          costs zero tokens -- and when it fails (the control has moved, been renamed, or the
          screen was mis-keyed) the ordinary path below still runs, including the model.  A learned
          record that no longer locates is therefore a *re-ask*, not a dead end;
        * the ledger is read once per run and cached, so this is a dict lookup per step rather than
          a file read per step.
        """
        advisor = getattr(self, "_advisor", None)
        key = page_knowledge.page_key(page, title)
        brain = getattr(self, "brain", None)
        goal = str(getattr(self, "_committed_goal", "")
                   or getattr(brain, "goal_id", "")
                   or getattr(brain, "current_goal", "") or "")
        # The learned attempt is placed here, not at the top of the method, because it needs the
        # same ``goal`` the question is filed under -- a learned action for one goal is not
        # knowledge about another.  And it is placed **before** the ``advisor is None`` return
        # below, because it is a deterministic re-location and not a model path: a deployment with
        # no planner at all should still get cheaper on a screen it has already solved.
        #
        # Guarded, and printed rather than swallowed: this runs on every unnamed screen, so an
        # unexpected failure here would take the whole ordinary path down with it -- but a silent
        # ``except`` would hide the learning layer being broken, which is the failure this project
        # keeps measuring as worse than a crash.  The expected negatives (nothing learned, the
        # control not drawn) are ordinary returns from ``_learned_reuse_point``, not exceptions.
        try:
            learned = self._learned_reuse_point(page, title, goal, frame_path, frame)
        except Exception as exc:  # noqa: BLE001 - learning must never fail a live step
            learned = None
            print(f"[learned] reuse lookup deferred ({type(exc).__name__}: {exc}); "
                  "falling through to the ordinary path", flush=True)
        if learned is not None:
            return learned
        if advisor is None:
            return None
        bootstrap = getattr(self, "_bootstrap_context", {}) or {}
        if bootstrap.get("bootstrap_stage"):
            if int(bootstrap.get("model_calls_this_screen") or 0) >= 2:
                return None
            bootstrap["model_calls_this_screen"] = int(bootstrap.get("model_calls_this_screen") or 0) + 1
        situation = self._l1_state(frame, title)
        # Serialised once: the request needs it as the world state, the state signature and the
        # character are read out of it, and ``to_dict`` on a whole WorldState is not free on a path
        # that runs on every step of an unnamed screen.
        observed = frame.to_dict()
        ocr = self._ocr_service()
        regions, boxes, texts, template_note = self._advice_evidence(page, frame_path, ocr)
        row_regions, row_boxes = self._quick_panel_advice_regions(frame, frame_path)
        regions = row_regions + regions
        boxes = row_boxes + boxes
        texts = tuple(row["text"] for row in row_regions) + texts
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
            # The HUD's name is not role identity. Unknown remains empty until
            # the same role-scoped live identity guard used by scheduling confirms it.
            character=self._calendar_role_id(),
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
                f"相关的控件在哪里？当前无法定位的语义目标为 "
                f"{getattr(self, '_unknown_semantic_target', '') or '(未命名控件)'}。"
                "只推进这个目标，不打开无关功能。请给出定位依据与 proposed_action。"
            ),
        )
        # Request files historically identify a page, not an encounter. Keep that
        # compatibility key and bind this execution attempt to its own causal trace.
        import uuid
        from .ui_venus_online import FrameIdentity, unknown_state_identity
        request.trace_id = f"unknown_{uuid.uuid4().hex}"
        request.parent_trace_id = str(getattr(self, "trace_id", "") or "")
        request.role_session_id = str(getattr(self, "role_session_id", "")
                                      or getattr(getattr(self, "capture_dir", None), "name", ""))
        request.episode_id = str(getattr(getattr(self, "capture_dir", None), "name", "") or "")
        request.frame_id = f"frame_{request.frame_digest}"
        request.semantic_target = str(getattr(self, "_unknown_semantic_target", "") or "")
        request.relevant_state_signature = situation
        request.unknown_identity = unknown_state_identity(goal_id=goal, page=key,
            semantic=request.semantic_target, state_signature=situation)
        # The question travels to whoever is answering it, not just its id.  A local planner
        # plans from the question's own evidence (the page, the goal, the OCR this frame
        # produced), so it needs the record; the retired answer-file reader was happy with the
        # key alone.  Detected rather than passed, so the runtime does not have to know which
        # kind of advisor it was given -- the same ``getattr`` capability check the rest of
        # this class uses for optional collaborators.
        # ``getattr`` rather than ``self.registry`` because this method is exercised on its own by
        # the wiring suite, which builds the runtime through ``object.__new__`` and therefore never
        # runs ``__init__`` -- the same defensive read the learned-ledger helpers below use.  A
        # production runtime always has the field, so this changes nothing there.
        registry = getattr(self, "registry", None)
        take_with_request = getattr(advisor, "take_request", None)
        advice = (
            take_with_request(request, registry=registry)
            if callable(take_with_request)
            else advisor.take(request.request_id, registry=registry)
        )
        # §15's numerator.  Reaching this line means the model *was* consulted, and since the
        # learned reuse ran first and returned if it could, this counts exactly one thing: a screen
        # this project had already solved, asked about again.  Counter rather than a log line
        # because the console's 重复 UNKNOWN 调用率 is this number over the run.
        if self._learned_ledger_rows():
            try:
                if unknown_learning.learned_steps_for(
                    self._learned_ledger_rows(), page_key=key, goal_id=goal
                ):
                    self._learned_model_calls_on_known = int(getattr(self, "_learned_model_calls_on_known", 0)) + 1
            except Exception:  # noqa: BLE001 - a metric must never fail a live step
                pass
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

        # Inference can outlive a page transition. Re-locate the measured element's
        # identity on a fresh screenshot; the proposal's old point is never carried
        # across frames. Pure replay callers have no device and issue no real input.
        if getattr(self, "device", None) is not None:
            refreshed = self._refresh_advised_region(page, title, frame, region, anchor=advice.target_anchor)
            if refreshed is None:
                self._learning_event("GROUNDING_REJECTED", {
                    "trace_id": request.trace_id, "parent_trace_id": request.parent_trace_id,
                    "role_id": request.character, "goal": goal, "page_key": key,
                    "unknown_identity": request.unknown_identity,
                }, reason="POST_INFERENCE_CONTEXT_OR_TARGET_CHANGED")
                return None
            region, frame_path, frame = refreshed
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
            # The directive's four questions, kept apart in the record as they are in the answer:
            # what notification was seen, which function that is, which control is being pressed,
            # and what to observe or do once inside.  ``level`` is the one the boundary was applied
            # at -- recorded, not recomputed, so the audit reads what actually happened.
            "notification": advice.notification,
            "entry": advice.entry,
            "action_level": unknown_advisor.advice_level(advice),
        }
        # This is the step the answer drives, so this is the step whose verdict settles it.
        self._advised_request_id = request.request_id
        # What this step would teach if the verifier passes (§12).  Captured *now*, at the moment
        # the answer is accepted, because by settlement time the frame is gone and the only record
        # of which semantic was pressed on which screen is this dict.  ``action_type`` is
        # ``CLICK_ELEMENT`` and that is not a placeholder: this method's whole contract is "return
        # a point to tap", so any other name would be describing a mechanism that does not exist.
        self._advised_learn_context = {
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "parent_trace_id": request.parent_trace_id,
            "frame_id": FrameIdentity.of(frame_path).frame_id,
            "frame_hash": FrameIdentity.of(frame_path).frame_hash,
            "proposal_frame_id": request.frame_id,
            "proposal_frame_hash": FrameIdentity.of(Path(request.frame_path), frame_id=request.frame_id).frame_hash,
            "unknown_identity": request.unknown_identity,
            "role_id": request.character,
            "episode_id": request.episode_id,
            "call_id": str(getattr(advisor, "last_outcome", {}).get("call_id") or ""),
            "relevant_state_signature": situation,
            "model_used": True,
            "page_key": key,
            "goal": goal,
            "semantic": semantic,
            "basis": str(advice.action_kind),
            "grounding_basis": basis,
            "expected_result": str(advice.expected_result or ""),
            "frame": str(frame_path),
            # Prior resolution attempts this run, before this one: §12's recovery evidence.
            "attempts": int(self._ordinary_attempts),
            # §12's "视觉依据", as identities rather than geometry: which reader located this point
            # and what it anchored on.  Enough for a reviewer to know *how* to find the element
            # again, and structurally incapable of carrying a pixel -- which is the same property
            # ``LearnedStepCandidate`` gets by having no coordinate field at all.
            "visual_evidence": {
                "reader": f"AI_ADVICE/{basis}",
                "ocr_anchor": str(region.get("text") or advice.target_semantics or ""),
                "region_basis": str(region.get("basis") or ""),
                "control_type": str(advice.action_kind or ""),
                "template_path": str((region.get("detail") or {}).get("template_path") or ""),
            },
        }
        self._learning_event("GROUNDING_VALID", self._advised_learn_context,
            grounding_basis="CURRENT_FRAME_VERIFIED_REGION", locator_basis=basis)
        self._learning_event("RISK_GATE_ALLOWED", self._advised_learn_context)
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

    def learning_run_counters(self) -> dict[str, int]:
        """This run's §15 counters, for the console and the end-of-run report.

        Exposed as a method rather than read as attributes so the two numbers that make the ratio
        always travel together: a reader who took one without the other could report a rate from
        a numerator with no denominator.
        """
        return {
            "learned_reuse_hits": int(getattr(self, "_learned_reuse_hits", 0)),
            "model_calls_on_known_screen": int(getattr(self, "_learned_model_calls_on_known", 0)),
        }

    # --------------------------------------------------- learned UNKNOWN reuse
    def _learned_ledger_rows(self) -> list[dict[str, Any]]:
        """The verified-step ledger, read once per run.

        Cached rather than re-read per step because this sits on the resolution path of every
        unnamed screen, and the file only changes when *this* run verifies something -- at which
        point the append invalidates the cache.  A missing ledger is an empty list, which is the
        correct answer for a project that has not learned anything yet.

        Both the ledger and the cache are created on first use rather than assumed to exist: a
        test that builds a runtime without running ``__init__`` is a supported construction in this
        project, and this path runs on *every* unnamed screen -- so it must behave like an optional
        collaborator (``getattr`` + default) instead of an initialised field.
        """
        ledger = getattr(self, "learned_ledger", None)
        if ledger is None:
            ledger = unknown_learning.VerifiedStepLedger(
                Path(__file__).resolve().parents[1] / unknown_learning.LEARNED_STEPS_PATH
            )
            self.learned_ledger = ledger
        if getattr(self, "_learned_cache", None) is None:
            try:
                self._learned_cache = ledger.verified()
            except Exception:  # noqa: BLE001 - a learning read must never fail a live step
                self._learned_cache = []
        return self._learned_cache

    def _learned_reuse_point(self, page: str, title: str, goal: str,
                             frame_path: Path, frame: "WorldState") -> tuple[float, float] | None:
        """An action this screen already proved, re-located on the current frame, or ``None``.

        §15 made mechanical.  The element is named by the client's own printed word (the ledger
        stores ``ORDINARY_CONTROL[<word>]``, which is the project's existing vocabulary for "a
        control named by what it prints"), and the point comes from ``find_printed_words`` on
        *this* frame -- so a learned action is re-located, never replayed.

        Deliberately narrow, and each bound is a rule rather than a tuning:

        * only ``FAST_PROMOTION`` / ``SLOW_PROMOTION`` rows are taken; a ``BLOCKED`` row names
          money or gems and must never be re-issued by a reuse path that has no risk gate in front
          of it;
        * only rows whose semantic is a printed control are usable -- ``AI_ADVICE[...]`` named an
          element the screen does not print, so there is no text to find and the honest answer is
          to leave it to the tier that can still ask;
        * the control must still be drawn.  If it is not, nothing is tapped and the caller proceeds
          to the ordinary path, which is the same "current frame does not match -> identify again"
          rule the L1 tier already follows.
        """
        key = page_knowledge.page_key(page, title)
        rows = self._learned_ledger_rows()
        if not rows:
            return None
        try:
            candidates = unknown_learning.learned_steps_for(
                rows, page_key=key, goal_id=str(goal or "")
            )
        except Exception:  # noqa: BLE001 - see above
            return None
        if not candidates:
            return None
        ocr = self._ocr_service()
        if ocr is None:
            return None
        for row in candidates:
            if str(row.get("risk_route") or "") == unknown_learning.ROUTE_BLOCKED:
                continue
            semantic = str(row.get("semantic_target") or "")
            recorded_state = str(row.get("relevant_state_signature") or "")
            if recorded_state and recorded_state != self._l1_state(frame, title):
                continue
            word = page_knowledge.word_from_control(semantic)
            bootstrap = getattr(self, "_bootstrap_context", {}) or {}
            if bootstrap.get("bootstrap_stage") and word != str(bootstrap.get("bootstrap_entry_label") or ""):
                continue
            visual = row.get("visual_evidence") or {}
            template_path = str(visual.get("template_path") or "")
            if (not word or word == semantic) and not template_path:
                continue
            if (page, word) in self._ordinary_tried:
                continue
            hit = find_printed_words(frame_path, (word,), ocr) if word and word != semantic else None
            if hit is None and template_path:
                # Search the current complete frame with the existing matcher.
                # The durable step stores a template identity, never a click point.
                matches = ui_collection.template_regions(frame_path, [{
                    "template_path": template_path, "semantic": semantic,
                    "roi_norm": {"x_norm": 0, "y_norm": 0, "w_norm": 1, "h_norm": 1},
                }], min_score=0.9)
                if len(matches) == 1:
                    box = matches[0]["box_norm"]
                    hit = {"center_norm": (box["x_norm"] + box["w_norm"] / 2,
                        box["y_norm"] + box["h_norm"] / 2), "box_norm": box,
                        "confidence": matches[0]["score"]}
            if hit is None:
                continue
            point = (float(hit["center_norm"][0]), float(hit["center_norm"][1]))
            self._learned_reuse_hits = int(getattr(self, "_learned_reuse_hits", 0)) + 1
            self._ordinary_tried.add((page, word))
            self._ordinary_attempts += 1
            # The same four records a measured tier leaves behind, so a learned tap is
            # indistinguishable to the rest of the runtime from one the printed-word tier found
            # -- which is what lets it register an L1 action and stage an element candidate
            # instead of being a special case nobody downstream understands.
            self._ordinary_last = {
                "page": page,
                "title": title,
                "word": word,
                "point": (round(point[0], 4), round(point[1], 4)),
                "semantic": semantic,
                "basis": "LEARNED_VERIFIED_STEP",
                "source": "LEARNED",
                "box_norm": dict(hit.get("box_norm") or {}),
            }
            self._l1_context = {
                "page": page,
                "goal": str(goal or ""),
                "state": self._l1_state(frame, title),
                "semantic": semantic,
                "text": word,
                "box_norm": dict(hit.get("box_norm") or {}),
                "basis": "LEARNED_VERIFIED_STEP",
                "source": "LEARNED",
                "confidence": float(hit.get("confidence") or 0.0),
                "frame": str(frame_path),
            }
            # A reuse has no model settlement, but its own verifier result must
            # strengthen (or reject) the learned step just like the first encounter.
            from .ui_venus_online import FrameIdentity
            import uuid
            reuse_frame_id = f"frame_{unknown_advisor.frame_digest(frame_path)}"
            self._advised_learn_context = {
                "trace_id": f"reuse_{uuid.uuid4().hex}",
                "parent_trace_id": str(row.get("trace_id") or ""),
                "reused_from_trace_id": str(row.get("trace_id") or ""),
                "unknown_identity": str(row.get("unknown_identity") or ""),
                "role_id": self._calendar_role_id(),
                "episode_id": str(getattr(getattr(self, "capture_dir", None), "name", "") or ""),
                "frame_id": reuse_frame_id,
                "frame_hash": FrameIdentity.of(frame_path, frame_id=reuse_frame_id).frame_hash,
                "relevant_state_signature": self._l1_state(frame, title),
                "model_used": False,
                "request_id": str(row.get("request_id") or ""),
                "page_key": key,
                "goal": str(goal or ""),
                "semantic": semantic,
                "basis": "LEARNED_VERIFIED_STEP",
                "grounding_basis": "CURRENT_FRAME_OCR",
                "expected_result": str(row.get("expected_result") or ""),
                "frame": str(frame_path),
                "attempts": 0,
                "visual_evidence": {"reader": "LEARNED_VERIFIED_STEP", "ocr_anchor": word,
                                    "template_path": template_path},
            }
            self._learning_event("SECOND_ENCOUNTER", self._advised_learn_context)
            self._learning_event("CANDIDATE_STEP_REUSED", self._advised_learn_context)
            self._note_printed(
                semantic,
                key,
                f"a verified step already learned on this screen "
                f"(session {row.get('session_id', '?')})",
                point,
                box_norm=hit.get("box_norm"),
                text=word,
                confidence=hit.get("confidence"),
                label=page,
            )
            print(
                f"[learned] {key}: '{word}' re-located on this frame from a verified step -- "
                f"no model needed (reuse #{getattr(self, '_learned_reuse_hits', 0)})",
                flush=True,
            )
            return point
        return None

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
                # One build, used for both consumers.  ``build_element_table`` is the same function
                # the planner's element table comes from, so the region an answer is grounded on and
                # the element the answer named cannot be two different readings of one frame --
                # which is the property that stops a tap landing where a control used to be.
                #
                # Ordering is load-bearing: composite controls come first, so a reasoner that names
                # the control by its printed word (``AI_ADVICE[登录好礼]``) grounds on the control's
                # own region rather than on the label's text box.  Measured 2026-09-25: before this,
                # the same answer resolved to the label and the tap landed on the words.
                table = ui_collection.build_element_table(frame_path, ocr, page=page)
                regions = [
                    {
                        "text": str(entry.get("text") or ""),
                        "box_norm": dict(entry.get("box_norm") or {}),
                        "basis": str(entry.get("basis") or ""),
                        "score": float(entry.get("confidence") or 0.0),
                        "detail": dict(entry.get("detail") or {}),
                    }
                    for entry in table
                    if entry.get("text")
                ]
                texts = tuple(str(region.get("text") or "") for region in regions)
                boxes = [
                    {
                        "text": str(entry.get("text") or ""),
                        "confidence": float(entry.get("confidence") or 0.0),
                        # The typed identity travels with the box, so the planner can offer a
                        # control for a click and refuse to offer a town name -- §2's requirement
                        # that an element with no reliable interactive region is not a CLICK target.
                        "element_kind": str(entry.get("kind") or ""),
                        "element_semantic": str(entry.get("semantic") or ""),
                        "element_executable": bool(entry.get("executable")),
                        **dict(entry.get("box_norm") or {}),
                    }
                    for entry in table
                    if entry.get("text")
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

        Levels (operator directive 2026-09-23).  The boundary is applied **per level**, because
        entering a function and acting inside it are different things: an ``ENTRY_CONTROL`` answer is
        screened against the money/irreversibility list alone, while a ``TASK_ACTION`` answer -- and
        any answer that does not declare a level, including every answer written before the levels
        existed -- is screened against the whole list, exactly as it was before.  That is what makes
        "不要求先写完整招募 Skill 才能首次免费招募" possible without loosening anything: the first
        free attempt is an *entry*, and whether the page charges for it is decided by the page.
        """
        bootstrap = getattr(self, "_bootstrap_context", {}) or {}
        if bootstrap.get("bootstrap_stage"):
            allowed_label = str(bootstrap.get("bootstrap_entry_label") or "")
            allowed_semantic = str(bootstrap.get("bootstrap_semantic_target") or "")
            actual_label = str(region.get("text") or "").strip()
            actual_semantic = str((region.get("detail") or {}).get("semantic") or "")
            if not ((allowed_label and allowed_label == actual_label)
                    or (allowed_semantic and allowed_semantic == actual_semantic)):
                return "BOOTSTRAP_SAFE_ENTRY_IDENTITY_MISMATCH"
            if any(word in actual_label for word in ("购买", "使用", "消耗", "出征", "攻击", "集结", "召回", "确认")):
                return "BOOTSTRAP_RESOURCE_ACTION_NOT_AUTHORIZED"
        level = unknown_advisor.advice_level(advice)
        identity = " ".join(
            [
                str(region.get("text") or ""),
                str(advice.target_semantics or ""),
                str(advice.grounding_ref or ""),
            ]
        ).lower()
        for word in unknown_advisor.words_refused_at(level):
            if word.lower() in identity:
                return f"the candidate itself is {word!r} at level {level}"
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
            recorded = self._control_ledger.get(control_experience.control_key(
                page, semantic, control_experience.state_signature(frame.to_dict()),
            ))
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
        """Where this device last saw ``semantic`` -- **diagnostic only, never a tap**.

        ⚠ 2026-09-24 — READ THIS BEFORE CALLING IT.

        This method is **no longer wired into ``_resolve_semantic_target``** and must not
        be re-wired.  The constitutional amendment (禁止坐标硬编码, 优先级最高) forbids a
        production click whose target is a stored coordinate:

            §一.3  复用历史截图或历史操作中的点击坐标
            §一.5  模板、OCR 或语义识别失败后，回退到历史坐标
            §一.6  根据某类页面的历史坐标记忆，直接生成当前页面的点击位置
            §二   本约束不设置生产点击例外
            §六   现有坐标台账如仍承担生产点击定位，应停止其直接输出点击目标的能力

        It is kept because §六 keeps positions for **audit and failure reproduction**
        ("历史 Episode 可以保存实际点击位置用于审计和故障复现"): ``tools/frame_owner.py``,
        ``probe_experience_reuse.py`` and incident analysis all read the ledger, and deleting
        the reader would delete that ability.  What ended is the one thing the amendment
        names -- its output reaching a tap.

        Measured before removal, from the real runtime logs: the tier that called this
        printed ``reusing a measured position`` **21 times** -- 21 production taps pointed at
        a coordinate rather than at a control -- and it refused 8 more, which is its own
        record that it was already reaching for screens it did not belong to.

        So: the conditions below are still correct and still enforced (so that a *diagnostic*
        answer is not a misleading one), but satisfying all of them no longer makes the point
        tappable.  Any future caller must be outside the tap path.

        ---
        (original docstring, kept because the conditions are the diagnostic contract)

        Where this device last saw ``semantic``, when the template can no longer find it.

        Operator §四.1/§四.3: "已知成功操作优先复用", "已知页面跳转结果用于规划导航".
        Until now the ledger was written on every step and read by nobody, so a control
        the machine had clicked thirty-five times successfully was still unusable the
        moment its template stopped matching -- which is the same wall
        ``TARGET_INFANTRY_CAMP_HIGHLIGHTED`` hits for a different reason.  This is the
        read.

        Conditions, and each excludes a different way of being wrong:

        * **the screen must match**, and it is the *screen* rather than the page because the page is
          not always a screen.  Two mechanisms, and they are not the same one twice:

          - the **key** carries the frame's ``state_signature`` (``POPUP|POWER_OVERVIEW|BTN_CLOSE``,
            not ``POPUP|BTN_CLOSE``), so a coordinate measured on one overlay is simply not found
            from another.  This is what fixes the live defect: the entry the runs were spending was
            ``POPUP|BTN_CLOSE`` at (0.8819, 0.3563), measured on the 退出确认 dialog, and 加成总览
            asks for a key nothing has ever written (issue #109).
          - ``reusable_on_this_screen`` is the second line, reached when a key and a stored screen
            disagree -- an entry that recorded a screen under a key that names none.  It keeps the
            two from drifting apart rather than doing the everyday work.

          (The old text here said a normalized point is "only allowed behind an independent proof of
          which screen it is on".  That was this project's own rule and it was a good one; the
          amendment supersedes it with a stronger one -- no stored point at all.)
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
        screen = control_experience.state_signature(frame.to_dict())
        entry = self._control_ledger.get(control_experience.control_key(page, semantic, screen))
        if entry is None:
            return None
        if not control_experience.reusable_on_this_screen(entry, screen):
            # The point exists but belongs to another screen.  Measured 2026-09-23 (issue #109):
            # ``POPUP|BTN_CLOSE`` held (0.8819, 0.3563), measured on the 退出确认 dialog, and eight
            # consecutive runs spent it on 加成总览 -- where it is the panel's own number column.
            # The refusal is the honest sentence: this frame does not draw the control where this
            # project has measured it, so the step fails instead of tapping a remembered stranger's
            # coordinate (operator §一: 不得把旧截图的点击坐标直接用于变化后的页面).
            if str(screen) not in self._printed_screen_refusals:
                self._printed_screen_refusals.add(str(screen))
                print(
                    f"[experience] {page}|{semantic} refused: the stored point was measured on "
                    f"{entry.screen or '(an unnamed screen)'} and this frame is {screen or '(unnamed)'}",
                    flush=True,
                )
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
            pages, words, merged = declared
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
                # ``merged`` is the record's own ``ocr_merged``: the client drew this control's name
                # together with its icon, so the token contains the name instead of equalling it.
                # Still a reading of *this* frame -- the word has to be there -- and still scored
                # against the record's declared words, not against every token on screen.
                hit = find_printed_words(frame_path, words, ocr, allow_containment=merged)
                if hit is not None:
                    point = (float(hit["center_norm"][0]), float(hit["center_norm"][1]))
                    self._note_printed(
                        semantic,
                        page,
                        f"the word {hit['word']!r}" + ("" if hit.get("exact", True) else " inside a merged token"),
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
        for holder in (getattr(self, "vision", None), getattr(self, "semantic_vision", None)):
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

    def _confirm_live_role(self, frame_path: Path | str) -> tuple[bool, str, Path | str]:
        """Confirm the active account, tolerating an occluded avatar after bootstrap.

        Each fresh worker must uniquely match a role avatar before it can use
        role-scoped state. Within that worker, a temporarily unreadable avatar
        (for example, the game blurring the city behind a modal) does not mean
        the account changed: this runtime owns the UI and a role switch ends the
        worker. A uniquely matched different avatar still stops the run.
        """
        confirmed_frame: Path | str = frame_path
        if not self._multi_role_enabled:
            return True, "", confirmed_frame

        observed_identity = self.role_switch_controller.identify_current_role(confirmed_frame)
        if observed_identity is None and not self._role_identity_bootstrapped:
            prepare_home = getattr(
                self.role_switch_controller, "prepare_current_role_home", None,
            )
            if callable(prepare_home):
                home_frame = prepare_home(confirmed_frame)
                if home_frame is not None:
                    confirmed_frame = home_frame
                    observed_identity = self.role_switch_controller.identify_current_role(confirmed_frame)
                    if observed_identity is not None:
                        print(
                            f"[global-role] returned to HOME before startup identity confirmation: "
                            f"{confirmed_frame}",
                            flush=True,
                        )
        if observed_identity is None:
            if self._role_identity_bootstrapped and self._role_identity_confirmed:
                print(
                    "[global-role] avatar is occluded or ambiguous; retaining the "
                    f"already confirmed role {self._calendar_role_id()} for this runtime",
                    flush=True,
                )
                return True, "ROLE_IDENTITY_RETAINED_FRAME_UNREADABLE", confirmed_frame
            self._role_identity_confirmed = False
            return False, "ROLE_IDENTITY_UNCONFIRMED", confirmed_frame

        observed_role_id, avatar_score = observed_identity
        if not self._role_identity_bootstrapped:
            self.role_id = observed_role_id
            identity = self._role_catalog_by_id.get(observed_role_id, {})
            self.role_scope = "FRESH_RUNTIME"
            self._role_identity_confirmed = True
            self._role_identity_bootstrapped = True
            self._activate_role_persistent_state(observed_role_id)
            state_store = self.global_scheduler_state_store
            if state_store is not None:
                state_store.recover_after_restart(
                    actual_role_id=observed_role_id,
                    actual_role_name=str(identity.get("display_name") or identity.get("role_name") or ""),
                    observed_at=datetime.now(timezone.utc),
                )
            print(
                f"[global-role] current identity matched live avatar: {observed_role_id} "
                f"(score={avatar_score:.3f}); all role live state starts stale",
                flush=True,
            )
            return True, "ROLE_IDENTITY_CONFIRMED", confirmed_frame

        if observed_role_id != self._calendar_role_id():
            # The one-device lease should make an in-process account change
            # impossible. If it happens anyway, invalidate the prior role before
            # allowing another task to run.
            self.role_id = observed_role_id
            self.role_scope = "FRESH_RUNTIME"
            self._activate_role_persistent_state(observed_role_id)
            state_store = self.global_scheduler_state_store
            if state_store is not None:
                state_store.recover_after_restart(
                    actual_role_id=observed_role_id,
                    actual_role_name=str(
                        self._role_catalog_by_id.get(observed_role_id, {}).get("display_name") or ""
                    ),
                    observed_at=datetime.now(timezone.utc),
                )
            return False, f"ROLE_IDENTITY_CHANGED:{observed_role_id}", confirmed_frame

        return True, "ROLE_IDENTITY_CONFIRMED", confirmed_frame

    # ------------------------------------------------------- GENERIC_SESSION_ENGINE_V1
    #
    # Two transport services the session host needs, and deliberately nothing else.  The
    # engine owns the sequence, the budgets and the lifecycle; the business adapter owns the
    # domain reading; **these two own the wire** -- how one atomic skill reaches the device
    # and how its outcome is judged.  Keeping them here (rather than in ``session_host``) is
    # what stops a session from growing a second executor, a second router or a second
    # verifier: there is exactly one implementation of each, and a session borrows it.

    def _session_execute_atomic(self, *, skill_id: str, before: WorldState, before_path: Path,
                                planned_resource: str | None = None, rally_target=None):
        """Dispatch ONE atomic skill for a session step, through the loop's own router.

        The same three lines the main loop runs immediately before ``Scheduler.tick``: an ADB
        executor bound to *this* observation, ``build_router`` choosing the backend from the
        skill's own routing row, and the pair handed to the **single** Scheduler.  A session
        that built its own executor would be the second routing implementation the directive
        forbids, and it would drift the first time a routing row changed.

        ``before`` is the frame the adapter decided on -- the same relationship the main loop
        has between its decision and its ``before`` state, which is what makes the verifier's
        comparison meaningful.  Returns the runtime's own ``ExecutionResult``, or ``None``
        when the Scheduler refused to dispatch (gone skill, not ready, entry gate).
        """
        if not self._validation_skill_allowed(skill_id):
            return None
        world = before

        def resolve(semantic: str):
            point = self._resolve_semantic_target(
                semantic, world, frame_path=before_path,
                resource=planned_resource, rally_target=rally_target,
            )
            if point is not None:
                return point
            return self._unknown_navigation_target(semantic, world, before_path, skill_id=skill_id)

        adb_executor = Executor(
            production=True, dry_run=False, device=self.adb_device,
            target_resolver=resolve, backend="ADB",
        )
        executor = build_router(
            adb_executor=adb_executor, adb_resolver=resolve,
            maa_adapter=self.maa_adapter, skill_id=str(skill_id),
            routing=self.routing, ledger=self.backend_ledger, rally_target=rally_target,
        )
        if self._scheduler is None:
            self._scheduler = Scheduler(
                self.brain, self.registry, executor, self.candidate_pool,
                global_state_store=getattr(self, "global_scheduler_state_store", None),
            )
        else:
            self._scheduler.executor = executor
        # The reason names the session, so a session's step is never readable in the episode
        # stream as a goal-driven decision.  The decision is NOT re-derived: the adapter
        # already chose the step, and a second ``brain.decide`` would answer differently for
        # the same frame (see ``Scheduler.tick``).
        decision = Decision(str(skill_id), f"session_step:{skill_id}", 1.0, "")
        return self._scheduler.tick(world, decision).execution

    def _session_verify(self, skill_id: str, before: WorldState, after: WorldState,
                        rally_target=None):
        """The runtime's own verifier for one skill, or ``None`` when it has none.

        Shares the rally branch with the loop's ``verify_current_step`` rather than
        restating it, so a session's ``START_RALLY`` / ``JOIN_RALLY`` is judged by the same
        target-scoped check the rest of the system uses -- the place where "no second
        verifier" would otherwise quietly stop being true, because the rally check is the one
        verifier that needs the goal's own target.
        """
        if before is None or after is None:
            return None
        if skill_id in ("START_RALLY", "JOIN_RALLY"):
            target = getattr(rally_target, "value", rally_target) or "UNKNOWN"
            return _verify_rally_action(skill_id, before, after, str(target))
        verifier = self.VERIFIED_ATOMIC.get(str(skill_id or ""))
        return verifier(before, after) if verifier is not None else None

    def _record_session_timeline(self, event: str, **fields: Any) -> None:
        """Keep session evidence beside this run's frames; logging cannot stop AUTO."""
        try:
            path = self.capture_dir / "session_timeline.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {"timestamp": datetime.now(timezone.utc).isoformat(),
                   "event": event, "role_id": self.role_id,
                   "repo_revision": self.code_revision, **fields}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def _run_goal_session(self, *, route, index: int, run_id: str, before: WorldState,
                          before_path: Path, best_goal, latency: dict, page_audit: dict,
                          rally_target, planned_resource: str | None,
                          attached_goal_ids: Iterable[str] = ()):
        """Run one Goal's internal sequence, then hand the device straight back.

        Returns the ``SessionResult``, or ``None`` when the session could not be built at all
        -- in which case the caller falls through to the ordinary atomic path, which is the
        safe direction: a routing defect must never turn into "this Goal did nothing".

        Nothing here decides anything globally.  The Goal and the role were already chosen by
        the Scheduler and the Brain before this is reached, the adapter is handed only its own
        domain, and the one question the session may ask the Scheduler is the yield check at
        its own safe point (``Scheduler.session_preemption``).
        """
        from .session_adapters import make_adapter, plan_for
        from .session_engine import SessionContext, SessionEngine
        from .session_host import LiveRuntimeSessionHost, SessionRunBinding

        goal_id = str(getattr(best_goal, "goal_id", "") or "")
        if not goal_id:
            return None
        plan = plan_for(route, goal_id=goal_id, role_id=self._calendar_role_id(),
                        goal_evidence=getattr(best_goal, "evidence", None))
        adapter = make_adapter(route.adapter, extras={**plan.extras,
                               'entry_skill': page_audit.get('attempted_skill', '')},
                               resource_budget=plan.spec.resource_budget)
        if adapter is None:
            return None
        binding = SessionRunBinding(
            index=index, goal_id=goal_id,
            role_id=str(self.role_id or self._calendar_role_id() or ""),
            before=before, before_path=before_path,
            latency=latency, page_audit=page_audit,
            settle_seconds=float(self.settle_seconds or 0.0),
            planned_resource=planned_resource, rally_target=rally_target,
            committed_goal=str(self._committed_goal or ""),
            attached_goal_ids=tuple(attached_goal_ids or ()),
        )
        context = SessionContext(
            spec=plan.spec, run_id=str(run_id), episode_prefix=self.capture_dir.name,
            goal_deadline_s=plan.goal_deadline_s, extras=plan.extras,
        )
        host = LiveRuntimeSessionHost(self, binding)
        try:
            return SessionEngine().run(context, adapter, host)
        except Exception as exc:  # noqa: BLE001
            # The engine already catches its own exceptions and returns a FAILED result; this
            # is the backstop for a defect in building the session (a bad route declaration, a
            # host that cannot be constructed).  A session failure may never end the run.
            self._narrate_once(f"session could not start for {goal_id}: "
                               f"{type(exc).__name__}:{exc}")
            return None

    def run(
        self,
        *,
        max_actions: int = 10,
        allowed_skills: set[str] | None = None,
        stop_after_skill: str | None = None,
        autogen_enabled: bool = True,
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
        self._giant_stamina_failed = False
        # The meters this run has read so far; see _remember_goal_meters.
        self._goal_meters: dict[str, float] = {}
        self._committed_goal = ""
        gate = self._gate()
        run_started_at = datetime.now(timezone.utc)
        run_id = f"{run_started_at.strftime('%Y%m%dT%H%M%S%fZ')}_{self.capture_dir.name}"
        audit_pages: list[dict[str, Any]] = []
        audit_starting_page: str | None = None
        audit_starting_goal: str | None = None
        audit_starting_priority: float | None = None

        def connected_state(target) -> bool | None:
            status_reader = getattr(target, "status", None)
            if not callable(status_reader):
                return None
            try:
                status = status_reader()
                value = getattr(status, "connected", None)
                return bool(value) if value is not None else None
            except Exception:  # noqa: BLE001 - diagnostics must never affect a run
                return None

        def append_fruitless_audit(reason: str) -> None:
            if self.fruitless_audit_path is None or reason != self.NOTHING_LEFT_TO_LOOK_AT:
                return
            try:
                last_page = audit_pages[-1] if audit_pages else {}
                final_step = steps[-1] if steps else None
                last_decision = final_step.decision if final_step is not None else None
                category, _state = state_for_stop_reason(
                    reason,
                    decision_skill=getattr(last_decision, "skill", None),
                    action_executed=bool(
                        final_step is not None
                        and final_step.execution is not None
                        and final_step.execution.executed
                    ),
                    verifier_failed=any(
                        step.verification is not None and not step.verification.ok for step in steps
                    ),
                )
                latest = last_page.get("observations", {})
                row = {
                    "run_id": run_id,
                    "started_at": run_started_at.isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "role_id": self.role_id or None,
                    "goal_id": audit_starting_goal,
                    "goal_priority": audit_starting_priority,
                    "starting_page": audit_starting_page,
                    "visited_pages": list(dict.fromkeys(
                        str(item.get("page", "UNKNOWN")) for item in audit_pages
                    )),
                    "per_page": audit_pages,
                    "scheduler": {
                        "runnable_goals": last_page.get("scheduler", {}).get("runnable_goals", []),
                        "selected_goal": last_page.get("scheduler", {}).get("selected_goal"),
                        "alternatives": last_page.get("scheduler", {}).get("alternatives", []),
                        "switch_task_possible": last_page.get("scheduler", {}).get("switch_task_possible", False),
                        "wait_reason": last_page.get("scheduler", {}).get("wait_reason"),
                    },
                    "queues": {
                        key: latest.get(key)
                        for key in ("march", "building", "research", "training")
                    },
                    "environment": {
                        "device_connected": connected_state(self.device),
                        "maa_available": self.maa_adapter is not None,
                        "adb_available": connected_state(self.adb_device),
                    },
                    "final_reason": reason,
                    "stop_category": category.value,
                }
                target = self.fruitless_audit_path
                target.parent.mkdir(parents=True, exist_ok=True)
                encoded = (json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, encoded.encode("utf-8"))
                finally:
                    os.close(fd)
            except Exception:  # noqa: BLE001 - an audit must never alter gameplay
                pass

        def finish(reason: str) -> LiveRun:
            append_fruitless_audit(reason)
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
        #: Controls this run asked for and got **no point** for, by the resolver's own reason.
        #:
        #: Kept apart from ``_failed_controls`` on purpose: a control that failed its verifier was
        #: tried and observed, while this one was never issued at all.  §6 forbids two root causes
        #: sharing one name, and the two behave differently downstream -- the first has a verifier
        #: verdict to report, the second has only the resolver's sentence.
        self._unresolved_controls: dict[str, tuple[int, str]] = {}
        #: Which of those have already been handed to another goal once.  The handover is offered
        #: once because a screen-level decision is the same step for every goal (see the guard
        #: before ``adb_executor``); a second handover would buy another identical non-attempt.
        self._unresolved_handed_over: set[str] = set()
        self._printed_remembered: set[str] = set()
        # Runtime self-generation: one derivation attempt per control per run, and a
        # record of what was derived so the run report can name it rather than let it
        # look like pre-existing knowledge. Off entirely when disabled, because a
        # hands-off run must stay hands-off.
        self._autogen_enabled: bool = bool(autogen_enabled)
        self._autogen_attempted: set[str] = set()
        # Bounded repair: one re-derivation per node-owning semantic per run.
        self._autogen_repaired: set[str] = set()
        self.recently_autogen: list[dict[str, str]] = []
        #: Screens whose stored point was refused for belonging elsewhere, so the sentence is
        #: printed once per screen per run rather than once per step.
        self._printed_screen_refusals: set[str] = set()
        #: Semantics refused for carrying only a *declared* ``position_hint`` (a constant in the
        #: dictionary) rather than a reading of the frame in hand.  Printed once per semantic per
        #: run for the same reason as ``_printed_screen_refusals``: the refusal is a property of the
        #: record, not of the step, so repeating it per step would bury the run's real log.
        #: Constitutional basis §一.2 / §一.5 / §八 (a coordinate moved into a config file is still
        #: a coordinate); see ``_dictionary_hint``'s ``frame_derived_only`` note.
        self._printed_declared_refusals: set[str] = set()
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
        # On-demand analysis (operator 2026-09-22; re-based 2026-09-25).  The advisor answers
        # a question about a screen no registered skill can advance.  It used to be answered
        # by a WorkBuddy background job; from 2026-09-25 the answer is planned **locally** by
        # the Qwen on this machine (``ui_planner.ManagedAdvisor``), which is why the abstract
        # four-method interface below is unchanged -- see
        # ``knowledge/failure_patterns/integration/WORKBUDDY_CHANNEL_RETIRED.md``.
        #
        # Either way it has no client and cannot block: a planner that is off, unreachable,
        # over budget or answering with a refusal returns no advice, and the cycle proceeds
        # on the paths that already work.  ``_last_advice`` is the answer this step used, and
        # ``_last_attempt_summary`` is the evidence handed over with a question.
        #
        # Built **here**, per run, from what ``__init__`` was given: a factory (called for a fresh
        # advisor with fresh per-run budgets), an instance, or nothing at all.  The default is the
        # pre-existing reader, so a caller that knows no planner exists behaves exactly as before.
        factory = getattr(self, "_advisor_factory", None)
        if callable(factory):
            self._advisor = factory()
        else:
            self._advisor = factory if factory is not None else unknown_advisor.UnknownAdvisor()
        self._last_advice: dict[str, Any] | None = None
        self._last_attempt_summary: dict[str, Any] = {}
        # The answer this step is allowed to settle: the request id of the advice the step
        # actually consumed, or "" for a step the model had nothing to do with.  Set when an
        # answer is accepted, cleared at the top of every resolution, and consumed by
        # ``_settle_advised_step`` -- so a verifier verdict can never be pinned on a step the
        # model did not drive.
        self._advised_request_id: str = ""
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
                      scheduler_loop_alive=True, last_fatal_error=None, stop_reason=None,
                      stop_category=None)

        previous_action_end: float | None = None
        # A tutorial overlay may consume the first current-frame camp tap. Permit at most
        # one retry per camp, after role, page, popup, panel, and static-camera checks.
        training_focus_retry_used: set[str] = set()
        pending_training_focus_retry: dict[str, Any] | None = None
        self._navigation_unknown_pending = {}
        self._navigation_unknown_attempted = set()
        # Consecutive ticks this run re-observed the active role instead of acting.  Cleared
        # whenever an action actually executes, so it counts a streak and not a total.
        role_refresh_ticks = 0
        loop_return_pending: dict[str, Any] | None = None

        for index in range(1, max_actions + 1):
            latency_started = time.monotonic()
            latency: dict[str, float | None] = {}
            if previous_action_end is not None:
                latency["inter_step_wait_ms"] = max(0.0, (latency_started - previous_action_end) * 1000)
            if index == 1 and os.environ.get("WINTER_WORKER_ENTRY_MONOTONIC"):
                try:
                    latency["worker_start_ms"] = max(
                        0.0,
                        (latency_started - float(os.environ["WINTER_WORKER_ENTRY_MONOTONIC"])) * 1000,
                    )
                except ValueError:
                    pass
            ocr_service = self._ocr_service()
            ocr_before_ms = float(getattr(ocr_service, "timing_total_ms", 0.0))
            parse_before_ms = float(getattr(ocr_service, "timing_parse_ms", 0.0))
            ocr_before_calls = int(getattr(ocr_service, "timing_calls", 0))
            ocr_before_hits = int(getattr(ocr_service, "timing_cache_hits", 0))
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
            phase_started = time.monotonic()
            before_path = self._capture_path(index, "before")
            latency["capture_ms"] = (time.monotonic() - phase_started) * 1000
            if self._device_lost(self.device.screenshot, before_path):
                return finish(self._device_stop_reason)
            if self._multi_role_enabled:
                identity_ok, identity_state, confirmed_frame = self._confirm_live_role(before_path)
                if Path(confirmed_frame) != before_path:
                    before_path = Path(confirmed_frame)
                if not identity_ok:
                    reason = identity_state
                    changed = reason.startswith("ROLE_IDENTITY_CHANGED:")
                    self._runtime(
                        agent_state=AgentState.IDLE.value,
                        current_skill="ROLE_IDENTITY_REFRESH",
                        reason=("live role avatar changed during one runtime session" if changed
                                else "current frame did not uniquely match an enabled role avatar"),
                        next_action=("restart and rebuild WorldState for the observed role" if changed
                                     else "reobserve before any role-scoped action"),
                        stop_reason=reason,
                    )
                    print(f"[global-role] {reason}; no further input will be sent", flush=True)
                    return finish(reason)
            phase_started = time.monotonic()
            before = self._observe(before_path, latency=latency, phase="before")
            latency["reobserve_ms"] = (time.monotonic() - phase_started) * 1000
            if pending_training_focus_retry is not None:
                pending = pending_training_focus_retry
                pending_training_focus_retry = None
                expected_goal = str(pending.get("goal_id") or "")
                expected_role = str(pending.get("role_id") or "")
                state_is_same_camp_route = (
                    expected_goal
                    # The camp identity this route carries is the run's committed goal.
                    # ``_remember_training_continuation`` was folded into
                    # ``self._committed_goal`` (assigned where the Scheduler selects the
                    # goal, and published as ``training_continuation_goal_id``); reading
                    # the retired name here crashed the run before this gate could say no.
                    and self._committed_goal == expected_goal
                    and (not expected_role or self._calendar_role_id() == expected_role)
                    and before.page is Page.HOME
                    and before.popup is None
                    and not before.training
                    and before.quick_panel.get("open") is False
                )
                point = None
                if state_is_same_camp_route:
                    point = reproject_point_on_static_city_view(
                        Path(str(pending.get("reference_frame") or "")),
                        before_path,
                        pending.get("point") or (),
                    )
                if point is not None:
                    before = replace(before, training={
                        "navigation": "PANEL_CAMP_FOCUSED",
                        "camp_focus_tap_norm": list(point),
                        "camp_focus_source": "REOBSERVED_STATIC_CITY_VIEW",
                        "camp_focus_retry_attempt": 1,
                        "camp_focus_reference_frame": str(pending.get("reference_frame") or ""),
                        "camp_focus_current_frame": str(before_path),
                    })
                    print(
                        f"[training] {pending.get('camp')} action bar still closed; "
                        "same HOME city view re-observed, allowing one current-frame retry",
                        flush=True,
                    )
                else:
                    print(
                        f"[training] {pending.get('camp')} tap recovery declined: "
                        "role/page/panel/camera did not revalidate",
                        flush=True,
                    )

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
            if str(getattr(self.brain, "current_goal", "") or "") == "GATHER_RESOURCE":
                self._active_gather_resource = planned_resource
            if before.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                before = replace(before, resource_target=planned_resource)
            self._runtime(last_tick_time=datetime.now(timezone.utc).isoformat(),
                          page=before.page.value, confidence=before.confidence,
                          vision="READY" if before.known else "UNKNOWN", screenshot_path=str(before_path),
                          march_used=before.march_used, march_max=before.march_max,
                          queues={"building": before.building, "research": before.research, "training": before.training,
                                  "intel": before.intel, "alliance": before.alliance, "events": before.events})
            before = self._reject_a_dropped_digit(before)
            selection_started = time.monotonic()
            goals = self._record_goals(before, frame=before_path)
            self._remember_goal_meters(goals)
            # Operator §四/§五: the board is re-ranked here, on every step, against the
            # frame we are standing on -- not once per run.  ``rank`` returns the whole
            # board with each term, and ``best`` is the same ordering, so the choice and
            # the explanation can never disagree.
            selectable_goals = self._selectable(self._focus_validation_goals(goals), deferrals)
            board = self.goal_library.rank(
                selectable_goals,
                before,
                fairness=self._fairness,
                routes=self._routes,
                event_readiness=self._event_readiness_for_goals(selectable_goals),
            )
            best_goal = board[0][0] if board else None
            self._note_the_choice(board, before)
            if best_goal is None and self._validation_route_scope_active():
                return finish('NO_RUNNABLE_VALIDATION_GOAL')
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
            self._sync_brain_goal(best_goal, gate)
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
            bootstrap_decision = self._bootstrap_decision(best_goal, before)
            decision = bootstrap_decision or (leave if leave is not None else self.brain.decide(before, self.registry))
            decision = self._stop_instead_of_looking_again(before, decision, best_goal)
            global_credited_goal_ids: tuple[str, ...] = ()
            if self._multi_role_enabled and self._role_identity_confirmed:
                active_role_id = self._calendar_role_id()
                global_store = self.global_scheduler_state_store
                if self._scheduler is None:
                    # Arbitration and execution share this one Scheduler instance.
                    # It receives its real step-scoped executor below before tick().
                    self._scheduler = Scheduler(
                        self.brain, self.registry, Executor(), self.candidate_pool,
                        global_state_store=global_store,
                    )
                state = global_store.load() if global_store is not None else None
                observations = self._global_role_observations(
                    before, goals, decision,
                    role_switch_cost=self._measured_role_switch_cost(state),
                )
                selection = self._scheduler.select_global(
                    observations,
                    current_role_id=active_role_id,
                    now=datetime.now(timezone.utc),
                    last_switch_at=getattr(state, "last_role_switch_at", None),
                    # ROLE_SESSION_POLICY: the current role's own logical batch, plus the
                    # deployment's parameters.  Passed explicitly rather than re-read from
                    # the store so the gate and the persisted session cannot disagree.
                    role_session=getattr(state, "role_session", None),
                    role_session_policy=self.role_session_policy,
                    # A switch is already an action boundary. Candidate exploration
                    # accounting belongs to Scheduler.tick and must happen once.
                    mark_candidate_attempts=False,
                )
                if selection.role_id and selection.role_id != active_role_id:
                    held = self.device_lease.holder() if self.device_lease is not None else None
                    if (held is not None and held.owner != OWNER_GAMEPLAY
                            and not self._owns_the_lease(held)):
                        switch_reason = f"ROLE_SWITCH_REFUSED_DEVICE_LEASE:{held.owner}"
                        print(f"[global-role] {switch_reason}; keep current role", flush=True)
                    else:
                        switch_result = self.role_switch_controller.switch_to(
                            source_role_id=active_role_id,
                            target_role_id=selection.role_id,
                            reason=selection.selection_reason,
                            reason_class=selection.switch_reason_class,
                        )
                        if switch_result.ok:
                            reason = f"ROLE_SWITCHED_TO:{selection.role_id}"
                            print(
                                f"[global-role] {selection.selection_reason}; verified in "
                                f"{switch_result.elapsed_seconds:.1f}s; restarting for a fresh "
                                f"{selection.role_id} observation",
                                flush=True,
                            )
                            self._runtime(
                                agent_state=AgentState.IDLE.value,
                                current_goal="GLOBAL_ROLE_ARBITRATION",
                                current_skill="ROLE_SWITCH",
                                reason=selection.selection_reason,
                                next_action="restart and observe the confirmed target role",
                                stop_reason=reason,
                            )
                            return finish(reason)
                        switch_reason = f"ROLE_SWITCH_FAILED:{selection.role_id}:{switch_result.reason}"
                        print(f"[global-role] {switch_reason}; stop before using the pre-switch frame", flush=True)
                        if global_store is not None:
                            try:
                                global_store.record_decision(decision={
                                    "decision": "ROLE_SWITCH_FAILED",
                                    "current_role_id": active_role_id,
                                    "selected_role_id": selection.role_id,
                                    "selected_goal_id": selection.goal_id,
                                    "selected_skill_id": selection.requested_skill,
                                    "reason": switch_reason,
                                    "scheduler_reason": selection.selection_reason,
                                    "evidence": list(switch_result.evidence),
                                })
                            except (OSError, TypeError, ValueError):
                                pass
                        self._runtime(
                            agent_state=AgentState.IDLE.value,
                            current_goal="GLOBAL_ROLE_ARBITRATION",
                            current_skill="ROLE_SWITCH",
                            reason=switch_reason,
                            next_action="reobserve after the target role switch cooldown",
                            stop_reason=switch_reason,
                        )
                        # The controller may have left the client in settings or an
                        # intermediate login page. Never execute a decision built
                        # from the screenshot captured before the failed transition.
                        return finish(switch_reason)
                elif selection.decision.reason in ROLE_REFRESH_ONLY_REASONS \
                        and selection.index is None:
                    reason = selection.decision.reason
                    # TASK THROUGHPUT V1 §10/§23/§24.  This verdict says "look at this same
                    # account again", not "this account is finished", and the *account* is
                    # already kept -- but the run was ended to obtain the re-observation, and
                    # that is what the directive calls device idle while work exists:
                    #
                    #   measured on pin 7055f02, 2026-09-30: run ended 03:14:37 after three
                    #   successful actions (OPEN_MAIL, MAIL_CLAIM_REWARDS, DISMISS_SHARED_REWARD)
                    #   with ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE; the panel then waited 30 s and
                    #   started a fresh subprocess, and the device sat idle.  Ending the run also
                    #   classified this reason as SYSTEM_FAILURE, so the panel's own
                    #   ``should_continue_auto_cycle`` returned False and AUTO stopped outright.
                    #
                    # So: re-observe in this run.  Bounded, because a role that never plans a
                    # candidate must still end its run rather than spin here.
                    role_refresh_ticks += 1
                    if role_refresh_ticks > self.max_role_refresh_ticks:
                        self._runtime(
                            agent_state=AgentState.IDLE.value,
                            current_goal="GLOBAL_SCHEDULER",
                            current_skill=reason,
                            reason=selection.selection_reason,
                            next_action=selection.next_wakeup or "bounded global refresh",
                            stop_reason=reason,
                        )
                        print(
                            f"[global-role] {reason}; {role_refresh_ticks} consecutive "
                            f"re-observations reached the limit -- ending the run; "
                            f"{selection.selection_reason}",
                            flush=True,
                        )
                        return finish(reason)
                    # ``AUTO_RUNNING`` and no stop_reason on purpose: the run has not stopped.
                    self._runtime(
                        agent_state=AgentState.AUTO_RUNNING.value,
                        current_goal="GLOBAL_SCHEDULER",
                        current_skill=reason,
                        reason=selection.selection_reason,
                        next_action="re-observe the same role in this run",
                    )
                    print(
                        f"[global-role] {reason}; re-observing the same role in this run "
                        f"({role_refresh_ticks}/{self.max_role_refresh_ticks}); "
                        f"{selection.selection_reason}",
                        flush=True,
                    )
                    continue
                elif selection.role_id == active_role_id and selection.index is not None:
                    decision = selection.decision
                    global_credited_goal_ids = selection.credited_goal_ids
                    if selection.goal_id:
                        chosen_goal = next(
                            (goal for goal in goals if goal.goal_id == selection.goal_id), None
                        )
                        if chosen_goal is not None:
                            best_goal = chosen_goal
                            self._committed_goal = chosen_goal.goal_id
            if loop_return_pending is not None:
                self._record_session_timeline("AUTO_CONTINUED", **loop_return_pending,
                                              next_goal_id=self._step_goal(best_goal))
                loop_return_pending = None
            primary_goal_id = (
                str(best_goal.goal_id) if best_goal is not None
                else str(getattr(self, "_committed_goal", "") or "")
            )
            attached_goal_ids = tuple(dict.fromkeys((
                *global_credited_goal_ids,
                *action_relevant_goal_ids(
                    goals, decision.skill, before, primary_goal_id=primary_goal_id,
                ),
            )))
            if audit_starting_page is None:
                audit_starting_page = before.page.value
                audit_starting_goal = best_goal.goal_id if best_goal is not None else None
                audit_starting_priority = float(best_goal.priority) if best_goal is not None else None
            runnable_rows = [
                {"goal_id": item[0].goal_id, "priority": float(item[0].priority)}
                for item in board
            ]
            selected_id = best_goal.goal_id if best_goal is not None else None
            selectable_ids = {goal.goal_id for goal in selectable_goals}
            rejected_rows = [
                {
                    "goal_id": item.goal_id,
                    "capability": item.capability,
                    "state": item.state,
                    "reason": item.reason,
                    "source": item.source,
                }
                for item in deferrals
            ]
            deferred_ids = {str(item.get("goal_id") or "") for item in rejected_rows}
            for goal in goals:
                if goal.goal_id in selectable_ids or goal.goal_id in deferred_ids:
                    continue
                rejected_rows.append({
                    "goal_id": goal.goal_id,
                    "capability": "",
                    "state": str(getattr(goal.status, "value", goal.status)),
                    # The operator's own reason when the policy refused it (POLICY_DISABLED_BY_USER
                    # vs POLICY_CATEGORY_DISABLED), so an audit can tell a standing prohibition from
                    # a paused category without reading the policy file itself.
                    "reason": (
                        self._policy_refusal(goal.goal_id) or "already_yielded_or_not_selectable"
                    ),
                    "source": "RUNTIME_SELECTION",
                })
            candidate_rows = [
                {"goal_id": goal.goal_id, "skill": str(skill),
                 "goal_status": str(getattr(goal.status, "value", goal.status)),
                 "priority": float(goal.priority)}
                for goal in goals for skill in goal.available_skills
            ]
            page_audit: dict[str, Any] = {
                "page": before.page.value,
                "confidence": float(before.confidence),
                "screenshot_path": str(before_path),
                "goal_id": best_goal.goal_id if best_goal is not None else None,
                "goal_priority": float(best_goal.priority) if best_goal is not None else None,
                "observations": {
                    "resources": before.resources,
                    "marches": [str(getattr(item, "value", item)) for item in before.marches],
                    "march_used": before.march_used,
                    "march_max": before.march_max,
                    "building": before.building,
                    "research": before.research,
                    "training": before.training,
                    "camps": before.camps,
                    "events": before.events,
                    "daily": before.daily,
                    "mail": before.mail,
                    "alliance": before.alliance,
                    "red_dots": before.red_dots,
                    "queues": before.queues,
                },
                "candidate_actions": candidate_rows,
                "rejected_actions": rejected_rows,
                "rejection_reasons": list(dict.fromkeys(str(item["reason"]) for item in rejected_rows)),
                "attempted_skill": None,
                "verifier_result": {"status": "NOT_ATTEMPTED", "reason": decision.reason},
                "scheduler": {
                    "runnable_goals": runnable_rows,
                    "selected_goal": selected_id,
                    "alternatives": [row["goal_id"] for row in runnable_rows if row["goal_id"] != selected_id],
                    "switch_task_possible": len(runnable_rows) > 1,
                    "wait_reason": decision.reason,
                    "deferred_goals": rejected_rows,
                },
            }
            audit_pages.append(page_audit)
            if not self._validation_skill_allowed(decision.skill):
                page_audit['verifier_result'] = {'status': 'NOT_ATTEMPTED',
                    'reason': 'VALIDATION_TARGET_SKILL_NOT_REACHED'}
                return finish('NO_RUNNABLE_VALIDATION_GOAL')
            page_audit["attempted_skill"] = decision.skill
            page_audit["attempted_reason"] = decision.reason
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
                            before = self._observe(recovery_path, latency=latency, phase="recovery")
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
                            before = self._observe(recovery_path, latency=latency, phase="recovery")
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
                page_audit["verifier_result"] = {"status": "NOT_ATTEMPTED", "reason": decision.reason}
                category, stop_state = state_for_stop_reason(
                    decision.reason, decision_skill=decision.skill, action_executed=False,
                )
                self._runtime(agent_state=stop_state.value, stop_category=category.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=decision.reason,
                              last_fatal_error=decision.reason if is_fatal_stop(decision.reason) else None)
                return finish(decision.reason)
            self._force_unknown_navigation_target = ""
            recovered_navigation = self._take_failed_navigation_retry(selected_id, before, allowed)
            if recovered_navigation is not None:
                decision = recovered_navigation
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

            rally_target = None
            if decision.skill in {"START_RALLY", "JOIN_RALLY"}:
                rally_target = (
                    rally_target_for_goal(
                        str(getattr(best_goal, "goal_id", "")),
                        getattr(best_goal, "evidence", None),
                    )
                    if best_goal is not None else None
                )
                # Rally clicks without an explicit/legacy Bear target are refused
                # by both recognizers and their target-specific verifiers.
                if rally_target is None:
                    rally_target = "UNKNOWN"

            # Bind the current frame and Goal target so the ADB fallback and MAA
            # LIST_DYNAMIC resolver apply one target identity to this observation.
            def resolve(semantic: str):
                if semantic == getattr(self, "_force_unknown_navigation_target", ""):
                    return self._unknown_navigation_target(semantic, before, before_path,
                                                           skill_id=decision.skill)
                point = self._resolve_semantic_target(
                    semantic,
                    before,
                    frame_path=before_path,
                    resource=planned_resource,
                    untried_intel_pins=untried_intel_pins,
                    rally_target=rally_target,
                )
                if point is not None:
                    return point
                return self._unknown_navigation_target(semantic, before, before_path,
                                                       skill_id=decision.skill)

            def verify_current_step(before_state: WorldState, after_state: WorldState):
                if decision.skill in {"START_RALLY", "JOIN_RALLY"}:
                    target = getattr(rally_target, "value", rally_target) or "UNKNOWN"
                    return _verify_rally_action(decision.skill, before_state, after_state, str(target))
                return self.VERIFIED_ATOMIC[decision.skill](before_state, after_state)

            # ---- GENERIC_SESSION_ENGINE_V1 -------------------------------------------
            #
            # The Goal and the role are already chosen (the Scheduler and the Brain ran above);
            # all that is left to decide is *how* this Goal does its work.  When the route
            # table says this Goal has a session, the session runs the Goal's internal sequence
            # -- several steps, one device lease, one budget -- and then this ``continue`` hands
            # the cycle straight back to the same Scheduler that chose it.  That is constraint
            # 8 ("Session 完成/Yield/失败后必须返回 Global Scheduler") implemented as the loop's
            # own existing edge, not as a new one.
            #
            # The hook sits HERE, after the decision and before the atomic step's own guards,
            # for three reasons:
            #   * the session must not be subject to the "this control resolved to nothing"
            #     guards below -- those are about repeating one failed atomic decision, and a
            #     session has not resolved anything yet;
            #   * it must not build the executor/router below -- the session's steps build
            #     their own through ``_session_execute_atomic``;
            #   * ``index < max_actions`` keeps one iteration of the run's budget for the
            #     return trip, so a session can never be the last thing a run does.
            #
            # A session's ending -- complete, yield OR failure -- is never a run ending.  The
            # failure of one Goal's internal sequence says nothing about the other Goals, and
            # the loop's next iteration re-arbitrates, which is the whole point of constraint 8.
            session_route = (session_adapters.route_for(selected_id, decision.skill)
                             if index < max_actions and not (getattr(best_goal, "evidence", {}) or {}).get("bootstrap_stage") else None)
            if session_route is not None:
                page_audit["session_route"] = {
                    "goal_id": selected_id, "adapter": session_route.adapter,
                    "step_budget": session_route.step_budget,
                    "time_budget_s": session_route.time_budget_s,
                    "lifecycle": session_route.lifecycle,
                }
                session_started = time.monotonic()
                session_result = self._run_goal_session(
                    route=session_route, index=index, run_id=run_id,
                    before=before, before_path=before_path, best_goal=best_goal,
                    latency=latency, page_audit=page_audit,
                    rally_target=rally_target, planned_resource=planned_resource,
                    attached_goal_ids=attached_goal_ids,
                )
                session_ms = (time.monotonic() - session_started) * 1000.0
                latency["session_ms"] = session_ms
                if session_result is not None:
                    if selected_id == 'AVOID_STAMINA_WASTE' and (best_goal.evidence or {}).get('stamina_sink') == 'GIANT_BEAST' and not session_result.completed:
                        self._giant_stamina_failed = True
                    metrics = dict(getattr(session_result, "metrics", {}) or {})
                    self._record_session_timeline("SESSION_ENDED",
                        session_id=session_result.session_id, goal_id=selected_id,
                        reason=session_result.reason, metrics=metrics)
                    page_audit["session_result"] = {
                        "session_id": session_result.session_id,
                        "lifecycle": session_result.lifecycle.value,
                        "outcome": session_result.outcome,
                        "reason": session_result.reason,
                        "steps": len(session_result.steps),
                        "verified": metrics.get("SESSION_VERIFIED_STEPS"),
                        # How much of the session was spent waiting on the client rather than
                        # acting.  Beside ``steps`` because the pair is the finding: ten steps
                        # with nine pending is a stalled wait, ten steps with none is work.
                        "still_pending": metrics.get("SESSION_STILL_PENDING"),
                        "episode_ids": list(session_result.episode_ids),
                        "yield_class": session_result.yield_class or None,
                        "failure": metrics.get("SESSION_FAILURE"),
                        "duration_ms": metrics.get("SESSION_DURATION_MS"),
                        "loop_metrics": {key: value for key, value in metrics.items()
                                         if key.startswith("LOOP_")},
                    }
                    page_audit["attempted_skill"] = decision.skill
                    page_audit["attempted_reason"] = (
                        f"session:{session_route.adapter}:{session_result.reason}")
                    page_audit["verifier_result"] = {
                        "status": "PASS" if session_result.completed else "SESSION_ENDED",
                        "ok": bool(session_result.completed),
                        "reason": session_result.reason,
                        "lifecycle": session_result.lifecycle.value,
                    }
                    page_audit["action_sent"] = bool(len(session_result.steps))
                    steps.append(LiveStep(index, decision, None, before, None, None))
                    # Only the snapshot's own declared fields are passed: ``update`` filters
                    # unknown keys out, so inventing ``session_*`` names here would look like
                    # reporting while changing nothing.  The session's facts ride on the audit
                    # row (``session_result``) and the narration, which is where a reader can
                    # actually find them.
                    self._runtime(
                        agent_state=AgentState.AUTO_RUNNING.value,
                        current_goal=self._step_goal(best_goal),
                        current_skill=decision.skill,
                        reason=(f"session {session_route.adapter} "
                                f"{session_result.lifecycle.value}:{session_result.reason}"),
                        next_action="return to the scheduler",
                        verifier="SESSION_ENGINE",
                    )
                    self._narrate_once(
                        f"session {session_result.session_id} [{session_route.adapter}] "
                        f"{session_result.lifecycle.value} {session_result.reason} "
                        f"steps={len(session_result.steps)} "
                        f"verified={metrics.get('SESSION_VERIFIED_STEPS')} "
                        f"{session_ms:.0f}ms -- returning to the scheduler"
                    )
                    if not session_result.completed and not (selected_id == 'AVOID_STAMINA_WASTE' and getattr(self,'_giant_stamina_failed',False)):
                        self._yield_to_next_goal(best_goal, deferrals, decision, session_result.reason)
                    if str(session_result.reason).startswith("SESSION_DOMAIN_STUCK"):
                        loop_return_pending = {"session_id": session_result.session_id,
                                               "goal_id": selected_id,
                                               "reason": session_result.reason}
                    continue
                # No result at all: the session could not be built.  Fall through to the
                # ordinary atomic path rather than ending the run on a routing problem.
                page_audit["session_result"] = {"lifecycle": "NOT_STARTED",
                                                "reason": "SESSION_COULD_NOT_BE_BUILT"}
                self._narrate_once(
                    f"session for {selected_id} could not be built; "
                    f"{decision.skill} runs as an ordinary step"
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
            planned_target = self._decision_target(decision)
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
            # The same refusal for a control that resolved to nothing -- no point, so nothing was
            # ever tried and nothing ever ran a verifier.
            #
            # Measured 2026-09-23, run ``20260923_140514_506593``: five consecutive CLOSE_POPUP
            # steps in three seconds, each for a *different* goal (CLEAR_INTEL, MAIL_ROUTINE,
            # DAILY_ACTIVITY_TARGET, CLAIM_EXPLORATION_IDLE, AUTO_DISCOVERY) and each the same
            # decision, because a named popup answers ``blocking_popup`` before every goal's own
            # route (``brain.py``:777).  Yielding to another goal therefore produced the identical
            # step once per goal, and the run ended only when there was no goal left to hand to.
            #
            # ``MAX_UNRESOLVED_ATTEMPTS`` is the bound, and it is not 1: each attempt resolves
            # against a freshly captured frame, and the reader this project trusts most is only
            # ~94% reliable per frame (measured on 245 加成总览 frames: 231 read the 实力详情 label,
            # 14 did not), so a second attempt is a real second chance rather than a repeat.
            if planned_target and planned_target in self._unresolved_controls:
                attempts, reason = self._unresolved_controls[planned_target]
                if attempts >= self.MAX_UNRESOLVED_ATTEMPTS:
                    # The handover is offered **once** per control: if the goal that takes the cycle
                    # asks for something else, the run continues with real work, which is why it is
                    # kept at all.  A second handover would buy another identical non-attempt.
                    if (
                        planned_target not in self._unresolved_handed_over
                        and index < max_actions
                        and self._yield_to_next_goal(
                            best_goal,
                            deferrals,
                            decision,
                            f"{planned_target} resolved to nothing {attempts} time(s) in this run "
                            f"({reason}); another goal gets the cycle once, and only if it asks for "
                            f"something else",
                        )
                    ):
                        self._unresolved_handed_over.add(planned_target)
                        continue
                    steps.append(LiveStep(index, decision, None, before, None, None))
                    return finish(reason)

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
                rally_target=rally_target,
            )
            started_at = time.monotonic()
            # ``decision`` was already made above and the backend router below
            # was built from it, so it is handed to the scheduler rather than
            # recomputed.  ``RuleBrain.decide`` mutates run-scoped state (the
            # free-stamina once-per-run flag), so a second call for the same
            # frame answers differently and the verifier then judges a skill the
            # step never ran.  See ``Scheduler.tick`` for the live evidence.
            latency["decision_ms"] = (time.monotonic() - selection_started) * 1000
            phase_started = time.monotonic()
            if self._scheduler is None:
                self._scheduler = Scheduler(
                    self.brain, self.registry, executor, self.candidate_pool,
                    global_state_store=getattr(self, "global_scheduler_state_store", None),
                )
            else:
                self._scheduler.executor = executor
            self._mark_bootstrap_attempt(best_goal)
            tick = self._scheduler.tick(before, decision)
            latency["scheduler_tick_ms"] = (time.monotonic() - phase_started) * 1000
            page_audit["attempted_skill"] = tick.decision.skill
            page_audit["attempted_reason"] = tick.decision.reason
            latency["maa_ms"] = (
                float(tick.execution.latency_ms)
                if tick.execution is not None and tick.execution.latency_ms is not None else None
            )
            self._runtime(last_action_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
            if tick.execution is not None and tick.execution.executed:
                # A real action ran, so whatever re-observation streak preceded it is over.
                role_refresh_ticks = 0
            if tick.execution is None or not tick.execution.executed:
                self._record_episode(
                    decision=tick.decision, before=before, execution=tick.execution,
                    after=None, verification=None, started_at=started_at,
                    step_id=index,
                    goal_id=self._step_goal(best_goal),
                    attached_goal_ids=attached_goal_ids,
                    goal_progress_by_id={goal_id: None for goal_id in attached_goal_ids},
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
                page_audit["verifier_result"] = {"status": "NOT_ATTEMPTED", "reason": str(reason)}
                if tick.execution is None or not tick.execution.executed:
                    page_audit["rejected_actions"].append({
                        "goal_id": selected_id,
                        "skill": tick.decision.skill,
                        "state": "REJECTED",
                        "reason": str(reason),
                        "source": "EXECUTOR",
                    })
                    page_audit["rejection_reasons"] = list(dict.fromkeys(
                        [*page_audit["rejection_reasons"], str(reason)]
                    ))
                # Recorded so the guard before the executor can refuse a *second* derivation of the
                # same control.  ``_failed_controls`` cannot serve here: nothing was tried, so no
                # verifier produced a verdict, and the six refusals this runtime names itself
                # (``_failure_type_from``) already show that "no point" and "failed" are two facts.
                unresolved = self._decision_target(tick.decision)
                if unresolved:
                    attempts, _last = self._unresolved_controls.get(unresolved, (0, ""))
                    self._unresolved_controls[unresolved] = (attempts + 1, str(reason))
                    # Derive the node the missing control needs, instead of waiting for a
                    # human to hand-write it. Only ever on the first failure: a second
                    # derivation would either repeat the same node or overwrite a good
                    # one with a worse crop, and neither is recoverable inside a run.
                    self._maybe_autogen_node(unresolved, str(tick.decision.skill or ""),
                                             attempts, reason)
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
                category, stop_state = state_for_stop_reason(
                    reason, decision_skill=tick.decision.skill, action_executed=False,
                )
                self._runtime(agent_state=stop_state.value, stop_category=category.value,
                              runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=reason,
                              last_fatal_error=reason if is_fatal_stop(reason) else None)
                return finish(tick.execution.error if tick.execution else "NO_EXECUTION")

            page_audit["action_sent"] = bool(tick.execution.executed)

            bear_reading = before.events.get("bear") if isinstance(before.events, dict) else None
            settle_policy = choose_settle_policy(
                decision.skill,
                goal=self._step_goal(best_goal) or "",
                bear_status=(
                    str(bear_reading.get("status") or "")
                    if isinstance(bear_reading, dict) else ""
                ),
                rally_list_visible=(
                    before.page is Page.ALLIANCE
                    and str(before.alliance.get("section") or "") == "RALLY_LIST"
                    and bool(before.alliance.get("rally_rows") or before.rally.get("rows"))
                ),
            )
            settle_limit = (
                min(max(0.0, self.settle_seconds), 0.75)
                if settle_policy.name == "P0_EVENT_FAST_MODE"
                else max(0.0, self.settle_seconds)
            )
            settle_first_wait = min(settle_policy.first_wait_s, settle_limit)
            settle_retry_wait = min(settle_policy.retry_wait_s, settle_limit)
            phase_started = time.monotonic()
            self.sleeper(settle_first_wait)
            latency["settle_first_wait_ms"] = (time.monotonic() - phase_started) * 1000
            phase_started = time.monotonic()
            after_path = self._capture_path(index, "after")
            latency["capture_ms"] = (latency.get("capture_ms") or 0.0) + (time.monotonic() - phase_started) * 1000
            if self._device_lost(self.device.screenshot, after_path):
                return finish(self._device_stop_reason)
            frame_changed, frame_change_fraction = FrameChangeProbe(before_path).changed(after_path)
            latency["settle_frame_change_fraction"] = frame_change_fraction
            latency["settle_retry_wait_ms"] = 0.0
            if not frame_changed and settle_retry_wait > 0.0:
                # The first post-action frame is still visually unchanged. Wait
                # once, then observe a fresh frame; never repeat the action.
                phase_started = time.monotonic()
                self.sleeper(settle_retry_wait)
                latency["settle_retry_wait_ms"] = (time.monotonic() - phase_started) * 1000
                phase_started = time.monotonic()
                retry_path = self._capture_path(index, "after", suffix="settle_retry")
                latency["capture_ms"] = (latency.get("capture_ms") or 0.0) + (time.monotonic() - phase_started) * 1000
                if self._device_lost(self.device.screenshot, retry_path):
                    return finish(self._device_stop_reason)
                after_path = retry_path
            latency["settle_ms"] = latency["settle_first_wait_ms"] + latency["settle_retry_wait_ms"]
            phase_started = time.monotonic()
            after = self._observe(after_path, latency=latency, phase="after")
            latency["reobserve_ms"] = (latency.get("reobserve_ms") or 0.0) + (time.monotonic() - phase_started) * 1000
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
                phase_started = time.monotonic()
                self.sleeper(settle_retry_wait)
                latency["settle_ms"] += (time.monotonic() - phase_started) * 1000
                recovery_path = self._capture_path(index, "after", suffix=f"payment_offer_closed_{offer_recovery}")
                if self._device_lost(self.device.screenshot, recovery_path):
                    return finish(self._device_stop_reason)
                after = self._observe(recovery_path, latency=latency, phase="recovery")
                if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                    after = replace(after, resource_target=planned_resource)
                after_path = recovery_path
            after = self._reject_a_dropped_digit(after)
            goals_after = self._record_goals(after, frame=after_path)
            phase_started = time.monotonic()
            verification = verify_current_step(before, after)
            page_audit["verifier_result"] = {
                "status": "PASS" if verification.ok else "FAIL",
                "ok": bool(verification.ok),
                "reason": verification.reason,
                "page_after": after.page.value,
            }
            latency["verifier_ms"] = (time.monotonic() - phase_started) * 1000
            for refresh in range(1, self.observation_retries + 1):
                # A known page can still be an intermediate animation/frame.
                # Re-observe when the action-specific verifier is not yet
                # satisfied, but never repeat the click whose result is merely
                # delayed. This handles slow MAP -> RESOURCE_DETAIL transitions.
                if verification.ok:
                    break
                phase_started = time.monotonic()
                self.sleeper(settle_retry_wait)
                latency["settle_ms"] += (time.monotonic() - phase_started) * 1000
                refresh_path = self._capture_path(index, "after", suffix=f"refresh_{refresh}")
                if self._device_lost(self.device.screenshot, refresh_path):
                    return finish(self._device_stop_reason)
                after = self._observe(refresh_path, latency=latency, phase="refresh")
                if after.page.value in {"MAP", "RESOURCE_DETAIL", "MARCH"}:
                    after = replace(after, resource_target=planned_resource)
                after = self._reject_a_dropped_digit(after)
                goals_after = self._record_goals(after, frame=refresh_path)
                phase_started = time.monotonic()
                verification = verify_current_step(before, after)
                page_audit["verifier_result"] = {
                    "status": "PASS" if verification.ok else "FAIL",
                    "ok": bool(verification.ok),
                    "reason": verification.reason,
                    "page_after": after.page.value,
                }
                latency["verifier_ms"] = (latency.get("verifier_ms") or 0.0) + (time.monotonic() - phase_started) * 1000
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
            phase_started = time.monotonic()
            delivery_initial_frame = str(after_path)
            after, after_path, delivery, verification, click_result = self._retry_semantic_click(
                decision=decision, before=before, before_path=before_path,
                after=after, after_path=after_path, execution=tick.execution,
                verify=verify_current_step, resource=planned_resource,
                rally_target=rally_target, index=index, settle=settle_retry_wait, latency=latency,
            )
            tick = replace(tick, execution=delivery)
            latency["semantic_click_retry_ms"] = (time.monotonic() - phase_started) * 1000
            latency["semantic_click_retries"] = click_result.retries if click_result else 0
            if click_result and click_result.observation.frame != delivery_initial_frame:
                goals_after = self._record_goals(after, frame=after_path)
            elif click_result and click_result.retries:
                goals_after = self._record_goals(after, frame=after_path)
            page_audit["verifier_result"] = {
                "status": "PASS" if verification.ok else "FAIL", "ok": bool(verification.ok),
                "reason": verification.reason, "page_after": after.page.value,
            }
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
            goal_progress_by_id = {
                attached_id: progress_moved(self._goal_meters, goals_after, attached_id)
                for attached_id in attached_goal_ids
            }
            completed_goal_ids = newly_completed_goal_ids(
                goals, goals_after, attached_goal_ids,
            )
            progress = goal_progress_by_id.get(step_goal)
            for attached_id, attached_progress in goal_progress_by_id.items():
                row = goal_utility.entry(self._fairness, attached_id)
                if attached_progress is True:
                    row.no_progress_streak = 0
                elif attached_progress is False:
                    row.no_progress_streak += 1
            phase_started = time.monotonic()
            self._record_episode(
                decision=tick.decision, before=before, execution=tick.execution,
                after=after, verification=verification, started_at=started_at,
                step_id=index,
                goal_id=step_goal,
                attached_goal_ids=attached_goal_ids,
                goal_progress_by_id=goal_progress_by_id,
                completed_goal_ids=completed_goal_ids,
                # The verifier passed means the action landed.  This says whether the
                # *goal* moved, and the two are not the same statement: 58 episodes
                # passed their verifier while stamina sat at 457 (2026-09-18).
                goal_progress=progress,
                before_screenshot=before_path, after_screenshot=after_path,
            )
            latency["episode_write_ms"] = (time.monotonic() - phase_started) * 1000
            latency["ocr_ms"] = max(0.0, float(getattr(ocr_service, "timing_total_ms", 0.0)) - ocr_before_ms)
            latency["parse_ms"] = max(
                0.0, float(getattr(ocr_service, "timing_parse_ms", 0.0)) - parse_before_ms
            )
            latency["total_step_ms"] = (time.monotonic() - latency_started) * 1000
            if self.latency_trace_path is not None:
                action_latency.append(self.latency_trace_path, {
                    **latency,
                    "episode_id": self.capture_dir.name,
                    "step_id": index,
                    "repo_revision": self.code_revision,
                    "role_id": self.role_id,
                    "goal": step_goal or "",
                    "skill": decision.skill,
                    "page_before": before.page.value,
                    "page_after": after.page.value,
                    "success": bool(verification.ok),
                    "failure_type": "" if verification.ok else verification.reason,
                    "settle_policy": settle_policy.name,
                    "settle_frame_change_fraction": latency.get("settle_frame_change_fraction"),
                    "ocr_calls": int(getattr(ocr_service, "timing_calls", 0)) - ocr_before_calls,
                    "ocr_cache_hits": int(getattr(ocr_service, "timing_cache_hits", 0)) - ocr_before_hits,
                })
            previous_action_end = time.monotonic()
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
                focused_camp = {
                    "TAP_FOCUSED_TRAINING_CAMP_SHIELD": "SHIELD",
                    "TAP_FOCUSED_TRAINING_CAMP_LANCER": "LANCER",
                    "TAP_FOCUSED_TRAINING_CAMP_MARKSMAN": "MARKSMAN",
                }.get(decision.skill)
                if (
                    focused_camp is not None
                    and (click_result is None or click_result.retries == 0)
                    and focused_camp not in training_focus_retry_used
                    and index < max_actions
                    and best_goal is not None
                    and best_goal.goal_id == f"{focused_camp}_CAMP_TRAINING"
                    # Same retired name as above: the committed goal IS this route's
                    # continuation identity, so ask it rather than a name nothing sets.
                    and self._committed_goal == best_goal.goal_id
                    and verification.reason == "FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN"
                    and can_reobserve_focused_training_camp_after_nonmenu_tap(
                        before, after, camp=focused_camp
                    ).ok
                ):
                    point = (before.training or {}).get("camp_focus_tap_norm")
                    if isinstance(point, (tuple, list)) and len(point) == 2:
                        training_focus_retry_used.add(focused_camp)
                        pending_training_focus_retry = {
                            "camp": focused_camp,
                            "goal_id": best_goal.goal_id,
                            "role_id": self._calendar_role_id(),
                            "reference_frame": str(before_path),
                            "point": [float(point[0]), float(point[1])],
                        }
                        self._runtime(
                            agent_state=AgentState.GOAL_RUNNING.value,
                            reason=f"{focused_camp.lower()}_tap_dismissed_or_selected_without_action_bar",
                            next_action="reobserve_same_home_view_then_allow_one_bounded_camp_tap",
                            verifier=verification.reason,
                        )
                        continue
                # A located navigation control can still fail its real verifier.
                # After existing settle/retry recovery, give this selected Goal
                # one fresh model-grounded attempt, retaining its original Skill
                # preconditions and verifier. Other Goals and hard events keep
                # their normal Scheduler arbitration on the next iteration.
                navigation = (decision.skill.startswith("OPEN_")
                              or decision.skill.startswith("TAP_FOCUSED_TRAINING_CAMP_"))
                semantic = (tick.execution.action.target or "") if tick.execution is not None else ""
                retry_key = (self._calendar_role_id(), self._step_goal(best_goal), semantic)
                if (navigation and semantic and best_goal is not None and index < max_actions
                        and before.page == after.page
                        and retry_key not in self._navigation_unknown_attempted
                        and not is_fatal_stop(verification.reason)):
                    self._navigation_unknown_attempted.add(retry_key)
                    self._navigation_unknown_pending[retry_key[:2]] = {
                        "skill": decision.skill, "semantic": semantic, "page": after.page,
                        "reason": verification.reason,
                    }
                    self._runtime(next_action="fresh_unknown_navigation_if_same_goal_selected",
                                  verifier=verification.reason)
                    continue
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
                self._runtime(agent_state=AgentState.DEGRADED.value,
                              stop_category=StopCategory.SYSTEM_FAILURE.value,
                              runtime_thread_alive=False,
                              scheduler_loop_alive=False, stop_reason=verification.reason)
                return finish(verification.reason)
            if decision.skill == "DISPATCH_MARCH" and self.resource_rotation is not None:
                self.resource_rotation.completed(planned_resource)
            if decision.skill == stop_after_skill:
                self._runtime(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                              scheduler_loop_alive=False, stop_reason="TARGET_SKILL_VERIFIED",
                              stop_category=StopCategory.COMPLETED.value)
                return finish("TARGET_SKILL_VERIFIED")

        self._runtime(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                      scheduler_loop_alive=False, stop_reason="MAX_ACTIONS_REACHED",
                      stop_category=StopCategory.COMPLETED.value)
        return finish("MAX_ACTIONS_REACHED")
