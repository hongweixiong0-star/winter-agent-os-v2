"""When a known skill stops working, ask the model what the screen looks like now.

Operator directive 2026-10-01, sections 16-17.  The temptation on a failing skill is to throw it
away and let the model handle the screen again.  The directive forbids that: a skill that has been
right for months is being told the *page moved*, not that it was wrong, and the difference is not
something a rule can see.  So the flow is

    known skill -> deterministic retry -> semantic retry -> reobserve -> still failing
        -> SKILL_REPAIR_ANALYSIS -> UI-Venus -> RepairCandidate
        -> current-frame grounding -> MAA -> Verifier -> candidate patch -> Replay/Shadow -> promote

and two properties of that flow are the whole point:

* **the last deterministic step comes first.**  :func:`should_escalate` refuses until the skill has
  really failed ``REPAIR_TRIGGER_FAILURES`` times in a row *and* the failures are of a kind that a
  layout change explains.  A skill failing because the march queue is full has nothing to learn
  from a screenshot, and asking would burn a model call per step.
* **the answer is a candidate patch, never a production change.**  Section 17: *"不能直接覆盖
  Stable Skill"*.  Everything this module writes lands under ``knowledge/skills/repairs/`` with
  ``status = CANDIDATE_PATCH``; the registry is never opened, and the existing Replay/Shadow gate
  remains the only route to a live skill.

Unlike ``unknown_learning``, the *judgement* here is a closed vocabulary, because it is the field
a reviewer reads to decide what to do: "the target is still there but the layout moved" (re-locate
it) and "this is not the right page at all" (the skill's precondition, not its locator) lead to
different repairs, and a free-text answer would make them indistinguishable after the fact.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Where a repair question waits for an answer.  Same shape as ``learning/unknown_requests``: the
#: file *is* the question, so nothing here can block a run.
REQUEST_DIR = Path("learning/skill_repair_requests")
ANSWERS_DIR = "answers"

#: Where a proposed patch is kept, and what it is called there.  Deliberately outside
#: ``knowledge/skills/``'s own tree so a patch cannot be mistaken for a skill definition by any
#: existing loader.
CANDIDATE_PATCH_DIR = Path("knowledge/skills/repairs")

#: How many consecutive verifier failures on one skill before repair analysis is warranted.
#: Three, because one failure is a flake and two can be a transient overlay -- and because a lower
#: number turns every passing queue-full into a model call, which is the "每张图都问模型" the
#: directive's section 22 exists to prevent.
REPAIR_TRIGGER_FAILURES = 3

#: How long a filed repair question suppresses a second question about the same skill and screen.
#: One hour, the same bound the UNKNOWN channel uses: the frame is re-photographed every step of a
#: failing route, so without this a broken skill would file a question per step and the pile would
#: be unreadable long before anyone answered the first one.
REPAIR_REQUEST_COOLDOWN_SECONDS = 3600

#: Failure kinds that a screenshot can actually explain.  A ``QUEUE_FULL`` or a
#: ``WAITING_FOR_NATURAL_STATE`` is a game-state answer, not a perception answer; escalating those
#: would ask the model a question about the world that it cannot see.
REPAIRABLE_FAILURES: tuple[str, ...] = (
    "SEMANTIC_TARGET_NOT_FOUND",
    "SEMANTIC_TARGET_NOT_VERIFIED",
    "TARGET_NOT_FOUND",
    "PAGE_NOT_OPEN",
    "MARCH_PAGE_NOT_OPEN",
    "UNKNOWN_PAGE",
    "NOT_PROGRESSED",
    "VERIFY_FAILED",
    "NO_EXECUTION",
)

#: What the model is allowed to conclude (section 16's own list, as one vocabulary).  A closed set
#: so a reviewer can count them, and so "the page moved" can never be silently recorded as "the
#: skill is wrong".
JUDGEMENTS: tuple[str, ...] = (
    "TARGET_STILL_PRESENT_LAYOUT_CHANGED",
    "TARGET_TEXT_CHANGED",
    "TARGET_ICON_CHANGED",
    "ENTRY_MOVED",
    "SKILL_OUTDATED",
    "NOT_THIS_PAGE",
    "UNKNOWN",
)

#: The judgements that say the skill's own route is wrong, not its locator.  Recorded separately
#: because the repair is a precondition change, which the promotion gate treats differently from a
#: re-located control.
ROUTE_JUDGEMENTS = ("SKILL_OUTDATED", "NOT_THIS_PAGE")

#: The reply contract, enforced by the same server-side schema mechanism ``ui_planner`` uses.
JUDGEMENT_MAX_CHARS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repair_schema() -> dict[str, Any]:
    """The repair reply contract, as JSON Schema.

    ``additionalProperties: False`` and the enum matter more here than in the planner's contract:
    this answer names the *repair*, so an invented judgement is an invented repair action, and the
    grammar is what stops one existing.
    """
    return {
        "type": "object",
        "properties": {
            "judgement": {"type": "string", "enum": list(JUDGEMENTS)},
            "new_semantic_target": {"type": "string", "maxLength": JUDGEMENT_MAX_CHARS},
            "candidate_bbox_norm": {
                "type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
            },
            "expected_result": {"type": "string", "maxLength": JUDGEMENT_MAX_CHARS},
            "reason": {"type": "string", "maxLength": 120},
        },
        "required": ["judgement", "reason"],
        "additionalProperties": False,
    }


REPAIR_SYSTEM_PROMPT = """You are the repair analyst of a screenshot-driven game automation agent.

A skill that used to work has now failed several times in a row. You are shown the CURRENT
screenshot and the record of what that skill expects. Decide which of these is true:

- TARGET_STILL_PRESENT_LAYOUT_CHANGED: the control the skill wants is on this screen, but drawn
  somewhere else than it used to be.
- TARGET_TEXT_CHANGED: the control is there but its printed words are different now.
- TARGET_ICON_CHANGED: the control is there as an icon and its artwork changed.
- ENTRY_MOVED: the screen this skill expects to be reached from has moved it elsewhere.
- SKILL_OUTDATED: the route itself no longer exists -- the function was removed or reworked.
- NOT_THIS_PAGE: this is not the screen this skill is for; the skill's precondition is wrong, not
  its locator.
- UNKNOWN: you cannot tell from this picture.

Hard rules:
1. Look at the picture. Do not guess from the skill's name.
2. If you can name the control's new location in words, put them in "new_semantic_target" -- the
   element's own printed words, or the words nearest to it. Never output pixel coordinates; a
   region, if you give one at all, is "candidate_bbox_norm": [x, y, width, height] with each
   number between 0 and 1 as a fraction of the image. It is only a proposal and will be checked
   against the live screen.
3. Answer with JSON only, exactly this shape:
   {"judgement": str, "new_semantic_target": str, "candidate_bbox_norm": [x, y, w, h],
    "expected_result": str, "reason": str}
   The server enforces this shape and the length caps, so an extra key is refused rather than
   ignored.
4. "reason" is one short sentence, in the language of the client's own text.
"""


# ---------------------------------------------------------------------------- trigger
@dataclass(frozen=True)
class RepairTrigger:
    """Why a skill is being escalated, derived from real episodes only.

    Every field is a fact about failures that actually happened.  Nothing here is inferred from a
    skill's own declaration, which is the discipline section 43 asks for: *"不得人为破坏生产代码
    制造假成功"* -- a trigger has to come from the episode stream or it is not a trigger.
    """

    skill_id: str
    consecutive_failures: int
    failure_kinds: tuple[str, ...]
    page_key: str = ""
    goal_id: str = ""
    first_failure_at: str = ""
    last_failure_at: str = ""
    #: Frames from the failing attempts, newest last.  Used as evidence, and never as the tap
    #: source -- the repair's own point is still produced from the *current* frame.
    failure_frames: tuple[str, ...] = ()

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["failure_kinds"] = list(self.failure_kinds)
        row["failure_frames"] = list(self.failure_frames)
        return row


def should_escalate(
    skill_id: str,
    recent: Sequence[Mapping[str, Any]],
    *,
    page_key: str = "",
    threshold: int = REPAIR_TRIGGER_FAILURES,
) -> RepairTrigger | None:
    """The trigger for one skill, or ``None`` when repair analysis is not warranted.

    ``recent`` is the tail of the episode stream for this skill, oldest first.  The function reads
    it the way the runtime does -- the *last* run of consecutive failures is what matters, because
    a skill that failed five times last month and has since passed twenty times is not broken.
    """
    tail: list[Mapping[str, Any]] = []
    for row in reversed(list(recent)):
        if row.get("verifier_ok") is True or str(row.get("result")) == "SUCCESS":
            break
        tail.append(row)
    tail.reverse()
    if len(tail) < threshold:
        return None
    kinds = tuple(dict.fromkeys(
        str(row.get("failure_type") or row.get("reason") or "") for row in tail
        if row.get("failure_type") or row.get("reason")
    ))
    if not kinds:
        return None
    if not any(kind.split(":")[0].strip() in REPAIRABLE_FAILURES for kind in kinds):
        # Nothing here is a perception failure, so a screenshot cannot help: the honest answer is
        # to leave the skill alone and let the recovery paths that own game-state failures work.
        return None
    frames = [str(row.get("after_screenshot") or row.get("before_screenshot") or "")
              for row in tail]
    return RepairTrigger(
        skill_id=str(skill_id),
        consecutive_failures=len(tail),
        failure_kinds=kinds,
        page_key=str(page_key or (tail[-1].get("before_page") or "")),
        goal_id=str(tail[-1].get("goal_id") or ""),
        first_failure_at=str(tail[0].get("recorded_at") or ""),
        last_failure_at=str(tail[-1].get("recorded_at") or ""),
        failure_frames=tuple(frame for frame in frames if frame),
    )


# ---------------------------------------------------------------------------- the question
@dataclass
class RepairRequest:
    """Section 16's input list, as one file: what the skill wanted, and what it met instead."""

    request_id: str
    skill_id: str
    page_key: str = ""
    goal_id: str = ""
    frame_path: str = ""
    frame_digest: str = ""
    #: The skill's own semantics: what it aims at, and the words it expects to find.
    old_semantic: str = ""
    old_target_text: str = ""
    #: The pages this skill's steps used to reach, so a reviewer can see a route change rather
    #: than just a moved control.
    old_success_pages: tuple[str, ...] = ()
    #: The verifier's own words for what a pass looks like.
    verifier_expectation: str = ""
    failure_kinds: tuple[str, ...] = ()
    consecutive_failures: int = 0
    failure_frames: tuple[str, ...] = ()
    role_id: str = ""
    created_at: str = ""
    question: str = ""

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        for name in ("old_success_pages", "failure_kinds", "failure_frames"):
            row[name] = list(getattr(self, name))
        return row


def request_id(skill_id: str, page_key: str = "") -> str:
    """A question's identity: the skill and the screen.  Same screen + same skill = one question."""
    stem = re.sub(r"[^a-z0-9]+", "_", str(skill_id).lower()).strip("_")[:40] or "skill"
    screen = re.sub(r"[^a-z0-9]+", "_", str(page_key).lower()).strip("_")[:24]
    return f"repair__{stem}__{screen or 'any'}"


def render_prompt(request: RepairRequest) -> str:
    """The user turn.  JSON, for the same reason ``ui_planner.render_packet`` is: the reply is JSON
    and a table invites prose that the schema would then truncate."""
    payload = {
        "skill": request.skill_id,
        "goal": request.goal_id,
        "screen_the_skill_is_on": request.page_key,
        "the_skill_aims_at": request.old_semantic,
        "it_expects_to_find": request.old_target_text,
        "pages_it_used_to_reach": list(request.old_success_pages),
        "its_verifier_requires": request.verifier_expectation,
        "how_it_has_been_failing": list(request.failure_kinds),
        "times_failed_in_a_row": request.consecutive_failures,
        "screenshot": "attached as an image; it is the CURRENT screen, look at it",
    }
    return "This skill's repair record:\n" + json.dumps(payload, ensure_ascii=False, indent=1)


@dataclass(frozen=True)
class RepairProposal:
    """One validated repair answer.  A candidate patch, never a production change."""

    request_id: str
    skill_id: str
    judgement: str
    reason: str = ""
    new_semantic_target: str = ""
    candidate_bbox_norm: tuple[float, float, float, float] | None = None
    expected_result: str = ""
    answered_at: str = ""
    source: str = "LOCAL_GUI_MODEL"

    @property
    def is_route_change(self) -> bool:
        return self.judgement in ROUTE_JUDGEMENTS

    def as_row(self) -> dict[str, Any]:
        return {
            "recorded_at": _now(),
            "status": "CANDIDATE_PATCH",
            "skill_id": self.skill_id,
            "request_id": self.request_id,
            "judgement": self.judgement,
            "reason": self.reason[:300],
            "new_semantic_target": self.new_semantic_target,
            # Written under a key that says "proposal", for the same reason the planner's box is:
            # a key that reads like a confirmed position is the first step to it becoming one.
            "proposed_region_untrusted": (
                list(self.candidate_bbox_norm) if self.candidate_bbox_norm else None
            ),
            "expected_result": self.expected_result,
            "source": self.source,
            "not_yet": (
                "a proposed patch only -- it has not been grounded, not been tried, and not been "
                "promoted. The existing Replay -> Shadow -> Live Verification gate decides."
            ),
        }


@dataclass(frozen=True)
class RepairParse:
    proposal: RepairProposal | None = None
    error: str = ""
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.proposal is not None


def _box(value: Any) -> tuple[tuple[float, float, float, float] | None, str]:
    """Read ``[x, y, w, h]`` as normalised fractions, or say why it is not one.

    The same strictness the planner applies, restated here rather than imported: the two contracts
    are allowed to diverge (this one has no element table to fall back on), and a shared validator
    would make a change to one silently change the other's meaning.
    """
    if value is None:
        return None, ""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None, "REPAIR_BOX_NOT_FOUR_NUMBERS"
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return None, "REPAIR_BOX_NOT_A_NUMBER"
    if any(number != number or number in (float("inf"), float("-inf")) for number in numbers):
        return None, "REPAIR_BOX_NOT_A_NUMBER"
    x, y, w, h = numbers
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None, "REPAIR_BOX_NOT_NORMALISED"
    if w <= 0.0 or h <= 0.0 or w > 1.0 or h > 1.0:
        return None, "REPAIR_BOX_NOT_NORMALISED"
    if x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
        return None, "REPAIR_BOX_OUTSIDE_FRAME"
    return (round(x, 4), round(y, 4), round(w, 4), round(h, 4)), ""


def parse_repair_reply(raw: str, *, request: RepairRequest) -> RepairParse:
    """Read one repair reply, or say why it cannot be used."""
    text = str(raw or "").strip()
    if not text:
        return RepairParse(error="REPAIR_EMPTY")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return RepairParse(error=f"REPAIR_NOT_JSON: {exc.msg}", raw=text[:400])
    if not isinstance(payload, Mapping):
        return RepairParse(error="REPAIR_NOT_AN_OBJECT", raw=text[:400])
    judgement = str(payload.get("judgement") or "").strip().upper()
    if judgement not in JUDGEMENTS:
        return RepairParse(error=f"REPAIR_JUDGEMENT_UNKNOWN: {judgement[:40]!r}", raw=text[:400])
    box, box_error = _box(payload.get("candidate_bbox_norm"))
    if box_error:
        return RepairParse(error=box_error, raw=text[:400])
    return RepairParse(
        proposal=RepairProposal(
            request_id=request.request_id,
            skill_id=request.skill_id,
            judgement=judgement,
            reason=str(payload.get("reason") or "").strip(),
            new_semantic_target=str(payload.get("new_semantic_target") or "").strip(),
            candidate_bbox_norm=box,
            expected_result=str(payload.get("expected_result") or "").strip(),
            answered_at=_now(),
        ),
        raw=text[:400],
    )


def file_candidate_patch(
    proposal: RepairProposal,
    request: RepairRequest,
    *,
    out_dir: Path | str = CANDIDATE_PATCH_DIR,
    ledger_path: Path | str | None = None,
) -> Path | None:
    """Write one repair as a candidate patch.  The only thing this module is allowed to write.

    The file carries the trigger's evidence as well as the answer, because section 17's gate has to
    be able to re-judge the repair months later: an answer whose evidence was not kept becomes an
    opinion, and an opinion cannot be promoted or rejected on its merits.

    Never returns a path when the write fails -- the caller treats ``None`` as "nothing was
    learned", which is the same outcome as a refusal and must not look like success.
    """
    directory = Path(out_dir)
    path = directory / f"{proposal.skill_id}.json"
    record = {
        "schema_version": "1.0",
        "recorded_at": _now(),
        "skill_id": proposal.skill_id,
        "page_key": request.page_key,
        "goal_id": request.goal_id,
        "status": "CANDIDATE_PATCH",
        "judgement": proposal.judgement,
        "is_route_change": proposal.is_route_change,
        "proposed": proposal.as_row(),
        "trigger": request.as_row(),
        "promotion_note": (
            "Route changed, so the repair is a precondition change: it may not be promoted by "
            "re-locating one control."
            if proposal.is_route_change else
            "Locator repair: replay -> shadow -> live verification, then the patch may replace the "
            "skill's target."
        ),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return None
    if ledger_path:
        try:
            ledger = Path(ledger_path)
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except (OSError, TypeError, ValueError):
            pass
    return path


# ---------------------------------------------------------------------------- stats
@dataclass
class RepairStats:
    """What repair has cost and what it has produced, for section 47's report."""

    attempts: int = 0
    verified: int = 0
    judgements: dict[str, int] = field(default_factory=dict)
    candidate_patches: int = 0
    route_changes: int = 0

    @classmethod
    def load(cls, *, out_dir: Path | str = CANDIDATE_PATCH_DIR) -> "RepairStats":
        stats = cls()
        directory = Path(out_dir)
        if not directory.exists():
            return stats
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            stats.attempts += 1
            stats.candidate_patches += 1
            judgement = str(payload.get("judgement") or "UNKNOWN")
            stats.judgements[judgement] = stats.judgements.get(judgement, 0) + 1
            if payload.get("is_route_change"):
                stats.route_changes += 1
            if str(payload.get("status")) == "VERIFIED_PATCH":
                stats.verified += 1
        return stats

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
