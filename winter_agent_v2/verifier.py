from __future__ import annotations

from .models import MarchState, Page, VerificationResult, WorldState
from .beast_targets import is_dispatchable, lookup_by_name, refused_by_evidence


def verify_event_points_increased(before: WorldState, after: WorldState) -> VerificationResult:
    before_goal = before.events.get("minimum_guarantee", {})
    after_goal = after.events.get("minimum_guarantee", {})
    before_points, after_points = before_goal.get("current_points"), after_goal.get("current_points")
    same_event = before_goal.get("event_id") == after_goal.get("event_id")
    ok = same_event and isinstance(before_points, int) and isinstance(after_points, int) and after_points > before_points
    return VerificationResult(ok, "OK" if ok else "EVENT_POINT_GAIN_FAILED", {
        "event_id": after_goal.get("event_id"), "points_before": before_points,
        "points_after": after_points,
        "verified_gain": after_points - before_points if isinstance(before_points, int) and isinstance(after_points, int) else None,
    })


def verify_intel_list_read(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.INTEL and after.page is Page.INTEL and after.intel.get("list_read") is True \
        and after.intel.get("status") in {"AVAILABLE", "CLAIMABLE", "NOT_AVAILABLE", "IN_PROGRESS"}
    return VerificationResult(ok, "OK" if ok else "INTEL_LIST_UNKNOWN", {
        "status": after.intel.get("status"), "available_count": after.intel.get("available_count"),
        "mission_type": after.intel.get("mission_type"),
    })


def verify_march_recall_dialog_open(before: WorldState, after: WorldState) -> VerificationResult:
    """Tapping an active march row opens the recall confirmation dialog.

    Live measurement (2026-09-14): on a map frame with six gathering marches,
    tapping the first march-list row opened a dialog titled 召回 with a
    「您确定要召回部队吗？」 body and 取消 / 确定 buttons.  The tap target is the
    row itself, so the pre-state must show at least one active march and a
    closed resource-search panel (the search panel covers the march list).
    """
    before_ok = (
        before.page is Page.MAP
        and before.march_used is not None
        and before.march_used >= 1
        and not before.resource_search_open
    )
    after_ok = after.page is Page.POPUP and after.popup == "MARCH_RECALL"
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "RECALL_DIALOG_NOT_OPEN",
        {"march_used": before.march_used, "search_open": before.resource_search_open, "popup": after.popup},
    )


def verify_march_recalled(before: WorldState, after: WorldState) -> VerificationResult:
    """A recall is proven by a gathering march becoming a returning one.

    The skill definition originally declared ``NORMAL_IDLE_SLOT_INCREASED``,
    which is wrong for this client: measured live on 2026-09-14, confirming the
    recall left ``march_used`` at 6/6 and turned the recalled row into 返回中.
    The slot only frees when the troops arrive, so an idle-slot increase right
    after the tap would have been a false expectation and the verifier would
    have failed a correct recall.  The proven signal is the state transition.
    """
    dialog_ok = before.page is Page.POPUP and before.popup == "MARCH_RECALL"
    transition = MarchState.RETURNING in after.marches and MarchState.RETURNING not in before.marches
    after_ok = after.page is Page.MAP and transition
    ok = dialog_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "MARCH_RECALL_NOT_PROVEN",
        {
            "dialog_open": dialog_ok,
            "returning_before": MarchState.RETURNING in before.marches,
            "returning_after": MarchState.RETURNING in after.marches,
            "march_used_before": before.march_used,
            "march_used_after": after.march_used,
        },
    )


def verify_stamina_sources_open(before: WorldState, after: WorldState) -> VerificationResult:
    """Tapping the 领主体力 gauge on the map opens the 获取更多 panel.

    Measured live on 2026-09-14: a single tap on the gauge (px 49,110 on
    720x1280) opened the panel, which lists every stamina source and marks the
    free one with a bare 领取 and no price.
    """
    before_ok = before.page is Page.MAP and not before.resource_search_open
    after_ok = after.page is Page.POPUP and after.popup == "GET_MORE_STAMINA"
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "STAMINA_SOURCES_NOT_OPEN",
        {"before_page": before.page.value, "after_popup": after.popup},
    )


def verify_free_stamina_claimed(before: WorldState, after: WorldState) -> VerificationResult:
    """Claiming the free stamina gift is proven from the panel's own readout.

    Measured live on 2026-09-14: the panel read ``200/200`` with the 领取 button
    present, and after one tap on 领取 it read ``350/200`` with the button
    replaced by 「下次补给」.  Both signals are accepted, because the second one
    also covers a gift delivered to the warehouse (no immediate stamina
    change); the tap itself can never spend diamonds, since the paid rows carry
    their own 「购买并使用 💎300」 control which this verifier does not touch.
    """
    before_ok = (
        before.page is Page.POPUP
        and before.popup == "GET_MORE_STAMINA"
        and before.stamina.get("free_claim_available") is True
    )
    before_value = before.stamina.get("current")
    after_value = after.stamina.get("current")
    increased = (
        isinstance(before_value, int) and isinstance(after_value, int) and after_value > before_value
    )
    control_gone = (
        after.page is Page.POPUP
        and after.popup == "GET_MORE_STAMINA"
        and after.stamina.get("free_claim_available") is False
    )
    ok = before_ok and (increased or control_gone)
    return VerificationResult(
        ok,
        "OK" if ok else "FREE_STAMINA_CLAIM_NOT_PROVEN",
        {
            "before_value": before_value,
            "after_value": after_value,
            "increased": increased,
            "claim_control_gone": control_gone,
        },
    )


def verify_popup_closed(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and bool(before.popup)
    closed = after.known and after.page is not Page.POPUP and after.popup is None
    ok = before_ok and closed
    return VerificationResult(
        ok,
        "OK" if ok else "POPUP_CLOSE_NOT_PROVEN",
        {"before_popup": before.popup, "after_page": after.page.value, "after_popup": after.popup},
    )


def verify_duplicate_target_cancelled(before: WorldState, after: WorldState) -> VerificationResult:
    """Cancel the duplicate-target question and leave the search panel ready.

    Sending anyway would spend a march on a node another of our teams already
    holds, so the reviewed policy is to cancel and let the next search offer a
    fresh node.  Proof is the dialog being gone while the resource-search
    panel is still open and still configured for the same resource.
    """
    before_ok = before.page is Page.POPUP and before.popup == "DUPLICATE_TARGET"
    dialog_gone = after.known and after.page is Page.MAP and after.resource_search_open
    still_configured = after.resource_selected in {"MEAT", "WOOD", "COAL", "IRON"}
    ok = before_ok and dialog_gone and still_configured
    return VerificationResult(
        ok,
        "OK" if ok else "DUPLICATE_TARGET_CANCEL_NOT_PROVEN",
        {
            "verified_dialog_before": before_ok,
            "search_panel_restored": dialog_gone,
            "resource_still_selected": after.resource_selected,
        },
    )


def verify_camp_menu_reobserved(before: WorldState, after: WorldState) -> VerificationResult:
    """Training-route Stage A: re-observe while the camp's radial menu draws.

    Measured 2026-09-17 17:45 GMT+8 (open issue #28, and the frames under
    ``dataset/raw/control_panel/runtime_training/20260917_train_homefix/``).  After
    ``NAVIGATE_INFANTRY_CAMP`` the client sits on HOME with the infantry camp
    highlighted and a large tutorial finger over it, and the radial menu is **not**
    drawn yet.  Tapping the camp in that state moved the client to the MAP
    (``step_004_after_refresh_2`` is the world map), which is why the route must wait
    instead of tapping.

    Nothing is sent, so the only honest expectations are:

      * the client is still on HOME, and
      * the camp is still highlighted (menu not drawn) or the menu has since drawn.

    A wait that ends on the MAP is precisely the failure this guards against, so it
    must never be recorded as a successful wait.
    """
    before_ok = (
        before.page is Page.HOME
        and before.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED"
    )
    still_highlighted = (
        after.page is Page.HOME
        and after.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED"
    )
    menu_drawn = after.page is Page.HOME and after.training.get("menu_open") is True
    ok = before_ok and (still_highlighted or menu_drawn)
    return VerificationResult(
        ok,
        "OK" if ok else "CAMP_MENU_REOBSERVE_NOT_PROVEN",
        {
            "before_highlighted": before_ok,
            "still_highlighted": still_highlighted,
            "menu_drawn": menu_drawn,
            "page_after": after.page.value,
        },
    )


def verify_environmental_wait(before: WorldState, after: WorldState) -> VerificationResult:
    """Confirm an environment wait changed nothing on the client.

    WAIT is a deliberate no-op: the maintenance window or loading splash can
    only resolve on its own.  Because no input is sent, the only honest
    expectation is that the client was left untouched — the same environmental
    page (or a naturally advanced one, e.g. loading -> home) with no popup the
    wait could have created.  A page that became UNKNOWN means the observation
    failed, which must not be reported as a successful wait.
    """
    environmental = {Page.MAINTENANCE, Page.LOADING}
    before_ok = before.page in environmental
    after_ok = after.page in environmental or after.page in {Page.HOME, Page.MAP}
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "ENVIRONMENTAL_WAIT_NOT_PROVEN",
        {"environmental_before": before_ok, "page_after": after.page.value},
    )


def verify_resource_level_relaxed(before: WorldState, after: WorldState) -> VerificationResult:
    """Prove the level filter actually moved down by exactly one step.

    The search must remain open and configured for the same resource, and the
    measured slider level must be exactly one below the level read before the
    tap.  Anything else (panel closed, level unchanged, level jumped, or level
    unreadable) is not proof, so the loop stops instead of tapping blindly.
    Level 1 is the floor: there the minus control is greyed out, so a further
    relax request can never be satisfied and must not be reported as success.
    """
    panel_open = before.page is Page.MAP and before.resource_search_open
    panel_still_open = after.page is Page.MAP and after.resource_search_open
    same_resource = before.resource_selected is not None and after.resource_selected == before.resource_selected
    measurable = before.resource_level is not None and after.resource_level is not None
    lowered = measurable and after.resource_level == before.resource_level - 1
    ok = panel_open and panel_still_open and same_resource and lowered
    if not ok and before.resource_level == 1:
        reason = "RESOURCE_LEVEL_ALREADY_MINIMUM"
    elif ok:
        reason = "OK"
    else:
        reason = "RESOURCE_LEVEL_RELAX_NOT_PROVEN"
    return VerificationResult(
        ok,
        reason,
        {
            "panel_open_before": panel_open,
            "panel_open_after": panel_still_open,
            "resource_preserved": same_resource,
            "level_before": before.resource_level,
            "level_after": after.resource_level,
        },
    )


def verify_march_count_readable(before: WorldState, after: WorldState) -> VerificationResult:
    """Prove the march capacity became readable without leaving the map.

    ``CHECK_MARCH`` taps nothing -- its action is an ``OBSERVE`` -- and exists
    only because the brain cannot plan march-dependent work while the counter is
    unread (``world.idle_marches is None``).  Its whole job is to look again.

    It was selected by the brain but absent from ``VERIFIED_ATOMIC``, and
    ``runtime.py`` refuses any skill outside that map, so every run that reached
    this state died with ``SKILL_NOT_ENABLED_FOR_LIVE_LOOP`` -- an integration
    gap reported as the outcome of a real session.  That is the same mislabelling
    class as 0ax and 0ba, one layer further in: the loop blamed the run for a
    wiring hole.

    It matters beyond the wording.  The recorded reason ``march_used`` goes
    missing is that an overlay hides the counter; when the overlay clears, the
    next frame reads it.  Today the loop cannot survive long enough to take that
    frame, so a transient occlusion ends the run -- and the gather workflow,
    which needs a free march, never starts at all (measured 2026-09-15: three
    ``GATHER_RESOURCE`` closures all died on step 1 here, which is why
    ``START_GATHER`` has never once executed on MAA).

    The honest claim is narrow: still on the map, and the count is now readable.
    Neither half is assumed -- an unread count stays a failure, reported as
    ``MARCH_COUNT_NOT_READ`` rather than as a fabricated success.
    """
    stayed = before.page is Page.MAP and after.page is Page.MAP
    readable = after.march_used is not None
    ok = stayed and readable
    return VerificationResult(
        ok,
        "OK" if ok else "MARCH_COUNT_NOT_READ",
        {
            "stayed_on_map": stayed,
            "march_used_before": before.march_used,
            "march_used_after": after.march_used,
            "march_max_after": after.march_max,
        },
    )


def verify_safe_back(before: WorldState, after: WorldState) -> VerificationResult:
    search_closed = before.page is Page.MAP and before.resource_search_open and after.page is Page.MAP and not after.resource_search_open
    page_returned = before.page not in {Page.MAP, Page.POPUP} and after.page is not before.page and after.known
    popup_closed = before.page is Page.POPUP and after.page is not Page.POPUP
    ok = search_closed or page_returned or popup_closed
    return VerificationResult(ok, "OK" if ok else "SAFE_BACK_NOT_PROVEN", {"search_closed":search_closed, "page_returned":page_returned, "popup_closed":popup_closed, "before_page":before.page.value, "after_page":after.page.value})


def verify_left_foreign_layer(before: WorldState, after: WorldState) -> VerificationResult:
    """Did closing a sub-layer another goal owned actually move the client off it?

    The second exit of ``Brain._leave_foreign_page_once``.  Most panels answer one Back,
    and ``verify_safe_back`` proves it because the page changes.  Not every layer does: the
    alliance chest layer was measured on 2026-09-21 leaving the client exactly where it
    started --

        before  page ALLIANCE  ->  PRESS_BACK  ->  after  page ALLIANCE  (confidence 0.98)
        verifier  SAFE_BACK_NOT_PROVEN

    -- and that layer's own exit is the X the client draws in its corner, not a Back.  The
    close it needs cannot be verified by ``verify_popup_closed``: that verifier's own
    precondition is ``before.page is Page.POPUP`` (``before_ok = ... bool(before.popup)``),
    and a sub-page of ALLIANCE is not POPUP, so a close that worked perfectly would still
    have answered ``POPUP_CLOSE_NOT_PROVEN``.  That is the same trap the shared-reward
    branch records for the identical reason: a close is bound to the verifier that matches
    what it is closing.

    So the statement this verifier proves is deliberately the weaker, true one: the client
    left the layer it was on.  ``after.known`` is required, because a page that could not be
    read afterwards is not evidence of movement -- it is evidence of nothing, and treating
    it as success is how a dead end becomes a loop.  ``before.page`` is required to be a
    definite page for the same reason: with an UNKNOWN start, ``is not before.page`` would
    be satisfied by any two unknowns.

    Measured separation, 2026-09-21: the frame that Back could not move reads ALLIANCE both
    before and after; every frame behind the close (HOME, MAP) reads a different known page.
    """
    definite_start = before.known and before.page not in {Page.UNKNOWN, Page.POPUP}
    moved = after.known and after.page is not before.page
    ok = definite_start and moved
    return VerificationResult(
        ok,
        "OK" if ok else "FOREIGN_LAYER_NOT_LEFT",
        {
            "definite_start": definite_start,
            "moved": moved,
            "before_page": before.page.value,
            "after_page": after.page.value,
            "after_known": after.known,
        },
    )


def verify_offline_rewards_claimed(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and before.popup == "WELCOME_BACK_OFFLINE" and before.daily.get("offline_rewards") == "CLAIMABLE"
    after_ok = after.page is Page.HOME and after.popup is None
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "OFFLINE_REWARD_CLAIM_NOT_PROVEN", {"verified_dialog_before": before_ok, "home_after": after_ok})


def verify_open_daily(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and after.page is Page.DAILY
    return VerificationResult(ok, "OK" if ok else "OPEN_DAILY_NOT_PROVEN", {"before_home": before.page is Page.HOME, "after_daily": after.page is Page.DAILY})


def verify_daily_tab_selected(before: WorldState, after: WorldState) -> VerificationResult:
    """The panel now shows the 每日任务 tab, read as a drawn state.

    `OPEN_DAILY` lands on the panel's first tab (章节任务) while the page classifier calls
    the page DAILY from the string on the tab bar, so every daily skill was reading the
    wrong tab's content.  The two states are distinguishable in the frames themselves
    (unselected = dark blue pill, selected = light pill; measured over 3490 corpus frames
    they match 4 and 1 frames, all of them live panel frames from 2026-09-16), so this is
    an independent observation of the client rather than a restatement of the action.
    """
    before_ok = before.page is Page.DAILY and before.daily.get("tab") == "NOT_TASKS"
    after_ok = after.page is Page.DAILY and after.daily.get("tab") == "TASKS"
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "DAILY_TAB_NOT_SELECTED",
                              {"before_on_another_tab": before_ok, "after_on_daily_tab": after_ok,
                               "before_tab": before.daily.get("tab"), "after_tab": after.daily.get("tab")})


def verify_open_alliance_gifts(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.ALLIANCE and before.alliance.get("section") == "HOME"
    after_ok = after.page is Page.ALLIANCE and after.alliance.get("section") == "GIFTS"
    return VerificationResult(before_ok and after_ok, "OK" if before_ok and after_ok else "OPEN_ALLIANCE_GIFTS_NOT_PROVEN", {"alliance_home_before": before_ok, "gifts_after": after_ok})


def verify_power_overview_open(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and after.page is Page.POPUP and after.popup == "POWER_OVERVIEW"
    return VerificationResult(ok, "OK" if ok else "POWER_OVERVIEW_NOT_PROVEN", {"home_before": before.page is Page.HOME, "overview_after": after.popup == "POWER_OVERVIEW"})


def verify_power_details_open(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.POPUP and before.popup == "POWER_OVERVIEW" and after.page is Page.POPUP and after.popup == "POWER_DETAILS"
    return VerificationResult(ok, "OK" if ok else "POWER_DETAILS_NOT_PROVEN", {"overview_before": before.popup == "POWER_OVERVIEW", "details_after": after.popup == "POWER_DETAILS"})


def verify_infantry_camp_highlighted(before: WorldState, after: WorldState) -> VerificationResult:
    arrived = after.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED" or after.training.get("menu_open") is True
    ok = before.page is Page.POPUP and before.popup == "POWER_DETAILS" and after.page is Page.HOME and arrived
    return VerificationResult(ok, "OK" if ok else "INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN", {"power_details_before": before.popup == "POWER_DETAILS", "highlight_after": after.training.get("navigation"), "menu_open_after": after.training.get("menu_open")})


def verify_infantry_camp_selected(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED" and after.page is Page.HOME and after.training.get("menu_open") is True
    return VerificationResult(ok, "OK" if ok else "INFANTRY_CAMP_MENU_NOT_PROVEN", {"highlight_before": before.training.get("navigation"), "menu_after": after.training.get("menu_open")})


def verify_training_page_open(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and before.training.get("menu_open") is True and after.page is Page.TRAINING
    return VerificationResult(ok, "OK" if ok else "TRAINING_PAGE_NOT_PROVEN", {"menu_before": before.training.get("menu_open"), "training_after": after.page is Page.TRAINING})


# The 科技研究 route, hop for hop the same shape as the training one above.  The route
# itself was measured on 2026-09-04 (knowledge/skills/RESEARCH_RESEARCH.md line 38);
# these two verifiers are the ones it was missing, which is why the goal could not move.
def verify_research_lab_focused(before: WorldState, after: WorldState) -> VerificationResult:
    arrived = after.research.get("menu_open") is True
    ok = before.page is Page.POPUP and before.popup == "POWER_DETAILS" and after.page is Page.HOME and arrived
    return VerificationResult(ok, "OK" if ok else "RESEARCH_LAB_HIGHLIGHT_NOT_PROVEN", {"power_details_before": before.popup == "POWER_DETAILS", "menu_open_after": after.research.get("menu_open")})


def verify_research_page_open(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and before.research.get("menu_open") is True and after.page is Page.RESEARCH
    return VerificationResult(ok, "OK" if ok else "RESEARCH_PAGE_NOT_PROVEN", {"menu_before": before.research.get("menu_open"), "research_after": after.page is Page.RESEARCH})


def verify_ally_gift_claim_feedback(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.ALLIANCE and before.alliance.get("section") == "GIFTS" and before.alliance.get("tab") == "ALLY_GIFT" and before.alliance.get("status") == "CLAIMABLE"
    reward_ok = after.page is Page.POPUP and after.popup == "GENERIC_REWARD"
    return VerificationResult(before_ok and reward_ok, "OK" if before_ok and reward_ok else "ALLY_GIFT_REWARD_FEEDBACK_NOT_PROVEN", {"claimable_before": before_ok, "reward_after": reward_ok})


def verify_alliance_reward_dismissed(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and before.popup == "GENERIC_REWARD"
    after_ok = after.page is Page.ALLIANCE and after.alliance.get("section") == "GIFTS"
    return VerificationResult(before_ok and after_ok, "OK" if before_ok and after_ok else "ALLIANCE_REWARD_DISMISS_NOT_PROVEN", {"reward_before": before_ok, "gifts_after": after_ok})


def verify_daily_claim_feedback(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.DAILY and before.daily.get("status") == "CLAIMABLE"
    reward_ok = after.page is Page.POPUP and (after.popup == "GENERIC_REWARD" or (after.popup == "DAILY_REWARD" and after.daily.get("claim_feedback") is True))
    return VerificationResult(before_ok and reward_ok, "OK" if before_ok and reward_ok else "DAILY_REWARD_FEEDBACK_NOT_PROVEN", {"claimable_before": before_ok, "reward_visible": reward_ok})


def verify_daily_reward_advanced(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and before.popup in {"DAILY_REWARD", "GENERIC_REWARD"}
    advanced = (after.page is Page.POPUP and after.popup in {"DAILY_REWARD", "GENERIC_REWARD"}) or after.page is Page.DAILY
    return VerificationResult(before_ok and advanced, "OK" if before_ok and advanced else "DAILY_REWARD_ADVANCE_NOT_PROVEN", {"reward_before": before_ok, "next_reward_or_daily": advanced})


def verify_intel_reward_dismissed(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and before.popup in {"INTEL_REWARD", "GENERIC_REWARD"}
    restored = after.page is Page.INTEL and after.popup is None
    ok = before_ok and restored
    return VerificationResult(
        ok,
        "OK" if ok else "INTEL_REWARD_DISMISS_NOT_PROVEN",
        {"before_reward": before_ok, "after_intel": restored, "after_page": after.page.value},
    )


INTEL_MISSION_POPUPS = frozenset({
    "INTEL_BEAST_MISSION",
    "INTEL_RESCUE_SURVIVORS_MISSION",
    "INTEL_HERO_JOURNEY",
    "INTEL_MASTER_BOUNTY",
})


def verify_intel_pin_opened(before: WorldState, after: WorldState) -> VerificationResult:
    """Tapping a mission pin opens that mission's card.

    The intel board is a pin map (live 2026-09-14/15): the card does not exist
    until a pin is tapped, so the pre-state cannot name a mission type - that is
    the whole reason this skill exists.  What it can require is a *positive
    sighting* of the board: the pin detector saw at least one pin.  The
    post-state must be one of the four reviewed mission cards; a tap that lands
    on snow leaves the page on INTEL and is reported as not proven, never as a
    success.

    A BLOCKED card (大师悬赏, power 189M) still counts as opened: the tap did
    reach the mission, and the brain is the layer that decides to back out.
    """
    before_ok = before.page is Page.INTEL and int(before.intel.get("pins") or 0) > 0
    after_ok = after.page is Page.POPUP and after.popup in INTEL_MISSION_POPUPS
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "INTEL_PIN_CARD_NOT_OPENED", {
        "before_pins": before.intel.get("pins"),
        "before_status": before.intel.get("status"),
        "after_page": after.page.value,
        "after_popup": after.popup,
    })


def verify_intel_mission_selected(before: WorldState, after: WorldState) -> VerificationResult:
    expected = {"BEAST": "INTEL_BEAST_10", "FIREBEAST": "INTEL_FIREBEAST_10"}
    mission_type = before.intel.get("mission_type")
    before_ok = before.page is Page.INTEL and before.intel.get("status") == "AVAILABLE" and mission_type in expected
    opened = after.page is Page.POPUP and after.popup == "INTEL_BEAST_MISSION" and after.intel.get("mission_type") == mission_type and after.intel.get("mission_id") == expected.get(mission_type)
    ok = before_ok and opened
    return VerificationResult(ok, "OK" if ok else "INTEL_MISSION_SELECTION_NOT_PROVEN", {"before_available":before_ok,"mission_dialog":opened})


def verify_intel_target_open(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and before.popup == "INTEL_BEAST_MISSION"
    expected = {"INTEL_BEAST_10": 22, "INTEL_FIREBEAST_10": 20}
    mission_id = before.intel.get("mission_id")
    target = after.page is Page.BEAST and after.beast.get("mission_id") == mission_id and after.beast.get("level") == expected.get(mission_id) and after.beast.get("available") is True
    ok = before_ok and target
    return VerificationResult(ok, "OK" if ok else "INTEL_BEAST_TARGET_NOT_PROVEN", {"mission_dialog":before_ok,"target":target})


def verify_intel_beast_march_open(before: WorldState, after: WorldState) -> VerificationResult:
    expected = {"INTEL_BEAST_10": 22, "INTEL_FIREBEAST_10": 20}
    mission_id = before.beast.get("mission_id")
    target = before.page is Page.BEAST and before.beast.get("level") == expected.get(mission_id) and before.beast.get("available") is True
    # The formation page does not repeat the target level. Its independent
    # safety fact is the green, current-client "victory assured" state.
    march = after.page is Page.MARCH and after.beast.get("victory_assured") is True
    ok = target and march
    return VerificationResult(ok, "OK" if ok else "INTEL_BEAST_MARCH_NOT_PROVEN", {"target":target,"victory_assured":march})


def verify_intel_beast_dispatch(before: WorldState, after: WorldState) -> VerificationResult:
    assured = before.page is Page.MARCH and before.beast.get("victory_assured") is True
    active = after.page is Page.MAP and any(state in {MarchState.MARCHING, MarchState.RETURNING} for state in after.marches)
    queue_visible = after.march_used is not None and after.march_used >= 1
    ok = assured and active and queue_visible
    return VerificationResult(ok, "OK" if ok else "INTEL_BEAST_DISPATCH_NOT_PROVEN", {"victory_assured":assured,"active_march":active,"march_used":after.march_used})


def verify_intel_rescue_selected(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.INTEL and before.intel.get("status") == "AVAILABLE" and before.intel.get("mission_type") == "RESCUE_SURVIVORS"
    opened = after.page is Page.POPUP and after.popup == "INTEL_RESCUE_SURVIVORS_MISSION" and after.intel.get("mission_id") == "INTEL_RESCUE_SURVIVORS_10"
    ok = before_ok and opened
    return VerificationResult(ok, "OK" if ok else "INTEL_RESCUE_SELECTION_NOT_PROVEN", {"before_available":before_ok, "mission_dialog":opened})


def verify_intel_rescue_target_open(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.POPUP and before.popup == "INTEL_RESCUE_SURVIVORS_MISSION"
    target = after.page is Page.MAP and after.popup == "INTEL_RESCUE_SURVIVORS_TARGET" and after.intel.get("mission_id") == "INTEL_RESCUE_SURVIVORS_10" and after.intel.get("stamina_cost_displayed") == 12
    ok = before_ok and target
    return VerificationResult(ok, "OK" if ok else "INTEL_RESCUE_TARGET_NOT_PROVEN", {"mission_dialog":before_ok, "target_and_cost":target})


def verify_intel_hero_target_open(before: WorldState, after: WorldState) -> VerificationResult:
    """Tapping 前往查看 on a Hero Journey card opens the workable camp panel.

    The panel used to be classified as ``Page.BEAST`` because it shares the
    beast target layout.  Live 2026-09-14 it classifies as ``Page.EXPLORATION``
    instead: its 探险 ⚡10 button belongs to the exploration system, and the
    vision layer reports ``exploration.stamina_cost_displayed`` on it.  The
    brain already follows the live client - ``brain.py`` returns
    ``INTEL_HERO_START_MARCH`` for exactly this page state, and
    ``INTEL_HERO_START_MARCH`` is itself declared on ``Page.EXPLORATION``.

    This verifier was still requiring ``Page.BEAST``, so a step that really
    worked was recorded FAILURE and stopped the run before the fight could be
    started (live 2026-09-14: ``stop_reason=INTEL_HERO_TARGET_NOT_PROVEN`` on a
    frame showing the camp panel with its cost).  Both shapes are accepted;
    the camp panel must show a stamina cost to count as the target.
    """
    before_ok = before.page is Page.POPUP and before.popup == "INTEL_HERO_JOURNEY"
    camp_panel = (
        after.page is Page.EXPLORATION
        and after.exploration.get("stamina_cost_displayed") is not None
    )
    beast_card = after.page is Page.BEAST
    ok = before_ok and (camp_panel or beast_card)
    return VerificationResult(
        ok,
        "OK" if ok else "INTEL_HERO_TARGET_NOT_PROVEN",
        {
            "card": before_ok,
            "camp_panel": camp_panel,
            "beast_card": beast_card,
            "after_page": after.page.value,
        },
    )


def verify_intel_hero_march_open(before: WorldState, after: WorldState) -> VerificationResult:
    """The camp panel accepted the 探险 tap: it was replaced by the next page.

    Live 2026-09-14 the hero-journey fight has no march stage, so any transition
    out of the camp panel - the squad-setup page, a battle screen, a result
    popup or the bare map - is the observable state change.

    The panel is classified as ``Page.EXPLORATION`` on the current client (see
    ``verify_intel_hero_target_open``), and the live route is
    ``EXPLORATION -> MARCH``: tapping 探险 opens the squad page directly.  This
    check still demanded ``before.page is Page.BEAST`` and therefore rejected
    that real transition, so the run stopped with
    ``INTEL_HERO_MARCH_NOT_OPEN`` one step short of the fight.
    """
    camp_panel = (
        before.page is Page.EXPLORATION
        and before.exploration.get("stamina_cost_displayed") is not None
    )
    beast_panel = before.page is Page.BEAST and not before.beast
    before_ok = camp_panel or beast_panel
    left_panel = after.page is not before.page
    # A GET_MORE_STAMINA panel is the client *refusing* the action for lack of
    # stamina, not a result of it, and `left_panel` alone cannot tell the two
    # apart because both replace the camp panel.
    #
    # Measured live 2026-09-15T03:03:57Z (run_live.py --goal INTEL, the client
    # parked on a Hero Journey camp panel by the hourly automation): stamina was
    # 9 and the panel showed 探险 💧10, so the tap produced
    # `POPUP / GET_MORE_STAMINA` and the fight never started -- yet this check
    # returned OK and the episode recorded `INTEL_HERO_START_MARCH` as a
    # success.  A refusal recorded as success is the one failure mode this
    # project treats as worse than a failure.
    refused_for_stamina = after.page is Page.POPUP and after.popup == "GET_MORE_STAMINA"
    ok = before_ok and left_panel and not refused_for_stamina
    reason = "OK"
    if not ok:
        reason = (
            "INTEL_HERO_MARCH_REFUSED_FOR_STAMINA"
            if before_ok and refused_for_stamina
            else "INTEL_HERO_MARCH_NOT_OPEN"
        )
    return VerificationResult(
        ok,
        reason,
        {
            "camp_panel": camp_panel,
            "beast_panel": beast_panel,
            "left_panel": left_panel,
            "after_page": after.page.value,
            "refused_for_stamina": refused_for_stamina,
        },
    )


def verify_intel_hero_dispatched(before: WorldState, after: WorldState) -> VerificationResult:
    """The squad page accepted the 战斗 tap: the fight is an instant hero
    battle (live 2026-09-14: 6.65M vs 0.96M recommended power), so the
    observable state change is the squad page being replaced by the battle
    result or the map."""
    before_ok = before.page is Page.MARCH and not before.beast
    after_ok = after.page is not Page.MARCH
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "INTEL_HERO_DISPATCH_NOT_PROVEN", {"squad_page": before_ok, "left_page": after_ok, "after_page": after.page.value})


def verify_intel_rescue_started(before: WorldState, after: WorldState) -> VerificationResult:
    """Starting Rescue Survivors is proven by the mission's stamina being paid.

    Live 2026-09-14 production frames (false negative): tapping 营救 on the
    reviewed target dialog really started the mission - the HUD went 178 -> 166
    (exactly the 12 the dialog advertised) and the dialog was replaced by the
    探索 progress panel - but the after-frame returned an EMPTY intel dict, so
    the old check (`intel.status == IN_PROGRESS` from a mission-pin template
    that only ever matches the intel page) recorded FAILURE for an action that
    had worked.  Five production episodes failed this way; three of them showed
    the exact -12 spend.  A verifier must not let one frame-specific read drag
    down the whole judgement when the real state change is observable.

    Evidence model (both parts required: the reviewed dialog, then the payment):
    - before: on the world map, the reviewed Rescue Survivors target dialog is
      open and it advertises a cost;
    - after: that dialog is gone AND the stamina actually dropped by no more
      than the advertised cost - the same acceptance rule already used by
      `verify_beast_hunt`.  A BACK-out clears the dialog without paying, so it
      stays a failure; a MAP_HUD misread drifts the wrong way and also fails.

    The `IN_PROGRESS` read stays accepted as an alternative signal, so the
    reviewed intel-page frames keep verifying.
    """
    cost = before.intel.get("stamina_cost_displayed")
    target = (
        before.page is Page.MAP
        and before.popup == "INTEL_RESCUE_SURVIVORS_TARGET"
        and isinstance(cost, int)
        and cost > 0
    )
    dialog_cleared = after.page is Page.MAP and after.popup is None
    stamina_before = (before.stamina or {}).get("current")
    stamina_after = (after.stamina or {}).get("current")
    spend = (
        stamina_before - stamina_after
        if isinstance(stamina_before, int) and isinstance(stamina_after, int)
        else None
    )
    paid = spend is not None and 0 < spend <= cost
    in_progress = after.intel.get("status") == "IN_PROGRESS"
    ok = bool(target and dialog_cleared and (paid or in_progress))
    return VerificationResult(
        ok,
        "OK" if ok else "INTEL_RESCUE_START_NOT_PROVEN",
        {
            "target_and_cost": target,
            "dialog_cleared": dialog_cleared,
            "stamina_before": stamina_before,
            "stamina_after": stamina_after,
            "stamina_spent": spend,
            "cost": cost,
            "paid": paid,
            "in_progress": in_progress,
        },
    )


def verify_open_map(before: WorldState, after: WorldState) -> VerificationResult:
    """``HOME -> MAP`` is the whole claim; the march counter is not part of it.

    The pass condition used to be
    ``before.page is HOME and after.page is MAP and (after.march_used is not None
    or after.resource_search_open)``.  The last term folded a *queue* read into a
    *navigation* proof, and it failed navigations the page model had already
    proven.  Measured on the production episode stream: 2026-09-14T13:12:13,
    ``after.page`` was MAP at confidence 0.99 with ``march_max == 6``, a MAP_HUD
    stamina reading of 177, and ``resource_target == "COAL"`` -- the world map
    was plainly open -- yet ``march_used`` was ``None`` because neither
    ``MARCH_COUNT_1_OF_6`` nor ``MARCH_COUNT_2_OF_6`` matched that frame, so
    OPEN_MAP was recorded as OPEN_MAP_NOT_PROVEN and the run stopped.
    ``00_MASTER_RULES.md`` §6 names this exact anti-pattern: "Verifier 不应把无关
    的观测塞进自己的条件里（会让一个脆弱读取拖垮整条判定）".

    The page pair is the proof, and it is independent of the counter:
    ``SemanticWorldVision`` returns MAP only when the world-map HUD anchor
    (``BTN_OPEN_HOME``) matched *and* the HOME-only ``PAGE_MAP`` control did not,
    and returns HOME only when ``PAGE_MAP`` matched.  Both templates are
    reviewed, sit in the same bottom-right box, and are mutually exclusive by
    construction (``live_back_safe_home.png`` = PAGE_MAP / HOME;
    ``live_attempt8_idle.png`` = BTN_OPEN_HOME / MAP).

    ``march_used`` / ``march_max`` stay in the evidence dict as diagnostics --
    ``CHECK_MARCH`` -> ``verify_march_count_readable`` owns that fact -- but they
    no longer decide this one.
    """
    before_ok = before.page is Page.HOME
    after_ok = after.page is Page.MAP and after.confidence >= 0.9
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "OPEN_MAP_NOT_PROVEN",
        {
            "before_home": before_ok,
            "after_map": after_ok,
            "after_confidence": round(after.confidence, 3),
            "march_used": after.march_used,
            "march_max": after.march_max,
            "resource_search_open": after.resource_search_open,
        },
    )


def verify_open_home(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MAP
    after_ok = after.page is Page.HOME
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "OPEN_HOME_NOT_PROVEN",
        {"before_map": before_ok, "after_home": after_ok},
    )


def verify_open_intel(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MAP
    after_ok = after.page is Page.INTEL
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "OPEN_INTEL_NOT_PROVEN", {"before_map":before_ok,"after_intel":after_ok,"stamina":after.intel.get("stamina")})


def verify_beast_scan_observed(before: WorldState, after: WorldState) -> VerificationResult:
    # The scan is a viewport pan, not a semantic tap: its verifiable effect is
    # that the client is still on a *readable* world map afterwards (a pan
    # cannot be proven from template hits alone -- the beast fields are world
    # facts, not action results).  Whether a verified target was actually
    # found is decided by the *next* hop's verifier (verify_beast_target_selected),
    # which stays the only judge that SPEND_STAMINA_ON_BEAST really progressed.
    moved = before.page is Page.MAP and after.page is Page.MAP and after.known
    return VerificationResult(
        moved,
        "OK" if moved else "BEAST_SCAN_NOT_PROVEN",
        {"before_map": before.page is Page.MAP, "after_map": after.page is Page.MAP,
         "after_known": after.known, "after_confidence": after.confidence},
    )


def verify_beast_target_selected(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MAP and before.beast.get("visible_target") == "MUSK_OX" and before.beast.get("level") == 9
    after_ok = after.page is Page.BEAST and after.beast.get("name") == "麝牛" and after.beast.get("level") == 9 and after.beast.get("available") is True
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "BEAST_TARGET_SELECTION_NOT_PROVEN", {"before_visible":before_ok,"after_target":after_ok})


def verify_beast_mammoth_target_selected(before: WorldState, after: WorldState) -> VerificationResult:
    # The mammoth card carries no printed species name the vision layer can
    # claim (the card is recognized by its 攻击 control, which is generic), so
    # the after half asserts the card state vision actually measured --
    # attack_card -- and the identity is carried by the before half: the
    # sprite template that only matches the level-5 mammoth.
    before_ok = before.page is Page.MAP and before.beast.get("visible_target") == "MAMMOTH" and before.beast.get("level") == 5
    after_ok = after.page is Page.BEAST and after.beast.get("attack_card") is True
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "BEAST_TARGET_SELECTION_NOT_PROVEN", {"before_visible":before_ok,"after_card":after_ok})


def verify_beast_card_march_open(before: WorldState, after: WorldState) -> VerificationResult:
    # Tapping 攻击 opens the formation page; the page's own victory strip is
    # what the after half accepts (the same safety line the musk-ox march
    # verifier uses).  The stamina spend itself is not proven here -- opening
    # a formation costs nothing -- so this stays honest about what moved.
    before_ok = before.page is Page.BEAST and before.beast.get("attack_card") is True
    after_ok = after.page is Page.MARCH and after.beast.get("victory_assured") is True
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "BEAST_MARCH_NOT_PROVEN", {"before_card":before_ok,"victory_assured":after_ok})


def verify_beast_card_opened(before: WorldState, after: WorldState) -> VerificationResult:
    # The species-agnostic selection hop added 2026-09-20: the route taps the beast the
    # client's own label named, and this proves the *target* -- the card for that animal
    # opened -- rather than that a tap happened.
    #
    # The identity is bound on the before half, because that is the frame the label was
    # read on: 霜鳞避役 at 0.89 beside its badge, resolved to a table row, with the tap
    # point taken from that label's own box.  The after half asserts the card state vision
    # actually measured.  The card does not print a species the vision layer can claim --
    # it is recognised by its 攻击 control, which is generic -- so nothing here pretends to
    # re-read the identity after the tap, and the spend is not authorised here either:
    # opening a card costs no stamina.
    #
    # `refused` is what keeps the level-29 leopard out: its printed red assessment is a
    # measured refusal, so it is not a target this hop may claim.
    identity = before.beast.get("visible_target"), before.beast.get("level")
    before_ok = (
        before.page is Page.MAP
        and isinstance(identity[0], str)
        and isinstance(identity[1], int)
        and before.beast.get("source") == "BEAST_LABEL"
        and not refused_by_evidence(before.beast)
    )
    after_ok = after.page is Page.BEAST and after.beast.get("attack_card") is True
    ok = before_ok and after_ok
    return VerificationResult(
        ok, "OK" if ok else "BEAST_TARGET_SELECTION_NOT_PROVEN",
        {"before_identity": identity, "before_labelled": before_ok, "after_card": after_ok},
    )


def verify_beast_march_open(before: WorldState, after: WorldState) -> VerificationResult:
    # The identity is bound on the BEAST side, where the client prints
    # 等级9 麝牛 on the target card.  The formation page prints only
    # 目标：<name> and no level, so its half asserts the measured name plus the
    # safety line.  Until 2026-09-15 this half also demanded `level == 9`, a
    # value vision copied from whichever duplicate dispatch-button template
    # matched -- a tautology that passed on an invented identity.
    before_ok = before.page is Page.BEAST and before.beast.get("name") == "麝牛" and before.beast.get("level") == 9 and before.beast.get("available") is True
    after_ok = after.page is Page.MARCH and after.beast.get("name") == "麝牛" and after.beast.get("victory_assured") is True
    ok = before_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "BEAST_MARCH_NOT_PROVEN", {"target_verified":before_ok,"victory_assured":after_ok})


def verify_beast_dispatch(before: WorldState, after: WorldState) -> VerificationResult:
    # CAP-Z01: the MARCH page prints 目标：<name> and no level, so the row is resolved by
    # name.  What the row must supply is "the client has not already refused this one" --
    # not a per-species pre-approval.  Measured 2026-09-20: the old `target.dispatchable`
    # requirement meant a correctly read 霜鳞避役/20 could never be recorded as a dispatch
    # even after the client printed 本次出征胜券在握 on its formation page, because the row
    # was registered as UNVERIFIED.  The operator's rule is "as long as we can beat it, we
    # may hit it", and the client's own victory strip is the evidence for "we can beat it";
    # that strip is what `victory_assured` is, so it stays required here unchanged.
    target = lookup_by_name(before.beast.get("name"))
    before_ok = (
        before.page is Page.MARCH
        and target is not None
        and not target.refused
        and before.beast.get("victory_assured") is True
    )
    active = after.page is Page.MAP and any(state in {MarchState.MARCHING, MarchState.RETURNING} for state in after.marches)
    queue_visible = after.march_used is not None and after.march_used >= 1
    ok = before_ok and active and queue_visible
    return VerificationResult(ok, "OK" if ok else "BEAST_DISPATCH_NOT_PROVEN", {"victory_assured":before_ok,"active_march":active,"march_used":after.march_used})


def verify_resource_search_open(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MAP and not before.resource_search_open
    after_ok = after.page is Page.MAP and after.resource_search_open
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "RESOURCE_SEARCH_NOT_OPEN",
        {"before_closed": before_ok, "after_open": after_ok, "selected": after.resource_selected},
    )


def verify_resource_selected(before: WorldState, after: WorldState) -> VerificationResult:
    """Prove the *active resource tab* changed to the requested resource.

    The level filter used to be part of this conjunction, which coupled an
    unrelated read to the selection: every frame whose slider could not be
    measured failed the selection even when the tab identity was proven.  The
    level is a separate observation (and a separate verifier when a caller
    actually needs it), so it is reported as evidence here but no longer gates
    the selection.  The state change this verifier must prove is exactly "the
    anchored tab is now the requested resource", and nothing weaker is accepted:
    an UNKNOWN or mismatching tab still fails.
    """
    before_ok = before.page is Page.MAP and before.resource_search_open
    expected = before.resource_target or "WOOD"
    after_ok = (
        after.page is Page.MAP
        and after.resource_search_open
        and expected in {"MEAT", "WOOD", "COAL", "IRON"}
        and after.resource_selected == expected
    )
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "RESOURCE_SELECTION_NOT_PROVEN",
        {
            "before_search_open": before_ok,
            "expected": expected,
            "selected": after.resource_selected,
            "level": after.resource_level,
            "tab_matches": after.resource_selected == expected,
        },
    )


def verify_resource_found(before: WorldState, after: WorldState) -> VerificationResult:
    expected = before.resource_target or before.resource_selected or "WOOD"
    before_ok = (
        before.page is Page.MAP
        and before.resource_search_open
        and before.resource_selected == expected
    )
    after_ok = (
        after.page is Page.RESOURCE_DETAIL
        and after.resource_target == expected
        and after.resource_available is True
    )
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "RESOURCE_NOT_FOUND",
        {"configured_wood": before_ok, "resource_page": after.page.value, "available": after.resource_available},
    )


def verify_beast_search_tab_selected(before: WorldState, after: WorldState) -> VerificationResult:
    """Prove the open search panel is showing the 野兽 (ordinary beast) tab.

    The panel is the same one the verified gathering chain opens; this hop only
    changes which tab is anchored inside it.  Both halves therefore require
    ``resource_search_open``: a frame without the panel cannot prove a tab
    switch, and reporting one from the bare map is exactly the stale-evidence
    mistake the fixed-ROI selection verifier used to make.

    The evidence is ``resource_beast_tab_norm`` -- where this frame's own OCR read the
    printed 野兽 label -- and NOT ``resource_selected``.  Two separate reasons, both
    measured:

    * ``resource_selected`` only identifies the four gatherable cells
      (MEAT/WOOD/COAL/IRON) against reviewed templates, so a monster tab always reads
      back as ``None`` there.  Measured 2026-09-21 on ``beast_tab.png``: the tab is
      drawn and anchored with its white bracket, and ``resource_selected`` was ``None``.
    * the *position* is not stable, so a template cannot stand in for the label either.
      Measured live 2026-09-21: the client had 野兽 in the leftmost slot where the
      archived frame had 冰原巨兽, so ``BTN_SEARCH_BEAST_TAB`` scored NO MATCH and the
      chain's second hop failed with SEMANTIC_TARGET_NOT_VERIFIED.  The printed label
      read at 0.95 and is what this now keys on.

    The distinction from 冰原巨兽 is load-bearing, not cosmetic: the measured level-5
    mammoth card offers only 集结, so a verifier that accepted either tab as "the beast
    tab" would pass a frame whose targets cannot be attacked solo -- which is the
    user-facing rule that a rally target must not be attempted as a normal attack.

    The evidence is the *anchor*, ``resource_selected_tab == "BEAST"``, and not merely
    the label's presence.  Measured 2026-09-21: the panel opens with all five tabs drawn
    and **生肉** bracketed, so ``resource_beast_tab_norm`` is already non-``None`` on a
    frame where the 野兽 tab is not selected at all.  A verifier keyed on the label would
    therefore have passed the very hop that failed -- it reported ``BEAST_SEARCH_TAB_NOT_PROVEN``
    only because the run never issued the hop, and issuing it would have produced a false
    pass while the 搜索 tap went to a gatherable node behind the panel.
    """
    before_ok = before.page is Page.MAP and before.resource_search_open
    after_ok = (
        after.page is Page.MAP
        and after.resource_search_open
        and after.resource_selected_tab == "BEAST"
    )
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "BEAST_SEARCH_TAB_NOT_PROVEN",
        {
            "before_search_open": before_ok,
            "after_selected_tab": after.resource_selected_tab,
            "after_beast_tab_label": after.resource_beast_tab_norm,
            "after_giant_beast_tab_label": after.resource_giant_beast_tab_norm,
            "after_tab_kinds": list(after.resource_tab_kinds),
            "after_selected": after.resource_selected,
            "level": after.resource_level,
        },
    )


def verify_beast_search_submitted(before: WorldState, after: WorldState) -> VerificationResult:
    """Prove the 搜索 tap made the client put a beast target on the map.

    The claim is about what the tap achieved, not that a tap happened.  Vision
    reports ``beast_search_submitted`` when the panel is still open, the beast
    tab is still selected, and the client has drawn its result card -- which is
    the state the reviewed ``beast5_found.png`` frame records.

    The panel staying open is why this verifier does NOT require it to close.
    That was the first design here and the archived frame refutes it: after
    搜索 the client keeps the panel up and overlays the target card on top of
    it, so "panel closed" would have been a condition no successful search could
    ever satisfy.  The measured after-state is the card, not an empty map.

    Nothing here authorises a spend.  搜索 costs no stamina and starts no march;
    the spend is decided and proven three hops further down, behind the client's
    own 胜券在握 strip.  The verifier is also careful about what it does not
    claim: the card for a 5-level beast may offer 集结 rather than 攻击, and that
    difference is read by the card branch itself -- this hop only establishes
    that a target is now on screen to be looked at.
    """
    before_ok = (
        before.page is Page.MAP
        and before.resource_search_open
        and before.resource_beast_tab
    )
    after_ok = after.page is Page.MAP and after.beast_search_submitted
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "BEAST_SEARCH_NOT_SUBMITTED",
        {
            "before_beast_tab": before_ok,
            "beast_search_submitted": after.beast_search_submitted,
            "beast_on_map": bool(after.beast.get("source") == "BEAST_LABEL" or after.beast.get("visible_target")),
            "after_page": after.page.value,
        },
    )


def verify_march_page_open(before: WorldState, after: WorldState) -> VerificationResult:
    """Prove the resource-detail Gather control opened the march formation page.
    ``MARCH_PAGE_NOT_OPEN`` used to be one opaque reason covering two unrelated
    defects, so the counter could not be acted on:

    * ``MARCH_PAGE_ACTION_MISSED`` — the resource-detail page is still on screen
      with its Gather control present, so the tap never took effect.  Treating
      this separately makes it a retry/latency problem.
    * ``MARCH_PAGE_NOT_RECOGNIZED`` — the page changed but Vision could not name
      it.  That is a template/classification problem, not a tap problem.

    Both are still failures; they are simply no longer counted as one number.
    """
    before_ok = (
        before.page is Page.RESOURCE_DETAIL
        and before.resource_target in {"MEAT", "WOOD", "COAL", "IRON"}
        and before.resource_available is True
    )
    if after.page is Page.MARCH and after.resource_target == before.resource_target:
        return VerificationResult(True, "OK", {"available_resource": before_ok, "march_page": True})
    if after.page is Page.RESOURCE_DETAIL:
        reason, detail = "MARCH_PAGE_ACTION_MISSED", {"still_on_resource_detail": True}
    elif after.page is Page.UNKNOWN:
        reason, detail = "MARCH_PAGE_NOT_RECOGNIZED", {"unclassified_page": True}
    else:
        reason, detail = "MARCH_PAGE_NOT_OPEN", {"after_page": after.page.value}
    detail.update({"available_resource": before_ok, "march_page": False, "after_page": after.page.value})
    return VerificationResult(False, reason, detail)


def verify_wood_dispatch_from_march(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MARCH and before.resource_target in {"MEAT", "WOOD", "COAL", "IRON"}
    after_state = any(state in {MarchState.MARCHING, MarchState.GATHERING} for state in after.marches)
    # The formation page does not expose the global march counter, and the
    # idle map can hide it completely. A fixed ``>= 2`` requirement therefore
    # rejected a real first dispatch. Require an observable active queue row
    # instead: positive used count + MARCHING/GATHERING + carried wood target.
    queue_ok = after.march_used is not None and after.march_used >= 1
    target_ok = before.resource_target in {"MEAT", "WOOD", "COAL", "IRON"}
    after_ok = after.page is Page.MAP and after_state and queue_ok and target_ok
    ok = before_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "DISPATCH_NOT_PROVEN",
        {
            "wood_march_page": before_ok,
            "active_state": after_state,
            "active_queue_visible": queue_ok,
            "march_used": after.march_used,
            "target_ok": target_ok,
        },
    )


def verify_dispatch(before: WorldState, after: WorldState, expected_resource: str) -> VerificationResult:
    used_increased = before.march_used is not None and after.march_used is not None and after.march_used > before.march_used
    target_ok = after.resource_target == expected_resource
    state_ok = any(state in {MarchState.MARCHING, MarchState.GATHERING} for state in after.marches)
    ok = used_increased and target_ok and state_ok
    return VerificationResult(ok, "OK" if ok else "DISPATCH_NOT_PROVEN", {"used_increased":used_increased,"target_ok":target_ok,"state_ok":state_ok})


def verify_gathering(state: WorldState) -> VerificationResult:
    ok = state.page in {Page.MAP, Page.RESOURCE_DETAIL} and MarchState.GATHERING in state.marches and bool(state.resource_target)
    return VerificationResult(ok, "OK" if ok else "GATHERING_NOT_PROVEN", {"page":state.page.value,"resource":state.resource_target,"marches":[m.value for m in state.marches]})


def verify_returning(state: WorldState) -> VerificationResult:
    ok = state.page in {Page.MAP, Page.MARCH_QUEUE} and MarchState.RETURNING in state.marches
    return VerificationResult(ok, "OK" if ok else "RETURNING_NOT_PROVEN", {"page":state.page.value,"marches":[m.value for m in state.marches]})


def verify_return_complete(returning: WorldState, idle: WorldState) -> VerificationResult:
    had_return = MarchState.RETURNING in returning.marches
    queue_decreased = (
        returning.march_used is not None
        and idle.march_used is not None
        and idle.march_used < returning.march_used
    )
    now_idle = idle.page is Page.MAP and not any(
        state in {MarchState.MARCHING, MarchState.GATHERING, MarchState.RETURNING}
        for state in idle.marches
    )
    ok = had_return and queue_decreased and now_idle
    return VerificationResult(
        ok,
        "OK" if ok else "RETURN_NOT_COMPLETE",
        {"had_return": had_return, "queue_decreased": queue_decreased, "now_idle": now_idle},
    )


def verify_gather_cycle(
    before: WorldState,
    marching: WorldState,
    returning: WorldState,
    idle: WorldState,
    expected_resource: str,
) -> VerificationResult:
    dispatch = verify_dispatch(before, marching, expected_resource)
    return_started = verify_returning(returning)
    return_complete = verify_return_complete(returning, idle)
    ok = dispatch.ok and return_started.ok and return_complete.ok
    return VerificationResult(
        ok,
        "OK" if ok else "GATHER_CYCLE_NOT_PROVEN",
        {
            "dispatch": dispatch.evidence,
            "returning": return_started.evidence,
            "return_complete": return_complete.evidence,
        },
    )


def verify_building_upgrade(before: WorldState, after: WorldState, building_id: str) -> VerificationResult:
    before_level = before.building.get("level")
    target_level = before.building.get("target_level")
    queue_building = after.building.get("queue_building")
    timer = after.building.get("timer")
    target_ok = before.building.get("id") == building_id and queue_building == building_id
    level_ok = isinstance(before_level, int) and target_level == before_level + 1
    queue_started = isinstance(timer, str) and bool(timer.strip())
    ok = target_ok and level_ok and queue_started
    return VerificationResult(
        ok,
        "OK" if ok else "BUILDING_UPGRADE_NOT_PROVEN",
        {"target_ok": target_ok, "level_ok": level_ok, "queue_started": queue_started, "timer": timer},
    )


def verify_research_queue(state: WorldState) -> VerificationResult:
    status_ok = state.research.get("status") == "IN_PROGRESS"
    timer = state.research.get("timer")
    timer_ok = isinstance(timer, str) and bool(timer.strip())
    queue_busy = state.research.get("queue_available") is False
    ok = state.page is Page.RESEARCH and status_ok and timer_ok and queue_busy
    return VerificationResult(
        ok,
        "OK" if ok else "RESEARCH_QUEUE_UNKNOWN",
        {"status_ok": status_ok, "timer_ok": timer_ok, "queue_busy": queue_busy, "timer": timer},
    )


def verify_research_started(before: WorldState, after: WorldState, research_id: str) -> VerificationResult:
    was_available = before.research.get("queue_available") is True
    target_ok = after.research.get("node") == research_id
    queue = verify_research_queue(after)
    ok = was_available and target_ok and queue.ok
    return VerificationResult(
        ok,
        "OK" if ok else "RESEARCH_START_NOT_PROVEN",
        {"was_available": was_available, "target_ok": target_ok, "queue": queue.evidence},
    )


def verify_training_queue(state: WorldState, troop_type: str) -> VerificationResult:
    type_ok = state.training.get("troop_type") == troop_type
    status_ok = state.training.get("status") == "IN_PROGRESS"
    timer = state.training.get("timer")
    timer_ok = isinstance(timer, str) and bool(timer.strip())
    queue_busy = state.training.get("queue_available") is False
    ok = state.page is Page.TRAINING and type_ok and status_ok and timer_ok and queue_busy
    return VerificationResult(
        ok,
        "OK" if ok else "TRAINING_QUEUE_UNKNOWN",
        {"type_ok": type_ok, "status_ok": status_ok, "timer_ok": timer_ok, "queue_busy": queue_busy},
    )


def verify_all_training_queues_busy(states: tuple[WorldState, ...]) -> VerificationResult:
    expected = {"INFANTRY", "LANCER", "MARKSMAN"}
    proven = {
        troop_type
        for troop_type in expected
        if any(verify_training_queue(state, troop_type).ok for state in states)
    }
    ok = proven == expected
    return VerificationResult(ok, "OK" if ok else "TRAINING_AVAILABILITY_UNKNOWN", {"busy_types": sorted(proven)})


def verify_training_started(before: WorldState, after: WorldState, troop_type: str) -> VerificationResult:
    was_available = before.training.get("queue_available") is True
    queue = verify_training_queue(after, troop_type)
    ok = was_available and queue.ok
    return VerificationResult(
        ok,
        "OK" if ok else "TRAINING_START_NOT_PROVEN",
        {"was_available": was_available, "queue": queue.evidence},
    )


def verify_intel_claim(before: WorldState, reward: WorldState, after: WorldState) -> VerificationResult:
    was_claimable = before.page is Page.INTEL and before.intel.get("status") == "CLAIMABLE" and int(before.intel.get("claimable_count", 0)) > 0
    reward_visible = is_reward_popup(reward)
    cleared = after.page is Page.INTEL and int(after.intel.get("claimable_count", 0)) == 0 and after.intel.get("status") != "CLAIMABLE"
    ok = was_claimable and reward_visible and cleared
    return VerificationResult(
        ok,
        "OK" if ok else "INTEL_CLAIM_NOT_PROVEN",
        {"was_claimable": was_claimable, "reward_visible": reward_visible, "cleared": cleared},
    )


# The client shows ONE shared "获得奖励" popup for every reward source, so
# which popup branch in vision.py wins is not stable.  Measured 2026-09-14: the
# same Intel claim produced EXPLORATION_REWARD on the first after-frame and
# GENERIC_REWARD on the two refresh frames, because POPUP_EXPLORATION_REWARD is
# checked before POPUP_INTEL_REWARD and they match the same artwork.  The source
# is therefore proven by the *before* state (Intel page with claimable > 0),
# which is already required; any reward popup counts as the feedback.
# verify_daily_claim_feedback accepted GENERIC_REWARD for the same reason.
REWARD_POPUPS = frozenset({"INTEL_REWARD", "GENERIC_REWARD", "EXPLORATION_REWARD"})


def is_reward_popup(state: WorldState) -> bool:
    """True when a reward popup is on screen, whatever the client called it."""
    return state.page is Page.POPUP and (
        state.popup in REWARD_POPUPS
        or state.intel.get("claim_feedback") is True
        or state.daily.get("claim_feedback") is True
        or state.mail.get("claim_feedback") is True
        or state.exploration.get("claim_feedback") is True
    )


def verify_intel_claim_feedback(before: WorldState, after: WorldState) -> VerificationResult:
    """Atomic claim proof used by LiveRuntime before the reward popup is closed."""
    was_claimable = before.page is Page.INTEL and before.intel.get("status") == "CLAIMABLE" and int(before.intel.get("claimable_count", 0)) > 0
    reward_visible = is_reward_popup(after)
    ok = was_claimable and reward_visible
    return VerificationResult(ok, "OK" if ok else "INTEL_CLAIM_FEEDBACK_NOT_PROVEN", {"was_claimable":was_claimable,"reward_visible":reward_visible,"popup":after.popup})


def verify_beast_hunt(
    target: WorldState,
    march: WorldState,
    returning: WorldState,
    idle: WorldState,
    intel_completed: WorldState,
) -> VerificationResult:
    target_ok = target.page is Page.BEAST and target.beast.get("available") is True and target.beast.get("mission_id") == "INTEL_BEAST_10"
    # The formation page prints no level, so this half asserts the measured
    # safety line only (it used to demand `level == 22`, a value vision copied
    # from a duplicate button template).
    march_ok = march.page is Page.MARCH and march.beast.get("victory_assured") is True
    returning_ok = (
        returning.page is Page.MAP
        and MarchState.RETURNING in returning.marches
        and returning.beast.get("battle_completed") is True
        and returning.march_used == 2
    )
    returned_ok = idle.page is Page.MAP and idle.march_used == 1 and MarchState.RETURNING not in idle.marches
    stamina_before = int(target.beast.get("stamina_before", 0))
    stamina_after = int(intel_completed.intel.get("stamina", stamina_before))
    displayed_cost = int(target.beast.get("stamina_cost_displayed", 0))
    stamina_delta = stamina_before - stamina_after
    stamina_ok = 0 < stamina_delta <= displayed_cost
    intel_ok = intel_completed.page is Page.INTEL and intel_completed.intel.get("status") == "CLAIMABLE"
    ok = target_ok and march_ok and returning_ok and returned_ok and stamina_ok and intel_ok
    return VerificationResult(
        ok,
        "OK" if ok else "BEAST_HUNT_NOT_PROVEN",
        {
            "target_ok": target_ok,
            "march_ok": march_ok,
            "returning_ok": returning_ok,
            "returned_ok": returned_ok,
            "stamina_delta": stamina_delta,
            "stamina_ok": stamina_ok,
            "intel_ok": intel_ok,
        },
    )


def verify_daily_hero_recruit(
    before: WorldState,
    recruit_page: WorldState,
    recruit_reward: WorldState,
    claimable: WorldState,
    daily_reward: WorldState,
    after: WorldState,
) -> VerificationResult:
    before_ok = before.page is Page.DAILY and before.daily.get("task_id") == "HERO_RECRUIT_1" and before.daily.get("progress") == 0
    free_ok = recruit_page.daily.get("free_recruits", 0) > 0 and recruit_page.daily.get("action") == "FREE_RECRUIT"
    recruit_ok = recruit_reward.page is Page.POPUP and recruit_reward.popup == "HERO_RECRUIT_REWARD"
    claimable_ok = claimable.page is Page.DAILY and claimable.daily.get("status") == "CLAIMABLE"
    reward_ok = daily_reward.page is Page.POPUP and daily_reward.popup == "DAILY_REWARD"
    points_before = int(before.daily.get("activity", 0))
    points_after = int(after.daily.get("activity", 0))
    after_ok = after.page is Page.DAILY and points_after == points_before + 10 and after.daily.get("claimable_count") == 0
    ok = before_ok and free_ok and recruit_ok and claimable_ok and reward_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "DAILY_HERO_RECRUIT_NOT_PROVEN",
        {"before_ok":before_ok,"free_ok":free_ok,"recruit_ok":recruit_ok,"claimable_ok":claimable_ok,"reward_ok":reward_ok,"activity_delta":points_after-points_before,"after_ok":after_ok},
    )


def verify_daily_claim(before: WorldState, reward: WorldState, after: WorldState) -> VerificationResult:
    claimable_before = before.page is Page.DAILY and before.daily.get("status") == "CLAIMABLE" and int(before.daily.get("claimable_count", 0)) > 0
    reward_ok = reward.page is Page.POPUP and reward.popup == "DAILY_REWARD" and reward.daily.get("claim_feedback") is True
    activity_before = int(before.daily.get("activity", 0))
    activity_after = int(after.daily.get("activity", activity_before))
    expected_delta = int(reward.daily.get("activity_reward", 0))
    activity_ok = expected_delta > 0 and activity_after - activity_before == expected_delta
    cleared = after.page is Page.DAILY and int(after.daily.get("claimable_count", 0)) == 0
    ok = claimable_before and reward_ok and activity_ok and cleared
    return VerificationResult(ok, "OK" if ok else "DAILY_CLAIM_NOT_PROVEN", {"claimable_before":claimable_before,"reward_ok":reward_ok,"activity_delta":activity_after-activity_before,"expected_delta":expected_delta,"cleared":cleared})


def verify_alliance_daily_chain(
    daily_before: WorldState,
    alliance_start: WorldState,
    contribution_before: WorldState,
    contribution_results: tuple[WorldState, ...],
    alliance_after: WorldState,
    daily_claimable: WorldState,
    daily_reward: WorldState,
    daily_after: WorldState,
) -> VerificationResult:
    task_before_ok = (
        daily_before.page is Page.DAILY
        and daily_before.daily.get("task_id") == "ALLIANCE_CONTRIBUTE_5"
        and daily_before.daily.get("progress") == 3
        and daily_before.daily.get("goal") == 5
    )
    action_ok = (
        contribution_before.page is Page.ALLIANCE
        and contribution_before.alliance.get("status") == "AVAILABLE"
        and contribution_before.alliance.get("resource") == "MEAT"
        and contribution_before.alliance.get("cost") == 10000
    )
    attempts_before = int(contribution_before.alliance.get("attempts_remaining", -1))
    rewards = [int(state.alliance.get("contribution", 0)) for state in contribution_results]
    attempts = [int(state.alliance.get("attempts_remaining", -1)) for state in contribution_results]
    contributions_ok = len(contribution_results) == 2 and rewards == [120, 240] and attempts == [attempts_before - 1, attempts_before - 2]
    contribution_delta = int(alliance_after.alliance.get("personal_contribution", 0)) - int(alliance_start.alliance.get("personal_contribution", 0))
    total_ok = contribution_delta == sum(rewards) == 360
    task_claimable_ok = (
        daily_claimable.page is Page.DAILY
        and daily_claimable.daily.get("task_id") == "ALLIANCE_CONTRIBUTE_5"
        and daily_claimable.daily.get("progress") == daily_claimable.daily.get("goal") == 5
        and daily_claimable.daily.get("status") == "CLAIMABLE"
    )
    claim = verify_daily_claim(daily_claimable, daily_reward, daily_after)
    tier_advanced = daily_after.daily.get("task_id") == "ALLIANCE_CONTRIBUTE_20" and daily_after.daily.get("progress") == 5
    ok = task_before_ok and action_ok and contributions_ok and total_ok and task_claimable_ok and claim.ok and tier_advanced
    return VerificationResult(
        ok,
        "OK" if ok else "ALLIANCE_DAILY_CHAIN_NOT_PROVEN",
        {
            "task_before_ok": task_before_ok,
            "action_ok": action_ok,
            "rewards": rewards,
            "attempts": attempts,
            "contribution_delta": contribution_delta,
            "task_claimable_ok": task_claimable_ok,
            "claim": claim.evidence,
            "tier_advanced": tier_advanced,
        },
    )


def verify_alliance_tech_contribution(before: WorldState, result: WorldState, after: WorldState) -> VerificationResult:
    available = (
        before.page is Page.ALLIANCE
        and before.alliance.get("section") == "TECHNOLOGY"
        and before.alliance.get("status") == "AVAILABLE"
    )
    cost_ok = before.alliance.get("resource") == "MEAT" and before.alliance.get("cost") == 10000
    attempts_before = int(before.alliance.get("attempts_remaining", -1))
    attempts_after = int(result.alliance.get("attempts_remaining", -1))
    result_ok = result.page is Page.ALLIANCE and result.alliance.get("status") == "CONTRIBUTED" and attempts_after == attempts_before - 1
    contribution_before = int(before.alliance.get("personal_contribution", 0))
    contribution_after = int(after.alliance.get("personal_contribution", 0))
    delta = contribution_after - contribution_before
    result_reward = int(result.alliance.get("contribution", 0))
    reward_ok = result_reward in {120, 240}
    after_ok = after.page is Page.ALLIANCE and after.alliance.get("section") == "TECHNOLOGY" and reward_ok and delta == result_reward
    ok = available and cost_ok and result_ok and after_ok
    return VerificationResult(
        ok,
        "OK" if ok else "ALLIANCE_TECH_CONTRIBUTION_NOT_PROVEN",
        {"available": available, "cost_ok": cost_ok, "attempt_delta": attempts_after - attempts_before, "result_reward": result_reward, "contribution_delta": delta, "reward_ok": reward_ok, "after_ok": after_ok},
    )


def verify_alliance_help_auto_active(state: WorldState) -> VerificationResult:
    ok = (
        state.page is Page.ALLIANCE
        and state.alliance.get("section") == "HELP"
        and state.alliance.get("status") == "NOT_AVAILABLE"
        and state.alliance.get("auto_help_active") is True
    )
    return VerificationResult(ok, "OK" if ok else "ALLIANCE_HELP_STATE_UNKNOWN", {"auto_help_active": state.alliance.get("auto_help_active")})


def verify_alliance_gifts_claim(before: WorldState, reward: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.ALLIANCE and before.alliance.get("section") == "GIFTS" and before.alliance.get("status") == "CLAIMABLE"
    reward_ok = reward.page is Page.POPUP and reward.popup == "ALLIANCE_GIFT_REWARD" and reward.alliance.get("claim_feedback") is True
    before_count = int(before.alliance.get("daily_claimed", -1))
    after_count = int(after.alliance.get("daily_claimed", -1))
    count_delta = after_count - before_count
    count_ok = before_count >= 0 and count_delta > 0 and after_count <= int(after.alliance.get("daily_limit", 500))
    progress_before = int(before.alliance.get("gift_progress", 0))
    progress_after = int(after.alliance.get("gift_progress", 0))
    progress_ok = progress_after >= progress_before
    claimed_ok = after.page is Page.ALLIANCE and after.alliance.get("section") == "GIFTS" and after.alliance.get("status") != "CLAIMABLE" and int(after.alliance.get("visible_claimed", 0)) > 0
    ok = before_ok and reward_ok and count_ok and progress_ok and claimed_ok
    return VerificationResult(ok, "OK" if ok else "ALLIANCE_GIFT_CLAIM_NOT_PROVEN", {"before_ok":before_ok,"reward_ok":reward_ok,"daily_count_delta":count_delta,"count_ok":count_ok,"progress_delta":progress_after-progress_before,"progress_ok":progress_ok,"claimed_ok":claimed_ok})


def verify_alliance_gifts_claimed(before: WorldState, after: WorldState) -> VerificationResult:
    """Claim-all on the Alliance Gifts page (the ``ALLIANCE_GIFTS`` skill).

    Why this exists (2026-09-15).  ``brain.py`` selects ``ALLIANCE_GIFTS``
    whenever the gifts page reports ``status == CLAIMABLE``, but the skill had
    no entry in ``LiveRuntime.VERIFIED_ATOMIC`` -- and a skill without a
    verifier is never dispatched.  So the last step of the alliance gift chain
    was dead even after the gifts page had been reached, which is why the live
    Alliance page could carry a 99+ unclaimed-gift badge indefinitely.

    The two-state form is deliberate: ``verify_alliance_gifts_claim`` above
    needs a third ``reward`` frame and is used by the offline daily chain, while
    the live loop only ever hands a verifier the before/after pair.

    Evidence is taken from fields the production vision already extracts from
    the live gifts page.  Measured 2026-09-15 on
    ``dataset/raw/live_alliance_gifts_page.png``: ``status=CLAIMABLE``,
    ``daily_claimed=444``, ``daily_limit=500``, ``gift_progress=71636``,
    ``visible_claim_buttons=4``.
    """
    before_ok = (
        before.page is Page.ALLIANCE
        and before.alliance.get("section") == "GIFTS"
        and before.alliance.get("status") == "CLAIMABLE"
    )
    # The client either resolves a claim-all in place (stays on the gifts list)
    # or answers with the alliance gift reward overlay.  Both are accepted,
    # because rejecting the overlay form would score a real claim as a failure
    # and poison the success rate -- the mistake this project has already paid
    # for twice.  Only the *specific* gift-reward overlay counts; a generic
    # popup would be no evidence at all.
    after_on_gifts = after.page is Page.ALLIANCE and after.alliance.get("section") == "GIFTS"
    after_is_gift_reward = after.page is Page.POPUP and after.popup == "ALLIANCE_GIFT_REWARD"

    count_ok = False
    buttons_ok = False
    progress_ok = False
    before_claimed = int(before.alliance.get("daily_claimed", -1))
    after_claimed = int(after.alliance.get("daily_claimed", -1))
    count_delta = after_claimed - before_claimed
    buttons_before = int(before.alliance.get("visible_claim_buttons", 0))
    buttons_after = int(after.alliance.get("visible_claim_buttons", 0))
    progress_delta = int(after.alliance.get("gift_progress", 0)) - int(before.alliance.get("gift_progress", 0))
    if after_on_gifts:
        # The counters only mean anything when the list is still readable; the
        # overlay covers it, and reading zeros behind it would look like a
        # negative delta.
        count_ok = (
            before_claimed >= 0
            and count_delta > 0
            and after_claimed <= int(after.alliance.get("daily_limit", 500))
        )
        buttons_ok = buttons_before > 0 and buttons_after < buttons_before
        progress_ok = progress_delta >= 0

    # Either in-place signal alone is enough: the daily counter is the game's
    # own record of what was claimed, while the visible button count can fall to
    # zero in the same frame that the counter read lags behind.
    action_ok = count_ok or buttons_ok
    ok = before_ok and ((after_on_gifts and action_ok and progress_ok) or after_is_gift_reward)
    return VerificationResult(
        ok,
        "OK" if ok else "ALLIANCE_GIFTS_CLAIM_NOT_PROVEN",
        {
            "before_ok": before_ok,
            "after_on_gifts": after_on_gifts,
            "after_is_gift_reward": after_is_gift_reward,
            "daily_count_delta": count_delta,
            "count_ok": count_ok,
            "claim_buttons_before": buttons_before,
            "claim_buttons_after": buttons_after,
            "buttons_ok": buttons_ok,
            "progress_delta": progress_delta,
            "progress_ok": progress_ok,
        },
    )


def verify_mail_claim(before: WorldState, reward: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MAIL and before.mail.get("status") == "CLAIMABLE"
    reward_ok = reward.page is Page.POPUP and reward.popup == "MAIL_REWARD" and reward.mail.get("claim_feedback") is True
    after_ok = after.page is Page.MAIL and after.mail.get("status") == "CLAIMED" and int(after.mail.get("badge_count", -1)) == 0
    ok = before_ok and reward_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "MAIL_CLAIM_NOT_PROVEN", {"before_ok":before_ok,"reward_ok":reward_ok,"after_ok":after_ok})


def verify_open_mail(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and after.page is Page.MAIL
    return VerificationResult(ok, "OK" if ok else "OPEN_MAIL_NOT_PROVEN", {"before_home":before.page is Page.HOME, "after_mail":after.page is Page.MAIL})


def verify_open_alliance(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and after.page is Page.ALLIANCE
    return VerificationResult(ok, "OK" if ok else "OPEN_ALLIANCE_NOT_PROVEN", {"before_home":before.page is Page.HOME, "after_alliance":after.page is Page.ALLIANCE})


def verify_open_exploration(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.HOME and after.page is Page.EXPLORATION
    return VerificationResult(ok, "OK" if ok else "OPEN_EXPLORATION_NOT_PROVEN", {"before_home":before.page is Page.HOME, "after_exploration":after.page is Page.EXPLORATION})


def verify_exploration_claim_feedback(before: WorldState, after: WorldState) -> VerificationResult:
    ok = before.page is Page.EXPLORATION and before.exploration.get("status") == "CLAIMABLE" and after.page is Page.POPUP and after.popup == "EXPLORATION_IDLE_DIALOG"
    return VerificationResult(ok, "OK" if ok else "EXPLORATION_IDLE_DIALOG_NOT_PROVEN", {"claimable_before":before.exploration.get("status") == "CLAIMABLE", "dialog_visible":after.popup == "EXPLORATION_IDLE_DIALOG"})


def verify_exploration_claim_confirmed(before: WorldState, after: WorldState) -> VerificationResult:
    reward_visible = after.page is Page.POPUP and (after.popup == "GENERIC_REWARD" or (after.popup == "EXPLORATION_REWARD" and after.exploration.get("claim_feedback") is True))
    ok = before.page is Page.POPUP and before.popup == "EXPLORATION_IDLE_DIALOG" and reward_visible
    return VerificationResult(ok, "OK" if ok else "EXPLORATION_REWARD_FEEDBACK_NOT_PROVEN", {"dialog_before":before.popup == "EXPLORATION_IDLE_DIALOG", "reward_visible":reward_visible})


def verify_exploration_reward_dismissed(before: WorldState, after: WorldState) -> VerificationResult:
    reward_before = before.page is Page.POPUP and before.popup in {"EXPLORATION_REWARD", "GENERIC_REWARD"}
    ok = reward_before and after.page is Page.EXPLORATION and after.exploration.get("status") == "CLAIMED"
    return VerificationResult(ok, "OK" if ok else "EXPLORATION_REWARD_DISMISS_NOT_PROVEN", {"reward_before":reward_before, "claimed_after":after.exploration.get("status") == "CLAIMED"})


def verify_mail_tab_selected(expected_tab: str, before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.MAIL and bool(before.mail.get("tab_badges", {}).get(expected_tab))
    active = after.page is Page.MAIL and after.mail.get("active_tab") == expected_tab
    ok = before_ok and active
    return VerificationResult(ok, "OK" if ok else "MAIL_TAB_SELECTION_NOT_PROVEN", {"badge_visible":before_ok, "active_tab":after.mail.get("active_tab"), "expected_tab":expected_tab})


def verify_mail_alliance_tab_selected(before: WorldState, after: WorldState) -> VerificationResult:
    return verify_mail_tab_selected("ALLIANCE", before, after)


def verify_mail_system_tab_selected(before: WorldState, after: WorldState) -> VerificationResult:
    return verify_mail_tab_selected("SYSTEM", before, after)


def verify_mail_report_tab_selected(before: WorldState, after: WorldState) -> VerificationResult:
    return verify_mail_tab_selected("REPORT", before, after)


def verify_mail_claim_feedback(before: WorldState, after: WorldState) -> VerificationResult:
    active = before.mail.get("active_tab")
    before_ok = before.page is Page.MAIL and bool(before.mail.get("tab_badges", {}).get(active))
    # Reward overlays share artwork and may be classified as DAILY/INTEL/etc.
    # Attribution comes from the verified action context: a claim launched from
    # an active Mail tab followed immediately by any known reward overlay is
    # Mail claim feedback.  This does not authorize clicking an unknown popup.
    known_reward_popup = after.popup in {
        "MAIL_REWARD", "INTEL_REWARD", "DAILY_REWARD",
        "EXPLORATION_REWARD", "GENERIC_REWARD",
    }
    reward = after.page is Page.POPUP and (
        (after.popup == "MAIL_REWARD" and after.mail.get("claim_feedback") is True)
        or (after.popup == "INTEL_REWARD" and after.intel.get("claim_feedback") is True)
        or known_reward_popup
    )
    ok = before_ok and reward
    return VerificationResult(ok, "OK" if ok else "MAIL_CLAIM_FEEDBACK_NOT_PROVEN", {"active_badge":before_ok, "reward_visible":reward})


def verify_mail_reward_dismissed(before: WorldState, after: WorldState) -> VerificationResult:
    reward_before = before.page is Page.POPUP and before.popup in {"MAIL_REWARD", "INTEL_REWARD", "GENERIC_REWARD"}
    ok = reward_before and after.page is Page.MAIL
    return VerificationResult(ok, "OK" if ok else "MAIL_REWARD_DISMISS_NOT_PROVEN", {"before_reward":reward_before, "after_mail":after.page is Page.MAIL})


def verify_mail_read_or_claim(before: WorldState, after: WorldState) -> VerificationResult:
    claimed = verify_mail_claim_feedback(before, after)
    if claimed.ok:
        return claimed
    active = before.mail.get("active_tab")
    read = (before.page is Page.MAIL and after.page is Page.MAIL
            and bool(before.mail.get("tab_badges", {}).get(active))
            and isinstance(after.mail.get("tab_badges"), dict)
            and after.mail.get("status") == "CLAIMED"
            and not after.mail["tab_badges"] and after.mail.get("badge_count") == 0)
    if read:
        return VerificationResult(True, "MAIL_NOTIFICATION_READ_NO_REWARD_PROVEN",
                                  {"notification_cleared": True, "reward_verified": False})
    before_count = before.mail.get("badge_count")
    after_count = after.mail.get("badge_count")
    badge_reduced = (
        before.page is Page.MAIL and after.page is Page.MAIL
        and isinstance(before_count, int) and isinstance(after_count, int)
        and 0 <= after_count < before_count
    )
    if badge_reduced:
        return VerificationResult(True, "MAIL_BADGE_REDUCTION_PROVEN",
                                  {"before_badges": before_count, "after_badges": after_count, "reward_verified": False})
    return claimed


def verify_exploration_idle_claim(before: WorldState, reward: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.EXPLORATION and before.exploration.get("status") == "CLAIMABLE"
    reward_ok = reward.page is Page.POPUP and reward.popup == "EXPLORATION_REWARD" and reward.exploration.get("claim_feedback") is True
    after_ok = after.page is Page.EXPLORATION and after.exploration.get("status") == "CLAIMED"
    ok = before_ok and reward_ok and after_ok
    return VerificationResult(ok, "OK" if ok else "EXPLORATION_CLAIM_NOT_PROVEN", {"before_ok":before_ok,"reward_ok":reward_ok,"after_ok":after_ok})


def verify_ally_gift_claim(before: WorldState, after: WorldState) -> VerificationResult:
    before_ok = before.page is Page.ALLIANCE and before.alliance.get("section") == "GIFTS" and before.alliance.get("tab") == "ALLY_GIFT" and before.alliance.get("status") == "CLAIMABLE"
    progress_delta = int(after.alliance.get("gift_progress", 0)) - int(before.alliance.get("gift_progress", 0))
    buttons_delta = int(before.alliance.get("visible_claim_buttons", 0)) - int(after.alliance.get("visible_claim_buttons", 0))
    claimed_delta = int(after.alliance.get("visible_claimed", 0)) - int(before.alliance.get("visible_claimed", 0))
    after_ok = after.page is Page.ALLIANCE and after.alliance.get("section") == "GIFTS" and after.alliance.get("tab") == "ALLY_GIFT"
    # Live evidence includes level-1 gifts worth 30 points and a level-3 gift
    # worth 120 points. The list can reorder immediately and a newly arrived gift
    # may replace the claimed row, so visible row counts are corroboration rather
    # than a mandatory state transition.
    progress_ok = 0 < progress_delta <= int(after.alliance.get("gift_progress_target", 150000))
    visible_transition = buttons_delta == 1 and claimed_delta == 1
    before_badge = before.alliance.get("badge_count")
    after_badge = after.alliance.get("badge_count")
    badge_transition = (
        isinstance(before_badge, int)
        and isinstance(after_badge, int)
        and after_badge == before_badge - 1
    )
    exhausted_transition = (
        int(before.alliance.get("visible_claim_buttons", 0)) == 1
        and int(after.alliance.get("visible_claim_buttons", 0)) == 0
        and after.alliance.get("status") == "CLAIMED"
    )
    action_transition = visible_transition or badge_transition or exhausted_transition
    ok = before_ok and after_ok and progress_ok and action_transition
    return VerificationResult(
        ok,
        "OK" if ok else "ALLY_GIFT_CLAIM_NOT_PROVEN",
        {
            "before_ok": before_ok,
            "after_ok": after_ok,
            "progress_delta": progress_delta,
            "progress_ok": progress_ok,
            "buttons_delta": buttons_delta,
            "claimed_delta": claimed_delta,
            "visible_transition": visible_transition,
            "badge_transition": badge_transition,
            "exhausted_transition": exhausted_transition,
            "list_replenished_or_reordered": badge_transition and not visible_transition,
        },
    )


def verify_rally_joined(before: WorldState, after: WorldState, target: str) -> VerificationResult:
    """Generic JOIN_RALLY verifier; clicking JOIN alone is never success."""
    before_used = before.march_used
    after_used = after.march_used
    queue_increased = isinstance(before_used, int) and isinstance(after_used, int) and after_used > before_used
    rally = after.alliance.get("rally", {}) if isinstance(after.alliance, dict) else {}
    member_state = rally.get("member_state") in {"JOINED", "MARCHING", "ARRIVED"}
    identity_ok = str(rally.get("target_type", target)).upper() == target.upper()
    ok = identity_ok and (queue_increased or member_state)
    return VerificationResult(ok, "OK" if ok else "RALLY_JOIN_NOT_PROVEN",
                              {"target":target, "queue_increased":queue_increased,
                               "member_state":rally.get("member_state")})


def verify_rally_created(before: WorldState, after: WorldState, target: str) -> VerificationResult:
    """Generic START_RALLY verifier, including Bear's non-normal special slot."""
    rally = after.alliance.get("rally", {}) if isinstance(after.alliance, dict) else {}
    own = rally.get("ownership") == "SELF"
    countdown = rally.get("remaining_seconds")
    countdown_started = isinstance(countdown, int) and countdown > 0
    identity_ok = str(rally.get("target_type", target)).upper() == target.upper()
    special_transition = target.upper() == "BEAR" and before.bear_rally_special_available is True and after.bear_rally_special_available is False
    ok = identity_ok and ((own and countdown_started) or special_transition)
    return VerificationResult(ok, "OK" if ok else "RALLY_CREATE_NOT_PROVEN",
                              {"target":target, "own":own, "countdown":countdown,
                               "special_slot_transition":special_transition})
