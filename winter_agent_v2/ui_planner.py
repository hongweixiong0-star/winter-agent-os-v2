"""The structured-UI-action protocol, and the local planner that fills it in.

Operator directive 2026-09-25, sections 3–8, extended by the 2026-09-30 model migration.
When no registered skill can advance a goal, the *how* has to come from somewhere, and it is
the local GUI model that supplies it — as **structured UI actions**, never as coordinates:

    fresh screenshot + goal + this frame's measured elements + the actions MAA can perform
        -> the model picks an element id and an action type
        -> validated against the same frame
        -> the existing executor taps the element it located
        -> the existing verifier judges the result

The screenshot is the part that changed on 2026-09-30.  Until then the packet carried a goal,
a page name and an OCR table and **no picture**, so the model was answering about a screen it
could not see; ``ui_planner`` now attaches the request's own ``frame_path`` to every call and
``local_gui_model`` refuses to send a text-only turn.  Measured on that directive: asked
blind, the model invented "Play for Free" on a screen that does not contain it; asked with
the frame, it read the real in-game text.  ``tools/probe_gui_model_multimodal.py`` reproduces
the comparison.

Three properties that are enforced here rather than trusted
-----------------------------------------------------------
* **No coordinates, in either direction.**  ``FORBIDDEN_KEYS`` is scanned recursively in the
  reply, so a model that answers ``{"x": 340, "y": 812}`` is refused by name instead of
  being quietly ignored.  And the packet's element table carries only ``id``, the client's
  own ``text``, a semantic name and a coarse area — the planner is never shown a pixel, so
  there is nothing to transport for the element path.  The tap point is produced later, from
  the frame, by ``unknown_advisor.grounded_region`` — the same grounding the verified advice
  path uses.  The one deliberate exception is ``VISION_BOX_KEY`` below, and it is deliberate
  precisely because it is *not* trusted.
* **Only what was offered.**  ``target_element_id`` must be one of the ids this frame
  produced, and the action must be one the call site can actually carry out.  ``INPUT_TEXT``
  is named in ``UNSUPPORTED_ACTIONS`` and refused with its own reason, because there is no
  text-entry path in this project yet and pretending otherwise would be the kind of
  "listed but not implemented" capability the constitution forbids.
* **A proposal, never a verdict.**  ``COMPLETE`` is recorded as a *claim* and changes no
  state: only the Verifier confirms a goal, and the runtime keeps its own path doing that.

The visual channel, and why the box is untrusted
------------------------------------------------
``elements == []`` used to end the step: with an empty table the model had nothing to name,
so a screen whose controls carry no text was unplannable no matter what it looked like.  The
directive is explicit that this must not continue, because a picture *can* answer it.  So
when the table is empty (or when the model judges no listed element fits) the model may
return ``semantic_target`` plus ``candidate_bbox_norm``, and that box is treated as
``UNTRUSTED_CURRENT_FRAME_PROPOSAL``:

    untrusted box -> this frame's own regions -> grounded_region/justified_point -> tap

The box never becomes a tap point by itself, and it is never filed as knowledge: the learned
record keeps the semantic name, not the number.  See ``_advice_for`` and the ``§「坐标不是知识」``
rule this mirrors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import local_gui_model
from . import unknown_advisor

#: Section 5's decision vocabulary.  Exactly these words, no synonyms.
DECISIONS = ("EXECUTE", "OBSERVE", "REPLAN", "COMPLETE", "DEFER", "BLOCKED")

#: Section 7's general capabilities.  What the *executor* finally issues stays the four
#: kinds ``Executor.execute`` implements (``TAP_SEMANTIC``/``PRESS_BACK``/``SWIPE``/
#: ``OBSERVE``); these names are the semantic layer above them.
ACTION_TYPES = (
    "CLICK_ELEMENT", "OPEN_PAGE", "BACK", "SCROLL", "SELECT_OPTION",
    "INPUT_TEXT", "CLOSE_POPUP", "OBSERVE", "WAIT_STATE", "VERIFY_STATE",
)

#: Named but not offered.  ``INPUT_TEXT`` is refused with its own reason rather than
#: silently dropped, so the gap is visible in the record instead of looking like a model
#: failure.  There is no keyboard/text-entry path on this project's executor yet.
UNSUPPORTED_ACTIONS = {"INPUT_TEXT": "UI_ACTION_INPUT_TEXT_NOT_IMPLEMENTED"}

#: Actions this call site can carry out, i.e. the ones a plan may actually use.  A BACK or
#: a SCROLL is *legal* per section 7, but this resolver can only return a point, so they are
#: not offered here and a plan asking for them is deferred to the recovery paths that
#: already own them -- better an honest boundary than a decision that silently does nothing.
OFFERED_ACTIONS = ("CLICK_ELEMENT", "OPEN_PAGE", "SELECT_OPTION", "CLOSE_POPUP", "OBSERVE")

#: Keys whose presence means the reply transported geometry.  Checked recursively, and this
#: is the element path's guard: a model that answers with a pixel is refused by name.
#: ``VISION_BOX_KEY`` is the one deliberate exception, handled in ``_find_forbidden``.
FORBIDDEN_KEYS = (
    "x", "y", "x1", "y1", "x2", "y2", "x_norm", "y_norm", "coord", "coords",
    "coordinate", "coordinates", "point", "tap", "tap_point", "tap_x", "tap_y",
    "pixel", "pixels", "box", "bbox", "rect",
)

#: The one key a reply may use to propose a region, and only as an **untrusted** proposal.
#: It exists because a screen can be full of controls that print nothing -- an icon, an
#: unlabelled close button, an event entrance drawn as art -- and with an empty element table
#: the model had no way to point at any of them.  The box is normalised (0..1) so a pixel
#: coordinate cannot ride in on it, it must be a 4-number list rather than a nested object
#: (so no ``x``/``y`` key appears anywhere), and the runtime still refuses to tap it unless
#: this same frame drew a region under it -- see ``unknown_advisor.justified_point``.
VISION_BOX_KEY = "candidate_bbox_norm"

#: The four normalised numbers, in the order ``_norm_box`` reads them back.
VISION_BOX_ORDER = ("x_norm", "y_norm", "w_norm", "h_norm")

#: The decisions that mean "do not tap this step".  Each one is recorded with its own
#: reason; none of them is allowed to stop the cycle (section 7 of the master rules).
NON_TAPPING_DECISIONS = ("OBSERVE", "REPLAN", "COMPLETE", "DEFER", "BLOCKED")

#: The two ways an EXECUTE can be justified, recorded in the ledger so "the model named one
#: of this screen's own elements" and "the model claimed a region we could not confirm" are
#: never confused after the fact.
BASIS_ELEMENT = "FRAME_ELEMENT"
BASIS_VISION_PROPOSAL = "UNTRUSTED_CURRENT_FRAME_PROPOSAL"

#: The reason every refusal is filed under when the model is simply not there.
PLANNER_UNAVAILABLE = "LOCAL_PLANNER_UNAVAILABLE"

SYSTEM_PROMPT = """You are the UI action planner of a screenshot-driven game automation agent.

You are shown the CURRENT screenshot of one game screen. Look at it.

You will also be given, for the same screen:
- goal: the task the Global Scheduler has ALREADY decided to pursue. You do NOT choose goals,
  you do NOT switch to another task, and you do NOT reconsider priorities. Your only question
  is: for this goal, what is the next thing to do on this screen?
- current_page: what the page model read this screen as.
- available_elements: the UI elements that were ACTUALLY measured on this screen right now.
  Each has an id, the text the client itself printed on it, a semantic name and a coarse area.
  When a "kind" is present it says what the element is: COMPOSITE_CONTROL is a control drawn as
  an icon with its name printed underneath (the id names the icon, which is what you would
  press); TEXT_LABEL is printed information -- a town name, a resource count -- and is NOT a
  button.
- available_actions: the action types you are allowed to return. Nothing else is legal.
- last_action / last_result / remaining_steps: what this session already tried and how much of
  its budget is left. If your previous step did not change anything, do NOT repeat it.

Choose the single next UI action toward the goal.

Hard rules:
1. Prefer naming an id that appears in available_elements. Never invent an element id.
2. You may only use an action from available_actions, and you may only CLICK an element whose
   "executable" is not false. A TEXT_LABEL is a name, not a control.
3. When NO listed element can serve the goal -- the table is empty, or the control you need is
   an icon or a picture with no text -- you MAY instead name what you are aiming at in words
   ("semantic_target") and, optionally, where it is as "candidate_bbox_norm": a list of four
   numbers [x, y, width, height], each between 0 and 1, measured as a fraction of the image.
   That box is only a PROPOSAL: the client re-checks it against the live screen and refuses it
   if nothing real is there. Never output pixel coordinates, and never use x/y/key names.
4. Never propose an element, banner or button that spends money, gems, items or speedups
   unless the goal is exactly that.
5. Reply with JSON only, exactly this shape:
   {"goal": str, "decision": str, "action": {"type": str, "target_element_id": str|null},
    "semantic_target": str|null, "candidate_bbox_norm": [x, y, w, h]|null,
    "expected": {"page": str, "result": str}, "confidence": 0.0, "reason": str}
6. decision must be one of: EXECUTE, OBSERVE, REPLAN, COMPLETE, DEFER, BLOCKED.
   - EXECUTE: carry out the action now; name a target_element_id, or a semantic_target plus box.
   - OBSERVE: the screen is not readable enough yet; tap nothing.
   - REPLAN: your previous step cannot work from here; tap nothing.
   - COMPLETE: the goal's own result is visible on this screen -- you can see that it is done.
     This is a claim; a separate verifier checks it. Do NOT use it just because you see nothing
     useful here.
   - DEFER: this screen is not the goal's screen, or the goal cannot be advanced from here.
     Use this when the page does not belong to the goal. The scheduler will switch tasks.
   - BLOCKED: the needed capability does not exist. State the gap in "reason".
   Measured 2026-09-25: asked for DAILY_ROUTINE while the client stood on the INTEL page with no
   relevant control, the model answered COMPLETE. The right answer was DEFER, and COMPLETE-vs-DEFER
   is decided by whether the goal's own result is on screen -- not by the absence of anything to do.
7. Prefer an element whose printed text directly names the action the goal needs. Prefer a
   low-risk control (close, back, confirm-free, claim-free) over anything that spends.
   "confidence" is your own 0..1 estimate; be honest, a low number is useful information.
8. "reason" is one short sentence, in the language of the client's own text.
   Measured 2026-09-30: the model writes **112-160 output tokens per plan whatever this rule
   asks for** -- asking it more firmly for <=20 characters changed p50 from 11.5s to 12.4s,
   i.e. not at all (noise). Output runs at ~16 tok/s here, so ~7-9s of every step is
   generation and it is not prompt-controllable. What contains it is the step and run budgets
   (``max_steps_per_screen`` / ``max_steps_per_run``), not this line. Recorded so the next
   account does not spend a cycle re-learning it.
"""


@dataclass(frozen=True)
class Plan:
    """One validated planner reply."""

    decision: str
    action_type: str = ""
    target_element_id: str = ""
    target_text: str = ""
    expected_page: str = ""
    expected_result: str = ""
    reason: str = ""
    goal: str = ""
    #: What the model said it was aiming at, when it could not name one of this frame's own
    #: elements.  Kept as words: words become a semantic name, a box does not.
    semantic_target: str = ""
    #: The model's own region proposal, already normalised to 0..1.  This is **not** a tap
    #: point and is never acted on directly -- it only travels to
    #: ``unknown_advisor.justified_point``, which refuses it unless this same frame drew a
    #: region under it.  Recorded so a refusal is auditable afterwards.
    candidate_bbox_norm: tuple[float, float, float, float] | None = None
    #: ``BASIS_ELEMENT`` or ``BASIS_VISION_PROPOSAL``.
    basis: str = BASIS_ELEMENT
    #: The model's own 0..1 confidence.  Advisory only; nothing branches on it yet, and it is
    #: recorded so a threshold can be chosen from measurements rather than invented.
    confidence: float = 0.0

    def to_row(self, *, page_key: str = "", source: str = "LOCAL_GUI_MODEL") -> dict[str, Any]:
        # The box is written with its basis so a later reader can never mistake a proposal for
        # a measurement.  It is deliberately a *list of four normalised numbers* under a key
        # that says "proposal": the rule is that a coordinate may not become knowledge, and a
        # key that reads as a confirmed position is the first step to it becoming one.
        box = list(self.candidate_bbox_norm) if self.candidate_bbox_norm else None
        return {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "page_key": page_key,
            "goal": self.goal,
            "decision": self.decision,
            "action_type": self.action_type,
            "target_element_id": self.target_element_id,
            "target_text": self.target_text,
            "semantic_target": self.semantic_target,
            "basis": self.basis,
            "proposed_region_untrusted": box,
            "confidence": round(float(self.confidence), 3),
            "expected_page": self.expected_page,
            "expected_result": self.expected_result,
            "reason": self.reason[:300],
        }


@dataclass(frozen=True)
class PlanParse:
    """The result of reading a reply: either a plan, or the reason there is none."""

    plan: Plan | None = None
    error: str = ""
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.plan is not None


# ---------------------------------------------------------------------------- elements
def _area_of(box: Any) -> str:
    """A coarse vertical band, so two identically-worded elements can be told apart.

    Coarse on purpose: "the 确定 near the bottom" is enough to disambiguate, and a precise
    number would be the beginning of the model reasoning about pixels.
    """
    if not isinstance(box, Mapping):
        return ""
    top = box.get("y_norm", box.get("y1", box.get("top")))
    height = box.get("h_norm", box.get("height"))
    try:
        y = float(top)
    except (TypeError, ValueError):
        return ""
    band = ("top", "upper", "middle", "lower", "bottom")
    index = min(len(band) - 1, max(0, int(y * len(band))))
    if isinstance(height, (int, float)) and float(height) > 0.2:
        return band[index] + "+large"
    return band[index]


def elements_from_request(request: Any) -> list[dict[str, Any]]:
    """This screen's own measured elements, from the request's recorded OCR.

    ``build_request`` already stores what this frame drew (``ocr_texts`` beside
    ``ocr_boxes``), and that is the right source rather than a fresh OCR pass: the element
    table the model sees is then *exactly* the evidence the question was filed with, and a
    plan naming ``E4`` always refers to something this screen really printed.
    """
    texts = [str(t) for t in (getattr(request, "ocr_texts", ()) or ())]
    boxes = [b for b in (getattr(request, "ocr_boxes", ()) or ())]
    elements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, text in enumerate(texts):
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        box = boxes[index] if index < len(boxes) else {}
        if isinstance(box, Mapping) and box.get("text"):
            # Some callers store the text inside the box record instead of beside it.
            text = str(box.get("text") or text).strip() or text
        entry = {
            "id": f"E{len(elements) + 1}",
            "text": text,
            "area": _area_of(box),
        }
        # The identity travels with the element when the frame measured one.  ``kind`` is the whole
        # point of §2: ``COMPOSITE_CONTROL`` is an icon whose meaning is its printed label and whose
        # region is that icon; ``TEXT_LABEL`` is information.  Only the former may be clicked.
        kind = str(box.get("element_kind") or "") if isinstance(box, Mapping) else ""
        if kind:
            entry["kind"] = kind
            entry["semantic"] = str(box.get("element_semantic") or "")
            entry["executable"] = bool(box.get("element_executable"))
        elements.append(entry)
    return elements


def build_packet(
    *,
    goal: str,
    role_id: str = "",
    current_page: str,
    world_state: Mapping[str, Any] | None = None,
    elements: list[dict[str, Any]] | None = None,
    actions: tuple[str, ...] = OFFERED_ACTIONS,
    relevant_knowledge: list[str] | None = None,
    last_action: str | None = None,
    last_result: str | None = None,
    remaining_steps: int = 0,
    step_index: int = 0,
    max_elements: int = 30,
) -> dict[str, Any]:
    """Section 4's packet, and nothing more.

    The caps are the point: the directive's own words are "不要将全部游戏知识库、完整历史日志
    和无关任务信息塞入模型上下文", and an 8K budget is only a budget if the caller enforces it.

    ``screenshot`` is a *statement of fact about the call*, not a datum: since 2026-09-30 the
    frame is attached as an image part alongside this text, and saying so in the packet keeps
    the model from concluding the text is all it has.  Its value is True by construction --
    ``local_gui_model`` refuses a text-only turn while ``multimodal`` is on -- so it cannot
    drift out of step with reality the way a hand-maintained flag would.
    """
    return {
        "goal": str(goal or ""),
        "role_id": str(role_id or ""),
        "current_page": str(current_page or ""),
        "screenshot": "attached as an image; it is the CURRENT frame, look at it",
        "step_index": int(step_index),
        "world_state": _compact(world_state or {}, keys=(
            "page", "confidence", "stamina", "march", "queue", "resources",
            "training", "research", "building", "player", "hospital", "defense",
        )),
        "available_elements": list(elements or [])[:max_elements],
        "available_actions": list(actions),
        "relevant_knowledge": [str(k)[:200] for k in (relevant_knowledge or [])[:3]],
        "last_action": None if last_action is None else str(last_action)[:200],
        "last_result": None if last_result is None else str(last_result)[:200],
        "remaining_steps": int(remaining_steps),
    }


def _compact(state: Mapping[str, Any], *, keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key not in state:
            continue
        value = state[key]
        if isinstance(value, Mapping):
            value = {k: value[k] for k in list(value)[:8]}
        elif isinstance(value, (list, tuple)):
            value = list(value)[:8]
        out[key] = value
    return out


def render_packet(packet: Mapping[str, Any]) -> str:
    """The user turn.  JSON, because the reply is JSON and a table would invite prose."""
    return "This screen's packet:\n" + json.dumps(packet, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------- parsing
def _find_forbidden(node: Any, path: str = "") -> str:
    """The first forbidden geometry key in the reply, or ``""``.

    ``candidate_bbox_norm`` is skipped on purpose -- it is the one channel the directive opens
    for a screenshot-only proposal, and it is validated separately in ``_box_from_reply``,
    which accepts four normalised numbers and nothing else.  Skipping the *recursion* here is
    what makes the narrow allowance safe: the value is checked by a function that only knows
    how to read a 0..1 quadruple, so a nested ``{"x": 340, "y": 812}`` cannot hide inside it.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key).strip().lower()
            if name in FORBIDDEN_KEYS:
                return f"{path}.{name}".lstrip(".")
            if name == VISION_BOX_KEY:
                continue
            found = _find_forbidden(value, f"{path}.{name}".lstrip("."))
            if found:
                return found
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found = _find_forbidden(value, f"{path}[{index}]")
            if found:
                return found
    return ""


def _box_from_reply(value: Any) -> tuple[tuple[float, float, float, float] | None, str]:
    """Read ``[x, y, w, h]`` as normalised fractions, or say why it is not one.

    Deliberately strict, because this is the only place a reply is allowed to carry a region:
    four finite numbers, each in 0..1, with a positive size and an inside-the-frame extent.  A
    pixel coordinate fails the range check by construction (340 is not <= 1), so the
    "no pixels" rule survives the new channel without a second rule to enforce it.
    """
    if value is None:
        return None, ""
    if isinstance(value, Mapping):
        # Tolerated shape, but only if it is already normalised and complete: the model
        # occasionally answers with the four named keys.
        if not all(key in value for key in VISION_BOX_ORDER):
            return None, "PLAN_BOX_NOT_FOUR_NUMBERS"
        value = [value[key] for key in VISION_BOX_ORDER]
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            return None, "PLAN_BOX_NOT_FOUR_NUMBERS"
        numbers: list[float] = []
        for item in value:
            try:
                number = float(item)
            except (TypeError, ValueError):
                return None, "PLAN_BOX_NOT_A_NUMBER"
            if number != number or number in (float("inf"), float("-inf")):
                return None, "PLAN_BOX_NOT_A_NUMBER"
            numbers.append(round(number, 4))
        x, y, w, h = numbers
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return None, "PLAN_BOX_NOT_NORMALISED"
        if w <= 0.0 or h <= 0.0 or w > 1.0 or h > 1.0:
            return None, "PLAN_BOX_NOT_NORMALISED"
        if x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
            return None, "PLAN_BOX_OUTSIDE_FRAME"
        return (x, y, w, h), ""
    return None, "PLAN_BOX_NOT_FOUR_NUMBERS"


def parse_plan(raw: str, *, elements: list[dict[str, Any]],
               actions: tuple[str, ...] = OFFERED_ACTIONS) -> PlanParse:
    """Read one reply, or say exactly why it cannot be used.

    The refusals are named rather than merged: "the model transported a pixel" and "the
    model named an element this screen does not have" need different responses, and a
    single ``INVALID`` would make them indistinguishable in the ledger.
    """
    text = str(raw or "").strip()
    if not text:
        return PlanParse(error="PLAN_EMPTY")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return PlanParse(error=f"PLAN_NOT_JSON: {exc.msg}", raw=text[:400])
    if not isinstance(payload, Mapping):
        return PlanParse(error="PLAN_NOT_AN_OBJECT", raw=text[:400])
    geometry = _find_forbidden(payload)
    if geometry:
        return PlanParse(error=f"PLAN_TRANSPORTED_GEOMETRY: {geometry}", raw=text[:400])

    decision = str(payload.get("decision") or "").strip().upper()
    if decision not in DECISIONS:
        return PlanParse(error=f"PLAN_DECISION_UNKNOWN: {decision[:40]!r}", raw=text[:400])
    reason = str(payload.get("reason") or "").strip()
    goal = str(payload.get("goal") or "").strip()
    expected = payload.get("expected")
    expected_page = ""
    expected_result = ""
    if isinstance(expected, Mapping):
        expected_page = str(expected.get("page") or "").strip()
        expected_result = str(expected.get("result") or "").strip()
    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    raw_action = payload.get("action")
    action: dict[str, Any] = dict(raw_action) if isinstance(raw_action, Mapping) else {}
    # The flat shape is accepted as well as the nested one: the 2026-09-30 directive writes the
    # protocol flat ("action_type", "target_element_id") while the 2026-09-25 prompt it grew
    # from nests them under "action".  Reading both is tolerant parsing of one protocol, not
    # two -- and the nested shape is the one observed to work live.
    semantic_target = str(payload.get("semantic_target")
                          or action.get("semantic_target") or "").strip()
    box, box_error = _box_from_reply(payload.get(VISION_BOX_KEY))

    if decision != "EXECUTE":
        # ``basis`` stays empty: "which evidence justified the tap" is not a question a step
        # that taps nothing has an answer to, and stamping FRAME_ELEMENT on an OBSERVE would
        # make the ledger read as if a frame had justified something.
        return PlanParse(plan=Plan(decision=decision, reason=reason, goal=goal,
                                   expected_page=expected_page, expected_result=expected_result,
                                   confidence=confidence, basis=""), raw=text[:400])

    # From here on the reply claims it will act, so it owes an action channel.  Checked after
    # the non-EXECUTE return on purpose: OBSERVE/DEFER/COMPLETE legitimately carry no action,
    # and refusing them here would reject the very answers that end a step honestly.
    if raw_action is None and not any(
        key in payload for key in ("action_type", "target_element_id", "semantic_target")
    ):
        return PlanParse(error="PLAN_EXECUTE_WITHOUT_ACTION", raw=text[:400])

    action_type = str(action.get("type") or payload.get("action_type") or "").strip().upper()
    if action_type in UNSUPPORTED_ACTIONS:
        return PlanParse(error=UNSUPPORTED_ACTIONS[action_type], raw=text[:400])
    if action_type not in actions:
        return PlanParse(error=f"PLAN_ACTION_NOT_OFFERED: {action_type[:40]!r}", raw=text[:400])

    target_id = str(action.get("target_element_id")
                    or payload.get("target_element_id") or "").strip().upper()
    by_id = {str(e.get("id", "")).upper(): e for e in elements}
    if target_id and target_id not in by_id:
        # Naming an id this frame did not produce is still an outright refusal: the element
        # path's whole guarantee is "only what was offered", and a hallucinated id must not
        # silently fall through to the screenshot channel either.
        return PlanParse(error=f"PLAN_TARGET_NOT_ON_THIS_SCREEN: {target_id[:40]!r}",
                         raw=text[:400])
    if target_id:
        element = by_id[target_id]
        if element.get("executable") is False:
            # §2: "不存在可靠交互区域时，该元素不得作为可执行 CLICK 目标提供给 Qwen".  Measured
            # 2026-09-25: this is the guard that would have refused the failing step outright -- the model
            # named 登录好礼 and the element it reached was the printed label, not the control.
            return PlanParse(
                error=f"PLAN_TARGET_IS_NOT_A_CONTROL: {target_id} is {element.get('kind', '?')}",
                raw=text[:400],
            )
        target_text = str(element.get("text") or "").strip()
        if not target_text:
            # Every offered element carries the client's own printed words, so this can only
            # happen if the packet was built from something else.  Refusing beats tapping an
            # unnamed box.
            return PlanParse(error="PLAN_TARGET_HAS_NO_PRINTED_TEXT", raw=text[:400])
        return PlanParse(
            plan=Plan(
                decision=decision, action_type=action_type, target_element_id=target_id,
                target_text=target_text, expected_page=expected_page,
                expected_result=expected_result, reason=reason, goal=goal,
                basis=BASIS_ELEMENT, confidence=confidence,
            ),
            raw=text[:400],
        )

    # No usable element id.  This is the screenshot-only path: the model is pointing at
    # something it can see but cannot name from the table, which used to end the step outright
    # whenever ``elements`` was empty.  It is accepted as a **proposal** only -- the region is
    # never tapped on the model's word; ``unknown_advisor.justified_point`` still has to find a
    # region this same frame drew underneath it.
    if box_error:
        return PlanParse(error=box_error, raw=text[:400])
    if not semantic_target:
        return PlanParse(error="PLAN_EXECUTE_WITHOUT_TARGET", raw=text[:400])
    return PlanParse(
        plan=Plan(
            decision=decision, action_type=action_type, target_element_id="",
            semantic_target=semantic_target, candidate_bbox_norm=box,
            expected_page=expected_page, expected_result=expected_result, reason=reason,
            goal=goal, basis=BASIS_VISION_PROPOSAL, confidence=confidence,
        ),
        raw=text[:400],
    )


# ---------------------------------------------------------------------------- advisor
class PlannerLedger:
    """Append-only record of every planner step, including the refusals."""

    def __init__(self, path: Path | str, *, limit: int = 5000) -> None:
        self.path = Path(path)
        self.limit = int(limit)

    def append(self, row: Mapping[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rows = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
            rows.append(json.dumps(dict(row), ensure_ascii=False, default=str))
            self.path.write_text("\n".join(rows[-self.limit:]) + "\n", encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass


class ManagedAdvisor:
    """The runtime's advisor, backed by the local planner instead of an answer file.

    ``_advised_control`` already implements everything after "an answer exists": grounding
    against *this* frame, the spend screen, the semantic name, the tap, the verifier, the
    knowledge filing.  This class supplies the answer, which is the only part that used to
    depend on a WorkBuddy session, and it keeps the same four methods the runtime calls.

    ``fallback`` is the retired channel's reader.  It is **not** wired by default -- the
    directive retires it -- but it is accepted so a deployment that deliberately keeps
    reading historical answers is a config change, not a code change.
    """

    def __init__(
        self,
        *,
        client: local_gui_model.LocalGUIModel,
        ledger: PlannerLedger,
        root: Path | str,
        fallback: Any = None,
        max_steps_per_run: int = 12,
        max_steps_per_screen: int = 2,
        last_action: str | None = None,
        last_result: str | None = None,
    ) -> None:
        self.client = client
        self.ledger = ledger
        self.root = Path(root)
        self.fallback = fallback
        self.max_steps_per_run = int(max_steps_per_run)
        self.max_steps_per_screen = int(max_steps_per_screen)
        self.steps = 0
        self._per_screen: dict[str, int] = {}
        self._asked: dict[str, Any] = {}
        self._requests: dict[str, Any] = {}
        self.last_action = last_action
        self.last_result = last_result
        self.last_outcome: dict[str, Any] = {}

    # ----------------------------------------------------------- runtime interface
    def take_request(self, request: Any, *, registry: Any = None) -> unknown_advisor.Advice | None:
        """Answer one question, or ``None`` to leave the cycle without an answer.

        This is the method the runtime prefers, because a planner plans from the question's
        own evidence -- the page, the goal, and the OCR boxes this frame produced -- and so
        needs the record rather than a key.  ``take`` below exists for the same reason the
        retired reader had one: an id-only caller keeps working.
        """
        question = request if not isinstance(request, str) else self._requests.get(request)
        if question is None:
            return self._delegate_take(request, registry)
        request_id = str(getattr(question, "request_id", "") or "")
        page_key = str(getattr(question, "page_key", "") or "")
        if request_id:
            self._requests[request_id] = question

        if self.take_guard(page_key):
            return self._delegate_take(request, registry)

        elements = elements_from_request(question)
        frame_path = str(getattr(question, "frame_path", "") or "")
        if not elements and not frame_path:
            # Both channels empty: no element to name and no picture to look at.  This is the
            # only remaining "nothing to work with" case -- an empty *table* alone is not one
            # any more, because the screenshot can still answer the question, which is the
            # whole point of the 2026-09-30 migration.
            self.last_outcome = {"decision": "", "error": "PLANNER_NO_ELEMENTS_ON_THIS_SCREEN"}
            self.ledger.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": SOURCE_LOCAL_GUI_MODEL, "page_key": page_key,
                "goal": str(getattr(question, "goal", "") or ""),
                "decision": "", "error": "PLANNER_NO_ELEMENTS_ON_THIS_SCREEN",
                "element_count": 0,
            })
            return self._delegate_take(request, registry)

        packet = build_packet(
            goal=str(getattr(question, "goal", "") or ""),
            role_id=str(getattr(question, "character", "") or ""),
            current_page=page_key,
            world_state=getattr(question, "world_state", {}) or {},
            elements=elements,
            actions=OFFERED_ACTIONS,
            relevant_knowledge=self._knowledge(question),
            last_action=self.last_action,
            last_result=self.last_result,
            remaining_steps=max(0, self.max_steps_per_screen - self._per_screen.get(page_key, 0)),
            step_index=self.steps,
        )
        # The frame travels with the question.  This is the P0 fix: before 2026-09-30 these
        # four arguments were the whole call and the model never saw the screen.
        call = self.client.ask_json(
            system=SYSTEM_PROMPT, user=render_packet(packet), purpose="ui_plan",
            element_count=len(elements), image_path=frame_path or None,
        )
        self.steps += 1
        self._per_screen[page_key] = self._per_screen.get(page_key, 0) + 1
        if not call.ok:
            self.last_outcome = {"decision": "", "error": call.error}
            self.ledger.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": SOURCE_LOCAL_GUI_MODEL, "page_key": page_key,
                "goal": str(getattr(question, "goal", "") or ""),
                "decision": "", "error": call.error, "element_count": len(elements),
                "latency_ms": call.latency_ms,
            })
            return self._delegate_take(request, registry)

        parsed = parse_plan(call.text, elements=elements, actions=OFFERED_ACTIONS)
        if not parsed.ok:
            self.last_outcome = {"decision": "", "error": parsed.error}
            self.ledger.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": SOURCE_LOCAL_GUI_MODEL, "page_key": page_key,
                "goal": str(getattr(question, "goal", "") or ""),
                "decision": "", "error": parsed.error, "element_count": len(elements),
                "latency_ms": call.latency_ms, "raw": parsed.raw,
            })
            return self._delegate_take(request, registry)

        plan = parsed.plan
        assert plan is not None
        self.last_outcome = {
            "decision": plan.decision, "action_type": plan.action_type,
            "target_element_id": plan.target_element_id, "target_text": plan.target_text,
            "reason": plan.reason,
        }
        self.ledger.append(plan.to_row(page_key=page_key))
        if plan.decision != "EXECUTE":
            # OBSERVE / REPLAN / COMPLETE / DEFER / BLOCKED all mean the same thing to the
            # executor: nothing is tapped this step.  Section 8 is explicit that COMPLETE is
            # a proposal -- it is recorded here as a claim and changes no state; the
            # verifier owns the verdict.
            if plan.decision == "COMPLETE":
                self.ledger.append({
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "source": SOURCE_LOCAL_GUI_MODEL, "page_key": page_key, "goal": plan.goal,
                    "decision": "COMPLETE_CLAIM", "verified": False,
                    "note": "a claim only; only the verifier confirms a goal",
                })
            return self._delegate_take(request, registry)

        return self._advice_for(plan, question, elements, request_id)

    def ask(self, request: Any, *, force: bool = False) -> bool:
        """No question file is written: the planner answers in the same step it is asked."""
        if self.fallback is not None:
            return bool(self.fallback.ask(request, force=force))
        return False

    def take(self, key: Any, *, registry: Any = None) -> unknown_advisor.Advice | None:
        """Id-only caller.  Plans from the cached question if this process asked it."""
        return self.take_request(key, registry=registry)

    def read_request(self, key: str) -> Any:
        cached = self._requests.get(str(key))
        if cached is not None:
            return cached
        if self.fallback is not None:
            return self.fallback.read_request(key)
        return None

    def pending(self) -> list[Any]:
        return list(self.fallback.pending()) if self.fallback is not None else []

    # ----------------------------------------------------------- helpers
    def take_guard(self, page_key: str) -> bool:
        """Whether this step is out of budget.  Bounded on purpose (section 3, path D)."""
        if self.steps >= self.max_steps_per_run:
            self.last_outcome = {"decision": "", "error": "PLANNER_RUN_BUDGET_SPENT"}
            return True
        if self._per_screen.get(page_key, 0) >= self.max_steps_per_screen:
            self.last_outcome = {"decision": "", "error": "PLANNER_SCREEN_BUDGET_SPENT"}
            return True
        return False

    def note_outcome(self, request_id: str, *, verifier_ok: bool | None, skill: str = "",
                     result: str = "", evidence: Mapping[str, Any] | None = None) -> None:
        """Record what the *verifier* decided about the step this answer drove.

        The plan ledger says what the model proposed; this says what the runtime did with it and
        whether the game agreed.  Without it a model-driven step's verdict lived only in
        ``episodes.jsonl``, where nothing joins it back to the answer -- which made "the model
        acted and the verifier passed" unprovable, and let a model's own claim of success look
        the same as a verified one.

        A settlement is appended rather than folded into the plan row: the ledger is append-only
        and the proposal has to stay exactly as it was made, refusals included.  Called only for
        the step that actually consumed the answer (the runtime matches the request id per step),
        so a settlement can never be attributed to a step the model did not touch.
        """
        if not request_id:
            return
        self.ledger.append({
            "record": "outcome",
            "source": SOURCE_LOCAL_GUI_MODEL,
            "request_id": str(request_id),
            "verifier_ok": None if verifier_ok is None else bool(verifier_ok),
            "result": str(result),
            "skill": str(skill),
            "verifier_evidence": dict(evidence or {}),
        })

    def _advice_for(self, plan: Plan, question: Any, elements: list[dict[str, Any]],
                    request_id: str) -> unknown_advisor.Advice | None:
        """Translate a validated plan into the advice record the runtime already consumes.

        Two bases, one record type.  For an element plan the anchor is the client's own printed
        words read off *this* frame, so no geometry travelled through the model at all.  For a
        vision plan the model's box becomes ``target_bbox`` -- and that is the whole difference:
        ``unknown_advisor.grounded_region`` treats a ``target_bbox`` exactly like a point, i.e.
        it must coincide with a region **this frame** measured, so an invented region is refused
        by the same code that refuses an invented tap point.  The words are still offered as an
        anchor too, so a screen whose OCR did see the control can be grounded that way instead.
        """
        if plan.basis == BASIS_VISION_PROPOSAL:
            text = plan.semantic_target
            if not text:
                return None
            box = plan.candidate_bbox_norm
            target_bbox = (None if box is None else {
                "x_norm": float(box[0]), "y_norm": float(box[1]),
                "w_norm": float(box[2]), "h_norm": float(box[3]),
            })
            note = f"{plan.reason} [{BASIS_VISION_PROPOSAL}]"
            return unknown_advisor.Advice(
                request_id=request_id or str(getattr(question, "request_id", "") or ""),
                unknown_type=unknown_advisor.UNKNOWN_CONTROL,
                candidate_semantics=(text,),
                proposed_action=text,
                expected_result=plan.expected_result or plan.expected_page or plan.reason,
                uncertainty=SOURCE_LOCAL_GUI_MODEL,
                source=SOURCE_LOCAL_GUI_MODEL,
                action_kind=unknown_advisor.ACTION_ORDINARY,
                target_semantics=text,
                # Both are hints, neither is a tap point: the anchor grounds only if this
                # frame's OCR printed the words, the box grounds only if this frame drew a
                # region under it.  If neither holds the step ends without tapping.
                target_anchor={"text": text},
                target_bbox=target_bbox,
                note=note,
                answered_at=datetime.now(timezone.utc).isoformat(),
                action_level=unknown_advisor.LEVEL_ENTRY,
                grounding_basis=BASIS_VISION_PROPOSAL if target_bbox is not None else "",
            )
        text = plan.target_text
        if not text:
            return None
        return unknown_advisor.Advice(
            request_id=request_id or str(getattr(question, "request_id", "") or ""),
            unknown_type=unknown_advisor.UNKNOWN_CONTROL,
            candidate_semantics=(text,),
            proposed_action=text,
            expected_result=plan.expected_result or plan.expected_page or plan.reason,
            uncertainty=SOURCE_LOCAL_GUI_MODEL,
            source=SOURCE_LOCAL_GUI_MODEL,
            action_kind=unknown_advisor.ACTION_ORDINARY,
            target_semantics=text,
            # The anchor is the client's own printed words, read off *this* frame by the
            # request's own OCR.  ``grounded_region`` then produces the point from the
            # frame's box, so no geometry travelled through the model at all.
            target_anchor={"text": text},
            note=plan.reason,
            answered_at=datetime.now(timezone.utc).isoformat(),
            action_level=unknown_advisor.LEVEL_ENTRY,
        )

    def _knowledge(self, question: Any) -> list[str]:
        """Only what the request itself carries about this screen.  No knowledge-base dump."""
        items: list[str] = []
        template_note = str(getattr(question, "template_match", "") or "").strip()
        if template_note:
            items.append(f"templates matched here: {template_note}")
        ledger_note = str(getattr(question, "ledger_match", "") or "").strip()
        if ledger_note:
            items.append(f"previous control->page on this screen: {ledger_note}")
        entry = str(getattr(question, "entry_page", "") or "").strip()
        if entry:
            items.append(f"reached from page {entry}")
        return items

    def _delegate_take(self, request: Any, registry: Any) -> unknown_advisor.Advice | None:
        if self.fallback is None:
            return None
        return self.fallback.take(request, registry=registry)


#: Recorded as the advice's ``source`` so a ledger row says which reasoner answered.
SOURCE_LOCAL_GUI_MODEL = "LOCAL_GUI_MODEL"


def from_config(
    config: dict[str, Any] | None,
    *,
    root: Path | str,
    fallback: Any = None,
) -> ManagedAdvisor | None:
    """Build the advisor the runtime should use, or ``None`` to keep the old one."""
    section = {}
    if isinstance(config, dict) and isinstance(config.get("local_planner"), dict):
        section = dict(config["local_planner"])
    if not section.get("enabled", False):
        return None
    client = local_gui_model.from_config(config, root=root)
    if client is None:
        return None
    return ManagedAdvisor(
        client=client,
        ledger=PlannerLedger(Path(root) / str(section.get("plan_ledger")
                                            or "learning/local_planner_steps.jsonl")),
        root=root,
        fallback=fallback,
        max_steps_per_run=int(section.get("max_steps_per_run") or 12),
        max_steps_per_screen=int(section.get("max_steps_per_screen") or 2),
    )


@dataclass
class PlannerStats:
    """A tiny fold over the step ledger, for the panel and for reporting."""

    path: Path
    calls: int = 0
    executed: int = 0
    refusals: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str) -> "PlannerStats":
        stats = cls(Path(path))
        try:
            rows = stats.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return stats
        for line in rows:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            stats.calls += 1
            if str(row.get("decision")) == "EXECUTE":
                stats.executed += 1
            elif row.get("error"):
                key = str(row["error"]).split(":")[0]
                stats.refusals[key] = stats.refusals.get(key, 0) + 1
        return stats
