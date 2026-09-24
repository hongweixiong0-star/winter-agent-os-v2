"""The structured-UI-action protocol, and the local planner that fills it in.

Operator directive 2026-09-25, sections 3–8.  When no registered skill can advance a goal,
the *how* has to come from somewhere, and it is the local Qwen that supplies it — as
**structured UI actions**, never as coordinates:

    goal + this frame's measured elements + the actions MAA can perform
        -> Qwen picks an element id and an action type
        -> validated against the same frame
        -> the existing executor taps the element it located
        -> the existing verifier judges the result

Three properties that are enforced here rather than trusted
-----------------------------------------------------------
* **No coordinates, in either direction.**  ``FORBIDDEN_KEYS`` is scanned recursively in the
  reply, so a model that answers ``{"x": 340, "y": 812}`` is refused by name instead of
  being quietly ignored.  And the packet's element table carries only ``id``, the client's
  own ``text`` and a coarse area — the planner is never even shown a pixel, so there is
  nothing to transport.  The tap point is produced later, from the frame, by
  ``unknown_advisor.grounded_region`` — the same grounding the verified advice path uses.
* **Only what was offered.**  ``target_element_id`` must be one of the ids this frame
  produced, and the action must be one the call site can actually carry out.  ``INPUT_TEXT``
  is named in ``UNSUPPORTED_ACTIONS`` and refused with its own reason, because there is no
  text-entry path in this project yet and pretending otherwise would be the kind of
  "listed but not implemented" capability the constitution forbids.
* **A proposal, never a verdict.**  ``COMPLETE`` is recorded as a *claim* and changes no
  state: only the Verifier confirms a goal, and the runtime keeps its own path doing that.

Reuse rather than a second protocol
-----------------------------------
The reply is translated into the project's **existing** advice record
(``unknown_advisor.Advice``, ``action_kind = ACTION_ORDINARY``), so the retirement of the
WorkBuddy channel changes *where the answer comes from* and nothing about how an answer is
screened, grounded, named, executed, verified or filed.  ``ManagedAdvisor`` is the drop-in
that makes that substitution: same four methods the runtime already calls.

Retired with the channel, kept for the record
---------------------------------------------
``ui_planner.LegacyAnswerFileAdvisor`` is not written here on purpose: reading
``learning/unknown_requests/answers/`` is ``unknown_advisor.UnknownAdvisor``'s own job and
that code stays where it is.  See
``knowledge/failure_patterns/integration/WORKBUDDY_CHANNEL_RETIRED.md`` for why the
automatic WorkBuddy call is gone and what remains reachable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import local_qwen
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

#: Keys whose presence means the reply transported geometry.  Checked recursively.
FORBIDDEN_KEYS = (
    "x", "y", "x1", "y1", "x2", "y2", "x_norm", "y_norm", "coord", "coords",
    "coordinate", "coordinates", "point", "tap", "tap_point", "tap_x", "tap_y",
    "pixel", "pixels", "box", "bbox", "rect",
)

#: The decisions that mean "do not tap this step".  Each one is recorded with its own
#: reason; none of them is allowed to stop the cycle (section 7 of the master rules).
NON_TAPPING_DECISIONS = ("OBSERVE", "REPLAN", "COMPLETE", "DEFER", "BLOCKED")

#: The reason every refusal is filed under when the model is simply not there.
PLANNER_UNAVAILABLE = "LOCAL_PLANNER_UNAVAILABLE"

SYSTEM_PROMPT = """You are the UI action planner of a screenshot-driven game automation agent.

You will be given, for ONE game screen:
- goal: the task the scheduler has already decided to pursue. You do NOT choose goals.
- current_page: what the page model read this screen as.
- available_elements: the UI elements that were ACTUALLY measured on this screen right now.
  Each has an id, the text the client itself printed on it, and a coarse vertical area.  When a
  "kind" is present it says what the element is: COMPOSITE_CONTROL is a control drawn as an icon
  with its name printed underneath (the id names the icon, which is what you would press);
  TEXT_LABEL is printed information -- a town name, a resource count -- and is NOT a button.
- available_actions: the action types you are allowed to return. Nothing else is legal.

Choose the single next UI action toward the goal.

Hard rules:
1. You may only name an id that appears in available_elements. Never invent an element.
2. You may only use an action from available_actions, and you may only CLICK an element whose
   "executable" is not false. A TEXT_LABEL is a name, not a control.
3. NEVER output coordinates, pixels, screen positions or tap points. You cannot see the
   screen; positions are produced later by the client-side locator.
4. Reply with JSON only, exactly this shape:
   {"goal": str, "decision": str, "action": {"type": str, "target_element_id": str|null},
    "expected": {"page": str}, "reason": str}
5. decision must be one of: EXECUTE, OBSERVE, REPLAN, COMPLETE, DEFER, BLOCKED.
   - EXECUTE: carry out the action now; target_element_id must name an element.
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
6. Prefer an element whose printed text directly names the action the goal needs. Prefer a
   low-risk control (close, back, confirm-free, claim-free) over anything that spends.
7. Never propose an element whose text implies spending money, gems, or an irreversible
   action unless the goal is exactly that.
8. "reason" is one short sentence, in the language of the client's own text.
"""


@dataclass(frozen=True)
class Plan:
    """One validated planner reply."""

    decision: str
    action_type: str = ""
    target_element_id: str = ""
    target_text: str = ""
    expected_page: str = ""
    reason: str = ""
    goal: str = ""

    def to_row(self, *, page_key: str = "", source: str = "LOCAL_QWEN") -> dict[str, Any]:
        return {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "page_key": page_key,
            "goal": self.goal,
            "decision": self.decision,
            "action_type": self.action_type,
            "target_element_id": self.target_element_id,
            "target_text": self.target_text,
            "expected_page": self.expected_page,
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
    max_elements: int = 30,
) -> dict[str, Any]:
    """Section 4's packet, and nothing more.

    The caps are the point: the directive's own words are "不要将全部游戏知识库、完整历史日志
    和无关任务信息塞入模型上下文", and an 8K budget is only a budget if the caller enforces it.
    """
    return {
        "goal": str(goal or ""),
        "role_id": str(role_id or ""),
        "current_page": str(current_page or ""),
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
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key).strip().lower()
            if name in FORBIDDEN_KEYS:
                return f"{path}.{name}".lstrip(".")
            found = _find_forbidden(value, f"{path}.{name}".lstrip("."))
            if found:
                return found
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found = _find_forbidden(value, f"{path}[{index}]")
            if found:
                return found
    return ""


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
    if isinstance(expected, Mapping):
        expected_page = str(expected.get("page") or "").strip()

    if decision != "EXECUTE":
        return PlanParse(plan=Plan(decision=decision, reason=reason, goal=goal,
                                   expected_page=expected_page), raw=text[:400])

    action = payload.get("action")
    if not isinstance(action, Mapping):
        return PlanParse(error="PLAN_EXECUTE_WITHOUT_ACTION", raw=text[:400])
    action_type = str(action.get("type") or "").strip().upper()
    if action_type in UNSUPPORTED_ACTIONS:
        return PlanParse(error=UNSUPPORTED_ACTIONS[action_type], raw=text[:400])
    if action_type not in actions:
        return PlanParse(error=f"PLAN_ACTION_NOT_OFFERED: {action_type[:40]!r}", raw=text[:400])

    target_id = str(action.get("target_element_id") or "").strip().upper()
    by_id = {str(e.get("id", "")).upper(): e for e in elements}
    if not target_id or target_id not in by_id:
        return PlanParse(error=f"PLAN_TARGET_NOT_ON_THIS_SCREEN: {target_id[:40]!r}",
                         raw=text[:400])
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
            target_text=target_text, expected_page=expected_page, reason=reason, goal=goal,
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
        client: local_qwen.LocalQwen,
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
        if not elements:
            self.last_outcome = {"decision": "", "error": "PLANNER_NO_ELEMENTS_ON_THIS_SCREEN"}
            self.ledger.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": "LOCAL_QWEN", "page_key": page_key,
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
        )
        call = self.client.ask_json(
            system=SYSTEM_PROMPT, user=render_packet(packet), purpose="ui_plan",
            element_count=len(elements),
        )
        self.steps += 1
        self._per_screen[page_key] = self._per_screen.get(page_key, 0) + 1
        if not call.ok:
            self.last_outcome = {"decision": "", "error": call.error}
            self.ledger.append({
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": "LOCAL_QWEN", "page_key": page_key,
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
                "source": "LOCAL_QWEN", "page_key": page_key,
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
                    "source": "LOCAL_QWEN", "page_key": page_key, "goal": plan.goal,
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

    def _advice_for(self, plan: Plan, question: Any, elements: list[dict[str, Any]],
                    request_id: str) -> unknown_advisor.Advice | None:
        text = plan.target_text
        if not text:
            return None
        return unknown_advisor.Advice(
            request_id=request_id or str(getattr(question, "request_id", "") or ""),
            unknown_type=unknown_advisor.UNKNOWN_CONTROL,
            candidate_semantics=(text,),
            proposed_action=text,
            expected_result=plan.expected_page or plan.reason,
            uncertainty="LOCAL_QWEN",
            source=SOURCE_LOCAL_QWEN,
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
SOURCE_LOCAL_QWEN = "LOCAL_QWEN"


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
    client = local_qwen.from_config(config, root=root)
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
