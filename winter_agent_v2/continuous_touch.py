"""ContinuousTouchSession — one held finger, always released.

Why this exists (2026-09-29, "V2 Continuous Visual Control"):

``click`` and ``swipe`` are fire-and-forget: down+up in one controller call.  A
game that must be *steered* — the fishing tournament's hook, for instance — needs
the finger to stay down across many frames while the client keeps rendering.  The
installed MaaFramework already exposes that (``post_touch_down`` /
``post_touch_move`` / ``post_touch_up``, probed in PHASE 1), but a raw triple of
calls is a liability: one exception between down and up leaves the finger pressed
on the device, and every later action in the whole system then lands on a
different screen.

So the invariant of this module is deliberately narrow and absolute:

    **A session that is not IDLE/RELEASED/ABORTED has a finger down, and every
    exit path — normal, exception, context-manager, interpreter teardown, or the
    watchdog calling ``release_all`` — lifts it.**

Nothing here schedules, decides, or knows about fishing.  It is a resource with
a close(), in the same spirit as ``DeviceLease``.
"""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

#: How many times ``_lift`` re-tries a failing touch_up before giving up.  Not
#: unbounded: a controller that cannot lift after this many tries is broken, and
#: retrying forever would block the watchdog that is asking for the release.
LIFT_ATTEMPTS = 3


class TouchState(str, Enum):
    IDLE = "IDLE"
    PRESSED = "PRESSED"
    MOVING = "MOVING"
    RELEASED = "RELEASED"
    ABORTED = "ABORTED"


#: States that mean "a finger is physically down on the device".
_HELD = (TouchState.PRESSED, TouchState.MOVING)


@dataclass
class TouchEvent:
    kind: str                       # down | move | up | abort | refuse
    x: int | None
    y: int | None
    ok: bool
    reason: str
    ms: float
    state_after: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "x": self.x, "y": self.y, "ok": self.ok,
                "reason": self.reason or None, "ms": round(self.ms, 2),
                "state_after": self.state_after}


@dataclass
class TouchSessionReport:
    """Everything an episode needs to prove what the finger did."""

    session_id: str
    contact: int
    opened_at: float
    closed_at: float | None = None
    state: str = TouchState.IDLE.value
    begin_xy: tuple[int, int] | None = None
    end_xy: tuple[int, int] | None = None
    moves: int = 0
    failed_moves: int = 0
    distance_px: float = 0.0
    lift_attempts: int = 0
    stuck: bool = False
    reason: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return (self.closed_at or time.monotonic()) - self.opened_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "contact": self.contact,
            "duration_s": round(self.duration_s, 3),
            "state": self.state,
            "begin_xy": list(self.begin_xy) if self.begin_xy else None,
            "end_xy": list(self.end_xy) if self.end_xy else None,
            "moves": self.moves, "failed_moves": self.failed_moves,
            "distance_px": round(self.distance_px, 1),
            "lift_attempts": self.lift_attempts,
            "stuck": self.stuck, "reason": self.reason,
            "mean_move_ms": (round(sum(e["ms"] for e in self.events
                                       if e["kind"] == "move") / self.moves, 2)
                             if self.moves else None),
            "events": self.events[-60:],
        }


# ---------------------------------------------------------------- module audit
_ACTIVE: "weakref.WeakSet[ContinuousTouchSession]" = weakref.WeakSet()
_LOCK = threading.Lock()
_SESSION_SEQ = 0


def active_sessions() -> list["ContinuousTouchSession"]:
    """Every session currently holding (or believed to hold) a finger."""
    with _LOCK:
        return [s for s in _ACTIVE if s.holds_finger]


def release_all(reason: str = "WATCHDOG_RELEASE_ALL") -> list[dict[str, Any]]:
    """Emergency lift for every live session.

    Called by the watchdog / runtime recovery path.  Idempotent and never raises,
    because the situation it exists for is precisely "something else is already
    broken".
    """
    out = []
    for session in active_sessions():
        try:
            out.append({"session_id": session.session_id,
                        "lifted": session.abort(reason)})
        except Exception as exc:  # noqa: BLE001
            out.append({"session_id": session.session_id, "lifted": False,
                        "error": f"{type(exc).__name__}:{exc}"})
    return out


class TouchStuckError(RuntimeError):
    """Raised when the controller accepted a down we could not lift."""


class ContinuousTouchSession:
    """A held finger with a guaranteed release.

    Usage::

        with ContinuousTouchSession(device) as touch:
            touch.begin(360, 900)
            while running:
                touch.move(nx, ny)

    ``__exit__`` lifts the finger on both the success and the exception path; the
    explicit ``abort()`` is for callers that must keep going after a failure.
    """

    def __init__(self, device: Any, *, contact: int = 0,
                 on_event: Callable[[TouchEvent], None] | None = None,
                 session_id: str | None = None) -> None:
        global _SESSION_SEQ
        self.device = device
        self.contact = int(contact)
        self._on_event = on_event
        self._state = TouchState.IDLE
        #: The PHYSICAL truth, tracked separately from the lifecycle state: True
        #: from the moment a down is accepted until an up is confirmed.  A
        #: lifecycle state of ABORTED must not be allowed to claim the finger is
        #: up when the lift actually failed — that is the exact dishonesty this
        #: module exists to prevent.
        self._finger_down = False
        self._begin_xy: tuple[int, int] | None = None
        self._last_xy: tuple[int, int] | None = None
        self._opened_at = time.monotonic()
        self._closed_at: float | None = None
        self._events: list[TouchEvent] = []
        self._moves = 0
        self._failed_moves = 0
        self._distance = 0.0
        self._lift_attempts = 0
        self._reason = ""
        with _LOCK:
            _SESSION_SEQ += 1
            seq = _SESSION_SEQ
        self.session_id = session_id or f"TOUCH{seq:05d}"
        with _LOCK:
            _ACTIVE.add(self)

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> TouchState:
        return self._state

    @property
    def holds_finger(self) -> bool:
        """True while the device still has a finger down — the physical fact."""
        return self._finger_down

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (f"<ContinuousTouchSession {self.session_id} {self._state.value} "
                f"moves={self._moves} last={self._last_xy}>")

    # --------------------------------------------------------------- lifecycle
    def begin(self, x: int, y: int, *, pressure: int = 1) -> bool:
        """Press down at (x, y).  Returns False (state unchanged) if refused."""
        if self._state is not TouchState.IDLE:
            return self._refuse("begin", x, y, f"BEGIN_IN_STATE_{self._state.value}")
        ok, reason, ms = self._call("down", x, y, pressure)
        self._begin_xy = (int(x), int(y))
        self._last_xy = self._begin_xy
        self._state = TouchState.PRESSED if ok else TouchState.IDLE
        self._finger_down = bool(ok)
        if not ok:
            self._reject("down", x, y, reason, ms)
        return ok

    def move(self, x: int, y: int, *, pressure: int = 1) -> bool:
        """Drag to (x, y).  Refused (and reported) when nothing is held."""
        if not self.holds_finger:
            return self._refuse("move", x, y, f"MOVE_IN_STATE_{self._state.value}")
        ok, reason, ms = self._call("move", x, y, pressure)
        if ok:
            if self._last_xy is not None:
                self._distance += ((x - self._last_xy[0]) ** 2
                                   + (y - self._last_xy[1]) ** 2) ** 0.5
            self._last_xy = (int(x), int(y))
            self._moves += 1
            self._state = TouchState.MOVING
        else:
            self._failed_moves += 1
            self._reject("move", x, y, reason, ms)
        return ok

    def end(self, *, reason: str = "END") -> bool:
        """Lift the finger normally.  Returns True only if the lift CONFIRMED."""
        if self._state is TouchState.RELEASED:
            return not self._finger_down
        if not self.holds_finger:
            self._refuse("up", None, None, f"END_IN_STATE_{self._state.value}")
            return True
        ok = self._lift()
        self._reason = reason
        self._state = TouchState.RELEASED
        self._closed_at = time.monotonic()
        return ok

    def abort(self, reason: str = "ABORT") -> bool:
        """Lift the finger because something went wrong.  Never raises.

        Returns True only when the release was confirmed; ``report().stuck``
        stays True when it was not, so a failed abort is visible instead of
        looking like a clean shutdown.
        """
        if self._state in (TouchState.RELEASED, TouchState.ABORTED, TouchState.IDLE):
            self._reason = self._reason or reason
            return not self._finger_down
        ok = self._lift()
        self._reason = reason
        self._state = TouchState.ABORTED
        self._closed_at = time.monotonic()
        self._emit(TouchEvent("abort", None, None, ok, reason,
                              (self._closed_at - self._opened_at) * 1000.0,
                              self._state.value))
        return ok

    # ------------------------------------------------------- guaranteed release
    def _lift(self) -> bool:
        """touch_up with bounded retries; clears ``_finger_down`` only on success."""
        last_reason = ""
        for attempt in range(1, LIFT_ATTEMPTS + 1):
            self._lift_attempts = attempt
            ok, reason, ms = self._call("up", None, None, 1)
            if ok:
                self._finger_down = False
                return True
            last_reason = reason
            time.sleep(0.05 * attempt)
        # Could not lift: say so loudly rather than reporting a clean release.
        self._reject("up", None, None, f"LIFT_FAILED:{last_reason}", 0.0)
        return False

    def __enter__(self) -> "ContinuousTouchSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.holds_finger:
            if exc_type is not None:
                self.abort(f"EXCEPTION_{exc_type.__name__}")
            else:
                self.end(reason="CONTEXT_EXIT")
        if self._closed_at is None:
            self._closed_at = time.monotonic()
        return False  # never swallow the caller's exception

    def __del__(self) -> None:  # pragma: no cover - interpreter teardown
        # Best effort only: at shutdown the controller may already be gone, and
        # an exception here would be printed as "Exception ignored in __del__".
        try:
            if self.holds_finger:
                self.abort("GC_FINALIZER")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ report
    def report(self) -> TouchSessionReport:
        return TouchSessionReport(
            session_id=self.session_id, contact=self.contact,
            opened_at=self._opened_at, closed_at=self._closed_at,
            state=self._state.value, begin_xy=self._begin_xy,
            end_xy=self._last_xy, moves=self._moves,
            failed_moves=self._failed_moves, distance_px=self._distance,
            lift_attempts=self._lift_attempts,
            stuck=self.holds_finger, reason=self._reason,
            events=[e.to_dict() for e in self._events])

    # ------------------------------------------------------------------ plumbing
    def _call(self, verb: str, x: int | None, y: int | None,
              pressure: int) -> tuple[bool, str, float]:
        started = time.perf_counter()
        try:
            fn = getattr(self.device, f"touch_{verb}")
            if verb == "up":
                ok, reason = fn(self.contact)
            else:
                ok, reason = fn(int(x), int(y), self.contact, int(pressure))
        except Exception as exc:  # noqa: BLE001
            ok, reason = False, f"TOUCH_{verb.upper()}_RAISED:{type(exc).__name__}"
        ms = (time.perf_counter() - started) * 1000.0
        if ok:
            self._emit(TouchEvent(verb, x, y, True, "", ms, self._state.value))
        return bool(ok), reason or "", ms

    def _reject(self, kind: str, x: int | None, y: int | None,
                reason: str, ms: float) -> None:
        self._emit(TouchEvent(kind, x, y, False, reason, ms, self._state.value))

    def _refuse(self, kind: str, x: int | None, y: int | None, reason: str) -> bool:
        self._emit(TouchEvent("refuse", x, y, False, reason, 0.0, self._state.value))
        return False

    def _emit(self, event: TouchEvent) -> None:
        if len(self._events) < 4000:
            self._events.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001
                pass


def mean_move_ms(reports: Iterable[TouchSessionReport]) -> float | None:
    values = [e["ms"] for r in reports for e in r.events if e["kind"] == "move"]
    return round(sum(values) / len(values), 2) if values else None
