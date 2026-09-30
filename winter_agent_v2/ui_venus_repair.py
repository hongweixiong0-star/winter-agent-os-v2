"""SKILL_REPAIR: the packet for a skill that used to work, and the patch it may propose.

Operator directive 2026-10-01, sections 14-15, plus the section-30 independence rule.

    UIVenusSkillRepairPacketV1  section 14  the failure, with the skill's own history
    UIVenusRepairCandidateV1    section 15  the diagnosis and the proposed change
    validate_repair_candidate              the gate that keeps a candidate a candidate

This is *not* an ordinary UNKNOWN, and the directive is explicit about the difference: "必须告诉
模型：这是一个以前成功过、现在失效的 Skill".  An UNKNOWN asks "what is this screen"; a repair asks
"why does this thing that worked stop working", which is a question only the *old* evidence makes
answerable.  That is why the packet carries ``previous_success_evidence`` at all -- a model shown
only the failing frame would be re-deriving the skill from scratch, and would be free to conclude
something that contradicts eight recorded successes.

Three things this module makes structurally impossible
------------------------------------------------------
1. **A candidate overwriting a stable skill.**  ``may_overwrite_stable`` returns ``False``
   unconditionally and ``RepairConstraints`` has no setter for it.  Sections 15 and 30 both forbid
   it, and the existing Replay -> Shadow -> Live Verification -> PromotionGate chain is the only
   route in.  A function rather than a comment, so a reviewer can grep the answer.
2. **Learning an absolute coordinate as the repair.**  ``proposed_change.type`` is a closed
   vocabulary that simply does not contain a position; a change that names one is refused by name
   (``REPAIR_LEARNS_A_COORDINATE``).  The one channel that may carry a region is
   ``candidate_bbox_norm``, which is an untrusted proposal on the *current* frame and grounds
   through the same code as ONLINE.
3. **A silent production write.**  ``RepairConstraints.direct_production_patch_allowed`` defaults
   to ``False`` and the packet states it to the model, so a reply that assumes permission is
   answering a different question than the one it was asked.

How this relates to ``skill_repair``
------------------------------------
``skill_repair`` already owns the *trigger* ("three consecutive perception failures, not a full
queue") and the request/answer files the runtime writes.  That module stays: the trigger is not
duplicated here.  This module owns the **types** the contract names, and provides adapters
(``packet_from_request``, ``candidate_from_proposal``) so the runtime's existing flow produces the
contract's shapes without a second code path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import ui_venus_contract as contract
from .ui_venus_contract import (
    MAX_INPUT_TOKENS,
    MAX_MODEL_CONTEXT,
    MODE_SKILL_REPAIR,
    OUTPUT_RESERVE,
    FrameIdentity,
    Ledger,
    Verdict,
    ok,
    read_box,
    refuse,
    reason_violation,
)

SCHEMA_SKILL_REPAIR_PACKET = "UIVenusSkillRepairPacketV1"
SCHEMA_REPAIR_CANDIDATE = "UIVenusRepairCandidateV1"
REPAIR_LEDGER_PATH = Path("learning/ui_venus_repair.jsonl")

#: Section 15's ``analysis_type``.  One legal value, because a repair reply that is not a repair
#: candidate is a reply to a different question.
ANALYSIS_TYPE = "SKILL_REPAIR_CANDIDATE"

#: Section 15's diagnosis vocabulary.  A closed set so a reviewer can count them, and so "the
#: layout moved" can never be silently recorded as "the skill is wrong" -- those two lead to
#: different repairs (re-locate vs change the route) and the promotion gate treats them
#: differently.
DIAGNOSES: tuple[str, ...] = (
    "VISUAL_LAYOUT_DRIFT",
    "TARGET_TEXT_CHANGED",
    "TARGET_ICON_CHANGED",
    "ENTRY_MOVED",
    "SKILL_OUTDATED",
    "NOT_THIS_PAGE",
    "UNKNOWN",
)

#: The diagnoses that say the *route* is wrong rather than the locator.  Recorded separately
#: because the repair is a precondition change, which the promotion gate treats differently from
#: a re-located control.
ROUTE_DIAGNOSES: tuple[str, ...] = ("SKILL_OUTDATED", "NOT_THIS_PAGE")

#: ``skill_repair.JUDGEMENTS`` on this vocabulary.  The trigger module keeps its own strings (its
#: tests pin them); this is the *known* translation between the two, so a repository with both
#: vocabularies has one meaning rather than two.
JUDGEMENT_TO_DIAGNOSIS: dict[str, str] = {
    "TARGET_STILL_PRESENT_LAYOUT_CHANGED": "VISUAL_LAYOUT_DRIFT",
    "TARGET_TEXT_CHANGED": "TARGET_TEXT_CHANGED",
    "TARGET_ICON_CHANGED": "TARGET_ICON_CHANGED",
    "ENTRY_MOVED": "ENTRY_MOVED",
    "SKILL_OUTDATED": "SKILL_OUTDATED",
    "NOT_THIS_PAGE": "NOT_THIS_PAGE",
    "UNKNOWN": "UNKNOWN",
}

#: What a repair may change.  There is deliberately no position in this list: a repair is a change
#: to a *rule*, and the coordinate rule is enforced by the vocabulary rather than by a check
#: someone has to remember to run.
CHANGE_VISUAL_RULE = "VISUAL_RULE"
CHANGE_SEMANTIC_TARGET = "SEMANTIC_TARGET"
CHANGE_PRECONDITION = "PRECONDITION"
CHANGE_ROUTE = "ROUTE"
CHANGE_RETIRE = "RETIRE"
CHANGE_TYPES: tuple[str, ...] = (
    CHANGE_VISUAL_RULE, CHANGE_SEMANTIC_TARGET, CHANGE_PRECONDITION, CHANGE_ROUTE, CHANGE_RETIRE,
)

#: Change kinds that are refused by name rather than by omission, so a reply that asks for one gets
#: a specific refusal instead of a generic schema error.  "PRODUCTION_PATCH" is the direct-write
#: attempt; the two coordinate ones are the shortcut this project's constitution forbids.
FORBIDDEN_CHANGE_TYPES: tuple[str, ...] = (
    "PRODUCTION_PATCH", "DIRECT_WRITE", "STABLE_OVERWRITE", "ABSOLUTE_COORDINATE",
    "PIXEL_POSITION", "HARDCODED_POINT",
)

#: Section 15's ``required_validation``.  The directive names four; the ones a repair must have are
#: the three that make it *evidence* rather than an opinion.
VALIDATION_CURRENT_FRAME_GROUNDING = "CURRENT_FRAME_GROUNDING"
VALIDATION_LIVE_VERIFIER = "LIVE_VERIFIER"
VALIDATION_REPLAY = "REPLAY"
VALIDATION_SHADOW = "SHADOW"
REQUIRED_VALIDATION_KINDS: tuple[str, ...] = (
    VALIDATION_CURRENT_FRAME_GROUNDING, VALIDATION_LIVE_VERIFIER,
    VALIDATION_REPLAY, VALIDATION_SHADOW,
)

#: The validations that mean "this was checked against reality, not against itself".  At least one
#: is mandatory: a repair candidate that only asks to be re-grounded has no path to promotion and
#: would sit in the folder forever looking like work.
LIVE_VALIDATIONS: tuple[str, ...] = (VALIDATION_LIVE_VERIFIER,)

REPAIR_REASON_MAX_CHARS = 120
DIAGNOSIS_DETAIL_MAX_CHARS = 120

#: Refusals this mode adds.  Prefixed ``REPAIR_`` so a folded ledger cannot confuse them with the
#: planner's ``PLAN_`` codes -- section 30's independence, visible in the data.
REPAIR_NOT_JSON = "REPAIR_NOT_JSON"
REPAIR_NOT_AN_OBJECT = "REPAIR_NOT_AN_OBJECT"
REPAIR_SCHEMA_INVALID = "REPAIR_SCHEMA_INVALID"
REPAIR_ANALYSIS_TYPE_UNKNOWN = "REPAIR_ANALYSIS_TYPE_UNKNOWN"
REPAIR_SKILL_MISMATCH = "REPAIR_SKILL_MISMATCH"
REPAIR_DIAGNOSIS_UNKNOWN = "REPAIR_DIAGNOSIS_UNKNOWN"
REPAIR_CHANGE_TYPE_UNKNOWN = "REPAIR_CHANGE_TYPE_UNKNOWN"
REPAIR_LEARNS_A_COORDINATE = "REPAIR_LEARNS_A_COORDINATE"
REPAIR_WOULD_TOUCH_PRODUCTION = "REPAIR_WOULD_TOUCH_PRODUCTION"
REPAIR_NO_EVIDENCE_REFS = "REPAIR_NO_EVIDENCE_REFS"
REPAIR_EVIDENCE_NOT_IN_PACKET = "REPAIR_EVIDENCE_NOT_IN_PACKET"
REPAIR_NO_REQUIRED_VALIDATION = "REPAIR_NO_REQUIRED_VALIDATION"
REPAIR_VALIDATION_UNKNOWN = "REPAIR_VALIDATION_UNKNOWN"
REPAIR_NOT_LIVE_VALIDATED = "REPAIR_NOT_LIVE_VALIDATED"
REPAIR_GEOMETRY_TRANSPORTED = "REPAIR_GEOMETRY_TRANSPORTED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------- packet (section 14)
@dataclass(frozen=True)
class RepairIdentity:
    """Section 14's ``identity`` block."""

    role_id: str = ""
    goal_id: str = ""
    skill_id: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {"role_id": self.role_id, "goal_id": self.goal_id, "skill_id": self.skill_id}


@dataclass(frozen=True)
class ExistingSkill:
    """Section 14's ``existing_skill`` block -- what the skill believes about itself.

    ``maturity`` is recorded so the reader can see what is at stake: a repair proposed against a
    ``CANDIDATE`` is a different act from one against a ``STABLE`` skill in production, even
    though neither may be written directly.
    """

    skill_id: str = ""
    maturity: str = ""
    semantic_target: str = ""
    expected_result: str = ""
    known_visual_rules: tuple[str, ...] = ()

    def as_wire(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "maturity": self.maturity,
            "semantic_target": self.semantic_target,
            "expected_result": self.expected_result,
            "known_visual_rules": list(self.known_visual_rules)[:8],
        }


@dataclass(frozen=True)
class SuccessEvidence:
    """One representative success (section 14's ``previous_success_evidence``).

    Section 14 says "只给少量代表性成功证据" -- a handful, not the whole history.  The bound is the
    caller's; this type records what one unit is so the packet's shape does not depend on how many
    the caller chose.
    """

    episode_id: str = ""
    page_before: str = ""
    page_after: str = ""
    verifier: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "page_before": self.page_before,
            "page_after": self.page_after,
            "verifier": self.verifier,
        }


@dataclass(frozen=True)
class FailureState:
    """Section 14's ``current_failure`` block: the run of failures, in the verifier's words."""

    consecutive_failures: int = 0
    verifier_reason: str = ""
    semantic_retry_result: str = ""
    loop_pattern: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "consecutive_failures": int(self.consecutive_failures),
            "verifier_reason": self.verifier_reason,
            "semantic_retry_result": self.semantic_retry_result,
            "loop_pattern": self.loop_pattern,
        }


@dataclass(frozen=True)
class RepairConstraints:
    """Section 14's ``constraints`` block, stated to the model *and* enforced here.

    Told to the model because a reply that assumes permission is answering a different question;
    enforced here because a model's assumption is not a boundary.  All three default to the closed
    value, and ``absolute_coordinate_learning_allowed`` has no setter -- a contract that could be
    configured into allowing coordinate learning is one config edit from doing it.
    """

    direct_production_patch_allowed: bool = False
    direct_stable_overwrite_allowed: bool = False
    absolute_coordinate_learning_allowed: bool = False

    def as_wire(self) -> dict[str, Any]:
        return {
            "direct_production_patch_allowed": False,
            "direct_stable_overwrite_allowed": False,
            "absolute_coordinate_learning_allowed": False,
        }


@dataclass(frozen=True)
class UIVenusSkillRepairPacketV1:
    """Section 14's packet, field for field."""

    identity: RepairIdentity = field(default_factory=RepairIdentity)
    frame_id: str = ""
    frame_hash: str = ""
    screenshot: str = "CURRENT_FRESH_IMAGE"
    page: str = ""
    page_confidence: float | None = None
    existing_skill: ExistingSkill = field(default_factory=ExistingSkill)
    previous_success_evidence: tuple[SuccessEvidence, ...] = ()
    current_failure: FailureState = field(default_factory=FailureState)
    elements: Mapping[str, Any] = field(default_factory=dict)
    relevant_knowledge: tuple[Mapping[str, Any], ...] = ()
    constraints: RepairConstraints = field(default_factory=RepairConstraints)
    budget: Mapping[str, Any] = field(default_factory=lambda: {
        "max_context_tokens": MAX_MODEL_CONTEXT,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "output_reserve_tokens": OUTPUT_RESERVE,
    })
    mode: str = MODE_SKILL_REPAIR

    @property
    def frame_identity(self) -> FrameIdentity:
        return FrameIdentity(self.frame_id, self.frame_hash)

    def evidence_ids(self) -> set[str]:
        """Every episode/frame id this packet actually contains.

        A candidate's ``evidence_refs`` is checked against this: an evidence list that names
        something the packet never showed is a citation the reader cannot follow, and following it
        is the whole point of section 17's traceability rule.
        """
        ids: set[str] = set()
        for item in self.previous_success_evidence:
            if item.episode_id:
                ids.add(item.episode_id)
        if isinstance(self.elements, Mapping):
            if self.elements.get("frame_id"):
                ids.add(str(self.elements["frame_id"]))
        if self.frame_id:
            ids.add(self.frame_id)
        return ids

    def validate(self) -> Verdict:
        """What must hold before the model is asked."""
        if not self.identity.skill_id:
            return refuse(REPAIR_SCHEMA_INVALID, stage="SCHEMA", detail="no skill_id")
        if not self.existing_skill.semantic_target and not self.existing_skill.expected_result:
            return refuse(REPAIR_SCHEMA_INVALID, stage="SCHEMA",
                          detail="the skill states neither a target nor an expected result")
        if self.current_failure.consecutive_failures <= 0:
            return refuse(REPAIR_SCHEMA_INVALID, stage="SCHEMA",
                          detail="no recorded failure: a repair with no failure is an UNKNOWN")
        if not self.frame_id or not self.frame_hash:
            return refuse(contract.CONTEXT_FRAME_MISMATCH, stage="FRAME_CONSISTENCY",
                          detail="the packet has no current frame")
        elements_frame = ""
        if isinstance(self.elements, Mapping):
            elements_frame = str(self.elements.get("frame_id") or "")
        if elements_frame and elements_frame != self.frame_id:
            return refuse(contract.CONTEXT_FRAME_MISMATCH, stage="FRAME_CONSISTENCY",
                          detail=f"elements {elements_frame!r} vs frame {self.frame_id!r}")
        return ok("SCHEMA")

    def as_wire(self) -> dict[str, Any]:
        packet: dict[str, Any] = {
            "mode": self.mode,
            "identity": self.identity.as_wire(),
            "current_frame": {
                "frame_id": self.frame_id,
                "screenshot": self.screenshot,
                "frame_hash": self.frame_hash,
            },
            "current_world": {"page": self.page, "page_confidence": self.page_confidence},
            "existing_skill": self.existing_skill.as_wire(),
            "previous_success_evidence": [e.as_wire() for e in self.previous_success_evidence],
            "current_failure": self.current_failure.as_wire(),
            "current_elements": dict(self.elements),
            "relevant_knowledge": [dict(row) for row in self.relevant_knowledge],
            "constraints": self.constraints.as_wire(),
            "context_budget": dict(self.budget),
        }
        return packet

    def render(self) -> str:
        return "This skill's repair packet:\n" + json.dumps(
            self.as_wire(), ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------- candidate (section 15)
@dataclass(frozen=True)
class ProposedChange:
    """Section 15's ``proposed_change``: a type from the closed vocabulary and a description."""

    type: str = ""
    description: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {"type": self.type, "description": self.description[:DIAGNOSIS_DETAIL_MAX_CHARS]}

    @property
    def is_forbidden(self) -> bool:
        return self.type.strip().upper() in FORBIDDEN_CHANGE_TYPES


@dataclass(frozen=True)
class UIVenusRepairCandidateV1:
    """Section 15's reply, parsed.  A candidate patch, never a production change."""

    skill_id: str = ""
    diagnosis: str = ""
    semantic_target: str = ""
    proposed_change: ProposedChange = field(default_factory=ProposedChange)
    candidate_bbox_norm: tuple[float, float, float, float] | None = None
    expected_result: str = ""
    confidence: float = 0.0
    evidence_refs: tuple[str, ...] = ()
    required_validation: tuple[str, ...] = ()
    analysis_type: str = ANALYSIS_TYPE
    reason: str = ""
    source: str = "LOCAL_GUI_MODEL"

    @property
    def is_route_change(self) -> bool:
        return self.diagnosis in ROUTE_DIAGNOSES

    def as_row(self, *, trace_id: str = "") -> dict[str, Any]:
        """The ledger row, and the shape a candidate patch file gets on disk.

        ``status`` is written and is always ``CANDIDATE``: section 21 says every offline and repair
        output starts there, and a row that omitted it would leave a reader to infer status from
        which folder it was in.
        """
        return {
            "recorded_at": _now(),
            "schema": SCHEMA_REPAIR_CANDIDATE,
            "mode": MODE_SKILL_REPAIR,
            "trace_id": trace_id,
            "status": "CANDIDATE",
            "analysis_type": self.analysis_type,
            "skill_id": self.skill_id,
            "diagnosis": self.diagnosis,
            "semantic_target": self.semantic_target,
            "proposed_change": self.proposed_change.as_wire(),
            "proposed_region_untrusted": (
                list(self.candidate_bbox_norm) if self.candidate_bbox_norm else None
            ),
            "expected_result": self.expected_result,
            "confidence": round(float(self.confidence), 3),
            "evidence_refs": list(self.evidence_refs),
            "required_validation": list(self.required_validation),
            "reason": self.reason[:REPAIR_REASON_MAX_CHARS],
            "source": self.source,
            "not_yet": (
                "a proposed patch only -- it has not been grounded, not been tried and not been "
                "promoted. This skill's stable record is untouched; the existing Replay -> Shadow "
                "-> Live Verification -> PromotionGate chain decides."
            ),
        }


@dataclass(frozen=True)
class RepairCandidateParse:
    candidate: UIVenusRepairCandidateV1 | None = None
    error: str = ""
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.candidate is not None


# ---------------------------------------------------------------------------- schema
def repair_schema() -> dict[str, Any]:
    """Section 15's reply contract, as JSON Schema.

    The enums matter more here than in the planner's contract: this answer names the *repair*, so
    an invented diagnosis is an invented repair action.  ``candidate_bbox_norm`` is present but
    nullable -- the region channel exists (a moved control has to be indicated somehow) while the
    *change* vocabulary deliberately has no position to name.
    """
    return {
        "type": "object",
        "properties": {
            "analysis_type": {"type": "string", "enum": [ANALYSIS_TYPE]},
            "skill_id": {"type": "string", "maxLength": 80},
            "diagnosis": {"type": "string", "enum": list(DIAGNOSES)},
            "semantic_target": {"type": "string", "maxLength": 60},
            "proposed_change": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(CHANGE_TYPES)},
                    "description": {"type": "string", "maxLength": DIAGNOSIS_DETAIL_MAX_CHARS},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
            contract.VISION_BOX_KEY: {
                "type": ["array", "null"],
                "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
            },
            "expected_result": {"type": "string", "maxLength": 60},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_refs": {
                "type": "array", "items": {"type": "string", "maxLength": 80}, "minItems": 1,
            },
            "required_validation": {
                "type": "array",
                "items": {"type": "string", "enum": list(REQUIRED_VALIDATION_KINDS)},
                "minItems": 1,
            },
            "reason": {"type": "string", "maxLength": REPAIR_REASON_MAX_CHARS},
        },
        "required": ["analysis_type", "diagnosis", "proposed_change", "evidence_refs",
                     "required_validation", "reason"],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """You are the repair analyst of a screenshot-driven game automation agent.

A skill that used to work has now failed several times in a row. You are shown the CURRENT
screenshot, what that skill expects, a few episodes where it succeeded, and the verifier's reasons
for the failures since.

Your question is not "what is this screen" -- it is: why does this thing that worked stop working?

Diagnose with exactly one of:
- VISUAL_LAYOUT_DRIFT: the control is on this screen, drawn somewhere else than it used to be.
- TARGET_TEXT_CHANGED: the control is there but its printed words differ now.
- TARGET_ICON_CHANGED: the control is there as an icon and its artwork changed.
- ENTRY_MOVED: the screen this skill is reached from moved it elsewhere.
- SKILL_OUTDATED: the route itself no longer exists.
- NOT_THIS_PAGE: this is not the screen this skill is for; its precondition is wrong.
- UNKNOWN: you cannot tell from this picture.

Hard rules:
1. Look at the picture. Do not guess from the skill's name or its old location.
2. Propose a change to a RULE, never to a position. "proposed_change.type" must be one of:
   VISUAL_RULE, SEMANTIC_TARGET, PRECONDITION, ROUTE, RETIRE. If you can name the control's new
   location in words, put the words in "semantic_target". Never output pixel coordinates; a
   region, if you give one at all, is "candidate_bbox_norm": [x, y, width, height] with each number
   between 0 and 1 as a fraction of the image. It is only a proposal and is re-checked against the
   live screen.
3. You cannot change the skill directly. This is a candidate: it must be replayed, shadowed and
   live-verified before anything is promoted. Say which checks it needs in "required_validation"
   (CURRENT_FRAME_GROUNDING, REPLAY, SHADOW, LIVE_VERIFIER).
4. Every conclusion must cite the episodes it came from, in "evidence_refs".
5. Reply with JSON only, in exactly the shape you are asked for. The server enforces the key set,
   the enums and the length caps, so an extra key is refused rather than ignored.
6. "reason" is one short sentence. Do not write a plan or a rationale paragraph."""


# ---------------------------------------------------------------------------- parsing
def parse_repair_candidate(raw: str, *, packet: UIVenusSkillRepairPacketV1) -> RepairCandidateParse:
    """Read one repair reply, or say exactly why it cannot be used.

    Shape only.  The section-15 gate ("no stable overwrite, no coordinates, cite your evidence") is
    ``validate_repair_candidate``'s job, so "this is not JSON" stays distinguishable from "this
    asks to write to production".
    """
    text = str(raw or "").strip()
    if not text:
        return RepairCandidateParse(error=REPAIR_NOT_JSON, raw="")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return RepairCandidateParse(error=f"{REPAIR_NOT_JSON}: {exc.msg}", raw=text[:400])
    if not isinstance(payload, Mapping):
        return RepairCandidateParse(error=REPAIR_NOT_AN_OBJECT, raw=text[:400])

    geometry = contract.find_forbidden_geometry(payload)
    if geometry:
        return RepairCandidateParse(
            error=f"{REPAIR_GEOMETRY_TRANSPORTED}: {geometry}", raw=text[:400])

    analysis = str(payload.get("analysis_type") or ANALYSIS_TYPE).strip().upper()
    if analysis != ANALYSIS_TYPE:
        return RepairCandidateParse(
            error=f"{REPAIR_ANALYSIS_TYPE_UNKNOWN}: {analysis[:40]!r}", raw=text[:400])

    diagnosis = str(payload.get("diagnosis") or "").strip().upper()
    if diagnosis not in DIAGNOSES:
        return RepairCandidateParse(
            error=f"{REPAIR_DIAGNOSIS_UNKNOWN}: {diagnosis[:40]!r}", raw=text[:400])

    raw_change = payload.get("proposed_change")
    change = dict(raw_change) if isinstance(raw_change, Mapping) else {}
    change_type = str(change.get("type") or payload.get("change_type") or "").strip().upper()
    change_desc = str(change.get("description") or payload.get("change_description") or "").strip()

    box, box_error = read_box(payload.get(contract.VISION_BOX_KEY))
    if box_error:
        return RepairCandidateParse(error=box_error, raw=text[:400])

    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    refs = tuple(
        str(item).strip() for item in _as_list(payload.get("evidence_refs")) if str(item).strip()
    )
    checks = tuple(
        str(item).strip().upper() for item in _as_list(payload.get("required_validation"))
        if str(item).strip()
    )

    reason = str(payload.get("reason") or "").strip()
    bad_reason = reason_violation(reason, max_chars=REPAIR_REASON_MAX_CHARS)
    if bad_reason:
        return RepairCandidateParse(error=bad_reason, raw=text[:400])

    return RepairCandidateParse(
        candidate=UIVenusRepairCandidateV1(
            skill_id=str(payload.get("skill_id") or packet.identity.skill_id).strip(),
            diagnosis=diagnosis,
            semantic_target=str(payload.get("semantic_target") or "").strip(),
            proposed_change=ProposedChange(change_type, change_desc),
            candidate_bbox_norm=box,
            expected_result=str(payload.get("expected_result") or "").strip(),
            confidence=confidence,
            evidence_refs=refs,
            required_validation=checks,
            analysis_type=analysis,
            reason=reason,
        ),
        raw=text[:400],
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [part for part in value.replace(";", ",").split(",")]
    return [value]


# ---------------------------------------------------------------------------- validator (section 15)
def validate_repair_candidate(
    candidate: UIVenusRepairCandidateV1,
    *,
    packet: UIVenusSkillRepairPacketV1,
    ground: Any = None,
    ground_regions: Iterable[Mapping[str, Any]] = (),
    frame_now: FrameIdentity | None = None,
) -> Verdict:
    """Section 15's gate, plus the two prohibitions sections 15 and 30 state twice.

    A passing verdict means "this is a well-formed candidate that may now be *tried*" -- it is not
    a permission to write anything.  ``may_overwrite_stable`` still answers ``False``.
    """
    if candidate.analysis_type != ANALYSIS_TYPE:
        return refuse(REPAIR_ANALYSIS_TYPE_UNKNOWN, stage="SCHEMA",
                      detail=candidate.analysis_type[:40])
    if candidate.skill_id and packet.identity.skill_id and \
            candidate.skill_id.upper() != packet.identity.skill_id.upper():
        return refuse(REPAIR_SKILL_MISMATCH, stage="SCHEMA",
                      detail=f"{candidate.skill_id!r} vs {packet.identity.skill_id!r}")
    if candidate.diagnosis not in DIAGNOSES:
        return refuse(REPAIR_DIAGNOSIS_UNKNOWN, stage="SCHEMA", detail=candidate.diagnosis[:40])

    # -- the change must be a rule, never a position or a production write ------------------------
    change_type = candidate.proposed_change.type.strip().upper()
    if change_type in FORBIDDEN_CHANGE_TYPES:
        return refuse(REPAIR_LEARNS_A_COORDINATE if "COORDINATE" in change_type
                      or "PIXEL" in change_type or "POINT" in change_type
                      else REPAIR_WOULD_TOUCH_PRODUCTION,
                      stage="SCHEMA", detail=f"proposed_change.type={change_type!r}")
    if not change_type:
        return refuse(REPAIR_SCHEMA_INVALID, stage="SCHEMA", detail="no proposed_change.type")
    if change_type not in CHANGE_TYPES:
        return refuse(REPAIR_CHANGE_TYPE_UNKNOWN, stage="SCHEMA", detail=change_type[:40])
    if candidate.proposed_change.description and \
            _looks_like_a_coordinate(candidate.proposed_change.description):
        return refuse(REPAIR_LEARNS_A_COORDINATE, stage="SCHEMA",
                      detail="the change's own description carries a position")

    # -- constraints -----------------------------------------------------------------------------
    #
    # ``packet.constraints`` is stated to the model and enforced here.  It is read rather than
    # assumed: the three fields are forced False by ``RepairConstraints``, and a packet whose
    # constraints ever said otherwise is refused rather than trusted -- that way the closed values
    # are load-bearing instead of decorative.
    if packet.constraints.direct_stable_overwrite_allowed or \
            packet.constraints.direct_production_patch_allowed or \
            packet.constraints.absolute_coordinate_learning_allowed:
        return refuse(REPAIR_WOULD_TOUCH_PRODUCTION, stage="SCHEMA",
                      detail="the packet granted a permission section 15 forbids")
    if candidate.diagnosis in ROUTE_DIAGNOSES and change_type not in (CHANGE_ROUTE, CHANGE_RETIRE):
        # A route diagnosis answered with a locator change is the classic misrepair: the model saw
        # the page is wrong and proposed re-locating a control on it.  Refused so the two are not
        # conflated in the promotion gate.
        return refuse(REPAIR_CHANGE_TYPE_UNKNOWN, stage="SCHEMA",
                      detail=f"route diagnosis {candidate.diagnosis} wants ROUTE or RETIRE, "
                             f"got {change_type!r}")

    # -- evidence (section 17) -------------------------------------------------------------------
    if not candidate.evidence_refs:
        return refuse(REPAIR_NO_EVIDENCE_REFS, stage="GROUNDING",
                      detail="a conclusion with no episodes cited is not traceable")
    known = packet.evidence_ids()
    if known:
        unknown = [ref for ref in candidate.evidence_refs if ref not in known]
        if len(unknown) == len(candidate.evidence_refs):
            return refuse(REPAIR_EVIDENCE_NOT_IN_PACKET, stage="GROUNDING",
                          detail=f"none of {list(candidate.evidence_refs)} is in the packet")

    # -- required validation (section 15's pipeline) ---------------------------------------------
    if not candidate.required_validation:
        return refuse(REPAIR_NO_REQUIRED_VALIDATION, stage="GROUNDING",
                      detail="the candidate names no check it must pass")
    bad = [c for c in candidate.required_validation if c not in REQUIRED_VALIDATION_KINDS]
    if bad:
        return refuse(REPAIR_VALIDATION_UNKNOWN, stage="GROUNDING", detail=f"unknown checks {bad}")
    if not any(c in LIVE_VALIDATIONS for c in candidate.required_validation):
        return refuse(REPAIR_NOT_LIVE_VALIDATED, stage="GROUNDING",
                      detail=f"needs one of {list(LIVE_VALIDATIONS)}: a candidate that cannot be "
                             f"live-verified has no route out of the candidate folder")

    # -- the one region channel, grounded against the current frame -------------------------------
    if candidate.candidate_bbox_norm is not None:
        box = candidate.candidate_bbox_norm
        if callable(ground):
            region, reason = ground(box, ground_regions)
        else:
            from . import ui_venus_online as online

            region, reason = online.local_ground(
                box, regions=ground_regions,
                frame_now=frame_now, frame_then=packet.frame_identity if frame_now else None,
            )
        if region is None:
            return refuse(contract.UNKNOWN_GROUNDING_FAILED, stage="GROUNDING", detail=reason)

    return ok("")


def _looks_like_a_coordinate(text: str) -> bool:
    """Whether a free-text description smuggled in a position.

    A rule description may say "the entry is now under the alliance button"; it may not say
    "(0.86, 0.68)" or "x=340, y=812".  Checked because the change vocabulary closes the *typed*
    door and a description is the untyped one -- the constitution is explicit that renaming a
    variable or moving a number into a string does not change the answer.
    """
    import re

    padded = f" {text} "
    if re.search(r"\b[xy]\s*=\s*\d", text, flags=re.IGNORECASE):
        return True
    if re.search(r"\b\d{2,4}\s*,\s*\d{2,4}\b", text):
        return True
    return bool(re.search(r"\(\s*0?\.\d+\s*,\s*0?\.\d+\s*\)", padded))


def may_overwrite_stable(candidate: Any = None) -> bool:
    """Always ``False``.  Sections 15 and 30 both forbid a repair from writing a stable skill.

    Takes an argument and ignores it so the call sites read as a decision being made, and so the
    answer to "may this patch the production skill" is a function a reviewer can grep rather than a
    sentence in a docstring.  The only route is the existing candidate patch -> replay -> shadow ->
    live verification -> PromotionGate chain, which lives elsewhere and is not bypassable here.
    """
    return False


# ---------------------------------------------------------------------------- ledger (section 30)
class RepairLedger(Ledger):
    """This mode's ledger.  Independent file and row shape (section 30)."""

    PATH = REPAIR_LEDGER_PATH

    def record_packet(
        self, packet: UIVenusSkillRepairPacketV1, *, verdict: Verdict, trace_id: str = ""
    ) -> dict[str, Any]:
        """One row per repair *question*: was section 14's packet well formed enough to ask with.

        Kept apart from the answer's row because the two failures are different and only one of them
        is the model's fault.  A packet with no current frame, or a skill that states neither what it
        aims at nor what its verifier requires, means the model was never really asked -- and a
        ledger that only kept answers could not tell that apart from a model that answered badly.
        """
        row = {
            "recorded_at": _now(),
            "schema": SCHEMA_SKILL_REPAIR_PACKET,
            "mode": MODE_SKILL_REPAIR,
            "trace_id": trace_id,
            "kind": "PACKET",
            "skill_id": packet.identity.skill_id,
            "page_key": packet.page,
            "frame_id": packet.frame_id,
            "frame_hash": packet.frame_hash,
            "maturity": packet.existing_skill.maturity,
            "semantic_target": packet.existing_skill.semantic_target[:120],
            "consecutive_failures": int(packet.current_failure.consecutive_failures),
            "success_evidence_count": len(packet.previous_success_evidence),
            "admitted": bool(verdict.ok),
            "verdict": verdict.as_row(),
        }
        self.append(row)
        return row

    def record_candidate(
        self, candidate: UIVenusRepairCandidateV1, *, verdict: Verdict, trace_id: str = "",
        page_key: str = "",
    ) -> dict[str, Any]:
        row = candidate.as_row(trace_id=trace_id)
        row["page_key"] = page_key
        row["verdict"] = verdict.as_row()
        row["admitted"] = bool(verdict.ok)
        self.append(row)
        return row

    def record_refusal(
        self, *, code: str, stage: str, detail: str = "", trace_id: str = "", skill_id: str = "",
        raw: str = "",
    ) -> dict[str, Any]:
        row = {
            "recorded_at": _now(),
            "schema": SCHEMA_REPAIR_CANDIDATE,
            "mode": MODE_SKILL_REPAIR,
            "trace_id": trace_id,
            "skill_id": skill_id,
            "status": "CANDIDATE",
            "admitted": False,
            "verdict": refuse(code, stage=stage, detail=detail).as_row(),
            "raw": str(raw)[:300],
        }
        self.append(row)
        return row


# ---------------------------------------------------------------------------- adapters
def packet_from_request(
    request: Any,
    *,
    maturity: str = "",
    known_visual_rules: Sequence[str] = (),
    success_evidence: Sequence[Any] = (),
    elements: Mapping[str, Any] | None = None,
    relevant_knowledge: Sequence[Mapping[str, Any]] = (),
) -> UIVenusSkillRepairPacketV1:
    """Build section 14's packet from the ``skill_repair`` trigger module's own request.

    Duck-typed rather than imported, so this module has no dependency on the trigger's internals
    and the trigger keeps owning "when is a skill escalated".  ``skill_repair`` keeps producing its
    request file -- the runtime's flow is unchanged -- and this is how the same facts reach the
    contract's shape.

    The trigger's own field names are read first, because they are the ones the runtime actually
    fills in: ``RepairRequest`` spells the skill's aim ``old_semantic`` and its verifier's
    requirement ``verifier_expectation``, and an adapter that read only this contract's spellings
    would produce a packet whose skill states neither a target nor an expected result -- which
    ``validate`` refuses, correctly, and which nobody would notice until a repair silently stopped
    being filed.  The contract's names are still accepted so a caller may pass either shape.
    """
    evidence = tuple(
        item if isinstance(item, SuccessEvidence) else SuccessEvidence(
            episode_id=str(getattr(item, "episode_id", "") or (item.get("episode_id", "")
                                                              if isinstance(item, Mapping) else "")),
            page_before=str(getattr(item, "page_before", "") or
                            (item.get("page_before", "") if isinstance(item, Mapping) else "")),
            page_after=str(getattr(item, "page_after", "") or
                           (item.get("page_after", "") if isinstance(item, Mapping) else "")),
            verifier=str(getattr(item, "verifier", "") or
                         (item.get("verifier", "") if isinstance(item, Mapping) else "")),
        )
        for item in success_evidence
    )
    failure_kinds = tuple(getattr(request, "failure_kinds", ()) or ())
    frame_path = str(getattr(request, "frame_path", "") or "")
    frame_digest = str(getattr(request, "frame_digest", "") or "")
    # ``frame_id`` is this contract's spelling; the trigger stores a path (and, declared but not
    # yet populated, a digest).  A frame that cannot be named is a frame the model was not really
    # shown, so this is left empty rather than invented -- and ``validate`` then refuses the packet.
    frame_id = (str(getattr(request, "frame_id", "") or "") or frame_digest
                or (Path(frame_path).stem if frame_path else ""))
    identity = FrameIdentity.of(frame_path, frame_id=frame_id) if frame_path else FrameIdentity()
    return UIVenusSkillRepairPacketV1(
        identity=RepairIdentity(
            role_id=str(getattr(request, "role_id", "") or ""),
            goal_id=str(getattr(request, "goal_id", "") or ""),
            skill_id=str(getattr(request, "skill_id", "") or ""),
        ),
        frame_id=identity.frame_id,
        frame_hash=identity.frame_hash,
        page=str(getattr(request, "page_key", "") or ""),
        existing_skill=ExistingSkill(
            skill_id=str(getattr(request, "skill_id", "") or ""),
            maturity=maturity,
            semantic_target=str(
                getattr(request, "old_semantic", "") or getattr(request, "semantic_target", "") or ""
            ),
            expected_result=str(
                getattr(request, "verifier_expectation", "")
                or getattr(request, "expected_result", "") or ""
            ),
            known_visual_rules=tuple(str(r) for r in known_visual_rules)[:8],
        ),
        previous_success_evidence=evidence,
        current_failure=FailureState(
            consecutive_failures=int(getattr(request, "consecutive_failures", 0) or 0),
            verifier_reason=", ".join(str(k) for k in failure_kinds),
            semantic_retry_result=str(getattr(request, "semantic_retry_result", "") or ""),
            loop_pattern=str(getattr(request, "loop_pattern", "") or ""),
        ),
        elements=dict(elements or {}),
        relevant_knowledge=tuple(dict(row) for row in relevant_knowledge),
    )


def candidate_from_proposal(proposal: Any, *, packet: UIVenusSkillRepairPacketV1) -> UIVenusRepairCandidateV1:
    """Adapt ``skill_repair.RepairProposal`` onto section 15's candidate type.

    The judgement vocabulary is translated through ``JUDGEMENT_TO_DIAGNOSIS`` rather than kept
    alongside it: two vocabularies for "what is wrong" would let a repair be counted under two
    names.  ``required_validation`` gets the full pipeline because the proposal's own contract has
    no field for it and the safest default is the longest route, not the shortest.

    The change type is chosen so the adapted candidate is one this module's own validator admits:
    a route diagnosis takes ``ROUTE`` **even when the proposal also names a new control**, because
    ``validate_repair_candidate`` refuses "the route is gone" answered with a locator change -- and
    an adapter that could produce a candidate its own gate rejects would be a repair filed and then
    silently dropped.
    """
    judgement = str(getattr(proposal, "judgement", "") or "").strip().upper()
    diagnosis = JUDGEMENT_TO_DIAGNOSIS.get(judgement, "UNKNOWN")
    semantic = str(getattr(proposal, "new_semantic_target", "") or "")
    box = getattr(proposal, "candidate_bbox_norm", None)
    if diagnosis in ROUTE_DIAGNOSES:
        change_type = CHANGE_ROUTE
    elif semantic:
        change_type = CHANGE_SEMANTIC_TARGET
    else:
        change_type = CHANGE_VISUAL_RULE
    refs = tuple(str(ref) for ref in (getattr(proposal, "evidence_refs", ()) or ()))
    if not refs and packet.frame_id:
        # A proposal predating this contract carries no citations.  The frame it was asked about
        # is a real, checkable reference, so it is used rather than left empty -- an empty list
        # would be refused by ``validate_repair_candidate`` for good reason and the adapted
        # candidate would be useless.
        refs = (packet.frame_id,)
    return UIVenusRepairCandidateV1(
        skill_id=str(getattr(proposal, "skill_id", "") or packet.identity.skill_id),
        diagnosis=diagnosis,
        semantic_target=semantic,
        proposed_change=ProposedChange(change_type, str(getattr(proposal, "reason", "") or "")[:120]),
        candidate_bbox_norm=tuple(box) if box else None,
        expected_result=str(getattr(proposal, "expected_result", "") or ""),
        confidence=float(getattr(proposal, "confidence", 0.0) or 0.0),
        evidence_refs=refs,
        required_validation=REQUIRED_VALIDATION_KINDS,
        reason=str(getattr(proposal, "reason", "") or "")[:REPAIR_REASON_MAX_CHARS],
        source=str(getattr(proposal, "source", "") or "LOCAL_GUI_MODEL"),
    )


__all__ = [
    "ANALYSIS_TYPE", "CHANGE_PRECONDITION", "CHANGE_RETIRE", "CHANGE_ROUTE",
    "CHANGE_SEMANTIC_TARGET", "CHANGE_TYPES", "CHANGE_VISUAL_RULE", "DIAGNOSES",
    "FORBIDDEN_CHANGE_TYPES", "FailureState", "ExistingSkill", "JUDGEMENT_TO_DIAGNOSIS",
    "LIVE_VALIDATIONS", "ProposedChange", "REPAIR_LEDGER_PATH", "REQUIRED_VALIDATION_KINDS",
    "ROUTE_DIAGNOSES", "RepairCandidateParse", "RepairConstraints", "RepairIdentity",
    "RepairLedger", "SCHEMA_REPAIR_CANDIDATE", "SCHEMA_SKILL_REPAIR_PACKET", "SYSTEM_PROMPT",
    "SuccessEvidence", "UIVenusRepairCandidateV1", "UIVenusSkillRepairPacketV1",
    "VALIDATION_LIVE_VERIFIER", "candidate_from_proposal", "may_overwrite_stable",
    "packet_from_request", "parse_repair_candidate", "repair_schema",
    "validate_repair_candidate",
]
