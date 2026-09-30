"""ONLINE_UNKNOWN: the packet the model is asked with, and the action it may answer with.

Operator directive 2026-10-01, sections 4-13.  This module is the three-part contract for one
mode, and only that mode:

    UIVenusContextPacketV1   section 4   what the model is shown
    UIVenusSemanticActionV1  section 7   what the model may answer
    validate_action          section 13  the chain the answer must survive before it is acted on

Section 30 requires the three modes to have independent schemas, validators and ledgers, which is
why this is a module rather than three functions in a shared one.  It shares the *vocabulary* --
``ui_venus_contract`` -- and nothing else with REPAIR or OFFLINE.

The two things this module refuses to let happen
------------------------------------------------
**A decision made against two different frames.**  Section 5 names the check and the consequence::

    SCREENSHOT_FRAME_ID == ELEMENT_TABLE_FRAME_ID
    SCREENSHOT_FRAME_HASH == ELEMENT_TABLE_FRAME_HASH
    ... otherwise CONTEXT_FRAME_MISMATCH -> discard the packet, re-capture, rebuild elements

That check is *programmatic* and it lives in ``UIVenusContextPacketV1.validate``, not in a prompt
sentence, because a model shown a fresh picture beside a stale element table cannot tell you it
was shown the wrong thing.  ``validate_action`` keeps a second, later gate for the same concern --
``PLAN_FRAME_STALE`` -- which is the "the screen moved while we were thinking" case.

**A model-supplied pixel becoming a tap.**  Sections 9 and 10 are one rule with two halves: the
picture *may* be analysed when there is no element table (an empty table used to end the step
outright), and the region the model proposes is only ever ``UNTRUSTED_CURRENT_FRAME_PROPOSAL``::

    UI-Venus bbox -> CURRENT fresh frame -> local visual grounding -> CurrentFrameVerifiedRegion
                  -> Risk Gate -> MAA

``local_ground`` is that middle column made concrete, and it is the *only* way a box becomes
something the executor can use.  What it establishes is narrow and worth stating: that a visual
target really exists on this frame.  It does **not** establish that pressing it is the right
thing to do -- that is the Verifier's question, and nothing here answers it.

Section 8's precedence runs the other way: when the frame *did* offer a usable element, a box is
not a fallback but a refusal (``PLAN_BBOX_UNNECESSARY``).  Otherwise the element table would be
decoration, and "the model picked one of this screen's own controls" -- the property that makes a
plan auditable -- would stop being true.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import ui_venus_contract as contract
from .ui_venus_contract import (
    ACTION_TYPES,
    CURRENT_FRAME_VERIFIED_REGION,
    DECISIONS,
    MAX_INPUT_TOKENS,
    MAX_MODEL_CONTEXT,
    MODEL_COMPLETE_CLAIM,
    MODE_ONLINE,
    NON_TAPPING_DECISIONS,
    OUTPUT_RESERVE,
    FrameIdentity,
    Ledger,
    RiskEnvelope,
    Verdict,
    canonical_code,
    ok,
    read_box,
    refuse,
    reason_violation,
)

#: Section 4's schema name and this mode's own ledger.  A separate file from ``ui_planner``'s
#: ledger on purpose: that one records what the *planner* did, this one records what the
#: *contract* admitted, and merging them would make "the validator let this through" and "the
#: planner tried this" the same row.
SCHEMA_CONTEXT_PACKET = "UIVenusContextPacketV1"
SCHEMA_SEMANTIC_ACTION = "UIVenusSemanticActionV1"
ONLINE_LEDGER_PATH = Path("learning/ui_venus_online.jsonl")

#: Section 4's packet, required fields.  Checked by ``UIVenusContextPacketV1.missing_required``.
REQUIRED_PACKET_FIELDS: tuple[str, ...] = (
    "frame_id", "frame_hash", "role_id", "goal_id", "page",
    "elements_frame_id", "elements_frame_hash",
)

#: Section 6's overlay: the picture with element ids drawn on it.  Recorded as a *name* rather than
#: a path in the packet, because the overlay is for reading and the executor uses the raw frame --
#: section 6 is explicit that text positions on the overlay are not tap coordinates.
OVERLAY_FLAG = "CURRENT_FRAME_WITH_ELEMENT_IDS"


# ---------------------------------------------------------------------------- packet (section 4)
@dataclass(frozen=True)
class Identity:
    """Section 4's ``identity`` block.  Role travels with every call because runtime state never
    crosses roles (section 24), while the *page semantics* it learns do."""

    role_id: str = ""
    role_session_id: str = ""
    goal_id: str = ""
    validation_scope: str = ""
    capability_scope: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "role_session_id": self.role_session_id,
            "goal_id": self.goal_id,
            "validation_scope": self.validation_scope,
            "capability_scope": self.capability_scope,
        }


@dataclass(frozen=True)
class FrameRef:
    """Section 4's ``frame`` block.

    ``screenshot`` is a statement about the *call*, not a datum: since 2026-09-30 the frame
    travels as an image part beside the text, and saying so keeps the model from concluding the
    text is all it has.  ``element_overlay_image`` names the annotated variant (section 6).
    """

    frame_id: str = ""
    captured_at: str = ""
    frame_hash: str = ""
    screenshot: str = "CURRENT_FRESH_IMAGE"
    element_overlay_image: str = OVERLAY_FLAG

    @property
    def identity(self) -> FrameIdentity:
        return FrameIdentity(self.frame_id, self.frame_hash)

    def as_wire(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "captured_at": self.captured_at,
            "screenshot": self.screenshot,
            "element_overlay_image": self.element_overlay_image,
            "frame_hash": self.frame_hash,
        }


@dataclass(frozen=True)
class WorldRef:
    """Section 4's ``world`` block, which is the *page read from this frame* and nothing else."""

    page: str = ""
    page_confidence: float | None = None

    def as_wire(self) -> dict[str, Any]:
        return {"page": self.page, "page_confidence": self.page_confidence}


@dataclass(frozen=True)
class SessionRef:
    """Section 4's ``session`` block.

    ``remaining_model_steps`` is section 29's per-screen budget carried *into* the prompt, so the
    model can see it is near the end rather than discovering it; ``no_progress_count`` is section
    8's repetition signal, which is what makes "try the same control again" refusable on evidence.
    """

    session_id: str = ""
    phase: str = "RUNNING"
    step_index: int = 0
    attempt_count: int = 0
    no_progress_count: int = 0
    remaining_model_steps: int = 0
    goal_deadline_seconds: int | None = None

    def as_wire(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "step_index": int(self.step_index),
            "attempt_count": int(self.attempt_count),
            "no_progress_count": int(self.no_progress_count),
            "remaining_model_steps": int(self.remaining_model_steps),
            "goal_deadline_seconds": self.goal_deadline_seconds,
        }


@dataclass(frozen=True)
class ElementItem:
    """One entry of section 4's element table.

    Carries no pixel.  ``id`` is what a reply names, ``text`` is the client's own printed words,
    ``semantic`` is the project's name for the control and ``kind`` says whether it may be pressed
    at all: ``COMPOSITE_CONTROL`` is an icon whose meaning is its label, ``TEXT_LABEL`` is
    information (a town name, a count) and is never a click target.

    ``executable`` is **tri-state** on purpose.  ``None`` means the frame did not measure it --
    which is the common case for an element table built from a request's plain OCR, and is not the
    same statement as ``False`` ("the frame measured this and it is not pressable").  Folding the
    two together is how the planner's own rule would be broken, since ``parse_plan`` refuses only
    an element *explicitly* marked non-executable.  Unmeasured is written as JSON ``null`` rather
    than as a guess in either direction.
    """

    id: str
    semantic: str = ""
    text: str = ""
    kind: str = ""
    executable: bool | None = None
    area: str = ""

    def as_wire(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.id,
            "semantic": self.semantic,
            "text": self.text,
            "kind": self.kind,
            "executable": None if self.executable is None else bool(self.executable),
        }
        if self.area:
            row["area"] = self.area
        return row

    @property
    def pressable(self) -> bool:
        """Whether a reply may *name* this element as its target.

        Deliberately the same rule ``parse_plan`` applies, because the two must not disagree about
        one table: refused only when the frame **explicitly** said this cannot be pressed.  An
        element whose pressability was never measured is not refused here -- inventing a stricter
        rule in the contract would reject names the planner accepts, and the resulting disagreement
        would be invisible until a live step stopped working.
        """
        return self.executable is not False and self.kind.strip().upper() != "TEXT_LABEL"

    @property
    def reliable(self) -> bool:
        """Whether section 8 calls this a trustworthy target that a box must not go around.

        A **narrower** question than ``pressable``, and the difference is the whole point of
        section 2: "不存在可靠交互区域时，该元素不得作为可执行 CLICK 目标".  A reliable target needs the
        frame to have *positively identified* an interactive area -- ``COMPOSITE_CONTROL``, or an
        explicit ``executable: true``.  A line of OCR text with no measured kind is offerable but
        not identified, so its presence does not make the model's box illegal.

        Reading these as one property would collapse "here is a control you skipped" (section 8's
        refusal) into "here is some text" (not a refusal at all), and every visually-grounded step
        on a screen that printed anything would start being refused.
        """
        if self.kind.strip().upper() == "TEXT_LABEL":
            return False
        return self.executable is True or self.kind.strip().upper() == "COMPOSITE_CONTROL"


@dataclass(frozen=True)
class ElementTable:
    """Section 4's ``elements`` block -- and its own frame identity, which is half of section 5."""

    frame_id: str = ""
    frame_hash: str = ""
    items: tuple[ElementItem, ...] = ()

    @property
    def identity(self) -> FrameIdentity:
        return FrameIdentity(self.frame_id, self.frame_hash)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.items)

    @property
    def reliable(self) -> tuple[ElementItem, ...]:
        return tuple(item for item in self.items if item.reliable)

    def get(self, element_id: str) -> ElementItem | None:
        wanted = str(element_id or "").strip().upper()
        for item in self.items:
            if item.id.upper() == wanted:
                return item
        return None

    def as_wire(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "frame_hash": self.frame_hash,
            "items": [item.as_wire() for item in self.items],
        }


@dataclass(frozen=True)
class ContextBudgetRef:
    """Section 4's ``context_budget`` block.  Stated in the packet so the model knows the window
    it is being read in, and so a ledger row read later shows which window the call was made
    under."""

    max_context_tokens: int = MAX_MODEL_CONTEXT
    max_input_tokens: int = MAX_INPUT_TOKENS
    output_reserve_tokens: int = OUTPUT_RESERVE

    def as_wire(self) -> dict[str, Any]:
        return {
            "max_context_tokens": int(self.max_context_tokens),
            "max_input_tokens": int(self.max_input_tokens),
            "output_reserve_tokens": int(self.output_reserve_tokens),
        }


@dataclass(frozen=True)
class VisualHistory:
    """Section 22's optional block: at most one previous frame, reference only.

    ``grounding_allowed`` is false and there is no setter.  A previous frame is evidence for a
    *comparison* ("what changed between these two"); it is never evidence for where a control is
    now, and section 22 forbids using it for exactly that.
    """

    previous_key_frame: str = ""
    purpose: str = ""
    grounding_allowed: bool = False

    def as_wire(self) -> dict[str, Any]:
        return {
            "previous_key_frame": self.previous_key_frame or None,
            "purpose": self.purpose or None,
            "grounding_allowed": False,
        }


@dataclass(frozen=True)
class UIVenusContextPacketV1:
    """Section 4's packet, field for field.

    Built from evidence the caller already has; pure; writes nothing.  ``as_wire`` is what is
    rendered into the user turn, so the model sees the directive's own structure rather than a
    flattened paraphrase of it.
    """

    identity: Identity = field(default_factory=Identity)
    frame: FrameRef = field(default_factory=FrameRef)
    world: WorldRef = field(default_factory=WorldRef)
    session: SessionRef = field(default_factory=SessionRef)
    elements: ElementTable = field(default_factory=ElementTable)
    allowed_actions: tuple[str, ...] = ()
    last_feedback: Mapping[str, Any] = field(default_factory=dict)
    recent_history: tuple[Mapping[str, Any], ...] = ()
    relevant_knowledge: tuple[Mapping[str, Any], ...] = ()
    failure_context: Mapping[str, Any] = field(default_factory=dict)
    risk: RiskEnvelope = field(default_factory=RiskEnvelope)
    budget: ContextBudgetRef = field(default_factory=ContextBudgetRef)
    visual_history: VisualHistory = field(default_factory=VisualHistory)
    mode: str = MODE_ONLINE

    # ---------------------------------------------------------------- section 5
    def frame_check(self) -> Verdict:
        """Section 5's programmatic consistency check.

        Returns a passing verdict or ``CONTEXT_FRAME_MISMATCH``.  The caller's response to a
        refusal is the directive's: discard this packet, take a fresh capture, rebuild the element
        table, and only then decide whether to ask the model at all.
        """
        code = contract.frame_consistency(self.frame.identity, self.elements.identity)
        if code:
            return refuse(code, stage="FRAME_CONSISTENCY",
                          detail=f"screenshot={self.frame.frame_id or '(none)'}/"
                                 f"{self.frame.frame_hash[:19] or '(none)'} "
                                 f"elements={self.elements.frame_id or '(none)'}/"
                                 f"{self.elements.frame_hash[:19] or '(none)'}")
        return ok("FRAME_CONSISTENCY")

    def missing_required(self) -> list[str]:
        """Section 4's P0 fields that are absent.  Reported, not raised: a caller may still want
        to record *why* it filed nothing."""
        out: list[str] = []
        flat = {
            "frame_id": self.frame.frame_id,
            "frame_hash": self.frame.frame_hash,
            "role_id": self.identity.role_id,
            "goal_id": self.identity.goal_id,
            "page": self.world.page,
            "elements_frame_id": self.elements.frame_id,
            "elements_frame_hash": self.elements.frame_hash,
        }
        for name in REQUIRED_PACKET_FIELDS:
            if not flat.get(name):
                out.append(name)
        return out

    def validate(self) -> Verdict:
        """Everything that must hold *before* the model is asked."""
        if not self.allowed_actions:
            return refuse(contract.PLAN_SCHEMA_INVALID, stage="SCHEMA",
                          detail="allowed_actions is empty: this call would offer the model nothing")
        check = self.frame_check()
        if not check.ok:
            return check
        return ok("SCHEMA")

    def as_wire(self) -> dict[str, Any]:
        """Section 4's field tree, with **all** of its keys, every time.

        The four optional blocks are written empty rather than omitted.  An earlier version dropped
        them when they were empty to save a few tokens; that made ``last_feedback`` absent both when
        there had been no verifier verdict and when the caller had not wired the field at all, and
        the two are opposite facts about the *call*.  Section 2's trimming ladder is about how much
        history travels -- a shorter ``recent_history`` -- not about which keys exist, so a stable
        shape costs ~40 tokens of a 32768 window and buys a packet a reader can trust the shape of.
        """
        return {
            "mode": self.mode,
            "identity": self.identity.as_wire(),
            "frame": self.frame.as_wire(),
            "world": self.world.as_wire(),
            "session": self.session.as_wire(),
            "allowed_actions": list(self.allowed_actions),
            "elements": self.elements.as_wire(),
            "last_feedback": dict(self.last_feedback),
            "recent_history": [dict(row) for row in self.recent_history],
            "relevant_knowledge": [dict(row) for row in self.relevant_knowledge],
            "failure_context": dict(self.failure_context),
            "risk": self.risk.as_wire(),
            "context_budget": self.budget.as_wire(),
            "optional_visual_history": self.visual_history.as_wire(),
        }

    def render(self) -> str:
        """The user turn.  JSON, because the reply is JSON and a table would invite prose."""
        return "This screen's packet:\n" + json.dumps(self.as_wire(), ensure_ascii=False, indent=1)

    @property
    def needs_box(self) -> bool:
        """Whether a reply on this packet could legally use a region at all (sections 8/9).

        Decided by the *frame*, not by the model: a packet with a reliable element has no use for
        a box, and asking for one costs tokens on every call (measured: 29 output tokens on a step
        that could not read it).
        """
        return not self.elements.reliable


# ---------------------------------------------------------------------------- action (section 7)
@dataclass(frozen=True)
class UIVenusSemanticActionV1:
    """Section 7's reply, parsed.  A proposal, never a verdict."""

    decision: str = ""
    action_type: str = ""
    target_element_id: str = ""
    semantic_target: str = ""
    candidate_bbox_norm: tuple[float, float, float, float] | None = None
    expected_page: str = ""
    expected_result: str = ""
    confidence: float = 0.0
    reason: str = ""
    #: ``FRAME_ELEMENT`` or ``UNTRUSTED_CURRENT_FRAME_PROPOSAL``; empty for a step that taps
    #: nothing.  Recorded so "which evidence justified this" is answerable afterwards.
    basis: str = ""
    source: str = "LOCAL_GUI_MODEL"

    @property
    def taps(self) -> bool:
        return self.decision == "EXECUTE" and self.action_type not in ("", "OBSERVE")

    @property
    def is_complete_claim(self) -> bool:
        """Section 11: COMPLETE is a claim about the goal, and only the Verifier can confirm it."""
        return self.decision == "COMPLETE"

    @property
    def identity_text(self) -> str:
        """What is being pressed, in words -- the element's own text when it named one.

        Used by the risk gate, which is a question about the *thing acted on*; a gate that only
        read ``action_type`` would let "CLICK_ELEMENT" mean both "close a popup" and "start a
        rally".
        """
        return self.semantic_target or self.target_element_id

    def as_wire(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "action_type": self.action_type,
            "target_element_id": self.target_element_id or None,
            "semantic_target": self.semantic_target,
            "candidate_bbox_norm": (
                list(self.candidate_bbox_norm) if self.candidate_bbox_norm else None
            ),
            "expected_page": self.expected_page,
            "expected_result": self.expected_result,
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
        }

    def as_row(self, *, trace_id: str = "", page_key: str = "", goal_id: str = "") -> dict[str, Any]:
        return {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "schema": SCHEMA_SEMANTIC_ACTION,
            "mode": MODE_ONLINE,
            "trace_id": trace_id,
            "page_key": page_key,
            "goal_id": goal_id or "",
            "decision": self.decision,
            "action_type": self.action_type,
            "target_element_id": self.target_element_id,
            "semantic_target": self.semantic_target,
            "basis": self.basis,
            "proposed_region_untrusted": (
                list(self.candidate_bbox_norm) if self.candidate_bbox_norm else None
            ),
            "expected_page": self.expected_page,
            "expected_result": self.expected_result,
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason[:contract.REASON_MAX_CHARS],
            "source": self.source,
        }


@dataclass(frozen=True)
class ActionParse:
    """The result of reading a reply: an action, or the reason there is none."""

    action: UIVenusSemanticActionV1 | None = None
    error: str = ""
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.action is not None


def action_schema(*, needs_box: bool = True, allowed_actions: Sequence[str] = ACTION_TYPES) -> dict[str, Any]:
    """Section 7's reply contract, as JSON Schema.

    The canonical, complete shape.  ``ui_planner.response_schema`` is a *projection* of this --
    the same protocol with the token-budget measured out of it (a nested ``action`` object, the
    box requested only when the frame can use one).  Both are legal; this one is the definition,
    and ``tests/test_ui_venus_online.py`` asserts the projection is a subset of it so the two
    cannot describe different protocols.

    ``additionalProperties: False`` is the part the prompt cannot do: the deployment honours it in
    the grammar, which is what turns "do not transport pixels" from an instruction into a refusal.
    """
    properties: dict[str, Any] = {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "action_type": {
            "type": "string",
            "enum": [a for a in allowed_actions if a in ACTION_TYPES] or list(ACTION_TYPES),
        },
        "target_element_id": {"type": ["string", "null"]},
        "semantic_target": {"type": "string", "maxLength": 60},
        "expected_page": {"type": "string", "maxLength": 40},
        "expected_result": {"type": "string", "maxLength": 60},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": contract.REASON_MAX_CHARS},
    }
    if needs_box:
        properties[contract.VISION_BOX_KEY] = {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "minItems": 4,
            "maxItems": 4,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": ["decision", "action_type", "reason"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------- prompt (section 12)
SYSTEM_PROMPT = """You are the UI action planner of a screenshot-driven game automation agent.

You are shown the CURRENT screenshot of one game screen. Look at it.

You are also given: the goal the Global Scheduler has ALREADY chosen, the elements ACTUALLY
measured on this screen right now (each with an id, the words the client itself printed on it, and
whether it may be pressed), the actions you are allowed to return, the last verifier verdict, and
how much of this session you are being shown.

Hard rules:
1. The Global Scheduler has already selected the goal. Do not select another goal.
2. Choose only ONE next action. Prefer an existing current-frame element_id.
3. Never invent elements. Never use old coordinates. Never infer hidden state without evidence.
4. If evidence is insufficient: return OBSERVE.
5. If this page cannot advance the current goal: return DEFER.
6. If the capability does not exist: return BLOCKED.
7. COMPLETE is only a claim. The Verifier decides actual completion.
8. You may only name an id from the element table, and only click one that is not marked
   unusable. When the table offers no usable control, you may instead name what you are aiming at
   in words and give "candidate_bbox_norm": four numbers [x, y, width, height], each between 0 and
   1, measured as a fraction of the image. That box is a PROPOSAL only: it is re-checked against
   the live screen and refused if nothing real is there. Never output pixel coordinates.
9. Never propose anything that spends money, gems, items or speedups unless the goal is exactly
   that.
10. Reply with JSON only, in exactly the shape you are asked for. The server enforces the key set
    and the length caps, so an extra key is refused rather than ignored. Do not write a plan, a
    rationale paragraph or a list of alternatives.
11. Prefer certainty over action. Do not compensate for missing evidence with confidence."""


def render_user_turn(packet: UIVenusContextPacketV1) -> str:
    """The packet, as the user turn."""
    return packet.render()


# ---------------------------------------------------------------------------- parsing (section 7)
def parse_action(raw: str, *, elements: ElementTable | None = None) -> ActionParse:
    """Read one reply into an action, or say exactly why it cannot be read.

    This is the *shape* reader only: sections 8-13's rules are ``validate_action``'s job, and
    keeping them apart is what lets the two refusal vocabularies stay meaningful -- "this is not
    JSON" and "this names an element this frame does not have" are different failures with
    different responses.
    """
    text = str(raw or "").strip()
    if not text:
        return ActionParse(error=contract.PLAN_NOT_JSON, raw="")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return ActionParse(error=f"{contract.PLAN_NOT_JSON}: {exc.msg}", raw=text[:400])
    if not isinstance(payload, Mapping):
        return ActionParse(error=contract.PLAN_NOT_AN_OBJECT, raw=text[:400])

    geometry = contract.find_forbidden_geometry(payload)
    if geometry:
        return ActionParse(error=f"{contract.PLAN_GEOMETRY_TRANSPORTED}: {geometry}", raw=text[:400])

    decision = str(payload.get("decision") or "").strip().upper()
    if decision not in DECISIONS:
        return ActionParse(
            error=f"{contract.PLAN_DECISION_UNKNOWN}: {decision[:40]!r}", raw=text[:400])

    reason = str(payload.get("reason") or "").strip()
    bad_reason = reason_violation(reason)
    if bad_reason:
        return ActionParse(error=bad_reason, raw=text[:400])

    # The flat shape is the contract's; the nested one is what ``ui_planner`` requests today.
    # Reading both is tolerant parsing of one protocol, not two -- and the nested shape is the
    # one observed to work against the deployed server.
    nested = payload.get("action") if isinstance(payload.get("action"), Mapping) else {}
    action_type = str(
        payload.get("action_type") or nested.get("type") or ""
    ).strip().upper()
    target_id = str(
        payload.get("target_element_id") or nested.get("target_element_id") or ""
    ).strip()
    semantic = str(
        payload.get("semantic_target") or nested.get("semantic_target") or ""
    ).strip()

    # ``expected`` may be flat or nested, with the same tolerance.
    expected = payload.get("expected") if isinstance(payload.get("expected"), Mapping) else {}
    expected_page = str(payload.get("expected_page") or expected.get("page") or "").strip()
    expected_result = str(payload.get("expected_result") or expected.get("result") or "").strip()

    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    box, box_error = read_box(payload.get(contract.VISION_BOX_KEY))
    if box_error:
        return ActionParse(error=box_error, raw=text[:400])

    action = UIVenusSemanticActionV1(
        decision=decision,
        action_type=action_type,
        target_element_id=target_id,
        semantic_target=semantic,
        candidate_bbox_norm=box,
        expected_page=expected_page,
        expected_result=expected_result,
        confidence=confidence,
        reason=reason,
        basis="",
    )
    if decision == "EXECUTE":
        action = _stamp_basis(action, elements)
    return ActionParse(action=action, raw=text[:400])


def _stamp_basis(
    action: UIVenusSemanticActionV1, elements: ElementTable | None
) -> UIVenusSemanticActionV1:
    """Fill in which evidence channel this EXECUTE used.

    Left empty for a non-EXECUTE step: "which evidence justified the tap" is not a question a step
    that taps nothing answers, and stamping ``FRAME_ELEMENT`` on an OBSERVE would make the ledger
    read as if a frame had justified something.
    """
    if action.target_element_id and elements is not None and elements.get(action.target_element_id):
        basis = "FRAME_ELEMENT"
    elif action.candidate_bbox_norm is not None:
        basis = contract.UNTRUSTED_PROPOSAL
    else:
        basis = ""
    return UIVenusSemanticActionV1(
        decision=action.decision, action_type=action.action_type,
        target_element_id=action.target_element_id, semantic_target=action.semantic_target,
        candidate_bbox_norm=action.candidate_bbox_norm, expected_page=action.expected_page,
        expected_result=action.expected_result, confidence=action.confidence,
        reason=action.reason, basis=basis, source=action.source,
    )


# ---------------------------------------------------------------------------- grounding (section 10)
#: What the local grounder may conclude.  Section 10's list, one name per check.
GROUNDING_NO_REGION = "GROUNDING_NO_REGION"
GROUNDING_TEXT_LABEL = "GROUNDING_TEXT_LABEL"
GROUNDING_READOUT_TEXT = "GROUNDING_READOUT_TEXT"
GROUNDING_STALE_FRAME = "GROUNDING_STALE_FRAME"

#: Region kinds that are *information*, not controls.  A box over one of these is refused: the
#: directive names "pure text label", "resource count" and "HUD status text" separately because
#: they are the three things a screenshot-only model most often mistakes for buttons.
READOUT_KINDS: tuple[str, ...] = ("TEXT_LABEL", "RESOURCE_COUNT", "HUD_STATUS")


def local_ground(
    box: tuple[float, float, float, float],
    *,
    regions: Iterable[Mapping[str, Any]] = (),
    elements: ElementTable | None = None,
    frame_now: FrameIdentity | None = None,
    frame_then: FrameIdentity | None = None,
    excluded_texts: Iterable[str] = (),
) -> tuple[dict[str, Any] | None, str]:
    """Re-check a proposed region against the **current** frame (section 10).

    Returns ``(region, "")`` when the frame really drew something pressable under the box, else
    ``(None, reason)``.  The region returned is the *frame's own*, not the model's -- the box only
    decided which of this frame's regions to look at.

    What this proves is narrow and the directive says so: *"OpenCV / local grounding 只能证明当前帧
    确实存在这个视觉目标，不能证明点这个一定正确"*.  Whether the press is the right thing to do is
    the Verifier's question.  A grounder that also judged correctness would be a second Verifier.
    """
    if frame_now is not None and frame_then is not None and frame_now.complete and frame_then.complete:
        if frame_now.frame_hash != frame_then.frame_hash:
            return None, GROUNDING_STALE_FRAME
    # Containment is delegated to the project's one existing implementation rather than restated.
    # ``grounded_region`` already answers "does a region this frame drew contain this point", and a
    # second copy of that rule here would be a second answer to the same question -- the failure
    # mode the constitution names when it forbids wrapping a fixed position in a helper.
    from . import unknown_advisor

    probe = unknown_advisor.Advice(
        request_id="", unknown_type=unknown_advisor.UNKNOWN_CONTROL,
        candidate_semantics=(), proposed_action="", expected_result="", uncertainty="",
        target_bbox={
            "x_norm": box[0], "y_norm": box[1], "w_norm": box[2], "h_norm": box[3],
        },
    )
    region = unknown_advisor.grounded_region(probe, regions)
    if region is None:
        return None, GROUNDING_NO_REGION
    # The three exclusions section 10 names, layered on top of containment: a pure text label, a
    # resource count and HUD status text are all *drawn*, so containment alone would admit them.
    inner = region.get("box_norm") if isinstance(region.get("box_norm"), Mapping) else region
    kind = str(region.get("kind") or region.get("element_kind") or "").strip().upper()
    if kind in READOUT_KINDS:
        return None, GROUNDING_READOUT_TEXT
    text = str(region.get("text") or "").strip()
    excluded = {str(item).strip() for item in excluded_texts if str(item).strip()}
    if text and text in excluded:
        return None, GROUNDING_READOUT_TEXT
    element = elements.get(str(inner.get("id") or region.get("id") or "")) \
        if elements is not None else None
    if element is not None and element.kind.strip().upper() in READOUT_KINDS:
        return None, GROUNDING_TEXT_LABEL
    return dict(region), ""


# ---------------------------------------------------------------------------- validator (section 13)
def validate_action(
    action: UIVenusSemanticActionV1,
    *,
    packet: UIVenusContextPacketV1,
    frame_now: FrameIdentity | None = None,
    claim_goal: str = "",
    claim_role: str = "",
    ground: Any = None,
    ground_regions: Iterable[Mapping[str, Any]] | None = None,
    excluded_texts: Iterable[str] = (),
) -> Verdict:
    """Section 13's chain, in the directive's own order.

    ``JSON parse -> schema -> goal scope -> role scope -> allowed_actions -> element existence ->
    frame consistency -> risk/spend -> grounding``

    ``claim_goal`` / ``claim_role`` are what the *reply* asserted about which goal or role it is
    serving.  They exist because a model can only violate scope by saying so -- a reply that stays
    inside the schema cannot name another goal -- so the check has a subject rather than being a
    formality.

    ``ground`` is an optional callable ``(box, regions) -> (region|None, reason)``; when omitted,
    ``local_ground`` is used with ``ground_regions``.  A bbox that grounds to nothing is refused
    with ``UNKNOWN_GROUNDING_FAILED`` and never reaches the executor.
    """
    # -- schema ---------------------------------------------------------------------------------
    if action.decision not in DECISIONS:
        return refuse(contract.PLAN_DECISION_UNKNOWN, stage="SCHEMA",
                      detail=f"decision={action.decision[:40]!r}")
    bad_reason = reason_violation(action.reason)
    if bad_reason:
        return refuse(bad_reason, stage="SCHEMA", detail=f"{len(action.reason)} chars")
    if action.decision == "EXECUTE":
        if action.action_type not in ACTION_TYPES:
            return refuse(contract.PLAN_ACTION_NOT_ALLOWED, stage="SCHEMA",
                          detail=f"action_type={action.action_type[:40]!r}")
        if not (action.target_element_id or action.semantic_target or action.candidate_bbox_norm):
            return refuse(contract.PLAN_EXECUTE_WITHOUT_TARGET, stage="SCHEMA",
                          detail="EXECUTE with no element id, no semantic target and no box")

    # -- goal scope -----------------------------------------------------------------------------
    if claim_goal and packet.identity.goal_id and str(claim_goal) != packet.identity.goal_id:
        return refuse(contract.PLAN_GOAL_SCOPE_VIOLATION, stage="GOAL_SCOPE",
                      detail=f"claimed {claim_goal!r}, scheduled {packet.identity.goal_id!r}")

    # -- role scope -----------------------------------------------------------------------------
    if claim_role and packet.identity.role_id and str(claim_role) != packet.identity.role_id:
        return refuse(contract.PLAN_ROLE_SCOPE_VIOLATION, stage="ROLE_SCOPE",
                      detail=f"claimed {claim_role!r}, scheduled {packet.identity.role_id!r}")

    # -- allowed actions ------------------------------------------------------------------------
    if action.decision == "EXECUTE" and packet.allowed_actions:
        if action.action_type not in packet.allowed_actions:
            return refuse(contract.PLAN_ACTION_NOT_ALLOWED, stage="ALLOWED_ACTIONS",
                          detail=f"{action.action_type!r} not in {list(packet.allowed_actions)}")

    # -- element existence (section 8) ----------------------------------------------------------
    if action.decision == "EXECUTE":
        if action.target_element_id:
            element = packet.elements.get(action.target_element_id)
            if element is None:
                return refuse(contract.PLAN_TARGET_NOT_ON_THIS_FRAME, stage="ELEMENT_EXISTENCE",
                              detail=f"{action.target_element_id!r} not in "
                                     f"{list(packet.elements.ids)}")
            if not element.pressable:
                return refuse(contract.PLAN_TARGET_IS_NOT_A_CONTROL, stage="ELEMENT_EXISTENCE",
                              detail=f"{element.id} is {element.kind or '?'} "
                                     f"(executable={element.executable})")
        elif action.candidate_bbox_norm is not None and packet.elements.reliable:
            # Section 8: a usable element existed and the model went around it.  Refused rather
            # than accepted, because accepting it would make the element table decoration and
            # would lose the audit trail that ties a plan to a control this frame really drew.
            return refuse(contract.PLAN_BBOX_UNNECESSARY, stage="ELEMENT_EXISTENCE",
                          detail=f"{len(packet.elements.reliable)} reliable element(s) were offered")

    # -- frame consistency (section 5's second gate) ---------------------------------------------
    #
    # ``frame_gate`` rather than ``packet.frame_check``: this stage asks "did the frame move under
    # us", and the answer is only knowable when both identities were measured.  The packet's own
    # ``validate`` keeps the strict form -- it built both halves itself, so an incomplete pair there
    # is a bug -- while a validator reading a packet it did not build must not turn "nobody
    # measured it" into "these are two different frames".
    if frame_now is not None:
        then = packet.frame.identity
        if then.complete and frame_now.complete and frame_now.frame_hash != then.frame_hash:
            return refuse(contract.PLAN_FRAME_STALE, stage="FRAME_CONSISTENCY",
                          detail=f"packet {then.frame_hash[:19]} vs now {frame_now.frame_hash[:19]}")
    frame_check = frame_gate(packet.frame.identity, packet.elements.identity)
    if not frame_check.ok:
        return frame_check

    # -- risk / spend (section 25) ---------------------------------------------------------------
    if action.decision == "EXECUTE":
        identity = action.identity_text
        if action.target_element_id:
            element = packet.elements.get(action.target_element_id)
            if element is not None:
                identity = " ".join(filter(None, (element.text, element.semantic, identity)))
        permitted, code = packet.risk.permits(action.action_type, identity=identity)
        if not permitted:
            return refuse(code, stage="RISK_SPEND", detail=f"identity={identity[:80]!r}")

    # -- grounding (section 10) ------------------------------------------------------------------
    #
    # Run only when the caller can supply this frame's own regions.  A caller that cannot is not
    # silently passed: the verdict says grounding was *deferred*, because in this project the link
    # that actually stops the tap is the runtime's own ``justified_point``, and a validator that
    # pretended to have checked a frame it never saw would be the worst of the three options.
    if action.decision == "EXECUTE" and action.candidate_bbox_norm is not None:
        if callable(ground) or ground_regions is not None:
            box = action.candidate_bbox_norm
            if callable(ground):
                region, reason = ground(box, ground_regions or ())
            else:
                region, reason = local_ground(
                    box,
                    regions=ground_regions or (),
                    elements=packet.elements,
                    frame_now=frame_now,
                    frame_then=packet.frame.identity if frame_now is not None else None,
                    excluded_texts=excluded_texts,
                )
            if region is None:
                return refuse(contract.UNKNOWN_GROUNDING_FAILED, stage="GROUNDING", detail=reason)
            grounding = f"grounded:{CURRENT_FRAME_VERIFIED_REGION}"
        else:
            grounding = "deferred:the runtime grounds this against its own fresh frame"
    else:
        grounding = ""

    # -- what the caller must still not do --------------------------------------------------------
    #
    # A COMPLETE reply is admitted here as a *claim* and nothing else.  Section 11 is explicit that
    # it "只能转换为 MODEL_COMPLETE_CLAIM" and that the Goal Verifier decides.  The verdict says so
    # rather than leaving the caller to remember.
    stage = "COMPLETE_CLAIM" if action.is_complete_claim else ""
    return Verdict(True, MODEL_COMPLETE_CLAIM if action.is_complete_claim else "", stage, grounding)


# ---------------------------------------------------------------------------- section 5 / 28
def frame_gate(screenshot: FrameIdentity, elements: FrameIdentity) -> Verdict:
    """Section 5 for a call site that may not have *both* identities measured.

    ``UIVenusContextPacketV1.frame_check`` is the contract verbatim and refuses an incomplete pair,
    which is right for a packet this module built -- it built both halves itself.  A call site that
    received a frame *path* from someone else may legitimately be unable to measure one side, and
    there is a real difference between the two states::

        same id, same hash      -> consistent
        same id, other hash     -> the slot was re-captured: refuse (CONTEXT_FRAME_MISMATCH)
        different id            -> refuse (CONTEXT_FRAME_MISMATCH)
        either side unmeasured  -> cannot be shown consistent, and cannot be shown *inconsistent*

    The last case returns a passing verdict with the reason recorded, rather than being folded into
    the refusal.  Folding it in would make "nobody measured this" and "these are two different
    frames" the same fact -- and in this project the unmeasured case is the common one, because a
    request stores a frame *path* and retention may have pruned the file.  The frame still travels
    with the call, so a picture that cannot be read fails loudly at the model client instead.
    """
    if screenshot.complete and elements.complete:
        code = contract.frame_consistency(screenshot, elements)
        if code:
            return refuse(code, stage="FRAME_CONSISTENCY",
                          detail=f"screen={screenshot.frame_id}/{screenshot.frame_hash[:19]} "
                                 f"elements={elements.frame_id}/{elements.frame_hash[:19]}")
        return ok("FRAME_CONSISTENCY")
    missing = []
    if not screenshot.complete:
        missing.append("screenshot")
    if not elements.complete:
        missing.append("elements")
    return Verdict(True, contract.PLAN_FRAME_INCOMPLETE, "FRAME_CONSISTENCY",
                   f"could not measure {' and '.join(missing)}: assumed neither match nor mismatch")


#: Section 28's identity inputs, in the order they are joined.  Named as a tuple so a report can
#: state what an UNKNOWN identity is made of without reading the join below.
IDENTITY_PARTS: tuple[str, ...] = ("goal_id", "page", "semantic", "state_signature")


def unknown_state_identity(
    *, goal_id: str, page: str, semantic: str = "", state_signature: str = ""
) -> str:
    """Section 28's ``UnknownStateIdentity``: what makes two UNKNOWN encounters *the same one*.

    The directive is explicit that a screenshot hash is not enough::

        不能只靠 screenshot hash 判断"这是同一个UNKNOWN"
        至少使用 goal_id / page / semantic target / relevant state signature
        pHash 只能用于视觉相似辅助 —— 不能 pHash 近似 -> 直接复用动作

    So the identity is built from the four things that actually decide whether an action can be
    reused: which goal wanted it, which screen it was on, which control it aimed at, and the
    relevant slice of the world state.  A pHash is *not* an input, and ``phash_is_sufficient``
    exists to say so in code rather than only here.
    """
    parts = [str(goal_id or "").strip(), str(page or "").strip(),
             str(semantic or "").strip(), str(state_signature or "").strip()]
    return "|".join(parts)


def phash_is_sufficient(similar: bool) -> bool:
    """Always ``False``.  Section 28: a visually similar frame does not license a recorded action.

    Takes an argument and ignores it, so the call site reads as a decision being made, and so the
    answer to "may this near-identical screenshot reuse the old tap" is a function a reviewer can
    grep.  pHash may *narrow* the search -- it is how the offline pass groups frames -- but the
    reuse decision itself is ``unknown_state_identity``'s.
    """
    return False


# ---------------------------------------------------------------------------- ledger (section 30)
class OnlineLedger(Ledger):
    """This mode's ledger.  Independent file, independent row shape (section 30).

    Records the accepted action *and* every refusal: the refusals are the interesting half, since
    "the model proposed a control the frame does not have" is a finding about the model and a
    ledger that only kept successes could not state it.
    """

    PATH = ONLINE_LEDGER_PATH

    def record_action(
        self,
        action: UIVenusSemanticActionV1,
        *,
        verdict: Verdict,
        trace_id: str = "",
        page_key: str = "",
        goal_id: str = "",
        model_call: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = action.as_row(trace_id=trace_id, page_key=page_key, goal_id=goal_id)
        row["verdict"] = verdict.as_row()
        row["admitted"] = bool(verdict.ok)
        if model_call:
            row["model_call"] = dict(model_call)
        self.append(row)
        return row

    def record_refusal(
        self, *, code: str, stage: str, detail: str = "", trace_id: str = "",
        page_key: str = "", goal_id: str = "", raw: str = "",
    ) -> dict[str, Any]:
        row = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "schema": SCHEMA_SEMANTIC_ACTION,
            "mode": MODE_ONLINE,
            "trace_id": trace_id,
            "page_key": page_key,
            "goal_id": goal_id,
            "admitted": False,
            "decision": "REFUSED",
            "verdict": refuse(code, stage=stage, detail=detail).as_row(),
            "raw": str(raw)[:300],
        }
        self.append(row)
        return row


# ---------------------------------------------------------------------------- counting
def count_refusals(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Tally refusals by the contract's own code, folding the legacy spellings in.

    ``ui_planner`` predates this contract and its refusal strings are pinned by 14 tests; folding
    happens here rather than by rewriting that module, so an old row and a new row count in the
    same column instead of looking like two different problems.
    """
    out: dict[str, int] = {}
    for row in rows:
        if row.get("admitted"):
            continue
        verdict = row.get("verdict") if isinstance(row.get("verdict"), Mapping) else {}
        code = canonical_code(verdict.get("code") or row.get("error") or "")
        if not code:
            continue
        out[code] = out.get(code, 0) + 1
    return out


def admitted_rate(rows: Iterable[Mapping[str, Any]]) -> float | None:
    """Admitted / total.  ``None`` when nothing was recorded: "no attempts" and "all refused" are
    opposite facts and the same number."""
    total = 0
    admitted = 0
    for row in rows:
        total += 1
        if row.get("admitted"):
            admitted += 1
    if total <= 0:
        return None
    return round(admitted / total, 4)


__all__ = [
    "ActionParse", "ContextBudgetRef", "ElementItem", "ElementTable", "FrameRef",
    "GROUNDING_NO_REGION", "GROUNDING_READOUT_TEXT", "GROUNDING_STALE_FRAME",
    "GROUNDING_TEXT_LABEL", "IDENTITY_PARTS", "Identity", "ONLINE_LEDGER_PATH", "OVERLAY_FLAG",
    "OnlineLedger", "READOUT_KINDS", "REQUIRED_PACKET_FIELDS", "SCHEMA_CONTEXT_PACKET",
    "SCHEMA_SEMANTIC_ACTION", "SYSTEM_PROMPT", "SessionRef", "UIVenusContextPacketV1",
    "UIVenusSemanticActionV1", "VisualHistory", "WorldRef", "action_schema", "admitted_rate",
    "count_refusals", "frame_gate", "local_ground", "parse_action", "phash_is_sufficient",
    "render_user_turn", "unknown_state_identity", "validate_action",
]
