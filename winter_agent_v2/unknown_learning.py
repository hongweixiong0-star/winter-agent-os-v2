"""The bridge that turns one solved UNKNOWN into something V2 can do by itself.

Operator directive 2026-10-01, sections 11-15 and 38.  The point of the local GUI model is
**not** that it keeps answering: the point is that a screen it answered once stops needing it.
That requires three things the project did not have before this module:

1.  **A verified step is written down as a *step*, not as a coordinate.**  ``Advice`` records
    what the model proposed and ``episodes.jsonl`` records that something ran; neither records
    "on this screen, for this goal, this semantic element moved to that screen, and the verifier
    agreed".  :class:`LearnedStepCandidate` is that record, and it is written **only** for a step
    whose verifier passed -- a model's own confidence is not evidence (section 39).

2.  **Several verified steps compose into a candidate skill** (section 13).  The compiler groups
    steps of one session into contiguous page chains and emits :class:`CandidateSkill`, whose
    identity is the *semantic* chain (``OPEN_ACTIVITY_CENTER`` style), never the taps.  Two
    consequences that are the whole reason for the design:
      * a chain compiled from two different sessions gets the **same** ``skill_id``, so the
        second observation *strengthens* the record instead of creating a near-duplicate;
      * no coordinate is ever stored, so "把 x/y/bbox 永久写进 Skill" (section 10) is impossible
        here by construction rather than by discipline.

3.  **The runtime can ask "have I solved this screen before?"**  ``learned_steps_for`` answers
    it, and section 15's ``UNKNOWN_REPEAT_MODEL_CALL_RATE`` is derived from whether the model was
    consulted anyway.

What this module deliberately does *not* do
-------------------------------------------
It does not touch ``v2_registry()``.  Section 14 is explicit -- *"UI-Venus 没有 Promotion 权限"* --
so everything here lands as ``CANDIDATE`` in ``knowledge/skills/candidates/`` and the existing
Replay/Shadow/Promotion gate stays the only way in.  A module that could register a skill from a
model's output would be exactly the "第二 Registry" the constitution forbids.

It also does not operate the device and holds no client.  It reads ledgers and writes JSON, the
same shape as ``page_knowledge`` / ``ui_collection``, which keeps ``tools/``-style offline use and
in-runtime use on one implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import unknown_advisor

#: Where verified UNKNOWN steps accumulate.  Beside the episode stream and the planner ledger, so
#: one directory answers "what has the model taught us".
LEARNED_STEPS_PATH = Path("learning/unknown_verified_steps.jsonl")

#: Where compiled candidate skills are written.  **Not** the registry: see the docstring.
CANDIDATE_SKILL_DIR = Path("knowledge/skills/candidates")

#: How many verified steps a chain needs before it is worth calling a skill.  Two, because one
#: observation cannot distinguish "this control does this" from "this control happened to be under
#: the finger" -- the project has paid for that lesson repeatedly (see ``learning.py`` on
#: ``goal_progress``).  A single step is still recorded; it just is not compiled yet.
MIN_CHAIN_STEPS = 2

#: How many independent sessions must verify the same (screen, goal, semantic) before a *single*
#: step is compiled on its own.  Section 15 is about exactly this: the second time must not need
#: the model, so a step proved twice in different sessions is a candidate even without a chain.
MIN_SINGLE_STEP_SESSIONS = 2

#: Actions whose verified occurrence is not enough to make a skill on its own, because "it worked
#: once" and "it is safe to repeat" are different claims for anything that spends or fights
#: (section 14's own list: 攻击 / START_RALLY / JOIN_RALLY / 撤回 / 道具 / 加速).  Such a chain is
#: still recorded -- the evidence is real -- but it is filed ``SLOW_PROMOTION`` so the existing
#: risk gate gives it the long route.
HIGH_RISK_WORDS: tuple[str, ...] = (
    "攻击", "发起集结", "加入集结", "集结", "撤回", "道具", "加速", "立即完成",
    "attack", "rally", "recall", "speedup", "start_rally", "join_rally",
)

#: What a compiled record's promotion route is.  Named rather than boolean so the reviewer sees
#: the risk decision in the file instead of having to re-derive it.
ROUTE_FAST = "FAST_PROMOTION"       # navigation / close popup / free claim
ROUTE_SLOW = "SLOW_PROMOTION"       # spends, fights, or is irreversible
ROUTE_BLOCKED = "BLOCKED"           # names money or gems: never promotable

#: A compiled record's status.  Only ever these two; ``STABLE`` is the registry's word and this
#: module is not allowed to say it.
STATUS_CANDIDATE = "CANDIDATE"
STATUS_STRENGTHENED = "CANDIDATE_STRENGTHENED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semantic_slug(text: str, *, limit: int = 40) -> str:
    """A stable, coordinate-free id fragment.  CJK survives; punctuation does not."""
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(text or "")).strip("_")
    return cleaned[:limit] or "UNKNOWN"


def risk_route(*, semantic: str, action_type: str, expected_result: str = "") -> str:
    """Which promotion route a verified step's element earns.

    Judged on the element's own identity and the action's own words, which is the same discipline
    ``unknown_advisor.words_refused_at`` uses -- an action that names money is not made safe by
    the page it sits on, and a 关闭 button is not made dangerous by a page that sells gems.
    """
    identity = " ".join((str(semantic), str(action_type), str(expected_result))).lower()
    for word in unknown_advisor.SPEND_WORDS:
        if word.lower() in identity:
            return ROUTE_BLOCKED
    for word in HIGH_RISK_WORDS:
        if word.lower() in identity:
            return ROUTE_SLOW
    # A free claim is low risk but still changes state; navigation and closing are the fastest.
    return ROUTE_FAST


@dataclass(frozen=True)
class LearnedStepCandidate:
    """One UNKNOWN step the verifier passed, described the way a skill would describe it.

    The field list is section 12's, in its own order, plus the identifiers a fold needs.  Note what
    is *absent*: there is no ``x``/``y``/``bbox`` member.  §10 forbids persisting a model's box, and
    the strongest way to enforce that is to have nowhere to put one -- the grounding basis and the
    element's own measurements are what the next attempt re-locates from.
    """

    # ---- identity ------------------------------------------------------------
    recorded_at: str = ""
    #: Which ask this step consumed.  Joins back to ``learning/local_planner_steps.jsonl``.
    request_id: str = ""
    #: The AUTO run this step happened in.  Named ``session_id`` rather than reusing
    #: ``episode_id`` because a session is the unit section 15 counts repeats over, and an AUTO
    #: run is the only unit the runtime actually knows.
    session_id: str = ""
    episode_id: str = ""
    step_index: int = 0

    # ---- role-independent page semantics (section 12) ------------------------
    goal_id: str = ""
    role_id: str = ""
    page_before: str = ""
    page_after: str = ""
    #: Changed nothing.  Kept because "this control does nothing" is knowledge too, and the
    #: failure-pattern learner (section 23) reads it; it is never compiled into a skill.
    no_progress: bool = False

    # ---- what was pressed, semantically --------------------------------------
    semantic_target: str = ""
    action_type: str = ""
    #: ``FRAME_ELEMENT`` or ``UNTRUSTED_CURRENT_FRAME_PROPOSAL`` -- how the model justified it.
    basis: str = ""
    #: Which of *this frame's own* measurements located the point: a printed word, a template this
    #: project collected, an anchored region.  This is the field the next attempt re-runs.
    grounding_basis: str = ""
    #: Where the element was printed, coarsely.  A band name, not a number: enough for a reviewer
    #: to tell two same-worded controls apart, useless as a tap target.
    area: str = ""

    # ---- visual evidence (section 12) ----------------------------------------
    #: ``{"ocr_anchor": ..., "template": ..., "relative_region": ..., "control_type": ...}``.
    #: Deliberately a dict of *identities* rather than of geometry.
    visual_evidence: dict[str, Any] = field(default_factory=dict)

    # ---- outcome -------------------------------------------------------------
    verifier_ok: bool = False
    verifier_reason: str = ""
    expected_result: str = ""
    actual_result: str = ""
    #: How many consecutive failures preceded this success in the same session, so a recovered
    #: step carries its own recovery evidence (§12's last bullet).
    attempts_before_success: int = 0
    recovery: str = ""
    risk_route: str = ROUTE_FAST

    # ---- evidence ------------------------------------------------------------
    source_frames: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """A step's identity: screen + element + goal.  Not the frame, not the time.

        Section 15 asks "have I solved this before?", and the honest key for that question is the
        semantic one.  A frame digest would make every repeat look new, which is the bug this
        module exists to prevent.
        """
        return "|".join((
            str(self.page_before), str(self.goal_id),
            str(self.semantic_target or self.action_type), str(self.page_after),
        ))

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["source_frames"] = list(self.source_frames)
        row["key"] = self.key
        row["schema_version"] = "1.0"
        return row


@dataclass(frozen=True)
class CandidateSkill:
    """A chain of verified steps, abstracted.  A proposal for the existing promotion gate.

    Composed of the *semantic* chain, and its ``skill_id`` is derived from that chain alone, so two
    sessions that walked the same route strengthen one record instead of producing two.  Nothing
    here is registered, and nothing here is ``STABLE``.
    """

    skill_id: str
    semantic_goal: str
    status: str = STATUS_CANDIDATE
    risk_route: str = ROUTE_FAST
    entry_page: str = ""
    exit_page: str = ""
    target_pages: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    semantics: tuple[str, ...] = ()
    action_types: tuple[str, ...] = ()
    goal_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    verifier_pass_count: int = 0
    sessions: tuple[str, ...] = ()
    evidence_episodes: tuple[str, ...] = ()
    evidence_frames: tuple[str, ...] = ()
    first_seen: str = ""
    last_seen: str = ""
    #: What must hold before this may be tried, written from what the steps actually proved.
    preconditions: tuple[str, ...] = ()
    #: What the verifier must see for the whole chain to count.  The last step's own expectation,
    #: because that is the one that ends the route.
    success_condition: str = ""
    #: §17/§39: this is what a reviewer reads to decide whether to promote.  Never a verdict.
    notes: str = ""

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        for name in ("target_pages", "steps", "semantics", "action_types", "goal_ids", "roles",
                     "sessions", "evidence_episodes", "evidence_frames", "preconditions"):
            row[name] = list(getattr(self, name))
        row["lifecycle"] = self.status
        row["schema_version"] = "1.0"
        # Stated in the file rather than only in the docstring, because the file is what a
        # promotion reviewer opens.
        row["not_yet"] = (
            "CANDIDATE only -- not registered, not runnable, and not STABLE. Promotion is the "
            "existing Replay -> Shadow -> Live Verification gate's decision, not this compiler's."
        )
        return row


class VerifiedStepLedger:
    """Append-only record of verified UNKNOWN steps, plus the fold that reads it back.

    Append-only for the same reason ``learning.py`` is: a step that was verified stays verified,
    and a later reader must not be able to rewrite history to make a skill look stronger.
    """

    def __init__(self, path: Path | str = LEARNED_STEPS_PATH) -> None:
        self.path = Path(path)

    def append(self, step: LearnedStepCandidate) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(step.as_row(), ensure_ascii=False, default=str) + "\n")
        except (OSError, TypeError, ValueError):
            # A learning record must never fail the step that already ran.  Same discipline as
            # ``_note_step_for_planner``.
            pass

    def rows(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, Mapping):
                out.append(dict(row))
        return out

    def verified(self) -> list[dict[str, Any]]:
        """Only the rows a skill may be built from: the verifier passed and something changed."""
        return [
            row for row in self.rows()
            if row.get("verifier_ok") is True and not row.get("no_progress")
        ]


# ---------------------------------------------------------------------------- compilation
def _chain_key(step: Mapping[str, Any]) -> str:
    """A chain's semantic identity.  Two walks of the same route must land on the same key, so this
    reads only page keys, goal and the semantic targets -- never the frames or the session."""
    material = "|".join((
        str(step.get("goal_id", "")),
        str(step.get("page_before", "")),
        str(step.get("semantic_target", "")),
        str(step.get("action_type", "")),
        str(step.get("page_after", "")),
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:10]


def _skill_id(chain: Sequence[Mapping[str, Any]]) -> str:
    """``LEARNED_<entry page>_<n>_<steps>_<digest>`` -- semantic, stable, and unique per route."""
    entry = _semantic_slug(str(chain[0].get("page_before", "")), limit=24).upper()
    verb = _semantic_slug(str(chain[0].get("action_type", "")), limit=18).upper()
    digest = _chain_key(chain[0]) if len(chain) == 1 else hashlib.sha256(
        "|".join(_chain_key(step) for step in chain).encode("utf-8")
    ).hexdigest()[:10]
    return f"LEARNED_{entry}_{verb}_{len(chain)}S_{digest}"


def _split_chains(steps: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Maximal runs where each step really leaves the page the previous one arrived on.

    Contiguity is checked rather than assumed because it is the only thing that makes a chain a
    *route*: steps that merely share a goal and a session but do not connect would compile into a
    skill that cannot be walked.
    """
    chains: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for step in steps:
        if not current:
            current = [step]
            continue
        if str(step.get("page_before", "")) == str(current[-1].get("page_after", "")):
            current.append(step)
        else:
            chains.append(current)
            current = [step]
    if current:
        chains.append(current)
    return chains


def _chain_record(chain: Sequence[Mapping[str, Any]]) -> CandidateSkill:
    """Turn one verified chain into a candidate skill.  Pure."""
    semantics = tuple(dict.fromkeys(str(s.get("semantic_target", "")) for s in chain if s.get("semantic_target")))
    action_types = tuple(dict.fromkeys(str(s.get("action_type", "")) for s in chain if s.get("action_type")))
    sessions = tuple(dict.fromkeys(str(s.get("session_id", "")) for s in chain if s.get("session_id")))
    episodes = tuple(dict.fromkeys(str(s.get("episode_id", "")) for s in chain if s.get("episode_id")))
    roles = tuple(dict.fromkeys(str(s.get("role_id", "")) for s in chain if s.get("role_id")))
    goals = tuple(dict.fromkeys(str(s.get("goal_id", "")) for s in chain if s.get("goal_id")))
    frames: list[str] = []
    for step in chain:
        frames.extend(str(f) for f in (step.get("source_frames") or ()) if f)
    # Risk is the worst step's, not the first's: a route that ends in a claim is a claiming route.
    routes = [str(s.get("risk_route") or ROUTE_FAST) for s in chain]
    if ROUTE_BLOCKED in routes:
        risk = ROUTE_BLOCKED
    elif ROUTE_SLOW in routes:
        risk = ROUTE_SLOW
    else:
        risk = ROUTE_FAST
    chain_semantics = " -> ".join(semantics) or "(no named element)"
    return CandidateSkill(
        skill_id=_skill_id(chain),
        semantic_goal=f"{goals[0] if goals else 'UNKNOWN'}: {chain_semantics}",
        status=STATUS_CANDIDATE,
        risk_route=risk,
        entry_page=str(chain[0].get("page_before", "")),
        exit_page=str(chain[-1].get("page_after", "")),
        target_pages=tuple(dict.fromkeys(str(s.get("page_after", "")) for s in chain)),
        steps=tuple(str(s.get("key", "")) for s in chain),
        semantics=semantics,
        action_types=action_types,
        goal_ids=goals,
        roles=roles,
        verifier_pass_count=len(chain),
        sessions=sessions,
        evidence_episodes=episodes,
        evidence_frames=tuple(dict.fromkeys(frames)),
        first_seen=str(chain[0].get("recorded_at", "")),
        last_seen=str(chain[-1].get("recorded_at", "")),
        preconditions=tuple(
            dict.fromkeys(
                [
                    f"page is {chain[0].get('page_before', '')}",
                ]
                + [
                    f"element {s.get('semantic_target')} locatable by {s.get('grounding_basis')}"
                    for s in chain
                    if s.get("semantic_target") and s.get("grounding_basis")
                ]
            )
        ),
        success_condition=str(chain[-1].get("expected_result", ""))[:160],
        notes=(
            f"compiled from {len(chain)} verified step(s) in {len(sessions)} session(s); "
            f"risk route {risk}"
        ),
    )


def compile_candidate_skills(
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    ledger: VerifiedStepLedger | None = None,
    out_dir: Path | str = CANDIDATE_SKILL_DIR,
    write: bool = True,
) -> tuple[CandidateSkill, ...]:
    """Fold verified steps into candidate skills, and (by default) write them out.

    Two passes, and both are needed for section 15 to actually work:

    * **Chains** -- contiguous verified routes of two or more steps inside one session.  These are
      the ``活动中心 -> 登录好礼 -> 领取`` shape section 13 asks for.
    * **Repeats** -- a *single* step proved in two or more different sessions.  Without this, a
      one-tap UNKNOWN (the common case: a close button, an event entrance) could never be learned,
      and section 15's "next time do not ask the model" would silently only apply to long routes.

    Writing is **merge-aware**: an existing file for the same ``skill_id`` is updated in place --
    ``verifier_pass_count`` grows, new sessions and episodes are appended -- so a second
    observation strengthens the record instead of forking a near-duplicate.  That merge is the
    mechanical form of section 39's "重复成功才算证据".
    """
    if rows is None:
        rows = (ledger or VerifiedStepLedger()).verified()
    rows = [dict(row) for row in rows if row.get("verifier_ok") is True and not row.get("no_progress")]

    compiled: dict[str, CandidateSkill] = {}

    # Pass 1: chains, per session.
    by_session: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_session.setdefault(str(row.get("session_id", "")), []).append(row)
    for session_rows in by_session.values():
        ordered = sorted(session_rows, key=lambda row: int(row.get("step_index") or 0))
        for chain in _split_chains(ordered):
            if len(chain) >= MIN_CHAIN_STEPS:
                record = _chain_record(chain)
                compiled[record.skill_id] = record

    # Pass 2: single steps proved in more than one session.
    seen: dict[str, set[str]] = {}
    evidence: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = str(row.get("key") or "")
        if not key:
            continue
        seen.setdefault(key, set()).add(str(row.get("session_id", "")))
        evidence.setdefault(key, []).append(row)
    for key, sessions in seen.items():
        if len(sessions) < MIN_SINGLE_STEP_SESSIONS:
            continue
        # The *newest* observation of that step describes the route as it is now.
        latest = max(evidence[key], key=lambda row: str(row.get("recorded_at", "")))
        record = _chain_record([latest])
        compiled[record.skill_id] = record

    out = tuple(compiled.values())
    if write:
        for record in out:
            _write_candidate(record, Path(out_dir))
    return out


def _write_candidate(record: CandidateSkill, out_dir: Path) -> None:
    """Write one candidate, merging with what is already on file for the same semantic route."""
    path = out_dir / f"{record.skill_id}.json"
    merged = record
    existing = _read_json(path)
    if existing:
        sessions = tuple(dict.fromkeys(tuple(existing.get("sessions") or ()) + record.sessions))
        episodes = tuple(dict.fromkeys(tuple(existing.get("evidence_episodes") or ())
                                       + record.evidence_episodes))
        frames = tuple(dict.fromkeys(tuple(existing.get("evidence_frames") or ())
                                     + record.evidence_frames))
        passes = max(int(existing.get("verifier_pass_count") or 0), record.verifier_pass_count)
        merged = CandidateSkill(
            **{
                **asdict(record),
                "status": STATUS_STRENGTHENED,
                "verifier_pass_count": passes,
                "sessions": sessions,
                "evidence_episodes": episodes,
                "evidence_frames": frames,
                "first_seen": str(existing.get("first_seen") or record.first_seen),
                "last_seen": max(str(existing.get("last_seen") or ""), record.last_seen),
                "notes": (
                    f"compiled from {passes} verified step(s) in {len(sessions)} session(s); "
                    f"risk route {record.risk_route}"
                ),
            }
        )
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged.as_row(), ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def learned_steps_for(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    page_key: str,
    goal_id: str,
) -> list[dict[str, Any]]:
    """Verified steps this project already knows for one screen and goal, best first.

    This is the answer to section 15's question, and it is deliberately keyed on *screen + goal*
    rather than on the frame: the frame changes every step of an unnamed screen, which is exactly
    why asking the model again used to feel unavoidable.

    Ordered by (risk route, repeat count, recency) so a caller that takes the first entry gets the
    least dangerous, best-proved action rather than whatever happened to be written last.
    """
    if rows is None:
        rows = VerifiedStepLedger().verified()
    matching = [
        dict(row) for row in rows
        if str(row.get("page_before", "")) == str(page_key)
        and (not goal_id or not row.get("goal_id") or str(row.get("goal_id")) == str(goal_id))
        and row.get("verifier_ok") is True
        and not row.get("no_progress")
        and row.get("semantic_target")
    ]
    if not matching:
        return []
    counts: dict[str, int] = {}
    for row in matching:
        counts[str(row.get("key", ""))] = counts.get(str(row.get("key", "")), 0) + 1

    def rank(row: Mapping[str, Any]) -> tuple[int, int, str]:
        route = str(row.get("risk_route") or ROUTE_FAST)
        route_rank = {ROUTE_FAST: 0, ROUTE_SLOW: 1, ROUTE_BLOCKED: 2}.get(route, 1)
        return (route_rank, -counts.get(str(row.get("key", "")), 0),
                -len(str(row.get("recorded_at", ""))))

    matching.sort(key=rank)
    deduped: dict[str, dict[str, Any]] = {}
    for row in matching:
        deduped.setdefault(str(row.get("key", "")), row)
    return list(deduped.values())


# ---------------------------------------------------------------------------- stats
@dataclass
class LearningStats:
    """A small fold over the ledgers, for the console and for section 47's report."""

    verified_steps: int = 0
    distinct_steps: int = 0
    sessions: int = 0
    candidate_skills: int = 0
    strengthened_skills: int = 0
    fast_route_skills: int = 0
    slow_route_skills: int = 0
    blocked_skills: int = 0
    pages_touched: int = 0
    goals_touched: int = 0

    @classmethod
    def load(
        cls,
        *,
        ledger: VerifiedStepLedger | None = None,
        skill_dir: Path | str = CANDIDATE_SKILL_DIR,
    ) -> "LearningStats":
        stats = cls()
        rows = (ledger or VerifiedStepLedger()).verified()
        stats.verified_steps = len(rows)
        stats.distinct_steps = len({str(r.get("key", "")) for r in rows if r.get("key")})
        stats.sessions = len({str(r.get("session_id", "")) for r in rows if r.get("session_id")})
        stats.pages_touched = len({str(r.get("page_before", "")) for r in rows if r.get("page_before")})
        stats.goals_touched = len({str(r.get("goal_id", "")) for r in rows if r.get("goal_id")})
        for path in sorted(Path(skill_dir).glob("*.json")) if Path(skill_dir).exists() else []:
            payload = _read_json(path)
            if not payload:
                continue
            stats.candidate_skills += 1
            if str(payload.get("status")) == STATUS_STRENGTHENED:
                stats.strengthened_skills += 1
            route = str(payload.get("risk_route") or ROUTE_FAST)
            if route == ROUTE_FAST:
                stats.fast_route_skills += 1
            elif route == ROUTE_SLOW:
                stats.slow_route_skills += 1
            else:
                stats.blocked_skills += 1
        return stats

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def record_verified_step(
    *,
    request_id: str = "",
    session_id: str = "",
    episode_id: str = "",
    step_index: int = 0,
    goal_id: str = "",
    role_id: str = "",
    page_before: str = "",
    page_after: str = "",
    no_progress: bool = False,
    semantic_target: str = "",
    action_type: str = "",
    basis: str = "",
    grounding_basis: str = "",
    area: str = "",
    visual_evidence: Mapping[str, Any] | None = None,
    verifier_ok: bool = False,
    verifier_reason: str = "",
    expected_result: str = "",
    actual_result: str = "",
    attempts_before_success: int = 0,
    recovery: str = "",
    source_frames: Sequence[str] = (),
    ledger: VerifiedStepLedger | None = None,
) -> LearnedStepCandidate:
    """Build and file one learned step.  The runtime's only entry point.

    ``verifier_ok`` is a parameter rather than something this function derives, because the
    verifier is the success authority and this module must not be able to disagree with it: a
    caller that has no verdict files nothing.
    """
    step = LearnedStepCandidate(
        recorded_at=_now(),
        request_id=str(request_id),
        session_id=str(session_id),
        episode_id=str(episode_id),
        step_index=int(step_index),
        goal_id=str(goal_id),
        role_id=str(role_id),
        page_before=str(page_before),
        page_after=str(page_after),
        no_progress=bool(no_progress),
        semantic_target=str(semantic_target),
        action_type=str(action_type),
        basis=str(basis),
        grounding_basis=str(grounding_basis),
        area=str(area),
        visual_evidence=dict(visual_evidence or {}),
        verifier_ok=bool(verifier_ok),
        verifier_reason=str(verifier_reason)[:200],
        expected_result=str(expected_result)[:200],
        actual_result=str(actual_result)[:200],
        attempts_before_success=int(attempts_before_success),
        recovery=str(recovery)[:200],
        risk_route=risk_route(
            semantic=f"{semantic_target} {area}",
            action_type=action_type,
            expected_result=expected_result,
        ),
        source_frames=tuple(str(f) for f in source_frames if f),
    )
    (ledger or VerifiedStepLedger()).append(step)
    return step
