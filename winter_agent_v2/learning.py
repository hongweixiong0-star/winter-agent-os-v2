from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any


@dataclass(frozen=True)
class Episode:
    """One production step, with the evidence needed to prove it happened.

    ``before_screenshot`` / ``after_screenshot`` are absolute paths.  They are
    what makes an episode auditable and what retention consults so a referenced
    frame is never pruned; without them "PRODUCTION evidence" was a claim with
    nothing behind it.  ``episode_id`` is unique per run, so the old
    ``step_001_before.png`` collision across episodes cannot come back.
    """

    skill: str
    state_before: dict[str, Any]
    action: dict[str, Any]
    state_after: dict[str, Any]
    result: str
    failure_type: str | None
    duration: float
    mode: str
    episode_id: str = ""
    goal_id: str = ""
    step_id: int = 0
    before_screenshot: str = ""
    after_screenshot: str = ""
    verifier_ok: bool | None = None
    # Why the verifier said so.  The boolean alone cannot answer what a step was accepted ON, and
    # measured 2026-09-23 that cost real time: of 6603 episodes on file only 29 carried any evidence
    # dict, so auditing a passed step meant re-deriving the verifier's reasoning from the two frames.
    # Every verifier already returns that dict; this is the field that keeps it.
    verifier_evidence: dict[str, Any] = field(default_factory=dict)
    recovery_result: str | None = None
    # Did the *goal* move, which is a different question from whether the action
    # worked.  Measured 2026-09-18: 58 of 60 consecutive episodes were
    # AVOID_STAMINA_WASTE / SCAN_MAP_FOR_BEAST with ``verifier_ok=True`` and a
    # stamina reading that never left 457 -- every step passed its verifier and the
    # goal made no progress at all for twenty minutes, because "the swipe landed"
    # was the only thing being measured.  ``None`` means the goal was not
    # observable on both frames, which is not the same as "no progress".
    goal_progress: bool | None = None
    # One physical action can advance more than one Goal. Keep the association on
    # the step record; each entry in ``goal_progress_by_id`` is measured against
    # that Goal's own observed meter, never inferred from the selected Goal alone.
    attached_goal_ids: tuple[str, ...] = ()
    goal_progress_by_id: dict[str, bool | None] = field(default_factory=dict)
    completed_goal_ids: tuple[str, ...] = ()
    # Which backend actually executed this step ("MAA" / "ADB" / "" when nothing
    # was issued).  Recorded per episode so the MAA rollout is auditable from the
    # production stream instead of from a migration document.
    executor_backend: str = ""
    # The full call chain for this step: which channel produced the frames, who
    # recognised the target, who issued the input.  Never inferred from config -
    # an episode claiming MAA happened because MAA ran.
    capture_backend: str = ""
    recognition_backend: str = ""
    action_backend: str = ""
    executor_latency_ms: float | None = None
    # Which tree revision this run imported its code from.  Stamped per run, because
    # the worker is a fresh process every cycle: it is the fact that separates "the
    # new version works" from "AUTO happened to succeed again while a job was open"
    # (RR-004, measured 2026-09-18).
    repo_revision: str = ""
    # Which kind of cycle produced this step.  ``PRODUCTION`` is the default because that is
    # what an AUTO cycle is, and a default of ``""`` would have made every existing producer
    # silently ambiguous -- the operator's rule is that a *validation* episode must never be
    # mistaken for production reuse, and that distinction has to be explicit on the row.
    execution_mode: str = "PRODUCTION"
    # The trace this step belongs to when it was produced by a Development Validation cycle:
    # which escalation, which job, which capability, and which version the cycle expected to
    # be running.  Empty on a production step, where there is no version being examined.
    trace_id: str = ""
    job_id: str = ""
    capability: str = ""
    expected_after_version: str = ""
    # Which *account* this step belongs to.  The project's own role audit found the corpus
    # was already pooled from two accounts (70,206,322 power / 6 march slots vs 542,443 /
    # 2), so every metric that pooled them was un-scoped -- and this was the one field the
    # episode stream did not carry.  Read once per run from the persisted role artifact.
    #
    # ``""`` is honest and load-bearing: it means the role was never read off the client,
    # which is true for all of history and for any run where the panel has no fresh read.
    # It is deliberately NOT filled in with a configured or default name.
    role_id: str = ""
    # How that role is known: LIVE_OBSERVED / PERSISTED / STALE / UNKNOWN.  A role-scoped
    # claim may only be made from an episode whose scope is at least PERSISTED, and a
    # fresh read never inherits an older run's scope.
    role_scope: str = ""
    # ---------------------------------------------------------------- causality
    # Operator §六/§十二: an episode must answer "what did we expect, what actually
    # changed".  Both existed in the run and neither reached the row -- the
    # expectation lived only on ``Decision`` (and in the runtime snapshot's
    # ``next_action``), and the change had to be reverse-engineered by diffing two
    # ``asdict(WorldState)`` blobs with no vocabulary for the answer.
    #
    # ``control`` is the semantic that was aimed at, so a row can be joined back to
    # ``learning/control_experience.json`` under one key.  Empty means the action had
    # no semantic target (a Back, a wait), which is not the same as "unknown".
    control: str = ""
    expected_result: str = ""
    # *Which branch* decided this step.  The decision's own reason string, verbatim.
    #
    # Measured 2026-09-23, and it is why the field exists: eight consecutive `OPEN_HOME` failures stood
    # on a map whose search panel covers the 城镇 door, and the whole question -- "who emitted a hop
    # home from a frame it cannot land on?" -- could not be answered from the stream.  The reason WAS
    # written by every step, into the worker's stdout, where it survives only until the log rotates
    # (``learning/control_panel/latest.log`` held the last round and nothing older), so the answer had
    # to be re-derived by elimination: the brain cannot emit `OPEN_HOME` for a goal-less run, so the
    # emitter had to be the runtime's own deferral hop.  That reasoning was right, and it should not
    # have been necessary -- the same lesson as ``verifier_evidence`` above and open issue #0aw.
    decision_reason: str = ""
    # The *session engine's* verdict for this step, verbatim: one of
    # ``StepOutcome`` (SUCCESS / PROGRESS / STILL_PENDING / AMBIGUOUS / FAILED).
    #
    # It was already computed and already passed to the writer, and then thrown away: the
    # parameter was read only to choose a value for ``result`` and never stored.  Measured
    # 2026-09-30 on 108 session steps, and the cost was that the outcome became
    # unmeasurable.  ``STILL_PENDING`` -- "the work is in flight" -- is not in the set the
    # fold admits, so it fell through to the default and every such step was written
    # ``result="FAILURE"`` with ``failure_type="NO_EXECUTION"``: 44 rows telling the
    # operator that a fishing cast had failed when the cast was still swimming.  A count
    # of "how long may a flow stay pending" cannot be taken from a ledger that answers
    # "failed", and an offline replay that reconstructs the outcome from ``result`` gets
    # the engine's own ``#44`` question wrong.
    #
    # ``""`` means the step was not a session step, which is true for every goal-driven
    # row and is deliberately not filled in with a guess.
    session_outcome: str = ""
    # One of ``control_experience.CHANGE_KINDS``.  NO_OP and UNKNOWN are kept apart
    # on purpose: "the tap was issued and nothing moved" is a finding about the
    # control, "we could not tell" is a finding about the reading.
    observed_change: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class ActionOutcome:
    """Observed outcome of one physical action and its role-scoped Goal effects."""

    action_id: str
    role_id: str
    skill_id: str
    goal_id: str = ""
    attached_goal_ids: tuple[str, ...] = ()
    action_sent: bool = False
    post_action_observed: bool = False
    observed_change: str = "UNKNOWN"
    verifier_result: str = "NOT_RUN"
    goal_progress_by_id: dict[str, bool | None] = field(default_factory=dict)
    credited_goal_ids: tuple[str, ...] = ()
    completed_goal_ids: tuple[str, ...] = ()
    failure_reason: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EpisodeStore:
    def __init__(self, path: Path, *, limit: int = 10000) -> None:
        self.path = path
        self.limit = max(1, int(limit))
        self._line_count: int | None = None
        self._ends_with_newline = True
        self._index_path = self.path.with_name(f".{self.path.name}.index.json")

    def append(self, episode: Episode) -> None:
        self._append_line(json.dumps(
            asdict(episode),
            ensure_ascii=False,
            default=lambda value: value.value if hasattr(value, "value") else str(value),
        ))

    def _append_line(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._line_count is None:
            self._line_count, self._ends_with_newline = self._load_line_index()

        # Production calls this once for every UI action. Re-reading and rewriting
        # the complete, growing ledger made each action O(total history size).
        # Keep the hot path to one small append; compact in bounded batches below.
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            if self._line_count and not self._ends_with_newline:
                stream.write("\n")
            stream.write(line)
            stream.write("\n")
        self._line_count += 1
        self._ends_with_newline = True

        # Let the ledger grow by at most ~5% (capped at 512 rows) between
        # compactions. This retains the configured history bound without making
        # every append rewrite all retained production evidence.
        overflow = max(1, min(512, self.limit // 20))
        if self._line_count > self.limit + overflow:
            try:
                self._compact_to_limit()
            except OSError:
                # The just-appended evidence is already durable. A failed
                # housekeeping compaction must not turn it into a failed action.
                pass
        self._persist_line_index()

    def _load_line_index(self) -> tuple[int, bool]:
        if not self.path.is_file():
            return 0, True
        try:
            stat = self.path.stat()
            with self._index_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if (
                isinstance(payload, dict)
                and payload.get("version") == 1
                and payload.get("file_size") == stat.st_size
                and payload.get("modified_ns") == stat.st_mtime_ns
                and isinstance(payload.get("line_count"), int)
                and payload["line_count"] >= 0
            ):
                return payload["line_count"], bool(payload.get("ends_with_newline", True))
        except (OSError, ValueError, TypeError):
            pass
        return self._count_existing_lines()

    def _count_existing_lines(self) -> tuple[int, bool]:
        if not self.path.is_file():
            return 0, True
        count = 0
        last_byte = b""
        with self.path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if last_byte and last_byte != b"\n":
            count += 1
        return count, not last_byte or last_byte == b"\n"

    def _compact_to_limit(self) -> None:
        assert self._line_count is not None
        drop = max(0, self._line_count - self.limit)
        if not drop:
            return
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as target:
                temporary_path = Path(target.name)
                with self.path.open("r", encoding="utf-8", newline="") as source:
                    for _ in range(drop):
                        if source.readline() == "":
                            break
                    for row in source:
                        target.write(row)
                        if not row.endswith("\n"):
                            target.write("\n")
                target.flush()
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        assert temporary_path is not None
        try:
            temporary_path.replace(self.path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        self._line_count = self.limit
        self._ends_with_newline = True

    def _persist_line_index(self) -> None:
        if self._line_count is None:
            return
        temporary_path: Path | None = None
        try:
            stat = self.path.stat()
            payload = {
                "version": 1,
                "file_size": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
                "line_count": self._line_count,
                "ends_with_newline": self._ends_with_newline,
            }
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=self.path.parent,
                prefix=f".{self._index_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(json.dumps(payload, separators=(",", ":")))
                stream.write("\n")
            temporary_path.replace(self._index_path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class ResourceSpend:
    resource: str
    amount: int | float | None
    reason: str
    expected_value: str
    before: int | float | None
    after: int | float | None


class ResourceLedger(EpisodeStore):
    def append_spend(self, spend: ResourceSpend) -> None:
        self._append_line(json.dumps(asdict(spend), ensure_ascii=False))
