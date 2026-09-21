from __future__ import annotations

from dataclasses import dataclass

from .models import Action, LatencyClass, Page, SkillState, WorldState

# The client draws ONE 获得奖励 dialog for every reward source and its artwork
# does not name the source, so the only region of it that is both
# source-independent and tappable is the 「点击任意位置退出」 footer.  The
# manifest record is named after Intel because it was cut from an Intel frame,
# but that name is a misnomer: measured over 103 labelled production frames it
# matches 102 of them at distance <= 2 whatever produced the dialog (see
# tests/test_reward_popup_source.py and tools/probe_reward_popup_gate.py).  It is
# the dialog's *declared exit*, not an Intel control, which is why it is the
# target of every dismiss that has no page of its own.
#
# Why no dismiss taps POPUP_GENERIC_REWARD_HEADER any more.  vision.py recognises
# this dialog by ``banner OR footer``, so the footer alone is enough to report
# POPUP/GENERIC_REWARD -- but the dismisses asked the executor for the BANNER, and
# the banner rides its own tolerance.  Measured over six live dialog frames the
# banner scores 14 / 16 / 18 / 20 / 26 against a tolerance of 16, while the footer
# scores 0-2 against 8:
#
#   frame                                    banner(16)   footer(8)   observe()
#   runtime_auto/20260919_132726_620764/…4       18 ✗        2 ✓      POPUP/GENERIC_REWARD
#   runtime_auto/20260920_204143_843357/…1       16 ✓        2 ✓      POPUP/GENERIC_REWARD
#   runtime_auto/20260920_205148_722868/…1       16 ✓        2 ✓      POPUP/GENERIC_REWARD
#   runtime_auto/20260920_211101_334048/…9       14 ✓        0 ✓      POPUP/GENERIC_REWARD
#
# So the dialog was recognised, the brain picked a dismiss, and the executor could
# not aim it: 45 of the 51 all-time failures of the old target are
# SEMANTIC_TARGET_NOT_VERIFIED -- no tap was ever issued.  The fix is to aim at the
# signal that actually matched.  Frames and the full table:
# dataset/truth_audit/reward_popup_exit_20260920/README.md.
#
# Note for a later reader: this is NOT the claim that the banner is an inert
# control.  It is not -- on 2026-09-20T13:09:49Z a banner tap did close the dialog
# (the after frame shows the next dialog, not this one).  What it does not do is
# resolve reliably, and even when it resolves it does not always dismiss (the
# 12:52:01 step resolved it at 16, tapped, and the dialog was still on screen 8 s
# later).  An earlier version of this comment said "tapping it does nothing"; the
# frames say otherwise, and that sentence has been corrected rather than left.
SHARED_REWARD_EXIT = "BTN_DISMISS_INTEL_REWARD"

# The verifier the goal-neutral close is bound to.  It is deliberately the
# shape-blind one: before is a popup, after is not a popup.  A per-domain
# verifier would demand the domain's page back, and the dialog can sit over any
# page, so binding one would reject a dismissal that worked -- the 2026-09-16
# failure this dialog already produced once.
SHARED_REWARD_VERIFIER = "POPUP_CLOSED"


@dataclass(frozen=True)
class Skill:
    id: str
    description: str
    required_page: Page | None
    action: Action
    timeout: float = 15.0
    risk: str = "LOW"
    state: SkillState = SkillState.CANDIDATE
    latency_class: LatencyClass = LatencyClass.NORMAL
    preconditions: tuple[str, ...] = ()
    verifier: str | None = None
    recovery: tuple[str, ...] = ()
    cost: str = "NONE"
    semantic_goal: str = ""
    parameters: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    semantic_requirements: tuple[str, ...] = ()
    vision_evidence: tuple[str, ...] = ()
    unknown_policy: str = ""
    ui_change_tolerance: tuple[str, ...] = ()

    def ready(self, world: WorldState) -> bool:
        return world.known and (self.required_page is None or world.page is self.required_page)

    @property
    def semantic_contract_complete(self) -> bool:
        return bool(self.semantic_goal and self.semantic_requirements and self.unknown_policy
                    and self.ui_change_tolerance and self.verifier and self.recovery)


class SkillRegistry:
    def __init__(self, skills: list[Skill]) -> None:
        self._skills = {skill.id: skill for skill in skills}

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def ready(self, world: WorldState) -> list[Skill]:
        return [skill for skill in self._skills.values() if skill.state is not SkillState.BLOCKED and skill.ready(world)]

    def all(self) -> list[Skill]:
        return list(self._skills.values())


def p0_registry() -> SkillRegistry:
    return SkillRegistry([
        Skill("CLOSE_POPUP", "Close a blocking popup without accepting it", Page.POPUP, Action("TAP_SEMANTIC", "BTN_CLOSE"), state=SkillState.VERIFIED),
        # The second exit for a layer another goal owned: Back first, and when the layer
        # ignores it, the close the client draws in its own corner.  Measured 2026-09-21 on
        # the alliance chest layer -- PRESS_BACK left page ALLIANCE reading ALLIANCE, and the
        # X at (682, 38) is what that layer answers.  Declared on Page.ALLIANCE rather than
        # POPUP because the layer IS an alliance sub-page: a POPUP declaration is the thing
        # that would keep the skill from being selected exactly when it is needed.
        Skill("LEAVE_FOREIGN_LAYER", "Leave a sub-layer another goal owned when a Back did not move it", Page.ALLIANCE, Action("TAP_SEMANTIC", "BTN_CLOSE"), state=SkillState.VERIFIED),
        Skill("RECONNECT_SESSION", "Reconnect a disconnected game session without changing account settings", Page.POPUP, Action("TAP_SEMANTIC", "BTN_RECONNECT_SESSION"), state=SkillState.CANDIDATE),
        Skill("DISMISS_BATTLEFIELD_REVIVAL", "Dismiss the battlefield-revival event without spending revival resources", Page.POPUP, Action("PRESS_BACK"), state=SkillState.CANDIDATE),
        Skill("DISMISS_BATTLE_VICTORY", "Dismiss a verified battle-result blocker and restore its underlying page", Page.POPUP, Action("PRESS_BACK"), state=SkillState.CANDIDATE),
        Skill("DISMISS_REAL_MONEY_OFFER", "Close a real-money offer without interacting with its purchase surface", Page.POPUP, Action("PRESS_BACK"), state=SkillState.CANDIDATE),
        Skill("DISMISS_INTEL_REWARD", "Dismiss the verified Intel reward overlay by tapping its continue surface", Page.POPUP, Action("TAP_SEMANTIC", "BTN_DISMISS_INTEL_REWARD"), state=SkillState.VERIFIED),
        Skill(
            "CANCEL_DUPLICATE_TARGET",
            "Cancel the duplicate-target question so a contested resource node is not marched and the search can offer another",
            Page.POPUP,
            Action("TAP_SEMANTIC", "BTN_DUPLICATE_TARGET_CANCEL"),
            state=SkillState.VERIFIED,
        ),
        Skill("SELECT_INTEL_BEAST_MISSION", "Select a verified blue, purple, or orange Beast Intel pin", Page.INTEL, Action("TAP_SEMANTIC", "TARGET_INTEL_BEAST_MISSION"), state=SkillState.VERIFIED),
        Skill("SELECT_INTEL_FIREBEAST_MISSION", "Select a current-client verified Firebeast Intel pin", Page.INTEL, Action("TAP_SEMANTIC", "TARGET_INTEL_FIREBEAST_MISSION"), state=SkillState.VERIFIED),
        Skill("SELECT_INTEL_RESCUE_SURVIVORS", "Select a current-client verified Rescue Survivors Intel pin", Page.INTEL, Action("TAP_SEMANTIC", "TARGET_INTEL_RESCUE_SURVIVORS"), state=SkillState.VERIFIED),
        Skill("SELECT_INTEL_PIN", "Tap the next untried Intel mission pin so its card opens and its mission type can be read",
              Page.INTEL,
              Action("TAP_SEMANTIC", "INTEL_PIN"),
              state=SkillState.VERIFIED,
              verifier="INTEL_PIN_OPENED", recovery=("BACK",),
              semantic_goal="Work an intel mission whose type is not yet known",
              parameters=(), context=("WORLD",),
              semantic_requirements=("intel_page_open", "pin_sighted"),
              vision_evidence=("intel_pin_board",),
              unknown_policy="No sighted pin blocks the tap; the loop never guesses a coordinate",
              ui_change_tolerance=("number", "position", "resolution")),
        Skill("OPEN_INTEL_RESCUE_SURVIVORS_TARGET", "Open the reviewed Rescue Survivors target", Page.POPUP, Action("TAP_SEMANTIC", "BTN_INTEL_VIEW_TARGET"), state=SkillState.VERIFIED),
        Skill("OPEN_INTEL_HERO_JOURNEY_TARGET", "Open the Hero Journey intel target from its mission card", Page.POPUP,
              Action("TAP_SEMANTIC", "BTN_INTEL_VIEW_TARGET"),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="INTEL_HERO_TARGET_OPEN", recovery=("BACK",),
              semantic_goal="Work an intel hero-journey mission", parameters=(), context=("WORLD",),
              semantic_requirements=("hero_journey_card_open", "go_view_available"),
              vision_evidence=("intel_mission_card",), unknown_policy="Missing button blocks",
              ui_change_tolerance=("number", "position", "resolution")),
        Skill("INTEL_HERO_START_MARCH", "Tap the measured 探险 ⚡10 fight button on a Hero Journey camp panel", Page.EXPLORATION,
              Action("TAP_SEMANTIC", "BTN_HERO_CAMP_FIGHT"),
              risk="MEDIUM_STAMINA_SPEND", state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="INTEL_HERO_MARCH_OPEN", recovery=("BACK",),
              semantic_goal="March to the hero-journey camp", parameters=(), context=("WORLD",),
              semantic_requirements=("hero_target_visible", "march_button_available"),
              vision_evidence=("target_card",), unknown_policy="Missing button blocks",
              ui_change_tolerance=("number", "position", "resolution")),
        Skill("INTEL_HERO_DISPATCH", "Fight the Hero Journey camp from its squad-setup page (战斗)", Page.MARCH,
              Action("TAP_SEMANTIC", "BTN_HERO_FIGHT"),
              risk="MEDIUM_STAMINA_SPEND", state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="INTEL_HERO_DISPATCHED", recovery=("BACK",),
              semantic_goal="Fight the hero-journey camp", parameters=(), context=("WORLD",),
              semantic_requirements=("formation_ready", "dispatch_available"),
              vision_evidence=("march_state",), unknown_policy="Missing button blocks",
              ui_change_tolerance=("number", "position", "resolution")),
        Skill("EXECUTE_INTEL_RESCUE_SURVIVORS", "Start Rescue Survivors after its 12-stamina cost is visible", Page.MAP, Action("TAP_SEMANTIC", "BTN_INTEL_RESCUE_SURVIVORS"), risk="MEDIUM_STAMINA_SPEND", state=SkillState.VERIFIED),
        Skill("OPEN_INTEL_BEAST_TARGET", "Open the world target for the reviewed Beast Intel mission", Page.POPUP, Action("TAP_SEMANTIC", "BTN_INTEL_VIEW_TARGET"), state=SkillState.VERIFIED),
        Skill("OPEN_INTEL", "Open Lighthouse Intel from the current world-map HUD", Page.MAP, Action("TAP_SEMANTIC", "BTN_OPEN_INTEL_WILD_HUD"), state=SkillState.VERIFIED),
        Skill("READ_INTEL_LIST", "Read visible Intel mission status and type without clicking", Page.INTEL, Action("OBSERVE", "INTEL_LIST"), state=SkillState.CANDIDATE),
        Skill("OPEN_MAP", "Open world map", Page.HOME, Action("TAP_SEMANTIC", "PAGE_MAP"), state=SkillState.VERIFIED),
        Skill("OPEN_HOME", "Return from world map to city", Page.MAP, Action("TAP_SEMANTIC", "BTN_OPEN_HOME"), state=SkillState.VERIFIED),
        Skill("SEARCH_RESOURCE", "Open resource search", Page.MAP, Action("TAP_SEMANTIC", "BTN_OPEN_RESOURCE_SEARCH"), state=SkillState.VERIFIED),
        Skill("SELECT_RESOURCE", "Select the balanced resource chosen by policy", Page.MAP, Action("TAP_SEMANTIC", "RESOURCE_DYNAMIC"), state=SkillState.CANDIDATE),
        Skill("SUBMIT_RESOURCE_SEARCH", "Find a configured resource node", Page.MAP, Action("TAP_SEMANTIC", "BTN_RESOURCE_SEARCH_SUBMIT"), state=SkillState.VERIFIED),
        Skill(
            "RELAX_RESOURCE_LEVEL",
            "Lower the resource-search level filter by one step so a node that matches the looser condition can be found instead of reporting none",
            Page.MAP,
            Action("TAP_SEMANTIC", "RESOURCE_LEVEL_MINUS"),
            state=SkillState.CANDIDATE,
        ),
        Skill("START_GATHER", "Open march selection for an available resource", Page.RESOURCE_DETAIL, Action("TAP_SEMANTIC", "BTN_GATHER"), state=SkillState.VERIFIED),
        Skill("CHECK_MARCH", "Observe march availability", Page.MAP, Action("OBSERVE", "MARCH_QUEUE"), state=SkillState.VERIFIED),
        Skill(
            "WAIT",
            "Hold without touching the client while an environmental state (maintenance window or client loading) resolves on its own",
            None,
            Action("OBSERVE", "ENVIRONMENTAL_WAIT"),
            state=SkillState.CANDIDATE,
        ),
        Skill(
            "WAIT_FOR_CAMP_MENU",
            "Re-observe after the infantry camp highlight while its radial menu draws (training route Stage A).  Sends no input on purpose: tapping the camp before the menu is drawn moves the client to the map.",
            Page.HOME,
            Action("OBSERVE", "CAMP_MENU_PENDING"),
            timeout=10.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
        Skill("DISPATCH_MARCH", "Dispatch selected march", Page.MARCH, Action("TAP_SEMANTIC", "BTN_DISPATCH"), state=SkillState.VERIFIED),
        Skill("VERIFY_GATHERING", "Verify gathering state", Page.RESOURCE_DETAIL, Action("OBSERVE", "STATUS_GATHERING"), state=SkillState.VERIFIED),
        Skill("BACK", "Return one game-navigation level", None, Action("PRESS_BACK"), state=SkillState.VERIFIED),
        Skill("OPEN_MAIL", "Open Mail from the current-client Home sidebar", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_MAIL"), state=SkillState.VERIFIED),
        Skill("OPEN_ALLIANCE", "Open Alliance from the current-client Home bottom navigation", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_ALLIANCE"), state=SkillState.VERIFIED),
        Skill("OPEN_EXPLORATION", "Open Exploration from the current-client Home bottom navigation", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_EXPLORATION"), state=SkillState.VERIFIED),
        Skill("DISMISS_EXPLORATION_REWARD", "Dismiss a verified Exploration idle reward", Page.POPUP, Action("TAP_SEMANTIC", "POPUP_EXPLORATION_REWARD"), state=SkillState.VERIFIED),
        Skill("CONFIRM_EXPLORATION_IDLE_CLAIM", "Confirm collection in the verified Exploration idle-income dialog", Page.POPUP, Action("TAP_SEMANTIC", "BTN_EXPLORATION_IDLE_CONFIRM"), state=SkillState.VERIFIED),
        Skill("CLAIM_OFFLINE_REWARDS", "Claim the verified normal-resource welcome-back reward", Page.POPUP, Action("TAP_SEMANTIC", "BTN_CLAIM_OFFLINE_REWARDS"), state=SkillState.CANDIDATE),
        Skill("OPEN_DAILY", "Open Daily Tasks from the current-client Home task icon", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_DAILY"), state=SkillState.CANDIDATE),
        Skill("SELECT_DAILY_TAB", "Switch the task panel from 章节任务 to 每日任务", Page.DAILY, Action("TAP_SEMANTIC", "BTN_DAILY_TAB_TASKS"), state=SkillState.CANDIDATE),
        Skill("OPEN_POWER_OVERVIEW", "Open the current-client power overview from Home", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_POWER_OVERVIEW_ICON"), state=SkillState.CANDIDATE),
        Skill("OPEN_POWER_DETAILS", "Open power-category details", Page.POPUP, Action("TAP_SEMANTIC", "BTN_OPEN_POWER_DETAILS"), state=SkillState.CANDIDATE),
        Skill("NAVIGATE_INFANTRY_CAMP", "Use Troop Power improvement to highlight the infantry camp", Page.POPUP, Action("TAP_SEMANTIC", "BTN_POWER_TROOP_IMPROVE"), state=SkillState.CANDIDATE),
        # The stage A hop: the camp is highlighted and no radial menu is drawn yet.  Its
        # target is the ring's centre, read off the current frame, not the template's own
        # centre -- measured on all 46 live stage A frames, the template centre sits 103 px
        # below the ring, on bare ground, and a tap there is a map tap (see camp_ring.py).
        Skill("SELECT_INFANTRY_CAMP", "Select the highlighted infantry camp", Page.HOME, Action("TAP_SEMANTIC", "TRAINING_CAMP_IN_RING"), state=SkillState.CANDIDATE),
        Skill("OPEN_INFANTRY_TRAINING", "Open training from the selected infantry camp", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_TRAINING_FROM_CAMP"), state=SkillState.CANDIDATE),
        # The 科技研究 route, the same shape as the training one.  The route itself was
        # verified on 2026-09-04 (knowledge/skills/RESEARCH_RESEARCH.md line 38) but
        # never wired here, and both of its controls are templates that had to be cut
        # from today's client -- the old BTN_OPEN_RESEARCH centre sat ~65 px off the
        # 研究 button.  See tools/register_research_route_templates.py.
        Skill("NAVIGATE_RESEARCH_LAB", "Use Technology Power improvement to highlight the 科研所", Page.POPUP, Action("TAP_SEMANTIC", "BTN_POWER_RESEARCH_IMPROVE"), state=SkillState.CANDIDATE),
        Skill("OPEN_RESEARCH", "Open 科技研究 from the focused 科研所", Page.HOME, Action("TAP_SEMANTIC", "BTN_OPEN_RESEARCH"), state=SkillState.CANDIDATE),
        Skill("DISMISS_DAILY_REWARD", "Advance one verified Daily reward overlay", Page.POPUP, Action("TAP_SEMANTIC", "POPUP_DAILY_REWARD_CURRENT"), state=SkillState.CANDIDATE),
        Skill("SELECT_MAIL_ALLIANCE_TAB", "Open the Alliance mail category", Page.MAIL, Action("TAP_SEMANTIC", "BTN_MAIL_TAB_ALLIANCE"), state=SkillState.VERIFIED),
        Skill("SELECT_MAIL_SYSTEM_TAB", "Open the System mail category", Page.MAIL, Action("TAP_SEMANTIC", "BTN_MAIL_TAB_SYSTEM"), state=SkillState.VERIFIED),
        Skill("SELECT_MAIL_REPORT_TAB", "Open the Report mail category", Page.MAIL, Action("TAP_SEMANTIC", "BTN_MAIL_TAB_REPORT"), state=SkillState.VERIFIED),
        Skill("DISMISS_MAIL_REWARD", "Dismiss the verified Mail reward overlay", Page.POPUP, Action("TAP_SEMANTIC", "POPUP_MAIL_REWARD"), state=SkillState.VERIFIED),
        # The five domain dismisses all tap the dialog's own declared exit rather
        # than its title band.  Their verifiers are what make them per-domain:
        # each demands its own page back afterwards, so the goal still has to be
        # right.  The tap target is shared because the dialog only has one
        # dismissible surface -- see SHARED_REWARD_EXIT above.
        Skill("DISMISS_MAIL_GENERIC_REWARD", "Dismiss a generic reward overlay attributed to the active Mail goal", Page.POPUP, Action("TAP_SEMANTIC", SHARED_REWARD_EXIT), state=SkillState.CANDIDATE),
        Skill("DISMISS_DAILY_GENERIC_REWARD", "Dismiss a generic reward overlay attributed to the active Daily goal", Page.POPUP, Action("TAP_SEMANTIC", SHARED_REWARD_EXIT), state=SkillState.CANDIDATE),
        Skill("DISMISS_INTEL_GENERIC_REWARD", "Dismiss a generic reward overlay attributed to the active Intel goal", Page.POPUP, Action("TAP_SEMANTIC", SHARED_REWARD_EXIT), state=SkillState.CANDIDATE),
        Skill("DISMISS_EXPLORATION_GENERIC_REWARD", "Dismiss a generic reward overlay attributed to the active Exploration goal", Page.POPUP, Action("TAP_SEMANTIC", SHARED_REWARD_EXIT), state=SkillState.CANDIDATE),
        Skill("OPEN_ALLIANCE_GIFTS", "Open Alliance Gifts from the current Alliance home", Page.ALLIANCE, Action("TAP_SEMANTIC", "BTN_OPEN_ALLIANCE_GIFTS"), state=SkillState.CANDIDATE),
        Skill("DISMISS_ALLIANCE_GENERIC_REWARD", "Dismiss a generic reward overlay attributed to the active Alliance goal", Page.POPUP, Action("TAP_SEMANTIC", SHARED_REWARD_EXIT), state=SkillState.CANDIDATE),
        # The goal-neutral close, for every goal that cannot name the page the
        # dialog covers.  It exists because a goal-neutral dismissal is not a
        # guess: the dialog says 点击任意位置退出 on itself, so its exit is
        # something the client declares rather than something we infer.  Before
        # it existed, such a goal stopped the run (SAFE_STOP) and the dialog
        # survived into the next round; measured live 2026-09-20, that was five
        # of six AUTO rounds in twenty minutes.
        Skill(
            "DISMISS_SHARED_REWARD",
            "Dismiss the client's shared 获得奖励 dialog by the exit it declares",
            Page.POPUP,
            Action("TAP_SEMANTIC", SHARED_REWARD_EXIT),
            state=SkillState.CANDIDATE,
            risk="LOW",
            semantic_goal="Clear a reward dialog that blocks the goal's next step, without claiming anything",
            verifier=SHARED_REWARD_VERIFIER,
            recovery=("REFRESH_STATE", "BACK"),
            semantic_requirements=("popup_present_before", "the dialog declares its own exit"),
            vision_evidence=("shared_reward_exit_band",),
            unknown_policy="Unknown dialog blocks nothing here: the exit band is present on 102 of 103 labelled reward dialogs, and a frame without it fails the verifier instead of tapping blind",
            ui_change_tolerance=("number", "reward_contents", "source_domain", "position", "resolution"),
        ),
    ])


def v2_registry() -> SkillRegistry:
    """The one registry, extended only by independently verified capabilities."""
    skills = p0_registry().all()
    skills.extend([
        Skill(
            "START_RALLY", "Start a parameterized rally for Bear, Polar Terror, Fortress, or another verified target",
            None, Action("START_RALLY", payload={"target":"FROM_GOAL", "context":"FROM_WORLD_STATE"}),
            timeout=30.0, risk="MEDIUM_COMBAT", state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
            semantic_goal="Create a rally against the goal-selected target",
            parameters=("target", "context", "formation"), context=("RALLY_LEADER",),
            semantic_requirements=("target_matches_policy", "rally_start_available", "formation_valid"),
            vision_evidence=("page_context", "target_semantic", "rally_button_state"),
            verifier="RALLY_CREATED", recovery=("REFRESH_RALLY_STATE", "RESELECT_TARGET"),
            unknown_policy="Unknown target or cost blocks; unknown target artwork does not block when semantic target is verified",
            ui_change_tolerance=("icon", "number", "position", "resolution", "skin"),
        ),
        Skill(
            "JOIN_RALLY", "Join a parameterized rally using a normal march slot and the context troop policy",
            None, Action("JOIN_RALLY", payload={"target":"FROM_GOAL", "context":"FROM_WORLD_STATE"}),
            timeout=8.0, risk="MEDIUM_COMBAT", state=SkillState.CANDIDATE, latency_class=LatencyClass.REALTIME,
            semantic_goal="Join an eligible rally matching goal policy",
            parameters=("target", "filter", "formation"), context=("RALLY_JOINER",),
            semantic_requirements=("rally_joinable", "target_matches_policy", "normal_idle_slot_positive"),
            vision_evidence=("rally_row_state", "relative_join_action", "capacity_state"),
            verifier="RALLY_JOINED", recovery=("TRY_NEXT_JOINABLE", "REFRESH_RALLY_LIST"),
            unknown_policy="Full or expired is environment race lost; unknown action blocks; unavailable body hero falls back to no hero",
            ui_change_tolerance=("icon", "number", "list_order", "position", "resolution", "skin"),
        ),
    ])
    skills.extend([
        Skill("NAVIGATE_TO", "Navigate through the verified page graph", None,
              Action("NAVIGATE_TO", payload={"page":"FROM_GOAL"}), state=SkillState.CANDIDATE,
              verifier="PAGE_CHANGED", recovery=("CLOSE_POPUPS", "RECOVER_HOME"),
              semantic_goal="Reach a requested game page", parameters=("page",), context=("NAVIGATION",),
              semantic_requirements=("current_page_known", "navigation_relation_known"),
              vision_evidence=("page_signature", "semantic_anchor", "relative_layout"),
              unknown_policy="Unknown destination action blocks and triggers page discovery",
              ui_change_tolerance=("icon", "text_alias", "position", "resolution", "skin")),
        Skill("RECOVER_HOME", "Return to a verified Home state", None, Action("RECOVER_HOME"),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="PAGE_CHANGED", recovery=("BACK", "REFRESH_STATE"),
              semantic_goal="Recover to a verified safe Home state", context=("RECOVERY",),
              semantic_requirements=("home_state_signature",), vision_evidence=("page_signature", "navigation_state"),
              unknown_policy="Never guess content actions while recovering",
              ui_change_tolerance=("popup", "position", "resolution", "skin")),
        Skill("READ_TIMER", "Read a timer for an event, queue, cooldown, or reset", None,
              Action("READ_TIMER", payload={"context":"FROM_GOAL"}), state=SkillState.CANDIDATE,
              latency_class=LatencyClass.FAST, verifier="TIMER_READ", recovery=("REFRESH_STATE", "OCR_FALLBACK"),
              semantic_goal="Read the active context timer", parameters=("context",), context=("EVENT", "QUEUE", "COOLDOWN"),
              semantic_requirements=("timer_relation_to_context",), vision_evidence=("relative_timer_roi", "ocr_number"),
              unknown_policy="Unreadable timer becomes unknown state and is never guessed",
              ui_change_tolerance=("number", "text_alias", "position", "resolution", "skin")),
        Skill("READ_COUNTER", "Read attempts, capacity, progress, or reward counters", None,
              Action("READ_COUNTER", payload={"context":"FROM_GOAL"}), state=SkillState.CANDIDATE,
              latency_class=LatencyClass.FAST, verifier="COUNTER_READ", recovery=("REFRESH_STATE", "OCR_FALLBACK"),
              semantic_goal="Read a context counter without assuming its fixed value", parameters=("context",),
              context=("ATTEMPT", "CAPACITY", "PROGRESS"), semantic_requirements=("counter_relation_to_context",),
              vision_evidence=("relative_counter_roi", "ocr_number"), unknown_policy="Unreadable value remains unknown",
              ui_change_tolerance=("number", "position", "resolution", "skin")),
        Skill("CLAIM_REWARD", "Claim a verified free or already-earned reward", None,
              Action("CLAIM_REWARD", payload={"source":"FROM_GOAL"}), state=SkillState.CANDIDATE,
              latency_class=LatencyClass.FAST, verifier="REWARD_CLAIMED",
              recovery=("REFRESH_STATE", "TRY_NEXT_CLAIMABLE"),
              semantic_goal="Claim a free, no-choice, already-earned reward regardless of reward content",
              parameters=("source", "context"), context=("REWARD",),
              semantic_requirements=("claimable", "free", "no_choice", "no_real_money_cost", "no_game_resource_cost", "no_item_cost"),
              vision_evidence=("page_context", "claim_action_state", "cost_area_state"),
              unknown_policy="UNKNOWN_REWARD is allowed after free claim is confirmed; UNKNOWN_ACTION or UNKNOWN_COST blocks",
              ui_change_tolerance=("reward_icon", "reward_quantity", "reward_count", "reward_order", "position", "resolution", "skin")),
        Skill("SEND_MARCH", "Send a parameterized march for gather, attack, reinforce, scout, or occupy", None,
              Action("SEND_MARCH", payload={"target":"FROM_GOAL", "mission":"FROM_GOAL", "formation":"FROM_STRATEGY"}),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="MARCH_STATE_CHANGED", recovery=("RESELECT_TARGET", "RECOVER_HOME"),
              semantic_goal="Send a march for the selected mission", parameters=("target", "mission", "formation"),
              context=("WORLD",), semantic_requirements=("target_matches_policy", "normal_idle_slot_positive"),
              vision_evidence=("target_state", "march_action_state", "relative_layout"),
              unknown_policy="Unknown target or action blocks; changed target artwork does not",
              ui_change_tolerance=("icon", "number", "position", "resolution", "skin")),
        Skill("OPEN_STAMINA_SOURCES", "Open the stamina-source panel from the world-map HUD gauge", Page.MAP,
              Action("TAP_SEMANTIC", "HUD_STAMINA_GAUGE"),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="STAMINA_SOURCES_OPEN", recovery=("REFRESH_STATE",),
              semantic_goal="See whether the free stamina gift is claimable",
              parameters=(), context=("WORLD",),
              semantic_requirements=("stamina_read_on_map", "search_panel_closed"),
              vision_evidence=("stamina_gauge", "popup_title"),
              unknown_policy="An unreadable gauge blocks; a covered HUD blocks",
              ui_change_tolerance=("number", "position", "resolution", "skin")),
        Skill("CLAIM_FREE_STAMINA", "Claim the free stamina gift and never the paid row", Page.POPUP,
              Action("TAP_SEMANTIC", "BTN_CLAIM_FREE_STAMINA"),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="FREE_STAMINA_CLAIMED", recovery=("REFRESH_STATE", "CLOSE_POPUP"),
              semantic_goal="Claim a stamina gift that costs nothing, in any currency",
              parameters=(), context=("REWARD",),
              semantic_requirements=("free", "no_choice", "no_real_money_cost", "no_game_resource_cost"),
              vision_evidence=("panel_title", "free_claim_control_state"),
              unknown_policy="Any control with a price is not this skill's target and blocks",
              ui_change_tolerance=("reward_quantity", "position", "resolution", "skin")),
        Skill("SELECT_MARCH_TO_RECALL", "Open the recall dialog for an active gathering march", Page.MAP,
              Action("TAP_SEMANTIC", "MARCH_ROW_1"),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="MARCH_RECALL_DIALOG_OPEN", recovery=("REFRESH_MARCH_STATE",),
              semantic_goal="Open the recall confirmation for a march that has no better use for its slot",
              parameters=(), context=("WORLD",),
              semantic_requirements=("active_march_visible", "search_panel_closed"),
              vision_evidence=("march_row", "march_state"),
              unknown_policy="No active march row blocks; a covered march list blocks",
              ui_change_tolerance=("number", "list_order", "position", "resolution")),
        Skill("RECALL_MARCH", "Confirm the open recall dialog and release the march", Page.POPUP,
              Action("TAP_SEMANTIC", "BTN_CONFIRM_RECALL"),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="MARCH_RECALLED", recovery=("REFRESH_MARCH_STATE",),
              semantic_goal="Confirm a recall dialog this loop opened itself",
              parameters=(), context=("WORLD",),
              semantic_requirements=("recall_dialog_open", "row_state_is_returning_after"),
              vision_evidence=("dialog_title", "confirm_action_state"),
              unknown_policy="A recall dialog not opened by this loop is closed instead of confirmed",
              ui_change_tolerance=("button_skin", "position", "resolution")),
        Skill("REINFORCE_TARGET", "Reinforce a city or alliance objective with a selected formation", None,
              Action("REINFORCE_TARGET", payload={"target":"FROM_GOAL", "formation":"FROM_STRATEGY"}),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="MARCH_STATE_CHANGED", recovery=("RESELECT_TARGET", "REFRESH_STATE"),
              semantic_goal="Reinforce a policy-selected target", parameters=("target", "formation"), context=("EXPEDITION",),
              semantic_requirements=("target_reinforceable", "normal_idle_slot_positive"),
              vision_evidence=("target_state", "reinforce_action_state"), unknown_policy="Unknown ownership or action blocks",
              ui_change_tolerance=("icon", "number", "position", "resolution", "skin")),
        Skill("USE_ACTIVITY_ATTEMPT", "Use one free or budget-approved activity attempt", None,
              Action("USE_ACTIVITY_ATTEMPT", payload={"activity":"FROM_GOAL"}),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.FAST,
              verifier="ATTEMPT_OR_RESULT_CHANGED", recovery=("REFRESH_ATTEMPT_STATE", "SWITCH_TASK"),
              semantic_goal="Use one available activity attempt", parameters=("activity", "strategy"), context=("ATTEMPT",),
              semantic_requirements=("attempt_positive", "action_cost_allowed", "activity_state_actionable"),
              vision_evidence=("attempt_counter", "action_state", "page_context"),
              unknown_policy="Never assume a fixed attempt count; unknown cost or action blocks",
              ui_change_tolerance=("number", "icon", "position", "resolution", "skin")),
        Skill("SELECT_REWARD_OPTION", "Select one option from a choice reward using strategy", None,
              Action("SELECT_REWARD_OPTION", payload={"options":"READ_FROM_CLIENT", "strategy":"FROM_GOAL"}),
              state=SkillState.CANDIDATE, latency_class=LatencyClass.NORMAL,
              semantic_goal="Choose and claim the highest-value allowed option", parameters=("options", "strategy"),
              context=("REWARD_CHOICE",), semantic_requirements=("choice_required", "options_read", "selection_confirmed"),
              vision_evidence=("option_relationships", "selection_state", "confirm_action_state"),
              verifier="REWARD_OPTION_CLAIMED", recovery=("CANCEL_SELECTION", "REFRESH_STATE"),
              unknown_policy="Unknown options block selection; never downgrade to generic claim",
              ui_change_tolerance=("reward_icon", "reward_quantity", "reward_order", "position", "resolution", "skin")),
    ])
    skills.append(
        Skill(
            "GATHER_RESOURCE",
            "Run the complete HOME to MAP to resource march and natural return workflow",
            Page.HOME,
            Action("RUN_WORKFLOW", "GATHER_RESOURCE"),
            timeout=900.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        )
    )
    skills.append(
        Skill(
            "BUILDING_UPGRADE",
            "Start a valid normal-resource building upgrade",
            Page.BUILDING,
            Action("TAP_SEMANTIC", "BTN_BUILD_UPGRADE"),
            timeout=30.0,
            risk="MEDIUM_RESOURCE_SPEND",
            state=SkillState.VERIFIED,
        )
    )
    skills.append(
        Skill(
            "RESEARCH",
            "Start one Whiteout Survival technology when the research queue is available",
            Page.RESEARCH,
            Action("TAP_SEMANTIC", "BTN_START_RESEARCH"),
            timeout=30.0,
            risk="MEDIUM_RESOURCE_SPEND",
            state=SkillState.BLOCKED,
        )
    )
    skills.append(
        Skill(
            "TRAIN_TROOPS",
            "Train or promote troops when one of the three camp queues is available",
            Page.TRAINING,
            Action("TAP_SEMANTIC", "BTN_START_TRAINING"),
            timeout=30.0,
            risk="MEDIUM_RESOURCE_SPEND",
            state=SkillState.VERIFIED,
        )
    )
    skills.append(
        Skill(
            "INTEL_CLAIM_REWARDS",
            "Claim completed Lighthouse Intel rewards",
            Page.INTEL,
            Action("TAP_SEMANTIC", "BTN_INTEL_CLAIM_ALL"),
            timeout=20.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        )
    )
    skills.append(
        Skill(
            "BEAST_HUNT",
            "Defeat a normal wilderness Beast with a verified march and stamina budget",
            Page.BEAST,
            Action("TAP_SEMANTIC", "BTN_BEAST_START_MARCH"),
            timeout=120.0,
            risk="MEDIUM_STAMINA_SPEND",
            state=SkillState.VERIFIED,
        )
    )
    skills.extend([
        Skill("INTEL_BEAST_START_MARCH", "Open a formation only for a verified ordinary Beast or Firebeast Intel target", Page.BEAST, Action("TAP_SEMANTIC", "BTN_BEAST_START_MARCH"), risk="MEDIUM_STAMINA_SPEND", state=SkillState.VERIFIED),
        Skill("DISPATCH_INTEL_BEAST", "Dispatch a verified victory-assured ordinary Beast or Firebeast Intel formation", Page.MARCH, Action("TAP_SEMANTIC", "BTN_BEAST_DISPATCH"), risk="MEDIUM_STAMINA_SPEND", state=SkillState.VERIFIED),
    ])
    skills.extend([
        Skill(
            "SELECT_BEAST_TARGET",
            "Select one current-client verified low-level normal Beast",
            Page.MAP,
            Action("TAP_SEMANTIC", "TARGET_BEAST_MUSK_OX_9"),
            timeout=15.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
        Skill(
            "DISPATCH_BEAST",
            "Dispatch only when the formation page explicitly reports victory assured",
            Page.MARCH,
            Action("TAP_SEMANTIC", "BTN_BEAST_DISPATCH_MUSK_OX_9"),
            timeout=30.0,
            risk="MEDIUM_STAMINA_SPEND",
            state=SkillState.VERIFIED,
        ),
        # The verified beast chain (SELECT_BEAST_TARGET -> BEAST_HUNT ->
        # DISPATCH_BEAST) only ever fires when the level-9 Musk Ox sprite sits
        # in the current viewport.  Live 2026-09-17: with goal BEAST_HUNT on
        # PAGE_MAP the viewport held no verified target (only a level-25 moose,
        # unsafe for this account), so the goal dead-ended at SAFE_STOP
        # verified_beast_target_not_visible every time and no beast was ever
        # dispatched.  This skill is the missing "find a target" hop: one
        # bounded viewport pan, re-observed by the normal loop afterwards.  The
        # swipe is a viewport gesture (no semantic control exists to locate),
        # same shape as the resource-strip swipe the runtime already performs.
        Skill(
            "SCAN_MAP_FOR_BEAST",
            "Pan the world map once to bring an off-screen beast target into view",
            Page.MAP,
            Action("SWIPE", "0.50,0.62,0.50,0.30", payload={"duration_ms": 600}),
            timeout=15.0,
            risk="LOW",
            state=SkillState.CANDIDATE,
        ),
        # 2026-09-18 escalation SPEND_STAMINA_ON_BEAST: the pan never converges
        # because it has no way to fly to a target.  The mammoth sprite is the
        # second dispatchable species on this account's map (measured live,
        # dataset/candidate/beast_card_route/); selection taps the sprite
        # wherever the anywhere-search found it.
        Skill(
            "SELECT_BEAST_TARGET_MAMMOTH",
            "Select the verified level-5 mammoth target on the world map",
            Page.MAP,
            Action("TAP_SEMANTIC", "TARGET_BEAST_MAMMOTH_5"),
            timeout=15.0,
            risk="LOW",
            state=SkillState.CANDIDATE,
        ),
        # The world-map beast card's 攻击 control: the hop from "a target card
        # is open" to "the formation page is open".  Opening the formation
        # spends nothing; the stamina is spent (and verified) by DISPATCH_BEAST.
        Skill(
            "ATTACK_BEAST_CARD",
            "Open the formation page from a visible world-map beast card",
            Page.BEAST,
            Action("TAP_SEMANTIC", "BTN_BEAST_CARD_ATTACK"),
            timeout=30.0,
            risk="MEDIUM_STAMINA_SPEND",
            state=SkillState.CANDIDATE,
        ),
        # 2026-09-20, SPEND_STAMINA_ON_BEAST: SELECT_BEAST_TARGET and its mammoth
        # twin each tap one species' sprite template, so the route could only ever
        # act on a beast somebody had already cut a template for.  Measured on a
        # live frame: the client prints the animal's own name beside it
        # (霜鳞避役 at 0.89) with its level badge (20 at 1.00), the table resolves
        # that to a row, and the route still recorded nothing -- because the row
        # was registered as UNVERIFIED.  This skill is the species-agnostic
        # version: it taps whatever beast the client's label named, at the
        # coordinate that label's own box measures on the current frame
        # (BEAST_ON_MAP is resolved from WorldState, not from a template), and
        # verify_beast_card_opened proves the card for *that* animal opened.
        #
        # No stamina moves here -- opening a card is free -- and the spend stays
        # gated on the client's own 胜券在握 strip further down the chain, so
        # this skill cannot spend on a beast the account cannot beat.
        Skill(
            "SELECT_BEAST_TARGET_LABELLED",
            "Select the beast the client's own map label names, whatever species it is",
            Page.MAP,
            Action("TAP_SEMANTIC", "BEAST_ON_MAP"),
            timeout=15.0,
            risk="LOW",
            state=SkillState.CANDIDATE,
        ),
    ])
    skills.extend([
        Skill(
            "DAILY_HERO_RECRUIT",
            "Complete the free Hero Recruitment daily task",
            Page.DAILY,
            Action("TAP_SEMANTIC", "BTN_DAILY_GO_HERO_RECRUIT"),
            timeout=60.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
        Skill(
            "DAILY_CLAIM_REWARDS",
            "Claim completed daily-task rewards",
            Page.DAILY,
            Action("TAP_SEMANTIC", "BTN_DAILY_CLAIM_ALL"),
            timeout=20.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
    ])
    skills.extend([
        Skill(
            "ALLIANCE_TECH_CONTRIBUTE",
            "Contribute normal resources to a live recommended Alliance Technology",
            Page.ALLIANCE,
            Action("TAP_SEMANTIC", "BTN_ALLIANCE_TECH_CONTRIBUTE_MEAT"),
            timeout=20.0,
            risk="LOW_RESOURCE_SPEND",
            state=SkillState.VERIFIED,
        ),
        Skill(
            "ALLIANCE_HELP",
            "Help alliance members when a manual help action is available",
            Page.ALLIANCE,
            Action("TAP_SEMANTIC", "BTN_ALLIANCE_HELP_ALL"),
            timeout=15.0,
            risk="LOW",
            state=SkillState.BLOCKED,
        ),
        Skill(
            "ALLIANCE_GIFTS",
            "Claim already available free Alliance Gifts",
            Page.ALLIANCE,
            Action("TAP_SEMANTIC", "BTN_ALLIANCE_GIFTS_CLAIM_ALL"),
            timeout=20.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
        Skill(
            "ALLIANCE_ALLY_GIFT_CLAIM",
            "Claim one already-created Ally Gift without entering its purchase-generation route",
            Page.ALLIANCE,
            Action("TAP_SEMANTIC", "BTN_ALLY_GIFT_CLAIM"),
            timeout=10.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
    ])
    skills.extend([
        Skill(
            "MAIL_CLAIM_REWARDS",
            "Read all mail tabs and claim only already-attached rewards",
            Page.MAIL,
            Action("TAP_SEMANTIC", "BTN_MAIL_CLAIM_ALL"),
            timeout=30.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
        Skill(
            "EXPLORATION_IDLE_CLAIM",
            "Open the accumulated Exploration idle-income dialog",
            Page.EXPLORATION,
            Action("TAP_SEMANTIC", "BTN_EXPLORATION_IDLE_CLAIM"),
            timeout=20.0,
            risk="LOW",
            state=SkillState.VERIFIED,
        ),
    ])
    return SkillRegistry(skills)
