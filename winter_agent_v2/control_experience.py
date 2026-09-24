"""Per-control action experience -- what each visible control actually did.

Why this exists (operator §四 / §五 / §六).  Until now the project recorded
*skill-level* outcomes (``Episode`` rows in ``learning/episodes.jsonl``) and
*domain-level* readings (``observation_store``), and nothing keyed by the UI
control itself.  So "we tapped this control on this page, the page said this, and
what actually happened was that" had nowhere to live.  The consequence was
measurable: an unregistered control could never accumulate knowledge, which made
"未注册 ⇒ 永远不许碰" self-fulfilling rather than a safety property.

Same shape as ``observation_store``: **a state file plus pure helpers**, not a
scheduler, not a registry, not a second brain.  Nothing here chooses an action.
It answers questions the brain and the goal engine ask:

    §四  what is on this page, what did each control do last time
    §五  what has been tried, what is still a hypothesis
    §六  what changed after the tap
    §八  has this control's result stopped being worth repeating

Keyed by ``(page, control)`` where ``control`` is the *semantic* name the frame
carries.  The normalized position is stored **with the frame it was read from**,
so a coordinate is always traceable to a picture and is never reusable as if it
were semantic -- the project rule that coordinates must be self-justifying
(``00_MASTER_RULES.md`` §5).  A control whose semantic is unknown is recorded
under its page plus whatever the frame could name it by, and is marked
``UNNAMED`` rather than given an invented identity.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "learning/control_experience.json"

#: Operator §六, verbatim, as machine values.  ``NO_OP`` and ``UNKNOWN`` are
#: deliberately distinct: "the tap was issued and nothing moved" is a real
#: finding about the control, while "we could not tell" is a finding about the
#: *reading* and must never be collapsed into the first.
#: ``QUICK_PANEL_OPENED`` is here because a control can now be *proved* to have opened an overlay:
#: the 快捷面板's handle, whose whole effect is that the panel's own reading flips from absent to
#: present.  Without it the name the verifier reports would be recorded as ``UNKNOWN`` by
#: ``record_outcome`` -- measured: that is exactly what happened on the first real step, and it made
#: the L1 registration that step earned unusable (``l1_reusable`` refuses an UNKNOWN last result).
#: A vocabulary that cannot hold a fact the project can measure is the wrong vocabulary.
CHANGE_KINDS: tuple[str, ...] = (
    "QUICK_PANEL_OPENED",
    "PAGE_CHANGED",
    "POPUP_OPENED",
    "POPUP_CLOSED",
    "NUMBER_CHANGED",
    "PROGRESS_CHANGED",
    "RESOURCE_SPENT",
    "TIMER_CHANGED",
    "QUEUE_CHANGED",
    "NO_OP",
    "UNKNOWN",
)

#: Risks an ordinary exploratory tap may carry.  Everything with a real,
#: possibly-irreversible price is outside this set by construction, so "was this
#: control allowed to be tried" stays a property of the risk table rather than a
#: judgement made at the call site.
EXPLORABLE_RISKS: frozenset[str] = frozenset({
    "LOW", "T1", "T2",
    "LOW_RESOURCE_SPEND", "MEDIUM_RESOURCE_SPEND", "MEDIUM_STAMINA_SPEND",
})

#: Never explorable, whatever the page: the project's permanent block
#: (``00_MASTER_RULES.md`` §8) plus the irreversible account operations.
FORBIDDEN_RISKS: frozenset[str] = frozenset({
    "REAL_MONEY", "REAL_MONEY_PURCHASE", "ACCOUNT_SECURITY", "ACCOUNT_DELETE",
    "IRREVERSIBLE", "T4",
})

UNNAMED = "UNNAMED"

#: A control whose effect **one real step** has established, with the conditions it holds under
#: (operator directive 2026-09-22 §七/§八).  Deliberately a level and not a status: a single-step
#: success is not a finished skill and not a stable template, and those two keep their own states
#: in their own stores (§十).
LEVEL_L1 = "L1"

#: The keys a registration's ``conditions`` carries.  Spelled out so a reader never has to guess
#: which fields "the same conditions" means.
CONDITION_PAGE = "page"
CONDITION_GOAL = "goal"
CONDITION_STATE = "state"


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def label(value: Any) -> str:
    """The readable name of a state field, whether it is an enum or already a string.

    ``asdict(WorldState)`` keeps ``Page.HOME`` as the *enum*, so ``str()`` on it
    produces ``"Page.HOME"``.  Every key and every comparison in this module goes
    through here, so a ledger key written by one code path is the same key read by
    another -- measured the hard way: the first version keyed on ``str()`` and filed
    the alliance page under ``"Page.ALLIANCE"`` while every reader looked for
    ``"ALLIANCE"``.
    """
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def screen_is_narrower_than_its_page(screen: str) -> bool:
    """Does this screen's signature name anything beyond the page?

    ``state_signature`` is ``page|popup|...``, so ``"HOME"`` answers no and
    ``"POPUP|POWER_OVERVIEW"`` answers yes.  The question matters because it decides whether the
    *page* is a sufficient name for the screen, and the ledger stores coordinates: a coordinate is
    a claim about one screen, and ``POPUP`` is not one -- the client draws 22 different overlays
    under it.
    """
    return len([part for part in str(screen or "").split("|") if part]) > 1


def control_key(page: str, control: str, screen: str = "") -> str:
    """The ledger's key: the screen plus the control, never a coordinate.

    ``screen`` is a :func:`state_signature`, and it is used in place of the bare page whenever it
    names something beyond the page -- ``POPUP|POWER_OVERVIEW|BTN_CLOSE`` rather than
    ``POPUP|BTN_CLOSE``.  The page alone was the key until 2026-09-23 and it cost a live defect:
    the close-X of the 退出确认 dialog was learned at ``(0.8819, 0.3563)``, filed under
    ``POPUP|BTN_CLOSE``, and handed to all 22 popups -- on 加成总览 (``POWER_OVERVIEW``) that point
    is the middle of the panel's own number column, so eight consecutive runs tapped it, observed
    nothing, and died (issue #109).

    Callers that pass no ``screen`` keep the old key exactly, which is deliberate: every entry
    whose page fully describes its screen -- 49 of the 57 with a stored position -- keeps working
    unchanged, and only the entries on screens the page cannot name move.

    Runs the parts through :func:`label`, so a caller may pass the ``Page`` enum or the semantic's
    own string and get the same key either way.
    """
    where = label(screen) if screen_is_narrower_than_its_page(screen) else (label(page) or "?")
    return f"{where}|{label(control) or UNNAMED}"


def measured_on_a_real_frame(experience: "ControlExperience") -> bool:
    """Was this record measured on a frame from this project, or on a test's scratch frame?

    Measured 2026-09-22, and it is the reason the ledger could not be trusted as evidence:
    eleven of the thirty-five records had a ``read_from_frame`` under the system temp
    directory, and their positions gave the game away -- ``HOME|PAGE_MAP``,
    ``MAP|BTN_OPEN_HOME``, ``EXPLORATION|BTN_HERO_CAMP_FIGHT``, ``POPUP|BTN_CLAIM_FREE_STAMINA``,
    ``ALLIANCE|BTN_CLOSE`` and ``ALLIANCE|BTN_ALLY_GIFT_CLAIM`` were all filed at exactly
    ``(0.8403, 0.5)``, which is six different controls at one point.  A test harness stubs
    ``target_resolver`` with a constant; ``STATE_PATH`` is a module constant; nothing stopped
    the harness from writing the real ledger, so test coordinates were filed as production
    measurements.

    A ledger entry is only evidence if the frame it was read from is a frame this project
    captured.  The test is deliberately narrow -- "is it under the system temp directory" --
    because that is exactly the condition a test or a throwaway probe satisfies and a real
    capture directory does not, whichever directory the operator points ``--capture-dir`` at.
    """
    recorded = str(getattr(experience, "read_from_frame", "") or "").strip()
    if not recorded:
        return False
    try:
        scratch = Path(tempfile.gettempdir()).resolve()
    except (OSError, RuntimeError):
        return True
    try:
        candidate = Path(recorded).resolve()
    except (OSError, RuntimeError):
        return False
    return scratch not in candidate.parents and candidate != scratch


def explorable_risk(risk: str | None) -> bool:
    """May an ordinary exploratory tap carry this risk?

    A risk that is neither in ``EXPLORABLE_RISKS`` nor in ``FORBIDDEN_RISKS`` is
    refused: an unknown price is not a low price, and the operator's §九 keeps the
    paid and the irreversible out of trial-and-error on purpose.
    """
    text = str(risk or "").strip().upper()
    if not text or text in FORBIDDEN_RISKS:
        return False
    return text in EXPLORABLE_RISKS


def classify_change(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> str:
    """Name what changed between two ``WorldState`` observations (operator §六).

    Reads the states the runtime already produces rather than comparing pixels:
    the eight kinds the operator listed are all *semantic* facts, and deriving
    them from the pixel diff would make them a second, worse vision layer.  The
    frames are still recorded, for traceability, but they are not what decides.

    Returns one of :data:`CHANGE_KINDS`.  ``UNKNOWN`` means one of the two states
    was not observable at all -- which is a statement about the reading, and is
    deliberately not the same answer as ``NO_OP``.
    """
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return "UNKNOWN"
    if not before or not after:
        return "UNKNOWN"

    def page_of(state: Mapping[str, Any]) -> str:
        return label(state.get("page"))

    def popup_of(state: Mapping[str, Any]) -> str:
        return label(state.get("popup"))

    page_before, page_after = page_of(before), page_of(after)
    popup_before, popup_after = popup_of(before), popup_of(after)

    if page_before and page_after and page_before != page_after:
        return "PAGE_CHANGED"
    if popup_after and not popup_before:
        return "POPUP_OPENED"
    if popup_before and not popup_after:
        return "POPUP_CLOSED"

    for key in ("resource_bank", "resources", "stamina"):
        old, new = before.get(key), after.get(key)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            for name, value in new.items():
                was = old.get(name)
                if isinstance(value, (int, float)) and isinstance(was, (int, float)):
                    if value < was:
                        return "RESOURCE_SPENT"
                    if value > was:
                        return "NUMBER_CHANGED"

    old_marches, new_marches = before.get("marches"), after.get("marches")
    if old_marches != new_marches and (old_marches is not None or new_marches is not None):
        return "QUEUE_CHANGED"

    old_queues, new_queues = before.get("queues"), after.get("queues")
    if isinstance(old_queues, Mapping) and isinstance(new_queues, Mapping):
        if set(old_queues) != set(new_queues):
            return "QUEUE_CHANGED"
        for name, body in new_queues.items():
            was = old_queues.get(name)
            if not isinstance(body, Mapping) or not isinstance(was, Mapping):
                continue
            # A queue whose own countdown moved is the timer case; anything else
            # that differs inside it is a queue-state change, which is a different
            # fact and must not be reported as a timer.
            if body.get("remaining") != was.get("remaining"):
                return "TIMER_CHANGED"
        if old_queues != new_queues:
            return "QUEUE_CHANGED"

    for key in ("goals", "goal_state", "progress", "events", "daily"):
        if before.get(key) != after.get(key) and (before.get(key) is not None
                                                  or after.get(key) is not None):
            return "PROGRESS_CHANGED"

    if before == after:
        return "NO_OP"
    return "NUMBER_CHANGED"


@dataclass
class ControlExperience:
    """One control's accumulated experience on one page (operator §四).

    Every field is optional in the sense that "not known yet" is representable:
    ``known_result`` empty and ``hypotheses`` non-empty is the normal state of a
    control that has been seen but not understood, and it is the state the
    exploration budget exists to shorten.
    """

    page: str
    control: str
    # -- §四 identity -------------------------------------------------------
    label: str = ""                      # the control's own words, when OCR read them
    visual: str = ""                     # the semantic/template that located it
    position_norm: tuple[float, float] | None = None
    #: The :func:`state_signature` of the frame ``position_norm`` was **measured on**, which is a
    #: stricter claim than ``page`` and exists because the page is not always a screen: the client
    #: draws 22 distinct overlays under ``POPUP``, and a point measured on one of them is not a
    #: point on the others.  Written in the same expression as the position, so the two cannot
    #: drift apart, and checked on reuse -- an entry that records no screen may only be reused on
    #: a frame whose own signature is no narrower, i.e. one where the page really is the screen.
    screen: str = ""
    read_from_frame: str = ""            # the frame the position was read from
    entry_path: tuple[str, ...] = ()     # how this page was reached, in order
    # -- §四 meaning --------------------------------------------------------
    possible_actions: tuple[str, ...] = ()
    clickable: bool | None = None
    known_result: str = ""               # the action's *name*, e.g. OPEN_ALLIANCE
    known_change: str = ""               # the observed CHANGE_KIND that established it
    hypotheses: tuple[str, ...] = ()     # expected but unverified outcomes
    # -- §六/§四 ledger ------------------------------------------------------
    attempts: int = 0
    last_result: str = ""                # CHANGE_KIND of the most recent attempt
    last_at: str = ""
    risk: str = ""
    cost_seen: dict[str, Any] = field(default_factory=dict)
    cooldown_seconds: int | None = None
    goal_help: dict[str, str] = field(default_factory=dict)
    #: True when the control has no wording of its own but its registration names a reader that can
    #: find it again on a later frame (``basis`` is a locator's name).
    #:
    #: Added for the 快捷面板 handle -- the one control in this project that is drawn with no text at
    #: all.  Before it, "no wording" meant "cannot be re-confirmed", which was true while every
    #: element was identified by what was printed on it and stopped being true once a locator could
    #: re-measure the same control from the frame in front of it.  A registration that sets this is
    #: reusable *because* the caller re-runs that reader: the confirmation happens there, on the
    #: current picture, exactly as a wording search does for a printed control.
    relocatable: bool = False

    #: Set when the control was refused by policy rather than tried.  Kept apart
    #: from ``last_result`` so "we decided not to" never reads as "it did nothing".
    refused_reason: str = ""
    # -- operator 2026-09-22: the L1 single-step action ----------------------
    #: :data:`LEVEL_L1` once one real step proved what this control does *here*.  A level and not
    #: a status on purpose: a single-step success is neither a finished skill nor a stable
    #: template, and those two keep their own states in their own stores.
    level: str = ""
    #: The page, goal and state signature the success is conditional on (keyed by
    #: :data:`CONDITION_PAGE` / :data:`CONDITION_GOAL` / :data:`CONDITION_STATE`).
    conditions: dict[str, str] = field(default_factory=dict)
    #: What the element looked like on the frame that proved it -- its own wording, its box
    #: normalized to that frame, and the frame itself.  This is what lets a later frame answer
    #: "is this still the same control" without trusting a stored coordinate.
    visual_features: dict[str, Any] = field(default_factory=dict)
    #: How the region was located: an OCR box, the client's printed instruction, the ledger, an
    #: on-demand analysis, or a template -- so an inferred position never reads as a measured one.
    basis: str = ""
    #: The action that was issued, as the executor described it (kind + target).
    action: dict[str, Any] = field(default_factory=dict)
    #: The expected result and the effect that actually followed, side by side and never merged.
    expected_effect: str = ""
    observed_effect: str = ""

    # -- reading ------------------------------------------------------------

    @property
    def resolved(self) -> bool:
        """Has this control's outcome stopped being a hypothesis?"""
        return bool(self.known_result) and self.last_result not in ("", "UNKNOWN")

    @property
    def sterile(self) -> bool:
        """A control whose every attempt was a no-op is not worth repeating (§八).

        Deliberately not "any failure": one ``NO_OP`` can be a mistimed tap.  Only
        a run of them, with no change ever observed, retires the control -- and
        even then it is retired for *automatic* repetition, not deleted, so a
        later page change can revive it.
        """
        return self.attempts >= 3 and self.last_result == "NO_OP" and not self.known_result

    def cooldown_remaining(self, now: datetime | None = None) -> int:
        if not self.cooldown_seconds or not self.last_at:
            return 0
        started = _moment(self.last_at)
        if started is None:
            return 0
        moment = now or datetime.now(timezone.utc)
        left = (started + timedelta(seconds=int(self.cooldown_seconds))) - moment
        return max(0, int(left.total_seconds()))

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": self.page,
            "control": self.control,
            "label": self.label,
            "visual": self.visual,
            "position_norm": list(self.position_norm) if self.position_norm else None,
            "screen": self.screen,
            "read_from_frame": self.read_from_frame,
            "entry_path": list(self.entry_path),
            "possible_actions": list(self.possible_actions),
            "clickable": self.clickable,
            "known_result": self.known_result,
            "known_change": self.known_change,
            "hypotheses": list(self.hypotheses),
            "attempts": self.attempts,
            "last_result": self.last_result,
            "last_at": self.last_at,
            "risk": self.risk,
            "cost_seen": dict(self.cost_seen),
            "cooldown_seconds": self.cooldown_seconds,
            "goal_help": dict(self.goal_help),
            "refused_reason": self.refused_reason,
            "relocatable": self.relocatable,
            "level": self.level,
            "conditions": dict(self.conditions),
            "visual_features": dict(self.visual_features),
            "basis": self.basis,
            "action": dict(self.action),
            "expected_effect": self.expected_effect,
            "observed_effect": self.observed_effect,
        }
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "ControlExperience":
        position = payload.get("position_norm")
        return cls(
            page=str(payload.get("page") or ""),
            control=str(payload.get("control") or UNNAMED),
            label=str(payload.get("label") or ""),
            visual=str(payload.get("visual") or ""),
            position_norm=(float(position[0]), float(position[1]))
            if isinstance(position, (list, tuple)) and len(position) == 2 else None,
            screen=str(payload.get("screen") or ""),
            read_from_frame=str(payload.get("read_from_frame") or ""),
            entry_path=tuple(str(x) for x in (payload.get("entry_path") or ())),
            possible_actions=tuple(str(x) for x in (payload.get("possible_actions") or ())),
            clickable=payload.get("clickable") if isinstance(payload.get("clickable"), bool) else None,
            known_result=str(payload.get("known_result") or ""),
            known_change=str(payload.get("known_change") or ""),
            hypotheses=tuple(str(x) for x in (payload.get("hypotheses") or ())),
            attempts=int(payload.get("attempts") or 0),
            last_result=str(payload.get("last_result") or ""),
            last_at=str(payload.get("last_at") or ""),
            risk=str(payload.get("risk") or ""),
            cost_seen=dict(payload.get("cost_seen") or {}),
            cooldown_seconds=_int_or_none(payload.get("cooldown_seconds")),
            goal_help={str(k): str(v) for k, v in (payload.get("goal_help") or {}).items()},
            refused_reason=str(payload.get("refused_reason") or ""),
            relocatable=bool(payload.get("relocatable", False)),
            level=str(payload.get("level") or ""),
            conditions={str(k): str(v) for k, v in (payload.get("conditions") or {}).items()},
            visual_features=dict(payload.get("visual_features") or {}),
            basis=str(payload.get("basis") or ""),
            action=dict(payload.get("action") or {}),
            expected_effect=str(payload.get("expected_effect") or ""),
            observed_effect=str(payload.get("observed_effect") or ""),
        )


# ------------------------------------------------------------------ store


def load(path: Path | str | None = None) -> dict[str, ControlExperience]:
    """Every recorded control.  Never raises; an unreadable file is an empty store.

    Empty is the safe direction here: it makes every control unexplored, so the
    cost of a lost file is re-exploration, never a control silently believed to be
    understood.

    Records measured on a scratch frame are dropped on the way in, not only refused on
    the way out -- a file that has already been polluted has to clean itself, because
    the alternative is that the next reader re-imports the same six controls filed at one
    coordinate.  See :func:`measured_on_a_real_frame`.
    """
    source = Path(path) if path is not None else STATE_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    records = payload.get("controls") if isinstance(payload, Mapping) else None
    if not isinstance(records, Mapping):
        return {}
    out: dict[str, ControlExperience] = {}
    for key, body in records.items():
        if not isinstance(body, Mapping):
            continue
        # A record this build cannot read is skipped, never raised: the ledger is read on the
        # runtime path, and a schema this build does not know is a reason to re-explore one
        # control, not a reason to stop a cycle.  (Measured the hard way: a field added to
        # ``as_json`` without the matching dataclass field made ``from_json`` raise ``TypeError``
        # straight through ``load``.)
        try:
            experience = ControlExperience.from_json(body)
        except (TypeError, ValueError):
            continue
        if not measured_on_a_real_frame(experience):
            continue
        out[str(key)] = experience
    return out


def _merge(
    on_disk: Mapping[str, ControlExperience],
    in_memory: Mapping[str, ControlExperience],
) -> dict[str, ControlExperience]:
    """Union of two copies of the ledger, per key, losing neither side's history.

    Measured 2026-09-22: this file went from 52 records to 4 while a test suite was running.  The
    store is a plain full-file rewrite and more than one process holds a copy of it (the control
    panel's cycles, a test run, a probe), so the last writer won and everything the others had
    learned was gone -- including an L1 registration a real step had just proved.

    Entries are never deleted by design (a control is retired by its own recorded outcomes, never
    by being forgotten), so a union is the correct join: the copy with more real attempts for a key
    wins, and the more recent one breaks the tie.  A run therefore cannot roll back what another
    run learned, whatever order they finish in.
    """
    merged: dict[str, ControlExperience] = dict(on_disk)
    for key, record in in_memory.items():
        current = merged.get(key)
        if current is None:
            merged[key] = record
            continue
        if (record.attempts, record.last_at) >= (current.attempts, current.last_at):
            merged[key] = record
    return merged


def save(
    experiences: Mapping[str, ControlExperience],
    path: Path | str | None = None,
    *,
    limit: int = 4000,
) -> None:
    """Write the ledger, **merged with what is already on disk**.  Never raises.

    Records measured on a scratch frame are not written.  ``STATE_PATH`` is a module
    constant, so a test or a throwaway probe that does not redirect it writes the real
    ledger -- which is how six controls ended up filed at one coordinate and the file
    became untrustworthy as evidence.  The filter here is what makes that impossible
    rather than merely discouraged, and it costs a real run nothing: every frame a real
    run measures comes from its capture directory.

    The read-modify-write is a union (:func:`_merge`) rather than a replace, for the reason
    recorded there: this is the project's only experience ledger, several processes can hold a
    copy, and a run that finishes later must not be able to delete what another proved.

    The ledger is sorted by recency **before** filtering, so the ``limit`` still counts
    records that will be kept instead of being spent on ones that will be dropped.
    """
    source = Path(path) if path is not None else STATE_PATH
    combined = _merge(load(source), experiences)
    kept = [
        (key, experience) for key, experience in combined.items()
        if measured_on_a_real_frame(experience)
    ]
    rows = sorted(kept, key=lambda item: str(item[1].last_at), reverse=True)[:limit]
    payload = {
        "schema_version": "1.0",
        "written_at": datetime.now(timezone.utc).isoformat(),
        "change_kinds": list(CHANGE_KINDS),
        "controls": {key: experience.as_json() for key, experience in rows},
    }
    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        temp = source.with_suffix(source.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(source)
    except OSError:
        pass


# ------------------------------------------------------------- reading out


def record_outcome(
    experience: ControlExperience,
    *,
    change: str,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    result_name: str = "",
    clicked: bool = True,
    now: datetime | None = None,
    frame: str = "",
) -> ControlExperience:
    """Apply §六 to one control: did it work, what did it cost, what is it worth.

    ``change`` is the :func:`classify_change` answer.  A change that is not
    ``NO_OP`` and not ``UNKNOWN`` is taken as evidence for the control's outcome
    -- that is the operator's §六 relaxation of "every action needs its own final
    verifier": for an ordinary interaction, *a new observation sufficient to
    decide the next step* is the bar.  Anything with a real price is checked
    against the spend deltas instead, and is never inferred from the control
    having moved.

    ``clicked=False`` records the reading without counting an attempt, which is
    what makes the attempt count mean "times we actually tapped this" rather than
    "times we looked at it".
    """
    moment = now or datetime.now(timezone.utc)
    kind = change if change in CHANGE_KINDS else "UNKNOWN"
    if clicked:
        experience.attempts += 1
    experience.last_result = kind
    experience.last_at = moment.isoformat()
    if frame:
        experience.read_from_frame = frame

    if kind not in ("NO_OP", "UNKNOWN"):
        if result_name:
            experience.known_result = result_name
        elif not experience.known_result:
            experience.known_result = kind
        experience.known_change = kind
        # The outcome is no longer a hypothesis; drop the ones it settled.
        experience.hypotheses = ()

    spent: dict[str, Any] = {}
    for key in ("resource_bank", "resources", "stamina"):
        old, new = (before or {}).get(key), (after or {}).get(key)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            for name, value in new.items():
                was = old.get(name)
                if isinstance(value, (int, float)) and isinstance(was, (int, float)) and value < was:
                    spent[str(name)] = {"amount": was - value, "before": was, "after": value}
    if spent:
        experience.cost_seen = spent

    return experience


# --------------------------------------------------- L1 single-step actions


def state_signature(state: Mapping[str, Any] | None) -> str:
    """The part of a frame's state that changes what its controls *do* (§十一).

    Deliberately narrow, and the narrowness is the design: the page, the popup, and the two
    sub-states this project's own frames keep switching *inside* one page -- which barracks the
    training page is open on, which section the alliance page is showing.  Wider would make "the
    same state" never recur (a countdown or a resource counter moves every step); narrower would
    reuse a control across screens whose controls mean different things.
    """
    if not isinstance(state, Mapping):
        return ""
    parts = [label(state.get("page")), label(state.get("popup"))]
    for holder, field_name in (("training", "camp_open_label"), ("alliance", "section")):
        body = state.get(holder)
        if isinstance(body, Mapping):
            value = body.get(field_name)
            if value:
                parts.append(f"{holder}.{field_name}={label(value)}")
    return "|".join(part for part in parts if part)


def reusable_on_this_screen(experience: "ControlExperience", screen: str) -> bool:
    """May the coordinate in ``experience`` be handed to a frame with this ``screen``?

    The stored point is a claim about the screen it was measured on, so the two have to agree.  The
    comparison has to accept **both** spellings of "the page is the screen" -- an entry written
    before this field existed records ``""``, and the writer records the signature, which for such a
    page is the page's own name -- or every stored position would be refused the moment the field
    started being written:

    * the same string: the same screen, and the everyday case;
    * this frame is **no narrower** than its page (``"HOME"``): the key already pinned that page, so
      an entry that recorded nothing, or recorded that same page-only form, was measured under
      exactly this condition.  An entry that recorded a *distinguished* screen was not, and is
      refused;
    * this frame names more than its page (``"POPUP|POWER_OVERVIEW"``): only an entry that recorded
      that same signature is allowed.  Nothing recorded is refused, and that is the honest
      direction -- it is a point measured on a screen nothing wrote down, and the alternative is
      what issue #109 is: a coordinate measured on the 退出确认 dialog spent on 加成总览.  For the
      same reason an entry measured on *some* popup is refused on a frame that reads ``POPUP``
      without naming which one: that frame cannot claim to be the screen the point belongs to.
    """
    recorded = str(experience.screen or "")
    now = str(screen or "")
    if recorded == now:
        return True
    if screen_is_narrower_than_its_page(now):
        return False
    return not recorded or not screen_is_narrower_than_its_page(recorded)


def visual_features(
    *,
    text: str,
    box_norm: Mapping[str, Any] | None,
    read_from_frame: str = "",
) -> dict[str, Any]:
    """Describe an element the way a later frame can be compared against it (§八).

    The wording it carried, the box it occupied **normalized to that frame**, and the frame
    itself.  No absolute pixel coordinate: a registration is a claim about a control, and the
    claim has to be re-established on whatever frame the next visit produces (§九).
    """
    features: dict[str, Any] = {}
    if text:
        features["text"] = str(text)
    if isinstance(box_norm, Mapping):
        box = {
            str(key): round(float(value), 4)
            for key, value in box_norm.items()
            if isinstance(value, (int, float))
        }
        if box:
            features["box_norm"] = box
    if read_from_frame:
        features["read_from_frame"] = str(read_from_frame)
    return features


def register_l1(
    experience: ControlExperience,
    *,
    goal: str,
    state: str,
    features: Mapping[str, Any],
    basis: str = "",
    action: Mapping[str, Any] | None = None,
    expected_effect: str = "",
    observed_effect: str = "",
    relocatable: bool = False,
    now: datetime | None = None,
) -> ControlExperience:
    """Record one single-step success as an L1 action (§七/§八).

    Called when -- and only when -- a real step's own verifier passed on a control that had no
    registered skill behind it.  Every field §八 names is stored: the page, goal and state the
    success is conditional on, the element's visual features, how its region was located, the
    action that was issued, and the effect that was observed.  The absolute coordinate is not the
    record; the box travels inside ``visual_features`` **with the frame it was measured on**, and
    reuse re-derives the point from the current frame.

    A later success under different conditions adds those conditions rather than replacing them,
    which is how one control can end up with two separate L1 registrations (§七 "不同页面、不同状态
    下的结果分别记录").
    """
    moment = now or datetime.now(timezone.utc)
    experience.level = LEVEL_L1
    experience.conditions = {
        CONDITION_PAGE: str(experience.page or ""),
        CONDITION_GOAL: str(goal or ""),
        CONDITION_STATE: str(state or ""),
    }
    features = dict(features or {})
    if features:
        features["recorded_at"] = moment.isoformat()
        experience.visual_features = features
    if basis:
        experience.basis = str(basis)
    if action:
        experience.action = {str(k): v for k, v in dict(action).items()}
    experience.expected_effect = str(expected_effect or "")
    experience.observed_effect = str(observed_effect or "")
    # How this control can be found again.  A printed control is found by its wording; this flag says
    # this one is found by its reader, which is what makes a textless registration reusable at all.
    experience.relocatable = bool(relocatable or experience.relocatable)
    if goal and observed_effect:
        experience.goal_help[str(goal)] = str(observed_effect)
    return experience


def l1_reusable(experience: ControlExperience, *, now: datetime | None = None) -> bool:
    """Is this L1 registration still worth reusing? (§九/§十一)

    A registration stops applying -- without being deleted -- when its most recent attempt on the
    live game did nothing or could not be read, when a policy refusal is on record, or while a
    cooldown runs.  That is §九's "结果不符时记录失败并调整候选，不得在同一状态下无限重复失败点击"
    answered from the record instead of from a run-scoped set.
    """
    if experience.level != LEVEL_L1:
        return False
    if not experience.visual_features.get("text") and not experience.relocatable:
        # Nothing to re-confirm it against on a later frame.  A registration that cannot be
        # checked is not reusable; it stays on the record as history.  A ``relocatable`` one *can*
        # be checked -- by re-running the reader its ``basis`` names, which is what the caller does
        # before it taps -- so it is not refused on the grounds of having no wording.
        return False
    if experience.refused_reason or experience.sterile:
        return False
    if experience.last_result in ("", "NO_OP", "UNKNOWN"):
        return False
    # L1 is a verified step, not a remembered tap. Older or partial records can have a
    # successful-looking change without retaining what the step expected, what actually
    # followed, or which semantic target the executor pressed. Such a record remains useful
    # history, but it cannot authorize replay under §19.3–19.4.
    if not str(experience.expected_effect or "").strip():
        return False
    if not str(experience.observed_effect or "").strip():
        return False
    if str(experience.action.get("target") or "").strip() != str(experience.control or "").strip():
        return False
    return experience.cooldown_remaining(now) == 0


def l1_for(
    experiences: Mapping[str, ControlExperience],
    *,
    page: str,
    goal: str,
    state: str,
    present_words: Iterable[str] = (),
    now: datetime | None = None,
) -> ControlExperience | None:
    """The registered single-step action to reuse on this frame, or ``None`` (§十一).

    Four clauses, each a directive rule rather than a heuristic:

    * **the same page** -- a control's meaning is page-local (§九: 同一个图标在不同页面可以具有不同
      语义, so a match may never cross pages);
    * **the same goal** -- unless the registration was made without one, which is a wildcard;
    * **the same state** -- the conditions the success was recorded as conditional on;
    * **the element must still be on this frame** -- its recorded wording has to be among the
      words this frame's OCR read.  A screen that no longer draws it is exactly §十一's
      "当前画面不匹配时重新识别", and refusing here is what sends the caller back to
      identification instead of tapping where something used to be.

    Strongest evidence first: a registration whose wording is on the frame, then the one with the
    most real attempts behind it.
    """
    wanted_page = label(page)
    wanted_goal = str(goal or "")
    words = {str(word).strip() for word in present_words if str(word or "").strip()}
    matches: list[ControlExperience] = []
    for experience in experiences.values():
        if label(experience.page) != wanted_page:
            continue
        conditions = experience.conditions or {}
        if str(conditions.get(CONDITION_GOAL) or "") not in ("", wanted_goal):
            continue
        if str(conditions.get(CONDITION_STATE) or "") != str(state or ""):
            continue
        text = str(experience.visual_features.get("text") or "").strip()
        if text:
            if text not in words:
                continue
        elif not experience.relocatable:
            # An element with neither wording nor a reader to find it again is not something reuse
            # may act on.
            continue
        if not l1_reusable(experience, now=now):
            continue
        matches.append(experience)
    if not matches:
        return None
    matches.sort(key=lambda item: (-item.attempts, item.control))
    return matches[0]


def candidates(
    experiences: Mapping[str, ControlExperience],
    page: str,
    *,
    now: datetime | None = None,
    limit: int = 8,
) -> tuple[ControlExperience, ...]:
    """Controls on ``page`` worth one bounded, ordinary exploratory try (§五/§十).

    Ordered by "least understood first, then least tried", so exploration is
    breadth-first over the page rather than a loop on one stubborn control.  A
    control is excluded when it has no located position, when its only outcome was
    a refusal by policy, when a cooldown is still running, or when it has proved
    sterile (§八: explored does not mean repeat forever).
    """
    moment = now or datetime.now(timezone.utc)
    ranked: list[tuple[int, int, str, ControlExperience]] = []
    for key, experience in experiences.items():
        if experience.page != page:
            continue
        if experience.position_norm is None:
            continue
        if experience.refused_reason:
            continue
        if experience.cooldown_remaining(moment) > 0:
            continue
        if experience.sterile:
            continue
        understood = 1 if experience.resolved else 0
        ranked.append((understood, experience.attempts, key, experience))
    ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    return tuple(row[3] for row in ranked[:limit])


def known_outcomes(
    experiences: Mapping[str, ControlExperience],
    page: str,
    *,
    goal_id: str = "",
) -> tuple[ControlExperience, ...]:
    """Controls on ``page`` whose outcome is already known -- what to reuse (§八).

    ``goal_id`` narrows to the controls already recorded as helping that goal, so
    "known" answers "known to help *this* task" and not merely "known".
    """
    out: list[ControlExperience] = []
    for experience in experiences.values():
        if experience.page != page or not experience.resolved:
            continue
        if goal_id and goal_id not in experience.goal_help:
            continue
        out.append(experience)
    out.sort(key=lambda item: (-item.attempts, item.control))
    return tuple(out)


def join(keys: Iterable[str]) -> str:
    """Stable rendering of a ledger key set, for logs and tests."""
    return ", ".join(sorted(str(key) for key in keys))
