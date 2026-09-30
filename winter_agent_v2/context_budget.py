"""The input budget for the local GUI model: 32K of window, 28K of prompt, and a rule for
what is dropped when even that is not enough.

Operator directive 2026-09-30 (second half): the runtime local model's context is raised from
8K to **32768**, and the same directive is explicit that this is a *ceiling and not a target*
-- "不要为了'利用32K'把所有历史全部塞给模型".  So the window is large and the planner is
still expected to send 6-16K for an ordinary UNKNOWN step and 16-24K for a long session, with
32K existing only so a deep session does not die against the wall.

Three quantities, and why they are three
------------------------------------------
``MAX_MODEL_CONTEXT = 32768``
    What llama-server was started with (``-c``).  The hard wall: a prompt larger than this is
    refused by the server, not merely slow.
``OUTPUT_RESERVE = 4096``
    What the reply, its reasoning field and the sampler's format slack are allowed to occupy.
    The directive asks for "至少预留 4096".  It is a *reserve*, i.e. subtracted before the
    input is measured, so the input is never fitted to the whole window and then truncated
    against the reply.
``MAX_INPUT_BUDGET = 32768 - 4096 = 28672``
    What this module enforces.

Why a manager and not a bigger ``max_elements``
-----------------------------------------------
The old packet was small by construction -- 30 elements, three knowledge lines, one previous
step -- so a cap was enough.  That stops being true the moment recent history and goal
knowledge are added, because the failure mode changes: a cap that is silently exceeded pushes
the *oldest* tokens out of the window at the server, and what falls off the end first is the
system prompt and the frame.  Trimming has to be explicit about what it removes, in the order
the directive sets, and it has to be visible in the ledger.  That is all this module is: an
ordered trim with a report.

The order is the directive's own P0/P1/P2, and it is enforced here rather than described
--------------------------------------------------------------------------------------------
P0 -- never dropped: the frame (it is an image part, not text), the goal, the page, the
session, the offered actions, the element table and the last verifier outcome.
P1 -- dropped third: recent Action->Feedback history (16 steps down to 8), goal knowledge
(Top-K down to 0), the failure/recovery note.
P2 -- dropped first: ``world_state`` keys beyond a core set, history older than the last 8
steps, and any second copy of text already listed as an element ("重复 OCR" is the directive's
own example).

The element table is P0 but is the one P0 that may shrink, because it is the only P0 whose
size is unbounded in principle; it never goes below ``ELEMENT_FLOOR``.  If the packet still
does not fit at the floor the manager says so (``within_budget=False``) instead of sending an
over-window prompt -- the caller turns that into ``LOCAL_GUI_MODEL_INPUT_OVER_BUDGET`` and the
step is deferred, which is the behaviour the directive asks for when the model cannot be given
a legal question.

Estimating, and measuring
-------------------------
Counting tokens properly needs the model's own tokenizer, and this module must not carry one
into the runtime: a second tokenizer in the process is a second source of truth about a
quantity only the server actually knows.  So the count here is an **estimate** built to
over-state rather than under-state, and the *real* count is read back from the server's own
``usage.prompt_tokens`` on every call (see ``local_gui_model.GUIModelCall``).  The estimate
decides what to trim; the measurement decides whether the estimate was any good, and
``tools/profile_gui_model_context.py --calibrate`` reports the two against each other.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

#: The window llama-server is started with.  One number, here and in the launch tool.
MAX_MODEL_CONTEXT = 32768

#: Reserved for the reply.  The directive's floor is 4096 and the observed replies are 112-160
#: tokens, so this is generous on purpose: what it buys is that a chatty model cannot turn a
#: legal prompt into a truncated one.
OUTPUT_RESERVE = 4096

#: What the prompt is allowed to occupy.  Named because the directive names it -- it is one of
#: the production-acceptance fields -- and derived so it cannot disagree with the two above.
MAX_INPUT_BUDGET = MAX_MODEL_CONTEXT - OUTPUT_RESERVE

#: What the frame costs, and the flag it must agree with.  ``launch_gui_model_server`` passes
#: ``--image-min-tokens 1024 --image-max-tokens 1024``, so the image is a known, fixed size and
#: the budget can account for it instead of discovering it after the first call.
IMAGE_TOKENS = 1024
IMAGE_TOKENS_NOTE = "--image-min-tokens/--image-max-tokens in tools/launch_gui_model_server.py"

#: Recent steps the packet aims to carry, and the floor it falls back to.  The directive says
#: "最近 8~16 步 Action → Feedback": 16 when there is room, 8 before anything else is cut, and
#: below 8 only after knowledge is gone.
HISTORY_TARGET = 16
HISTORY_FLOOR = 8

#: Elements the packet aims to carry and the floor it never goes under.  The table is P0, so
#: the floor exists to make "P0 survives" true rather than aspirational.
ELEMENT_TARGET = 30
ELEMENT_FLOOR = 12

#: Knowledge lines the packet aims to carry.  Top-K, per the directive.
KNOWLEDGE_TARGET = 3

#: ``world_state`` keys that survive the first trim.  The rest are P2: useful context, and the
#: first thing to go, because the page model and the frame already carry most of what a
#: one-screen decision needs.
WORLD_STATE_CORE = ("page", "confidence", "stamina")


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x2E80 <= code <= 0x9FFF      # CJK radicals through unified ideographs
        or 0xF900 <= code <= 0xFAFF   # compatibility ideographs
        or 0x3040 <= code <= 0x30FF   # kana
        or 0xAC00 <= code <= 0xD7AF   # hangul syllables
        or 0xFF00 <= code <= 0xFFEF   # fullwidth forms
    )


#: Calibrated against the served tokenizer on 2026-09-30 (``/tokenize``), per character, and
#: deliberately fitted to the *worst* content this packet contains rather than the average.
#:
#: The measurement, because the constants are otherwise invisible:
#:
#:     English prose (the system prompt)   5875 chars -> 1479 tokens   0.252 /char
#:     a real packet, no history           2409 chars -> 1130 tokens   0.469 /char
#:     the same packet + 144 history rows 27145 chars -> 10710 tokens  0.395 /char
#:     the same packet + 432 history rows 77544 chars -> 30111 tokens  0.388 /char
#:
#: The first version of this module used 0.32 for ASCII, taken from prose, and under-stated a
#: JSON packet by up to **43%** -- enough for the manager to approve a 27756-token estimate that
#: the server really counted at 32760, i.e. 99.98% of the window with nothing left for the reply.
#: Measured, not reasoned: ``profile_gui_model_context.py`` reports the estimate against
#: ``usage.prompt_tokens`` on every call.  JSON spends tokens on ``{``, ``"``, ``:`` and short
#: digit runs, which is why it is *denser* than prose, and why the flat rate above is set to the
#: densest content the packet can contain.  The cost is that prose is over-stated by ~2x; the
#: benefit is that the estimate is on the safe side of the one mistake that matters.
CJK_TOKENS_PER_CHAR = 0.68
ASCII_TOKENS_PER_CHAR = 0.50


def estimate_tokens(text: str) -> int:
    """A deliberate over-estimate of what ``text`` costs the served model.

    Over-estimating is the safe direction and is the whole design of the constants above: it
    trims a little early rather than sending a prompt the server will truncate.  The real number
    is read back from ``usage.prompt_tokens`` after every call, so this never has to be *right*,
    only never too low.
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        if _is_cjk(char):
            cjk += 1
        else:
            other += 1
    # The +2 is the role marker and separator a message costs whatever it contains; without it a
    # packet of empty strings would estimate at zero.
    return int(math.ceil(cjk * CJK_TOKENS_PER_CHAR + other * ASCII_TOKENS_PER_CHAR)) + 2


def estimate_packet_tokens(packet: Mapping[str, Any]) -> int:
    """What the packet costs as the JSON the model is actually shown.

    Measured on the rendered form rather than on the object, because that is what travels and
    because indentation is not free.
    """
    try:
        text = json.dumps(packet, ensure_ascii=False, indent=1, default=str)
    except (TypeError, ValueError):
        text = json.dumps(packet, ensure_ascii=False, default=str)
    return estimate_tokens(text)


@dataclass(frozen=True)
class BudgetReport:
    """What the trim did, so the ledger can say it instead of a reader having to infer it."""

    max_model_context: int
    output_reserve: int
    max_input_budget: int
    estimated_tokens: int
    image_tokens: int
    system_tokens: int
    packet_tokens: int
    elements_kept: int = 0
    elements_dropped: int = 0
    history_kept: int = 0
    history_dropped: int = 0
    knowledge_kept: int = 0
    knowledge_dropped: int = 0
    dropped_sections: tuple[str, ...] = ()
    within_budget: bool = True

    @property
    def headroom(self) -> int:
        return self.max_input_budget - self.estimated_tokens

    def to_row(self) -> dict[str, Any]:
        return {
            "max_model_context": self.max_model_context,
            "output_reserve": self.output_reserve,
            "max_input_budget": self.max_input_budget,
            "estimated_input_tokens": self.estimated_tokens,
            "image_tokens": self.image_tokens,
            "system_tokens": self.system_tokens,
            "packet_tokens": self.packet_tokens,
            "headroom_tokens": self.headroom,
            "elements_kept": self.elements_kept,
            "elements_dropped": self.elements_dropped,
            "history_kept": self.history_kept,
            "history_dropped": self.history_dropped,
            "knowledge_kept": self.knowledge_kept,
            "knowledge_dropped": self.knowledge_dropped,
            "dropped_sections": list(self.dropped_sections),
            "within_budget": self.within_budget,
        }


class ContextBudgetManager:
    """Fits a packet into ``MAX_INPUT_BUDGET`` by dropping in the directive's own order.

    Deliberately stateless per call: it is given a packet and returns a smaller packet plus a
    report.  Nothing here holds a socket, a clock or a model, so the whole thing is testable
    without a server -- which is how the tier order is pinned by
    ``tests/test_context_budget.py`` rather than argued about.
    """

    def __init__(
        self,
        *,
        max_model_context: int = MAX_MODEL_CONTEXT,
        output_reserve: int = OUTPUT_RESERVE,
        image_tokens: int = IMAGE_TOKENS,
        history_target: int = HISTORY_TARGET,
        history_floor: int = HISTORY_FLOOR,
        element_target: int = ELEMENT_TARGET,
        element_floor: int = ELEMENT_FLOOR,
        knowledge_target: int = KNOWLEDGE_TARGET,
        counter: Callable[[str], int] | None = None,
    ) -> None:
        self.max_model_context = int(max_model_context)
        self.output_reserve = int(output_reserve)
        if self.output_reserve < 0:
            raise ValueError("output_reserve must not be negative")
        if self.output_reserve >= self.max_model_context:
            # A reserve that eats the whole window leaves no legal prompt at all, and every
            # step would fail with an over-budget refusal that looks like a model fault.
            raise ValueError("output_reserve must be smaller than max_model_context")
        self.image_tokens = int(image_tokens)
        self.history_target = int(history_target)
        self.history_floor = max(0, min(int(history_floor), self.history_target))
        self.element_target = int(element_target)
        self.element_floor = max(1, min(int(element_floor), self.element_target))
        self.knowledge_target = int(knowledge_target)
        self._counter = counter or estimate_tokens

    @property
    def max_input_budget(self) -> int:
        return self.max_model_context - self.output_reserve

    def count(self, text: str) -> int:
        """How many tokens this manager thinks ``text`` costs.

        Public because the calibration tool has to ask the same counter the trim uses; a second
        entry point that called the estimator directly would let the two disagree about a number
        they both act on.
        """
        return self._counter(text)

    # ------------------------------------------------------------------ the trim
    def fit(
        self,
        *,
        system: str = "",
        packet: Mapping[str, Any],
        image_tokens: int | None = None,
    ) -> tuple[dict[str, Any], BudgetReport]:
        """Return a packet that fits, with the record of what it took to make it fit.

        The packet is copied, never mutated: the caller's ``step_index`` and element ids have
        to stay as they were, and a trim that edited its input would make "what did the model
        see" unanswerable after a retry.
        """
        work = dict(packet)
        image = self.image_tokens if image_tokens is None else int(image_tokens)
        system_tokens = self._counter(system)

        elements = list(work.get("available_elements") or [])
        history = list(work.get("recent_steps") or [])
        knowledge = list(work.get("relevant_knowledge") or [])
        world_state = dict(work.get("world_state") or {})

        total_elements = len(elements)
        total_history = len(history)
        total_knowledge = len(knowledge)
        dropped: list[str] = []

        # The ladders are applied in the directive's priority order, and each rung is tried
        # only if the packet still does not fit.  Written as a list of (name, apply) so the
        # order is one readable thing instead of a chain of ifs that can drift.
        world_state = dict(work.get("world_state") or {})
        core_state = {k: v for k, v in world_state.items() if k in WORLD_STATE_CORE}
        trimmed_state = {k: v for k, v in world_state.items() if k not in WORLD_STATE_CORE}

        ladders: list[tuple[str, Callable[[], None]]] = []

        def drop_state_extras() -> None:
            nonlocal trimmed_state
            if trimmed_state:
                dropped.append("world_state:" + ",".join(sorted(trimmed_state)))
                trimmed_state = {}

        def history_to(count: int) -> Callable[[], None]:
            def apply() -> None:
                nonlocal history
                if len(history) > count:
                    # Oldest first: the directive calls old session history P2 and recent
                    # steps P1, so the tail is what survives.
                    dropped.append(f"history:{len(history)}->{count}")
                    history = history[-count:] if count else []
            return apply

        def knowledge_to(count: int) -> Callable[[], None]:
            def apply() -> None:
                nonlocal knowledge
                if len(knowledge) > count:
                    dropped.append(f"knowledge:{len(knowledge)}->{count}")
                    knowledge = knowledge[:count]
            return apply

        def elements_to(count: int) -> Callable[[], None]:
            def apply() -> None:
                nonlocal elements
                if len(elements) > count:
                    dropped.append(f"elements:{len(elements)}->{count}")
                    elements = elements[:count]
            return apply

        def drop_failure_note() -> None:
            if work.get("last_failure"):
                dropped.append("last_failure")
                work.pop("last_failure", None)

        # P2 first (the directive's own list: 无关 Goal history, 大段旧日志, 无关 Knowledge,
        # 重复 OCR), then P1, then the one P0 that may shrink, and never below its floor.
        ladders.append(("world_state_extras", drop_state_extras))
        for rung in (self.history_floor, self.history_floor // 2, 0):
            if rung < self.history_target:
                ladders.append((f"history_to_{rung}", history_to(rung)))
        ladders.append(("world_state_extras_again", drop_state_extras))
        for rung in range(self.knowledge_target - 1, -1, -1):
            ladders.append((f"knowledge_to_{rung}", knowledge_to(rung)))
        ladders.append(("last_failure", drop_failure_note))
        for rung in (24, 18, self.element_floor):
            if rung < self.element_target:
                ladders.append((f"elements_to_{rung}", elements_to(rung)))

        def measure() -> int:
            trial = dict(work)
            trial["available_elements"] = elements
            if total_history:
                trial["recent_steps"] = history
            else:
                trial.pop("recent_steps", None)
            if total_knowledge:
                trial["relevant_knowledge"] = knowledge
            else:
                trial.pop("relevant_knowledge", None)
            merged = dict(core_state)
            merged.update(trimmed_state)
            if merged:
                trial["world_state"] = merged
            else:
                trial.pop("world_state", None)
            return image + system_tokens + self._counter(
                json.dumps(trial, ensure_ascii=False, indent=1, default=str)
            )

        estimated = measure()
        for _name, apply in ladders:
            if estimated <= self.max_input_budget:
                break
            apply()
            estimated = measure()

        fitted = dict(work)
        if total_elements:
            fitted["available_elements"] = elements
        if total_history:
            if history:
                fitted["recent_steps"] = history
            else:
                fitted.pop("recent_steps", None)
        if total_knowledge:
            if knowledge:
                fitted["relevant_knowledge"] = knowledge
            else:
                fitted.pop("relevant_knowledge", None)
        merged = dict(core_state)
        merged.update(trimmed_state)
        if merged:
            fitted["world_state"] = merged
        else:
            fitted.pop("world_state", None)

        # What the packet says about its own size.  Recorded in the packet, not only in the
        # report, so the model can see that history was cut and does not treat a truncated
        # session as a short one -- and so a reader of the ledger can tell a step that never
        # had history from one that lost it.
        if total_history or total_knowledge or total_elements:
            fitted["context"] = {
                "max_context": self.max_model_context,
                "max_input_budget": self.max_input_budget,
                "steps_shown": len(history),
                "steps_available": total_history,
                "elements_shown": len(elements),
                "elements_available": total_elements,
            }

        report = BudgetReport(
            max_model_context=self.max_model_context,
            output_reserve=self.output_reserve,
            max_input_budget=self.max_input_budget,
            estimated_tokens=estimated,
            image_tokens=image,
            system_tokens=system_tokens,
            packet_tokens=max(0, estimated - image - system_tokens),
            elements_kept=len(elements),
            elements_dropped=total_elements - len(elements),
            history_kept=len(history),
            history_dropped=total_history - len(history),
            knowledge_kept=len(knowledge),
            knowledge_dropped=total_knowledge - len(knowledge),
            dropped_sections=tuple(dropped),
            within_budget=estimated <= self.max_input_budget,
        )
        return fitted, report


def from_config(config: Mapping[str, Any] | None) -> ContextBudgetManager | None:
    """Build a manager from ``config/v2.json``'s ``local_planner`` section.

    ``None`` when the planner is off, matching ``local_gui_model.from_config``: a runtime with
    no planner should behave exactly as it did before either module existed, and that includes
    not constructing budget machinery nobody will consult.
    """
    section: Mapping[str, Any] = {}
    if isinstance(config, Mapping):
        candidate = config.get("local_planner")
        if isinstance(candidate, Mapping):
            section = candidate
    if not section or not section.get("enabled", False):
        return None
    return ContextBudgetManager(
        max_model_context=int(section.get("context") or MAX_MODEL_CONTEXT),
        output_reserve=int(section.get("output_reserve") or OUTPUT_RESERVE),
        history_target=int(section.get("history_steps") or HISTORY_TARGET),
    )


@dataclass
class BudgetTotals:
    """Running totals for the report: the *actual* prompt sizes, not the estimates.

    Filled from the server's own ``usage.prompt_tokens`` on every call that returned one, so
    ``ACTUAL_PROMPT_P50/P95/MAX`` are measurements.  The estimate is kept beside it so a
    reader can see whether the estimator is over- or under-stating, which is the only way the
    heuristics above can be corrected from evidence rather than taste.
    """

    actual: list[int] = field(default_factory=list)
    estimated: list[int] = field(default_factory=list)

    def add(self, *, actual: int, estimated: int) -> None:
        if actual > 0:
            self.actual.append(int(actual))
            self.estimated.append(int(estimated))

    @staticmethod
    def _percentile(values: list[int], fraction: float) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * fraction
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        return int(round(ordered[low] + (ordered[high] - ordered[low]) * (position - low)))

    def summary(self) -> dict[str, Any]:
        if not self.actual:
            return {"n": 0, "p50": 0, "p95": 0, "max": 0, "estimate_ratio_p50": 0.0}
        ratios = sorted(
            a / e for a, e in zip(self.actual, self.estimated) if e > 0
        ) or [0.0]
        return {
            "n": len(self.actual),
            "p50": self._percentile(self.actual, 0.50),
            "p95": self._percentile(self.actual, 0.95),
            "max": max(self.actual),
            "estimate_ratio_p50": round(ratios[len(ratios) // 2], 3),
        }
