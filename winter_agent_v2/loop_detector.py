"""LOOP_DETECTOR_V1 — a Goal-local loop detector, and the recovery ladder it drives.

Four engineering designs were taken from MAI, and only these four:

1. **AAA / ABA loop detection.**  A flow that repeats the same context-action-feedback
   triple is stuck, and the shape of the repetition names which kind of stuck.
2. **Context -> Action -> Feedback.**  Written as one dataclass rather than three parallel
   logs, because the thing that is stuck is the *triple*, not any of its parts.  ``page``
   and ``relevant_state_hash`` are the context, ``skill_id``/``semantic_target`` are the
   action, ``verifier_outcome`` is the feedback.
3. **Planner / Executor / Verifier separation.**  This module is a planner of *recovery*:
   it answers "you are looping, do this next" and nothing else.  It never taps a device
   (the host's executor does), never decides what the client means (the adapter's or the
   runtime's verifier does), and never ranks Goals (the Scheduler does).
4. **Session timeline telemetry.**  Every observation, detection, rung and retraction is
   appended to a bounded timeline, so "where did the run spend itself" is readable from
   the run's own output instead of inferred from a stop reason.

Four things are explicitly **not** here, per the directive, and each is enforced by what
the module is able to reference rather than by discipline: there is no second Scheduler,
no second Executor, no second WorldState, and no second local model.  This file imports
only the standard library — it cannot reach a runtime, a scheduler, a registry or a model
even by accident, and ``tests/test_loop_detector_boundary.py`` pins that.

Why a detector is needed at all, measured 2026-09-30 by replaying ``learning/episodes.jsonl``
through this module (``dataset/truth_audit/loop_detector_20260930/``): real flows spend real
minutes retrying, and none of it was visible to any counter that existed.

* ``CLOSE_POPUP`` on ``BTN_CLOSE`` inside one ``AUTO_DISCOVERY`` flow failed **60 times**, all
  with ``POPUP_CLOSE_NOT_PROVEN``, every one of them on page ``POPUP`` and with
  ``goal_progress`` *unread* (stream lines 1595-1715).  Sixty attempts to close one popup.
* ``OPEN_ALLIANCE`` on ``BTN_OPEN_ALLIANCE`` was issued three times **consecutively** in one
  ``ALLIANCE_ROUTINE`` flow, from the same page, with ``goal_progress`` false each time
  (stream lines 1253, 1281, 1303).  Three identical taps with nothing gained is AAA.
* ``SCROLL_QUICK_PANEL_TASKS`` scrolled ``QUICK_PANEL_SCROLL_CURRENT`` past the point where the
  ladder was spent, and the panel then moved (stream lines 6950 -> 6954).  That one is this
  design's own false positive, and it is recorded rather than tuned away: the number that
  matters is not "how often did it fire" but "how often was it wrong", which is why
  ``LOOP_FALSE_POSITIVE`` is a metric and not an apology.

The goal-level ``no_progress_streak`` in ``goal_utility`` lowers a Goal's *priority* between
rounds, which is the right remedy for "this Goal keeps failing" and the wrong remedy for "this
Goal is about to re-issue the same tap for the fourth time".  This module is the fine-grained
half.

The last rung ends the *session*, never the run.  ``RECOVERY_LADDER``'s final entry is
``defer_goal``: the session returns to the Scheduler through the loop edge that already
exists, the Goal is deferred, and AUTO continues with the next Goal.  A detector that could
stop AUTO would be a second Scheduler wearing a detector's name.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

# ----------------------------------------------------------------- metric vocabulary
#
# The four names the directive requires be provable.  They are strings rather than an enum
# because they land in episode rows and JSON summaries, where a string is what a reader
# greps for.

#: A loop matched a pattern.  Counted at fire time, before anyone knows whether it was real.
LOOP_DETECTED = "LOOP_DETECTED"
#: A detection was retracted by the very next observation showing progress.  Counted
#: separately and never subtracted silently: the honest reading is "we fired N times and
#: were wrong M of them", and a reader must be able to see both numbers.
LOOP_FALSE_POSITIVE = "LOOP_FALSE_POSITIVE"
#: A rung was applied and the flow then moved on (progress, or a new action).  This is the
#: only evidence that the ladder is worth its cost.
LOOP_RECOVERED = "LOOP_RECOVERED"
#: The ladder ran out and the Goal was handed back.  The session ended; the run did not.
LOOP_DEFERRED = "LOOP_DEFERRED"
#: The run kept going after a deferral.  Emitted by the caller that owns the run loop, not
#: by the detector, because only the run knows whether it continued.
AUTO_CONTINUED = "AUTO_CONTINUED"

#: Detections minus retractions.  Derived for the report; never stored as a counter, since
#: a stored net would let the two halves drift apart.
LOOP_DETECTED_NET = "LOOP_DETECTED_NET"


# ----------------------------------------------------------------- the recovery ladder
#
# Fixed order, cheapest first, and the order is the directive's.  Every rung is an action
# the *existing* layers can already perform -- the ladder names them, it does not implement
# them, which is what keeps this from becoming a second Executor.

#: Re-observe and retry the same step.  The engine already owns this loop.
RUNG_SEMANTIC_RETRY = "semantic_retry"
#: Look at the current page again, cheaply, without widening the search.
RUNG_LOCAL_REOBSERVE = "local_reobserve"
#: Look again with every expensive sweep allowed.  Reuses the runtime's own widening pass.
RUNG_WIDEN_OBSERVE = "widen_observe"
#: Leave and re-enter the feature the flow is stuck in.  The adapter's ``recover``.
RUNG_FEATURE_REOPEN = "feature_reopen"
#: Go HOME and re-approach from a known page.  The runtime's existing OPEN_HOME skill.
RUNG_HOME_RECOVERY = "home_recovery"
#: Hand the Goal back to the Scheduler.  The session ends; AUTO continues elsewhere.
RUNG_DEFER_GOAL = "defer_goal"

RECOVERY_LADDER: tuple[str, ...] = (
    RUNG_SEMANTIC_RETRY,
    RUNG_LOCAL_REOBSERVE,
    RUNG_WIDEN_OBSERVE,
    RUNG_FEATURE_REOPEN,
    RUNG_HOME_RECOVERY,
    RUNG_DEFER_GOAL,
)

#: Rungs that need the device for a *navigation* action rather than a plain re-look.  Used
#: by the engine to know which rungs it may skip when a host cannot perform them, and by
#: the report to explain why a ladder stopped short.
DEVICE_RUNGS: frozenset[str] = frozenset({RUNG_HOME_RECOVERY})


class LoopPattern(str, Enum):
    """The four shapes the directive names.  A string enum so it lands in JSON readably."""

    #: The same context-action-feedback triple, three times running.
    AAA = "AAA"
    #: Two signatures alternating, twice: A B A B.
    ABAB = "ABAB"
    #: The same action repeated while the Goal made no progress, even though the frame moved.
    SAME_ACTION_NO_PROGRESS = "SAME_ACTION_NO_PROGRESS"
    #: A page cycle repeating: the client is being walked in a circle.
    NAVIGATION_LOOP = "NAVIGATION_LOOP"


#: The fields of a state that a loop can be *stuck about*.  Deliberately short: a hash over
#: the whole WorldState would change on every frame for reasons unrelated to progress
#: (a timer ticking, a dot blinking) and no repeat would ever match -- which would make the
#: detector silently useless rather than visibly wrong, the worst of the two.
RELEVANT_STATE_FIELDS: tuple[str, ...] = (
    "page", "popup", "march_used", "march_max", "normal_idle_slots",
)


def _read(state: Any, name: str) -> Any:
    """One field from a WorldState, a dict, or nothing at all."""
    if state is None:
        return None
    if isinstance(state, Mapping):
        return state.get(name)
    return getattr(state, name, None)


def _plain(value: Any) -> Any:
    """A hashable, JSON-stable projection of one state field."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return repr(value)


def relevant_state_hash(state: Any) -> str:
    """A short, stable digest of the state fields a loop can be stuck about.

    ``empty != none`` applies: an unread field is recorded as ``None`` in the projection and
    therefore hashes to a value *distinct* from a read zero.  Flattening an unread march
    count to 0 would make two different situations hash alike, and the whole point of the
    hash is to tell "the same situation" from "a different one".
    """
    projection = {name: _plain(_read(state, name)) for name in RELEVANT_STATE_FIELDS}
    blob = json.dumps(projection, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def progress_from_outcome(outcome: Any) -> bool | None:
    """Map a unified step outcome onto the tri-state ``progress``.

    ``True`` only for an outcome that means the Goal moved.  ``False`` only for one that
    means it did not.  Everything else is ``None`` -- *unread*, not zero.  ``STILL_PENDING``
    is the case worth naming: a cast still running has neither progressed nor failed, and
    calling it ``False`` would let the detector count honest work as a loop.
    """
    name = str(getattr(outcome, "value", outcome) or "").strip().upper()
    if name in ("SUCCESS", "PROGRESS"):
        return True
    if name in ("FAILED", "FAILURE"):
        return False
    return None


def no_progress_block(block: Sequence["LoopSignature"]) -> bool:
    """True only when *every* step in the block was verified as making no progress.

    ``is False``, never ``not True``.  This is the single qualification every pattern shares,
    and it is deliberately the strictest one:

    * a block containing one step that *did* progress is honest work, not a loop -- the flow
      moved, it simply moved somewhere the pattern still recognises;
    * a block of entirely **unread** progress is a block the detector knows nothing about.
      Firing there would be the worst failure available: the detector would be confident
      exactly where its input is empty, and ``progress_from_outcome``'s ``None`` would have
      been flattened to a zero one layer down.  §真值纪律 applies to counters too.

    The cost is a false *negative* -- a real loop whose steps were never judged as failed is
    not reported.  That is the correct trade: a missed loop costs one more step of the flow,
    while a false detection spends a rung and rewrites the session's ending.
    """
    return all(s.progress is False for s in block)


@dataclass(frozen=True)
class LoopSignature:
    """One step, as the detector sees it: context, action, feedback.

    ``verifier_outcome`` and ``progress`` are separate on purpose.  The outcome is what the
    verifier said about *this step*; progress is what it said about the *Goal*.  A step can
    succeed while the Goal stands still (the daily cycle below: every tap verified, no
    meter moved), and that difference is exactly the one the no-progress pattern needs.
    """

    role_id: str = ""
    page: str = ""
    goal_id: str = ""
    skill_id: str = ""
    semantic_target: str = ""
    state_hash: str = ""
    verifier_outcome: str = ""
    progress: bool | None = None

    @property
    def key(self) -> tuple[str, ...]:
        """The full triple, including the state hash and the verdict.

        Three equal keys means literally the same action, on the same situation, with the
        same answer -- the safest possible basis for calling something repetitive.
        """
        return (self.role_id, self.page, self.goal_id, self.skill_id,
                self.semantic_target, self.state_hash, self.verifier_outcome)

    @property
    def action_key(self) -> tuple[str, ...]:
        """What "the same action" means: same role, same Goal, same skill, same target.

        Page, state and verdict are deliberately **out**: a flow that keeps issuing the same
        tap while the page drifts and the frame changes is still issuing the same tap, and
        that is the pattern a full-key-only detector misses.
        """
        return (self.role_id, self.goal_id, self.skill_id, self.semantic_target)

    @property
    def page_key(self) -> tuple[str, ...]:
        return (self.role_id, self.page)

    @property
    def move_key(self) -> tuple[str, ...]:
        """Page *and* action: what a navigation loop is periodic in.

        Deliberately not the whole signature.  ``state_hash`` and ``verifier_outcome`` may
        legitimately differ between two laps of the same circuit (a reward popup appears on
        one lap and not the other), and requiring them to match would make the pattern fire
        only on cases AAA and ABAB already catch.  But requiring the *moves* to repeat is what
        separates a circle from honest work: ``HOME -> ALLIANCE -> HOME -> ALLIANCE`` with a
        different control tapped on each visit is a client being used, not a client being
        walked in a circle, and a page-only test calls both the same thing.  The cost of the
        stricter test is measured in
        ``dataset/truth_audit/loop_detector_20260930/replay_report.json``.
        """
        return (self.role_id, self.page, self.goal_id, self.skill_id, self.semantic_target)

    @property
    def digest(self) -> str:
        blob = "|".join(str(part) for part in self.key)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]

    def as_row(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id, "page": self.page, "goal_id": self.goal_id,
            "skill_id": self.skill_id, "semantic_target": self.semantic_target,
            "state_hash": self.state_hash, "verifier_outcome": self.verifier_outcome,
            "progress": self.progress, "digest": self.digest,
        }


@dataclass(frozen=True)
class LoopVerdict:
    """What the detector concluded, and what it wants done about it.

    ``provisional`` is the honest half of the design.  A detection is a *claim*: the next
    observation either confirms it (the flow is still stuck) or retracts it (the flow moved,
    and we were two frames too early).  Callers do not have to act differently for a
    provisional verdict -- the rung is already the cheap one -- but the ledger keeps the
    distinction so ``LOOP_FALSE_POSITIVE`` can be reported rather than assumed away.
    """

    detected: bool = False
    pattern: str = ""
    rung: str = ""
    reason: str = ""
    repeats: int = 0
    signature_digest: str = ""
    provisional: bool = False
    retracted: bool = False
    escalated: bool = False

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return bool(self.detected)

    @property
    def wants_defer(self) -> bool:
        """True when the ladder is spent and the Goal must go back to the Scheduler."""
        return bool(self.detected and self.rung == RUNG_DEFER_GOAL)

    def as_row(self) -> dict[str, Any]:
        return {
            "detected": self.detected, "pattern": self.pattern, "rung": self.rung,
            "reason": self.reason, "repeats": self.repeats,
            "signature": self.signature_digest, "provisional": self.provisional,
            "retracted": self.retracted, "escalated": self.escalated,
        }


@dataclass
class _Pending:
    """A detection awaiting its one frame of confirmation."""

    action_key: tuple[str, ...]
    pattern: str
    rung: str
    signature_digest: str


class LoopDetector:
    """A bounded, per-flow loop detector.  One instance per session; never shared.

    ``window`` bounds the memory and the search: a cycle longer than the window cannot be
    seen, and that is a deliberate cost -- an unbounded pattern search over a long run is
    how a detector starts reporting "loops" that span two different Goals.

    Every counter is per-instance so a session's ledger cannot leak into the next Goal's.
    """

    #: How many signatures are remembered.  Long enough for the longest pattern
    #: (``NAV_MAX_PERIOD`` * ``NAV_REPEATS`` = 8) plus room to see the retraction frame.
    WINDOW = 12
    #: Same full key this many times running.
    AAA_REPEATS = 3
    #: A two-signature alternation needs four entries to be a cycle rather than a coincidence.
    ABAB_ENTRIES = 4
    #: Same action, no progress, this many times.
    NO_PROGRESS_REPEATS = 3
    #: A page cycle of period 2..4 repeating this many times.
    NAV_REPEATS = 2
    NAV_MIN_PERIOD = 2
    NAV_MAX_PERIOD = 4

    def __init__(
        self,
        *,
        window: int | None = None,
        aaa_repeats: int | None = None,
        abab_entries: int | None = None,
        no_progress_repeats: int | None = None,
        nav_repeats: int | None = None,
        nav_min_period: int | None = None,
        nav_max_period: int | None = None,
        ladder: Sequence[str] = RECOVERY_LADDER,
    ) -> None:
        self.window = max(4, int(window if window is not None else self.WINDOW))
        self.aaa_repeats = max(2, int(aaa_repeats if aaa_repeats is not None else self.AAA_REPEATS))
        self.abab_entries = max(4, int(abab_entries if abab_entries is not None else self.ABAB_ENTRIES))
        self.no_progress_repeats = max(
            2, int(no_progress_repeats if no_progress_repeats is not None else self.NO_PROGRESS_REPEATS)
        )
        self.nav_repeats = max(2, int(nav_repeats if nav_repeats is not None else self.NAV_REPEATS))
        self.nav_min_period = max(2, int(nav_min_period if nav_min_period is not None else self.NAV_MIN_PERIOD))
        self.nav_max_period = max(
            self.nav_min_period,
            int(nav_max_period if nav_max_period is not None else self.NAV_MAX_PERIOD),
        )
        self.ladder: tuple[str, ...] = tuple(ladder) or RECOVERY_LADDER
        self._signatures: deque[LoopSignature] = deque(maxlen=self.window)
        #: Per-action rung index.  Reset to 0 the moment the action makes progress, so a
        #: Goal that loops today does not start tomorrow's session one rung up.
        self._rung_index: dict[tuple[str, ...], int] = {}
        self._pending: _Pending | None = None
        self.counts: dict[str, int] = {
            LOOP_DETECTED: 0, LOOP_FALSE_POSITIVE: 0, LOOP_RECOVERED: 0, LOOP_DEFERRED: 0,
        }
        #: Bounded timeline.  Telemetry, not truth: it is the run's own account of what it
        #: was doing, and it never becomes an input to a decision.
        self.timeline: deque[dict[str, Any]] = deque(maxlen=64)
        self.patterns: dict[str, int] = {p.value: 0 for p in LoopPattern}

    # ------------------------------------------------------------------ observation

    def observe(self, signature: LoopSignature) -> LoopVerdict:
        """Feed one step.  Returns what (if anything) should be done about it.

        Order matters and is: settle the pending detection, remember the new signature,
        then look for a pattern.  Settling first is what makes the retraction honest -- it is
        answered by the *actual next* observation, not by a guess about what comes next.
        """
        settle = self._settle(signature)
        if settle is not None and settle.retracted:
            # The flow moved on.  This observation is not itself a detection, and reporting
            # one here would double-count the frame that disproved the previous claim.
            self._signatures.append(signature)
            self._timeline("retracted", signature, settle)
            return settle

        self._signatures.append(signature)
        pattern, repeats, why = self._match()
        if pattern is None:
            self._timeline("ok", signature, None)
            return LoopVerdict()

        action_key = signature.action_key
        index = min(self._rung_index.get(action_key, 0), len(self.ladder) - 1)
        rung = self.ladder[index]
        # A repeat of a cycle we are already tracking is a *confirmation*: the rung that was
        # handed out did not work, so the next observation must escalate rather than repeat it.
        escalated = bool(self._pending is not None and self._pending.action_key == action_key)
        if escalated:
            index = min(index + 1, len(self.ladder) - 1)
            rung = self.ladder[index]
        self._rung_index[action_key] = index

        self._pending = _Pending(action_key=action_key, pattern=pattern.value,
                                 rung=rung, signature_digest=signature.digest)
        self.counts[LOOP_DETECTED] += 1
        self.patterns[pattern.value] += 1
        if rung == RUNG_DEFER_GOAL:
            self.counts[LOOP_DEFERRED] += 1

        verdict = LoopVerdict(
            detected=True, pattern=pattern.value, rung=rung,
            reason=f"{pattern.value}: {why}",
            repeats=repeats, signature_digest=signature.digest,
            provisional=True, escalated=escalated,
        )
        self._timeline("detected", signature, verdict)
        return verdict

    def note_progress(self, *, goal_id: str = "", skill_id: str = "", semantic_target: str = "") -> None:
        """The adapter says the domain moved.  Forget the ladder for that action.

        Called when a layer *knows* progress happened in a way the step outcome cannot show
        (a cast landing two steps later, a barracks count dropping).  Without this the rung
        index would only ever climb, and an intermittently-stuck flow would be deferred for
        having been stuck an hour ago.
        """
        self._forget_matching(goal_id=goal_id, skill_id=skill_id, semantic_target=semantic_target)

    def reset(self) -> None:
        """Forget everything.  Keeps the counters -- this is a new *flow*, not a new ledger."""
        self._signatures.clear()
        self._rung_index.clear()
        self._pending = None

    # ------------------------------------------------------------------ internals

    def _settle(self, signature: LoopSignature) -> LoopVerdict | None:
        """Confirm or retract the pending detection using this observation.

        Three outcomes, and only the first is a false positive:

        * progress on the *tracked action* -- the claim was wrong.  Counted as
          ``LOOP_FALSE_POSITIVE``, because that is what it is: the flow was not stuck.
        * progress on a *different action* -- the flow moved on, which says nothing about
          whether the tracked action was stuck.  The claim is dropped as stale.  Counting
          this as a false positive would inflate the error rate with cases the detector never
          got wrong, and a metric nobody trusts is worse than no metric.
        * no progress yet -- the claim stands and the next repeat escalates it.
        """
        pending = self._pending
        if pending is None:
            return None
        same_action = signature.action_key == pending.action_key
        if not same_action:
            # Stale, but earned: a rung had been spent on that action and the flow is now
            # somewhere else, so the ladder did its job.
            if self._rung_index.get(pending.action_key, 0) >= 1:
                self.counts[LOOP_RECOVERED] += 1
            self._rung_index.pop(pending.action_key, None)
            self._pending = None
            return None
        if signature.progress is True:
            self.counts[LOOP_FALSE_POSITIVE] += 1
            if self._rung_index.get(pending.action_key, 0) >= 1:
                # A real intervention had been applied before the flow moved.
                self.counts[LOOP_RECOVERED] += 1
            # ``pop``, not ``= 0``.  A zero-valued entry is indistinguishable from no entry to
            # the look-up that reads a rung (``.get(key, 0)``), but not to ``_top_rung``, which
            # takes the maximum of the values -- so writing 0 left the action visibly on rung
            # one after the Goal had moved, and the next flow started a rung up.  Deleting the
            # key makes the two readers agree, which is what ``note_progress`` already does.
            self._rung_index.pop(pending.action_key, None)
            self._pending = None
            return LoopVerdict(
                retracted=True, pattern=pending.pattern, rung=pending.rung,
                reason=f"{LOOP_FALSE_POSITIVE}: progress arrived after {pending.rung}",
                signature_digest=pending.signature_digest,
            )
        return None

    def _forget_matching(self, *, goal_id: str, skill_id: str, semantic_target: str) -> None:
        goal = str(goal_id or "")
        skill = str(skill_id or "")
        target = str(semantic_target or "")
        for key in list(self._rung_index):
            _role, key_goal, key_skill, key_target = (list(key) + ["", "", "", ""])[:4]
            if goal and key_goal != goal:
                continue
            if skill and key_skill != skill:
                continue
            if target and key_target != target:
                continue
            del self._rung_index[key]
        if self._pending is not None:
            self._pending = None

    def _match(self) -> tuple[LoopPattern | None, int, str]:
        """First matching pattern in a fixed order, with the count that matched.

        The order is AAA, ABAB, SAME_ACTION_NO_PROGRESS, NAVIGATION_LOOP: from the most
        specific claim to the most general.  A frame that satisfies AAA is also a repeat of
        the same action with no progress, and calling it AAA is the more useful answer --
        it says the *state* did not move either.

        Every pattern additionally requires ``no_progress_block``: a repeat is only a loop
        when the block verifiably made no progress.  Shape alone is not enough -- three
        identical successes, or three steps whose outcome nobody could read, are not a loop,
        and firing on them is the way a detector becomes something operators turn off.
        """
        sigs = list(self._signatures)
        n = len(sigs)

        if n >= self.aaa_repeats:
            tail = sigs[-self.aaa_repeats:]
            if len({s.key for s in tail}) == 1 and no_progress_block(tail):
                return (LoopPattern.AAA, self.aaa_repeats,
                        f"the same signature {self.aaa_repeats}x running ({tail[-1].digest})")

        if n >= self.abab_entries:
            a, b, c, d = sigs[-4:]
            if a.key == c.key and b.key == d.key and a.key != b.key:
                if no_progress_block((a, b, c, d)):
                    return (LoopPattern.ABAB, 2,
                            f"two signatures alternating: {a.digest} / {b.digest}")

        if n >= self.no_progress_repeats:
            tail = sigs[-self.no_progress_repeats:]
            if len({s.action_key for s in tail}) == 1 and no_progress_block(tail):
                return (LoopPattern.SAME_ACTION_NO_PROGRESS, self.no_progress_repeats,
                        f"{tail[-1].skill_id or '(no skill)'}"
                        f"{' -> ' + tail[-1].semantic_target if tail[-1].semantic_target else ''}"
                        f" repeated {self.no_progress_repeats}x with no Goal progress")

        nav = self._match_navigation(sigs)
        if nav is not None:
            return nav
        return (None, 0, "")

    def _match_navigation(self, sigs: list[LoopSignature]) -> tuple[LoopPattern, int, str] | None:
        """A page-and-move cycle of period 2..4 repeated ``nav_repeats`` times, gaining nothing.

        Periodicity is required of ``move_key``, not of ``page_key`` -- see that property for
        why.  A single repeated move is AAA's business, and calling it navigation would
        mislabel the remedy (there is nothing to navigate back to).
        """
        n = len(sigs)
        for period in range(self.nav_min_period, self.nav_max_period + 1):
            span = period * self.nav_repeats
            if n < span:
                continue
            block = sigs[-span:]
            moves = [s.move_key for s in block]
            if len({moves[i] for i in range(period)}) < 2:
                continue
            if any(moves[i] != moves[i % period] for i in range(span)):
                continue
            if not no_progress_block(block):
                continue
            names = [str(moves[i][1]) for i in range(period)]
            return (LoopPattern.NAVIGATION_LOOP, self.nav_repeats,
                    f"pages {' -> '.join(names)} cycled {self.nav_repeats}x with the same moves "
                    f"and no progress")

    def _timeline(self, kind: str, signature: LoopSignature, verdict: LoopVerdict | None) -> None:
        self.timeline.append({
            "kind": kind,
            "digest": signature.digest,
            "role_id": signature.role_id,
            "goal_id": signature.goal_id,
            "skill_id": signature.skill_id,
            "semantic_target": signature.semantic_target,
            "relevant_state_hash": signature.state_hash,
            "page": signature.page,
            "outcome": signature.verifier_outcome,
            "progress": signature.progress,
            **({"pattern": verdict.pattern, "rung": verdict.rung} if verdict else {}),
        })

    # ------------------------------------------------------------------ reporting

    def summary(self) -> dict[str, Any]:
        """The ledger, ready for ``SessionResult.metrics`` or a run's audit row.

        ``LOOP_DETECTED_NET`` is derived here rather than counted, so the two halves cannot
        drift: a stored net is a number that can be right while its inputs are wrong.
        """
        detected = int(self.counts.get(LOOP_DETECTED, 0))
        false_positive = int(self.counts.get(LOOP_FALSE_POSITIVE, 0))
        return {
            LOOP_DETECTED: detected,
            LOOP_FALSE_POSITIVE: false_positive,
            LOOP_RECOVERED: int(self.counts.get(LOOP_RECOVERED, 0)),
            LOOP_DEFERRED: int(self.counts.get(LOOP_DEFERRED, 0)),
            LOOP_DETECTED_NET: max(0, detected - false_positive),
            "LOOP_PATTERNS": {k: v for k, v in self.patterns.items() if v},
            "LOOP_LADDER_TOP": self._top_rung(),
            "LOOP_TIMELINE": list(self.timeline),
        }

    def _top_rung(self) -> str:
        if not self._rung_index:
            return ""
        index = max(self._rung_index.values())
        return self.ladder[min(index, len(self.ladder) - 1)]


def signature_rows(signatures: Iterable[LoopSignature]) -> list[dict[str, Any]]:
    """Convenience for a replay harness: the signatures as plain rows."""
    return [s.as_row() for s in signatures]


__all__ = [
    "AUTO_CONTINUED", "DEVICE_RUNGS", "LOOP_DEFERRED", "LOOP_DETECTED",
    "LOOP_DETECTED_NET", "LOOP_FALSE_POSITIVE", "LOOP_RECOVERED", "LoopDetector",
    "LoopPattern", "LoopSignature", "LoopVerdict", "RECOVERY_LADDER",
    "RELEVANT_STATE_FIELDS", "RUNG_DEFER_GOAL", "RUNG_FEATURE_REOPEN",
    "RUNG_HOME_RECOVERY", "RUNG_LOCAL_REOBSERVE", "RUNG_SEMANTIC_RETRY",
    "RUNG_WIDEN_OBSERVE", "no_progress_block", "progress_from_outcome", "relevant_state_hash",
    "signature_rows",
]
