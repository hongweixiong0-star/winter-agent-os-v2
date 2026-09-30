# -*- coding: utf-8 -*-
"""The bridge between the Generic Session Engine and a live run.

Why this file is thin on purpose
--------------------------------
The engine (``session_engine``) owns the sequence, the budgets and the lifecycle.  The
business adapter (``session_adapters``) owns the domain reading.  This host owns **the
wire**: the six or seven primitives a session needs in order to touch the real client --
one frame, one read, one atomic skill, one verdict, one episode row, one question to the
Scheduler.

Everything expensive or dangerous is *borrowed* from ``LiveRuntime`` rather than
re-implemented:

* the executor and the backend router come from ``runtime._session_execute_atomic``, so a
  session step goes through the same ADB/MAA routing row the loop uses;
* the verifier comes from ``runtime._session_verify``, so a session's ``START_RALLY`` is
  judged by the same target-scoped check as any other rally;
* the episode row comes from ``runtime._record_episode``, the run's single writer;
* the OCR comes from ``runtime._ocr_service``, the project's single reader;
* the preemption answer comes from ``Scheduler.session_preemption`` -- the existing single
  Scheduler's own method.

There is deliberately **no** ``select_goal`` and no ``switch_role`` on this class.  That is
not a convention: ``SessionHost`` (the protocol the engine is typed against) does not
declare them, so an adapter cannot call one even by accident.  A session that wants to work
on another Goal must end and return to the Scheduler, which is constraint 8 of the
directive expressed as a missing method.

Two hazards this file handles explicitly
----------------------------------------
1. **VISION_POLICY_V1 section C/F**: while a realtime servo loop is open, ANY text
   recognition raises ``VisionPolicyViolation``.  So the "wait until the level is on
   screen" phase runs entirely on the adapter's own OpenCV detector and finishes *before*
   the servo opens its gate.  ``ocr()`` also refuses outright while a session is active, so
   the refusal is visible at this seam rather than only buried inside the servo.
2. **§24 (坐标不是知识，UI 元素才是)**: a printed-word tap locates the word on the frame in
   hand and taps what it found.  If the same word appears more than once, the host refuses
   instead of guessing which control was meant -- a guess about a coordinate is exactly what
   §24 forbids, and refusing is cheaper than the wrong tap.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from . import vision_policy as vp
from .device_lease import OWNER_GAMEPLAY
from .models import WorldState
from .models import Action, ExecutionResult, VerificationResult
from .ocr import read_frame_size
from .session_adapters import _stamina_of
from .session_engine import (
    STEP_OBSERVE_ONLY,
    STEP_PRINTED_TAP,
    STEP_REALTIME,
    STEP_SEMANTIC_TAP,
    STEP_SKILL,
    RealtimeControl,
    SessionContext,
    SessionStep,
    StepExecution,
    StepVerdict,
    YieldVerdict,
)


@dataclass
class SessionRunBinding:
    """The run-scoped facts a session needs, and none of the decisions.

    Deliberately not "the runtime": handing an adapter the runtime would hand it the Goal
    Library, the role controller and the brain, which is the whole thing the session is not
    allowed to touch.  What is here is the frame the cycle was decided on, where it is on
    disk, which Goal and role it belongs to, and the run's own audit/latency dictionaries so
    a session's steps are accounted for in the same places as everyone else's.
    """

    index: int
    goal_id: str
    role_id: str
    before: WorldState
    before_path: Path
    latency: dict = field(default_factory=dict)
    page_audit: dict = field(default_factory=dict)
    settle_seconds: float = 1.0
    planned_resource: str | None = None
    rally_target: Any = None
    committed_goal: str = ""
    attached_goal_ids: tuple[str, ...] = ()


def _norm(text: Any) -> str:
    return "".join(ch for ch in str(text or "") if not ch.isspace())


def _target_visible(state: Any) -> bool:
    """Did this detector answer "the target is on screen"?

    Duck-typed on purpose: the fishing detector returns a ``FishingFrame`` with ``found``,
    and a future realtime adapter may return a plain dict.  ``found`` wins when present
    because a detector that sets ``found`` is stating an answer; ``lost`` is only consulted
    when there is no ``found`` to read.
    """
    if isinstance(state, Mapping):
        if state.get("found") is not None:
            return bool(state["found"])
        return not bool(state.get("lost", False))
    found = getattr(state, "found", None)
    if found is not None:
        return bool(found)
    return not bool(getattr(state, "lost", False))


class LiveRuntimeSessionHost:
    """``SessionHost`` over an in-flight ``LiveRuntime``.

    One instance per session.  The engine holds no state between sessions and neither does
    this: the per-step stash below is the last attempt of the step currently being recorded,
    and a new session gets a new host.
    """

    def __init__(self, runtime: Any, binding: SessionRunBinding) -> None:
        self.runtime = runtime
        self.binding = binding
        #: Narration lines, also mirrored onto the run's per-step audit row.
        self.notes: list[str] = []
        #: The step reports this session produced, for the run's own accounting.
        self.step_reports: list[dict[str, Any]] = []
        #: The frame the adapter decided on.  Set by ``observe``; reused by the next step's
        #: verifier so a session does not pay a full observation twice per step.
        self._last_world: WorldState | None = None
        self._last_world_path: Path | None = None
        #: Transport objects for the step being recorded.  ``report.evidence`` is serialised,
        #: so the live ``ExecutionResult`` / ``VerificationResult`` live here instead of in it.
        self._execution: Any = None
        self._verification: Any = None
        self._before: WorldState | None = None
        self._after: WorldState | None = None
        self._before_path: Path | None = None
        self._after_path: Path | None = None
        self._device_lost_seen = False

    # ----------------------------------------------------------------- time & device

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        """The runtime's own sleeper, so an interrupt behaves the same inside a session."""
        delay = max(0.0, float(seconds))
        try:
            self.runtime.sleeper(delay)
        except Exception:  # noqa: BLE001 - a bad sleeper must not end a session
            time.sleep(delay)

    def device(self) -> Any:
        """The touch + fast-capture device, or the observation device when there is none.

        A realtime servo needs ``capture``/``touch_down``/``touch_move``/``touch_up``; the
        ADB-only device has none of them.  Asking for the capability rather than a name is
        what keeps this correct when MAA observation is off (ADB executor) or on (MAA).
        """
        needed = ("capture", "touch_down", "touch_move", "touch_up")
        for holder in (self.runtime.device, getattr(self.runtime, "maa_adapter", None),
                       getattr(self.runtime, "adb_device", None)):
            if holder is not None and all(hasattr(holder, name) for name in needed):
                return holder
        return self.runtime.device

    def capture(self) -> Any:
        """One frame, cheap path only.  ``None`` when the device cannot answer."""
        source = getattr(self.device(), "capture", None)
        if source is None:
            return None
        try:
            return source()
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------------ reading

    def ocr(self, frame: Any = None, *,
            region: tuple[float, float, float, float] | None = None) -> list[dict[str, Any]]:
        """Read text off ``frame`` (or one normalised region of it).

        Built on the runtime's own ``OCRService``: it already owns the screenshot-hash cache
        and the ROI path, so a session that read text with anything else would be a second
        reader with a second answer to "what does this screen say".

        Refuses inside a realtime session rather than trusting the servo's own gate, because
        VISION_POLICY_V1 section C/F makes that a hard error and this seam is where a future
        adapter would most plausibly try it.
        """
        if vp.realtime_active() is not None:
            return []
        service = self.runtime._ocr_service()
        if service is None:
            return []
        path = self._frame_to_path(frame)
        if path is None:
            return []
        roi = self._roi_of(region)
        try:
            result = service.recognize(path, roi, upright=True) if roi else service.recognize(path)
        except Exception:  # noqa: BLE001 - an unreadable frame is "no words", not a crash
            return []
        width = height = 0.0
        size = read_frame_size(path)
        if size:
            width, height = float(size[0]), float(size[1])
        # ``OCRService`` crops before recognising, so a region's token boxes come back in the
        # crop's own pixels.  Adding the offset back is what keeps ``center_norm`` a position
        # on the *frame* -- a crop-local centre read as a frame centre is a coordinate nobody
        # measured, which is the failure §24 is about.
        off_x = off_y = 0.0
        if roi is not None and width and height:
            off_x, off_y = roi["x_norm"] * width, roi["y_norm"] * height
        tokens: list[dict[str, Any]] = []
        for token in getattr(result, "tokens", ()) or ():
            try:
                cx, cy = token.centre
            except Exception:  # noqa: BLE001
                cx = cy = 0.0
            tokens.append({
                "text": str(getattr(token, "text", "") or ""),
                "confidence": getattr(token, "confidence", None),
                "center_norm": (((off_x + cx) / width, (off_y + cy) / height)
                                if width and height else None),
            })
        return tokens

    def observe(self, phase: str) -> Any:
        """The runtime's existing full observation.  Safe points only.

        A session step's verifier compares two states of the client, so the *second* one has
        to be read after the action -- this is that read.  The first one is the frame the
        adapter decided on (see ``_world_for_step``), never a second observation of a frame
        that cannot be newer than the decision it would justify.
        """
        path = self._fresh_path("session_observe", suffix=str(phase or "step"))
        if self.runtime._device_lost(self.runtime.device.screenshot, path):
            self._device_lost_seen = True
            return None
        world = self.runtime._observe(path, latency=self.binding.latency,
                                      phase=f"session_{phase}")
        if self.binding.latency is not None:
            self.binding.latency.setdefault("session_observes", 0)
            self.binding.latency["session_observes"] += 1
        self._last_world = world
        self._last_world_path = path
        if phase == 'after':
            self._after = world
            self._after_path = path
        return world

    def widen(self, phase: str = "loop_widen") -> Any:
        """A fresh frame read with every expensive sweep allowed.

        LOOP_DETECTOR_V1's ``widen_observe`` rung, and nothing more: the runtime's own
        observation with its one widening flag set.  Deliberately a *separate frame* rather
        than a re-look at the one the decision was made on -- a loop means the last look was
        not enough, and re-reading the same picture cannot answer a question the picture has
        already answered.  Costs the sweeps, which is why only the ladder asks for it.
        """
        world = self._observe_with(phase, widen=True)
        self._last_world = world
        return world

    def _observe_with(self, phase: str, *, widen: bool) -> Any:
        """Shared body of ``observe`` and ``widen`` -- one reader, two verbosities."""
        path = self._fresh_path("session_observe", suffix=str(phase or "step"))
        if self.runtime._device_lost(self.runtime.device.screenshot, path):
            self._device_lost_seen = True
            return None
        world = self.runtime._observe(path, latency=self.binding.latency,
                                      phase=f"session_{phase}", widen=widen)
        if self.binding.latency is not None:
            self.binding.latency.setdefault("session_observes", 0)
            self.binding.latency["session_observes"] += 1
        self._last_world_path = path
        return world

    # ------------------------------------------------------------------- one step

    def execute_step(self, step: SessionStep) -> StepExecution:
        started = time.monotonic()
        self._reset_stash()
        kind = str(step.kind or STEP_SKILL)
        if kind == STEP_OBSERVE_ONLY:
            # There is nothing to drive.  The adapter's own verifier is what reads the screen
            # for this kind, which is why the engine does not require an execution here.
            self.sleep(min(0.5, self.binding.settle_seconds))
            return StepExecution(executed=False, reason="OBSERVE_ONLY", latency_ms=0.0)
        if kind == STEP_REALTIME:
            return self._run_realtime(step, started)
        if kind in (STEP_PRINTED_TAP, STEP_SEMANTIC_TAP):
            return self._tap_printed(step, started)
        return self._run_skill(step, started)

    def verify_step(self, step: SessionStep, execution: StepExecution) -> Any:
        """The runtime's own verdict for this step's skill, or ``None`` when it has none.

        ``None`` rather than a fabricated ``False``: "nobody judged this" and "the client
        answered no" are different facts, and a verifier that flattens them turns a missing
        verifier into a failure report.  The adapter's ``verify_step`` maps this onto the
        five unified outcomes -- that mapping is domain knowledge, not transport.
        """
        if str(step.kind or STEP_SKILL) != STEP_SKILL:
            return None
        verdict = self.runtime._session_verify(
            str(step.skill_id or ""),
            getattr(execution, "before", None),
            getattr(execution, "after", None),
            self.binding.rally_target,
        )
        self._verification = verdict
        return verdict

    def record_step(self, report: Any) -> str | None:
        """Append this step to the run's episode stream.

        Reuses the run's single episode writer, so a session step is the same kind of row as
        any other step and carries this batch's goal/role.  The decision reason names the
        session, which is what makes a session step distinguishable in the stream from a
        goal-driven one without inventing a second field.

        Returns the episode id (the capture folder's own name -- the identifier the
        screenshots and the ledger already share).
        """
        try:
            self.step_reports.append(dict(report.as_row() or {}))
        except Exception:  # noqa: BLE001
            self.step_reports.append({"skill_id": getattr(report, "skill_id", ""),
                                      "outcome": getattr(report, "outcome", "")})
        execution = self._execution
        if execution is None and getattr(report, "executed", False):
            execution = ExecutionResult(True, False,
                Action(str(getattr(report, "kind", "")), str(getattr(report, "target", ""))),
                backend=str(getattr(report, "backend", "")), detail=dict(getattr(report, "evidence", {}) or {}))
        verification = self._verification
        if verification is None:
            verdict_name = str(getattr(report, "outcome", "")).upper()
            if verdict_name in ("STILL_PENDING", "AMBIGUOUS"):
                # No answer arrived, so nothing judged this step.  ``verify_step`` above states
                # the rule for this file -- ``None`` rather than a fabricated ``False``, because
                # "nobody judged this" and "the client answered no" are different facts -- and
                # fabricating it here was the same defect one layer down: every pending step
                # was written ``verifier_ok=False``, which reads as a verification that was
                # made and rejected.  ``goal_progress`` below still answers ``False`` for these,
                # and that is the honest statement: the step advanced nothing yet.
                verification = None
            else:
                verification = VerificationResult(verdict_name == "SUCCESS",
                                                 str(getattr(report, "reason", "")),
                                                 dict(getattr(report, "evidence", {}) or {}))
        before = self._before if self._before is not None else getattr(report, "before", None)
        after = self._after if self._after is not None else getattr(report, "after", None)
        try:
            from .models import Decision

            skill = str(getattr(report, "skill_id", "") or getattr(report, "kind", "") or "SESSION")
            self.runtime._record_episode(
                decision=Decision(skill, f"session:{getattr(report, 'session_id', '')}:"
                                         f"{getattr(report, 'reason', '')}", 1.0, ""),
                before=before if isinstance(before, WorldState) else self.binding.before,
                execution=execution,
                after=after if isinstance(after, WorldState) else None,
                verification=verification,
                started_at=time.monotonic() - (float(getattr(report, "latency_ms", 0.0) or 0.0) / 1000.0),
                step_id=self.binding.index * 100 + int(getattr(report, "index", 0)) + 1,
                goal_id=self.binding.goal_id,
                attached_goal_ids=self.binding.attached_goal_ids,
                # The session's own verdict is the progress statement for this step; a step
                # that ran and verified is progress, everything else is honestly not.
                goal_progress=bool(str(getattr(report, "outcome", "")).upper() in ("SUCCESS", "PROGRESS")),
                before_screenshot=self._before_path,
                after_screenshot=self._after_path,
                session_outcome=str(getattr(report, "outcome", "")),
            )
        except Exception as exc:  # noqa: BLE001 - the record is evidence, not the step
            self.note("session_episode_failed", reason=f"{type(exc).__name__}:{exc}")
            return None
        return str(self.runtime.capture_dir.name)

    # --------------------------------------------------------------- scheduler contact

    def yield_verdict(self, context: SessionContext, steps_used: int) -> YieldVerdict:
        """Ask the **Global Scheduler** whether to hand the device back.

        This is the engine's only scheduler contact and it is a question, not a decision.
        The answer comes from ``Scheduler.session_preemption`` -- the existing single
        Scheduler's own method, reading its own event readiness -- which is what makes
        "Hard Event 只能通过 Global Scheduler 抢占" true by construction: a session has no
        other way to learn that it should stop.
        """
        scheduler = getattr(self.runtime, "_scheduler", None)
        if scheduler is None:
            return YieldVerdict(False, "", "", None)
        fatal = "DEVICE_LOST" if self._device_lost_seen else ""
        try:
            return scheduler.session_preemption(
                goal_id=self.binding.goal_id,
                role_id=self.binding.role_id,
                steps_used=int(steps_used or 0),
                fatal_reason=fatal,
            )
        except Exception:  # noqa: BLE001 - an oracle that raises must not strand a session
            return YieldVerdict(False, "", "", None)

    # ------------------------------------------------------------------- environment

    def resource_state(self) -> Mapping[str, Any]:
        """The readings the spec's resource floors are checked against.

        ``stamina`` is read from the observation the adapter already made, which is the frame
        the step was chosen on.  A floor checked against a *different* frame than the
        decision would stop sessions the client never asked to stop.  A missing reading
        stays ``None`` and is never flattened to 0 (§真值纪律: 空 ≠ 没有).
        """
        world = self._last_world if isinstance(self._last_world, WorldState) \
            else self.binding.before
        return {
            "stamina": _stamina_of(world),
            "idle_marches": getattr(world, "idle_marches", None),
        }

    def lease_ok(self) -> bool:
        """True while nobody else has taken the device.

        Mirrors the loop's own pre-step check rather than restating the rule: gameplay owning
        the lease is not a conflict, this run owning it is not a conflict, and an unreadable
        lease is unknown -- which must not read as "lost", or a broken lease file would end
        every session.
        """
        lease = getattr(self.runtime, "device_lease", None)
        if lease is None:
            return True
        try:
            held = lease.holder()
        except Exception:  # noqa: BLE001
            return True
        if held is None:
            return True
        if str(getattr(held, "owner", "") or "") == OWNER_GAMEPLAY:
            import os
            return getattr(held, "process", None) == os.getpid()
        try:
            return bool(self.runtime._owns_the_lease(held))
        except Exception:  # noqa: BLE001
            return True

    def note(self, event: str, **fields: Any) -> None:
        """Record diagnostics without stranding a device session on a write failure."""
        if event in {'GIANT_BEAST_DISPATCH_PENDING', 'GIANT_BEAST_RALLY_STARTED'}:
            try:
                from . import observation_store
                reading = fields.get('alliance') or {'rally': {
                    'target_type': 'POLAR_TERROR', 'dispatch_pending': True,
                    'source': 'DISPATCH_SENT_NOT_YET_VERIFIED'}}
                observation_store.record('rally', reading['rally'],
                    path=self.runtime._role_observation_store_path())
            except Exception as exc:  # A telemetry failure cannot repeat a dispatch.
                self.notes.append(f'rally_persistence_failed {type(exc).__name__}:{exc}')
        if event in {"fishing_observation", "fishing_run"}:
            try:
                self._persist_fishing(event, fields)
            except Exception as exc:
                self.notes.append(f"fishing_persistence_failed {type(exc).__name__}:{exc}")
        parts = " ".join(f"{key}={value}" for key, value in sorted(fields.items())
                         if value not in (None, ""))
        line = f"{event} {parts}".strip()
        self.notes.append(line)
        try:
            if isinstance(self.binding.page_audit, dict):
                self.binding.page_audit.setdefault("sessions", []).append(line)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------------- internals

    def _persist_fishing(self, event: str, fields: Mapping[str, Any]) -> None:
        """Use the existing role-scoped fishing store and append-only run ledger."""
        from datetime import datetime, timezone, timedelta
        from .fishing_state import FishingState, FishingRun
        base = Path(self.runtime.episode_store.path).parent
        store = FishingState.load(base / "fishing_state.json", base / "fishing_runs.jsonl")
        role_id = str(self.binding.role_id)
        role_key = next((k for k, role in store.roles.items() if role.role_id == role_id), role_id)
        now = datetime.now(timezone.utc)
        if event == "fishing_run":
            before, after = fields.get("bait_before"), fields.get("bait_after")
            cost = max(0, before - after) if isinstance(before, int) and isinstance(after, int) else 0
            servo = fields.get("servo") or {}
            run = FishingRun(run_id=f"{self.runtime.capture_dir.name}_{self.binding.index}",
                role_key=role_key, at=now, bait_cost=cost,
                points_before=fields.get("points_before"), points_after=fields.get("points_after"),
                depth_m=fields.get("depth_m"), duration_s=servo.get("duration_s"),
                control_hz=servo.get("control_hz"), verifier=fields.get("verifier") or {},
                evidence=str(self.runtime.capture_dir), performance=servo.get('performance') or {})
            store.record_run(run)
            store.observe(role_key, role_id=role_id, bait_current=after,
                          points_total=fields.get("points_after"), now=now)
        else:
            remaining = fields.get("remaining_seconds")
            store.observe(role_key, role_id=role_id, bait_current=fields.get("bait_current"),
                          bait_cap=fields.get("bait_cap"), points_total=fields.get("points_total"),
                          event_end_at=now + timedelta(seconds=remaining) if remaining is not None else None,
                          now=now, extra={"event_live_open": fields.get("event_live_open"),
                                         **{key: fields[key] for key in ("line_level", "hook_level", "sinker_level")
                                            if fields.get(key) is not None},
                                         "source": "AUTO_FISHING_CURRENT_FRAME"})
            role = store.role(role_key)
            for key in ("line_level", "hook_level", "sinker_level"):
                if fields.get(key) is not None:
                    setattr(role, key, fields[key])
        store.save()

    def _reset_stash(self) -> None:
        self._execution = None
        self._verification = None
        self._before = None
        self._after = None
        self._before_path = None
        self._after_path = None

    def _fresh_path(self, stage: str, *, suffix: str = "") -> Path:
        """A self-describing path for one of this session's frames.

        Goes through the runtime's own namer so a session frame is found the same way as
        every other frame (``{episode}_step_{index}_{stage}...``), and a session's pictures
        cannot collide with the loop's.
        """
        try:
            return self.runtime._capture_path(self.binding.index, stage, suffix=suffix)
        except Exception:  # noqa: BLE001
            stamp = int(time.monotonic() * 1000)
            return Path(self.runtime.capture_dir) / f"session_{stage}_{stamp}.png"

    def _frame_to_path(self, frame: Any) -> Path | None:
        if frame is None:
            return getattr(self, '_last_world_path', None)
        if isinstance(frame, (str, Path)):
            return Path(frame)
        path = self._fresh_path("session_ocr")
        try:
            if isinstance(frame, Image.Image):
                frame.convert("RGB").save(path, format="PNG")
            else:
                Image.fromarray(frame).save(path, format="PNG")
        except Exception:  # noqa: BLE001
            return None
        return path

    @staticmethod
    def _roi_of(region: tuple[float, float, float, float] | None) -> dict[str, float] | None:
        """``(x0, y0, x1, y1)`` normalised -> ``OCRService``'s ``x/y/w/h`` form."""
        if region is None:
            return None
        try:
            x0, y0, x1, y1 = (float(value) for value in region)
        except (TypeError, ValueError):
            return None
        return {"x_norm": x0, "y_norm": y0,
                "w_norm": max(0.0, x1 - x0), "h_norm": max(0.0, y1 - y0)}

    def _world_for_step(self) -> tuple[WorldState | None, Path | None]:
        """The observation the adapter decided on; observed fresh only if there is none."""
        if self._last_world is None:
            self.observe("before")
        return self._last_world, self._last_world_path

    # ---- STEP_SKILL ----------------------------------------------------------

    def _run_skill(self, step: SessionStep, started: float) -> StepExecution:
        skill_id = str(step.skill_id or "")
        if not skill_id:
            return StepExecution(executed=False, reason="SESSION_STEP_WITHOUT_SKILL",
                                 latency_ms=(time.monotonic() - started) * 1000)
        before, before_path = self._world_for_step()
        if before is None or before_path is None:
            return StepExecution(executed=False, reason="SESSION_OBSERVE_FAILED",
                                 latency_ms=(time.monotonic() - started) * 1000)
        execution = self.runtime._session_execute_atomic(
            skill_id=skill_id, before=before, before_path=before_path,
            planned_resource=self.binding.planned_resource,
            rally_target=self.binding.rally_target,
        )
        self._before, self._before_path = before, before_path
        latency_ms = (time.monotonic() - started) * 1000
        if execution is None or not execution.executed:
            return StepExecution(
                executed=False,
                reason=str((getattr(execution, "error", "") if execution is not None
                            else "") or "SESSION_STEP_NOT_DISPATCHED"),
                before=before, latency_ms=latency_ms,
                backend=str(getattr(execution, "backend", "") or ""),
                evidence={"skill": skill_id},
            )
        # Settle, then read the client again.  The verifier compares two states and the
        # second one must be read after the action -- reusing the frame the decision was made
        # on would make every session step compare a state with itself.
        self.sleep(self.binding.settle_seconds)
        after = self.observe("after")
        self._execution = execution
        self._after = after
        self._after_path = self._last_world_path
        return StepExecution(
            executed=True,
            reason=skill_id,
            before=before,
            after=after,
            backend=str(getattr(execution, "backend", "") or ""),
            latency_ms=latency_ms,
            tap_point=getattr(execution, "tap_point", None),
            evidence={"skill": skill_id, "error": getattr(execution, "error", None)},
        )

    # ---- STEP_REALTIME -------------------------------------------------------

    def _run_realtime(self, step: SessionStep, started: float) -> StepExecution:
        lease = getattr(self.runtime, "device_lease", None)
        owned = False
        if lease is not None:
            if not self.lease_ok():
                return StepExecution(False, "DEVICE_LEASE_HELD_BY_OTHER_OWNER")
            if lease.holder() is None:
                record, why = lease.acquire(owner=OWNER_GAMEPLAY,
                    capability_id="FISHING_REALTIME", job_id=self.binding.goal_id)
                if record is None:
                    return StepExecution(False, why)
                owned = True
        try:
            return self._run_realtime_owned(step, started)
        finally:
            if owned:
                lease.release(result="FISHING_CONTROL_ENDED")

    def _run_realtime_owned(self, step: SessionStep, started: float) -> StepExecution:
        control = (step.params or {}).get("control")
        if not isinstance(control, RealtimeControl):
            return StepExecution(executed=False, reason="SESSION_REALTIME_WITHOUT_CONTROL",
                                 latency_ms=(time.monotonic() - started) * 1000)
        device = self.device()
        if not all(hasattr(device, name)
                   for name in ("capture", "touch_down", "touch_move", "touch_up")):
            return StepExecution(executed=False, reason="SESSION_REALTIME_NEEDS_TOUCH_DEVICE",
                                 latency_ms=(time.monotonic() - started) * 1000)
        # Wait for the domain BEFORE opening the realtime gate.  The signal is the adapter's
        # own detector -- never a printed word -- because text recognition is forbidden inside
        # the loop, so reading "点击开始" here would be the violation the gate exists to catch.
        # Tutorial acknowledgements are read before the realtime gate, on a fresh frame.
        # No historical tap point survives into the controller.
        self._acknowledge_start_prompts(control)
        start_confirmed = self._wait_for_start(control) if control.start_signal is not None else True
        if not start_confirmed:
            return StepExecution(False, "FISHING_START_NOT_CONFIRMED")
        report = self._drive(control, device)
        payload = self._servo_payload(report)
        payload["start_confirmed"] = start_confirmed
        frames = int(payload.get("frames") or 0)
        moves = int(payload.get("moves_sent") or 0)
        # ``executed`` means "the device was driven", and the adapter judges whether what it
        # drove was a completed cast.  Reporting "not executed" for a loop that ran but ended
        # with the line gone would send the engine into a semantic retry of the whole servo
        # instead of the adapter's own ``recover``, which is the domain's designed answer.
        return StepExecution(
            executed=bool(frames > 0 or payload.get("presses")),
            reason=str(payload.get("outcome") or "SESSION_REALTIME"),
            latency_ms=(time.monotonic() - started) * 1000,
            backend="REALTIME",
            evidence=payload,
        )

    def _acknowledge_start_prompts(self, control: RealtimeControl) -> None:
        seen: set[str] = set()
        for _ in range(2):
            frame = self.capture()
            if control.start_signal is not None:
                state = control.detector(frame)
                if control.start_signal(state):
                    return  # already live: no blocking OCR sweep before taking control
            hits = [token for token in self.ocr(frame)
                    if token.get("text") in control.start_words and token.get("text") not in seen]
            if len(hits) != 1 or not self.lease_ok():
                return
            word = str(hits[0]["text"])
            seen.add(word)
            result = self._tap_printed(SessionStep(0, STEP_PRINTED_TAP, target=word), time.monotonic())
            if not result.executed:
                return
            self.sleep(self.binding.settle_seconds)

    def _wait_for_start(self, control: RealtimeControl) -> bool:
        """Poll the adapter's detector until it says the level is on screen.  OCR-free."""
        deadline = time.monotonic() + max(0.0, float(control.wait_for_line_s))
        while time.monotonic() < deadline:
            frame = self.capture()
            if frame is None:
                return False
            try:
                state = control.detector(frame)
                ready = bool(control.start_signal(state))
            except Exception:  # noqa: BLE001 - a detector that raises is not a "yes"
                ready = False
            if ready:
                return True
            self.sleep(0.02)
        return False

    def _drive(self, control: RealtimeControl, device: Any) -> Any:
        """Open one servo session and run it to its end condition.

        The end condition is the adapter's declared ``lost_ticks_to_end``: the target leaving
        the screen is how a level *finishes*, not how it fails, so the loop aborts with its
        own reason and the adapter's verifier reads ``frames``/``moves_sent`` off the report.
        """
        from .visual_servo import VisualServoSession  # local: keeps import cost off the hot path

        holder: dict[str, Any] = {"session": None}
        missing = {"ticks": 0}
        scenes = {"ticks": 0}
        trace, samples = [], []
        drive_started = time.monotonic()
        limit = max(1, int(control.lost_ticks_to_end or 0))

        def detector(frame: Any) -> Any:
            state = control.detector(frame)
            if getattr(state, 'meta', {}).get('gameplay') is False:
                scenes['ticks'] += 1
            else:
                scenes['ticks'] = 0
            if scenes['ticks'] >= 3 and holder['session'] is not None:
                holder['session'].abort('LEVEL_ENDED_SCENE_TRANSITION')
            if _target_visible(state):
                missing["ticks"] = 0
            else:
                missing["ticks"] += 1
                if limit and missing["ticks"] >= limit:
                    session = holder["session"]
                    if session is not None:
                        session.abort(f"TARGET_GONE_FOR_{missing['ticks']}_TICKS")
            return state

        def on_frame(row, frame, state):
            decision = getattr(control.controller, 'last', None)
            trace.append({**row.to_dict(),
                          'at':row.at,
                          **(state.to_dict() if hasattr(state,'to_dict') else {}),
                          'gameplay':getattr(state,'meta',{}).get('gameplay'),
                          'phase':getattr(decision,'phase',None),
                          'desired_line_x':getattr(decision,'desired_line_x',None)})
            if row.index % 20 == 0 and len(samples)<60:
                samples.append((row.index, frame.copy()))
        session = VisualServoSession(device, config=control.config, on_frame=on_frame)
        holder["session"] = session
        try:
            report = session.run(detector, control.controller,
                                 max_duration_s=float(control.max_seconds))
            vision = getattr(control.detector,'vision',None)
            performance = vision.summary() if vision is not None else {}
            summary = getattr(control.controller,'summary',None)
            if callable(summary):
                performance.update({k:v for k,v in summary().items() if k!='decision_trace'})
            moved = next((r for r in trace if r.get('moved')),None)
            first_valid = getattr(vision,'first_valid_at',None) or drive_started
            performance['first_effective_control_ms'] = ((moved['at']-first_valid)*1000 if moved else None)
            performance['fish_caught'] = performance['collision_count'] = performance['shield_used'] = None
            performance['touch_stuck'] = sum(bool(row.get('stuck')) for row in report.touch_sessions)
            performance['ocr_calls_in_control'] = report.policy.get('ocr_calls_inside_realtime')
            performance['model_calls_in_control'] = report.policy.get('qwen_calls')
            gameplay = [r for r in trace if r.get('gameplay') is not False]
            performance['control_coverage'] = sum(not r.get('lost') for r in gameplay)/max(1,len(gameplay))
            performance['idle_frame_ratio'] = sum(not r.get('moved') for r in gameplay)/max(1,len(gameplay))
            performance['active_steering_ratio'] = sum(bool(r.get('moved')) for r in gameplay)/max(1,len(gameplay))
            report.performance = performance
            try:
                folder = self.runtime.capture_dir / f'fishing_performance_{self.binding.index:03d}'
                folder.mkdir(parents=True,exist_ok=True)
                (folder/'timeline.json').write_text(json.dumps({'performance':performance,'frames':trace},
                    ensure_ascii=False,indent=1),encoding='utf-8')
                from PIL import Image
                for index, frame in samples:
                    Image.fromarray(frame).save(folder/f't{index:05d}.png')
            except Exception as exc:
                self.note('fishing_timeline_write_failed',reason=type(exc).__name__)
            return report
        except Exception as exc:  # noqa: BLE001
            # The servo releases the finger on every exit path it owns; what it cannot do is
            # return a report from a frame it failed to read, so the failure is shaped as one.
            return _ServoFailure(f"{type(exc).__name__}:{exc}")

    @staticmethod
    def _servo_payload(report: Any) -> dict[str, Any]:
        """The report as evidence, minus the per-frame timeline.

        The timeline is 20 dicts a second; pasting it into a step's evidence would put a
        minute of control-loop internals into every episode row.  The numbers that decide
        whether the loop controlled anything are kept, and the density is kept with them.
        """
        if report is None:
            return {"outcome": "SERVO_FAILED", "frames": 0, "moves_sent": 0}
        payload: dict[str, Any] = {}
        try:
            payload = dict(report.to_dict())
        except Exception:  # noqa: BLE001
            for name in ("outcome", "frames", "moves_sent", "presses", "duration_s",
                         "reason", "lost_events", "max_lost_streak", "stale_frames"):
                payload[name] = getattr(report, name, None)
        payload.pop("timeline", None)
        payload.pop("touch_sessions", None)
        if hasattr(report,'performance'):
            payload['performance'] = report.performance
        return payload

    # ---- STEP_PRINTED_TAP ----------------------------------------------------

    def _tap_printed(self, step: SessionStep, started: float) -> StepExecution:
        """Tap the control the client printed this word on, this frame.

        §24 in its most direct form: the point is produced by recognising the current frame
        and is discarded immediately after.  If the word appears more than once the host
        refuses -- two tokens carrying the same word are two different controls, and picking
        the higher-confidence one would be a guess about a coordinate, which is the one thing
        §24 says a tap may never rest on.
        """
        word = str(step.target or "").strip()
        self._before, self._before_path = self._world_for_step()
        self._after = None
        self._after_path = None

        def latency_ms() -> float:
            return (time.monotonic() - started) * 1000.0

        if not word:
            return StepExecution(executed=False, reason="SESSION_TAP_WITHOUT_WORD",
                                 latency_ms=latency_ms())
        service = self.runtime._ocr_service()
        if service is None:
            return StepExecution(executed=False, reason="SESSION_TAP_WITHOUT_OCR",
                                 latency_ms=latency_ms())
        path = self._fresh_path("session_printed")
        if self.runtime._device_lost(self.runtime.device.screenshot, path):
            self._device_lost_seen = True
            return StepExecution(executed=False, reason="DEVICE_LOST", latency_ms=latency_ms())
        anchor = str((step.params or {}).get('below_text') or '')
        point, why = self._locate_printed(path, word, service, below_text=anchor)
        if word == "普通关卡" and point is not None:
            import numpy as np
            from .fishing_vision import locate_normal_stage
            with Image.open(path) as image:
                semantic_point = locate_normal_stage(np.asarray(image.convert("RGB")))
            if semantic_point is not None:
                point = semantic_point
        if point is None:
            return StepExecution(executed=False, reason=why, latency_ms=latency_ms(),
                                 evidence={"word": word, "frame": str(path)})
        size = read_frame_size(path)
        if not size:
            return StepExecution(executed=False, reason="SESSION_TAP_NO_FRAME_SIZE",
                                 latency_ms=latency_ms())
        frame_w, frame_h = float(size[0]), float(size[1])
        device_w, device_h = self._device_size(frame_w, frame_h)
        x = int(round(point[0] / frame_w * device_w))
        y = int(round(point[1] / frame_h * device_h))
        try:
            target_device = self.device()
            if hasattr(target_device, "click"):
                target_device.click(x, y)
            else:
                target_device.tap(x, y)
        except Exception as exc:  # noqa: BLE001
            return StepExecution(executed=False,
                                 reason=f"SESSION_TAP_FAILED:{type(exc).__name__}",
                                 latency_ms=latency_ms())
        self.note("session_printed_tap", word=word, x=x, y=y, frame=str(path))
        self.sleep(self.binding.settle_seconds)
        return StepExecution(
            executed=True, reason=f"PRINTED_TAP:{word}", latency_ms=latency_ms(),
            tap_point=(x, y), backend="MAA" if hasattr(self.device(), "click") else "ADB",
            evidence={"word": word, "frame": str(path),
                      "center_norm": (point[0] / frame_w, point[1] / frame_h)},
        )

    def _locate_printed(self, path: Path, word: str,
                        service: Any, *, below_text: str = '') -> tuple[tuple[float, float] | None, str]:
        """``(pixel centre, "")`` or ``(None, reason)``.  Whole frame, so the centre is native."""
        try:
            result = service.recognize(path)
        except Exception as exc:  # noqa: BLE001
            return None, f"SESSION_TAP_OCR_FAILED:{type(exc).__name__}"
        wanted = _norm(word)
        hits = [token for token in (getattr(result, "tokens", ()) or ())
                if _norm(getattr(token, "text", "")) == wanted]
        if below_text:
            anchors = [token for token in result.tokens
                       if _norm(below_text) in _norm(getattr(token, 'text', ''))]
            if len(anchors) != 1:
                return None, 'SESSION_TAP_CONTEXT_ANCHOR_NOT_PROVEN'
            hits = [token for token in hits if token.centre[1] > anchors[0].centre[1]]
        if not hits:
            return None, f"SESSION_TAP_WORD_ABSENT:{word}"
        if len(hits) > 1:
            return None, f"SESSION_TAP_WORD_AMBIGUOUS:{word}x{len(hits)}"
        try:
            return tuple(hits[0].centre), ""  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            return None, f"SESSION_TAP_WORD_NO_POSITION:{word}"

    def _device_size(self, fallback_w: float, fallback_h: float) -> tuple[float, float]:
        """The device's own resolution, or the frame's when the device cannot say."""
        try:
            size = self.device().status().resolution
        except Exception:  # noqa: BLE001
            size = None
        if size and len(size) == 2 and float(size[0]) > 0 and float(size[1]) > 0:
            return float(size[0]), float(size[1])
        return fallback_w, fallback_h


@dataclass
class _ServoFailure:
    """A servo that raised, shaped like the report the caller reads.

    ``ServoReport.to_dict`` is what the evidence builder consumes, so a raised exception has
    to arrive in the same shape -- otherwise ``_servo_payload`` would need a second branch
    and the two would drift.
    """

    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": "SERVO_RAISED", "frames": 0, "moves_sent": 0, "presses": 0,
                "reason": self.reason, "lost_events": 0, "max_lost_streak": 0,
                "stale_frames": 0}


__all__ = ["LiveRuntimeSessionHost", "SessionRunBinding"]
