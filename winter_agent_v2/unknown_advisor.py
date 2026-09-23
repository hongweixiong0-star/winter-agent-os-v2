"""On-demand UNKNOWN analysis: ask a reasoner without ever waiting for one.

Why this exists (operator directive 2026-09-22, "复用现有 UNKNOWN，接入按需 AI 分析")

``Page.UNKNOWN`` and ``UNKNOWN`` action results are the states this project handles worst, and
the two mechanical halves of the answer are already in place: the runtime reads an unnamed screen
with OCR, taps what the client printed, and keeps the screen and the transition it measured (the
UI collector and ``page_knowledge``).  What neither can do is *understand* a screen whose own words
are not enough -- 领主指令 with no recognisable action word, or a step whose outcome the WorldState
cannot express.

The third half is a reasoner, and the shape of it is fixed by this project's own standing rule
(operator section 7, pinned by ``tests/test_qwen_decoupling.py``): **a model is an optional
provider, never a runtime dependency**.  With no model enabled, every rule-based capability still
runs.  So this module holds no client, opens no socket and blocks on nothing:

    the AUTO    writes a structured request to ``learning/unknown_requests/`` and moves on
    the reasoner answers by dropping one file (or by calling ``tools/unknown_advisor.py``)
    the AUTO    picks the answer up on a later step and routes it through the chain it already has

That is what keeps "按需 AI 分析" from becoming "AUTO waits for WorkBuddy": there is no code path
here that can wait, because the only I/O is reading files that already exist.

What it is and is not
---------------------
A **state directory plus pure parsing**, the same shape as ``ui_collection`` / ``page_knowledge``.
It does not click, decides no goal, owns no device, and knows no skill of its own: an answer's
proposed action must name a skill the registry already has, exactly as the project's own
model-decision parser requires of a model's JSON.

An answer is a **candidate**, never a verdict (directive §三/§五):

* ``verification_status`` moves only on a real step's verifier -- this module cannot set it;
* an answer's point is used only when the frame justifies it (the directive's §四 "有合理的当前
  画面定位依据"): the point has to fall inside a text box this frame's OCR actually read, so an
  invented coordinate cannot become a tap;
* an answer that names money, gems or an irreversible action is refused outright, on the same
  blacklist the ordinary-control resolver carries.

The request is also the record the directive's §二 asks for -- goal, frame, page label and
confidence, OCR text with boxes, entry page and trigger, world state, what the template and ledger
measured, and the last attempt's expectation against its observed result -- because a reasoner that
has to guess what it was shown is a reasoner whose answer cannot be audited.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: Where unanswered requests wait.  Under ``learning/`` beside the episode stream and the control
#: ledger, so a WorkBuddy session (or an operator, or a script) reads one directory to see what the
#: AUTO could not work out for itself.
REQUEST_ROOT = Path("learning/unknown_requests")
ANSWERS_DIR = "answers"

#: The kinds of UNKNOWN this project actually meets.  Named so a request says which question it is
#: asking -- "what screen is this" and "did that step work" need different evidence (directive §二
#: asks for both frames in the second case).
UNKNOWN_PAGE = "PAGE"
UNKNOWN_CONTROL = "CONTROL"          # a named control that could not be located
UNKNOWN_RESULT = "RESULT"            # the action's outcome was not readable
UNKNOWN_TYPES: tuple[str, ...] = (UNKNOWN_PAGE, UNKNOWN_CONTROL, UNKNOWN_RESULT)

#: The provenance value an advice carries.  It is deliberately not ``ACTION_RESULT``: nothing here
#: has been acted on, so nothing here may look like a measurement.
METHOD_AI = "AI_INFERENCE"

#: How many requests one run may write.  A bound rather than a budget: the AUTO must not turn an
#: unnamed screen into a request generator, and a reasoner answering a hundred near-identical
#: frames would learn nothing it could not learn from one.
MAX_REQUESTS_PER_RUN = 2

#: One request per (screen, question) per hour.  The frame is re-photographed on every step of an
#: unnamed screen, so without this the same question would be filed dozens of times -- and a
#: reasoner's answer would arrive to find the request it answers superseded.
REQUEST_COOLDOWN_SECONDS = 3600

#: Exactly what an answer must carry (directive §三).  Anything missing or extra is rejected rather
#: than interpreted: an answer whose shape floats is an answer nobody can audit.
ANSWER_FIELDS = (
    "unknown_type",
    "candidate_semantics",
    "proposed_action",
    "expected_result",
    "uncertainty",
)
OPTIONAL_ANSWER_FIELDS = (
    "target_point",
    "target_bbox",
    "alternative_actions",
    "note",
    # Which of the three shapes the action is (see ACTION_KINDS).  Absent, it is inferred from
    # ``proposed_action`` itself, so an answer written before this existed keeps working.
    "action_kind",
    # What the answer is asking for, named.  Kept apart from ``proposed_action`` because the action
    # names a *mechanism* ("tap this", "reuse the L1 action") while this names the *element*.
    "target_semantics",
    # Directive §三's third basis: a region derived from a text box the frame really drew, e.g.
    # ``{"text": "说明", "dy_norm": -0.045, "w_norm": 0.06, "h_norm": 0.05}`` -- the icon above that
    # label.  The anchor is measured on the current frame and the offset is bounded; see
    # ``ui_collection.anchored_region``.
    "target_anchor",
    # What the reasoner believes it anchored on.  Recorded, never trusted: the runtime decides which
    # basis actually justified the point, and files *that* one.
    "grounding_basis",
    "grounding_ref",
    # --- the directive's four questions, as fields (operator 2026-09-23) --------------------------
    #
    # ``notification``  what notification was seen, and on which entry or task row
    # ``entry``         which function that entry leads into
    # ``target_semantics`` / ``proposed_action``  which real control to press   (above)
    # ``expected_result``          what to observe or do once inside            (above)
    #
    # The first two are new because the old contract could not tell "there is a gift icon with a dot"
    # from "press the gift icon": both had to be said in ``proposed_action``, and a reader of the
    # answer had no way to check that the *entry* was entered before anything was claimed.  Optional
    # rather than required, because requiring them would invalidate every answer already on disk --
    # including the one real answer this project has (``unknown__control__b6546e80``), which was
    # written before the split existed and is still perfectly usable.
    "notification",
    "entry",
    # Which of ``ACTION_LEVELS`` this answer is asking for.  Absent means TASK_ACTION, i.e. the
    # stricter reading: an answer that does not say it is only entering a page does not get to be
    # treated as if it had.
    "action_level",
)

#: The three shapes an answer's action may take (directive §二).  Before this, only the first was
#: accepted -- every answer had to name a registered skill -- which made the channel useless for
#: exactly the case it exists for: an element nobody has registered.
ACTION_SKILL = "SKILL"
ACTION_L1 = "L1"
ACTION_ORDINARY = "ORDINARY_CONTROL"
ACTION_KINDS: tuple[str, ...] = (ACTION_SKILL, ACTION_L1, ACTION_ORDINARY)

#: The strings that name the action *itself* -- its mechanism, and the element it acts on.  The
#: boundary below is applied to these and to nothing else.
ACTION_IDENTITY_FIELDS = ("proposed_action", "candidate_semantics", "target_semantics", "grounding_ref")

#: Fields that are the reasoner *talking*, not the reasoner acting.  Directive §五 is explicit that a
#: reasoner must be able to understand a page that offers 钻石 / 加速 / 购买, and it cannot
#: demonstrate that understanding if those words are banned from its explanation.  So the boundary
#: is not applied here: an answer may say "this page sells gems; the low-risk action is 关闭".
COMMENTARY_FIELDS = ("note", "uncertainty", "expected_result", "alternative_actions")

#: The two levels of *acting* that an answer may ask for (operator directive 2026-09-23).
#:
#: The directive separates three things a screenshot makes look like one -- the notification, the
#: control that enters the function, and the action taken once inside -- and it is explicit that the
#: dot is only the first of them: "红点不等于按钮，不等于点击目标，也不等于任务可执行或奖励可领取".
#:
#: ``ENTRY_CONTROL``  press a control that opens a function.  Nothing is claimed, spent or donated by
#:                    entering, so the boundary for it is the money/irreversibility list alone.
#: ``TASK_ACTION``    act on what the page shows once inside (claim / train / donate / recruit).  The
#:                    full boundary applies, unchanged from before this split.
#:
#: The third thing the directive names -- the notification -- is not an action at all, which is why
#: it is a field (``Advice.notification``) and not a level.
LEVEL_ENTRY = "ENTRY_CONTROL"
LEVEL_TASK = "TASK_ACTION"
ACTION_LEVELS: tuple[str, ...] = (LEVEL_ENTRY, LEVEL_TASK)

#: Words that must never be proposed at *any* level: real money, and irreversible spend.
SPEND_WORDS: tuple[str, ...] = (
    "充值",
    "购买",
    "支付",
    "钻石",
    "特惠",
    "首充",
    "月卡",
    "基金",
    "花费",
    "消费",
    "buy",
    "purchase",
    "pay",
    "gems",
)

#: Words whose risk depends on the level.  Each of these *names a function* and, acted on, can cost
#: something: 招募 / 礼包 / 加速 / 立即完成.  Entering the function is not doing it, so at
#: ``ENTRY_CONTROL`` these are allowed and at ``TASK_ACTION`` they are not -- which is what makes the
#: directive's own example possible: "不要求先写完整招募 Skill 才能首次免费招募".  The first free
#: attempt is an entry; whether anything is spent is decided from the page it lands on, by the chain
#: that already reads pages, and never from the notification.
CONTEXT_WORDS: tuple[str, ...] = (
    "礼包",
    "招募",
    "加速",
    "立即完成",
)

#: The boundary the ordinary-control resolver draws, restated here so a *reasoner* cannot be the
#: way around it.  It is applied to the action's own identity -- what is being pressed -- and never
#: to the answer's commentary (``COMMENTARY_FIELDS``), because understanding a page that sells
#: things is not the same as buying from it (directive §五).
#:
#: Kept as the union of the two groups above so the TASK_ACTION reading -- and every answer that does
#: not declare a level -- is judged by exactly the list it was judged by before the levels existed.
REFUSED_WORDS: tuple[str, ...] = SPEND_WORDS + CONTEXT_WORDS


def words_refused_at(level: str | None) -> tuple[str, ...]:
    """The boundary for one level.  ``None``/unknown levels get the strict list, never the loose one."""
    return SPEND_WORDS if str(level or "").strip().upper() == LEVEL_ENTRY else REFUSED_WORDS


def advice_level(advice: Any) -> str:
    """The level an answer is asking for, with the conservative default applied.

    An answer written before the levels existed, or one that simply does not say, is a
    ``TASK_ACTION``: it does not get the entry-level boundary by accident.
    """
    level = str(getattr(advice, "action_level", "") or "").strip().upper()
    return level if level in ACTION_LEVELS else LEVEL_TASK


#: How far a point may sit outside the OCR box it claims, as a fraction of the frame.  A reasoner
#: reading a 720x1280 screenshot usually lands near the control rather than on its exact centre, and
#: demanding pixel equality would reject every honest answer; this is the trade, and it is measured
#: against the box, not guessed.
POINT_SLOP_NORM = 0.02


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seconds_since(stamp: str) -> float:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


def request_id(page_key: str, unknown_type: str) -> str:
    """A request's identity: the screen and the question -- deliberately **not** the frame.

    The frame digest is carried inside the request (so a reasoner knows which picture it was
    shown) but it must not be part of the id: an unnamed screen is re-photographed on every step,
    so a digest-keyed id would file a new question every step and the answer to the first one could
    never be found again.  Same screen + same question = same request.
    """
    stem = re.sub(r"[^a-z0-9]+", "_", str(page_key).lower()).strip("_")[:36] or "unknown"
    # The stem alone is not an identity: every unnamed screen's key starts with ``UNKNOWN`` and its
    # title is Chinese, so the ASCII-only stem collapses them all to ``unknown`` -- measured on the
    # first two live screens, whose questions would have overwritten each other.  A digest of the
    # whole key keeps them apart while staying stable across frames (no frame digest here, see the
    # docstring): same screen, same question, one request.
    material = hashlib.sha256(str(page_key).encode("utf-8")).hexdigest()[:8]
    return f"{stem}__{unknown_type.lower()}__{material}"


def frame_digest(frame_path: Path | str) -> str:
    """A short digest of a frame's bytes, so the same picture is the same request."""
    try:
        return hashlib.sha256(Path(frame_path).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


@dataclass
class UnknownRequest:
    """The directive's §二 input list, as one file."""

    request_id: str
    unknown_type: str
    page_label: str
    page_key: str
    goal: str = ""
    frame_path: str = ""
    page_confidence: float | None = None
    ocr_texts: tuple[str, ...] = ()
    ocr_boxes: tuple[dict[str, Any], ...] = ()
    entry_page: str = ""
    entry_trigger: str = ""
    world_state: dict[str, Any] = field(default_factory=dict)
    template_match: str = ""
    ledger_match: str = ""
    last_attempt: dict[str, Any] = field(default_factory=dict)
    before_frame_path: str = ""
    after_frame_path: str = ""
    created_at: str = ""
    question: str = ""
    #: Which picture the question is about.  Not part of the identity (see ``request_id``), kept so
    #: a reasoner can tell "the same screen, one frame later" from "a different frame entirely".
    frame_digest: str = ""
    #: The state the question was asked in -- the same signature an L1 registration is conditional
    #: on, so an answer and the reuse it enables agree about what "this screen" means (§四).
    situation: str = ""
    #: Who was being played, when the frame could say.  A control that is safe for one role is not
    #: automatically safe for another, and §四 asks the answer to be tied to the conditions.
    character: str = ""

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Advice:
    """One reasoner answer, validated.  A candidate, never a verdict."""

    request_id: str
    unknown_type: str
    candidate_semantics: tuple[str, ...]
    proposed_action: str
    expected_result: str
    uncertainty: str
    target_point: tuple[float, float] | None = None
    target_bbox: dict[str, float] | None = None
    alternative_actions: tuple[str, ...] = ()
    note: str = ""
    answered_at: str = ""
    source: str = METHOD_AI
    #: One of ``ACTION_KINDS``: whether this answer names a registered skill, an L1 action this
    #: project has already proved, or an ordinary control candidate that needs no registration.
    action_kind: str = ACTION_SKILL
    #: The element the answer is about, as the reasoner named it.
    target_semantics: str = ""
    #: The region the reasoner derived from a text box, if it used that basis.
    target_anchor: dict[str, Any] | None = None
    #: What the reasoner *claimed* it anchored on.  Recorded for the audit; the runtime files the
    #: basis it actually measured instead.
    grounding_basis: str = ""
    grounding_ref: str = ""
    #: The directive's four questions, in the answer's own words.  ``notification`` is what was seen
    #: and where; ``entry`` is which function that is; ``target_semantics``/``proposed_action`` is
    #: the control to press; ``expected_result`` is what to observe or do once inside.  Empty when the
    #: answer predates the split -- recorded as empty rather than inferred, so a reader can tell
    #: "the reasoner said this is only an entry" from "nobody said".
    notification: str = ""
    entry: str = ""
    #: One of ``ACTION_LEVELS``, or ``""`` for an answer that did not say (judged as ``TASK_ACTION``).
    action_level: str = ""

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class AdviceRejected(ValueError):
    """An answer that cannot be used, with the reason kept for the record."""


def parse_advice(payload: Mapping[str, Any], *, request_id: str = "", registry: Any = None) -> Advice:
    """Validate one answer against §三, or raise ``AdviceRejected``.

    Strict on purpose, and this is the project's own precedent: the model-decision parser in
    ``brain`` demands an exact schema before it will turn a model's words into a Decision, because a
    parser that improvises is a parser that feeds invented actions into a live game.
    """
    if not isinstance(payload, Mapping):
        raise AdviceRejected("REJECT: answer is not an object")
    missing = [name for name in ANSWER_FIELDS if name not in payload]
    if missing:
        raise AdviceRejected(f"REJECT: missing fields {missing}")
    unknown = [name for name in payload if name not in ANSWER_FIELDS + OPTIONAL_ANSWER_FIELDS]
    if unknown:
        raise AdviceRejected(f"REJECT: unexpected fields {unknown}")

    unknown_type = str(payload["unknown_type"]).strip().upper()
    if unknown_type not in UNKNOWN_TYPES:
        raise AdviceRejected(f"REJECT: unknown_type {unknown_type!r} is not one of {UNKNOWN_TYPES}")

    semantics = payload["candidate_semantics"]
    if isinstance(semantics, str):
        semantics = [semantics]
    if not isinstance(semantics, (list, tuple)) or not all(isinstance(item, str) for item in semantics):
        raise AdviceRejected("REJECT: candidate_semantics must be a list of strings")
    semantics = tuple(str(item) for item in semantics)

    proposed = str(payload["proposed_action"]).strip()
    if not proposed:
        raise AdviceRejected("REJECT: empty proposed_action")
    target_semantics = str(payload.get("target_semantics") or "").strip()

    # Which level this answer is asking for (operator directive 2026-09-23).  Read before the
    # boundary, because the boundary is applied *per level*: entering a function is not doing it.
    level = str(payload.get("action_level") or "").strip().upper()
    if level and level not in ACTION_LEVELS:
        raise AdviceRejected(f"REJECT: action_level {level!r} is not one of {ACTION_LEVELS}")

    # The boundary, applied to the action's own identity (directive §五).  ``note``/``uncertainty``
    # /``expected_result`` are deliberately not screened: an answer has to be able to say that the
    # page in front of it offers gems in order to explain why it is *not* pressing them.
    identity = " ".join(
        [str(payload.get(name) or "") for name in ACTION_IDENTITY_FIELDS]
    ).lower()
    for word in words_refused_at(level):
        if word.lower() in identity:
            raise AdviceRejected(
                f"REJECT: the proposed action itself involves {word!r}"
                + ("" if level == LEVEL_ENTRY else
                   " -- and this answer does not declare itself an entry (ACTION_LEVEL="
                   f"{LEVEL_ENTRY}), so it is read as acting on the page")
                + ".  An answer may *describe* a page that offers it -- note/uncertainty/"
                  "expected_result are not screened -- but it may not propose pressing it"
            )

    # Which of the three shapes this is (§二).  Inferred when absent, so an answer written against
    # the old contract -- a registered skill, or the ordinary-control attempt -- is read the same
    # way it always was.
    kind = str(payload.get("action_kind") or "").strip().upper()
    if kind and kind not in ACTION_KINDS:
        raise AdviceRejected(f"REJECT: action_kind {kind!r} is not one of {ACTION_KINDS}")
    if not kind:
        kind = infer_action_kind(proposed, registry=registry)
        if kind is None:
            raise AdviceRejected(
                f"REJECT: {proposed!r} is not a registered skill, not an L1[...] action and not an "
                "ORDINARY_CONTROL[...] candidate, so there is nothing this answer could execute"
            )
    elif kind == ACTION_SKILL and registry is not None and registry.get(proposed) is None:
        raise AdviceRejected(f"REJECT: unknown skill {proposed!r}")
    if kind == ACTION_L1 and not l1_target(proposed):
        raise AdviceRejected(
            "REJECT: an L1 action must name the control it reuses, e.g. L1[ORDINARY_CONTROL[退出]]"
        )
    if kind == ACTION_ORDINARY and not (target_semantics or semantics):
        raise AdviceRejected(
            "REJECT: an ordinary-control candidate must say which element it means "
            "(target_semantics or candidate_semantics)"
        )

    anchor = payload.get("target_anchor")
    if anchor is not None:
        if not isinstance(anchor, Mapping) or not str(anchor.get("text") or "").strip():
            raise AdviceRejected(
                "REJECT: target_anchor must be an object naming the text it is anchored to, e.g. "
                '{\"text\": \"说明\", \"dy_norm\": -0.045}'
            )
        anchor = dict(anchor)

    point = payload.get("target_point")
    if point is not None:
        point = _norm_point(point)
        if point is None:
            raise AdviceRejected("REJECT: target_point is not a point inside the frame")
    box = payload.get("target_bbox")
    if box is not None:
        box = _norm_box(box)
        if box is None:
            raise AdviceRejected("REJECT: target_bbox is not a box inside the frame")

    alternatives = payload.get("alternative_actions") or ()
    if isinstance(alternatives, str):
        alternatives = [alternatives]
    alternatives = tuple(str(item) for item in alternatives)

    return Advice(
        request_id=request_id,
        unknown_type=unknown_type,
        candidate_semantics=semantics,
        proposed_action=proposed,
        expected_result=str(payload["expected_result"]),
        uncertainty=str(payload["uncertainty"]),
        target_point=point,
        target_bbox=box,
        alternative_actions=alternatives,
        note=str(payload.get("note") or ""),
        answered_at=_now(),
        action_kind=kind,
        target_semantics=target_semantics,
        target_anchor=anchor,
        grounding_basis=str(payload.get("grounding_basis") or ""),
        grounding_ref=str(payload.get("grounding_ref") or ""),
        notification=str(payload.get("notification") or "").strip(),
        entry=str(payload.get("entry") or "").strip(),
        action_level=level,
    )


def infer_action_kind(proposed: str, *, registry: Any = None) -> str | None:
    """Which of §二's three shapes ``proposed_action`` is, or ``None`` when it is none of them.

    Read from the action's own syntax first, because the syntax is unambiguous: ``L1[...]`` and
    ``ORDINARY_CONTROL[...]`` are the shapes this project already writes into its ledgers.  A bare
    name is a skill only if the registry really has it -- that check is what stops an invented
    action from arriving through an answer, and it is kept here rather than dropped.
    """
    text = str(proposed or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper.startswith("L1[") or upper.startswith("L1_ACTION["):
        return ACTION_L1
    if upper.startswith("ORDINARY_CONTROL[") or upper.startswith("ORDINARY_CONTROL:"):
        return ACTION_ORDINARY
    if registry is not None and registry.get(text) is not None:
        return ACTION_SKILL
    if registry is None:
        # Nothing to check a bare name against at this layer.  The old contract did the same, and
        # the checker that matters -- ``tools/unknown_advisor.py`` -- always passes a real registry,
        # so an invented skill is refused where it is written rather than where it is read.
        return ACTION_SKILL
    return None


def l1_target(proposed: str) -> str:
    """The control an ``L1[...]`` action names, or ``""`` when the shape is wrong."""
    text = str(proposed or "").strip()
    for prefix in ("L1[", "l1[", "L1_ACTION[", "l1_action["):
        if text.startswith(prefix):
            inner = text[len(prefix):]
            # Exactly one closing bracket: ``L1[ORDINARY_CONTROL[退出]]`` nests, so stripping every
            # trailing ``]`` would eat the inner control's own bracket and name a control that does
            # not exist in the ledger.
            if inner.endswith("]"):
                inner = inner[:-1]
            return inner.strip()
    return ""


def ordinary_target(proposed: str, semantics: Iterable[str] = ()) -> str:
    """The element an ``ORDINARY_CONTROL[...]`` action names, or the first semantic offered."""
    text = str(proposed or "").strip()
    upper = text.upper()
    for prefix in ("ORDINARY_CONTROL[", "ORDINARY_CONTROL:"):
        if upper.startswith(prefix):
            inner = text[len(prefix):]
            if inner.endswith("]"):
                inner = inner[:-1]
            return inner.strip()
    for item in semantics:
        if str(item or "").strip():
            return str(item).strip()
    return ""


def advice_staleness(
    advice: Advice,
    request: UnknownRequest | None,
    *,
    page_key: str,
    goal: str,
) -> str:
    """Why this answer may not be used on the screen in front of us, or ``""`` when it may (§四).

    An answer is a claim about a *screen and a purpose*, and both travel in the request it answers.
    Reusing it elsewhere is how an asynchronous channel turns into a wrong tap: a reasoner answered
    about 燃霜矿区 under the DAILY goal, and the AUTO is now on 挂机收益 pursuing TRAIN.  The check
    is deliberately about identity rather than about how old the file is -- an old answer about the
    same screen and the same goal is still a correct answer.

    It does **not** decide whether the element is still drawn: that is a measurement on the current
    frame (the point has to fall inside a region this frame really has), and it is made separately
    so a moved control is re-*located* rather than merely refused.
    """
    if request is None:
        return "NO_REQUEST_FOR_THIS_SCREEN"
    if str(request.page_key or "") != str(page_key or ""):
        return "PAGE_CHANGED"
    if str(request.goal or "") != str(goal or ""):
        return "GOAL_CHANGED"
    return ""


def _norm_point(value: Any) -> tuple[float, float] | None:
    if isinstance(value, Mapping):
        try:
            value = (value["x_norm"], value["y_norm"])
        except (KeyError, TypeError):
            return None
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return (round(x, 4), round(y, 4))


def _norm_box(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        box = {
            "x_norm": float(value["x_norm"]),
            "y_norm": float(value["y_norm"]),
            "w_norm": float(value["w_norm"]),
            "h_norm": float(value["h_norm"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if box["w_norm"] <= 0 or box["h_norm"] <= 0:
        return None
    if not (0.0 <= box["x_norm"] <= 1.0 and 0.0 <= box["y_norm"] <= 1.0):
        return None
    if box["x_norm"] + box["w_norm"] > 1.0 + 1e-6 or box["y_norm"] + box["h_norm"] > 1.0 + 1e-6:
        return None
    return {key: round(val, 4) for key, val in box.items()}


def justified_point(
    advice: Advice,
    boxes: Iterable[Mapping[str, Any]],
    *,
    slop: float = POINT_SLOP_NORM,
) -> tuple[float, float] | None:
    """The advice's point **only if this frame's own evidence puts something there**, else ``None``.

    This is §四's "有合理的当前画面定位依据" made mechanical: an answer may choose which of the
    frame's real elements to use, but it cannot invent one.  A point that matches no region the
    frame supplied (or an answer that carries only a bbox, which is then used when it *is* over
    one) is refused, and the step ends honestly instead of tapping an unmeasured coordinate.

    A thin wrapper over :func:`grounded_region`, so the rule has exactly one implementation and
    "may this be tapped" and "what did the frame draw there" can never drift apart.
    """
    region = grounded_region(advice, boxes, slop=slop)
    if region is None:
        return None
    point = region.get("point")
    if point is None:
        return None
    return (float(point[0]), float(point[1]))


def grounded_region(
    advice: Advice,
    regions: Iterable[Mapping[str, Any]],
    *,
    slop: float = POINT_SLOP_NORM,
    points: Iterable[tuple[float, float]] = (),
) -> dict[str, Any] | None:
    """The region of the **current** frame that justifies this answer's point, or ``None``.

    ``justified_point`` answers "may this point be tapped"; this answers "what did the frame draw
    there", which is what the collector crops, what the ledger records and what makes an anchored or
    template-based answer auditable afterwards.  The basis returned is the one the *frame* supplied
    -- ``regions`` is built by the caller from its own measurements -- so a reasoner's claim about
    how it anchored never becomes the record.

    ``points`` is how an answer that carries **no coordinate at all** can still be grounded.  Its
    only member is the centre of a region the caller derived from this frame's own evidence (for a
    wordless element: the region ``ui_collection.anchored_region`` computed from a text box the
    frame really drew, see §三).  The rule is unchanged: the point still has to fall inside a region
    on this frame, so this adds a way for a grounded answer to *name* its point and not a way to
    invent one.
    """
    candidates: list[tuple[float, float]] = []
    if advice.target_point is not None:
        candidates.append(advice.target_point)
    if advice.target_bbox is not None:
        box = advice.target_bbox
        candidates.append(
            (round(box["x_norm"] + box["w_norm"] / 2, 4), round(box["y_norm"] + box["h_norm"] / 2, 4))
        )
    for point in points:
        try:
            candidates.append((round(float(point[0]), 4), round(float(point[1]), 4)))
        except (TypeError, ValueError, IndexError):
            continue
    region_list = [dict(region) for region in regions]
    for point in candidates:
        for region in region_list:
            box = region.get("box_norm") if isinstance(region.get("box_norm"), Mapping) else region
            try:
                x, y = float(box["x_norm"]), float(box["y_norm"])
                w, h = float(box["w_norm"]), float(box["h_norm"])
            except (KeyError, TypeError, ValueError):
                continue
            if x - slop <= point[0] <= x + w + slop and y - slop <= point[1] <= y + h + slop:
                out = dict(region)
                out["point"] = point
                return out
    return None


def boxes_from_request(request: UnknownRequest) -> list[dict[str, Any]]:
    """The OCR boxes an answer's point has to fall inside, from the request's own record."""
    return [dict(box) for box in request.ocr_boxes if isinstance(box, Mapping)]


def box_containing(point: tuple[float, float], boxes: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The frame's own OCR box a point landed in, or ``None``.

    Used by the collector past (directive §五): the element that gets cropped and remembered is the
    region this frame really drew, not a box the answer supplied.  A point that sits on no box is a
    point ``justified_point`` would already have refused, so ``None`` here means "nothing to file".
    """
    for box in boxes:
        try:
            x, y = float(box["x_norm"]), float(box["y_norm"])
            w, h = float(box["w_norm"]), float(box["h_norm"])
        except (KeyError, TypeError, ValueError):
            continue
        if x <= point[0] <= x + w and y <= point[1] <= y + h:
            return dict(box)
    return None


class UnknownAdvisor:
    """The runtime's side of the queue: write a request, read an answer, never wait.

    Held once per run and bounded twice (§二/§六): at most ``MAX_REQUESTS_PER_RUN`` new requests,
    and never the same (screen, question) inside ``REQUEST_COOLDOWN_SECONDS``.  Both bounds exist
    because the AUTO must not spend its cycle on questions -- a request is written so that a later
    cycle (or a WorkBuddy session, or an operator) can answer it, and until then the chain this
    project already has stays in charge.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else REQUEST_ROOT
        self._written = 0
        self._asked: set[str] = set()

    # ------------------------------------------------------------------ the ask

    def ask(self, request: UnknownRequest, *, force: bool = False) -> bool:
        """Write one request if the bounds allow; return whether it was written.

        Never blocks, never calls out: the file *is* the question.  ``False`` means either the run
        has already asked its share or the same question is already on file, which is the answer to
        "should this step stop to ask" -- no.

        ``force`` skips the cooldown and nothing else.  It exists for one case (§四): the answer on
        file turned out to be about a different screen or a different goal, so the question is
        genuinely unanswered again, and waiting an hour for a new one would leave the screen
        unanalysed for no reason.  The per-run bound still applies, so this cannot become a
        question generator.
        """
        if self._written >= MAX_REQUESTS_PER_RUN:
            return False
        key = request.request_id
        if key in self._asked and not force:
            return False
        if not force:
            existing = self.read_request(key)
            if existing is not None and _seconds_since(existing.created_at) < REQUEST_COOLDOWN_SECONDS:
                self._asked.add(key)
                return False
        self.root.mkdir(parents=True, exist_ok=True)
        request.created_at = _now()
        path = self.root / f"{key}.json"
        path.write_text(json.dumps(request.as_row(), ensure_ascii=False, indent=1), encoding="utf-8")
        self._asked.add(key)
        self._written += 1
        return True

    def read_request(self, key: str) -> UnknownRequest | None:
        path = self.root / f"{key}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        data = dict(payload)
        for name in ("ocr_texts", "ocr_boxes"):
            data[name] = tuple(data.get(name) or ())
        return UnknownRequest(
            **{k: v for k, v in data.items() if k in UnknownRequest.__dataclass_fields__}
        )

    # ------------------------------------------------------------------ the answer

    def take(self, key: str, *, registry: Any = None) -> Advice | None:
        """The answer already on disk for one request, validated, or ``None``.

        Reads and returns -- there is no wait, no poll and no retry in here.  An answer that fails
        validation is moved aside rather than deleted (``<id>.rejected.json``), because "what the
        reasoner said" is evidence about the reasoner, and the directive's §五 wants the record.
        """
        answer_path = self.root / ANSWERS_DIR / f"{key}.json"
        if not answer_path.exists():
            return None
        try:
            payload = json.loads(answer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            advice = parse_advice(payload, request_id=key, registry=registry)
        except AdviceRejected as exc:
            try:
                answer_path.replace(answer_path.with_suffix(".rejected.json"))
                (self.root / ANSWERS_DIR / f"{key}.rejected.reason").write_text(str(exc), encoding="utf-8")
            except OSError:
                pass
            return None
        return advice

    def pending(self) -> list[UnknownRequest]:
        """Every request with no answer yet -- what a reasoner should look at, newest first."""
        out: list[UnknownRequest] = []
        if not self.root.exists():
            return out
        for path in sorted(self.root.glob("*.json")):
            answer = self.root / ANSWERS_DIR / path.name
            if answer.exists():
                continue
            request = self.read_request(path.stem)
            if request is not None:
                out.append(request)
        out.sort(key=lambda item: item.created_at or "", reverse=True)
        return out


def build_request(
    *,
    unknown_type: str,
    page_label: str,
    page_key: str,
    frame_path: Path | str,
    goal: str = "",
    page_confidence: float | None = None,
    ocr_texts: Sequence[str] = (),
    ocr_boxes: Sequence[Mapping[str, Any]] = (),
    entry_page: str = "",
    entry_trigger: str = "",
    world_state: Mapping[str, Any] | None = None,
    template_match: str = "",
    ledger_match: str = "",
    last_attempt: Mapping[str, Any] | None = None,
    before_frame_path: Path | str = "",
    after_frame_path: Path | str = "",
    question: str = "",
    situation: str = "",
    character: str = "",
) -> UnknownRequest:
    """Assemble one request from evidence the caller already has.  Pure; writes nothing."""
    digest = frame_digest(frame_path)
    return UnknownRequest(
        request_id=request_id(page_key, unknown_type),
        frame_digest=digest,
        unknown_type=unknown_type,
        page_label=str(page_label or ""),
        page_key=str(page_key or ""),
        goal=str(goal or ""),
        frame_path=str(frame_path or ""),
        page_confidence=page_confidence,
        ocr_texts=tuple(str(text) for text in ocr_texts),
        ocr_boxes=tuple(dict(box) for box in ocr_boxes),
        entry_page=str(entry_page or ""),
        entry_trigger=str(entry_trigger or ""),
        world_state=dict(world_state or {}),
        template_match=str(template_match or ""),
        ledger_match=str(ledger_match or ""),
        last_attempt=dict(last_attempt or {}),
        before_frame_path=str(before_frame_path or ""),
        after_frame_path=str(after_frame_path or ""),
        question=str(question or ""),
        situation=str(situation or ""),
        character=str(character or ""),
    )
