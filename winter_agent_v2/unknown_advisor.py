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
OPTIONAL_ANSWER_FIELDS = ("target_point", "target_bbox", "alternative_actions", "note")

#: The same boundary the ordinary-control resolver draws, restated here so a *reasoner* cannot be
#: the way around it: an answer carrying any of these is refused before it is even parsed into a
#: candidate.
REFUSED_WORDS: tuple[str, ...] = (
    "充值",
    "购买",
    "支付",
    "钻石",
    "礼包",
    "特惠",
    "首充",
    "月卡",
    "基金",
    "招募",
    "加速",
    "花费",
    "消费",
    "立即完成",
    "buy",
    "purchase",
    "pay",
    "gems",
)

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

    # The boundary first: an answer that mentions a purchase is refused whatever else it says,
    # over every string it carries, exactly as the resolver screens a whole frame.
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for word in REFUSED_WORDS:
        if word.lower() in blob:
            raise AdviceRejected(f"REJECT: answer mentions {word!r}, which no advice may propose")

    semantics = payload["candidate_semantics"]
    if isinstance(semantics, str):
        semantics = [semantics]
    if not isinstance(semantics, (list, tuple)) or not all(isinstance(item, str) for item in semantics):
        raise AdviceRejected("REJECT: candidate_semantics must be a list of strings")

    proposed = str(payload["proposed_action"]).strip()
    if not proposed:
        raise AdviceRejected("REJECT: empty proposed_action")
    # A proposed action must name a skill this project already has.  The one it is *expected* to
    # name is the ordinary-control attempt; naming anything else is allowed only if it is real,
    # so an invented skill cannot arrive through an answer.
    if registry is not None and registry.get(proposed) is None:
        raise AdviceRejected(f"REJECT: unknown skill {proposed!r}")

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
        candidate_semantics=tuple(str(item) for item in semantics),
        proposed_action=proposed,
        expected_result=str(payload["expected_result"]),
        uncertainty=str(payload["uncertainty"]),
        target_point=point,
        target_bbox=box,
        alternative_actions=alternatives,
        note=str(payload.get("note") or ""),
        answered_at=_now(),
    )


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
    """The advice's point **only if this frame's own OCR puts text there**, else ``None``.

    This is §四's "有合理的当前画面定位依据" made mechanical: an answer may choose which of the
    frame's real controls to use, but it cannot invent a control.  A point that matches no text box
    (or an answer that carries only a bbox, which is then used when it *is* over a text box) is
    refused, and the step ends honestly instead of tapping an unmeasured coordinate.
    """
    candidates: list[tuple[float, float]] = []
    if advice.target_point is not None:
        candidates.append(advice.target_point)
    if advice.target_bbox is not None:
        box = advice.target_bbox
        candidates.append(
            (round(box["x_norm"] + box["w_norm"] / 2, 4), round(box["y_norm"] + box["h_norm"] / 2, 4))
        )
    for point in candidates:
        for box in boxes:
            try:
                x, y = float(box["x_norm"]), float(box["y_norm"])
                w, h = float(box["w_norm"]), float(box["h_norm"])
            except (KeyError, TypeError, ValueError):
                continue
            if x - slop <= point[0] <= x + w + slop and y - slop <= point[1] <= y + h + slop:
                return point
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

    def ask(self, request: UnknownRequest) -> bool:
        """Write one request if the bounds allow; return whether it was written.

        Never blocks, never calls out: the file *is* the question.  ``False`` means either the run
        has already asked its share or the same question is already on file, which is the answer to
        "should this step stop to ask" -- no.
        """
        if self._written >= MAX_REQUESTS_PER_RUN:
            return False
        key = request.request_id
        if key in self._asked:
            return False
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
    )
