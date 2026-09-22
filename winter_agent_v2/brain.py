from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .models import Decision, MarchState, Page, WorldState
from .beast_targets import is_dispatchable, may_evaluate
from .camp_training import CAMP_LABELS, CAMP_ORDER, LABEL_TO_CAMP
from .skills import SkillRegistry

#: Skills that leave a page or restore a known state instead of advancing whatever goal is being
#: pursued.  A page whose ready set contains nothing else has no registered way forward, which is
#: what licenses the one bounded generic attempt (see the fallback in ``decide``).
GENERIC_READY_SKILLS: frozenset[str] = frozenset({"BACK", "NAVIGATE_TO", "RECOVER_HOME"})

#: Which quick-panel row skill enters which camp's task page.  The panel keys the reading by the same
#: camp names ``WorldState.camps`` uses (``SHIELD_CAMP`` ...), so no second vocabulary is introduced.
#: Every panel row the reader can name, and the skill that taps *that* row's own arrow.
#:
#: The keys are the row keys ``read_quick_panel`` produces, spelled once here so the two cannot drift.
#: An incomplete table is not a cosmetic problem: on 2026-09-23 00:42:30 the research row was offered
#: by the reading, this map had no ``RESEARCH`` entry, and the caller's default substituted
#: ``..._SHIELD`` -- a real action pointing at the 盾兵 row.  There is no default any more (see
#: ``_panel_row_skill``): a row this table cannot name is a row this brain does not tap.
_QUICK_PANEL_ROW_SKILL: dict[str, str] = {
    "SHIELD_CAMP": "OPEN_TASK_FROM_QUICK_PANEL_SHIELD",
    "LANCER_CAMP": "OPEN_TASK_FROM_QUICK_PANEL_LANCER",
    "MARKSMAN_CAMP": "OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN",
    "RESEARCH": "OPEN_TASK_FROM_QUICK_PANEL_RESEARCH",
    "ALLIANCE_DONATION": "OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION",
    "HERO_RECRUIT": "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT",
    "MY_REWARDS": "OPEN_TASK_FROM_QUICK_PANEL_MY_REWARDS",
}


from .ocr import QUICK_PANEL_ARROW_BASIS_SCAN


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
        # How many times this run has tapped the free stamina gift.  One, because a
        # second sighting of the same unclaimed panel proves the tap does not work
        # (see the GET_MORE_STAMINA branch).
        self.stamina_claim_attempts = 0
        # A separate flag for the camp panel's affordability gate.  It must not
        # reuse ``stamina_panel_checked``: that flag gates the map's
        # free-stamina check, and the gate below deliberately *routes towards*
        # that check, so setting it here would switch off the very step it is
        # sending the run to do.
        self.unaffordable_camp_panel_left = False
        # Set once the brain has left a non-actionable beast/hero target card.
        # The page is a dead end (measured live 2026-09-15: a BLOCKED 大师悬赏
        # leaves the client with nothing to tap), and leaving it is what lets the
        # next run work at all -- but a Back that failed to move the client must
        # not be repeated, or the loop ping-pongs between the card and the map.
        self.beast_card_not_actionable_left = False
        # Bounded map-scan budget for BEAST_HUNT.  Live 2026-09-17: the goal
        # dead-ended whenever no verified beast sat in the current viewport,
        # because nothing ever looked for one.  Each scan is one viewport pan
        # (SCAN_MAP_FOR_BEAST); after ``max_beast_scans`` pans without a
        # verified target the goal still stops with the original named reason,
        # so the scan can never become an endless pan loop.
        #
        # Raised 3 -> 5 on 2026-09-19.  The bound is the operator's 4-6 local moves,
        # and three pans is a small patch of a world map: a beast one viewport away
        # was unreachable, and the failure it produced then cost the capability its
        # whole repair budget (see ``STOP_REASON_WALLS``).  Five keeps the search
        # finite while giving "the beast is simply not here right now" a fair chance
        # to be wrong.  The stop itself is no longer treated as a capability wall, so
        # exhausting this budget defers one attempt instead of blocking the goal.
        self.beast_scans_used = 0
        # Once per run: has the client's own beast search been asked for a target?
        #
        # The search is the convergence the viewport pan never had -- it makes the
        # client locate and centre a beast instead of moving the camera one
        # viewport and hoping.  It is bounded to one attempt because the client may
        # legitimately answer "没有发现条件相符的目标", and an unbounded 搜索 loop
        # would then tap forever; after this flag is set the pan budget below still
        # applies, so exhausting both still ends with the route's original named
        # reason.  Cleared alongside ``beast_scans_used`` whenever a target does
        # appear, so a later beast in the same run can use the search again.
        self.beast_search_used = False
        # Once per run: has the beast route already pressed Back to leave the
        # search panel after spending its search?
        #
        # 搜索 leaves the panel up and overlays the result card on it (measured
        # 2026-09-21 on ``beast5_found.png``), so one Back is what exposes the
        # target the route just asked for.  A Back that did not move the client
        # must not be repeated, or the loop ping-pongs between the panel and the
        # map spending an action each way -- the same guard the daily panel and
        # the non-actionable beast card already carry.
        self.beast_search_panel_left = False
        # Once per run: has the spend goal already handed over to the intel flow because
        # the beast route found nothing?  See the give-up branch in the BEAST_HUNT route.
        self.spend_route_switched = False
        # Once per run: has the labelled route already opened a map beast and put it
        # back because its card offered no ordinary attack?
        #
        # ``SELECT_BEAST_TARGET_LABELLED`` taps the beast the client's own label named
        # so the card can be read.  A card that comes back with 集结 and no 攻击 is
        # refused (correctly -- see the ``attack_card`` branch), but the tap that read
        # it resets both search budgets, so the route found the same beast again and
        # re-read it forever.  Measured 2026-09-21T12:24Z on the live client, whose map
        # carried a 等级7 霜鳞避役 that offers only 集结:
        #
        #     step 1  SELECT_BEAST_TARGET_LABELLED  tap 147,190   card 霜鳞避役 solo=False
        #     step 2  BACK                          beast_card_is_a_rally_not_a_solo_attack
        #     step 3  SELECT_BEAST_TARGET_LABELLED  tap 147,189   card 霜鳞避役 solo=False
        #     step 4  BACK                          beast_card_is_a_rally_not_a_solo_attack
        #     ... four full cycles, eight actions, stamina 430 -> 430, no dispatch
        #
        # That is precisely the loop the operator's rule forbids: "无法普通攻击时应自动
        # 尝试其他等级/目标，不得持续搜索同一不可攻击目标".  The marker is what makes
        # "already tried" survive the budget reset, so the search the run has not spent
        # yet becomes the next step instead of another tap on the same animal.  It is
        # bounded to one reading per run, so a map that is genuinely all rallies still
        # ends honestly rather than panning forever.
        self.beast_labelled_target_refused = False
        # The barracks the 快捷面板 last proved idle, or ``None``.  The panel reports all
        # three camps in one frame, so it can say a camp is startable without the three
        # page visits the power route costs.  Recorded rather than acted on: the panel's
        # own 加号 has no proven template, so the value informs the route's reason and is
        # available to a later step, while the tap still goes through proven controls.
        self.idle_camp_from_quick_panel: str | None = None
        #: Row arrows of the 快捷面板 asked for in this run.  A tap that does not open the task page
        #: must hand the next step back to the proven power route rather than repeat itself.
        self._panel_row_attempts = 0
        # Which goal put this run on its route.  The route name alone cannot say: a
        # `--goal BEAST_HUNT` run and the spend goal riding the same route are
        # indistinguishable from inside the brain, and only one of them may hand over to
        # the intel flow.  Set by the runtime when it derives the route from a goal.
        self.goal_id = ""
        self.max_beast_scans = 5
        # Same reasoning for the tabbed 任务 panel that ``OPEN_DAILY`` opens.
        # Measured live 2026-09-16: the panel lands on its 章节任务 tab and the
        # account had nothing claimable on any tab (the four 每日任务 sat at
        # 16/20, 25/40, 0/10, 0/10 and the three activity chests at 80/160/270 were
        # already open), so the honest decision is to stop -- but stopping *inside*
        # the panel is what leaves the client parked where the next run can do
        # nothing, the failure mode the beast card already produced.  One Back
        # leaves it (measured: DAILY -> HOME), and the flag is what stops the loop
        # from re-opening the panel it has already judged empty.
        self.daily_panel_not_actionable_left = False
        # The training page and the 科技研究 page are leaves: a run that reaches
        # one and finds nothing to do used to end standing on it, and the NEXT run
        # -- whatever its goal -- stopped within seconds with ``goal_page_mismatch``
        # (hit live 2026-09-17, twice: a TRAIN run ended on TRAINING and the
        # following DAILY run never got further).  One Back is measured to land on
        # HOME from both, and ``verify_safe_back`` accepts a different known page
        # afterwards, so leaving is verifiable rather than hopeful.  The flag is
        # what stops a Back that did not move the client from being repeated.
        self.terminal_page_left = False
        # How many exits this run has already tried on a panel another goal owned, so a Back (or
        # a close) that did not move the client is not repeated.  Two, because a layer can ignore
        # a Back and still answer its own close button -- see ``_leave_foreign_page_once``.
        self.foreign_page_steps = 0
        # Consecutive Stage A re-observations in this run.  Measured 2026-09-17:
        # the highlighted-camp state is NOT a transient animation -- seven waits in a
        # row all reported ``menu_drawn: false`` and ended with MAX_ACTIONS_REACHED,
        # so an unbounded wait burns a whole run on a state that is not converging.
        self._camp_menu_waits = 0
        # Barracks switched inside one run, so a training page whose three queues are all busy
        # cannot turn into a loop of taps (operator §八, bounded the same way as the wait above).
        #
        # Counted per *goal* as well as per run.  The goal board is re-ranked on every step
        # (operator §四/§五, ``runtime.py``), so a per-run budget alone is spent by whichever goals
        # happened to win earlier and leaves a later goal unable to reach its own camp even when the
        # open camp is idle: measured live 2026-09-22 20:55-20:56, where the page answered ``BACK``
        # with 矛兵营 ``AVAILABLE``/``trainable`` on screen because two earlier goals had used the
        # switches.  ``_camp_switch_goal`` is the goal the current count belongs to.
        self._camp_switch_attempts = 0
        self._camp_switches_this_run = 0
        self._camp_switch_goal = ""
        self.MAX_CAMP_SWITCHES = 2
        self.MAX_CAMP_SWITCHES_PER_RUN = 4
        # The camp this run wants the training page switched TO, as the client's own tab
        # label (盾兵营 / 矛兵营 / 射手营), or ``None`` when no camp is preferred.
        #
        # Operator directive 2026-09-22: TRAINING_CAMP_NEXT must not march through the
        # tabs mechanically ("当前打开哪个兵营就切下一个").  The choice belongs to the
        # goal, so the brain -- which owns WHAT -- picks the target from the camps' own
        # measured states, and the resolver only turns the picked label into the pixel
        # its tab sits at on this frame.  Recomputed on every switch decision, so a
        # stale preference cannot outlive the reading it came from.
        self.desired_camp_label: str | None = None
        # The generic ordinary-control attempt budget (operator directive 2026-09-22,
        # third item).  Two per run, and only while the runtime's frame scan can still
        # find an untried control: ``ordinary_scan_exhausted`` is set by the runtime
        # when its whitelist found nothing on the frame, so the brain stops asking for
        # a tap the frame cannot name.
        self.ordinary_attempts = 0
        self.MAX_ORDINARY_ATTEMPTS = 2
        # How many panel rows one run may be navigated through.  The panel is a task board -- three
        # barracks, the research lab, 联盟捐献, 英雄招募, 我的奖励 -- and the operator's §五 asks for
        # several in-city tasks handled in one pass, so a bound of two cut off the third barracks.
        # It stays bounded because a row whose tap opens nothing must not be retried forever; that
        # is what this ceiling is for, and each row is now only offered while its own reading says
        # it is idle, so a row that succeeded is never offered again in the same run.
        self.MAX_PANEL_ROW_ATTEMPTS_PER_RUN = 6
        self.ordinary_scan_exhausted = False
        # Two waits is the whole budget: measured, the state does not converge, so the
        # third Stage A observation is a blocker rather than another wait.
        self.MAX_CAMP_MENU_WAITS = 2
        # The panel opens on its 章节任务 tab, and the daily skills were calibrated on the
        # 每日任务 tab, so one tap is needed to read the content they act on.  One-shot:
        # if the tap does not take, repeating it would spend an action per step forever,
        # and the honest path is to stop instead (see the panel-exit flag above).
        self.daily_tab_switched = False
        # Set by the runtime when the *client itself* refused a camp fight for
        # lack of stamina.  That refusal is ground truth and it outranks the
        # gauge reading: measured live 2026-09-15, the camp panel's stamina ROI
        # reads 19/25 frames, and on the miss the gate silently failed to fire
        # while the client was already telling us the price was unpayable.
        # Never cleared: stamina only regenerates, so a panel that was
        # unaffordable earlier in a run cannot have become affordable later.
        self.camp_panel_refused = False
        # When the next free gift arrives, learned from the panel's own 下次补给
        # countdown and supplied by the runtime before each decision.  ``None``
        # means "not known", and unknown must never authorize the detour below:
        # this exists to *stop* paying a detour on every cycle, so a missing
        # value has to fall back to the old once-per-run behaviour.
        self.next_supply_at = None
        # Set by the runtime from the recorded outcome of the last free-gift
        # claim: True means tapping the panel's 领取 control has already been
        # measured not to change anything, so the claim must not be re-decided
        # from the frame alone.  Measured live 2026-09-19T05:17Z -- the control
        # is still drawn and still matches its template at distance 0, so the
        # *frame* says "claimable" while the client refuses the tap; eight
        # consecutive runs (four different goals) died on that same tap because
        # nothing in the brain could learn it from a picture.
        self.free_stamina_claim_cooling = False

    def _supply_may_be_due(self) -> bool:
        """Whether opening the stamina panel could plausibly find a free gift.

        The panel is the only place the gift is visible, so the check must run
        at least once per run.  But the supply cadence was measured at 7 hours
        (2026-09-15: 04:00:01Z and 11:00:01Z, three independent countdown reads),
        while the unattended loop runs up to 8 cycles an hour -- so a blind
        once-per-run check spends roughly 16 actions an hour to find a gift that
        is available three times a day.  Once the runtime has learned the
        instant, the check is skipped until it is near.

        Unknown is always due.  This is an optimisation, and an unknown clock
        must not be able to skip the gift -- that would trade a handful of saved
        actions for silently losing 150 stamina every 7 hours.

        A recorded refusal is the one thing that *does* skip the detour: opening
        the panel again would only re-tap a control the client has already been
        measured to ignore, and the retry is bounded by the cooldown rather than
        abandoned (see ``free_stamina_claim_cooling``).
        """
        if self.free_stamina_claim_cooling:
            return False
        if self.next_supply_at is None:
            return True
        now = datetime.now(timezone.utc)
        # A little early, because the countdown read is only second-accurate and
        # the panel is opened a step or two later.
        return now >= self.next_supply_at - timedelta(minutes=1)

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

    def _leave_daily_panel_once(self, world: WorldState) -> Decision | None:
        """One Back out of the 任务 panel, the first time it is found empty.

        Measured live 2026-09-16T13:47Z from inside the panel, on the same client
        the panel was opened from: one Back lands on ``Page.HOME``.  That
        transition is accepted by ``verify_safe_back`` (``before`` is neither MAP
        nor POPUP and ``after`` is a different known page), so this is a verifiable
        step rather than a hopeful one.

        Returns ``None`` once the flag is set, which is what keeps a Back that did
        not actually move the client from being repeated forever; the caller then
        falls through to its honest SAFE_STOP.
        """
        if self.daily_panel_not_actionable_left:
            return None
        self.daily_panel_not_actionable_left = True
        return Decision(
            "BACK",
            "daily_panel_not_actionable_leaving_the_page",
            world.confidence,
            "home_opened",
        )

    def _leave_foreign_page_once(self, world: WorldState, *, owner: str) -> Decision | None:
        """Leave a panel this goal does not own, so the next run can hop home.

        Measured live 2026-09-19, the first time the sweep was ever selected: one run opened the
        mail panel, read it, and recorded a reading; the next run selected ``DAILY_ACTIVITY_TARGET``
        -- and stopped with ``goal_page_mismatch``, because the client was still standing on MAIL
        and the daily route had no branch for a page that is neither HOME nor MAP nor its own.

        That is the difference between "one panel got looked at" and a sweep that walks all of
        them: consecutive routines meet each other on the previous panel, and refusing to move is
        the one answer that cannot work.  Most panels' own exit is a single Back to HOME (the same
        transition ``_leave_daily_panel_once`` and ``_leave_terminal_page_once`` were measured on),
        and ``verify_safe_back`` accepts it because ``before`` is neither MAP nor POPUP and
        ``after`` is a different known page.

        Not every layer answers a Back, though, and the measured counter-example is what gives this
        method its second step.  On 2026-09-21 the alliance chest layer was left standing by
        ``KEEP_TRAINING_PRODUCTIVE``, which is a goal that does not own ALLIANCE:

            before  page ALLIANCE  ->  PRESS_BACK  ->  after  page ALLIANCE  (confidence 0.98)
            verifier  SAFE_BACK_NOT_PROVEN

        The Back moved nothing, so the run ended and -- worse -- the ``foreign_page_left`` flag was
        already set, so every following run answered ``training_entry_not_verified`` without even
        trying.  One unmovable layer cost the cycle its training work permanently.  That layer is a
        sub-page with its own X in the top-right corner rather than a page with a back arrow, so its
        declared exit is a close, not a Back.

        Hence an ordered, bounded pair: Back first (cheap, and correct on every panel measured so
        far), then the close the client itself draws.  ``CLOSE_POPUP`` is the existing
        verifier-bound close -- ``verify_popup_closed`` accepts a page that is no longer POPUP --
        and it taps ``BTN_CLOSE``, whose alliance-chest-layer template was measured on the same
        frame (ccoeff 1.000 at (682, 38); 24 frames without that X measured 0.432-0.580).  Two
        steps per run, not a loop: the flag still ends the sequence, so a layer that answers
        neither exit still falls through to the caller's honest stop.
        """
        if self.foreign_page_steps >= 2:
            return None
        self.foreign_page_steps += 1
        if self.foreign_page_steps == 1:
            return Decision(
                "BACK",
                f"{owner.lower()}_goal_leaves_a_panel_it_does_not_own",
                world.confidence,
                "home_opened",
            )
        return Decision(
            "LEAVE_FOREIGN_LAYER",
            f"{owner.lower()}_goal_closes_a_layer_a_back_did_not_move",
            world.confidence,
            "foreign_layer_left",
        )

    def _leave_terminal_page_once(self, world: WorldState) -> Decision | None:
        """One Back off a page that has no exit of its own.

        ``Page.TRAINING`` and ``Page.RESEARCH`` are reached by a goal and have no
        branch that moves the client away again, so a run that finishes on one
        parks it there.  Measured 2026-09-17 (``tools/probe_power_route.py
        --leave``): one Back from either lands on ``Page.HOME``, and
        ``verify_safe_back`` accepts it because ``before`` is neither MAP nor POPUP
        and ``after`` is a different known page.

        Returns ``None`` once the flag is set, which is what keeps a Back that did
        not move the client from being repeated forever; the caller then falls
        through to its honest stop.
        """
        if self.terminal_page_left:
            return None
        self.terminal_page_left = True
        return Decision(
            "BACK",
            f"{world.page.value.lower()}_page_not_actionable_leaving_the_page",
            world.confidence,
            "home_opened",
        )

    def leave_terminal_page(self, world: WorldState) -> Decision | None:
        """One Back off a leaf page when nothing is runnable and nothing named it.

        Public because the *runtime* is the only caller that knows goal discovery
        found nothing: the brain cannot tell "this queue is busy and other work is
        waiting" (a SAFE_STOP the scheduler wants) from "this queue is busy and
        there is nothing else at all" (a dead end that must be left).
        """
        return self._leave_terminal_page_once(world)

    def _leave_or_stop(self, world: WorldState, reason: str, transition: str) -> Decision:
        """Leave a leaf page once if a NAMED goal is stuck on it, else stop by name.

        ``SAFE_STOP`` is how the brain tells the scheduler "skip this observation",
        so turning a busy queue into a Back would make it look like work and
        displace an observation that has real work waiting -- which is exactly what
        ``tests/test_multitask_scheduler.py`` pins.  A named goal, by contrast, is
        not choosing between observations; it is stuck where nothing can happen, so
        for it the Back is the only way out.
        """
        if self.current_goal is not None:
            leave = self._leave_terminal_page_once(world)
            if leave is not None:
                return leave
        return Decision("SAFE_STOP", reason, 1.0, transition)

    def _owns_terminal_page(self, world: WorldState) -> bool:
        """True when the current goal is one that works on this leaf page.

        The training page is owned by the legacy ``TRAIN`` goal **and** by any of the three
        per-camp goals.  That second half was missing, and it is the defect the operator reported on
        2026-09-22: the goal layer splits training into ``SHIELD_CAMP_TRAINING`` /
        ``LANCER_CAMP_TRAINING`` / ``MARKSMAN_CAMP_TRAINING``, so the sweep almost never runs the
        legacy goal -- and the gate above this one (``_leave_terminal_page_once``) backs off the
        training page for any goal that does not "own" it.  Measured on the archived run
        (20260922_192231_632514): the client stood on 射手营's page with the 训练 button lit, the
        goal was ``MARKSMAN_CAMP_TRAINING`` -- its own camp, open on screen -- and the decision was
        ``BACK`` with reason ``training_page_not_actionable_leaving_the_page``.  The route could not
        act on the page it had just navigated to, whatever the page said.

        Which goals those are is **the goal library's own answer**, not a list kept here: the route a
        goal belongs to (``goal_library.route_for``) is ``TRAIN`` for the legacy goal, for the three
        per-camp goals and for the aggregate ``KEEP_TRAINING_PRODUCTIVE`` -- measured -- and
        ``RESEARCH`` for the research pair.  A second copy of "which goals are training goals" is
        exactly how such a list drifts from the goal layer that defines it.

        ``goal_id`` is the concrete goal (the runtime sets it per goal, ``runtime.py``); a goal-less
        sweep reads ``None`` here and keeps its old fall-through, which is what the comment above
        ``_leave_terminal_page_once`` asks for -- the route for an unnamed goal is ``None`` too, so
        only a goal that really belongs to the page's route is treated as owning it.
        """
        if world.page not in (Page.TRAINING, Page.RESEARCH):
            return False
        from .goal_library import route_for

        route = route_for(str(getattr(self, "goal_id", "") or ""))
        if route is None:
            route = route_for(str(self.current_goal or ""))
        wanted = "TRAIN" if world.page is Page.TRAINING else "RESEARCH"
        return route == wanted

    def _select_daily_tab_once(self, world: WorldState) -> Decision | None:
        """One tap onto the 每日任务 tab, the first time the panel is read elsewhere.

        `OPEN_DAILY` lands on the panel's first tab (章节任务) while the page classifier
        names the page from the string on the tab *bar*, so `page is DAILY` has never
        meant "the daily tab is showing".  Measured on the live panel 2026-09-16: with
        章节任务 showing, the reading is `{'status':'AVAILABLE','claimable_count':0}`, and
        the account's three activity chests (thresholds 80/160/270, activity 285) were
        invisible; the two tab states are distinguishable in the frames themselves
        (dark blue pill vs light pill) and `verify_daily_tab_selected` reads that.

        Returns ``None`` once the flag is set, so the caller falls through to its honest
        stop instead of tapping forever.
        """
        if world.daily.get("tab") != "NOT_TASKS" or self.daily_tab_switched:
            return None
        self.daily_tab_switched = True
        return Decision(
            "SELECT_DAILY_TAB",
            "daily_panel_opened_on_another_tab",
            world.confidence,
            "daily_tab_selected",
        )

    @property
    def _intel_like(self) -> bool:
        """Whether this run is working the intel missions.

        Two goals share one route on purpose: CLEAR_INTEL clears the board and
        AVOID_STAMINA_WASTE rides the same flow because the intel beast missions are the
        *verified* way to spend stamina (the world-beast path is blocked and the map carries no
        species the table knows).  They are not the same goal, though, and the difference is
        real: one of them must not claim free stamina, because for that goal a rising number is
        the wrong direction.  This property is what lets the shared route tell them apart
        without duplicating it.
        """
        return self.current_goal in {"INTEL", "SPEND_STAMINA"}

    def reserved_slots(self, world: WorldState) -> int:
        """How many march slots the policy keeps free, given the OBSERVED capacity.

        ``reserve_marches`` is the operator's *intent* -- "keep some slots for
        realtime work" -- and it was being applied as an absolute number of slots
        regardless of how many the account actually has.  That is what stalled the
        gather chain on 2026-09-16: the live client reports capacity 2 for that
        role, so a standing reserve of 2 made ``idle <= reserve`` true as soon as a
        single march was out, and three consecutive GATHER_RESOURCE runs answered
        SAFE_STOP 'reserved_march_for_stamina' and produced no episode at all.  The
        same policy is reasonable for the 6-slot role it was written for.

        A reservation that makes the running goal unreachable is not a policy, it is
        a deadlock, so the intent is capped by what the account can afford: it may
        never eat into the last two slots, leaving at least one usable by the goal
        in progress.

            capacity 2 -> 0    one gathering plus one free is already the whole army;
                               realtime work is served by recall-on-demand instead,
                               which ``_recallable`` below already implements
            capacity 3 -> 1
            capacity 4+ -> reserve_marches, capped the same way

        With the capacity unknown this returns 0: the caller must not act on a
        capacity it has not read, and the map branch answers CHECK_MARCH before any
        dispatch decision is reached.
        """
        capacity = world.effective_normal_march_slots
        if capacity is None:
            return 0
        return max(0, min(self.reserve_marches, capacity - 2))

    def decide(self, world: WorldState, registry: SkillRegistry) -> Decision:
        if not world.known:
            # A screen the page model cannot name used to end the task here: ``SAFE_STOP
            # unknown_page``, nothing clicked, and -- because the runtime then backed out --
            # whatever the client had drawn on that screen went unread.  Operator directive
            # 2026-09-22 ("未知页面自主探索"):
            #
            #   不因页面尚未注册就拒绝全部普通操作 ... 先判断当前画面是否仍能支持当前 Goal；
            #   如果可以，就继续尝试普通低风险操作。
            #
            # The evidence that this is not a hypothetical: measured over this project's own
            # episode stream, 31 of the 87 steps that landed on UNKNOWN did so on one screen --
            # 挂机收益, an idle-income dialog whose own largest control is 领取 and whose goal
            # (``CLAIM_EXPLORATION_IDLE``) is to claim it.  The dialog was opened, the page model
            # could not name it, and the reward sat there for every one of those 31 steps.
            #
            # So an unnamed screen with a named goal now gets the same bounded ordinary attempt a
            # *named* page gets: the brain says only THAT a control should be tried, and the
            # runtime answers WHICH from this frame's own printed words, screened by the spend
            # blacklist it already carries.  That is the whole change -- no new skill, no new
            # executor, no page registry.
            #
            # Three things keep it from becoming an exploration loop:
            #
            #   * a named goal is required -- with no goal there is nothing to advance, so the
            #     answer stays the old one;
            #   * the budget is the same counter and the same ceiling the named-page fallback
            #     uses (``MAX_ORDINARY_ATTEMPTS``), shared rather than doubled;
            #   * once the budget is gone -- or the frame names nothing untried -- the answer is
            #     still ``SAFE_STOP unknown_page``, which is what hands the screen to the
            #     runtime's own bounded Back recovery and then the next goal (§六).
            if (
                self.current_goal
                and self.ordinary_attempts < self.MAX_ORDINARY_ATTEMPTS
                and not self.ordinary_scan_exhausted
            ):
                self.ordinary_attempts += 1
                return Decision(
                    "TRY_ORDINARY_CONTROL",
                    f"unnamed_page_with_goal_{self.current_goal}_may_still_name_an_ordinary_control",
                    world.confidence,
                    "ordinary_control_observed",
                )
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
        if world.page is Page.POPUP and world.popup == "NEW_TROOP_UNLOCK":
            # The barracks' first-open reveal.  Measured live 2026-09-22T04:39:04Z: it is what
            # the client answered the 射手营 tab tap with, the run could not name the screen, and
            # the switch it had really made was recorded as TRAINING_CAMP_SWITCH_NOT_PROVEN.
            #
            # The goal-neutral close is the right one and not a guess: the client prints
            # 点击任意位置继续 on the card itself, which is the runtime's existing
            # "declared its own exit" path (``read_tap_anywhere_instruction``), and the verifier
            # only asks that the screen be gone afterwards -- the page underneath is whichever
            # the reveal covered, which is why no domain-named dismiss fits here.
            return Decision(
                "DISMISS_SHARED_REWARD",
                "new_troop_reveal_declares_its_own_exit",
                world.confidence,
                "underlying_page_restored",
            )
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
            if self._intel_like:
                return Decision("DISMISS_INTEL_GENERIC_REWARD", "intel_goal_generic_reward_feedback", world.confidence, "intel_page_restored")
            if self.current_goal == "EXPLORATION":
                return Decision("DISMISS_EXPLORATION_GENERIC_REWARD", "exploration_goal_generic_reward_feedback", world.confidence, "exploration_claimed")
            if self.current_goal == "ALLIANCE":
                return Decision("DISMISS_ALLIANCE_GENERIC_REWARD", "alliance_goal_generic_reward_feedback", world.confidence, "alliance_gifts_restored")
            if self.current_goal in {"TRAIN", "RESEARCH"}:
                # The training sweep meets this dialog on its way to the power
                # panel.  It used to be closed with CLOSE_POPUP because that was
                # the only verifier-bound close at the time, but CLOSE_POPUP taps
                # BTN_CLOSE, which measures phash 28 against a tolerance of 6 on
                # the dialog (its ROI is the top-right corner, empty here), so it
                # could never have cleared it.  Same for every other goal that
                # cannot name the page under the dialog, which is why they all
                # share the one dismiss now.
                return Decision(
                    "DISMISS_SHARED_REWARD",
                    f"{self.current_goal.lower()}_goal_generic_reward_dismissed",
                    world.confidence,
                    "underlying_page_restored",
                )
            # Any remaining goal -- AUTO_DISCOVERY meets this dialog constantly --
            # gets the dialog's own exit, and this used to be SAFE_STOP.  Stopping
            # was wrong for a reason the client states on the dialog itself: it
            # says 点击任意位置退出, so its exit is declared by the client rather
            # than inferred by us, and closing a blocker is not a guess about
            # which page to return to.  Measured live 2026-09-20 (open issue #64):
            # five of the six AUTO rounds in one twenty-minute window were a single
            # action on this dialog followed by a failure, and none of the five got
            # past it -- so the next round met the same blocker.
            return Decision(
                "DISMISS_SHARED_REWARD",
                "shared_reward_popup_dismissed_by_its_declared_exit",
                world.confidence,
                "underlying_page_restored",
            )
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
        # The 加成总览 panel is shared by every route that walks the power-category
        # list, so the first hop is expressed once rather than per goal.  The two
        # goals differ only in which row's 提升 they take: TRAIN goes to 部队实力,
        # RESEARCH to 科技实力.
        if world.page is Page.POPUP and world.popup == "POWER_OVERVIEW" and self.current_goal in ("TRAIN", "RESEARCH"):
            return Decision("OPEN_POWER_DETAILS", f"{self.current_goal.lower()}_goal_power_overview", world.confidence, "power_details_open")
        if world.page is Page.POPUP and world.popup == "POWER_DETAILS" and self.current_goal == "TRAIN":
            return Decision("NAVIGATE_INFANTRY_CAMP", "training_goal_troop_power_route", world.confidence, "infantry_camp_highlighted")
        if world.page is Page.POPUP and world.popup == "POWER_DETAILS" and self.current_goal == "RESEARCH":
            return Decision("NAVIGATE_RESEARCH_LAB", "research_goal_technology_power_route", world.confidence, "research_lab_highlighted")
        if world.page is Page.POPUP and world.popup == "INTEL_BEAST_MISSION":
            return Decision("OPEN_INTEL_BEAST_TARGET", "reviewed_intel_beast_mission", world.confidence, "intel_beast_target_open")
        if world.page is Page.POPUP and world.popup == "INTEL_RESCUE_SURVIVORS_MISSION":
            return Decision("OPEN_INTEL_RESCUE_SURVIVORS_TARGET", "reviewed_rescue_survivors_mission", world.confidence, "intel_rescue_target_open")
        if world.page is Page.MAP and world.popup == "INTEL_RESCUE_SURVIVORS_TARGET":
            return Decision("EXECUTE_INTEL_RESCUE_SURVIVORS", "rescue_target_and_cost_verified", world.confidence, "intel_rescue_in_progress")
        if world.page is Page.POPUP and world.popup == "HERO_BATTLE_VICTORY":
            # The hero battle result screen: taps do not clear it (measured),
            # BACK does.
            return Decision("BACK", "hero_battle_victory_dismissed", world.confidence, "intel_page_restored")
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
            #
            # Bounded to one attempt per run.  Measured live 2026-09-19: the client sat on this
            # popup with ``free_claim_available: true`` while the loop chose CLAIM_FREE_STAMINA
            # every ~45 seconds, four times and across three different goals, and the popup never
            # changed -- the claim's own episode carried no verification, so nothing was proved.
            # A second sighting of the same unclaimed panel is evidence that tapping it does not
            # work, and because this branch precedes every goal route it was also starving those
            # goals of their turn.  Leaving is the honest answer: one attempt, then the panel is
            # closed and the goal's own route runs.
            #
            # The per-run counter is necessary but NOT sufficient, and the residual livelock was
            # measured after it landed: a step whose verifier fails ends the run (``runtime.py``,
            # ``if not verification.ok: return finish(...)``), so a run that starts on this panel
            # observes it exactly ONCE -- the counter is 0, the claim is re-decided, and the
            # counter never reaches the second sighting that would leave.  Every cycle is a fresh
            # interpreter, so the count resets.  The cross-run half is ``free_stamina_claim_cooling``:
            # the refused tap is remembered on disk and the branch leaves until the retry is due.
            if (
                world.stamina.get("free_claim_available") is True
                and not self.free_stamina_claim_cooling
                and self.stamina_claim_attempts < 1
            ):
                self.stamina_claim_attempts += 1
                return Decision("CLAIM_FREE_STAMINA", "free_stamina_gift_claimable", world.confidence, "free_stamina_claimed")
            if world.stamina.get("free_claim_available") is True:
                # Two different reasons, because they are two different facts: the panel was
                # already tapped this run and did not change, versus the same tap was refused
                # on an earlier run and has not been retried yet.  Merging them would hide
                # which one the runtime is actually in.
                reason = (
                    "stamina_panel_claim_refused_waiting_for_the_next_supply"
                    if self.free_stamina_claim_cooling
                    else "stamina_panel_still_unclaimed_after_the_claim_attempt"
                )
                return Decision("BACK", reason, world.confidence, "map_restored")
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
        # The quit dialog needs its own decision, not the generic one.  Measured on
        # the live dialog 2026-09-17 (「确认退出游戏吗?」 -- 取消 / 确定 / X): the
        # BTN_CLOSE record that wins scores d=2 and its ROI centre (635,455) is the
        # X in the title bar, so closing it cannot quit the client; the two buttons
        # sit ~290 px below in one row (BTN_CANCEL centre (208,793), and the sibling
        # duplicate-target dialog measures its confirm at (503,787)).  Naming the
        # branch is what stops a future BTN_CLOSE record from silently repointing
        # this at a control that quits the game.
        if world.page is Page.POPUP and world.popup == "EXIT_CONFIRM":
            return Decision("CLOSE_POPUP", "exit_confirm_closed_via_its_close_button", world.confidence, "popup_closed")
        if world.page is Page.POPUP and world.popup:
            return Decision("CLOSE_POPUP", "blocking_popup", world.confidence, "popup_closed")
        # A previous run can finish on the training or the 科技研究 page, which are
        # leaves.  A *named* goal that cannot work on such a page would otherwise
        # answer ``goal_page_mismatch`` within one step and leave the client exactly
        # where it was, so it is moved off first.  Two cases are deliberately left
        # alone: the goal that owns the page (it still has actions to take), and a
        # goal-less sweep, which keeps its old fall-through to the page's own
        # branches -- a trainable queue there is real work, not a dead end.
        if (
            world.page in (Page.TRAINING, Page.RESEARCH)
            and self.current_goal is not None
            and not self._owns_terminal_page(world)
        ):
            leave = self._leave_terminal_page_once(world)
            if leave is not None:
                return leave
            return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_off_terminal_page")
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
                leave = self._leave_foreign_page_once(world, owner="MAIL")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_mail_route")
        if self._intel_like:
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
                # Measured live 2026-09-19, and it is why the stamina requirement stayed unmet:
                # the sweep left the client on the ALLIANCE panel, the previous goal handed over,
                # and this route answered goal_page_mismatch without taking a single step.  Since
                # AVOID_STAMINA_WASTE now rides this route (the beast path is blocked and the intel
                # missions are the verified spend), this branch stood directly between the operator
                # and "keep stamina under 30".  Same measured hop as the panel and terminal routes:
                # one Back to HOME, which is this route's own entry point.
                leave = self._leave_foreign_page_once(world, owner="INTEL")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_intel_route")
            if world.page is Page.MAP and world.resource_search_open:
                return Decision("BACK", "close_resource_search_for_intel_goal", world.confidence, "resource_search_closed")
        if self.current_goal == "BEAST_HUNT":
            if world.page is Page.HOME:
                return Decision("OPEN_MAP", "beast_goal_requires_map", world.confidence, "map_opened")
            if world.page not in {Page.MAP, Page.BEAST, Page.MARCH}:
                # The same measured hop the intel-like route above already has, and for the same
                # reason: a run that ends standing on a panel it does not own parks the client
                # there, and the next run then answers goal_page_mismatch without taking a single
                # step.  My spend handover makes that certain rather than occasional -- it moves the
                # run onto the intel page, and when the board has no untried pin the run ends
                # standing on it, so without this every following run stops on step 1 forever.
                leave = self._leave_foreign_page_once(world, owner="BEAST")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_beast_route")
            if world.page is Page.MAP and world.resource_search_open and self.beast_search_used:
                # This branch used to close the search panel unconditionally, because
                # the panel belonged to the gathering route and a beast goal standing
                # on it was somewhere it did not belong.
                #
                # Since 2026-09-21 the panel is the beast route's own tool: it is
                # where 冰原巨兽 is selected and where 搜索 is tapped to make the
                # client locate and centre a target.  Closing the panel while the
                # search ticket is still unspent would therefore tear down the very
                # instrument the route is about to use, and the two branches would
                # fight -- measured: an unconditional Back here meant the search
                # route could never issue its first hop at all.
                #
                # So the exit is gated on the ticket: the panel is left once the
                # search has been spent, which is the same "this route is done with
                # this panel" meaning the branch always had, just scoped to when that
                # is actually true.  It is also one-shot: 搜索 keeps the panel up and
                # draws the result card over it, so this Back is what exposes the
                # target -- while a Back that failed to move the client must not be
                # repeated, or the loop ping-pongs between panel and map forever.
                #
                # But NOT while the search has already produced something to act on.
                # Measured 2026-09-21 with the whole chain walked: 搜索 succeeds, the
                # panel stays open on the beast tab, and the beast is on the map behind
                # it -- so this branch fired first and answered Back, and the labelled
                # route below (which is what actually opens the card and spends the
                # stamina) was never reached.  The search worked and nothing was hunted.
                # Standing on the panel is fine when there is a target to tap; leaving it
                # is only the right move when there is not.
                #
                # The result card the search itself drew counts as a target, and it had
                # to be added here explicitly: it is read into ``beast_search_result``
                # and NOT into ``world.beast`` (it matches no reviewed card template),
                # so neither ``is_dispatchable`` nor ``may_evaluate`` could see it.  The
                # measured cost of leaving it out was this Back firing on the one frame
                # that had the target -- ``等级10 麝牛``, 攻击 at (361,600) -- and
                # dropping it.  ``solo_attack`` is required so that a rally card does not
                # hold the panel open for a route that cannot use it.
                search_found_a_target = bool(
                    (world.beast_search_result or {}).get("solo_attack")
                )
                if not (
                    is_dispatchable(world.beast)
                    or may_evaluate(world.beast)
                    or search_found_a_target
                ):
                    if not self.beast_search_panel_left:
                        self.beast_search_panel_left = True
                        return Decision("BACK", "close_resource_search_for_beast_goal", world.confidence, "resource_search_closed")
        if (
            world.page is Page.EXPLORATION
            and self._intel_like
            and world.exploration.get("stamina_cost_displayed") is not None
        ):
            # Live 2026-09-14: the Hero Journey camp panel classifies as the
            # exploration page (its 探险 ⚡10 button belongs to that system).
            # With the intel goal active this panel IS the workable target.
            cost = world.exploration.get("stamina_cost_displayed")
            available = world.stamina.get("current")
            cost_affordable = world.stamina.get("cost_affordable")
            # Three signals, in descending authority.  The first two are the
            # client's own verdicts and need no reading at all:
            #
            # * ``cost_affordable is False`` -- the client drew the cost in red,
            #   which is what it will refuse on.  Measured 5/5 across three
            #   cost-bearing buttons (tools/probe_cost_colour.py), and it needs
            #   no OCR, so it also covers the 6 of 25 frames the gauge cannot
            #   read and the genuine ``0`` the ROI cannot read at all.
            # * ``camp_panel_refused`` -- the client already refused this fight;
            #   recorded by the runtime (see the flag's comment in __init__).
            #
            # Only the last one is our own arithmetic, and it is the weakest: it
            # needs both integers, so an unread gauge leaves it silent.
            #
            # ``cost_affordable`` must be tested against ``False`` explicitly --
            # ``None`` means "not measured", which must not block a fight that
            # was payable.
            unaffordable = (
                cost_affordable is False
                or self.camp_panel_refused
                or (isinstance(cost, int) and isinstance(available, int) and available < cost)
            )
            if unaffordable:
                # Live 2026-09-15T03:03:57Z: the client sat on this panel with
                # stamina 9 against a displayed cost of 10.  Tapping 探险 made
                # the client refuse and open 获取更多 instead; the run then
                # spent its remaining three actions on the stamina panel and
                # achieved nothing.  The refusal is now recorded honestly
                # (verify_intel_hero_march_open -> INTEL_HERO_MARCH_REFUSED_FOR_
                # STAMINA), and runtime.py returns on the first failed
                # verification, so attempting it would end the run on step 1.
                # Measure the price before paying it instead.
                #
                # A missing read is not a zero: the gauge test only fires on two
                # integers, so an unread gauge leaves the attempt in place and
                # the client stays the authority on affordability -- and when it
                # refuses, runtime.py records that refusal on the brain and the
                # run comes back here through ``camp_panel_refused`` instead of
                # ending.
                if (
                    self.claim_free_stamina
                    and not self.stamina_panel_checked
                    and not self.unaffordable_camp_panel_left
                ):
                    # BACK leaves the panel.  Measured live 2026-09-15T03:46Z:
                    # from the camp panel it lands on **MAP**
                    # (dataset/truth_audit/camp_panel_stamina_gate_20260915,
                    # step 3: EXPLORATION -> MAP), which is where the
                    # free-stamina check runs.  The 8/8 recorded
                    # EXPLORATION->HOME transitions belong to the *idle-income*
                    # exploration page, a different screen; HOME also converges
                    # on MAP because the INTEL goal maps HOME to OPEN_MAP.  The
                    # panel cannot be opened from here even though the gauge is
                    # visible: verify_stamina_sources_open requires the map as
                    # its before-state.
                    #
                    # This flag is the loop guard, and it is deliberately not
                    # ``stamina_panel_checked``: that one is set by the map
                    # branch when it actually opens the panel, and setting it
                    # here would cancel the check this decision exists to
                    # trigger.  With the guard in place a Back that failed to
                    # move the client stops the run instead of repeating.
                    self.unaffordable_camp_panel_left = True
                    return Decision(
                        "BACK",
                        "camp_fight_unaffordable_go_get_free_stamina",
                        world.confidence,
                        "camp_panel_left",
                    )
                return Decision(
                    "SAFE_STOP",
                    "camp_fight_unaffordable_and_free_gift_already_checked",
                    1.0,
                    "wait_for_stamina_regen",
                )
            return Decision("INTEL_HERO_START_MARCH", "intel_hero_camp_panel", world.confidence, "intel_hero_fight_started")
        if self.current_goal == "EXPLORATION":
            if world.page is Page.HOME:
                return Decision("OPEN_EXPLORATION", "exploration_goal", world.confidence, "exploration_open")
            if world.page is Page.MAP:
                return Decision("OPEN_HOME", "exploration_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.EXPLORATION:
                leave = self._leave_foreign_page_once(world, owner="EXPLORATION")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_exploration_route")
        if self.current_goal == "DAILY":
            if world.page is Page.HOME:
                # Do not re-open a panel this run has already read and found
                # empty: the Back below would otherwise send the loop round
                # HOME -> panel -> Back forever.
                if self.daily_panel_not_actionable_left:
                    return Decision("SAFE_STOP", "daily_panel_already_read_not_actionable", 1.0, "switch_task")
                return Decision("OPEN_DAILY", "daily_goal", world.confidence, "daily_open")
            if world.page is Page.MAP:
                if self.daily_panel_not_actionable_left:
                    return Decision("SAFE_STOP", "daily_panel_already_read_not_actionable", 1.0, "switch_task")
                return Decision("OPEN_HOME", "daily_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.DAILY:
                leave = self._leave_foreign_page_once(world, owner="DAILY")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_daily_route")
            select_tab = self._select_daily_tab_once(world)
            if select_tab is not None:
                return select_tab
            if world.daily.get("status") != "CLAIMABLE":
                leave = self._leave_daily_panel_once(world)
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "daily_no_claimable_rewards", 1.0, "switch_task")
        if self.current_goal == "ALLIANCE":
            if world.page is Page.HOME:
                return Decision("OPEN_ALLIANCE", "alliance_goal", world.confidence, "alliance_open")
            if world.page is Page.MAP:
                return Decision("OPEN_HOME", "alliance_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.ALLIANCE:
                leave = self._leave_foreign_page_once(world, owner="ALLIANCE")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "bootstrap_to_alliance_route")
            if world.alliance.get("section") == "HOME":
                return Decision("OPEN_ALLIANCE_GIFTS", "alliance_gifts_badge_visible", world.confidence, "alliance_gifts_open")
        # ---- the 快捷面板 as the in-city task board (operator directive 2026-09-22 §一) -------------
        #
        # This used to live *inside* the TRAIN branch below, so only the TRAIN route could use the
        # panel.  Measured live 2026-09-22 22:54:15: ``KEEP_RESEARCH_PRODUCTIVE`` won the step, the
        # branch never ran, and the round fell back to the power route and failed twice
        # (``NAVIGATE_INFANTRY_CAMP``, ``NAVIGATE_RESEARCH_LAB``).  It sits before the per-route
        # branches now, and it asks which rows the running goal works from through the goal layer's own
        # route (``route_for``) and the panel's own row kinds -- never by comparing goal ids, route
        # names or capability ids against each other.
        #
        # It does not touch a page that can already be advanced: this only ever runs on HOME, and when
        # the goal is already standing where it can work, the branches below answer first.
        # ---- a task bar opened from a panel row is *the page that row promised* ---------------
        #
        # Measured on the device 2026-09-22 23:42:41: the 矛兵 row's arrow was tapped and the
        # client opened that barracks' own action bar in the city (详情 / 升级 / 训练), which the
        # reader names as ``training.menu_open`` with ``camp = LANCER_CAMP`` and ``train_tap_norm``.
        # The frame after the tap is archived as
        # 20260922_234118_459931_step_006_after_refresh_2_20260922T154326121610.png.
        #
        # Finishing it is one more tap of the client's own 训练 label, which
        # ``BTN_OPEN_TRAINING_FROM_CAMP`` resolves from this very frame.  Doing it here, before the
        # per-route branches, is what keeps a row that has already advanced to its last step from
        # being dropped: on 23:43:39 the bar was open and the next step re-ranked the goals, so the
        # bar sat there with nobody pressing it (operator §一: 当前 Goal 已在正确任务页面且仍可推进
        # 时，直接完成当前任务; §六: 完成一项后继续).
        #
        # The barracks must be this goal's own.  A bar for another camp is left alone -- the panel
        # draws three look-alike rows and §二 is explicit that a tap must belong to the task it came
        # from; that camp's own goal gets its turn on the board.
        if world.page is Page.HOME and self._goal_route() == "TRAIN" and world.training.get("menu_open"):
            open_camp = str(world.training.get("camp") or "")
            own_camp = self._goal_camp()
            # ``_goal_camp`` already answers in the canonical camp form (``LANCER_CAMP``), the same
            # form ``world.training["camp"]`` and the panel's row keys use.  An earlier version of
            # this appended ``_CAMP`` a second time, which made the comparison impossible to satisfy
            # and silently disabled the branch for every per-camp goal -- caught by replaying this
            # frame, not by reading the code.
            if own_camp is None or not open_camp or open_camp == own_camp:
                return Decision(
                    "OPEN_INFANTRY_TRAINING",
                    "an_opened_camp_bar_is_the_page_this_goal_came_for",
                    world.confidence,
                    "training_page_open",
                )
        if (
            world.page is Page.HOME
            and self._goal_route() == "RESEARCH"
            and world.research.get("menu_open")
            # Same precedence the research route already had: a queue that is already running needs
            # nothing from us, and entering the page to confirm that is a wasted round trip.
            and world.research.get("queue_available") is not False
        ):
            return Decision(
                "OPEN_RESEARCH",
                "an_opened_lab_bar_is_the_page_this_goal_came_for",
                world.confidence,
                "research_page_open",
            )
        panel = world.quick_panel or {}
        if world.page is Page.HOME and self._panel_rows_for_this_goal():
            if not panel.get("open"):
                handle = panel.get("handle") or {}
                # Not open: ask for one ordinary control, which the runtime's dictionary tier resolves
                # to a tap of the handle on this very frame (proved live 21:24:58, QUICK_PANEL_OPENED).
                if (
                    str(handle.get("state") or "") == "COLLAPSED"
                    and self.ordinary_attempts < self.MAX_ORDINARY_ATTEMPTS
                    and not self.ordinary_scan_exhausted
                ):
                    self.ordinary_attempts += 1
                    return Decision(
                        "TRY_ORDINARY_CONTROL",
                        "quick_panel_is_the_in_city_task_board_for_this_goal",
                        world.confidence,
                        "ordinary_control_observed",
                    )
            else:
                row = self._actionable_panel_row(world)
                skill_id = self._panel_row_skill(row)
                if skill_id is not None and self._panel_row_attempts < self.MAX_PANEL_ROW_ATTEMPTS_PER_RUN:
                    self._panel_row_attempts += 1
                    key = str(row.get("key") or "")
                    return Decision(
                        skill_id,
                        f"quick_panel_row_{key.lower()}_enters_its_own_task_page",
                        world.confidence,
                        "task_page_open",
                    )
        if self.current_goal == "RESEARCH":
            # Same route shape as the training goal below, one category row across:
            # 加成总览 -> 实力详情 -> 科技实力 提升 -> the 科研所's 研究 button.
            # The route was measured live on 2026-09-04
            # (knowledge/skills/RESEARCH_RESEARCH.md line 38) and re-measured
            # 2026-09-17; what it never had was a decision here, so the goal could
            # only ever stop with research_entry_not_verified.
            #
            # Measured live 2026-09-19, and this is why the hop below exists: the research goal was
            # selected while the client stood on the ALLIANCE panel, this route has no branch for a
            # page it does not own, and the page-driven alliance branch then ran
            # OPEN_ALLIANCE_GIFTS under a *research* goal -- twelve times, each run closing the
            # reward popup and ending, so the research page was never once read.  The four panel
            # routines got this hop when they were wired; these two routes were missed.
            if world.page not in {Page.HOME, Page.MAP, Page.RESEARCH, Page.POPUP}:
                leave = self._leave_foreign_page_once(world, owner="RESEARCH")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "research_entry_not_verified", 1.0, "bootstrap_to_research_route")
            # A run that has already read this page and left it must not walk the
            # route again: the Back below lands on HOME, which is exactly the page
            # this branch would start from, so without this the loop would be
            # HOME -> route -> RESEARCH -> Back -> HOME forever.
            if self.terminal_page_left:
                return Decision("SAFE_STOP", "research_page_already_read_not_actionable", 1.0, "switch_task")
            if world.page is Page.HOME and world.research.get("queue_available") is False:
                # A queue that is already running needs nothing from us, so this
                # precedes the navigation hop: opening the page to confirm it cannot
                # start anything is a wasted round trip.  (Both facts can be true at
                # once -- the 科研所's menu is open *and* the queue is busy -- which is
                # why vision reports them separately.)
                return Decision("SAFE_STOP", "research_queue_busy", 1.0, "switch_task")
            if world.page is Page.HOME:
                return Decision("OPEN_POWER_OVERVIEW", "research_goal_requires_power_route", world.confidence, "power_overview_open")
            if world.page is Page.MAP:
                # The client's resting page is the map, and a named route goal used
                # to stop here -- research_entry_not_verified / training_entry_not_verified
                # -- so a 科研 or 训练 task launched after any other task died on its
                # first step.  The other four route goals (MAIL / EXPLORATION / DAILY /
                # ALLIANCE) have had this hop all along; these two never did.
                # Measured 2026-09-17: run_live --goal TRAIN started on MAIL and ended
                # step 1 with training_entry_not_verified, having taken no action.
                if world.resource_search_open:
                    return Decision("BACK", "close_resource_search_for_research_goal", world.confidence, "resource_search_closed")
                return Decision("OPEN_HOME", "research_goal_requires_home", world.confidence, "home_opened")
            if world.page is not Page.RESEARCH:
                return Decision("SAFE_STOP", "research_entry_not_verified", 1.0, "refresh_state_or_switch_task")
        if self.current_goal == "TRAIN":
            # Same re-route guard as the research goal above: after the Back the
            # client is on HOME, which is where this branch starts.
            #
            # And the same foreign-page hop, for the same measured reason: the sweep selects these
            # goals from wherever the client happens to be, and a route that only knows HOME is a
            # route that does nothing whenever the previous goal left the client on a panel.
            if world.page not in {Page.HOME, Page.MAP, Page.TRAINING, Page.POPUP}:
                leave = self._leave_foreign_page_once(world, owner="TRAIN")
                if leave is not None:
                    return leave
                return Decision("SAFE_STOP", "training_entry_not_verified", 1.0, "bootstrap_to_training_route")
            if self.terminal_page_left:
                return Decision("SAFE_STOP", "training_page_already_read_not_actionable", 1.0, "switch_task")
            if world.page is Page.HOME and world.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED":
                # Stage A (#28, and this is the third position the route has taken on it).
                #
                # The camp is highlighted and the radial menu has not been drawn.  It waited,
                # because one 2026-09-17 attempt from here ended on the world map.  Then, on
                # 2026-09-21, the reason given for that ("a tutorial finger covers the camp")
                # was falsified and the tap point was shown to be 103 px off -- on bare ground,
                # 37 px below the ring -- so the tap was restored, aimed at the ring's centre
                # measured from the current frame.
                #
                # THE TAP HAS NOW BEEN TRIED, AND IT FAILED.  Live 2026-09-20T18:43:51Z:
                # SELECT_INFANTRY_CAMP carried training["camp_tap_norm"] = (0.441, 0.4551), i.e.
                # (317, 583) -- inside the ring -- action_backend was ADB so the tap really went
                # out, and the outcome was FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN with
                # after.training EMPTY: neither a menu nor the highlight.  The ring was simply
                # gone, which is what the client does when a tap lands on nothing.
                #
                # Four live taps now, four failures: three at the template's own centre
                # (346, 682, on bare ground; one of them ending on the map) and one inside the
                # ring.  Aiming is therefore not the problem, and the honest reading is that this
                # state is not understood.  The hypothesis worth testing next is that the gold
                # ellipse does not mean "this camp is selected" at all: it is an ellipse drawn
                # over a large multi-part building, carrying a 2 badge, with a tutorial hand
                # pointing at that badge -- which is what a guided step looks like, not a
                # selection.  If that is right, then verify_infantry_camp_highlighted accepting
                # this frame is a FALSE ARRIVAL and the training route's first half has been
                # reporting success it never had.
                #
                # THE HYPOTHESIS IS NOW CONFIRMED OFF THE FRAMES, and issue #82 asked for exactly
                # this: on 2026-09-21 the four live stage A frames
                # (dataset/raw/live_runtime/live_runtime_step_008/009/010_*_20260921T1005*.png)
                # were read at 3x magnification.  The gold ellipse is drawn on the *ground* beside
                # the building, not around it; five small lit action blocks sit inside it; and the
                # tutorial hand's fingertip rests on the rightmost of them -- the one carrying the
                # 2 badge, measured at (379,592).  Across three consecutive frames (08_after,
                # 09_after, 10_after) ``menu_open`` stayed absent and ``camp_tap_norm`` moved by
                # under 2 px, i.e. nothing about the screen is progressing toward a menu.
                #
                # That is a guided tutorial step, so this is a PRECONDITION, not a tap target.
                # Issue #82's own decisive step 3 says what to do once it is identified: record it
                # as precondition-unmet and stop hunting for a coordinate.  The state below does
                # that -- it does NOT wait for a menu (which the frames show is not coming) and it
                # does NOT tap (which four live attempts show does nothing).  The reason string
                # says the precondition out loud, because the old ``camp_menu_never_drawn``
                # described a menu that was merely late and thereby invited the same two waits
                # forever: 45 of 127 historical KEEP_TRAINING_PRODUCTIVE steps -- 35% -- were
                # spent right here.
                #
                # camp_ring.py and training["camp_tap_norm"] are kept on purpose: the ring
                # measurement is sound (46/46 frames, sd 4 px) and it is the input any future
                # attempt needs.  What the ring points AT is now answered -- a tutorial step --
                # and issue #82 closes on that.
                self._camp_menu_waits += 1
                if self._camp_menu_waits > self.MAX_CAMP_MENU_WAITS:
                    return Decision("SAFE_STOP", "camp_entry_is_a_guided_step_not_a_selection", 1.0, "switch_task")
                return Decision("WAIT_FOR_CAMP_MENU", "camp_highlight_is_stage_a_reobserve", world.confidence, "camp_menu_open")
            # The 快捷面板 reports every barracks' state in one frame, which is the one
            # reading the power route below cannot give: it names a camp and highlights
            # it, but does not say whether that camp has a free queue.
            #
            # Measured 2026-09-21, this is what answers "为什么不训练士兵".  The panel was
            # on screen with all three rows reading 已完成, but the frame was misread as
            # `Page.RESEARCH` carrying a borrowed building-queue timer, so `training` was
            # empty and the route walked the power list to the research lab instead.
            #
            # What the panel changes is the *diagnosis*, not the route: it proves a camp
            # is idle, so the goal is known to be startable and the power route is the
            # right way to reach the camp.  The panel's own 加号 is deliberately NOT
            # tapped here -- its template was cut from the training page and does not
            # match the panel (checked on the live panel frame), so a tap at that ROI
            # would be an unproven coordinate.  The power route reaches the camp through
            # controls that are proven.
            #
            # It only fires when a camp is positively idle; a panel that was not read,
            # or whose rows were busy, leaves the route on its existing path.
            if world.page is Page.HOME and world.quick_panel.get("open"):
                idle_camp = next(
                    (
                        camp
                        for camp, reading in (world.quick_panel.get("camps") or {}).items()
                        if reading.get("queue_available") is True and reading.get("status") == "IDLE"
                    ),
                    None,
                )
                if idle_camp is not None:
                    self.idle_camp_from_quick_panel = idle_camp
                    # The row's own arrow is the shortcut (operator §五): one tap onto that task's
                    # page, and it can reach any of the three camps, where the power route reaches
                    # only the infantry one.  Preferred while the reading still carries the row --
                    # the resolver needs ``arrow_norm`` on THIS frame, so a row the panel no longer
                    # draws falls through to the proven power route instead of tapping blind.
                    #
                    # Bounded to two tries per run: a row arrow whose tap does not open the page
                    # must not become a loop on a panel that stays open.
                    row = next(
                        (
                            item
                            for item in (world.quick_panel.get("rows") or ())
                            if str(item.get("key")) == idle_camp and item.get("arrow_norm")
                        ),
                        None,
                    )
                    skill_id = self._panel_row_skill(row)
                    if skill_id is not None and self._panel_row_attempts < self.MAX_PANEL_ROW_ATTEMPTS_PER_RUN:
                        self._panel_row_attempts += 1
                        return Decision(
                            skill_id,
                            f"quick_panel_{idle_camp.lower()}_row_arrow_enters_its_own_task_page",
                            world.confidence,
                            "task_page_open",
                        )
                    return Decision(
                        "OPEN_POWER_OVERVIEW",
                        f"quick_panel_{idle_camp.lower()}_is_idle",
                        world.confidence,
                        "power_overview_open",
                    )
            if world.page is Page.HOME and world.training.get("queue_available") is False:
                return Decision("SAFE_STOP", "training_queue_busy", 1.0, "switch_task")
            if world.page is Page.HOME:
                return Decision("OPEN_POWER_OVERVIEW", "training_goal_requires_power_route", world.confidence, "power_overview_open")
            if world.page is Page.MAP:
                # See the research goal above: both route goals were missing the hop
                # the other four have always had.
                if world.resource_search_open:
                    return Decision("BACK", "close_resource_search_for_training_goal", world.confidence, "resource_search_closed")
                return Decision("OPEN_HOME", "training_goal_requires_home", world.confidence, "home_opened")
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
            and world.idle_marches <= self.reserved_slots(world)
        ):
            return Decision("SAFE_STOP", "reserved_march_for_stamina", 1.0, "stamina_task_slot_preserved")
        if world.page is Page.RESOURCE_DETAIL and world.resource_available:
            return Decision("START_GATHER", "resource_available", world.confidence, "march_page_open")
        if world.page is Page.BUILDING and world.building.get("upgradeable"):
            return Decision("BUILDING_UPGRADE", "building_prerequisites_satisfied", world.confidence, "building_queue_started")
        if world.page is Page.RESEARCH:
            if world.research.get("status") == "IN_PROGRESS" or world.research.get("queue_available") is False:
                return self._leave_or_stop(world, "research_queue_busy", "switch_task")
            if world.research.get("researchable"):
                return Decision("RESEARCH", "research_queue_available", world.confidence, "research_queue_started")
            # Nothing on the page says a node can be started.  Until the node/cost
            # reading exists this is the honest stop, and naming it keeps the goal
            # from looking like it silently did nothing (the previous code fell
            # through every later branch to the same stop with no reason).
            return self._leave_or_stop(world, "research_page_no_startable_node", "switch_task")
        if world.page is Page.TRAINING:
            # Which barracks is open, and which one this goal is for.  The page draws all three tab
            # labels but names only the open camp (``camp_open_label``, read from the title), so the
            # comparison is the page's own word against the goal's own camp -- never "a camp is open,
            # tap the training button".  Operator 2026-09-22 §三: 当前 Goal 是训练矛兵时，应定位矛兵行
            # 右侧箭头，而不是任意选择一个外观相同的蓝色箭头.
            goal_camp = self._goal_camp()
            open_camp = LABEL_TO_CAMP.get(str((world.training or {}).get("camp_open_label") or ""))
            if goal_camp is not None and open_camp is not None and goal_camp != open_camp:
                if self._camp_switch_allowed() and (world.training.get("camp_tab_norm") or {}):
                    self._note_camp_switch()
                    self.desired_camp_label = CAMP_LABELS[goal_camp]
                    return Decision(
                        "SELECT_TRAINING_CAMP",
                        f"another_camp_is_open_and_this_goal_is_{goal_camp}",
                        world.confidence,
                        "goal_camp_open",
                    )
                return self._leave_or_stop(world, "goal_camp_not_open_and_cannot_switch", "switch_task")
            if world.training.get("all_queues_busy"):
                return self._leave_or_stop(world, "all_training_queues_busy", "switch_task")
            if world.training.get("queue_available") is False:
                # Operator §八: "一个兵营正在训练，不得阻止其他空闲兵营执行训练".
                #
                # This used to end the goal here ("inspect_other_training_queue") and nothing ever
                # inspected anything -- there was no hop to reach another barracks, so 矛兵营 and
                # 射手营 went untrained for the whole project while the shield camp's queue was
                # busy.  The page draws all three tabs, so switching is an ordinary tap, and the
                # target is derived from this frame's own reading.
                #
                # Bounded like the camp-menu wait above: at most two switches per run, so a page
                # whose tabs are all busy cannot become a loop.
                if self._camp_switch_allowed() and (world.training.get("camp_tab_norm") or {}):
                    # WHICH camp is the goal's answer, not the resolver's: the brain reads the
                    # camps it has measured, prefers a positively idle one, falls back to a
                    # barracks it has never seen (UNKNOWN is "still worth a look", the same
                    # doctrine camp_training.py states), and refuses to spend a tap on a camp
                    # that was positively read busy.  ``None`` means every other known camp
                    # is busy -- switching would only walk into the same wall, so the goal
                    # leaves the page instead of cycling.
                    self.desired_camp_label = self._choose_target_camp(world)
                    if self.desired_camp_label is not None:
                        self._note_camp_switch()
                        return Decision(
                            "SELECT_TRAINING_CAMP",
                            f"training_queue_busy_switch_to_{self.desired_camp_label}",
                            world.confidence,
                            "another_camp_open",
                        )
                return self._leave_or_stop(world, "training_queue_busy", "inspect_other_training_queue")
            if world.training.get("trainable") and (goal_camp is None or open_camp == goal_camp):
                return Decision("TRAIN_TROOPS", "training_queue_available", world.confidence, "training_queue_started")
        if world.page is Page.INTEL:
            status = world.intel.get("status", "UNKNOWN")
            # The free-gift check lives in the world-map branch, but the
            # unattended intel loop lives on this page: measured live
            # 2026-09-15T04:10:33Z, a run that started on an intel pin popup
            # never stood on the map once, so the check could not run at all.
            # Go there deliberately -- and only when it is actually worth it,
            # so this cannot become a detour every cycle.  Bounded to once per
            # run by ``stamina_panel_checked``, the same flag the map uses.
            if (
                self.claim_free_stamina
                and not self.stamina_panel_checked
                and self._supply_may_be_due()
            ):
                # OPEN_MAP is a HOME-only skill. The live INTEL -> MAP Back
                # transition was measured on 2026-09-15 (0bb).
                return Decision("BACK", "free_stamina_gift_is_due_go_to_the_map", world.confidence, "map_opened")
            if status == "AVAILABLE" and int(world.intel.get("pins") or 0) > 0 and not world.intel.get("mission_type"):
                if world.intel.get("untried_pins") == 0:
                    return Decision("SAFE_STOP", "intel_no_untried_pins", 1.0, "switch_task")
                # The board is a pin map: pins are sighted but no card is open,
                # so the mission type cannot be known yet - the card only exists
                # after a pin is tapped.  Tap one to find out; whatever opens
                # then drives the reviewed chain.  This has to come before the
                # READ_INTEL_LIST branch, which would otherwise observe a board
                # it cannot read and stop.
                return Decision("SELECT_INTEL_PIN", "intel_board_has_pins_but_no_card_open", world.confidence, "intel_pin_card_opened")
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
            # The intel mission id IS the page identity, so it must not be
            # gated on `current_goal`.  Until 2026-09-15 it was, and the
            # consequence was measured live: with goal HOME the game sat on an
            # intel beast target (`mission_id=INTEL_BEAST_10`, 大角鹿 level 22)
            # and control fell through to the two BEAST_HUNT branches below.
            # BEAST_HUNT taps the same button (BTN_BEAST_START_MARCH) so the
            # action was right, but its verifier binds the *map wilderness*
            # target (`verify_beast_march_open` requires name 麝牛 / level 9),
            # so a correct action was recorded as a FAILURE:
            #   episode ally_prep_20260915 step 3, 2026-09-15T02:10:52Z,
            #   BEAST_HUNT / BEAST_MARCH_NOT_PROVEN, while the after-state was
            #   a victory-assured formation page.
            # That poisoned the success rate for both skills.  Keying on the
            # mission id alone routes the target to the skill whose verifier
            # actually binds it (`verify_intel_beast_march_open` maps
            # INTEL_BEAST_10 -> level 22, INTEL_FIREBEAST_10 -> level 20),
            # with no change to the physical tap.  Goal-gated routes are
            # unaffected because each goal's own gate above already safe-stops
            # on a page it does not own.
            if world.beast.get("mission_id") in {"INTEL_BEAST_10", "INTEL_FIREBEAST_10"} and world.beast.get("available"):
                return Decision("INTEL_BEAST_START_MARCH", "intel_beast_target_verified", world.confidence, "intel_beast_march_page_open")
            if world.beast.get("attack_card"):
                # The world-map beast card's 攻击 control (2026-09-18
                # escalation SPEND_STAMINA_ON_BEAST).  Vision claims only the
                # control itself, never a species, so this branch is the
                # species-independent way to a wilderness formation page --
                # the convergence the viewport pan never had.  The stamina is
                # not spent here: the tap only opens the formation page, and
                # DISPATCH_BEAST plus its verifier decide and prove the spend.
                #
                # ``attack_card`` is the template layer's name for "a huntable card is
                # open", and it is a misnomer: the client draws the same card for every
                # huntable beast and puts either 攻击 or 集结 at the bottom, so the flag
                # alone cannot tell an ordinary attack from a rally.  Reading that
                # distinction is the user's hard rule -- a beast offering only 集结 is
                # NOT an ordinary-attack target -- and it is available because the card's
                # own words are read into ``beast_search_result``.
                #
                # Measured live 2026-09-21 on
                # ``live_runtime_step_001_after_refresh_1_20260921T113541458785.png``: a
                # ``等级7 霜鳞避役`` card offering only 集结 (推荐实力683,100,000) read
                # ``has_rally=True, solo_attack=False``, and this branch still answered
                # ATTACK_BEAST_CARD -- i.e. it would have entered a rally target through
                # the ordinary-attack control.  The card's words are required now.
                card = world.beast_search_result or {}
                if card:
                    if not card.get("solo_attack"):
                        # A rally card, or a card whose words could not be read.  Neither
                        # is an ordinary-attack target, and refusing is the safe direction:
                        # the wrong way here spends stamina on a rally the account must
                        # commit troops to.
                        #
                        # The refusal is remembered so the labelled route above stops
                        # re-tapping this same animal.  It resets both search budgets
                        # when it taps -- that is how a *later* beast may search again --
                        # and without a marker that reset also refunded the label route
                        # itself, so the pair repeated forever on one refused target.
                        self.beast_labelled_target_refused = True
                        return Decision(
                            "BACK",
                            "beast_card_is_a_rally_not_a_solo_attack",
                            world.confidence,
                            "beast_card_dismissed",
                        )
                return Decision("ATTACK_BEAST_CARD", "beast_card_attack_control_visible", world.confidence, "beast_march_page_open")
            if self._intel_like and not world.beast:
                # A Hero Journey camp target card: same layout as the beast
                # target card (the 出征 button drives the page) but without the
                # beast mission fields, which is how the two are told apart.
                return Decision("INTEL_HERO_START_MARCH", "intel_hero_target_open", world.confidence, "intel_hero_fight_started")
            # Only the map wilderness beast reaches here: vision emits
            # `available` on this page from the 麝牛/9 dialog alone
            # (`DIALOG_BEAST_MUSK_OX_9`), which carries no mission id.
            if world.beast.get("available") and world.idle_marches and world.idle_marches > 0:
                return Decision("BEAST_HUNT", "beast_available_with_idle_march", world.confidence, "beast_defeated_and_returned")
            if world.beast.get("available") and world.march_used is None:
                return Decision("BEAST_HUNT", "verified_beast_target", world.confidence, "beast_march_page_open")
            # The card is on screen but offers no action: measured live
            # 2026-09-15, a BLOCKED 大师悬赏 (`available=false`,
            # `blocked_reason=POWER_BELOW_RECOMMENDED`) parks the client here.
            #
            # Returning SAFE_STOP used to end every run at its first step, which
            # is not a stop but a dead end: nothing moved the client off the
            # card, so the *next* run hit the same page and stopped again.  The
            # hourly automation produced nothing for as long as the client sat
            # there -- recorded twice, twice with `dispatches=0 claims=0`
            # (evidence/intel_pins_20260915_092119.json and ..._095605.json,
            # the latter with three identical `steps=1 elapsed_s=5.4` nav
            # cycles before run_intel_pins.py gave up on its own cap).
            #
            # Leave the page instead.  Where BACK goes from here is measured,
            # not assumed: `tools/probe_back_from_beast.py` pressed it once on a
            # live blocked card and the client landed on **MAP** with the HUD
            # readable again (stamina 110), which is exactly the page the INTEL
            # goal - and the free-stamina check - start from.
            # `verify_safe_back` accepts this transition (before is neither MAP
            # nor POPUP, after is a different known page), so the step is
            # verifiable rather than merely hopeful.
            #
            # Once per run: if BACK did not actually leave the card, repeating it
            # would ping-pong the loop between this page and the map, spending
            # actions and recording nothing.  The flag mirrors the camp panel's
            # ``unaffordable_camp_panel_left`` guard, and after it is set the
            # honest SAFE_STOP below still applies.
            if not self.beast_card_not_actionable_left:
                self.beast_card_not_actionable_left = True
                return Decision("BACK", "beast_card_not_actionable_leaving_the_page", world.confidence, "map_opened")
            return Decision("SAFE_STOP", "beast_not_actionable", 1.0, "switch_task")
        if world.page is Page.DAILY:
            select_tab = self._select_daily_tab_once(world)
            if select_tab is not None:
                return select_tab
            if world.daily.get("status") == "CLAIMABLE":
                return Decision("DAILY_CLAIM_REWARDS", "daily_task_claimable", world.confidence, "daily_activity_increased")
            if world.daily.get("task_id") == "HERO_RECRUIT_1" and world.daily.get("status") == "AVAILABLE":
                return Decision("DAILY_HERO_RECRUIT", "free_recruit_daily_available", world.confidence, "daily_task_claimable")
            leave = self._leave_daily_panel_once(world)
            if leave is not None:
                return leave
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
            # A goal that does not own this panel leaves it; it does not end the run.
            #
            # The goal-driven branch above (``current_goal == "ALLIANCE"``) answers section HOME
            # by opening the gifts panel.  This page-driven branch had no exit at all, so any
            # *other* goal standing on the alliance panel fell straight through to the stop
            # below -- and ``SAFE_STOP`` is not "skip this observation" here: the runtime records
            # it as DEGRADED and returns from the run.  One screen nobody could act on therefore
            # ended an entire cycle, and since nothing moved the client off the panel, the next
            # cycle opened on the same screen and did it again.
            #
            # States that reach this line, counted over the whole episode history: section HOME
            # 56 times, GIFTS with an unreadable status 14, TECHNOLOGY with no status field 6,
            # HELP 2, HOME with no status 1.  The live instance: goal AUTO_DISCOVERY, page
            # ALLIANCE, ``{"section": "HOME"}``, one step, stop_reason alliance_state_unknown --
            # on a frame that plainly showed 联盟科技 carrying a 25 badge and 联盟互助 a 6.
            #
            # The leave is the project's own bounded one: ``_leave_foreign_page_once`` Backs out
            # exactly once per run and is bound to ``verify_safe_back``, the same hop the panel
            # routines and the research route use when they meet a panel they do not own.
            # (Adding the gifts hop here instead was already measured and rejected: doing that
            # under a research goal ran OPEN_ALLIANCE_GIFTS twelve times and the research page
            # was never once read -- see the research route's own note.)
            #
            # Scoped to a NAMED goal, which is ``_leave_or_stop``'s own rule: "leave a leaf page
            # once if a NAMED goal is stuck on it, else stop by name".  With no goal, the
            # scheduler is probing and a Back would look like work and displace an observation
            # that has real work waiting -- tests/test_multitask_scheduler.py pins exactly that,
            # and it is why the answer below is still a plain stop for that case.
            #
            # This brings the alliance panel into the shape the daily panel already has, and the
            # comparison is the argument: the daily branch got its Back on 2026-09-16 for the same
            # measured reason, "an unknown or empty panel ... stranded the client for every
            # following run".  The alliance panel kept the old answer only because nobody had
            # counted what it cost; the count is above.
            if self.current_goal is not None and self.current_goal != "ALLIANCE":
                leave = self._leave_foreign_page_once(world, owner="ALLIANCE")
                if leave is not None:
                    return leave
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
                # Not while the goal *is* to spend stamina.  Measured live 2026-09-19: the spend
                # goal's runs were consumed by OPEN_STAMINA_SOURCES -> CLAIM_FREE_STAMINA, which
                # raises stamina -- the opposite of the goal -- so the meter went the wrong way,
                # the no-progress rule deferred the goal for 30 minutes, and it came back and did
                # the same thing.  Claiming free stamina is good value and stays for every other
                # goal; it is only contradictory for the one that exists to get the number down.
                and self.current_goal != "SPEND_STAMINA"
                and not self.stamina_panel_checked
                and not world.resource_search_open
                and self._supply_may_be_due()
            ):
                # No ``stamina.current is not None`` here.  Measured
                # 2026-09-15T04:03:02Z: stamina was genuinely 0 and the gauge
                # ROI read returned nothing (the OCR cannot read a lone 0 --
                # best confidence 0.73, flipping between '0' and 'O'; see
                # tools/probe_stamina_zero.py), so this check was skipped on the
                # one frame where the free +150 gift mattered most, and the run
                # went on to open an intel pin instead.  The gauge pill is drawn
                # on those frames (dataset/probe_output/map_gauge_unreadable/),
                # and the panel -- not the gauge -- is what proves whether the
                # gift is claimable, so the number is not needed to decide
                # whether to look.
                self.stamina_panel_checked = True
                return Decision("OPEN_STAMINA_SOURCES", "free_stamina_gift_not_yet_checked_this_run", world.confidence, "stamina_sources_open")
            if self._intel_like:
                return Decision("OPEN_INTEL", "intel_goal_from_world_map", world.confidence, "intel_page_open")
            if self.current_goal == "BEAST_HUNT":
                if world.idle_marches is not None and world.idle_marches <= 0:
                    if self._recallable(world):
                        self.pending_recall = True
                        return Decision("SELECT_MARCH_TO_RECALL", "stamina_goal_needs_a_slot_and_only_gathering_marches_remain", world.confidence, "recall_dialog_open")
                    return Decision("SAFE_STOP", "no_idle_march", 1.0, "wait_for_beast_slot")
                # CAP-Z01: whether this is spendable is a property of the
                # client's own beast table, not of a literal pair here.  The
                # table currently allows exactly the live-verified musk ox, so
                # this reads identically to the old `=="MUSK_OX" and ==9` while
                # a target can now be added -- or refused, like the level-29
                # leopard with its red assessment -- without touching the route.
                if is_dispatchable(world.beast):
                    self.beast_scans_used = 0
                    self.beast_search_used = False
                    # One sprite template per species is the data cost of a
                    # target (CAP-Z01's design note): the skill's tap target is
                    # the sprite itself, so a second dispatchable species gets
                    # its own selection skill rather than reusing the musk
                    # ox's tap.
                    if world.beast.get("visible_target") == "MAMMOTH":
                        return Decision("SELECT_BEAST_TARGET_MAMMOTH", "verified_visible_mammoth_target", world.confidence, "beast_target_dialog_open")
                    return Decision("SELECT_BEAST_TARGET", "verified_visible_low_level_beast", world.confidence, "beast_target_dialog_open")
                if may_evaluate(world.beast):
                    # Added 2026-09-20.  Measured on a live frame: the client printed
                    # 霜鳞避役 beside its 20 badge, the label read at 0.89, the table
                    # resolved it to a row -- and the route recorded nothing, because
                    # the only beast it could act on was one somebody had pre-approved
                    # or cut a sprite for.  The species-specific taps above need one
                    # template per animal; this one needs none, so a species nobody has
                    # measured is *considered* instead of being invisible.
                    #
                    # Nothing is spent here.  The tap opens the card, and the spend is
                    # decided further down by the client's own 胜券在握 strip -- which
                    # is also why an unsafe target is not a risk of this branch: it is
                    # exactly how the level-29 leopard gets read and refused.
                    #
                    # But only while a card has not already been read and refused this
                    # run.  The budget reset below is what re-arms the search, and it
                    # was also what made "read the nearest animal" unbounded: the same
                    # refused beast was re-tapped, re-read and re-refused, four cycles
                    # of two actions each with nothing spent (measured 2026-09-21T12:24Z,
                    # see ``beast_labelled_target_refused``).  Skipping one tap lets the
                    # search below -- which is the route that can actually find a
                    # *different* target -- become the next step.
                    if not self.beast_labelled_target_refused:
                        self.beast_scans_used = 0
                        self.beast_search_used = False
                        return Decision("SELECT_BEAST_TARGET_LABELLED", "beast_labelled_on_the_map_reading_the_clients_own_verdict", world.confidence, "beast_target_dialog_open")
                # The client's own beast search, tried before any viewport pan.
                #
                # SCAN_MAP_FOR_BEAST pans once and re-observes, and its own record
                # says why it never converges: it has no way to *fly* to a target.
                # Five runs of the spend goal spent nothing, and the species
                # templates matched nothing on 23 frames, because a pan searches
                # bare snow.  The client ships the answer to exactly this problem:
                # a search panel whose first tab is 冰原巨兽, whose level slider
                # reaches 5, and whose 搜索 button makes the client locate and
                # centre a matching beast -- which is the convergence the pan
                # lacked.
                #
                # The order matters and is the whole fix: search first, pan second.
                # A pan only ever moves the camera by one viewport and cannot know
                # whether the beast it wants is nearby; the search asks the client,
                # which does know.  Running the pan first would spend the run's
                # budget on the method with no convergence and reach the search
                # with nothing left to try it with.
                #
                # Search is bounded to one attempt per run
                # (``beast_search_used``), so a client that returns nothing cannot
                # become an endless loop of 搜索 taps; after it is spent, the pan
                # budget below still applies and the route still ends with its
                # original named reason.  Nothing here spends stamina: 搜索 costs
                # none and starts no march, and the spend stays behind the client's
                # own 胜券在握 strip three hops further down.
                # ``beast_search_used`` is set when the search is SUBMITTED, not when its
                # result is acted on, so the card check must sit ABOVE the ticket gate.
                # Measured cost of getting this wrong: the run at 11:26Z submitted on step
                # 3 (flag set), step 4 read 等级10 麝牛 back in its before-state, and the
                # branch below -- being inside ``if not self.beast_search_used`` -- was
                # skipped, so the run answered SCAN_MAP_FOR_BEAST over a verified target.
                # The ticket bounds how often the client is ASKED; it does not bound
                # spending an answer that has already arrived.
                if world.beast_search_result.get("solo_attack"):
                    self.beast_search_used = True
                    return Decision(
                        "ATTACK_BEAST_CARD",
                        "solo_attack_card_found_by_the_clients_own_search",
                        world.confidence,
                        "beast_march_page_open",
                    )
                if not self.beast_search_used:
                    if not world.resource_search_open:
                        # The magnifier on the world-map HUD.  Same control the
                        # verified gathering chain taps, so this hop invents
                        # nothing about how to reach the panel.
                        return Decision("SEARCH_RESOURCE", "beast_search_starts_by_opening_the_client_search", world.confidence, "resource_search_open")
                    # The search has answered: the client drew its result card over the panel.
                    #
                    # Measured 2026-09-21 on
                    # ``live_runtime_step_001_after_refresh_1_20260921T110723901682.png``:
                    # the search succeeded and the client put a ``等级10 麝牛`` card on
                    # screen whose orange 攻击 control reads at (361,600), over a map whose
                    # beast sits at (668,424) -- the panel is *still open behind the card*
                    # (its 搜索 button and the 10级 slider are both drawn), so
                    # ``resource_search_open`` stays True and this must be checked BEFORE
                    # the panel-state branches below, all of which assume the card is not
                    # there and would re-issue a search the run has already spent.
                    #
                    # This is the hop the route was missing.  The card matches no reviewed
                    # template, so ``world.beast`` stays empty and neither ``attack_card``
                    # nor ``is_dispatchable`` could ever fire on it; the run verified its
                    # search and then had nowhere to go.  The card's own 攻击 word is the
                    # control, and its box is the coordinate, so both are read from it.
                    #
                    # ``solo_attack`` is what keeps the user's rule: a card carrying 集结
                    # (the measured level-5 mammoth) is a rally target and must not be
                    # entered as an ordinary attack, so that card yields instead -- the
                    # search is bounded, so refusing here cannot become a loop.
                    # The gate is ``resource_selected_tab``, not ``resource_beast_tab_norm``.
                    #
                    # Measured 2026-09-21 on
                    # ``live_runtime_step_002_after_20260921T103154681030.png``: a freshly
                    # opened panel draws ALL five tabs, so ``resource_beast_tab_norm`` was
                    # already non-``None`` (0.0576, 0.7398) while the client had **生肉**
                    # anchored -- ``resource_selected`` read ``MEAT`` and the brackets sat on
                    # the 生肉 cell.  Keying on the label's presence therefore declared the
                    # tab switch unnecessary, fell straight through to ``SUBMIT_BEAST_SEARCH``,
                    # and the 搜索 tap landed on a gatherable node *behind* the panel: the run
                    # recorded ``page MAP -> RESOURCE_DETAIL`` and opened a 等级6 废弃畜牧场
                    # card, with ``BEAST_SEARCH_NOT_SUBMITTED`` as the verifier's verdict.
                    #
                    # The label being *drawn* is not the tab being *selected*.  The selected
                    # pad is the bracket, and ``resource_selected_tab`` is that read, resolved
                    # over the whole strip so a monster tab is nameable.
                    #
                    # Two older signals were tried as the selection test and are measured to
                    # fail here, so neither is reused below:
                    #
                    # * ``resource_selected`` only identifies the four gatherable cells
                    #   (MEAT/WOOD/COAL/IRON) against reviewed templates, so a monster tab reads
                    #   back ``None`` even when it is drawn, bracketed and active (measured
                    #   2026-09-21 on ``beast_tab.png``).  Gating on ``resource_selected ==
                    #   "BEAST"`` re-issues the switch forever.
                    # * ``BTN_SEARCH_BEAST_TAB`` is pinned to the leftmost strip slot, and the
                    #   client moved 野兽 into that slot where the archived frame had 冰原巨兽:
                    #   all three beast-search templates scored NO MATCH on the live frame and
                    #   the hop failed with SEMANTIC_TARGET_NOT_VERIFIED.  ``vision.
                    #   resource_tab_order`` carries that same warning from 2026-09-18.
                    #
                    # ``BEAST`` and not ``GIANT_BEAST`` throughout: the measured level-5 mammoth
                    # card offers only 集结, so a solo-attack route must not treat the rally tab
                    # as equivalent.
                    if world.resource_selected_tab == "BEAST":
                        # Already anchored: nothing to switch, so the search is what this hop
                        # is for.  Kept as the first branch because it is the only state that
                        # may spend the ticket.
                        self.beast_search_used = True
                        return Decision("SUBMIT_BEAST_SEARCH", "beast_tab_and_level_chosen_submitting_search", world.confidence, "beast_target_resent")
                    if "BEAST" not in world.resource_tab_kinds:
                        # The strip was read and carries no 野兽 tab.  Two sub-cases, both of
                        # which must NOT submit a search:
                        #
                        # * only the rally tab is drawn -- measured 2026-09-21 on the archived
                        #   ``beast_tab.png`` frames, where 冰原巨兽 is leftmost and there is no
                        #   野兽 tab at all.  Its cards offer only 集结 (measured on the level-5
                        #   mammoth), so a solo-attack route must decline outright.
                        # * nothing readable at all -- an OCR miss or a strip this build draws
                        #   differently.  Falling through to the pan budget is the honest
                        #   outcome; tapping the strip would pick whichever cell happens to be
                        #   there, and spending the ticket would spend the only search this run
                        #   gets on a panel whose tab was never confirmed.
                        if "GIANT_BEAST" in world.resource_tab_kinds:
                            return Decision("SAFE_STOP", "only_the_rally_beast_tab_is_offered_no_solo_attack_entry", 1.0, "switch_task")
                        # Neither monster tab read: leave ``beast_search_used`` alone and let the
                        # pan budget below run.  A later frame may still read the strip.
                        pass
                    else:
                        # ``BEAST`` is drawn and something else is anchored -- the measured
                        # live state, where the panel opens on 生肉.  Switch to it.
                        return Decision("OPEN_BEAST_SEARCH_TAB", "search_panel_needs_the_ordinary_beast_tab", world.confidence, "beast_search_tab_selected")
                if self.beast_scans_used < self.max_beast_scans:
                    self.beast_scans_used += 1
                    return Decision("SCAN_MAP_FOR_BEAST", "verified_beast_target_not_visible_scanning_map", world.confidence, "beast_target_resent")
                if self.goal_id == "AVOID_STAMINA_WASTE" and not self.spend_route_switched:
                    # The scan budget is spent and no dispatchable target appeared, so this route
                    # cannot spend on this map at all -- measured: five runs, 0 stamina, and the
                    # templates match nothing on 23 frames because they search bare snow.  The
                    # operator's rule for exactly this case is to use another verified task that
                    # costs stamina, and intel is the one this goal already knows how to ride
                    # (SPEND_STAMINA shares the intel flow; the beast way is the only one that was
                    # ever going to be scanned for).  Bounded: once per run, and only after the
                    # beast route has had its whole budget.
                    self.spend_route_switched = True
                    self.current_goal = "SPEND_STAMINA"
                    return Decision("OPEN_INTEL", "spend_goal_switches_to_intel_no_beast_in_view", world.confidence, "intel_page_open")
                return Decision("SAFE_STOP", "verified_beast_target_not_visible", 1.0, "refresh_or_switch_task")
            if self.current_goal == "HOME":
                return Decision("OPEN_HOME", "current_goal_home", world.confidence, "home_opened")
            if (
                self.current_goal in {None, "GATHER_RESOURCE"}
                and world.idle_marches is not None
                and world.idle_marches <= self.reserved_slots(world)
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
            # Ask the weaker, always-knowable question first.  ``idle_marches`` is a
            # count and the client only draws the counter while a march is out, so
            # requiring it here deadlocked the whole gather goal: measured live
            # 2026-09-16T11:09-11:16, three runs answered CHECK_MARCH eight times each
            # and re-observed nothing, because nothing was going to change.  With
            # nothing out, "at least one slot is free" is provable, and the dispatch
            # itself makes the exact capacity readable (04:15:47, max None -> 2).
            # CHECK_MARCH now only runs when marches ARE out and the capacity is still
            # unread -- the one state in which looking again can help.
            free_slot = world.has_free_march_slot
            if free_slot is None:
                return Decision("CHECK_MARCH", "march_capacity_unknown", world.confidence, "march_state_known")
            if not free_slot:
                # Operator directive: a march may be released on demand.  Only
                # a GATHERING march is eligible (see _recallable); a dialog this
                # decision opens is confirmed by the RECALL_MARCH branch.
                if self._recallable(world):
                    self.pending_recall = True
                    return Decision("SELECT_MARCH_TO_RECALL", "no_idle_march_and_a_gathering_march_can_be_released", world.confidence, "recall_dialog_open")
                return Decision("SAFE_STOP", "no_idle_march", 1.0, "no_action")
            if (
                self.current_goal in {None, "GATHER_RESOURCE"}
                and world.idle_marches is not None
                and world.idle_marches <= self.reserved_slots(world)
            ):
                return Decision("SAFE_STOP", "reserved_march_for_stamina", 1.0, "stamina_task_slot_preserved")
            return Decision("SEARCH_RESOURCE", "idle_march_available", world.confidence, "resource_search_open")
        if world.page is Page.MARCH and self._intel_like and not world.beast:
            # The Hero Journey squad-setup page (小队设置): no beast fields, and
            # without this explicit branch the decision fell to the registry
            # fallback, which could pick the *gathering* dispatch skill whose
            # button semantic does not exist on this page (live 2026-09-14:
            # SEMANTIC_TARGET_NOT_VERIFIED loop). The camp fight is an instant
            # hero battle, so dispatching the pre-filled formation is correct.
            #
            # Deliberately above the affordability guard below: this page draws a
            # different control, whose cost colour the guard's ROI has not been
            # measured against, so the guard is kept to the 出征 formation pages.
            return Decision("INTEL_HERO_DISPATCH", "intel_hero_formation_ready", world.confidence, "intel_hero_fight_started")
        if world.page is Page.MARCH and world.stamina.get("cost_affordable") is False:
            # The client drew the dispatch cost in red, which is its own verdict
            # that the account cannot pay for this march.  Tapping 出征 in that
            # state cannot succeed, so attempting it only produces a mislabelled
            # failure.
            #
            # That mislabelling is the reason this branch exists.  Measured
            # 2026-09-15 (learning/episodes.jsonl, all recorded beast dispatches):
            # the 25 that were affordable matched the reviewed dispatch template
            # at phash distance 0, and the 4 that were unaffordable all sat at
            # distance 26 against a threshold of 8 -- because the red digit is
            # painted over the white one the template was cut from.  The executor
            # therefore reported those four as SEMANTIC_TARGET_NOT_VERIFIED, i.e.
            # "the control is not there", which is false and which twice sent
            # earlier sessions looking for a stale template or a wrong
            # coordinate.  Refusing here records what actually happened instead:
            # the control was found, and the account could not afford it.
            #
            # ``is False`` is required, not truthiness: ``None`` means Vision
            # could not measure the colour, and an unmeasured cost must not stop
            # a dispatch that was payable.  The client stays the authority; this
            # only short-circuits the case where it has already said no.
            #
            # SAFE_STOP rather than a detour: the free-stamina route runs from the
            # map (``0au``/``0e``), and what BACK does from a formation page is
            # not measured, so no unverified navigation is invented here.  The
            # run ends honestly and the next cycle replenishes.
            return Decision(
                "SAFE_STOP",
                "dispatch_unaffordable_for_stamina",
                1.0,
                "wait_for_stamina_regen",
            )
        if world.page is Page.MARCH and world.beast:
            if world.beast.get("victory_assured") is True:
                # The route keys on `target_kind`, which HybridVision reads from
                # the formation page's title bar.  It used to key on
                # `world.beast.get("level") == 22`, a level vision copied from
                # whichever duplicate dispatch-button template happened to
                # match, so the choice between the wilderness and intel dispatch
                # was decided by pixel noise.  See vision.py's 出征 block and
                # tools/probe_beast_formation_identity.py.
                #
                # The wilderness route requires *positive* evidence (a title
                # that read 目标：<name>); everything else -- an intel title, an
                # unreadable title, or the INTEL goal -- takes the intel route.
                # The asymmetry is deliberate.  Both dispatch buttons are the
                # same control, so either tap lands, but the two verifiers are
                # not equivalent: `verify_beast_dispatch` demands the measured
                # name 麝牛, so sending an unidentified formation there would
                # record a correct action as a FAILURE, which is the failure
                # mode that has poisoned this project's statistics before.
                # `verify_intel_beast_dispatch` asserts only facts that are true
                # of both pages (victory assured, a real march started), so it
                # stays honest when the identity is not measured.
                if world.beast.get("target_kind") == "WILDERNESS":
                    return Decision("DISPATCH_BEAST", "beast_victory_assured", world.confidence, "beast_march_dispatched")
                return Decision("DISPATCH_INTEL_BEAST", "intel_beast_victory_assured", world.confidence, "intel_beast_march_dispatched")
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
            # When the best this page can offer is to *leave* it, nothing registered advances this
            # goal, and one bounded ordinary attempt is the cheaper first move: it is screened by
            # the resolver's relevance rule and its spend blacklist, the budget is shared with the
            # unnamed-page attempt above, and a step that does nothing at all leaves the ledger
            # wiser and the page still there to leave on the next step.  A page whose only option
            # is a registered route (or any domain skill) is untouched: a hypothesis never
            # outranks a route.
            if (
                self.current_goal
                and skill.id in GENERIC_READY_SKILLS
                and self.ordinary_attempts < self.MAX_ORDINARY_ATTEMPTS
                and not self.ordinary_scan_exhausted
            ):
                self.ordinary_attempts += 1
                return Decision(
                    "TRY_ORDINARY_CONTROL",
                    f"goal_{self.current_goal}_has_only_{skill.id}_left_on_this_page",
                    world.confidence,
                    "ordinary_control_observed",
                )
            return Decision(skill.id, "first_ready_p0_skill", world.confidence, skill.description)
        # The generic ordinary-control attempt (operator directive 2026-09-22, third item).
        # A named goal, a known page, and no registered skill that can advance it: this is
        # exactly the state that used to end in SAFE_STOP while the client sat there
        # printing an ordinary control the frame could have named.  The brain only says
        # THAT one should be tried -- WHICH control is the runtime's frame scan, screened
        # by its spend blacklist, and the existing verifier decides whether the tap did
        # anything.  Bounded per run and disabled once the scan reports the frame offers
        # nothing untried, so this cannot become a tap loop.
        if (
            self.current_goal
            and self.ordinary_attempts < self.MAX_ORDINARY_ATTEMPTS
            and not self.ordinary_scan_exhausted
        ):
            self.ordinary_attempts += 1
            return Decision(
                "TRY_ORDINARY_CONTROL",
                f"goal_{self.current_goal}_has_no_ready_skill_but_the_frame_may_name_a_control",
                world.confidence,
                "ordinary_control_observed",
            )
        return Decision("SAFE_STOP", "no_ready_skill", 1.0, "no_action")

    def _choose_target_camp(self, world: WorldState) -> str | None:
        """Which barracks the goal wants the training page switched to, or ``None``.

        Operator directive 2026-09-22: the switch target is decided by the goal and the
        camps' own states, never by "which camp is open, tap the next tab".  A tap into a
        barracks that was positively read busy is a wasted round trip the directive names
        explicitly ("避免反复切换或进入不需要训练的兵营"), so those are excluded.

        The evidence is exactly what this run has measured, in two layers:

        * **the goal's own camp**, when the goal is one of the per-camp training goals.  The
          goal layer splits the three barracks into three goals precisely so "which camp was
          blocked" is answerable from the record (open issue #86), and that answer is only
          real if the route honours it: a ``LANCER_CAMP_TRAINING`` run that taps 射手营's tab
          is training somebody else's goal.  When that camp is positively busy there is
          nothing for *this* goal on this page, so the answer is ``None`` (leave) rather than
          a switch -- walking to another camp is exactly the mechanical behaviour the
          operator forbade.
        * ``world.camps`` -- per-barracks readings carried in the frame (from the 快捷
          panel or a visited camp page).  ``busy`` follows camp_training's own doctrine:
          ``True`` only from a positive busy reading, ``False`` only from a positive idle
          reading, ``None`` when this run never saw that camp.
        * tabs drawn on *this* frame -- a camp whose tab is not on screen cannot be
          tapped at all, whatever its state says.

        Preference order inside each tier is the operator's own priority: 矛兵营 then
        射手营, 盾兵营 last (it is the camp the route reaches first and the one whose
        queue being busy created this whole problem).  A camp never seen counts as worth
        a look -- ``UNKNOWN`` is "still worth a look" in this codebase's vocabulary -- but
        it loses to any camp positively known idle.

        ``None`` is the honest "do not switch": every other camp whose tab is drawn was
        positively read busy, so the only thing a tap can produce is the same page again.
        """
        training = world.training or {}
        open_label = str(training.get("camp_open_label") or "")
        open_camp = LABEL_TO_CAMP.get(open_label)
        tabs = training.get("camp_tab_norm") or {}
        present = [camp for camp in CAMP_ORDER if CAMP_LABELS.get(camp) in (tabs or {})]

        # The goal's own camp comes first: the goal layer's three per-camp goals are the
        # caller's statement of *which* barracks this run is for.
        goal_camp = self._goal_camp()
        if goal_camp is not None and goal_camp != open_camp and goal_camp in present:
            reading = (world.camps or {}).get(goal_camp) or {}
            positively_busy = (
                reading.get("training") is True or reading.get("status") == "IN_PROGRESS"
            )
            if positively_busy:
                return None  # this goal's camp has nothing to start; do not walk elsewhere
            return CAMP_LABELS[goal_camp]

        idle: list[str] = []
        unknown: list[str] = []
        for camp in present:
            if camp == open_camp:
                continue
            reading = (world.camps or {}).get(camp) or {}
            if reading.get("training") is True or reading.get("status") == "IN_PROGRESS":
                continue  # positively busy: not a switch target
            if reading.get("queue_available") is True or reading.get("status") == "AVAILABLE":
                idle.append(camp)
            else:
                unknown.append(camp)

        priority = ("LANCER_CAMP", "MARKSMAN_CAMP", "SHIELD_CAMP")
        for pool in (idle, unknown):
            for camp in sorted(set(pool), key=priority.index):
                return CAMP_LABELS[camp]
        return None

    def _camp_switch_allowed(self) -> bool:
        """Whether this goal may switch barracks once more; renews the count when the goal changes.

        The per-goal count is what stops a goal from marching through the tabs; the per-run ceiling
        is what stops a *sequence* of goals from doing the same thing between them.  Both are
        required: with only the first, three camp goals could take turns tapping forever, and with
        only the second, the live failure above returns.
        """
        goal = str(getattr(self, "goal_id", "") or self.current_goal or "")
        if goal != self._camp_switch_goal:
            self._camp_switch_goal = goal
            self._camp_switch_attempts = 0
        return (
            self._camp_switch_attempts < self.MAX_CAMP_SWITCHES
            and self._camp_switches_this_run < self.MAX_CAMP_SWITCHES_PER_RUN
        )

    def _note_camp_switch(self) -> None:
        """Count one barracks switch in both budgets."""
        self._camp_switch_attempts += 1
        self._camp_switches_this_run += 1

    #: Which panel row kinds each route works from.  Keyed by the goal layer's own route names, so a
    #: goal nobody has a row kind for is simply not served by the panel -- and no goal id is named here.
    PANEL_ROWS_FOR_ROUTE: dict[str, tuple[str, ...]] = {
        "TRAIN": ("CAMP",),
        "RESEARCH": ("RESEARCH",),
        # 联盟捐献 lives on the alliance route; 我的奖励 is where the daily/goal rewards are collected.
        # 英雄招募 has no route of its own yet, which is stated here rather than invented.
        "ALLIANCE": ("ALLIANCE_DONATION",),
        "DAILY": ("MY_REWARDS",),
    }

    def _goal_route(self) -> str | None:
        """Which route the running goal belongs to, asked of the goal layer.

        ``current_goal`` first: that field *is* the route (the runtime assigns it from
        ``route_for(best_goal.goal_id)``, and a directed run hands ``run_live`` a route name), so it is
        the run's own statement of where it is.  ``goal_id`` is the fallback for callers that set only
        that.  Measured 2026-09-23 in a ``--goal TRAIN`` run: the runtime writes ``goal_id`` only when
        it also sets ``current_goal``, so ``goal_id`` kept the scheduler's last attribution
        (``CLEAR_INTEL``) and asking it first made this run read as the INTEL route while it was in
        TRAIN -- which kept the panel's own branch from firing at all.

        Nothing here compares goal ids or capability ids against each other: ``route_for`` is the goal
        layer's own answer, so a goal nobody has heard of yet still routes correctly.
        """
        from .goal_library import route_for

        return route_for(str(self.current_goal or "")) or route_for(
            str(getattr(self, "goal_id", "") or "")
        )

    def _panel_rows_for_this_goal(self) -> tuple[str, ...]:
        """The panel row kinds the running goal works from; empty when the panel is not its board."""
        return self.PANEL_ROWS_FOR_ROUTE.get(str(self._goal_route() or ""), ())

    def _panel_row_skill(self, row: dict | None) -> str | None:
        """The skill that taps this row's own arrow, or ``None`` when no skill names that row.

        ``None`` means the row is not offered: the callers fall through to their route's own hop
        instead.  That is the whole point -- the previous ``.get(key, "..._SHIELD")`` turned "I have no
        skill for this row" into "tap the 盾兵 row", which is a wrong tap rather than a missing one.
        """
        if not row:
            return None
        return _QUICK_PANEL_ROW_SKILL.get(str(row.get("key") or ""))

    def _actionable_panel_row(self, world: WorldState) -> dict | None:
        """The first panel row this goal can act on, from this frame's own reading.

        A row qualifies when its kind is one the goal's route works from, its *own* state says it is
        idle, and an arrow was located on that row to navigate with.  A row whose state says it is
        running is never offered: 进行中 is not "worth starting again", which is the distinction the
        operator's §四 insists on (进行中 / 已完成待领取 / 已领取 are three different things).
        """
        kinds = self._panel_rows_for_this_goal()
        if not kinds:
            return None
        candidates = [
            row
            for row in (world.quick_panel.get("rows") or ())
            if str(row.get("kind")) in kinds
            and str(row.get("status")) == "IDLE"
            and row.get("arrow_norm")
            # ...and the row's button had to be *located on this frame*.  Measured 2026-09-23
            # 17:21:50: the 盾兵 row read ``已完成`` with the client drawing a **green check** where the
            # other rows draw their blue arrow, so the button scan correctly found none -- and the row
            # was still offered, with the reading's own weak fallback (``PANEL_RELATIVE_ESTIMATE``,
            # x 0.4042) standing in for a button.  The tap landed at x 291 on the row's text and no
            # action bar opened.  A row whose control was not found is not a row to tap: the estimate
            # is honest as a hint and worthless as a coordinate (operator: 未验证不等于可以点).
            and str(row.get("arrow_basis")) == QUICK_PANEL_ARROW_BASIS_SCAN
        ]
        if not candidates:
            return None
        # A goal that names a barracks gets that barracks' row, and only that one: the panel draws
        # three look-alike rows and the operator's §二 is explicit that the arrow must belong to the
        # row the goal is about.  Measured live 23:09:30, this function handed
        # ``SHIELD_CAMP_TRAINING`` the **LANCER** row because it took the first match of the right kind.
        own = self._goal_camp()
        if own:
            # The same form on both sides: ``_goal_camp`` answers ``LANCER_CAMP`` and that is what
            # ``read_quick_panel`` puts in ``row["key"]``.  (The first version of this compared
            # ``f"{own}_CAMP"``, i.e. ``LANCER_CAMP_CAMP``, and so never matched -- which returned
            # ``None`` and left every per-camp goal without a row to tap.)
            for row in candidates:
                if str(row.get("key")) == own:
                    return row
            return None
        # No barracks named: prefer a row the client is *pointing at*.  Measured 2026-09-23 on the live
        # panel (20260923_004054_research_step_003_after_...): 矛兵 空闲中 carried the red dot and
        # 射手 also read IDLE without one.  The operator's §五 is that a red dot means that row has
        # something to do, and it is the only per-row signal the panel draws that distinguishes two
        # otherwise identical IDLE rows -- so it decides the order, not the eligibility.
        for row in candidates:
            if str(row.get("badge")) == "PRESENT":
                return row
        return candidates[0]

    def _goal_camp(self) -> str | None:
        """The barracks this run's goal names, or ``None`` for a goal that names none.

        The one mapping is ``goal_library.CAMP_GOAL_FOR`` -- imported here rather than
        copied, because a second copy of "which goal is which camp" is exactly how the two
        drift apart, and the goal layer is where that pairing is defined.
        """
        goal_id = str(getattr(self, "goal_id", "") or "")
        if not goal_id:
            return None
        from .goal_library import CAMP_GOAL_FOR

        for camp, camp_goal in CAMP_GOAL_FOR.items():
            if camp_goal == goal_id:
                return camp
        return None


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
