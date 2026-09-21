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
CHANGE_KINDS: tuple[str, ...] = (
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


def control_key(page: str, control: str) -> str:
    """The ledger's key: the page plus the control, never a coordinate.

    Runs both halves through :func:`label`, so a caller may pass the ``Page`` enum or
    the semantic's own string and get the same key either way.
    """
    return f"{label(page) or '?'}|{label(control) or UNNAMED}"


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
    #: Set when the control was refused by policy rather than tried.  Kept apart
    #: from ``last_result`` so "we decided not to" never reads as "it did nothing".
    refused_reason: str = ""

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
        experience = ControlExperience.from_json(body)
        if not measured_on_a_real_frame(experience):
            continue
        out[str(key)] = experience
    return out


def save(
    experiences: Mapping[str, ControlExperience],
    path: Path | str | None = None,
    *,
    limit: int = 4000,
) -> None:
    """Write the ledger.  Never raises -- an experience note must not fail a run.

    Records measured on a scratch frame are not written.  ``STATE_PATH`` is a module
    constant, so a test or a throwaway probe that does not redirect it writes the real
    ledger -- which is how six controls ended up filed at one coordinate and the file
    became untrustworthy as evidence.  The filter here is what makes that impossible
    rather than merely discouraged, and it costs a real run nothing: every frame a real
    run measures comes from its capture directory.

    The ledger is sorted by recency **before** filtering, so the ``limit`` still counts
    records that will be kept instead of being spent on ones that will be dropped.
    """
    source = Path(path) if path is not None else STATE_PATH
    kept = [
        (key, experience) for key, experience in experiences.items()
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
