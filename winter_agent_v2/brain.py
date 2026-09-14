from __future__ import annotations

import json

from .models import Decision, MarchState, Page, WorldState
from .skills import SkillRegistry


class RuleBrain:
    """Strict deterministic fallback brain for P0; decides WHAT, never clicks."""

    def __init__(
        self,
        current_goal: str | None = None,
        reserve_marches: int = 0,
        recall_on_demand: bool = False,
        claim_free_stamina: bool = False,
    ) -> None:
        self.current_goal = current_goal
        self.reserve_marches = max(0, int(reserve_marches))
        # The operator directive of 2026-09-14 allows recalling a march at any
        # time, including to free a slot for a live-verification experiment.
        # ``pending_recall`` remembers that *this loop* opened the recall dialog,
        # so a dialog that appeared for any other reason is closed instead of
        # confirmed.
        self.recall_on_demand = bool(recall_on_demand)
        self.pending_recall = False
        # The same directive asks for the free stamina gift to be claimed.  The
        # only way to know whether it is available is to open the source panel,
        # because the map gauge never shows it, so the check runs once per run.
        self.claim_free_stamina = bool(claim_free_stamina)
        self.stamina_panel_checked = False

    def _recallable(self, world: WorldState) -> bool:
        """True when recalling a march is both allowed and useful.

        Only a GATHERING march may be recalled: a beast or intel march is
        already spending the stamina this directive asks us to spend, and
        recalling it would throw that cost away.
        """
        return (
            self.recall_on_demand
            and world.page is Page.MAP
            and not world.resource_search_open
            and world.idle_marches == 0
            and MarchState.GATHERING in world.marches
        )

    def decide(self, world: WorldState, registry: SkillRegistry) -> Decision:
        if not world.known:
            return Decision("SAFE_STOP", "unknown_page", 1.0, "no_action")
        # Maintenance and loading are environmental states.  Nothing in the
        # game can be acted on, and tapping would only restart the client, so
        # the loop waits instead of burning actions or exiting the worker.
        if world.page is Page.MAINTENANCE:
            return Decision("WAIT", "server_maintenance_notice", 1.0, "retry_when_servers_return")
        if world.page is Page.LOADING:
            return Decision("WAIT", "client_loading_screen", 1.0, "wait_for_game_page")
        if world.page is Page.POPUP and world.popup == "WELCOME_BACK_OFFLINE":
            return Decision("CLAIM_OFFLINE_REWARDS", "verified_welcome_back_rewards", world.confidence, "home_restored")
        if world.page is Page.POPUP and world.popup == "SESSION_DISCONNECTED":
            return Decision("RECONNECT_SESSION", "game_session_disconnected", world.confidence, "live_page_restored")
        if world.page is Page.POPUP and world.popup == "BATTLEFIELD_REVIVAL":
            return Decision("DISMISS_BATTLEFIELD_REVIVAL", "revival_event_interrupts_current_goal", world.confidence, "underlying_page_restored")
        if world.page is Page.POPUP and world.popup == "BATTLE_VICTORY_BANNER":
            return Decision("DISMISS_BATTLE_VICTORY", "battle_result_blocks_underlying_page", world.confidence, "underlying_page_restored")
        if world.page is Page.POPUP and world.popup == "REAL_MONEY_OFFER":
            return Decision("DISMISS_REAL_MONEY_OFFER", "real_money_action_permanently_blocked", world.confidence, "offer_closed_without_purchase")
        # A duplicate-target question means another of our teams already holds
        # the node this search produced.  Sending anyway burns a march on a
        # contested node, so cancel and let the next search offer a new one.
        # This must precede the generic blocking-popup branch because closing
        # it as an unknown popup would abandon the configured resource.
        if world.page is Page.POPUP and world.popup == "DUPLICATE_TARGET":
            return Decision("CANCEL_DUPLICATE_TARGET", "contested_resource_node_do_not_send", world.confidence, "search_panel_restored_for_new_node")
        if world.page is Page.POPUP and world.popup == "DAILY_REWARD":
            return Decision("DISMISS_DAILY_REWARD", "daily_reward_requires_continue_tap", world.confidence, "daily_reward_advanced")
        if world.page is Page.POPUP and world.popup == "GENERIC_REWARD":
            if self.current_goal == "MAIL":
                return Decision("DISMISS_MAIL_GENERIC_REWARD", "mail_goal_generic_reward_feedback", world.confidence, "mail_page_restored")
            if self.current_goal == "DAILY":
                return Decision("DISMISS_DAILY_GENERIC_REWARD", "daily_goal_generic_reward_feedback", world.confidence, "daily_reward_advanced")
            if self.current_goal == "INTEL":
                return Decision("DISMISS_INTEL_GENERIC_REWARD", "intel_goal_generic_reward_feedback", world.confidence, "intel_page_restored")
            if self.current_goal == "EXPLORATION":
                return Decision("DISMISS_EXPLORATION_GENERIC_REWARD", "exploration_goal_generic_reward_feedback", world.confidence, "exploration_claimed")
            if self.current_goal == "ALLIANCE":
                return Decision("DISMISS_ALLIANCE_GENERIC_REWARD", "alliance_goal_generic_reward_feedback", world.confidence, "alliance_gifts_restored")
            return Decision("SAFE_STOP", "generic_reward_without_goal_context", 1.0, "no_action")
        if world.page is Page.POPUP and world.popup == "INTEL_REWARD" and self.current_goal == "MAIL":
            return Decision("DISMISS_MAIL_GENERIC_REWARD", "mail_goal_generic_reward_feedback", world.confidence, "mail_page_restored")
        if world.page is Page.POPUP and world.popup == "INTEL_REWARD":
            return Decision("DISMISS_INTEL_REWARD", "intel_reward_requires_continue_tap", world.confidence, "intel_page_restored")
        if world.page is Page.POPUP and world.popup == "MAIL_REWARD":
            return Decision("DISMISS_MAIL_REWARD", "mail_reward_requires_continue_tap", world.confidence, "mail_page_restored")
        if world.page is Page.POPUP and world.popup == "EXPLORATION_REWARD":
            return Decision("DISMISS_EXPLORATION_REWARD", "exploration_reward_requires_dismiss", world.confidence, "exploration_claimed")
        if world.page is Page.POPUP and world.popup == "EXPLORATION_IDLE_DIALOG":
            return Decision("CONFIRM_EXPLORATION_IDLE_CLAIM", "verified_idle_income_dialog", world.confidence, "exploration_reward_feedback")
        if self.current_goal == "TRAIN" and world.page is Page.POPUP and world.popup == "POWER_OVERVIEW":
            return Decision("OPEN_POWER_DETAILS", "training_goal_power_overview", world.confidence, "power_details_open")
        if self.current_goal == "TRAIN" and world.page is Page.POPUP and world.popup == "POWER_DETAILS":
            return Decision("NAVIGATE_INFANTRY_CAMP", "training_goal_troop_power_route", world.confidence, "infantry_camp_highlighted")
        if world.page is Page.POPUP and world.popup == "INTEL_BEAST_MISSION":
            return Decision("OPEN_INTEL_BEAST_TARGET", "reviewed_intel_beast_mission", world.confidence, "intel_beast_target_open")
        if world.page is Page.POPUP and world.popup == "INTEL_RESCUE_SURVIVORS_MISSION":
            return Decision("OPEN_INTEL_RESCUE_SURVIVORS_TARGET", "reviewed_rescue_survivors_mission", world.confidence, "intel_rescue_target_open")
        if world.page is Page.MAP and world.popup == "INTEL_RESCUE_SURVIVORS_TARGET":
            return Decision("EXECUTE_INTEL_RESCUE_SURVIVORS", "rescue_target_and_cost_verified", world.confidence, "intel_rescue_in_progress")
        if world.page is Page.POPUP and world.popup == "INTEL_HERO_JOURNEY":
            # Live 2026-09-14: the operator asked for the intel board to be
            # drained; the hero-journey card shares the 前往查看 button with the
            # verified beast flow, so route it through the same machinery.
            return Decision("OPEN_INTEL_HERO_JOURNEY_TARGET", "reviewed_hero_journey_mission", world.confidence, "intel_hero_target_open")
        if world.page is Page.POPUP and world.popup == "INTEL_MASTER_BOUNTY":
            return Decision("BACK", "intel_master_bounty_power_blocked", 1.0, "intel_page_restored")
        if world.page is Page.POPUP and world.popup == "GET_MORE_STAMINA":
            # Only the free control is ever confirmed.  The panel also sells
            # stamina for diamonds; when there is no free gift the panel is
            # simply closed, which is why this branch precedes CLOSE_POPUP.
            if world.stamina.get("free_claim_available") is True:
                return Decision("CLAIM_FREE_STAMINA", "free_stamina_gift_claimable", world.confidence, "free_stamina_claimed")
            return Decision("BACK", "stamina_panel_without_a_free_gift", world.confidence, "map_restored")
        # The recall confirmation must be answered before the generic
        # blocking-popup rule, otherwise a deliberately opened recall dialog
        # would be closed instead of confirmed.  It is only confirmed when this
        # loop opened it; an unexplained recall dialog is closed unconfirmed.
        if world.page is Page.POPUP and world.popup == "MARCH_RECALL":
            if self.pending_recall:
                self.pending_recall = False
                return Decision("RECALL_MARCH", "recall_dialog_opened_by_this_loop", world.confidence, "march_returning_slot_freed_on_arrival")
            return Decision("CLOSE_POPUP", "recall_dialog_not_opened_by_this_loop", world.confidence, "dialog_closed_unconfirmed")
        if world.page is Page.POPUP and world.popup:
            return Decision("CLOSE_POPUP", "blocking_popup", world.confidence, "popup_closed")
        # Goal isolation precedes ordinary page actions. A reward sweep opened
        # on a resource or formation page must never inherit Gather behavior.
        if self.current_goal == "MAIL":
            if world.page is Page.HOME:
                return Decision("OPEN_MAIL", "mail_sweep_goal", world.confidence, "mail_page_open")
            if world.page is Page.MAP:
                if world.resource_search_open:
                    return Decision("BACK", "close_resource_search_for_mail_goal", world.confidence, "resource_search_closed")
                return Decision("OPEN_HOME", "mail_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.MAIL:
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_mail_route")
        if self.current_goal == "INTEL":
            if world.page is Page.HOME:
                return Decision("OPEN_MAP", "intel_goal_requires_map", world.confidence, "map_opened")
            if (
                world.page is Page.EXPLORATION
                and not world.intel
                and world.exploration.get("stamina_cost_displayed") is None
            ):
                # A camp panel with a stamina cost is the workable hero-journey
                # target (handled below); anything else on the exploration page
                # is not intel work, so leave it.
                return Decision("BACK", "leave_exploration_for_intel_goal", world.confidence, "home_restored")
            if world.page not in {Page.MAP, Page.INTEL, Page.BEAST, Page.MARCH, Page.EXPLORATION}:
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_intel_route")
            if world.page is Page.MAP and world.resource_search_open:
                return Decision("BACK", "close_resource_search_for_intel_goal", world.confidence, "resource_search_closed")
        if self.current_goal == "BEAST_HUNT":
            if world.page is Page.HOME:
                return Decision("OPEN_MAP", "beast_goal_requires_map", world.confidence, "map_opened")
            if world.page not in {Page.MAP, Page.BEAST, Page.MARCH}:
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_beast_route")
            if world.page is Page.MAP and world.resource_search_open:
                return Decision("BACK", "close_resource_search_for_beast_goal", world.confidence, "resource_search_closed")
        if (
            world.page is Page.EXPLORATION
            and self.current_goal == "INTEL"
            and world.exploration.get("stamina_cost_displayed") is not None
        ):
            # Live 2026-09-14: the Hero Journey camp panel classifies as the
            # exploration page (its 探险 ⚡10 button belongs to that system).
            # With the intel goal active this panel IS the workable target.
            return Decision("INTEL_HERO_START_MARCH", "intel_hero_camp_panel", world.confidence, "intel_hero_fight_started")
        if self.current_goal == "EXPLORATION":
            if world.page is Page.HOME:
                return Decision("OPEN_EXPLORATION", "exploration_goal", world.confidence, "exploration_open")
            if world.page is Page.MAP:
                return Decision("OPEN_HOME", "exploration_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.EXPLORATION:
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_exploration_route")
        if self.current_goal == "DAILY":
            if world.page is Page.HOME:
                return Decision("OPEN_DAILY", "daily_goal", world.confidence, "daily_open")
            if world.page is Page.MAP:
                return Decision("OPEN_HOME", "daily_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.DAILY:
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_daily_route")
            if world.daily.get("status") != "CLAIMABLE":
                return Decision("SAFE_STOP", "daily_no_claimable_rewards", 1.0, "switch_task")
        if self.current_goal == "ALLIANCE":
            if world.page is Page.HOME:
                return Decision("OPEN_ALLIANCE", "alliance_goal", world.confidence, "alliance_open")
            if world.page is Page.MAP:
                return Decision("OPEN_HOME", "alliance_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.ALLIANCE:
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_alliance_route")
            if world.alliance.get("section") == "HOME":
                return Decision("OPEN_ALLIANCE_GIFTS", "alliance_gifts_badge_visible", world.confidence, "alliance_gifts_open")
        if self.current_goal == "RESEARCH":
            if world.page is Page.HOME and world.research.get("queue_available") is False:
                return Decision("SAFE_STOP", "research_queue_busy", 1.0, "switch_task")
            if world.page is not Page.RESEARCH:
                return Decision("SAFE_STOP", "research_entry_not_verified", 1.0, "refresh_state_or_switch_task")
        if self.current_goal == "TRAIN":
            if world.page is Page.HOME and world.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED":
                return Decision("SELECT_INFANTRY_CAMP", "verified_infantry_camp_highlight", world.confidence, "infantry_camp_menu_open")
            if world.page is Page.HOME and world.training.get("menu_open"):
                return Decision("OPEN_INFANTRY_TRAINING", "idle_infantry_camp_selected", world.confidence, "training_page_open")
            if world.page is Page.HOME and world.training.get("queue_available") is False:
                return Decision("SAFE_STOP", "training_queue_busy", 1.0, "switch_task")
            if world.page is Page.HOME:
                return Decision("OPEN_POWER_OVERVIEW", "training_goal_requires_power_route", world.confidence, "power_overview_open")
            if world.page is not Page.TRAINING:
                return Decision("SAFE_STOP", "training_entry_not_verified", 1.0, "refresh_state_or_switch_task")
        if (
            world.page is Page.RESOURCE_DETAIL
            and world.resource_available is not True
            and any(m.value == "GATHERING" for m in world.marches)
        ):
            return Decision("VERIFY_GATHERING", "gathering_visible", world.confidence, "gathering_verified")
        if world.page is Page.RESOURCE_DETAIL and world.idle_marches is not None and world.idle_marches <= 0:
            return Decision("SAFE_STOP", "no_idle_march", 1.0, "wait_for_march_slot")
        if (
            world.page is Page.RESOURCE_DETAIL
            and self.current_goal in {None, "GATHER_RESOURCE"}
            and world.idle_marches is not None
            and world.idle_marches <= self.reserve_marches
        ):
            return Decision("SAFE_STOP", "reserved_march_for_stamina", 1.0, "stamina_task_slot_preserved")
        if world.page is Page.RESOURCE_DETAIL and world.resource_available:
            return Decision("START_GATHER", "resource_available", world.confidence, "march_page_open")
        if world.page is Page.BUILDING and world.building.get("upgradeable"):
            return Decision("BUILDING_UPGRADE", "building_prerequisites_satisfied", world.confidence, "building_queue_started")
        if world.page is Page.RESEARCH:
            if world.research.get("status") == "IN_PROGRESS" or world.research.get("queue_available") is False:
                return Decision("SAFE_STOP", "research_queue_busy", 1.0, "switch_task")
            if world.research.get("researchable"):
                return Decision("RESEARCH", "research_queue_available", world.confidence, "research_queue_started")
        if world.page is Page.TRAINING:
            if world.training.get("all_queues_busy"):
                return Decision("SAFE_STOP", "all_training_queues_busy", 1.0, "switch_task")
            if world.training.get("queue_available") is False:
                return Decision("SAFE_STOP", "training_queue_busy", 1.0, "inspect_other_training_queue")
            if world.training.get("trainable"):
                return Decision("TRAIN_TROOPS", "training_queue_available", world.confidence, "training_queue_started")
        if world.page is Page.INTEL:
            status = world.intel.get("status", "UNKNOWN")
            if status == "AVAILABLE" and not world.intel.get("mission_type") and not world.intel.get("list_read"):
                return Decision("READ_INTEL_LIST", "intel_list_requires_structured_observation", world.confidence, "intel_list_known")
            if status == "CLAIMABLE" and int(world.intel.get("claimable_count", 0)) > 0:
                return Decision("INTEL_CLAIM_REWARDS", "completed_intel_claimable", world.confidence, "intel_rewards_claimed")
            if status in {"NOT_AVAILABLE", "EXPIRED"}:
                return Decision("SAFE_STOP", f"intel_{status.lower()}", 1.0, "switch_task")
            if status == "UNKNOWN":
                return Decision("SAFE_STOP", "intel_state_unknown", 1.0, "refresh_state")
            if status == "AVAILABLE":
                if world.intel.get("mission_type") == "RESCUE_SURVIVORS":
                    return Decision("SELECT_INTEL_RESCUE_SURVIVORS", "rescue_survivors_intel_available", world.confidence, "intel_rescue_mission_detail_open")
                if world.intel.get("mission_type") == "FIREBEAST":
                    return Decision("SELECT_INTEL_FIREBEAST_MISSION", "firebeast_intel_available", world.confidence, "intel_firebeast_mission_detail_open")
                if world.intel.get("mission_type") == "BEAST":
                    return Decision("SELECT_INTEL_BEAST_MISSION", "ordinary_beast_intel_available", world.confidence, "intel_mission_detail_open")
                return Decision("SAFE_STOP", "intel_available_no_claim", 1.0, "inspect_or_execute_intel_mission")
        if world.page is Page.BEAST:
            if self.current_goal == "INTEL" and world.beast.get("mission_id") in {"INTEL_BEAST_10", "INTEL_FIREBEAST_10"} and world.beast.get("available"):
                return Decision("INTEL_BEAST_START_MARCH", "intel_beast_target_verified", world.confidence, "intel_beast_march_page_open")
            if self.current_goal == "INTEL" and not world.beast:
                # A Hero Journey camp target card: same layout as the beast
                # target card (the 出征 button drives the page) but without the
                # beast mission fields, which is how the two are told apart.
                return Decision("INTEL_HERO_START_MARCH", "intel_hero_target_open", world.confidence, "intel_hero_fight_started")
            if world.beast.get("available") and world.idle_marches and world.idle_marches > 0:
                return Decision("BEAST_HUNT", "beast_available_with_idle_march", world.confidence, "beast_defeated_and_returned")
            if world.beast.get("available") and world.march_used is None:
                return Decision("BEAST_HUNT", "verified_beast_target", world.confidence, "beast_march_page_open")
            return Decision("SAFE_STOP", "beast_not_actionable", 1.0, "switch_task")
        if world.page is Page.DAILY:
            if world.daily.get("status") == "CLAIMABLE":
                return Decision("DAILY_CLAIM_REWARDS", "daily_task_claimable", world.confidence, "daily_activity_increased")
            if world.daily.get("task_id") == "HERO_RECRUIT_1" and world.daily.get("status") == "AVAILABLE":
                return Decision("DAILY_HERO_RECRUIT", "free_recruit_daily_available", world.confidence, "daily_task_claimable")
            return Decision("SAFE_STOP", "daily_state_unknown_or_not_actionable", 1.0, "refresh_state_or_switch_task")
        if world.page is Page.ALLIANCE:
            if world.alliance.get("section") == "GIFTS" and world.alliance.get("status") == "CLAIMABLE":
                if world.alliance.get("tab") == "ALLY_GIFT":
                    return Decision("ALLIANCE_ALLY_GIFT_CLAIM", "ally_gift_claimable", world.confidence, "one_ally_gift_claimed")
                return Decision("ALLIANCE_GIFTS", "alliance_gifts_claimable", world.confidence, "gift_counter_increased_and_list_claimed")
            if world.alliance.get("section") == "TECHNOLOGY" and world.alliance.get("status") == "AVAILABLE":
                return Decision("ALLIANCE_TECH_CONTRIBUTE", "normal_resource_contribution_available", world.confidence, "contribution_counter_increased")
            if world.alliance.get("section") == "HELP" and world.alliance.get("auto_help_active"):
                return Decision("SAFE_STOP", "alliance_help_auto_active", 1.0, "switch_task")
            if world.alliance.get("status") in {"NOT_AVAILABLE", "CONTRIBUTED", "CLAIMED"}:
                return Decision("SAFE_STOP", "alliance_action_not_needed", 1.0, "switch_task")
            return Decision("SAFE_STOP", "alliance_state_unknown", 1.0, "refresh_state")
        if world.page is Page.MAIL:
            badges = world.mail.get("tab_badges", {})
            active_tab = world.mail.get("active_tab")
            if isinstance(badges, dict) and badges:
                if active_tab in badges:
                    return Decision("MAIL_CLAIM_REWARDS", "active_mail_tab_has_reward", world.confidence, "mail_reward_feedback")
                for tab, skill in (("ALLIANCE", "SELECT_MAIL_ALLIANCE_TAB"), ("SYSTEM", "SELECT_MAIL_SYSTEM_TAB"), ("REPORT", "SELECT_MAIL_REPORT_TAB")):
                    if badges.get(tab):
                        return Decision(skill, f"mail_{tab.lower()}_badge_visible", world.confidence, f"mail_{tab.lower()}_tab_active")
                return Decision("SAFE_STOP", "mail_badge_tab_not_supported", 1.0, "refresh_or_switch_task")
            if world.mail.get("status") == "CLAIMED":
                return Decision("SAFE_STOP", "mail_all_clear", 1.0, "switch_task")
            if world.mail.get("status") == "CLAIMABLE":
                return Decision("MAIL_CLAIM_REWARDS", "mail_attachment_or_unread_available", world.confidence, "mail_reward_feedback")
            return Decision("SAFE_STOP", "mail_state_unknown", 1.0, "refresh_state")
        if world.page is Page.EXPLORATION:
            if world.exploration.get("status") == "CLAIMABLE":
                return Decision("EXPLORATION_IDLE_CLAIM", "idle_income_claimable", world.confidence, "idle_income_claimed")
            return Decision("SAFE_STOP", "exploration_income_not_ready", 1.0, "switch_task")
        if world.page is Page.MAP:
            # Free stamina first: it costs nothing, it is time-limited (the
            # panel shows 下次补给 with a countdown), and it is only visible if
            # the panel is opened.  Once per run, so it cannot become a loop.
            if (
                self.claim_free_stamina
                and not self.stamina_panel_checked
                and not world.resource_search_open
                and world.stamina.get("current") is not None
            ):
                self.stamina_panel_checked = True
                return Decision("OPEN_STAMINA_SOURCES", "free_stamina_gift_not_yet_checked_this_run", world.confidence, "stamina_sources_open")
            if self.current_goal == "INTEL":
                return Decision("OPEN_INTEL", "intel_goal_from_world_map", world.confidence, "intel_page_open")
            if self.current_goal == "BEAST_HUNT":
                if world.idle_marches is not None and world.idle_marches <= 0:
                    if self._recallable(world):
                        self.pending_recall = True
                        return Decision("SELECT_MARCH_TO_RECALL", "stamina_goal_needs_a_slot_and_only_gathering_marches_remain", world.confidence, "recall_dialog_open")
                    return Decision("SAFE_STOP", "no_idle_march", 1.0, "wait_for_beast_slot")
                if world.beast.get("visible_target") == "MUSK_OX" and world.beast.get("level") == 9:
                    return Decision("SELECT_BEAST_TARGET", "verified_visible_low_level_beast", world.confidence, "beast_target_dialog_open")
                return Decision("SAFE_STOP", "verified_beast_target_not_visible", 1.0, "refresh_or_switch_task")
            if self.current_goal == "HOME":
                return Decision("OPEN_HOME", "current_goal_home", world.confidence, "home_opened")
            if (
                self.current_goal in {None, "GATHER_RESOURCE"}
                and world.idle_marches is not None
                and world.idle_marches <= self.reserve_marches
                and world.resource_search_open
            ):
                return Decision("BACK", "close_resource_search_to_preserve_stamina_slot", world.confidence, "resource_search_closed")
            desired_resource = world.resource_target or "WOOD"
            if world.resource_search_open and world.resource_selected == desired_resource:
                # A configured search that already came back empty means the
                # level filter excluded every nearby node. Loosen one step
                # instead of re-submitting the identical query, which would
                # fail the same way. Never relax below the minimum.
                if (
                    world.resource_search_exhausted
                    and world.resource_level is not None
                    and world.resource_level > 1
                ):
                    return Decision(
                        "RELAX_RESOURCE_LEVEL",
                        "no_node_matched_current_level_filter",
                        world.confidence,
                        "resource_level_relaxed",
                    )
                return Decision("SUBMIT_RESOURCE_SEARCH", "balanced_resource_search_configured", world.confidence, "resource_found")
            if world.resource_search_open:
                return Decision("SELECT_RESOURCE", "balanced_resource_not_selected", world.confidence, f"{desired_resource.lower()}_selected")
            if world.idle_marches is None:
                return Decision("CHECK_MARCH", "march_capacity_unknown", world.confidence, "march_state_known")
            if world.idle_marches <= 0:
                # Operator directive: a march may be released on demand.  Only
                # a GATHERING march is eligible (see _recallable); a dialog this
                # decision opens is confirmed by the RECALL_MARCH branch.
                if self._recallable(world):
                    self.pending_recall = True
                    return Decision("SELECT_MARCH_TO_RECALL", "no_idle_march_and_a_gathering_march_can_be_released", world.confidence, "recall_dialog_open")
                return Decision("SAFE_STOP", "no_idle_march", 1.0, "no_action")
            if self.current_goal in {None, "GATHER_RESOURCE"} and world.idle_marches <= self.reserve_marches:
                return Decision("SAFE_STOP", "reserved_march_for_stamina", 1.0, "stamina_task_slot_preserved")
            return Decision("SEARCH_RESOURCE", "idle_march_available", world.confidence, "resource_search_open")
        if world.page is Page.MARCH and world.beast:
            if world.beast.get("victory_assured") is True:
                if self.current_goal == "INTEL" or world.beast.get("level") == 22:
                    return Decision("DISPATCH_INTEL_BEAST", "intel_beast_victory_assured", world.confidence, "intel_beast_march_dispatched")
                return Decision("DISPATCH_BEAST", "beast_victory_assured", world.confidence, "beast_march_dispatched")
            return Decision("SAFE_STOP", "beast_low_win_probability", 1.0, "choose_lower_target")
        if world.page is Page.MARCH:
            # The gathering formation page had no branch at all, so it fell
            # through to the generic "first ready skill" fallback below.  That
            # fallback walks the registry in insertion order and the first skill
            # whose required_page is None is WAIT (an environment hold), so a
            # live gather run reached the formation page and then waited
            # forever instead of dispatching.  Measured live on 2026-09-14:
            # START_GATHER verified, then the loop picked WAIT and the run ended
            # with ENVIRONMENTAL_WAIT_NOT_PROVEN.
            #
            # A gather march page means the formation is already configured by
            # the game's own default selection, so the correct action is to
            # dispatch and let the march verifier prove the state change.
            if self.current_goal in {None, "GATHER_RESOURCE"} or world.resource_target:
                return Decision(
                    "DISPATCH_MARCH",
                    "resource_march_formation_open",
                    world.confidence,
                    "gather_march_dispatched",
                )
        ready = registry.ready(world)
        if ready:
            # A placeholder skill must never win the fallback.  WAIT only means
            # "hold while an environmental state resolves", and every
            # environmental state is handled explicitly above; letting it be
            # chosen here silently stalls whatever page the loop is actually on.
            actionable = [skill for skill in ready if skill.id != "WAIT"]
            skill = (actionable or ready)[0]
            return Decision(skill.id, "first_ready_p0_skill", world.confidence, skill.description)
        return Decision("SAFE_STOP", "no_ready_skill", 1.0, "no_action")


def parse_qwen_decision(text: str, registry: SkillRegistry) -> Decision:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("REJECT: invalid JSON") from exc
    required = {"skill", "reason", "confidence", "expected_result"}
    if set(payload) != required:
        raise ValueError("REJECT: invalid decision schema")
    if payload["skill"] != "SAFE_STOP" and registry.get(payload["skill"]) is None:
        raise ValueError("REJECT: unknown skill")
    confidence = float(payload["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("REJECT: confidence out of range")
    return Decision(payload["skill"], str(payload["reason"]), confidence, str(payload["expected_result"]))
