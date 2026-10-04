"""LOOP_WATCH_V1 -- the main AUTO path's half of LOOP_DETECTOR_V1.

The defect this exists for
--------------------------
``LoopDetector`` is fed from exactly one place: ``SessionEngine._run_one_step``.  Eight Goals
have a session route; **every other Goal walks ``LiveRuntime.run``'s ordinary atomic loop, and
that path had no detector at all** (``runtime.py`` referenced ``LoopDetector`` zero times).
Measured in the 24 h to 2026-10-04T03:16Z: 58.7 % of the main path's *successful* steps moved
their Goal not at all, and ``HERO_RECRUIT_ADVANCED`` issued **171 consecutive steps that passed
their verifier and produced zero Goal progress** -- the textbook ``SAME_ACTION_NO_PROGRESS``,
one perfect input to this detector, never once shown to it.

Why the fix is a projection and not a second detector
----------------------------------------------------
The engine's own boundary test pins the detector to **one** call site, and its design line is
that "a second ``observe`` call site is a second notion of *this is a loop*".  So this module
does not decide what a loop is.  It owns one real ``LoopDetector`` per run and does the only
two things the main path needs that the engine got from its adapters:

1. **It builds the signature** out of facts the run has already computed.  The load-bearing
   one is ``progress``.  The engine has to fall back to ``progress_from_outcome`` because no
   adapter ever assigns ``StepVerdict.progress``, so on a session row ``progress`` is the
   step's own outcome wearing the Goal's name -- and a flow whose every tap succeeds is, to
   that detector, honest work.  The main path is luckier: it already computes the Goal-level
   fact in ``LiveRuntime.run`` -- ``progress_moved``, tri-state -- and this module is handed
   that, so it never needs the fallback.  Named rather than numbered on purpose: a line number
   in a docstring rots the first time anything above it is edited, and this one already had.

2. **It projects ``RECOVERY_LADDER`` onto surfaces the main path already has.**  The rungs are
   the ladder's, not this file's; the *remedies* are the run's existing ones.  See
   ``RUNG_INTENTS`` for the table and ``UNAVAILABLE_ON_MAIN_PATH`` for the one rung whose
   remedy lives in a session adapter and therefore has no main-path surface at all.

The ladder's order is preserved so the escalation rate is the detector's, not this file's: one
rung per repeat of the same action, reset only by real progress.

What this module may not become
-------------------------------
Held to ``loop_detector``'s own rule, and checked the same way (``tests/test_loop_main_path_
wiring.py``): standard-library imports plus ``loop_detector``, no module-level mutable state,
no Scheduler / Executor / WorldState / Registry / Brain / Queue / Model, and **no way to end a
run**.  The last one is the operator's clause 「Loop Detector 只能阻止当前局部流程，不得停止整个
AUTO」: the strongest ending available here is ``INTENT_YIELD_GOAL``, which asks the run's own
``_yield_to_next_goal`` to hand *one Goal* back -- a surface ``runtime.py`` already uses for
half a dozen other reasons.  There is no ``finish``, no ``sys.exit`` and no ``AgentState``
reachable from this file.

Why the blast radius is known before arming it
----------------------------------------------
``tools/replay_loop_main_path.py`` runs this exact projection over the recorded ledger, one
detector per run (which is what the live path does).  One invocation, verbatim:

    window   : last 60 MB of learning/episodes.jsonl
    rows     : 4047                     runs: 335
    rungs    : semantic_retry 28  local_reobserve 25  widen_observe 21
               feature_reopen 9 (unavailable)  home_recovery 9        defer_goal 85
    intents  : same_step 53  widen 21  go_home 18  yield_goal 85
    Goals handed back : ['HERO_RECRUIT_ADVANCED'] in 8 run(s)
    HERO_RECRUIT_ADVANCED fires 130 times over 179 rows
    AVOID_STAMINA_WASTE -- the productive Goal -- fires 46 times and never reaches defer_goal

**Read those integers as a shape, not as a constant.**  The instrument reads a file production
is still appending to, and a byte window over a growing file is a *sliding* window: the same
command a minute later printed ``detections 176`` and then ``177`` for the same
``rows 4047``.  What does not move is the shape, and the shape is the argument:

    ~335 runs  ->  ~175 detections  ->  the 85 ``defer_goal`` detections collapse to
    **8** actual yields, because ``_yield_to_next_goal`` answers False once a Goal is already
    held back in that run, and **all 8 are HERO_RECRUIT_ADVANCED**.

So arming it costs at most 8 goal-yields in ~335 runs (2.4 %), every one of them on the Goal the
detector exists for, and the productive Goal only ever pays the cheap early rungs -- its rung
index is reset by the progress it makes.  A count of detections is not a count of acts; that
distinction is why the per-run pass, not the whole-window pass, answers "what would happen".
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from winter_agent_v2.loop_detector import (
    RECOVERY_LADDER,
    RUNG_DEFER_GOAL,
    RUNG_FEATURE_REOPEN,
    RUNG_HOME_RECOVERY,
    RUNG_LOCAL_REOBSERVE,
    RUNG_SEMANTIC_RETRY,
    RUNG_WIDEN_OBSERVE,
    LoopDetector,
    LoopSignature,
    relevant_state_hash,
)

# ----------------------------------------------------------------- what the run should do
#
# Strings rather than an enum, for the reason ``loop_detector`` gives for its metric names:
# these land in a JSON line a reader greps, and a string is what a grep finds.

#: Re-issue the same action.  On the main path this is the run's own default -- the brain
#: re-decides from the same state, and it takes exactly one observation per step -- so the rung
#: is *recorded* and nothing is forced.
#:
#: Deliberately not "override the decision with last step's": forcing a stale decision is a new
#: way for a run to issue a tap the brain would not have chosen, and the rung's own name asks
#: for a retry, which is what the loop already does.  The rung is not a silent no-op -- the
#: intent and the rung are both written to the run's trace -- because "a remedy that silently
#: did nothing is indistinguishable from no remedy at all".
#:
#: ``local_reobserve`` lands here too, and that is not a degradation: "look at the current page
#: again, cheaply, without widening" is precisely what the next iteration of this loop does, and
#: the next iteration is where the run is going anyway.  ``Watch.rung`` still records which of
#: the two the ladder asked for; ``intent`` records what the run did about it, and on this path
#: the honest answer for both is "the same step".
INTENT_SAME_STEP = "same_step"
#: Look again with every expensive sweep allowed.  This is the runtime's ``_observe(widen=True)``
#: at ``runtime.py``'s ``_observe`` (the ``elif widen:`` branch), whose own docstring already
#: names LOOP_DETECTOR_V1 as its caller.
INTENT_WIDEN = "widen"
#: Leave and re-approach from a known page.  The runtime's existing ``OPEN_HOME`` decision.
INTENT_GO_HOME = "go_home"
#: Hand this Goal back to the Scheduler and let AUTO continue elsewhere.  The run's existing
#: ``_yield_to_next_goal``.  This is the ladder's last rung and the strongest ending available
#: here -- it ends one Goal's turn, never the run.
INTENT_YIELD_GOAL = "yield_goal"

#: The ladder, projected onto what the main path can carry out.  A tuple rather than a dict
#: because this file keeps nothing mutable at module level, which is ``loop_detector``'s own
#: rule and is enforced by the same scan.
#:
#: Note what is *absent*: ``RUNG_FEATURE_REOPEN``.  Its remedy is the adapter's ``recover``, and
#: the main AUTO path has no adapter -- see ``UNAVAILABLE_ON_MAIN_PATH``.  It is declared
#: unavailable rather than mapped to something that resembles it, because a rung whose remedy
#: silently does nothing is the failure mode the ladder's own docstring forbids.
RUNG_INTENTS: tuple[tuple[str, str], ...] = (
    (RUNG_SEMANTIC_RETRY, INTENT_SAME_STEP),
    (RUNG_LOCAL_REOBSERVE, INTENT_SAME_STEP),
    (RUNG_WIDEN_OBSERVE, INTENT_WIDEN),
    (RUNG_HOME_RECOVERY, INTENT_GO_HOME),
    (RUNG_DEFER_GOAL, INTENT_YIELD_GOAL),
)

#: Rungs with no surface on this path.  ``resolve`` walks *past* these to the next rung the run
#: can actually carry out and reports which were passed over, so the trace says "the ladder had
#: one fewer step here" instead of quietly pretending it had six.
UNAVAILABLE_ON_MAIN_PATH: tuple[str, ...] = (RUNG_FEATURE_REOPEN,)

@dataclass(frozen=True)
class Watch:
    """A detection the run has not yet acted on, and what it should do about it."""

    goal_id: str = ""
    skill_id: str = ""
    semantic_target: str = ""
    intent: str = ""
    rung: str = ""
    pattern: str = ""
    reason: str = ""
    repeats: int = 0
    #: Rungs the projection had to step over to find one this path can carry out.
    skipped: tuple[str, ...] = ()

    def as_row(self) -> dict[str, Any]:
        return {
            "loop_rung": self.rung, "loop_pattern": self.pattern,
            "loop_intent": self.intent, "loop_skipped": list(self.skipped),
            "loop_repeats": self.repeats,
        }


#: An empty watch: "nothing pending, carry on normally".  Frozen, and a module-level constant
#: rather than a mutable container, so the discipline scan stays satisfied.
EMPTY_WATCH = Watch()


# ----------------------------------------------------------------- the projection

def _intent_of(rung: str) -> str:
    """The main path's remedy for one rung, or ``""`` when it has none."""
    for name, intent in RUNG_INTENTS:
        if name == rung:
            return intent
    return ""


def unmapped_rungs() -> tuple[str, ...]:
    """Ladder entries with neither a remedy nor a declaration of unavailability.

    Empty is the only healthy value, and it is asserted rather than assumed: a seventh rung
    added to ``RECOVERY_LADDER`` must be *noticed* here.  The alternative -- a ``.get(rung, ...)``
    default -- degrades into "issue the same step once more", which is the exact behaviour the
    ladder exists to stop.
    """
    return tuple(r for r in RECOVERY_LADDER
                 if not _intent_of(r) and r not in UNAVAILABLE_ON_MAIN_PATH)


def resolve(rung: str) -> tuple[str, tuple[str, ...]]:
    """``(intent, skipped)`` for a rung: what to do, and which rungs were stepped over.

    Raises ``KeyError`` for a name that is not in ``RECOVERY_LADDER`` at all, and walks forward
    from the named rung to the first one this path can carry out.  ``defer_goal`` is always
    available, so the walk cannot run off the end -- and if a future ladder made that false,
    this raises rather than returning "carry on".
    """
    order = list(RECOVERY_LADDER)
    if rung not in order:
        raise KeyError(f"{rung!r} is not a rung of RECOVERY_LADDER")
    skipped: list[str] = []
    for candidate in order[order.index(rung):]:
        intent = _intent_of(candidate)
        if intent:
            return intent, tuple(skipped)
        skipped.append(candidate)
    raise KeyError(f"no rung at or after {rung!r} can be carried out on the main path")


def _page_of(state: Any) -> str:
    """The page label, spelled exactly as ``session_engine._signature_for`` spells it.

    ``.value`` and not ``str(enum)``: ``Page`` is a ``(str, Enum)``, so ``str(Page.HOME)`` is
    ``"Page.HOME"`` while the ledger records ``"HOME"``.  The replay reads the ledger, so the
    two spellings must not diverge -- a page in ``move_key`` that matched offline and not
    online would make this instrument unusable for the one thing it exists for.

    Reads a mapping as well as an object, for the same reason ``loop_detector._read`` does: the
    replay hands the detector a state read back out of JSON, and the live run hands it a
    ``WorldState``.  One fact, two shapes.
    """
    if state is None:
        return ""
    page = state.get("page") if isinstance(state, Mapping) else getattr(state, "page", None)
    return str(getattr(page, "value", page) or "")


# ----------------------------------------------------------------- the watch

class LoopWatch:
    """One real ``LoopDetector`` for one run, plus the main path's projection.

    Never module-level and never shared: a shared detector would carry one run's ledger into
    the next, which is the same reason ``LoopDetector`` keeps every counter on the instance.
    """

    def __init__(self, *, detector: LoopDetector | None = None) -> None:
        self.detector = detector if detector is not None else LoopDetector()
        self._pending = EMPTY_WATCH
        #: Observations the detector refused, and why.  Counted, never swallowed silently:
        #: a detector that broke quietly would make a looping run look like a clean one.
        self.broken = 0
        self.warnings: list[str] = []
        #: Rungs this run's ladder had to step over, recorded once each.
        self.skipped: list[str] = []
        #: Detections this run acted on, by intent.  Run-level telemetry, not truth.
        self.acted: dict[str, int] = {}

    # ---------------------------------------------------------------- observation

    def observe_step(self, *, role_id: str = "", goal_id: str = "", skill_id: str = "",
                     semantic_target: str = "", after: Any = None, outcome: str = "",
                     progress: bool | None = None) -> Any:
        """Feed one completed step.  Returns the verdict, or ``None`` when it was refused.

        ``progress`` is the *Goal*-level fact the run already computed, and it is the whole
        reason this seam exists: passing the step's outcome here instead is what left 1216
        verifier-passing non-progressing main-path steps invisible to the detector.

        Exception-proof on purpose.  This sits on the hot path, and a diagnostic must never be
        able to stop gameplay -- ``action_latency.append`` makes the same promise for the same
        reason.  A refusal is counted and printed once rather than swallowed: a detector that
        broke silently is worse than one that never existed, because the run then looks like
        "nothing loops here" and nobody goes looking.
        """
        try:
            verdict = self.detector.observe(LoopSignature(
                role_id=str(role_id or ""),
                page=_page_of(after),
                goal_id=str(goal_id or ""),
                skill_id=str(skill_id or ""),
                semantic_target=str(semantic_target or ""),
                state_hash=relevant_state_hash(after),
                verifier_outcome=str(outcome or ""),
                progress=progress,
            ))
        except Exception as exc:  # noqa: BLE001 - see the docstring: gameplay outranks this
            self.broken += 1
            message = f"{type(exc).__name__}: {exc}"
            if message not in self.warnings:
                self.warnings.append(message)
                print(f"[loop] the detector refused a step ({message}); the run continues",
                      flush=True)
            return None

        if verdict.detected:
            intent, skipped = resolve(verdict.rung)
            for name in skipped:
                if name not in self.skipped:
                    self.skipped.append(name)
            self._pending = Watch(
                goal_id=str(goal_id or ""), skill_id=str(skill_id or ""),
                semantic_target=str(semantic_target or ""), intent=intent, rung=verdict.rung,
                pattern=verdict.pattern, reason=verdict.reason, repeats=verdict.repeats,
                skipped=skipped,
            )
        return verdict

    def note_progress(self, *, goal_id: str = "", skill_id: str = "",
                     semantic_target: str = "") -> None:
        """The run says the Goal moved in a way the step's own frame could not show.

        Forwarded rather than re-implemented: without it the rung index would only ever climb
        and an intermittently-stuck Goal would be deferred for having been stuck an hour ago.
        """
        self.detector.note_progress(goal_id=goal_id, skill_id=skill_id,
                                    semantic_target=semantic_target)

    # ---------------------------------------------------------------- consumption

    def take(self, *, goal_id: str = "") -> Watch:
        """The pending remedy for ``goal_id``, or an empty watch.

        Called once at the top of the next iteration, which is the earliest moment the run can
        act on a detection at all -- the detection is produced *after* a step has been issued
        and verified, and there is no honest way to un-issue it.

        The match is on the Goal, not on the whole action, and that is a deliberate weakness:
        at this point the run has not decided what it is about to do, so the only fact it has is
        which Goal it is still pursuing.  The cost of being generous is bounded and cheap -- at
        worst one widened look for a Goal that was genuinely looping a step ago -- while the
        cost of a stricter match would be a rung that never fires at all.
        """
        pending = self._pending
        self._pending = EMPTY_WATCH
        if not pending.intent:
            return pending
        if pending.goal_id and pending.goal_id != str(goal_id or ""):
            # The flow moved to another Goal: this claim is about an action nobody is issuing
            # any more.  Dropped, not carried out -- ``LoopDetector._settle`` drops a stale
            # claim for the same reason.
            return EMPTY_WATCH
        return pending

    def note_acted(self, intent: str) -> None:
        """Record that an intent was carried out.

        Counted by the run rather than by ``take``: taking an intent and *carrying it out* are
        two facts, and a rung that was handed over and then declined (the Goal already held
        back, ``OPEN_HOME`` not ready) must not be recorded as a recovery.
        """
        if intent:
            self.acted[intent] = int(self.acted.get(intent, 0)) + 1

    # ---------------------------------------------------------------- reporting

    def summary(self) -> dict[str, Any]:
        """The detector's ledger plus what this run's projection did with it."""
        return {
            **self.detector.summary(),
            "LOOP_WATCH_ACTED": dict(self.acted),
            "LOOP_WATCH_SKIPPED_RUNGS": list(self.skipped),
            "LOOP_WATCH_BROKEN": self.broken,
            "LOOP_WATCH_WARNINGS": list(self.warnings),
        }


__all__ = [
    "EMPTY_WATCH", "INTENT_GO_HOME", "INTENT_SAME_STEP", "INTENT_WIDEN",
    "INTENT_YIELD_GOAL", "LoopWatch", "RUNG_INTENTS", "UNAVAILABLE_ON_MAIN_PATH", "Watch",
    "resolve", "unmapped_rungs",
]
