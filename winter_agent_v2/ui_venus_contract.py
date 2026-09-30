"""The parts of the UI-Venus contract all three modes share.

Operator directive 2026-10-01, "UI-Venus Input / Output Contract V1".  That directive is careful
to say what it is **not**: it is a *model interface contract*, not a new architecture.  Nothing
here creates a second scheduler, executor, world state, runtime model or GUI agent -- this module
holds the vocabulary and the constants three existing call sites agree on, and nothing else.

What is shared, and why it has to live in one place
---------------------------------------------------
Section 30 splits the contract three ways and then immediately reunites it::

    ONLINE_UNKNOWN  -> independent schema, independent validator, independent ledger
    SKILL_REPAIR    -> independent schema, independent validator, independent ledger
    OFFLINE_LEARNING-> independent schema, independent validator, independent ledger

    but they share: LocalGUIModel, the knowledge confidence system, the Verifier truth system,
    the Skill Lifecycle, and the Risk Gate.

The three modes must not be able to loosen one another (section 30's "禁止混用"), so each gets
its own module -- ``ui_venus_online``, ``ui_venus_repair``, ``ui_venus_offline``.  But a shared
concept that each re-declares *is a shared concept that will drift*, and a drifted risk boundary
is the kind that lets a spend through on the mode nobody re-read.  So every quantity more than
one mode acts on is declared exactly once, here:

* the context budget (section 2) -- the same 32768/4096/28672 the model server is started with;
* the confidence ladder (section 23) -- CONFIRMED > OBSERVED > CANDIDATE, one ranking;
* the risk gate (section 25) -- including ``real_money_allowed = false``, permanently;
* the refusal vocabulary (sections 5, 10, 13) -- one name per refusal, no synonyms;
* the funnel's layers and ratios (section 26) -- so the console and the writers count the same
  things with the same words.

Where a quantity already exists in this project, it is *imported*, not restated.  ``SPEND_WORDS``
lives in ``unknown_advisor`` because that module has owned the spend boundary since 2026-09-22;
a second copy here is how "the planner may spend but the advisor may not" would start.

Long-form reasoning is refused by name
--------------------------------------
Sections 1 and 12 forbid a long chain of thought in the reply.  That is not left to the prompt:
``reason_violation`` refuses a reply whose ``reason`` is a paragraph, and the reply *schemas* cap
the field in the server's grammar.  Measured 2026-09-30 on this deployment (14.3 tok/s): prose is
the budget, and a prompt rule asking for brevity moved p50 latency 11.5 s -> 12.4 s, i.e. it did
nothing.  The shape is the lever; the sentence is not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .unknown_advisor import SPEND_WORDS

# ---------------------------------------------------------------------------- context (section 2)
#: The window the local model is started with.  Same number as ``context_budget.MAX_MODEL_CONTEXT``,
#: pinned here as well because this is the contract a *reader* checks against the directive, and a
#: contract that has to import a budget module to state its own window is one indirection away
#: from disagreeing with it.  ``tests/test_ui_venus_contract.py`` asserts they are equal, so the
#: duplication cannot rot silently.
MAX_MODEL_CONTEXT = 32768

#: Section 2: output must have room, always.
OUTPUT_RESERVE = 4096

#: Section 2's recommended ceiling for input.
MAX_INPUT_TOKENS = 28672

#: Section 2's bands, named so a caller can say which one it thinks it is in.
BAND_ROUTINE = "ROUTINE"          # 4K ~ 10K
BAND_COMPLEX = "COMPLEX"          # 10K ~ 20K
BAND_DEEP_SESSION = "DEEP_SESSION"  # 20K ~ 28K

#: Section 2's trimming order, as one tuple so the code and the docstring cannot disagree.  Read
#: left to right: what is dropped first is first.  P0 appears nowhere, and that is the rule -- the
#: ladder may not trim it.
TRIMMING_ORDER: tuple[str, ...] = (
    "P2_OLD_HISTORY",
    "P2_FULL_OCR",
    "LOW_RELEVANCE_KNOWLEDGE",
    "EARLIER_ACTION_HISTORY",
)

#: Section 3's three priority tiers.
PRIORITY_P0 = "P0"
PRIORITY_P1 = "P1"
PRIORITY_P2 = "P2"

# ---------------------------------------------------------------------------- modes (section 0)
MODE_ONLINE = "ONLINE_UNKNOWN"
MODE_SKILL_REPAIR = "SKILL_REPAIR"
MODE_OFFLINE = "OFFLINE_LEARNING"
MODES: tuple[str, ...] = (MODE_ONLINE, MODE_SKILL_REPAIR, MODE_OFFLINE)

# ---------------------------------------------------------------------------- confidence (section 23)
#: Highest first.  Section 23's whole point is that the model must know which of these it is
#: reading, and must not be handed a CANDIDATE dressed as a game fact.
CONFIDENCE_CONFIRMED = "CONFIRMED"
CONFIDENCE_OBSERVED = "OBSERVED"
CONFIDENCE_CANDIDATE = "CANDIDATE"
CONFIDENCE_LEVELS: tuple[str, ...] = (
    CONFIDENCE_CONFIRMED, CONFIDENCE_OBSERVED, CONFIDENCE_CANDIDATE,
)

#: The ordering itself, as data.  ``higher`` is what makes "CONFIRMED > OBSERVED > CANDIDATE"
#: checkable rather than merely asserted in a comment.
CONFIDENCE_RANK: dict[str, int] = {
    CONFIDENCE_CONFIRMED: 3,
    CONFIDENCE_OBSERVED: 2,
    CONFIDENCE_CANDIDATE: 1,
}


def confidence_rank(level: str) -> int:
    """The rank of a confidence level; unknown text ranks lowest rather than raising.

    An unrecognised level is treated as the *weakest* signal, never the strongest: the failure
    mode to design against is a typo'd "CONFIRMED" being read as a measurement.
    """
    return CONFIDENCE_RANK.get(str(level or "").strip().upper(), 0)


def confidence_is_readable_as_fact(level: str) -> bool:
    """Whether a knowledge item may be presented to the model as a game fact.

    Only ``CONFIRMED`` and ``OBSERVED`` may; a ``CANDIDATE`` may travel but must be marked, which
    is what ``KnowledgeItem.as_wire`` does.  Section 23: "禁止 Candidate Knowledge 在 Prompt 中
    伪装成游戏事实".
    """
    return confidence_rank(level) >= CONFIDENCE_RANK[CONFIDENCE_OBSERVED]


@dataclass(frozen=True)
class KnowledgeItem:
    """One piece of knowledge handed to the model (section 23).

    ``id``/``text``/``confidence`` are required by the directive; ``evidence_count`` and
    ``last_verified_at`` are its recommended pair.  ``confidence`` is normalised to the ladder, so
    an item retyped by hand cannot arrive as "probably".
    """

    id: str
    text: str
    confidence: str = CONFIDENCE_CANDIDATE
    evidence_count: int = 0
    last_verified_at: str = ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "text": str(self.text)[:400],
            "confidence": _norm_confidence(self.confidence),
            "evidence_count": int(self.evidence_count),
            "last_verified_at": str(self.last_verified_at),
        }


@dataclass(frozen=True)
class ConfidenceBuckets:
    """A tally over the ladder, so "how much of what we know is actually confirmed" is a number.

    Returned by the funnel and by any caller that reports coverage; a single scalar would hide the
    case this exists to expose -- plenty of knowledge, none of it verified.
    """

    confirmed: int = 0
    observed: int = 0
    candidate: int = 0

    def as_row(self) -> dict[str, int]:
        return {"confirmed": self.confirmed, "observed": self.observed, "candidate": self.candidate}

    @property
    def total(self) -> int:
        return self.confirmed + self.observed + self.candidate


def _norm_confidence(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if text in CONFIDENCE_LEVELS else CONFIDENCE_CANDIDATE


def bucket_confidence(values: Iterable[Any]) -> ConfidenceBuckets:
    """Count a stream of levels (or rows carrying one) into the ladder."""
    confirmed = observed = candidate = 0
    for value in values:
        level = value
        if isinstance(value, Mapping):
            level = value.get("confidence")
        elif not isinstance(value, str):
            level = getattr(value, "confidence", "")
        norm = _norm_confidence(level)
        if norm == CONFIDENCE_CONFIRMED:
            confirmed += 1
        elif norm == CONFIDENCE_OBSERVED:
            observed += 1
        else:
            candidate += 1
    return ConfidenceBuckets(confirmed, observed, candidate)


# ---------------------------------------------------------------------------- decisions (section 7)
#: Section 7's decision vocabulary.  Exactly these six words.
DECISIONS: tuple[str, ...] = ("EXECUTE", "OBSERVE", "REPLAN", "COMPLETE", "DEFER", "BLOCKED")

#: Section 7's action vocabulary.  Exactly these seven.
ACTION_TYPES: tuple[str, ...] = (
    "CLICK_ELEMENT", "SCROLL", "BACK", "OBSERVE", "OPEN_PAGE", "SELECT_OPTION", "CLOSE_POPUP",
)

#: Decisions that tap nothing.  Listed so "did this step touch the device" is answerable without
#: re-deriving it from the decision word at each call site.
NON_TAPPING_DECISIONS: tuple[str, ...] = ("OBSERVE", "REPLAN", "COMPLETE", "DEFER", "BLOCKED")

#: Section 11: COMPLETE is a *claim*.  Named as its own constant so the runtime's claim record and
#: the validator agree on the spelling, and so "the model said done" is greppable apart from
#: "the verifier said done".
MODEL_COMPLETE_CLAIM = "MODEL_COMPLETE_CLAIM"


# ---------------------------------------------------------------------------- risk (section 25)
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_LEVELS: tuple[str, ...] = (RISK_LOW, RISK_MEDIUM, RISK_HIGH)

#: Section 25's high-risk action family, verbatim.  An action in this family is legal only when the
#: current goal authorised it -- which is what ``RiskEnvelope.authorized_actions`` carries.
HIGH_RISK_ACTIONS: tuple[str, ...] = (
    "ATTACK", "START_RALLY", "JOIN_RALLY", "RECALL", "USE_ITEM", "SPEEDUP", "RESOURCE_SPEND",
)

#: Section 25's words that put an action in the high-risk family when they name what is pressed.
#: The English entries are the action names themselves (the comparison lowercases both sides), and
#: the Chinese ones are the client's own words for the same acts.
#:
#: This is the canonical tuple: ``unknown_learning.HIGH_RISK_WORDS`` imports it rather than
#: keeping a second copy, because two risk vocabularies are two risk *rules*, and the one nobody
#: re-read is the one a spend gets through.  ``SPEND_WORDS`` is imported from ``unknown_advisor``
#: for the same reason -- it is not restated here.
HIGH_RISK_WORDS: tuple[str, ...] = HIGH_RISK_ACTIONS + (
    "攻击", "发起集结", "加入集结", "集结", "撤回", "道具", "加速", "立即完成",
)


@dataclass(frozen=True)
class RiskEnvelope:
    """What the current goal is allowed to do, as plain data the validator can read (section 25).

    Defaults are the *closed* ones.  A caller that forgets to fill this in gets ``LOW``, no
    spending and no real money -- never an open envelope.  Section 25 makes
    ``real_money_allowed = false`` permanent, and it has no setter here on purpose: a contract
    that could be configured into allowing real-money spend is one config edit away from doing it.
    """

    level: str = RISK_LOW
    spending_allowed: bool = False
    authorized_actions: tuple[str, ...] = ()

    @property
    def real_money_allowed(self) -> bool:
        """Always false.  A property, not a field, so no input path can set it."""
        return False

    def permits(self, action_type: str, *, identity: str = "") -> tuple[bool, str]:
        """Whether this envelope lets ``action_type`` act on ``identity``.

        Returns ``(allowed, reason)``.  ``identity`` is the words of whatever is being pressed --
        an element's printed text, or the model's ``semantic_target`` -- so the check is about the
        thing acted on and not merely the action's name.
        """
        action = str(action_type or "").strip().upper()
        text = str(identity or "").strip().lower()
        spends = any(word.lower() in text for word in SPEND_WORDS)
        risky = action in HIGH_RISK_ACTIONS or any(word.lower() in text for word in HIGH_RISK_WORDS)
        if spends and not self.spending_allowed:
            return False, PLAN_SPEND_BLOCKED
        if risky:
            authorized = {str(a).strip().upper() for a in self.authorized_actions}
            if action not in authorized:
                return False, PLAN_ACTION_NOT_AUTHORIZED
        return True, ""

    def as_wire(self) -> dict[str, Any]:
        return {
            "level": _norm_risk(self.level),
            "spending_allowed": bool(self.spending_allowed),
            "real_money_allowed": False,
            "authorized_actions": list(self.authorized_actions),
        }


def _norm_risk(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if text in RISK_LEVELS else RISK_HIGH


# ---------------------------------------------------------------------------- frame identity (section 5)
@dataclass(frozen=True)
class FrameIdentity:
    """One frame's identity: an id plus the hash of its bytes (section 5).

    Both, not either.  ``frame_id`` alone can survive a re-capture into the same slot, and a hash
    alone cannot be quoted in a log readably -- the directive requires the packet to carry both
    and the validator to compare both.
    """

    frame_id: str = ""
    frame_hash: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.frame_id and self.frame_hash)

    @classmethod
    def of(cls, path: Path | str, *, frame_id: str = "") -> "FrameIdentity":
        """Digest a real file.  ``frame_id`` defaults to a short form of the digest.

        Reading the file is deliberate: a frame identity that was not taken from the frame's own
        bytes cannot detect that the frame changed, which is the only thing section 5 asks it to
        do.
        """
        target = Path(path)
        try:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            return cls(str(frame_id or ""), "")
        return cls(str(frame_id or f"frame_{digest[:12]}"), f"sha256:{digest}")

    def as_wire(self) -> dict[str, str]:
        return {"frame_id": self.frame_id, "frame_hash": self.frame_hash}


def frame_consistency(screenshot: FrameIdentity, elements: FrameIdentity) -> str:
    """Section 5's programmatic check, as one function so it has exactly one meaning.

    Returns ``""`` when screenshot and element table describe the same frame, else
    ``CONTEXT_FRAME_MISMATCH``.  Both halves must match: a packet whose *image* and whose *element
    table* are of different frames is the defect the directive is explicit about ("禁止模型基于
    frame_A 的截图 + frame_B 的 element table 进行决策"), and id-matches-but-hash-differs is what a
    re-capture into the same slot looks like.
    """
    if not screenshot.complete or not elements.complete:
        # An incomplete pair cannot be *shown* consistent, so it is refused.  The alternative --
        # treating "we did not measure it" as "it matched" -- would make the check pass exactly
        # when nobody took it.
        return CONTEXT_FRAME_MISMATCH
    if screenshot.frame_id != elements.frame_id:
        return CONTEXT_FRAME_MISMATCH
    if screenshot.frame_hash != elements.frame_hash:
        return CONTEXT_FRAME_MISMATCH
    return ""


# ---------------------------------------------------------------------------- refusal vocabulary
#: Section 13's rejection names, plus the ones sections 5 and 10 add.  One name per refusal and no
#: synonyms: "the model named an element this frame does not have" and "the model transported a
#: pixel" need different responses, and a code shared by both makes the ledger unreadable.
PLAN_NOT_JSON = "PLAN_NOT_JSON"
PLAN_NOT_AN_OBJECT = "PLAN_NOT_AN_OBJECT"
PLAN_SCHEMA_INVALID = "PLAN_SCHEMA_INVALID"
PLAN_DECISION_UNKNOWN = "PLAN_DECISION_UNKNOWN"
PLAN_REASON_TOO_LONG = "PLAN_REASON_TOO_LONG"
PLAN_GOAL_SCOPE_VIOLATION = "PLAN_GOAL_SCOPE_VIOLATION"
PLAN_ROLE_SCOPE_VIOLATION = "PLAN_ROLE_SCOPE_VIOLATION"
PLAN_ACTION_NOT_ALLOWED = "PLAN_ACTION_NOT_ALLOWED"
PLAN_TARGET_NOT_ON_THIS_FRAME = "PLAN_TARGET_NOT_ON_THIS_FRAME"
PLAN_TARGET_IS_NOT_A_CONTROL = "PLAN_TARGET_IS_NOT_A_CONTROL"
PLAN_BBOX_UNNECESSARY = "PLAN_BBOX_UNNECESSARY"
PLAN_FRAME_STALE = "PLAN_FRAME_STALE"
PLAN_FRAME_INCOMPLETE = "PLAN_FRAME_INCOMPLETE"
PLAN_SPEND_BLOCKED = "PLAN_SPEND_BLOCKED"
PLAN_ACTION_NOT_AUTHORIZED = "PLAN_ACTION_NOT_AUTHORIZED"
PLAN_EXECUTE_WITHOUT_TARGET = "PLAN_EXECUTE_WITHOUT_TARGET"
PLAN_GEOMETRY_TRANSPORTED = "PLAN_GEOMETRY_TRANSPORTED"
PLAN_BOX_NOT_NORMALISED = "PLAN_BOX_NOT_NORMALISED"
PLAN_BOX_NOT_FOUR_NUMBERS = "PLAN_BOX_NOT_FOUR_NUMBERS"
PLAN_BOX_OUTSIDE_FRAME = "PLAN_BOX_OUTSIDE_FRAME"
CONTEXT_FRAME_MISMATCH = "CONTEXT_FRAME_MISMATCH"
UNKNOWN_GROUNDING_FAILED = "UNKNOWN_GROUNDING_FAILED"

#: The refusals that mean "this reply never reached the device".  Grouped so a report can state
#: MODEL_DIRECT_DEVICE_CONTROL = false as a *count over these*, rather than as an assurance.
REFUSAL_CODES: tuple[str, ...] = (
    PLAN_NOT_JSON, PLAN_NOT_AN_OBJECT, PLAN_SCHEMA_INVALID, PLAN_DECISION_UNKNOWN,
    PLAN_REASON_TOO_LONG, PLAN_GOAL_SCOPE_VIOLATION, PLAN_ROLE_SCOPE_VIOLATION,
    PLAN_ACTION_NOT_ALLOWED, PLAN_TARGET_NOT_ON_THIS_FRAME, PLAN_TARGET_IS_NOT_A_CONTROL,
    PLAN_BBOX_UNNECESSARY, PLAN_FRAME_STALE, PLAN_FRAME_INCOMPLETE, PLAN_SPEND_BLOCKED,
    PLAN_ACTION_NOT_AUTHORIZED, PLAN_EXECUTE_WITHOUT_TARGET, PLAN_GEOMETRY_TRANSPORTED,
    PLAN_BOX_NOT_NORMALISED, PLAN_BOX_NOT_FOUR_NUMBERS, PLAN_BOX_OUTSIDE_FRAME,
    CONTEXT_FRAME_MISMATCH, UNKNOWN_GROUNDING_FAILED,
)

#: Codes the 2026-09-30 planner already emits, mapped onto the contract's name for the same
#: refusal.  Kept so a ledger written before this contract can still be folded into the same
#: columns -- and so the two vocabularies are *known* to be two spellings of one thing rather
#: than quietly different rules.  ``ui_planner`` keeps its own strings (14 tests pin them); the
#: folding happens where the counts are made.
LEGACY_CODE_ALIASES: dict[str, str] = {
    "PLAN_TARGET_NOT_ON_THIS_SCREEN": PLAN_TARGET_NOT_ON_THIS_FRAME,
    "PLAN_ACTION_NOT_OFFERED": PLAN_ACTION_NOT_ALLOWED,
    "PLAN_TRANSPORTED_GEOMETRY": PLAN_GEOMETRY_TRANSPORTED,
    "PLAN_EXECUTE_WITHOUT_ACTION": PLAN_EXECUTE_WITHOUT_TARGET,
}


def canonical_code(code: Any) -> str:
    """Fold a legacy refusal string onto the contract's vocabulary.

    A prefixed refusal (``PLAN_TRANSPORTED_GEOMETRY: x``) folds to its bare code: the suffix is
    detail, and a counter that keys on the whole string would report one refusal per offending
    key name.
    """
    text = str(code or "").strip()
    if not text:
        return ""
    head = text.split(":", 1)[0].strip()
    head = head.split(" ", 1)[0].strip()
    return LEGACY_CODE_ALIASES.get(head, head)


def code_family(code: Any) -> str:
    """Which part of the chain refused, for grouping: ``PARSE``/``SCOPE``/``TARGET``/``GROUND``.

    Used by reports that have to answer "where does the funnel leak" without enumerating codes.
    The repair and offline vocabularies keep their own prefixes (section 30's independence) and are
    folded to their own families here, so one report can read all three ledgers without the codes
    being silently mixed.
    """
    name = canonical_code(code)
    if name.startswith("REPAIR_"):
        return "REPAIR"
    if name.startswith("OFFLINE_"):
        return "OFFLINE"
    if name in (PLAN_NOT_JSON, PLAN_NOT_AN_OBJECT, PLAN_SCHEMA_INVALID, PLAN_DECISION_UNKNOWN,
                PLAN_REASON_TOO_LONG):
        return "PARSE"
    if name in (PLAN_GOAL_SCOPE_VIOLATION, PLAN_ROLE_SCOPE_VIOLATION):
        return "SCOPE"
    if name in (PLAN_ACTION_NOT_ALLOWED, PLAN_ACTION_NOT_AUTHORIZED, PLAN_SPEND_BLOCKED):
        return "AUTHORITY"
    if name in (PLAN_TARGET_NOT_ON_THIS_FRAME, PLAN_TARGET_IS_NOT_A_CONTROL,
                PLAN_BBOX_UNNECESSARY):
        return "TARGET"
    if name in (CONTEXT_FRAME_MISMATCH, PLAN_FRAME_STALE, PLAN_FRAME_INCOMPLETE):
        return "FRAME"
    if name == UNKNOWN_GROUNDING_FAILED:
        return "GROUNDING"
    if name in (PLAN_BOX_NOT_NORMALISED, PLAN_BOX_NOT_FOUR_NUMBERS, PLAN_BOX_OUTSIDE_FRAME,
                PLAN_GEOMETRY_TRANSPORTED):
        return "GEOMETRY"
    if name == PLAN_EXECUTE_WITHOUT_TARGET:
        return "TARGET"
    return "OTHER"


# ---------------------------------------------------------------------------- geometry
#: The one key a reply may use to propose a region, and only as an *untrusted* proposal
#: (sections 9/10).  Named once here because all three modes name it.
VISION_BOX_KEY = "candidate_bbox_norm"

#: Keys whose presence anywhere in a reply means it transported geometry.  A model that answers
#: with a pixel is refused *by name* rather than quietly ignored.
FORBIDDEN_GEOMETRY_KEYS: tuple[str, ...] = (
    "x", "y", "x1", "y1", "x2", "y2", "x_norm", "y_norm", "coord", "coords",
    "coordinate", "coordinates", "point", "tap", "tap_point", "tap_x", "tap_y",
    "pixel", "pixels", "box", "bbox", "rect",
)

#: Section 10's banner.  The value is never trusted; it is what the record says the number was.
UNTRUSTED_PROPOSAL = "UNTRUSTED_CURRENT_FRAME_PROPOSAL"

#: Section 10's positive form: the box was re-checked against the current frame and something real
#: was found under it.  That still does not mean "the click is correct" -- the Verifier decides.
CURRENT_FRAME_VERIFIED_REGION = "CURRENT_FRAME_VERIFIED_REGION"


def find_forbidden_geometry(node: Any, path: str = "") -> str:
    """The first forbidden geometry key in a reply, or ``""``.

    ``candidate_bbox_norm`` is skipped on purpose -- it is the one channel sections 9/10 open, and
    it is read back by ``read_box``, which only knows how to read four normalised numbers.  Skipping
    the *recursion* here is what makes the narrow allowance safe: a nested ``{"x": 340, "y": 812}``
    cannot hide inside a value that is validated as a 0..1 quadruple.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key).strip().lower()
            if name in FORBIDDEN_GEOMETRY_KEYS:
                return f"{path}.{name}".lstrip(".")
            if name == VISION_BOX_KEY:
                continue
            found = find_forbidden_geometry(value, f"{path}.{name}".lstrip("."))
            if found:
                return found
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found = find_forbidden_geometry(value, f"{path}[{index}]")
            if found:
                return found
    return ""


def read_box(value: Any) -> tuple[tuple[float, float, float, float] | None, str]:
    """Read ``[x, y, w, h]`` as normalised fractions, or say why it is not one.

    Deliberately strict, and this is the *only* reader of a region in the contract.  Four finite
    numbers, each in 0..1, positive size, inside the frame.  A pixel coordinate fails the range
    check by construction (340 is not <= 1), so "no pixels" survives the one channel that carries
    geometry without needing a second rule.
    """
    if value is None:
        return None, ""
    if isinstance(value, Mapping):
        order = ("x_norm", "y_norm", "w_norm", "h_norm")
        if not all(key in value for key in order):
            return None, PLAN_BOX_NOT_FOUR_NUMBERS
        value = [value[key] for key in order]
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None, PLAN_BOX_NOT_FOUR_NUMBERS
    numbers: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            return None, PLAN_BOX_NOT_FOUR_NUMBERS
        if number != number or number in (float("inf"), float("-inf")):
            return None, PLAN_BOX_NOT_FOUR_NUMBERS
        numbers.append(round(number, 4))
    x, y, w, h = numbers
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None, PLAN_BOX_NOT_NORMALISED
    if w <= 0.0 or h <= 0.0 or w > 1.0 or h > 1.0:
        return None, PLAN_BOX_NOT_NORMALISED
    if x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
        return None, PLAN_BOX_OUTSIDE_FRAME
    return (x, y, w, h), ""


# ---------------------------------------------------------------------------- reason (sections 1/12)
#: One short sentence.  The directive's own cap for the online reason field, kept in one place so
#: the schema, the validator and the prompt cannot disagree about it.
REASON_MAX_CHARS = 120

#: A reason may not be a paragraph.  Two sentences is already a plan; this is the count that makes
#: "one short explanation" checkable.
REASON_MAX_SENTENCES = 1


def reason_violation(value: Any, *, max_chars: int = REASON_MAX_CHARS) -> str:
    """Whether a ``reason`` is a long-form rationale, as a refusal code (``""`` when it is fine).

    Sections 1 and 12 forbid prose as the main output.  This is the enforcement: a reply whose
    reason runs long is refused rather than truncated, because a truncated rationale still costs
    the tokens it was written in -- the cost is in the *generation*, and only a refusal removes it.
    """
    text = str(value or "").strip()
    if len(text) > max_chars:
        return PLAN_REASON_TOO_LONG
    stripped = text.rstrip("。.!！?？;；")
    for separator in ("。", "！", "？", ". ", "! ", "? ", "\n"):
        if separator in stripped:
            return PLAN_REASON_TOO_LONG
    return ""


# ---------------------------------------------------------------------------- verdict
@dataclass(frozen=True)
class Verdict:
    """One validation outcome: whether it passed, and if not, where and why.

    ``stage`` is which checkpoint of section 13 refused, ``code`` is the contract's name for the
    refusal, ``detail`` is the evidence.  A boolean alone would make "the model transported a
    pixel" and "the page moved under us" the same fact.
    """

    ok: bool
    code: str = ""
    stage: str = ""
    detail: str = ""

    @property
    def refused(self) -> bool:
        return not self.ok

    def as_row(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "code": self.code,
            "stage": self.stage,
            "detail": str(self.detail)[:300],
            "family": code_family(self.code) if self.code else "",
        }


def ok(stage: str = "") -> Verdict:
    return Verdict(True, "", stage, "")


def refuse(code: str, *, stage: str, detail: str = "") -> Verdict:
    return Verdict(False, code, stage, detail)


# ---------------------------------------------------------------------------- sections 13 stages
#: Section 13's chain, in order, as one tuple.  The validator walks it; the ledger records which
#: checkpoint a reply stopped at, so "where does the funnel leak" is a count over these names.
VALIDATION_STAGES: tuple[str, ...] = (
    "JSON_PARSE",
    "SCHEMA",
    "GOAL_SCOPE",
    "ROLE_SCOPE",
    "ALLOWED_ACTIONS",
    "ELEMENT_EXISTENCE",
    "FRAME_CONSISTENCY",
    "RISK_SPEND",
    "GROUNDING",
)

# ---------------------------------------------------------------------------- funnel (section 26)
#: Section 26's layer names, in funnel order.  The console and every writer count these exact
#: words -- ``learning_funnel`` imports this tuple rather than keeping its own copy, so a layer
#: cannot exist in one and be missing in the other.
FUNNEL_LAYERS: tuple[str, ...] = (
    "unknown_observed",
    "venus_called",
    "venus_proposed",
    "grounding_valid",
    "grounding_rejected",
    "risk_gate_allowed",
    "risk_gate_rejected",
    "maa_executed",
    "verifier_progress",
    "verifier_success",
    "candidate_step_created",
    "candidate_skill_created",
    "candidate_replay_pass",
    "candidate_shadow_pass",
    "live_verified",
    "stable_promoted",
)

#: Section 26's required ratios, as (numerator, denominator).  Named as pairs so a report cannot
#: compute a rate between two layers that were never adjacent.
FUNNEL_RATIOS: tuple[tuple[str, str], ...] = (
    ("venus_proposed", "unknown_observed"),
    ("grounding_valid", "venus_proposed"),
    ("maa_executed", "risk_gate_allowed"),
    ("verifier_success", "maa_executed"),
    ("candidate_skill_created", "candidate_step_created"),
    ("stable_promoted", "candidate_skill_created"),
)


@dataclass(frozen=True)
class TraceRow:
    """One funnel layer's row, with the two ids section 26 requires.

    ``trace_id`` identifies this observation; ``source_id`` names the layer it came from.  Without
    the second, a funnel can be counted but not *followed*, and the directive's requirement ("每一层
    必须有 trace ID，有上一层来源 ID") is precisely about being able to follow one UNKNOWN from
    the screen it appeared on to the skill it became.
    """

    layer: str
    trace_id: str
    source_id: str = ""
    mode: str = MODE_ONLINE
    recorded_at: str = ""
    outcome: str = ""
    code: str = ""

    def as_row(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "trace_id": self.trace_id,
            "source_id": self.source_id,
            "mode": self.mode,
            "recorded_at": self.recorded_at,
            "outcome": self.outcome,
            "code": canonical_code(self.code) if self.code else "",
        }


# ---------------------------------------------------------------------------- ledgers
def append_row(path: Path | str, row: Mapping[str, Any], *, limit: int = 5000) -> bool:
    """Append one JSON row to a jsonl ledger, bounded to the newest ``limit`` rows.

    Shared by all three ledgers because "append-only, newest N kept, never raise" is a property of
    the *store*, not of what is stored -- and three copies of it would be three chances for one
    ledger to raise inside a page step.  Returns whether the row was written; never raises.
    """
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        rows.append(json.dumps(dict(row), ensure_ascii=False, default=str))
        target.write_text("\n".join(rows[-int(limit):]) + "\n", encoding="utf-8")
        return True
    except (OSError, TypeError, ValueError):
        return False


def read_rows(path: Path | str) -> list[dict[str, Any]]:
    """Read a jsonl ledger as rows, skipping anything unreadable.  Never raises."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


class Ledger:
    """An append-only jsonl ledger.  One instance per mode, per section 30's independence rule.

    Deliberately the *only* thing this class does.  Each mode's module subclasses or wraps it with
    the row shape it writes, so the three ledgers are three files with three schemas -- which is
    what "独立 ledger" asks for -- while the durability behaviour is shared.
    """

    #: Where this ledger lives, relative to the project root.  Subclasses set it.
    PATH: Path = Path("learning/ui_venus.jsonl")

    def __init__(self, path: Path | str | None = None, *, limit: int = 5000) -> None:
        self.path = Path(path) if path is not None else Path(self.PATH)
        self.limit = int(limit)

    def append(self, row: Mapping[str, Any]) -> bool:
        return append_row(self.path, row, limit=self.limit)

    def rows(self) -> list[dict[str, Any]]:
        return read_rows(self.path)


# ---------------------------------------------------------------------------- guard (section 31)
#: The gate's own name.  Section 31 makes this the *first* door: until it is true, no planner or
#: learning wiring may be considered done, and the only permitted work is fixing the model service.
SCREENSHOT_INPUT_VERIFIED = "SCREENSHOT_INPUT_VERIFIED"

#: What a section-31 record must carry, so the proof is reproducible and not a sentence.
GATE_FIELDS: tuple[str, ...] = (
    "backend",
    "model",
    "quantization",
    "mmproj_loaded",
    "image_resolution",
    "image_encoding",
    "latency_ms",
    "ram_mb",
    "vram_mb",
)


@dataclass(frozen=True)
class GateRecord:
    """Section 31's evidence that the model receives pixels, field by field.

    A field whose value is unknown is written as ``""`` and the record is *not* verified: section 31
    asks for these quantities, and a record that silently omitted the ones it could not measure
    would be the kind of overclaim the constitution forbids elsewhere.
    """

    backend: str = ""
    model: str = ""
    quantization: str = ""
    mmproj_loaded: bool = False
    image_resolution: str = ""
    image_encoding: str = ""
    latency_ms: float = 0.0
    ram_mb: float = 0.0
    vram_mb: float = 0.0
    with_image_reply: str = ""
    text_only_reply: str = ""

    @property
    def verified(self) -> bool:
        """True only when the model answered *with* an image and the projector is loaded.

        The comparison is the proof: the same question asked blind and asked with the frame, and
        the two answers differing.  A reply that cannot be shown to have used the picture is not
        evidence, however confident it sounds.
        """
        return bool(self.mmproj_loaded and self.with_image_reply
                    and self.with_image_reply.strip() != self.text_only_reply.strip())

    def as_row(self) -> dict[str, Any]:
        row = {
            "backend": self.backend,
            "model": self.model,
            "quantization": self.quantization,
            "mmproj_loaded": bool(self.mmproj_loaded),
            "image_resolution": self.image_resolution,
            "image_encoding": self.image_encoding,
            "latency_ms": round(float(self.latency_ms), 1),
            "ram_mb": round(float(self.ram_mb), 1),
            "vram_mb": round(float(self.vram_mb), 1),
            "with_image_reply": str(self.with_image_reply)[:300],
            "text_only_reply": str(self.text_only_reply)[:300],
        }
        row[SCREENSHOT_INPUT_VERIFIED] = self.verified
        missing = [name for name in GATE_FIELDS if not row.get(name) and name != "mmproj_loaded"]
        row["unmeasured_fields"] = missing
        return row


# ---------------------------------------------------------------------------- serialisation
def to_json(value: Any, *, indent: int | None = None) -> str:
    """The one serialiser every mode uses, so ``ensure_ascii`` and key order cannot diverge.

    ``ensure_ascii=False`` because the client's own text is Chinese and the model must read it as
    Chinese: escaped codepoints are both longer and measurably worse for this model.
    """
    return json.dumps(value, ensure_ascii=False, indent=indent, default=str)


def digest_of(value: Any) -> str:
    """A short stable id for a wire payload, used to build trace ids.

    The funnel's rows must be joinable across layers; hashing the payload that produced a step is
    what lets the same observation be found again without inventing a counter that another process
    would have to agree on.
    """
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def compact_state(state: Mapping[str, Any] | None, keys: Sequence[str]) -> dict[str, Any]:
    """A few named fields of a world state, each bounded.

    Section 1 forbids sending the whole knowledge base or a full log; this is the shape of "only
    what the current task needs" for a world state, and it is shared so all three modes bound it
    the same way.
    """
    out: dict[str, Any] = {}
    for key in keys:
        if not isinstance(state, Mapping) or key not in state:
            continue
        value = state[key]
        if isinstance(value, Mapping):
            value = {k: value[k] for k in list(value)[:8]}
        elif isinstance(value, (list, tuple)):
            value = list(value)[:8]
        elif isinstance(value, str):
            value = value[:200]
        out[key] = value
    return out


__all__ = [
    "ACTION_TYPES", "BAND_COMPLEX", "BAND_DEEP_SESSION", "BAND_ROUTINE",
    "CURRENT_FRAME_VERIFIED_REGION", "CONFIDENCE_CANDIDATE", "CONFIDENCE_CONFIRMED",
    "CONFIDENCE_LEVELS", "CONFIDENCE_OBSERVED", "CONFIDENCE_RANK", "CONTEXT_FRAME_MISMATCH",
    "ConfidenceBuckets", "DECISIONS", "FUNNEL_LAYERS", "FUNNEL_RATIOS", "FORBIDDEN_GEOMETRY_KEYS",
    "FrameIdentity", "GATE_FIELDS", "GateRecord", "HIGH_RISK_ACTIONS", "HIGH_RISK_WORDS",
    "KnowledgeItem", "Ledger", "MAX_INPUT_TOKENS", "MAX_MODEL_CONTEXT", "MODEL_COMPLETE_CLAIM",
    "MODE_OFFLINE", "MODE_ONLINE", "MODE_SKILL_REPAIR", "MODES", "NON_TAPPING_DECISIONS",
    "OUTPUT_RESERVE", "PLAN_BBOX_UNNECESSARY", "PLAN_FRAME_STALE", "PLAN_GOAL_SCOPE_VIOLATION",
    "PLAN_SCHEMA_INVALID", "PLAN_SPEND_BLOCKED", "PLAN_TARGET_NOT_ON_THIS_FRAME",
    "PRIORITY_P0", "PRIORITY_P1", "PRIORITY_P2", "REASON_MAX_CHARS", "REFUSAL_CODES",
    "RISK_HIGH", "RISK_LEVELS", "RISK_LOW", "RISK_MEDIUM", "RiskEnvelope",
    "SCREENSHOT_INPUT_VERIFIED", "TRIMMING_ORDER", "TraceRow", "UNKNOWN_GROUNDING_FAILED",
    "UNTRUSTED_PROPOSAL", "VALIDATION_STAGES", "VISION_BOX_KEY", "Verdict",
    "append_row", "bucket_confidence", "canonical_code", "code_family", "compact_state",
    "confidence_is_readable_as_fact", "confidence_rank", "digest_of", "find_forbidden_geometry",
    "frame_consistency", "ok", "read_box", "read_rows", "reason_violation", "refuse", "to_json",
]
