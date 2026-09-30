"""OFFLINE_LEARNING: the packet built from past episodes, and the candidates it may produce.

Operator directive 2026-10-01, sections 16-22, plus the section-30 independence rule.

    OfflineUIVenusLearningPacketV1  section 16  the evidence, with its provenance
    OfflineLearningCandidateV1      sections 18-20  what should be learned from it
    validate_learning_packet / validate_candidate  sections 17, 18, 21

The question this mode answers is not "where do I click now" -- the directive says so twice -- it
is: *"从过去这些真实 Episode 中，V2 应该学会什么？"*.  Everything here follows from that one
substitution:

* **Freshness stops mattering; traceability starts.**  Section 17 replaces the online rule (a
  frame must be current) with a different one: every frame must carry an ``episode_id`` and a
  ``frame_id``, every action must trace to the episode and step it came from, every verifier
  result must be reachable.  A conclusion here has to be able to answer "which episode, which
  frame, which action, which verdict" -- because nobody can re-watch the screen it came from.
* **Nothing is a fact.**  Section 21: "模型分析 ≠ 游戏事实; 模型生成 Skill ≠ Stable Skill;
  confidence=0.99 ≠ 已验证".  Every output starts at ``CANDIDATE`` and the only route out is
  Offline Replay -> Shadow -> Live Verifier -> PromotionGate, which lives elsewhere and is not
  bypassable from here.
* **No ``EXECUTE``.**  Section 18: offline output may only be the seven candidate kinds.  The
  candidate type has no ``decision`` field at all, and ``refuse_offline_execute`` names the
  refusal for a reply that tries to answer the online question anyway -- a model asked about the
  past is not allowed to volunteer a tap.

The device is out of reach by construction
------------------------------------------
``LearningConstraints`` asserts ``no_device_actions`` / ``no_production_write`` /
``no_direct_promotion`` / ``no_absolute_coordinate_learning``, all ``True``, with no setter.  This
mode reads files and writes candidate JSON.  It holds no client, opens no socket, and cannot tap
anything: the offline pass runs at night precisely because the device must not be touched.

How this relates to ``offline_learning``
----------------------------------------
``offline_learning`` already does the part that needs no model -- pHash the frame stores, cluster
them, write the medoid of each group as a candidate.  That module stays, unchanged, and this one
types its output through ``candidate_from_cluster``.  What this module adds is the *contract*: the
packet shape (``packet_from_episodes``), the candidate vocabulary, the traceability validator, and
the reply schema for the case where a model is asked to interpret a cluster -- which, per the
directive's section 21, is offline and never on the device's critical path.
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
    MODE_OFFLINE,
    OUTPUT_RESERVE,
    Ledger,
    Verdict,
    ok,
    reason_violation,
    refuse,
)

SCHEMA_LEARNING_PACKET = "OfflineUIVenusLearningPacketV1"
SCHEMA_LEARNING_CANDIDATE = "OfflineLearningCandidateV1"
OFFLINE_LEDGER_PATH = Path("learning/ui_venus_offline.jsonl")

#: Section 18's candidate vocabulary.  Exactly these seven; ``EXECUTE`` is not among them and is
#: not a value of any field here.
CANDIDATE_PAGE = "CANDIDATE_PAGE"
CANDIDATE_UI_SEMANTIC = "CANDIDATE_UI_SEMANTIC"
FAILURE_PATTERN_CANDIDATE = "FAILURE_PATTERN_CANDIDATE"
CANDIDATE_STEP = "CANDIDATE_STEP"
CANDIDATE_SKILL = "CANDIDATE_SKILL"
SKILL_REPAIR_CANDIDATE = "SKILL_REPAIR_CANDIDATE"
NAVIGATION_EDGE_CANDIDATE = "NAVIGATION_EDGE_CANDIDATE"
ANALYSIS_TYPES: tuple[str, ...] = (
    CANDIDATE_PAGE, CANDIDATE_UI_SEMANTIC, FAILURE_PATTERN_CANDIDATE, CANDIDATE_STEP,
    CANDIDATE_SKILL, SKILL_REPAIR_CANDIDATE, NAVIGATION_EDGE_CANDIDATE,
)

#: Every offline output begins here (section 21) and nothing in this module can move it.
STATUS_CANDIDATE = "CANDIDATE"

#: Section 18's own prohibition, as a refusal rather than a rule in prose.
OFFLINE_DECISION_EXECUTE_FORBIDDEN = "OFFLINE_DECISION_EXECUTE_FORBIDDEN"

#: Section 24's shared-learning marker.  A packet that learns across roles must say so, because
#: runtime state never crosses roles while *page semantics* may.
ROLE_SCOPE_SHARED = "SHARED_KNOWLEDGE"

#: Section 18's ``required_validation`` vocabulary for offline candidates.  ``REOBSERVE`` and
#: ``LIVE_NAVIGATION`` are the page/navigation ones; the rest are the promotion chain.
VALIDATION_REOBSERVE = "REOBSERVE"
VALIDATION_LIVE_NAVIGATION = "LIVE_NAVIGATION"
VALIDATION_REPLAY = "REPLAY"
VALIDATION_SHADOW = "SHADOW"
VALIDATION_LIVE_VERIFIER = "LIVE_VERIFIER"
REQUIRED_VALIDATION_KINDS: tuple[str, ...] = (
    VALIDATION_REOBSERVE, VALIDATION_LIVE_NAVIGATION, VALIDATION_REPLAY, VALIDATION_SHADOW,
    VALIDATION_LIVE_VERIFIER,
)

#: The one validation every candidate must ask for, because a candidate with no path to reality is
#: a file that will sit in a folder forever.
VALIDATION_MUST_INCLUDE: tuple[str, ...] = (
    VALIDATION_REOBSERVE, VALIDATION_LIVE_NAVIGATION, VALIDATION_REPLAY, VALIDATION_SHADOW,
    VALIDATION_LIVE_VERIFIER,
)

#: Every geometry key, including the one channel the *online* contract opens.  Offline has no
#: region channel at all: its outputs are knowledge (section 18's seven candidate kinds), and a
#: region recorded as knowledge is a coordinate becoming a learned artefact -- which section 30 and
#: this project's constitution both forbid.  ``contract.find_forbidden_geometry`` skips
#: ``candidate_bbox_norm`` on purpose (online may propose one); the exemption is not inherited.
GEOMETRY_KEYS_FORBIDDEN_OFFLINE: tuple[str, ...] = (
    contract.VISION_BOX_KEY,
) + contract.FORBIDDEN_GEOMETRY_KEYS


def find_any_geometry(node: Any, path: str = "") -> str:
    """The first geometry key anywhere in a reply, box included, or ``""``.

    The difference from the shared scan is one exemption, and it is the whole reason this exists:
    a reply of the shape ``{"payload": {"candidate_bbox_norm": [0.1, 0.2, 0.3, 0.4]}}`` would pass
    the shared scan and land verbatim in a candidate's body, because ``payload`` is an open object
    (the seven analysis types have genuinely different bodies).  Strict here rather than open,
    because offline learning is the one place a position could survive as knowledge.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key).strip().lower()
            if name in GEOMETRY_KEYS_FORBIDDEN_OFFLINE:
                return f"{path}.{name}".lstrip(".")
            found = find_any_geometry(value, f"{path}.{name}".lstrip("."))
            if found:
                return found
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found = find_any_geometry(value, f"{path}[{index}]")
            if found:
                return found
    return ""


#: Refusals this mode adds.  Prefixed ``OFFLINE_`` so a folded ledger cannot confuse them with the
#: planner's or the repair's.
OFFLINE_NOT_JSON = "OFFLINE_NOT_JSON"
OFFLINE_NOT_AN_OBJECT = "OFFLINE_NOT_AN_OBJECT"
OFFLINE_SCHEMA_INVALID = "OFFLINE_SCHEMA_INVALID"
OFFLINE_ANALYSIS_TYPE_UNKNOWN = "OFFLINE_ANALYSIS_TYPE_UNKNOWN"
OFFLINE_STATUS_NOT_CANDIDATE = "OFFLINE_STATUS_NOT_CANDIDATE"
OFFLINE_NO_EVIDENCE_REFS = "OFFLINE_NO_EVIDENCE_REFS"
OFFLINE_EVIDENCE_NOT_IN_PACKET = "OFFLINE_EVIDENCE_NOT_IN_PACKET"
OFFLINE_FRAME_WITHOUT_IDENTITY = "OFFLINE_FRAME_WITHOUT_IDENTITY"
OFFLINE_ACTION_WITHOUT_SOURCE = "OFFLINE_ACTION_WITHOUT_SOURCE"
OFFLINE_VERIFIER_UNTRACEABLE = "OFFLINE_VERIFIER_UNTRACEABLE"
OFFLINE_NO_REQUIRED_VALIDATION = "OFFLINE_NO_REQUIRED_VALIDATION"
OFFLINE_VALIDATION_UNKNOWN = "OFFLINE_VALIDATION_UNKNOWN"
OFFLINE_GEOMETRY_TRANSPORTED = "OFFLINE_GEOMETRY_TRANSPORTED"

CANDIDATE_REASON_MAX_CHARS = 120
SEMANTIC_MAX_CHARS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------- evidence (sections 16-17)
@dataclass(frozen=True)
class EvidenceFrame:
    """One historical frame (section 16's ``frames``).

    ``frame_id`` is required here even though the online packet's frame identity is checked for
    *freshness*: the offline rule is different on purpose (section 17), and a frame that cannot be
    named is a frame whose conclusion cannot be audited.
    """

    frame_id: str = ""
    screenshot: str = ""
    page: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {"frame_id": self.frame_id, "screenshot": self.screenshot, "page": self.page}


@dataclass(frozen=True)
class EvidenceAction:
    """One historical action (section 16's ``actions``).  ``step`` is its index in the episode, and
    it is what makes "this conclusion came from that step" answerable."""

    step: int = 0
    action: str = ""
    semantic_target: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "step": int(self.step),
            "action": self.action,
            "semantic_target": self.semantic_target,
        }


@dataclass(frozen=True)
class EvidenceVerifier:
    """The verdict on one episode (section 16's ``verifier``).  The truth authority, as always."""

    outcome: str = ""
    reason: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "reason": self.reason}


@dataclass(frozen=True)
class EvidenceEpisode:
    """One episode: frames, actions, and the verdict (section 16's ``episodes[]``).

    ``role_id`` and ``goal_id`` travel with it because offline learning is where two roles' evidence
    may legitimately be compared -- section 24 allows sharing *page semantics*, and a cluster of
    one screen seen by three roles is exactly the evidence that makes a shared page candidate.
    """

    episode_id: str = ""
    role_id: str = ""
    goal_id: str = ""
    frames: tuple[EvidenceFrame, ...] = ()
    actions: tuple[EvidenceAction, ...] = ()
    verifier: EvidenceVerifier = field(default_factory=EvidenceVerifier)

    def as_wire(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "role_id": self.role_id,
            "goal_id": self.goal_id,
            "frames": [f.as_wire() for f in self.frames],
            "actions": [a.as_wire() for a in self.actions],
            "verifier": self.verifier.as_wire(),
        }

    def frame_ids(self) -> set[str]:
        return {f.frame_id for f in self.frames if f.frame_id}


@dataclass(frozen=True)
class LearningScope:
    """Section 16's ``learning_scope``.  ``role_scope`` is explicit because section 24 makes
    "shared" a claim a packet has to make, not a default it can drift into."""

    task: str = ""
    goal_family: str = ""
    role_scope: str = ROLE_SCOPE_SHARED
    cluster_id: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "goal_family": self.goal_family,
            "role_scope": self.role_scope,
            "cluster_id": self.cluster_id,
        }


@dataclass(frozen=True)
class LearningConstraints:
    """Section 16's ``constraints``, all four ``True`` and none settable.

    These are assertions about *this mode*, not permissions granted to a model: the offline pass
    runs without a device, writes candidates rather than knowledge, and cannot promote.  A field
    that could be set False would be describing a different, forbidden mode.
    """

    no_device_actions: bool = True
    no_production_write: bool = True
    no_direct_promotion: bool = True
    no_absolute_coordinate_learning: bool = True

    @property
    def all_held(self) -> bool:
        return (self.no_device_actions and self.no_production_write
                and self.no_direct_promotion and self.no_absolute_coordinate_learning)

    def as_wire(self) -> dict[str, Any]:
        return {
            "no_device_actions": True,
            "no_production_write": True,
            "no_direct_promotion": True,
            "no_absolute_coordinate_learning": True,
        }


@dataclass(frozen=True)
class FailureSummary:
    """Section 16's ``failure_summary``: the shape of what went wrong, in counts."""

    success_count: int = 0
    failure_count: int = 0
    common_failure: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "success_count": int(self.success_count),
            "failure_count": int(self.failure_count),
            "common_failure": self.common_failure,
        }


@dataclass(frozen=True)
class UIVenusLearningPacketV1:
    """Section 16's packet, field for field."""

    scope: LearningScope = field(default_factory=LearningScope)
    episodes: tuple[EvidenceEpisode, ...] = ()
    existing_knowledge: tuple[Mapping[str, Any], ...] = ()
    existing_skill: Mapping[str, Any] = field(default_factory=dict)
    failure_summary: FailureSummary = field(default_factory=FailureSummary)
    constraints: LearningConstraints = field(default_factory=LearningConstraints)
    budget: Mapping[str, Any] = field(default_factory=lambda: {
        "max_context_tokens": MAX_MODEL_CONTEXT,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "output_reserve_tokens": OUTPUT_RESERVE,
    })
    mode: str = MODE_OFFLINE

    # ---------------------------------------------------------------- section 17
    def evidence_index(self) -> dict[str, set[str]]:
        """episode id -> the frame ids it can vouch for.

        Built once and used by the candidate validator: a citation is resolvable only when the
        packet really contains that episode, and -- when a frame is named too -- that frame belongs
        to it.  A cross-episode frame id is a citation nobody can follow, which is the failure
        section 17 exists to prevent.
        """
        index: dict[str, set[str]] = {}
        for episode in self.episodes:
            index.setdefault(episode.episode_id, set()).update(episode.frame_ids())
        return index

    def traceability_gaps(self) -> list[str]:
        """Section 17's requirements, as a list of what is missing.

        Returns the gaps rather than a boolean so a report can say *which* rule was broken; a
        packet that fails as "invalid" tells a reviewer nothing about where the evidence chain
        broke.
        """
        gaps: list[str] = []
        if not self.episodes:
            gaps.append("no episodes: an offline packet with no evidence has nothing to learn from")
        seen_episode_ids: set[str] = set()
        for index, episode in enumerate(self.episodes):
            where = episode.episode_id or f"episode[{index}]"
            if not episode.episode_id:
                gaps.append(f"{where}: missing episode_id")
            elif episode.episode_id in seen_episode_ids:
                gaps.append(f"{where}: duplicate episode_id")
            seen_episode_ids.add(episode.episode_id)
            if not episode.frames:
                gaps.append(f"{where}: no frames")
            for frame in episode.frames:
                if not frame.frame_id:
                    gaps.append(f"{where}: a frame has no frame_id")
            for action in episode.actions:
                if not action.step:
                    gaps.append(f"{where}: an action has no step id")
            if not episode.verifier.outcome:
                gaps.append(f"{where}: no verifier outcome: the episode has no verdict to trace")
        if self.scope.role_scope != ROLE_SCOPE_SHARED and len({e.role_id for e in self.episodes}) > 1:
            gaps.append(
                f"episodes span {len({e.role_id for e in self.episodes})} roles but role_scope is "
                f"{self.scope.role_scope!r}: section 24 requires {ROLE_SCOPE_SHARED!r} to share"
            )
        return gaps

    def validate(self) -> Verdict:
        if not self.constraints.all_held:
            return refuse(OFFLINE_SCHEMA_INVALID, stage="SCHEMA",
                          detail="a learning constraint was relaxed")
        gaps = self.traceability_gaps()
        if gaps:
            return refuse(OFFLINE_FRAME_WITHOUT_IDENTITY, stage="SCHEMA", detail="; ".join(gaps[:4]))
        return ok("SCHEMA")

    def as_wire(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "learning_scope": self.scope.as_wire(),
            "evidence": {"episodes": [e.as_wire() for e in self.episodes]},
            "existing_knowledge": [dict(row) for row in self.existing_knowledge],
            "existing_skill": dict(self.existing_skill),
            "failure_summary": self.failure_summary.as_wire(),
            "constraints": self.constraints.as_wire(),
            "context_budget": dict(self.budget),
        }

    def render(self) -> str:
        return "Offline learning packet:\n" + json.dumps(
            self.as_wire(), ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------- candidate (section 18-20)
@dataclass(frozen=True)
class EvidenceRef:
    """One citation (sections 19/20 use two shapes; this is the union of them).

    A bare ``"ep_001"`` is accepted on input and normalised here, because the directive's own two
    examples differ and a contract that demanded one shape would be refusing the other's data.
    """

    episode_id: str = ""
    frame_id: str = ""
    step: int | None = None
    verifier: str = ""

    def as_wire(self) -> dict[str, Any]:
        row: dict[str, Any] = {"episode_id": self.episode_id}
        if self.frame_id:
            row["frame_id"] = self.frame_id
        if self.step is not None:
            row["step"] = int(self.step)
        if self.verifier:
            row["verifier"] = self.verifier
        return row


def as_ref(value: Any) -> EvidenceRef:
    """Normalise one citation from a string, a mapping, or an ``EvidenceRef``."""
    if isinstance(value, EvidenceRef):
        return value
    if isinstance(value, Mapping):
        try:
            step = int(value["step"]) if value.get("step") is not None else None
        except (TypeError, ValueError):
            step = None
        return EvidenceRef(
            episode_id=str(value.get("episode_id") or ""),
            frame_id=str(value.get("frame_id") or ""),
            step=step,
            verifier=str(value.get("verifier") or ""),
        )
    return EvidenceRef(episode_id=str(value or "").strip())


def _field(node: Any, *names: str) -> str:
    """The first non-empty of ``names`` on a mapping or an object.  ``""`` when none is set."""
    for name in names:
        value = node.get(name) if isinstance(node, Mapping) else getattr(node, name, None)
        if value:
            return str(value)
    return ""


def frame_id_of(frame: Any) -> str:
    """One evidence frame's id: an explicit id if it carries one, else its path's stem.

    Stated once because two adapters have to agree about it.  The packet *names* a frame and a
    candidate *cites* it; if the two derived the id differently every citation would fail to
    resolve, and the traceability rule would fire on a bookkeeping mismatch rather than on a real
    gap in the evidence.  Accepts a mapping or an object, and any of the spellings this project
    uses for a frame's picture (``screenshot``, ``frame_path``, ``path``).
    """
    explicit = _field(frame, "frame_id", "id")
    path = _field(frame, "screenshot", "frame_path", "path", "hash_target")
    return explicit or (Path(path).stem if path else "")


@dataclass(frozen=True)
class OfflineLearningCandidateV1:
    """Sections 18-20's output.  A candidate knowledge item, never a fact and never an action.

    ``payload`` is the type-specific body (section 19's ``visual_features`` and
    ``candidate_controls``; section 20's ``steps``), left as a mapping because the seven analysis
    types have genuinely different bodies and seven dataclasses would be seven chances for one of
    them to grow a ``decision`` field.
    """

    analysis_type: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence_refs: tuple[EvidenceRef, ...] = ()
    required_validation: tuple[str, ...] = ()
    status: str = STATUS_CANDIDATE
    scope: LearningScope = field(default_factory=LearningScope)
    reason: str = ""
    source: str = "LOCAL_GUI_MODEL"

    def as_row(self, *, trace_id: str = "") -> dict[str, Any]:
        return {
            "recorded_at": _now(),
            "schema": SCHEMA_LEARNING_CANDIDATE,
            "mode": MODE_OFFLINE,
            "trace_id": trace_id,
            "status": STATUS_CANDIDATE,
            "analysis_type": self.analysis_type,
            "learning_scope": self.scope.as_wire(),
            "payload": dict(self.payload),
            "confidence": round(float(self.confidence), 3),
            "evidence_refs": [ref.as_wire() for ref in self.evidence_refs],
            "evidence_count": len(self.evidence_refs),
            "required_validation": list(self.required_validation),
            "reason": self.reason[:CANDIDATE_REASON_MAX_CHARS],
            "source": self.source,
            "not_yet": (
                "candidate knowledge only -- it is not a game fact, it is not registered, and it "
                "is not runnable. Replay -> Shadow -> Live Verifier -> PromotionGate decides."
            ),
        }


@dataclass(frozen=True)
class CandidateParse:
    candidate: OfflineLearningCandidateV1 | None = None
    error: str = ""
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.candidate is not None


# ---------------------------------------------------------------------------- schema
def learning_schema() -> dict[str, Any]:
    """Sections 18-20's reply contract, as JSON Schema.

    ``analysis_type`` is the enum that *is* section 18's prohibition: ``EXECUTE`` cannot be
    generated because it is not a value.  ``payload`` is an open object because the seven types
    differ -- the validator, not the grammar, is what checks each type's required body.
    """
    return {
        "type": "object",
        "properties": {
            "analysis_type": {"type": "string", "enum": list(ANALYSIS_TYPES)},
            "payload": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_refs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "string", "maxLength": 80},
                        "frame_id": {"type": "string", "maxLength": 80},
                        "step": {"type": "integer"},
                        "verifier": {"type": "string", "maxLength": 40},
                    },
                    "required": ["episode_id"],
                    "additionalProperties": False,
                },
                "minItems": 1,
            },
            "required_validation": {
                "type": "array",
                "items": {"type": "string", "enum": list(REQUIRED_VALIDATION_KINDS)},
                "minItems": 1,
            },
            "reason": {"type": "string", "maxLength": CANDIDATE_REASON_MAX_CHARS},
        },
        "required": ["analysis_type", "payload", "evidence_refs", "required_validation", "reason"],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """You are the offline analyst of a screenshot-driven game automation agent.

You are shown evidence from episodes that ALREADY HAPPENED: frames, the actions taken, and the
verifier's verdict on each. You are NOT controlling anything and NOT answering "what should be
done now". You are answering: what should this agent learn from this evidence?

Allowed answers, and nothing else:
- CANDIDATE_PAGE: these frames are one screen; what controls does it carry.
- CANDIDATE_UI_SEMANTIC: these frames show the same control under different printed words.
- FAILURE_PATTERN_CANDIDATE: these episodes failed the same way.
- CANDIDATE_STEP: one action reliably led to one result.
- CANDIDATE_SKILL: several steps formed a route that reliably reached a goal.
- SKILL_REPAIR_CANDIDATE: an existing skill's route or locator no longer matches the evidence.
- NAVIGATION_EDGE_CANDIDATE: one screen reliably leads to another.

Hard rules:
1. Everything you produce is a CANDIDATE, not a fact. Your confidence is not verification.
2. Cite your evidence. Every conclusion must name the episode_id (and frame_id where it applies)
   it came from, in "evidence_refs". A conclusion with no citation is refused.
3. Never output a click, a tap, or a next action. Never output pixel coordinates.
4. Say which checks the candidate must still pass in "required_validation" (REOBSERVE,
   LIVE_NAVIGATION, REPLAY, SHADOW, LIVE_VERIFIER).
5. Reply with JSON only, in exactly the shape you are asked for. The server enforces the key set
   and the enums, so an extra key is refused rather than ignored.
6. "reason" is one short sentence."""


# ---------------------------------------------------------------------------- parsing
def refuse_offline_execute(payload: Any) -> str:
    """Section 18's prohibition, as a check on a raw reply.

    A reply that carries ``decision`` at all is answering the online question, and a reply that
    carries ``decision: EXECUTE`` is answering it dangerously.  Both are refused here, before the
    candidate is built, so the prohibition is a refusal rather than a hope about the prompt.
    """
    if not isinstance(payload, Mapping):
        return ""
    decision = str(payload.get("decision") or "").strip().upper()
    if decision == "EXECUTE":
        return OFFLINE_DECISION_EXECUTE_FORBIDDEN
    if "decision" in payload or "action_type" in payload or "target_element_id" in payload:
        # Any of the online protocol's own keys: this is a different answer to a different
        # question, and admitting it would make the two modes' ledgers incomparable.
        return OFFLINE_ANALYSIS_TYPE_UNKNOWN
    return ""


def parse_candidate(
    raw: str, *, packet: UIVenusLearningPacketV1, scope: LearningScope | None = None
) -> CandidateParse:
    """Read one offline reply, or say exactly why it cannot be used."""
    text = str(raw or "").strip()
    if not text:
        return CandidateParse(error=OFFLINE_NOT_JSON, raw="")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return CandidateParse(error=f"{OFFLINE_NOT_JSON}: {exc.msg}", raw=text[:400])
    if not isinstance(payload, Mapping):
        return CandidateParse(error=OFFLINE_NOT_AN_OBJECT, raw=text[:400])

    execute = refuse_offline_execute(payload)
    if execute:
        return CandidateParse(error=execute, raw=text[:400])

    geometry = find_any_geometry(payload)
    if geometry:
        return CandidateParse(error=f"{OFFLINE_GEOMETRY_TRANSPORTED}: {geometry}", raw=text[:400])

    analysis = str(payload.get("analysis_type") or "").strip().upper()
    if analysis not in ANALYSIS_TYPES:
        return CandidateParse(
            error=f"{OFFLINE_ANALYSIS_TYPE_UNKNOWN}: {analysis[:40]!r}", raw=text[:400])

    body = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else {}
    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    refs = tuple(as_ref(item) for item in _as_list(payload.get("evidence_refs")))
    checks = tuple(
        str(item).strip().upper() for item in _as_list(payload.get("required_validation"))
        if str(item).strip()
    )
    reason = str(payload.get("reason") or "").strip()
    bad_reason = reason_violation(reason, max_chars=CANDIDATE_REASON_MAX_CHARS)
    if bad_reason:
        return CandidateParse(error=bad_reason, raw=text[:400])

    return CandidateParse(
        candidate=OfflineLearningCandidateV1(
            analysis_type=analysis,
            payload=dict(body),
            confidence=confidence,
            evidence_refs=refs,
            required_validation=checks,
            status=STATUS_CANDIDATE,
            scope=scope or packet.scope,
            reason=reason,
        ),
        raw=text[:400],
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ---------------------------------------------------------------------------- validator (sections 17/18/21)
def validate_candidate(
    candidate: OfflineLearningCandidateV1, *, packet: UIVenusLearningPacketV1
) -> Verdict:
    """Sections 17, 18 and 21, as one gate.

    A passing verdict means "this is a traceable candidate that may now be replayed and shadowed".
    It does **not** mean the knowledge is true -- section 21 says so in three different ways, and
    nothing in this module can promote anything.
    """
    if candidate.analysis_type not in ANALYSIS_TYPES:
        return refuse(OFFLINE_ANALYSIS_TYPE_UNKNOWN, stage="SCHEMA",
                      detail=candidate.analysis_type[:40])
    if candidate.status != STATUS_CANDIDATE:
        return refuse(OFFLINE_STATUS_NOT_CANDIDATE, stage="SCHEMA",
                      detail=f"status={candidate.status!r}: section 21 requires {STATUS_CANDIDATE}")
    if "decision" in candidate.payload or "action_type" in candidate.payload:
        return refuse(OFFLINE_DECISION_EXECUTE_FORBIDDEN, stage="SCHEMA",
                      detail="the payload carries the online protocol's own keys")
    carried = find_any_geometry(candidate.payload)
    if carried:
        # Also checked on the built object, not only on the raw reply: a caller may construct a
        # candidate directly, and ``payload`` is open by design (seven types, seven bodies).
        return refuse(OFFLINE_GEOMETRY_TRANSPORTED, stage="SCHEMA",
                      detail=f"the payload carries geometry at {carried}")

    # -- payload shape per analysis type -----------------------------------------------------------
    body_error = _payload_error(candidate)
    if body_error:
        return refuse(OFFLINE_SCHEMA_INVALID, stage="SCHEMA", detail=body_error)

    # -- section 17: every conclusion cites evidence it can actually reach -------------------------
    if not candidate.evidence_refs:
        return refuse(OFFLINE_NO_EVIDENCE_REFS, stage="GROUNDING",
                      detail="a conclusion with no episode cited is not traceable")
    index = packet.evidence_index()
    unresolvable: list[str] = []
    for ref in candidate.evidence_refs:
        if not ref.episode_id or ref.episode_id not in index:
            unresolvable.append(ref.episode_id or "(empty)")
            continue
        if ref.frame_id and ref.frame_id not in index[ref.episode_id]:
            unresolvable.append(f"{ref.episode_id}/{ref.frame_id}")
    if unresolvable and len(unresolvable) == len(candidate.evidence_refs):
        return refuse(OFFLINE_EVIDENCE_NOT_IN_PACKET, stage="GROUNDING",
                      detail=f"no citation resolves: {unresolvable[:4]}")

    # -- required validation -----------------------------------------------------------------------
    if not candidate.required_validation:
        return refuse(OFFLINE_NO_REQUIRED_VALIDATION, stage="GROUNDING",
                      detail="the candidate names no check it must still pass")
    bad = [c for c in candidate.required_validation if c not in REQUIRED_VALIDATION_KINDS]
    if bad:
        return refuse(OFFLINE_VALIDATION_UNKNOWN, stage="GROUNDING", detail=f"unknown checks {bad}")

    return ok("")


def _payload_error(candidate: OfflineLearningCandidateV1) -> str:
    """Each analysis type's own required body (sections 19/20).

    Kept as one function with one branch per type so the seven shapes are readable side by side;
    the alternative -- seven dataclasses -- would spread one rule over seven files and let six of
    them drift.
    """
    kind = candidate.analysis_type
    body = candidate.payload
    if kind == CANDIDATE_PAGE:
        if not str(body.get("page_semantic") or "").strip():
            return "CANDIDATE_PAGE needs page_semantic"
        if not _as_list(body.get("visual_features")):
            return "CANDIDATE_PAGE needs at least one visual feature"
    elif kind == CANDIDATE_UI_SEMANTIC:
        if not _as_list(body.get("texts")):
            return "CANDIDATE_UI_SEMANTIC needs the printed texts it unifies"
        if not str(body.get("semantic") or "").strip():
            return "CANDIDATE_UI_SEMANTIC needs a semantic name"
    elif kind == FAILURE_PATTERN_CANDIDATE:
        if not str(body.get("failure") or "").strip():
            return "FAILURE_PATTERN_CANDIDATE needs the failure it describes"
    elif kind == CANDIDATE_STEP:
        if not str(body.get("semantic_action") or "").strip():
            return "CANDIDATE_STEP needs semantic_action"
        if not str(body.get("expected_result") or "").strip():
            return "CANDIDATE_STEP needs expected_result"
    elif kind == CANDIDATE_SKILL:
        steps = _as_list(body.get("steps"))
        if not steps:
            return "CANDIDATE_SKILL needs steps"
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                return f"CANDIDATE_SKILL step {index} is not an object"
            if not str(step.get("semantic_action") or "").strip():
                return f"CANDIDATE_SKILL step {index} has no semantic_action"
    elif kind == SKILL_REPAIR_CANDIDATE:
        if not str(body.get("skill_id") or "").strip():
            return "SKILL_REPAIR_CANDIDATE needs skill_id"
        if not str(body.get("diagnosis") or "").strip():
            return "SKILL_REPAIR_CANDIDATE needs a diagnosis"
    elif kind == NAVIGATION_EDGE_CANDIDATE:
        if not str(body.get("from_page") or "").strip() or not str(body.get("to_page") or "").strip():
            return "NAVIGATION_EDGE_CANDIDATE needs from_page and to_page"
    return ""


# ---------------------------------------------------------------------------- builders
def candidate_page(
    *, page_semantic: str, visual_features: Sequence[str], controls: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Any], confidence: float = 0.0, reason: str = "",
    scope: LearningScope | None = None,
) -> OfflineLearningCandidateV1:
    """Section 19's ``CANDIDATE_PAGE``."""
    return OfflineLearningCandidateV1(
        analysis_type=CANDIDATE_PAGE,
        payload={
            "page_semantic": str(page_semantic)[:SEMANTIC_MAX_CHARS],
            "visual_features": [str(f) for f in visual_features][:16],
            "candidate_controls": [dict(c) for c in controls][:32],
        },
        confidence=confidence,
        evidence_refs=tuple(as_ref(r) for r in evidence_refs),
        required_validation=(VALIDATION_REOBSERVE, VALIDATION_LIVE_NAVIGATION),
        scope=scope or LearningScope(),
        reason=reason,
    )


def candidate_skill(
    *, skill_id: str, goal_family: str, steps: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Any], confidence: float = 0.0, reason: str = "",
    scope: LearningScope | None = None,
) -> OfflineLearningCandidateV1:
    """Section 20's ``CANDIDATE_SKILL``."""
    return OfflineLearningCandidateV1(
        analysis_type=CANDIDATE_SKILL,
        payload={
            "skill_id": str(skill_id)[:SEMANTIC_MAX_CHARS],
            "goal_family": str(goal_family)[:SEMANTIC_MAX_CHARS],
            "steps": [dict(step) for step in steps][:16],
        },
        confidence=confidence,
        evidence_refs=tuple(as_ref(r) for r in evidence_refs),
        required_validation=(VALIDATION_REPLAY, VALIDATION_SHADOW, VALIDATION_LIVE_VERIFIER),
        scope=scope or LearningScope(),
        reason=reason,
    )


def candidate_failure_pattern(
    *, failure: str, evidence_refs: Sequence[Any], detail: str = "", confidence: float = 0.0,
    reason: str = "", scope: LearningScope | None = None,
) -> OfflineLearningCandidateV1:
    """Section 18's ``FAILURE_PATTERN_CANDIDATE`` -- the type this project already produces.

    Its evidence requirement is the same as any other candidate's, which is the point: a failure
    pattern is a claim about *which episodes* failed the same way, and a claim with no episodes is
    a hunch.
    """
    return OfflineLearningCandidateV1(
        analysis_type=FAILURE_PATTERN_CANDIDATE,
        payload={"failure": str(failure)[:SEMANTIC_MAX_CHARS], "detail": str(detail)[:400]},
        confidence=confidence,
        evidence_refs=tuple(as_ref(r) for r in evidence_refs),
        required_validation=(VALIDATION_REPLAY, VALIDATION_SHADOW),
        scope=scope or LearningScope(),
        reason=reason,
    )


def candidate_navigation_edge(
    *, from_page: str, to_page: str, trigger: str = "", evidence_refs: Sequence[Any] = (),
    confidence: float = 0.0, reason: str = "", scope: LearningScope | None = None,
) -> OfflineLearningCandidateV1:
    """Section 18's ``NAVIGATION_EDGE_CANDIDATE``: "one screen reliably leads to another".

    The edge is a claim about the *navigation graph*, and it is deliberately a candidate: a single
    observed transition and a reliable route are different statements, and the validator's
    evidence requirement is what keeps the second from being written when only the first happened.
    """
    return OfflineLearningCandidateV1(
        analysis_type=NAVIGATION_EDGE_CANDIDATE,
        payload={"from_page": from_page, "to_page": to_page, "trigger": trigger[:SEMANTIC_MAX_CHARS]},
        confidence=confidence,
        evidence_refs=tuple(as_ref(r) for r in evidence_refs),
        required_validation=(VALIDATION_REOBSERVE, VALIDATION_LIVE_NAVIGATION),
        scope=scope or LearningScope(),
        reason=reason,
    )


# ---------------------------------------------------------------------------- ledger (section 30)
class OfflineLedger(Ledger):
    """This mode's ledger.  Independent file and row shape (section 30)."""

    PATH = OFFLINE_LEDGER_PATH

    def record_candidate(
        self, candidate: OfflineLearningCandidateV1, *, verdict: Verdict, trace_id: str = "",
    ) -> dict[str, Any]:
        row = candidate.as_row(trace_id=trace_id)
        row["verdict"] = verdict.as_row()
        row["admitted"] = bool(verdict.ok)
        self.append(row)
        return row

    def record_refusal(
        self, *, code: str, stage: str, detail: str = "", trace_id: str = "", raw: str = "",
    ) -> dict[str, Any]:
        row = {
            "recorded_at": _now(),
            "schema": SCHEMA_LEARNING_CANDIDATE,
            "mode": MODE_OFFLINE,
            "trace_id": trace_id,
            "status": STATUS_CANDIDATE,
            "admitted": False,
            "verdict": refuse(code, stage=stage, detail=detail).as_row(),
            "raw": str(raw)[:300],
        }
        self.append(row)
        return row


# ---------------------------------------------------------------------------- adapters
def packet_from_episodes(
    episodes: Iterable[Any], *, scope: LearningScope | None = None,
    existing_knowledge: Sequence[Mapping[str, Any]] = (),
    existing_skill: Mapping[str, Any] | None = None,
    failure_summary: FailureSummary | None = None,
) -> UIVenusLearningPacketV1:
    """Build section 16's packet from episode records (duck-typed).

    Accepts either ``EvidenceEpisode`` or a mapping with the same keys, so the caller can pass
    ``learning/episodes.jsonl`` rows straight through.  The evidence chain is built here rather
    than by the caller because "every frame carries its episode id" is exactly the property the
    packet is responsible for.
    """
    built: list[EvidenceEpisode] = []
    for item in episodes:
        if isinstance(item, EvidenceEpisode):
            built.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        episode_id = str(item.get("episode_id") or item.get("id") or "")
        frames = tuple(
            EvidenceFrame(
                frame_id=frame_id_of(frame),
                screenshot=_field(frame, "screenshot", "frame_path", "path"),
                page=_field(frame, "page", "page_key"),
            )
            for frame in _as_list(item.get("frames"))
            if isinstance(frame, Mapping)
        )
        actions = tuple(
            EvidenceAction(
                step=int(action.get("step") or 0) if str(action.get("step") or "0").isdigit() else 0,
                action=str(action.get("action") or ""),
                semantic_target=str(action.get("semantic_target") or ""),
            )
            for action in _as_list(item.get("actions"))
            if isinstance(action, Mapping)
        )
        verifier = item.get("verifier") if isinstance(item.get("verifier"), Mapping) else {}
        built.append(EvidenceEpisode(
            episode_id=episode_id,
            role_id=str(item.get("role_id") or ""),
            goal_id=str(item.get("goal_id") or ""),
            frames=frames,
            actions=actions,
            verifier=EvidenceVerifier(
                outcome=str(verifier.get("outcome") or item.get("result") or ""),
                reason=str(verifier.get("reason") or ""),
            ),
        ))
    return UIVenusLearningPacketV1(
        scope=scope or LearningScope(),
        episodes=tuple(built),
        existing_knowledge=tuple(dict(row) for row in existing_knowledge),
        existing_skill=dict(existing_skill or {}),
        failure_summary=failure_summary or FailureSummary(),
    )


def _cluster_frames(cluster: Any) -> list[Any]:
    """Every frame a cluster carries, in whatever shape it carries them.

    ``offline_learning.UnknownCluster`` names them ``representative`` / ``variants`` / ``members``,
    and the representative is a whole frame rather than a path -- so an adapter written against an
    imagined shape would find nothing (or raise on ``Path(frame_object)``) exactly when the nightly
    pass first produced real clusters.  All four spellings are read, in the order the producer
    lists them, because the *representative* is the frame that should lead the citation list.
    """
    out: list[Any] = []
    for name in ("representative", "variants", "members", "frames"):
        value = cluster.get(name) if isinstance(cluster, Mapping) else getattr(cluster, name, None)
        if value is None:
            continue
        if isinstance(value, (str, Mapping)) or hasattr(value, "frame_path"):
            out.append(value)
        elif isinstance(value, (list, tuple)):
            out.extend(value)
    return out


def candidate_from_cluster(
    cluster: Any, *, scope: LearningScope | None = None
) -> OfflineLearningCandidateV1 | None:
    """Adapt one ``offline_learning`` cluster onto a contract candidate.

    Returns ``None`` when the cluster carries no usable evidence: a cluster whose members cannot be
    named is one whose candidate could not be cited, and section 17 refuses those anyway -- better
    to produce nothing than a row that will be refused on arrival.

    The clustering module keeps its own rule of *not* naming pages from pixel similarity alone, so
    the candidate produced here is a ``CANDIDATE_PAGE`` whose ``page_semantic`` is the cluster's
    own stable id rather than an invented page name.  That is the honest reading of both rules: the
    contract's type allows a page candidate, and this project's evidence does not yet justify a
    name.
    """
    frames = _cluster_frames(cluster)
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    for frame in frames:
        path = _field(frame, "screenshot", "frame_path", "path", "hash_target")
        episode = _field(frame, "episode_id")
        if not path or not episode:
            continue
        key = (episode, frame_id_of(frame))
        if key in seen:
            continue
        seen.add(key)
        refs.append(EvidenceRef(episode_id=episode, frame_id=frame_id_of(frame)))
    if not refs:
        return None
    representative = _field(frames[0], "hash_target", "image_path", "frame_path", "path")
    return candidate_page(
        page_semantic=_field(cluster, "cluster_id"),
        visual_features=[Path(representative).name] if representative else ["(no representative)"],
        controls=[],
        evidence_refs=refs,
        confidence=0.0,
        reason="视觉相似的一组帧，尚未命名页面。",
        scope=scope,
    )


def packet_from_clusters(
    clusters: Iterable[Any], *, scope: LearningScope | None = None,
    existing_knowledge: Sequence[Mapping[str, Any]] = (),
    failure_summary: FailureSummary | None = None,
) -> UIVenusLearningPacketV1:
    """Section 16's packet, rebuilt from the clusters' own frames.

    Why from the clusters rather than from a fresh scan: the offline pass has already decided which
    frames belong together and has already recorded where each came from, so regrouping them by
    episode here is a *re-reading* of the pass's own index, not a second opinion about the corpus.

    The verifier outcome is the episode's own ``failure_type`` when a frame carries one and
    ``UNKNOWN`` otherwise.  The pass groups pictures, not outcomes; inventing a verdict would make
    section 17's chain look complete when it is not, and an offline conclusion that "these episodes
    succeeded" has to come from a real verdict or from nowhere.
    """
    frames_by_episode: dict[str, list[dict[str, Any]]] = {}
    outcomes: dict[str, str] = {}
    for cluster in clusters:
        for frame in _cluster_frames(cluster):
            path = _field(frame, "screenshot", "frame_path", "path", "hash_target")
            episode = _field(frame, "episode_id")
            if not path or not episode:
                continue
            rows = frames_by_episode.setdefault(episode, [])
            row = {"frame_id": frame_id_of(frame), "path": path,
                   "page": _field(frame, "page", "page_key")}
            if row not in rows:
                rows.append(row)
            failure = _field(frame, "failure_type")
            if failure:
                outcomes.setdefault(episode, failure)
    episode_rows = [
        {
            "episode_id": episode,
            "frames": rows,
            "verifier": {"outcome": outcomes.get(episode, "UNKNOWN"), "reason": ""},
        }
        for episode, rows in frames_by_episode.items()
    ]
    return packet_from_episodes(
        episode_rows, scope=scope, existing_knowledge=existing_knowledge,
        failure_summary=failure_summary,
    )


def clusters_from_dir(directory: Path | str) -> list[dict[str, Any]]:
    """Read the per-cluster rows ``offline_learning.write_clusters`` wrote.

    Those files (``knowledge/offline/candidates/<cluster_id>.json``) are the pass's full record --
    the summary in ``unknown_clusters.json`` keeps only each cluster's representative *path*, which
    is not enough to cite a frame from.  Unreadable files are skipped; a nightly report must not
    fail because one cluster record was truncated.
    """
    out: list[dict[str, Any]] = []
    try:
        paths = sorted(Path(directory).glob("*.json"))
    except OSError:
        return out
    for path in paths:
        # Per file, not per directory: a single truncated cluster record must not swallow the rest
        # of the pass.  The failure mode of the whole-loop version is worth naming because it is
        # silent -- one unreadable file sorted early and the report reads "no clusters at all".
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def record_clusters(
    clusters: Iterable[Any], *, ledger: OfflineLedger | None = None, scope: LearningScope | None = None,
    existing_knowledge: Sequence[Mapping[str, Any]] = (),
    failure_summary: FailureSummary | None = None,
) -> dict[str, Any]:
    """Type the offline pass's clusters as candidates and record what the contract admitted.

    This is the offline mode's wiring, and it is written as a *report* rather than a gate: the pass
    has already done its real work (grouping pixels and writing them), and a typing layer that could
    refuse it would turn a nightly job into a nightly failure.  Every outcome is counted, including
    the refusals -- "the pass produced clusters but none of them could be cited" is a finding about
    the pass's provenance, and it is exactly the kind of finding a summary that only reported
    ``admitted`` would hide.
    """
    rows = list(clusters)
    packet = packet_from_clusters(
        rows, scope=scope, existing_knowledge=existing_knowledge, failure_summary=failure_summary)
    out: dict[str, Any] = {
        "clusters": len(rows),
        "episodes": len(packet.evidence_index()),
        "candidates": 0,
        "no_evidence": 0,
        "admitted": 0,
        "refused": {},
    }
    book: OfflineLedger = ledger if ledger is not None else OfflineLedger()
    for cluster in rows:
        candidate = candidate_from_cluster(cluster, scope=scope)
        if candidate is None:
            out["no_evidence"] += 1
            continue
        out["candidates"] += 1
        verdict = validate_candidate(candidate, packet=packet)
        book.record_candidate(
            candidate, verdict=verdict,
            trace_id=contract.digest_of({"cluster": _field(cluster, "cluster_id")}),
        )
        if verdict.ok:
            out["admitted"] += 1
        else:
            out["refused"][verdict.code] = out["refused"].get(verdict.code, 0) + 1
    out["ledger"] = str(book.path)
    return out


__all__ = [
    "ANALYSIS_TYPES", "CANDIDATE_PAGE", "CANDIDATE_SKILL", "CANDIDATE_STEP",
    "CANDIDATE_UI_SEMANTIC", "CandidateParse", "EvidenceAction", "EvidenceEpisode",
    "EvidenceFrame", "EvidenceRef", "EvidenceVerifier", "FAILURE_PATTERN_CANDIDATE",
    "FailureSummary", "GEOMETRY_KEYS_FORBIDDEN_OFFLINE", "LearningConstraints", "LearningScope",
    "NAVIGATION_EDGE_CANDIDATE",
    "OFFLINE_DECISION_EXECUTE_FORBIDDEN", "OFFLINE_LEDGER_PATH", "OfflineLearningCandidateV1",
    "OfflineLedger", "REQUIRED_VALIDATION_KINDS", "ROLE_SCOPE_SHARED", "SCHEMA_LEARNING_CANDIDATE",
    "SCHEMA_LEARNING_PACKET", "SKILL_REPAIR_CANDIDATE", "STATUS_CANDIDATE", "SYSTEM_PROMPT",
    "UIVenusLearningPacketV1", "as_ref", "candidate_failure_pattern", "candidate_from_cluster",
    "candidate_navigation_edge", "candidate_page", "candidate_skill", "clusters_from_dir",
    "find_any_geometry", "frame_id_of", "learning_schema", "packet_from_clusters",
    "packet_from_episodes", "parse_candidate", "record_clusters", "refuse_offline_execute",
    "validate_candidate",
]
