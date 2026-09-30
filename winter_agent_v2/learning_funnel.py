"""The learning funnel: where the model's involvement actually turns into V2 capability.

Operator directive 2026-10-01, sections 36-38 and 47.  Section 38 asks for one thing above all:
every stage between "an UNKNOWN was seen" and "a skill is stable" has to be **countable**, because
otherwise a drop in model involvement cannot be attributed -- was the model wrong, was the grounding
wrong, did the action fail, or did the promotion gate refuse a good skill?

    UNKNOWN observed -> proposed -> grounding valid -> risk allowed -> MAA executed
        -> verifier progress -> verifier success -> candidate step -> candidate skill
        -> replay -> shadow -> live verified -> stable

Two rules this module follows, both of them the project's own anti-overclaim discipline:

1.  **a stage with no record is reported as unmeasured, with the reason.**  ``None`` plus
    ``UNMEASURED_REASON`` rather than a zero, because a zero reads as "this never happened" and
    the truth is "nothing writes this down yet" -- the two lead to opposite decisions.
2.  **every number names its source file.**  A console cell that cannot be traced to a ledger is a
    number nobody can check, and section 37 is explicit that counting JSON files is not success.

``KNOWN_MODEL_CALLS`` gets its own treatment for the same reason.  It is a *constitutional* number
(the model must not be consulted on a screen the rules can read), and the honest way to report it is
to count the ledger rows that show it *was* consulted on a named page -- which is evidence of the
number, rather than an assertion that it is zero.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import offline_learning, skill_repair, unknown_learning

#: The stores this fold reads.  Named here rather than inline so the report can say which file a
#: number came from without the reader having to guess.
PLANNER_LEDGER = Path("learning/local_planner_steps.jsonl")
EPISODES = Path("learning/episodes.jsonl")
UNKNOWN_REQUESTS = Path("learning/unknown_requests")
PAGE_STORE_INDEX = Path("knowledge/perception/pages/INDEX.json")
ELEMENT_STORE_INDEX = Path("knowledge/perception/candidates/INDEX.json")
SKILL_CANDIDATES = unknown_learning.CANDIDATE_SKILL_DIR
REPAIR_CANDIDATES = skill_repair.CANDIDATE_PATCH_DIR
OFFLINE_CLUSTERS = offline_learning.CLUSTERS_PATH

#: The words a runtime uses for the source of a planner call.  Both appear in the ledger's own
#: history: ``LOCAL_QWEN`` before the 2026-09-30 migration and ``LOCAL_GUI_MODEL`` after it, and a
#: fold that knew only the second would report the first as "no planner calls at all".
PLANNER_SOURCES = ("LOCAL_GUI_MODEL", "LOCAL_QWEN")

#: The stage names, in funnel order.  Fixed here so the console and the report cannot disagree
#: about what the funnel is.
FUNNEL_STAGES: tuple[str, ...] = (
    "unknown_observed",
    "model_proposed",
    "grounding_valid",
    "risk_allowed",
    "maa_executed",
    "verifier_progress",
    "verifier_success",
    "candidate_step",
    "candidate_skill",
    "replay_pass",
    "shadow_pass",
    "live_verified",
    "stable",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
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
        if isinstance(row, Mapping):
            out.append(dict(row))
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _rows_under(directory: Path, *, suffix: str = ".json") -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob(f"*{suffix}")):
        payload = _read_json(path)
        if payload:
            out.append(payload)
    return out


def _within(rows: Iterable[Mapping[str, Any]], *, since: datetime) -> list[dict[str, Any]]:
    """Rows stamped at or after ``since``.  Rows with no stamp are excluded rather than assumed.

    A row that cannot be dated cannot be counted as "today", and quietly including it would make
    every daily number drift upward for reasons nobody could see.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        stamp = str(row.get("recorded_at") or row.get("created_at") or "")
        if not stamp:
            continue
        try:
            moment = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment >= since:
            out.append(dict(row))
    return out


@dataclass
class FunnelCounts:
    """One row per stage, each with the source that produced it."""

    stage: str
    count: int | None = None
    source: str = ""
    unmeasured_reason: str = ""

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LearningFunnel:
    """The whole picture: the funnel, the KPIs, and today's console numbers."""

    generated_at: str = ""
    window_days: int = 1
    funnel: tuple[FunnelCounts, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    console: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "generated_at": self.generated_at,
            "window_days": self.window_days,
            "funnel": [stage.as_row() for stage in self.funnel],
            "metrics": dict(self.metrics),
            "console": dict(self.console),
            "sources": dict(self.sources),
        }


def _ratio(numerator: int | None, denominator: int | None) -> float | None:
    """A rate, or ``None`` when the denominator is zero.

    ``None`` rather than ``0.0``: "no attempts" and "all attempts failed" are the same number and
    opposite facts, and section 37's whole point is that the shape of the funnel is the finding.
    """
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def build_funnel(
    *,
    root: Path | str = ".",
    now: datetime | None = None,
    window_days: int = 1,
) -> LearningFunnel:
    """Fold every ledger into the funnel and the KPI set.  Pure; reads only.

    ``root`` locates the stores, so this runs against a production worktree or a development tree
    without touching a module global -- and so a test can point it at a fixture.
    """
    base = Path(root)
    moment = now or datetime.now(timezone.utc)
    since = moment - timedelta(days=max(1, int(window_days)))

    planner = _read_lines(base / PLANNER_LEDGER)
    planner_calls = [row for row in planner if str(row.get("source") or "") in PLANNER_SOURCES]
    planner_today = _within(planner_calls, since=since)
    # Two row shapes live in one file: a plan (with a decision) and a settlement (``record:
    # outcome``, the verifier's verdict on the step that answer drove).  Separating them here is
    # what lets "the model proposed something" be counted apart from "the game agreed".
    plans = [row for row in planner_calls if row.get("decision") or row.get("error")]
    outcomes = [row for row in planner_calls if str(row.get("record") or "") == "outcome"]
    plans_today = [row for row in planner_today if row.get("decision") or row.get("error")]
    outcomes_today = _within(outcomes, since=since)

    learned_rows = unknown_learning.VerifiedStepLedger(
        base / unknown_learning.LEARNED_STEPS_PATH
    )
    verified_steps = learned_rows.verified()
    verified_today = _within(verified_steps, since=since)

    requests = _rows_under(base / UNKNOWN_REQUESTS)
    requests_today = _within(requests, since=since)

    candidates = _rows_under(base / SKILL_CANDIDATES)
    candidates_today = _within(candidates, since=since)
    strengthened = [row for row in candidates if str(row.get("status")) == "CANDIDATE_STRENGTHENED"]

    repairs = _rows_under(base / REPAIR_CANDIDATES)
    repairs_today = _within(repairs, since=since)
    repairs_verified = [row for row in repairs if str(row.get("status")) == "VERIFIED_PATCH"]

    pages_index = _read_json(base / PAGE_STORE_INDEX) or {}
    elements_index = _read_json(base / ELEMENT_STORE_INDEX) or {}
    page_counts = dict(pages_index.get("counts_by_status") or {})
    element_counts = dict(elements_index.get("counts_by_status") or {})
    clusters = _read_json(base / OFFLINE_CLUSTERS) or {}

    episodes = _read_lines(base / EPISODES)
    episodes_today = _within(episodes, since=since)
    succeeded = [row for row in episodes_today if str(row.get("result")) == "SUCCESS"]
    # The completion rate is over *steps that finished*, i.e. the denominator excludes INCOMPLETE
    # and PROGRESS rows.  A rate over every row would fall whenever the agent correctly observed
    # something, which is the opposite of what a completion rate is for.
    finished = [row for row in episodes_today if str(row.get("result")) in ("SUCCESS", "FAILURE")]

    # KNOWN_MODEL_CALLS, as evidence rather than assertion: ledger rows whose page key is a *named*
    # page.  The planner's call site is guarded by "unnamed screen" only, so any row on a named page
    # is a call that should not have happened.
    named_page_calls = [
        row for row in plans
        if str(row.get("page_key") or "") and not str(row.get("page_key") or "").startswith("UNKNOWN")
    ]
    named_page_calls_today = [
        row for row in plans_today
        if str(row.get("page_key") or "") and not str(row.get("page_key") or "").startswith("UNKNOWN")
    ]

    proposal_refusals: dict[str, int] = {}
    for row in plans:
        error = str(row.get("error") or "")
        if not error:
            continue
        key = error.split(":")[0].strip()
        proposal_refusals[key] = proposal_refusals.get(key, 0) + 1

    executed = [row for row in outcomes]
    executed_ok = [row for row in executed if row.get("verifier_ok") is True]
    executed_fail = [row for row in executed if row.get("verifier_ok") is False]

    funnel = (
        FunnelCounts(
            "unknown_observed",
            len(requests) + len(verified_steps) or None,
            source=f"{UNKNOWN_REQUESTS}/*.json + {unknown_learning.LEARNED_STEPS_PATH}",
            unmeasured_reason="" if (requests or verified_steps) else "NO_UNKNOWN_FILED_YET",
        ),
        FunnelCounts(
            "model_proposed",
            len(plans),
            source=str(PLANNER_LEDGER),
            unmeasured_reason="" if plans else "NO_PLANNER_CALLS_YET",
        ),
        FunnelCounts(
            "grounding_valid",
            None,
            source=str(PLANNER_LEDGER),
            unmeasured_reason=(
                "GROUNDING_RESULT_NOT_PERSISTED -- the runtime refuses an ungrounded point on "
                "stdout only; the funnel cannot separate 'the model pointed nowhere' from "
                "'the model was never asked'. Recording this needs a row at the refusal site."
            ),
        ),
        FunnelCounts(
            "risk_allowed",
            None,
            source=str(PLANNER_LEDGER),
            unmeasured_reason="RISK_REFUSAL_NOT_PERSISTED -- same gap as grounding_valid",
        ),
        FunnelCounts(
            "maa_executed",
            len(executed),
            source=str(PLANNER_LEDGER),
            unmeasured_reason="" if executed else "NO_ADVISED_STEP_SETTLED_YET",
        ),
        FunnelCounts(
            "verifier_progress",
            None,
            source=str(EPISODES),
            unmeasured_reason=(
                "PROGRESS_IS_NOT_JOINED_TO_THE_ADVISED_STEP -- episodes carry result=PROGRESS but "
                "nothing links one to the planner request that caused it"
            ),
        ),
        FunnelCounts(
            "verifier_success",
            len(executed_ok),
            source=str(PLANNER_LEDGER),
            unmeasured_reason="" if executed else "NO_ADVISED_STEP_SETTLED_YET",
        ),
        FunnelCounts(
            "candidate_step",
            len(verified_steps),
            source=str(unknown_learning.LEARNED_STEPS_PATH),
            unmeasured_reason="" if verified_steps else "NO_VERIFIED_STEP_YET",
        ),
        FunnelCounts(
            "candidate_skill",
            len(candidates),
            source=str(SKILL_CANDIDATES),
            unmeasured_reason="" if candidates else "NOTHING_COMPILED_YET",
        ),
        FunnelCounts("replay_pass", None, unmeasured_reason="REPLAY_RUNS_OUTSIDE_THE_RUNTIME"),
        FunnelCounts("shadow_pass", None, unmeasured_reason="SHADOW_RUNS_OUTSIDE_THE_RUNTIME"),
        FunnelCounts(
            "live_verified", None,
            unmeasured_reason="REGISTRY_OWNS_THIS -- the learning ledgers deliberately cannot say it",
        ),
        FunnelCounts(
            "stable", None,
            unmeasured_reason="REGISTRY_OWNS_THIS -- see knowledge/goals/capability_skill_map.json",
        ),
    )

    repeat_rate = _ratio(len(named_page_calls_today), len(plans_today))
    metrics = {
        "GAME_TASK_COMPLETION_RATE": _ratio(len(succeeded), len(finished)),
        "game_task_completion_rate_n": len(finished),
        "UNKNOWN_RESOLUTION_RATE": _ratio(len(verified_steps), len(requests) + len(verified_steps)),
        "UNKNOWN_VERIFIER_PASS_RATE": _ratio(len(executed_ok), len(executed) or None),
        "UNKNOWN_REPEAT_MODEL_CALL_RATE": repeat_rate,
        # The windowed repeat rate is the one the console shows; the all-time one is kept beside it
        # because a first day with no history cannot move an average, and a reader should see both.
        "UNKNOWN_REPEAT_MODEL_CALL_RATE_ALL_TIME": _ratio(len(named_page_calls), len(plans)),
        "CANDIDATE_TO_STABLE_RATE": None,
        "CANDIDATE_TO_STABLE_RATE_REASON": "STABLE is the registry's word; see FUNNEL stage 'stable'",
        "SKILL_REPAIR_SUCCESS_RATE": _ratio(len(repairs_verified), len(repairs) or None),
        "KNOWN_MODEL_CALLS": len(named_page_calls),
        "KNOWN_MODEL_CALLS_TODAY": len(named_page_calls_today),
        "MODEL_CALLS_PER_HOUR": (
            round(len(plans_today) / (max(1, int(window_days)) * 24), 3) if plans_today else 0.0
        ),
        "UNKNOWN_MODEL_CALLS": len(plans),
        "UNKNOWN_MODEL_CALLS_TODAY": len(plans_today),
        "UNKNOWN_VERIFIED_STEPS_CREATED": len(verified_steps),
        "UNKNOWN_VERIFIED_STEPS_CREATED_TODAY": len(verified_today),
        "CANDIDATE_SKILLS_CREATED": len(candidates),
        "CANDIDATE_SKILLS_CREATED_TODAY": len(candidates_today),
        "CANDIDATE_SKILLS_STRENGTHENED": len(strengthened),
        "CANDIDATE_SKILLS_PROMOTED": None,
        "STABLE_SKILLS_CREATED": None,
        "SKILL_REPAIR_ATTEMPTS": len(repairs),
        "SKILL_REPAIR_ATTEMPTS_TODAY": len(repairs_today),
        "SKILL_REPAIR_VERIFIED": len(repairs_verified),
        "CANDIDATE_PAGES_CREATED": int(page_counts.get("DISCOVERED", 0)),
        "CONFIRMED_PAGES_CREATED": int(page_counts.get("VERIFIED", 0)),
        "CANDIDATE_UI_SEMANTICS_CREATED": int(element_counts.get("DISCOVERED", 0)),
        "CONFIRMED_UI_SEMANTICS": int(element_counts.get("VERIFIED", 0)),
        "OFFLINE_UNKNOWN_CLUSTERS": int(clusters.get("clusters") or 0),
        "OFFLINE_KNOWLEDGE_CANDIDATES": int(clusters.get("candidate_knowledge") or 0),
        "PROPOSAL_REFUSALS": proposal_refusals,
    }

    # Section 36's console, in Chinese, with the field each line reads.  Chinese because the
    # operator reads it, and with the source beside it because a number without one is a number
    # that cannot be argued with.
    console = {
        "今日 UI-Venus 调用": len(plans_today),
        "UNKNOWN 次数": len(requests_today) or len(requests),
        "UNKNOWN 成功解决": len(verified_today),
        "Verifier 通过数": len(executed_ok),
        "新 Candidate Skill": len(candidates_today),
        "新 Stable Skill": None,
        "Skill Repair 成功数": len(repairs_verified),
        "新增 Candidate Page": int(page_counts.get("DISCOVERED", 0)),
        "新增 Confirmed Page": int(page_counts.get("VERIFIED", 0)),
        "重复 UNKNOWN 调用率": repeat_rate,
        "KNOWN_MODEL_CALLS": len(named_page_calls_today),
        "今日游戏任务完成率": metrics["GAME_TASK_COMPLETION_RATE"],
    }

    return LearningFunnel(
        generated_at=_now(),
        window_days=int(window_days),
        funnel=funnel,
        metrics=metrics,
        console=console,
        sources={
            "planner_ledger": str(PLANNER_LEDGER),
            "episodes": str(EPISODES),
            "unknown_requests": str(UNKNOWN_REQUESTS),
            "learned_steps": str(unknown_learning.LEARNED_STEPS_PATH),
            "skill_candidates": str(SKILL_CANDIDATES),
            "repair_candidates": str(REPAIR_CANDIDATES),
            "page_store": str(PAGE_STORE_INDEX),
            "element_store": str(ELEMENT_STORE_INDEX),
            "offline_clusters": str(OFFLINE_CLUSTERS),
        },
    )


def render_console(funnel: LearningFunnel, *, width: int = 34) -> str:
    """The console block, as text.  One line per metric, ``—`` for an unmeasured stage."""
    lines = [f"学习效果（最近 {funnel.window_days} 天）", "─" * (width + 14)]
    for label, value in funnel.console.items():
        shown = "—" if value is None else (
            f"{value:.0%}" if isinstance(value, float) and 0.0 <= value <= 1.0 and "率" in label
            else str(value)
        )
        lines.append(f"{label:<{width}} {shown:>10}")
    lines.append("─" * (width + 14))
    lines.append("漏斗")
    for stage in funnel.funnel:
        if stage.count is None:
            lines.append(f"  {stage.stage:<28} {'—':>6}  ({stage.unmeasured_reason})")
        else:
            lines.append(f"  {stage.stage:<28} {stage.count:>6}  ({stage.source})")
    return "\n".join(lines)


def refresh(
    *,
    root: Path | str = ".",
    window_days: int = 1,
    write_to: Path | str | None = Path("learning/learning_funnel.json"),
) -> LearningFunnel:
    """Build the funnel and, by default, persist it for the panel to read.

    The panel reads a file rather than recomputing: it refreshes on a UI tick, and folding
    ``episodes.jsonl`` (thousands of rows) on every tick would make the console the slowest thing
    in the process.
    """
    funnel = build_funnel(root=root, window_days=window_days)
    if write_to:
        try:
            path = Path(root) / Path(write_to) if not Path(write_to).is_absolute() else Path(write_to)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(funnel.to_row(), ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except (OSError, TypeError, ValueError):
            pass
    return funnel
