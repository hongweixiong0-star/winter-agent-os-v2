"""WorkBuddy's model-selection strategy — the only place in this repo that names a model.

Why this is its own module
--------------------------
The operator's architecture has four layers, and the model is *not* one of them:

    MAA          eyes and hands
    V2           gameplay brain
    WorkBuddy    autonomous development platform
    models       replaceable development compute

So the model must be invisible to V2.  The strongest way to keep a boundary is to
make it checkable, and this module exists to be the single place where model names
appear at all: ``tests/test_workbuddy_model_router.py`` asserts that no model
literal occurs anywhere else in ``winter_agent_v2/``.  Tomorrow's stronger, cheaper
or faster model is therefore a change to *this file* (or to the stats it reads),
and nothing in the brain, scheduler, skills, verifier or MAA layer moves.

What "lowest cost" means here, stated honestly
---------------------------------------------
The operator's rule is "the lowest-cost model that can reliably do the task".  The
cheapest half of that is measurable — the seed list is ordered by cost, cheapest
first.  The *cost* half is not: the jobs API exposes no token or cost field
(measured 2026-09-17; the payload carries ``id``/``state``/``output`` and nothing
about usage), so every recorded row stores ``cost: null`` with the reason rather
than an estimate.  Selection is therefore *performance-driven within a known cost
ordering*, which is the strongest statement the data supports.  If a usage field
ever appears, it is recorded automatically and the comparison can become real.

How the choice is made
----------------------
Per ``task_type``, from recorded outcomes (:data:`ModelStatsStore`):

* cold start — nothing recorded for this task type: the cheapest rung, unless the
  problem's shape says otherwise (vision work starts at the vision rung);
* warm — the cheapest rung whose recorded success rate clears :data:`MIN_SUCCESS`
  over at least :data:`MIN_SAMPLES` jobs;
* a rung whose record is below that bar is not retried for that task type unless
  every rung is below it, in which case the cheapest is still tried first.

And the floor never ratchets: :meth:`ModelRouter.choose` at ``attempt=0`` always
considers the seed order from the cheapest, so a task that needed the top rung
does not make every later task expensive.  That is the operator's explicit rule,
and it is the failure mode of every naive "escalate and remember" router.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

# The seed ordering, cheapest first.  A **seed**, not the answer: it is what the
# router falls back to before it has any evidence, and every rung was verified end
# to end on 2026-09-17 (each dispatched a job that reached ``done``).
#
# This is the only place in the repository that names a model.
SEED_ORDER: tuple[str, ...] = (
    "deepseek-v4.1-flash",
    "glm-5.3-flash",
    "hy4-preview-f",
    "deepseek-v4-pro",
)

# The rungs a problem shape may start from when nothing is recorded yet.
VISION_RUNG = "hy4-preview-f"
LONG_CONTEXT_RUNG = "glm-5.3-flash"

MIN_SAMPLES = 3
MIN_SUCCESS = 0.5

# Tasks, as the router sees them.  Derived from the escalation condition plus the
# problem shape, so the same kind of work accumulates evidence together.
TASK_UI_RECOGNITION = "UI_RECOGNITION"
TASK_CAPABILITY_IMPLEMENTATION = "CAPABILITY_IMPLEMENTATION"
TASK_GAMEPLAY_MODELING = "GAMEPLAY_MODELING"
TASK_REGRESSION_FIX = "REGRESSION_FIX"
TASK_STUCK_INVESTIGATION = "STUCK_INVESTIGATION"

TASK_TYPES: tuple[str, ...] = (
    TASK_UI_RECOGNITION,
    TASK_CAPABILITY_IMPLEMENTATION,
    TASK_GAMEPLAY_MODELING,
    TASK_REGRESSION_FIX,
    TASK_STUCK_INVESTIGATION,
)

# condition -> task type.  Kept here rather than in the queue so the queue never
# has to know what a model is at all.
_CONDITION_TO_TASK = {
    "UNKNOWN_UI": TASK_UI_RECOGNITION,
    "CAPABILITY_MISSING": TASK_CAPABILITY_IMPLEMENTATION,
    "UNKNOWN_GAME_MECHANIC": TASK_GAMEPLAY_MODELING,
    "REPEATED_LIVE_FAILURE": TASK_REGRESSION_FIX,
    "STUCK_15_MIN": TASK_STUCK_INVESTIGATION,
}


def task_type_for(condition: str, *, needs: str = "") -> str:
    """The task bucket an escalation belongs to, for evidence accumulation."""
    base = _CONDITION_TO_TASK.get(str(condition), TASK_STUCK_INVESTIGATION)
    if needs == "vision" and base == TASK_UI_RECOGNITION:
        return TASK_UI_RECOGNITION
    return base


@dataclass(frozen=True)
class ModelOutcome:
    """One finished job, as the router will remember it."""

    model: str
    task_type: str
    duration: float | None = None
    cost: float | None = None
    success: bool = False
    live_improvement: bool = False
    retry_count: int = 0
    escalation_count: int = 0
    recorded_at: str = ""
    note: str = ""

    def as_row(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "task_type": self.task_type,
            "duration": self.duration,
            "cost": self.cost,
            "success": self.success,
            "live_improvement": self.live_improvement,
            "retry_count": self.retry_count,
            "escalation_count": self.escalation_count,
            "recorded_at": self.recorded_at or datetime.now(timezone.utc).isoformat(),
            "note": self.note,
        }


class ModelStatsStore:
    """Append-only outcome log.  ``learning/workbuddy_model_stats.jsonl``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, outcome: ModelOutcome) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(outcome.as_row(), ensure_ascii=False) + "\n")

    def rows(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("model"):
                out.append(row)
        return out


@dataclass(frozen=True)
class Rung:
    """One model's record for one task type."""

    model: str
    samples: int = 0
    successes: int = 0
    live_improvements: int = 0
    total_duration: float = 0.0
    duration_samples: int = 0

    @property
    def success_rate(self) -> float:
        return self.successes / self.samples if self.samples else 0.0

    @property
    def live_rate(self) -> float:
        return self.live_improvements / self.samples if self.samples else 0.0

    @property
    def mean_duration(self) -> float | None:
        return self.total_duration / self.duration_samples if self.duration_samples else None

    def describe(self) -> str:
        if not self.samples:
            return f"{self.model}: no record for this task"
        bits = [f"{self.samples} job(s)", f"success {self.success_rate:.0%}",
                f"live {self.live_rate:.0%}"]
        if self.mean_duration is not None:
            bits.append(f"mean {self.mean_duration:.0f}s")
        return f"{self.model}: " + ", ".join(bits)


def stats_for(rows: Iterable[Mapping[str, Any]], task_type: str) -> dict[str, Rung]:
    """Fold the outcome log into per-model records for one task type."""
    out: dict[str, Rung] = {}
    for row in rows:
        if str(row.get("task_type")) != task_type:
            continue
        model = str(row.get("model") or "")
        if not model:
            continue
        current = out.get(model, Rung(model=model))
        duration = row.get("duration")
        duration_add = float(duration) if isinstance(duration, (int, float)) else 0.0
        out[model] = Rung(
            model=model,
            samples=current.samples + 1,
            successes=current.successes + (1 if row.get("success") else 0),
            live_improvements=current.live_improvements + (1 if row.get("live_improvement") else 0),
            total_duration=current.total_duration + duration_add,
            duration_samples=current.duration_samples + (1 if isinstance(duration, (int, float)) else 0),
        )
    return out


@dataclass(frozen=True)
class Choice:
    """One routing decision, with the reason recorded beside it."""

    model: str
    reason: str
    task_type: str
    from_history: bool = False
    escalated_from: str = ""

    @property
    def is_escalated(self) -> bool:
        return bool(self.escalated_from)


def _seed_index(model: str, order: tuple[str, ...]) -> int:
    return order.index(model) if model in order else 0


class ModelRouter:
    """Pick the cheapest model that has been reliable for this kind of task.

    Replaceable on purpose: nothing outside this module knows a model name, so
    changing the strategy (or the seed order) cannot touch V2, MAA, the skills,
    the scheduler or the verifier.
    """

    def __init__(
        self,
        store: ModelStatsStore | str | Path | None = None,
        *,
        seed_order: tuple[str, ...] = SEED_ORDER,
        min_samples: int = MIN_SAMPLES,
        min_success: float = MIN_SUCCESS,
    ) -> None:
        self.store = store if isinstance(store, ModelStatsStore) else ModelStatsStore(
            store if store is not None else "learning/workbuddy_model_stats.jsonl"
        )
        self.seed_order = tuple(seed_order)
        self.min_samples = int(min_samples)
        self.min_success = float(min_success)

    def choose(
        self,
        task_type: str,
        *,
        attempt: int = 0,
        needs: str = "",
        previous_model: str = "",
    ) -> Choice:
        """The decision.  ``attempt`` 0 is the first honest try for one task.

        Never ratchets the floor: a task that climbed to a stronger rung does not
        raise the starting point for the *next* task, because the starting point is
        always derived from this task type's own record.
        """
        if attempt <= 0:
            return self._cold_or_warm(task_type, needs=needs)

        previous = previous_model or self.seed_order[0]
        step = min(_seed_index(previous, self.seed_order) + 1, len(self.seed_order) - 1)
        model = self.seed_order[step]
        return Choice(
            model=model,
            reason=(
                f"attempt {attempt + 1}: the rung below ({previous}) produced no live "
                f"improvement for {task_type}, so climbing to {model}"
            ),
            task_type=task_type,
            escalated_from=previous,
        )

    def _cold_or_warm(self, task_type: str, *, needs: str) -> Choice:
        rungs = stats_for(self.store.rows(), task_type)
        known = {m: r for m, r in rungs.items() if r.samples >= self.min_samples}

        if not known:
            # Nothing trustworthy recorded: start cheap, unless the shape of the
            # problem is one the cheap rungs have never been good at.
            if needs == "vision":
                return Choice(VISION_RUNG, f"cold start for {task_type}; vision-shaped problem", task_type)
            if needs == "logs":
                return Choice(LONG_CONTEXT_RUNG, f"cold start for {task_type}; long-context problem", task_type)
            return Choice(
                self.seed_order[0],
                f"cold start for {task_type}: no model has {self.min_samples}+ recorded "
                f"jobs yet, so the cheapest rung is tried first",
                task_type,
            )

        for model in self.seed_order:
            rung = known.get(model)
            if rung is None:
                continue
            if rung.success_rate >= self.min_success:
                return Choice(
                    model,
                    f"cheapest rung whose record for {task_type} clears "
                    f"{self.min_success:.0%} ({rung.describe()})",
                    task_type,
                    from_history=True,
                )
        cheapest = known.get(self.seed_order[0])
        return Choice(
            self.seed_order[0],
            f"every recorded rung for {task_type} is below {self.min_success:.0%}"
            + (f" ({cheapest.describe()})" if cheapest else "")
            + "; starting cheap again rather than ratcheting the floor",
            task_type,
            from_history=True,
        )

    # -- reporting --------------------------------------------------------

    def report(self) -> str:
        lines = ["model routing (WorkBuddy-side strategy; the only place a model "
                 "name appears):", "  seed order, cheapest first:"]
        for index, model in enumerate(self.seed_order, start=1):
            lines.append(f"    {index}. {model}")
        lines.append("  recorded outcomes by task type:")
        rows = self.store.rows()
        if not rows:
            lines.append("    (none yet)")
        for task_type in TASK_TYPES:
            rungs = stats_for(rows, task_type)
            if not rungs:
                continue
            lines.append(f"    {task_type}:")
            for model in self.seed_order:
                rung = rungs.get(model)
                if rung is not None:
                    lines.append(f"      {rung.describe()}")
        return "\n".join(lines)


def default_stats_path(root: Path | str) -> Path:
    return Path(root) / "learning/workbuddy_model_stats.jsonl"
