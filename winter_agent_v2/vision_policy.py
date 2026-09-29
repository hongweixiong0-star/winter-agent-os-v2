"""Vision Policy V1 — the routing rules, and the counters that PROVE them.

Operator directive 2026-09-29.  This module is the single place where the vision
policy lives, so it cannot drift into being a document that nobody enforces.

Three things, in order of how much they matter:

1. **A hard gate.**  Section C/F forbid OCR and Qwen inside a realtime control
   loop.  That is enforced at the deepest possible choke point
   (``RapidOCRBackend.recognize``), not by convention: while a realtime session is
   open, ANY text-recognition call raises ``VisionPolicyViolation``.  A rule that
   can only be broken loudly is worth more than one that is merely written down.
2. **A routing decision** (sections D/E) as code: ``choose_path()`` returns
   FAST / SLOW / UNKNOWN from the situation, and ``Method`` is an ordered enum so
   the priority in section E cannot be expressed backwards.
3. **Counters** (section G): opencv_ms, ocr_ms, capture_ms, control_loop_ms, and
   per-fishing-session fps / vision_hz / control_hz / lost_target_frames.

Plus a thin localisation façade for section A.  It does NOT reimplement anything:
template matching goes to ``matchers.match_ccoeff``, pHash to ``image_hash.phash``,
and colour/contour/edge/geometry to OpenCV directly.  What it adds is a single
entry point that always returns a bbox measured on the frame it was given.

The one rule this module is built around:

    **A localisation is a measurement of ONE frame, never a coordinate to replay.**
    ``Localization.frame_token`` records which frame produced it and
    ``require_fresh()`` refuses a measurement taken on another frame, so
    "historical absolute coordinates" cannot quietly become a cross-frame rule.
"""

from __future__ import annotations

import pathlib
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Iterable, Sequence

#: ``Path`` below is the POLICY enum (FAST/SLOW/UNKNOWN path), so the filesystem one
#: is aliased.  Named explicitly rather than shadowed silently.
_FS = pathlib.Path

import numpy as np

# --------------------------------------------------------------------------- #
# Section E — priority, as an ORDERED quantity so it cannot be reversed in code
# --------------------------------------------------------------------------- #


class Method(IntEnum):
    """Cheapest/most reliable first.  Lower value == tried first, always."""

    OPENCV_DIRECT = 1
    STRUCTURAL = 2
    ROI_OCR = 3
    MULTI_FRAME = 4
    QWEN_FALLBACK = 5

    @property
    def needs_ocr(self) -> bool:
        """True only for methods that literally run text recognition.

        Deliberately an explicit set rather than ``self >= ROI_OCR``: MULTI_FRAME
        sits above ROI_OCR in the priority order but is cross-frame inference, not
        OCR, and an ordered comparison silently banned it from the FAST path — the
        kind of off-by-one that turns a policy into a bug.
        """
        return self in (Method.ROI_OCR, Method.QWEN_FALLBACK)

    @property
    def needs_model(self) -> bool:
        """True for methods that need a model at all (a realtime loop forbids these)."""
        return self is Method.QWEN_FALLBACK


class Path(str, Enum):
    """Section D — which pipeline a situation is allowed to use."""

    FAST = "FAST"          # OpenCV -> action
    SLOW = "SLOW"          # OpenCV + local ROI OCR + world state
    UNKNOWN = "UNKNOWN"    # Qwen permitted here only


class Locator(str, Enum):
    """Section A — the localisation methods, cheapest first."""

    TEMPLATE = "TEMPLATE"
    COLOR = "COLOR"
    CONTOUR = "CONTOUR"
    EDGE = "EDGE"
    GEOMETRY = "GEOMETRY"
    STRUCTURE = "STRUCTURE"
    PHASH = "PHASH"


#: Situations that may run on the FAST path (OpenCV only).  Anything not listed is
#: SLOW at best; an unrecognised SITUATION is UNKNOWN.
FAST_SITUATIONS = frozenset({
    "KNOWN_BUTTON", "KNOWN_PAGE", "RALLY", "MINIGAME", "REPEAT_NAVIGATION",
    "FORMATION_SLOT", "GATHER_TAB", "RED_DOT",
})
#: Situations that legitimately need numbers/text and therefore ROI OCR.
SLOW_SITUATIONS = frozenset({
    "TASK_DISCOVERY", "VALUE_READING", "RULE_READING", "COUNTDOWN", "UNKNOWN_PAGE",
    "EVENT_STATE", "REWARD_TIERS", "INVENTORY",
})


def choose_path(situation: str, *, target_known: bool = True,
                needs_text: bool = False) -> Path:
    """Section D/E routing.  Text need forces SLOW; target knowledge forces FAST."""
    if situation in FAST_SITUATIONS and not needs_text:
        return Path.FAST if target_known else Path.SLOW
    if situation in SLOW_SITUATIONS or needs_text:
        return Path.SLOW
    return Path.UNKNOWN


def methods_for(path: Path) -> tuple[Method, ...]:
    """Which methods a path may use, in priority order (never reversed)."""
    if path is Path.FAST:
        return (Method.OPENCV_DIRECT, Method.STRUCTURAL, Method.MULTI_FRAME)
    if path is Path.SLOW:
        return (Method.OPENCV_DIRECT, Method.STRUCTURAL, Method.ROI_OCR,
                Method.MULTI_FRAME)
    return tuple(Method)


# --------------------------------------------------------------------------- #
# Section C/F — the hard gate
# --------------------------------------------------------------------------- #


class VisionPolicyViolation(RuntimeError):
    """Raised when OCR/Qwen is called inside a realtime control session."""


_REALTIME = threading.local()


def realtime_active() -> str | None:
    """Name of the realtime session currently open, or None."""
    return getattr(_REALTIME, "name", None)


def guard_ocr(entry: str) -> None:
    """Called by every text-recognition entry point.  Raises inside realtime."""
    name = realtime_active()
    if name is None:
        return
    _REALTIME.violations = getattr(_REALTIME, "violations", 0) + 1
    if getattr(_REALTIME, "strict", True):
        raise VisionPolicyViolation(
            f"VISION_POLICY_V1 section C/F: {entry}() called inside the realtime "
            f"session '{name}'.  A realtime control loop may only use "
            f"MAA fast capture -> OpenCV -> lightweight policy -> MAA input.")
    counters = getattr(_REALTIME, "counters", None)
    if counters is not None:
        counters.ocr_calls_inside_realtime += 1


def realtime_counters() -> "VisionCounters | None":
    """Counters of the open realtime session, or None.  Used by OCR to bill itself."""
    return getattr(_REALTIME, "counters", None)


def guard_qwen(entry: str = "qwen") -> None:
    """Qwen is never allowed in a realtime loop (section C/F)."""
    name = realtime_active()
    if name is None:
        return
    _REALTIME.violations = getattr(_REALTIME, "violations", 0) + 1
    if getattr(_REALTIME, "strict", True):
        raise VisionPolicyViolation(
            f"VISION_POLICY_V1 section C: {entry}() called inside the realtime "
            f"session '{name}'.  Realtime loops are OpenCV only.")


@contextmanager
def realtime_session(name: str, *, counters: "VisionCounters | None" = None,
                     strict: bool = True, require_zero_ocr: bool = True):
    """Open a realtime control loop.  OCR/Qwen inside it is a hard error.

    On exit it checks section F's ``OCR_CALLS = 0`` and records the verdict on the
    counters, so a session that violated the rule is visible even if the violation
    was tolerated in non-strict mode.
    """
    if realtime_active() is not None:
        raise VisionPolicyViolation(
            f"a realtime session '{realtime_active()}' is already open; nesting is not "
            f"allowed because the inner session would hide the outer one's rules")
    _REALTIME.name = name
    _REALTIME.strict = strict
    _REALTIME.violations = 0
    _REALTIME.counters = counters
    if counters is not None:
        counters.ocr_calls_inside_realtime = 0
    started = time.perf_counter()
    try:
        yield counters
    finally:
        violations = getattr(_REALTIME, "violations", 0)
        _REALTIME.name = None
        _REALTIME.strict = True
        _REALTIME.counters = None
        if counters is not None:
            counters.realtime_sessions += 1
            counters.realtime_s += (time.perf_counter() - started)
            counters.policy_violations += violations
            counters.ocr_zero_inside_realtime = (violations == 0)
            if require_zero_ocr and violations:
                counters.realtime_clean = False


# --------------------------------------------------------------------------- #
# Section G — counters
# --------------------------------------------------------------------------- #


@dataclass
class VisionCounters:
    """Section G.  Everything is a total; the report converts to ms and Hz."""

    frames: int = 0
    capture_ms: float = 0.0
    opencv_ms: float = 0.0
    ocr_calls: int = 0
    ocr_ms: float = 0.0
    control_loop_ms: float = 0.0
    qwen_calls: int = 0
    lost_target_frames: int = 0
    #: sessions that ran inside the realtime gate
    realtime_sessions: int = 0
    realtime_s: float = 0.0
    ocr_calls_inside_realtime: int = 0
    ocr_zero_inside_realtime: bool = True
    realtime_clean: bool = True
    policy_violations: int = 0

    # ---- recording helpers (called by the loops, not by hand) ----
    def record_capture(self, ms: float) -> None:
        self.frames += 1
        self.capture_ms += ms

    def record_opencv(self, ms: float) -> None:
        self.opencv_ms += ms

    def record_ocr(self, ms: float) -> None:
        self.ocr_calls += 1
        self.ocr_ms += ms

    def record_loop(self, ms: float) -> None:
        self.control_loop_ms += ms

    def record_lost(self, n: int = 1) -> None:
        self.lost_target_frames += n

    def report(self) -> dict[str, Any]:
        fps = (self.frames / self.realtime_s) if self.realtime_s > 0 else None
        control_hz = (self.frames / (self.control_loop_ms / 1000.0)
                      if self.control_loop_ms > 0 else None)
        vision_hz = (self.frames / (self.opencv_ms / 1000.0)
                     if self.opencv_ms > 0 else None)
        return {
            "frames": self.frames,
            "capture_ms_mean": round(self.capture_ms / self.frames, 2) if self.frames else None,
            "opencv_ms_mean": round(self.opencv_ms / self.frames, 2) if self.frames else None,
            "ocr_calls": self.ocr_calls,
            "ocr_ms_mean": round(self.ocr_ms / self.ocr_calls, 2) if self.ocr_calls else None,
            "control_loop_ms_mean": round(self.control_loop_ms / self.frames, 2) if self.frames else None,
            "qwen_calls": self.qwen_calls,
            "lost_target_frames": self.lost_target_frames,
            "fps": round(fps, 2) if fps else None,
            "vision_hz": round(vision_hz, 2) if vision_hz else None,
            "control_hz": round(control_hz, 2) if control_hz else None,
            "realtime_sessions": self.realtime_sessions,
            "realtime_s": round(self.realtime_s, 3),
            "ocr_calls_inside_realtime": self.ocr_calls_inside_realtime,
            "ocr_zero_inside_realtime": self.ocr_zero_inside_realtime,
            "realtime_clean": self.realtime_clean,
            "policy_violations": self.policy_violations,
        }

    def assert_clean(self, *, where: str = "session") -> None:
        """Section F as an assertion: OCR_CALLS must be 0 inside a realtime loop."""
        rep = self.report()
        if rep["ocr_calls_inside_realtime"] or rep["qwen_calls"]:
            raise VisionPolicyViolation(
                f"{where}: realtime loop was not vision-pure "
                f"(ocr_inside={rep['ocr_calls_inside_realtime']}, qwen={rep['qwen_calls']})")


# --------------------------------------------------------------------------- #
# Section A — localisation façade.  One entry point, a bbox per frame.
# --------------------------------------------------------------------------- #


@dataclass
class Localization:
    """The result of measuring one frame.  Carries the frame it came from."""

    found: bool
    method: str
    bbox: tuple[int, int, int, int] | None = None      # x, y, w, h
    score: float = 0.0
    frame_token: str | None = None
    latency_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def centre(self) -> tuple[int, int] | None:
        if not self.bbox:
            return None
        x, y, w, h = self.bbox
        return (int(x + w / 2), int(y + h / 2))

    def to_dict(self) -> dict[str, Any]:
        return {"found": self.found, "method": self.method,
                "bbox": list(self.bbox) if self.bbox else None,
                "centre": list(self.centre) if self.centre else None,
                "score": round(self.score, 4), "frame_token": self.frame_token,
                "latency_ms": round(self.latency_ms, 2), **self.extra}


@dataclass
class TargetSpec:
    """What to look for.  Deliberately has NO absolute click coordinate field."""

    name: str
    locator: Locator
    #: Search window in native pixels (x, y, w, h).  A search window is not a
    #: click target: the answer is still measured on the frame.
    roi: tuple[int, int, int, int] | None = None
    template: str | _FS | None = None
    template_threshold: float = 0.7
    hsv_low: tuple[int, int, int] | None = None
    hsv_high: tuple[int, int, int] | None = None
    min_area: int = 60
    max_area: int | None = None
    aspect: tuple[float, float] | None = None
    #: STRUCTURE: split the ROI into N slots and return the one whose index matches
    slots: int | None = None
    slot_index: int | None = None
    slot_axis: str = "x"
    phash_hex: str | None = None
    phash_max_distance: int = 6


def require_fresh(loc: Localization, frame_token: str,
                  *, where: str = "localise") -> Localization:
    """Refuse a localisation measured on a different frame.

    This is section A's "no historical absolute coordinates as a cross-frame rule"
    made checkable: a stale measurement cannot be clicked.
    """
    if loc.frame_token != frame_token:
        raise VisionPolicyViolation(
            f"{where}: localisation for '{loc.method}' came from frame "
            f"'{loc.frame_token}' but the current frame is '{frame_token}'. "
            f"Re-measure on the current frame instead of replaying a coordinate.")
    return loc


def frame_token(frame: np.ndarray, index: int = 0) -> str:
    """Cheap identity for a frame, so a stale measurement is detectable."""
    if frame is None or frame.size == 0:
        return f"empty:{index}"
    step = max(1, frame.shape[0] // 24)
    sample = frame[::step, ::max(1, frame.shape[1] // 24)]
    return f"f{index}:{int(sample.sum())}"


def _crop(frame: np.ndarray, roi: tuple[int, int, int, int] | None):
    if roi is None:
        return frame, 0, 0
    x, y, w, h = roi
    return frame[max(0, y):y + h, max(0, x):x + w], max(0, x), max(0, y)


def localize(frame: np.ndarray, spec: TargetSpec, *, index: int = 0,
             counters: VisionCounters | None = None) -> Localization:
    """Measure ``spec`` on THIS frame and return its bbox.

    No OCR, ever (sections A/C): text on a target is not what identifies it — a
    template, a colour, a contour, an edge, geometry, structure or a pHash is.
    """
    started = time.perf_counter()
    token = frame_token(frame, index)
    loc = Localization(found=False, method=spec.locator.value, frame_token=token)
    if frame is None or frame.size == 0:
        return loc
    import cv2

    view, ox, oy = _crop(frame, spec.roi)
    if view.size == 0:
        return loc

    def done(bbox, score, **extra):
        loc.found = bbox is not None
        loc.bbox = bbox
        loc.score = score
        loc.extra.update(extra)
        loc.latency_ms = (time.perf_counter() - started) * 1000.0
        if counters is not None:
            counters.record_opencv(loc.latency_ms)
        return loc

    if spec.locator is Locator.TEMPLATE:
        tpl_path = ROOT_TEMPLATES / spec.template if spec.template else None
        if tpl_path is None or not _FS(tpl_path).exists():
            return done(None, 0.0, error="TEMPLATE_MISSING")
        tpl = cv2.cvtColor(np.asarray(_pil(tpl_path)), cv2.COLOR_RGB2BGR)
        bgr = cv2.cvtColor(view, cv2.COLOR_RGB2BGR)
        if tpl.shape[0] > bgr.shape[0] or tpl.shape[1] > bgr.shape[1]:
            return done(None, 0.0, error="TEMPLATE_LARGER_THAN_ROI")
        res = cv2.matchTemplate(bgr, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc_xy = cv2.minMaxLoc(res)
        if score < spec.template_threshold:
            return done(None, float(score), error="BELOW_THRESHOLD")
        return done((int(loc_xy[0] + ox), int(loc_xy[1] + oy),
                     int(tpl.shape[1]), int(tpl.shape[0])), float(score))

    if spec.locator in (Locator.COLOR, Locator.CONTOUR, Locator.EDGE, Locator.GEOMETRY):
        hsv = cv2.cvtColor(view, cv2.COLOR_RGB2HSV)
        if spec.locator is Locator.EDGE:
            edges = cv2.Canny(cv2.cvtColor(view, cv2.COLOR_RGB2GRAY), 60, 160)
            mask = cv2.dilate(edges, np.ones((3, 3), np.uint8))
        elif spec.hsv_low and spec.hsv_high:
            mask = cv2.inRange(hsv, tuple(spec.hsv_low), tuple(spec.hsv_high))
        else:
            # CONTOUR/GEOMETRY without a colour: salient = far from the ROI median
            med = np.median(view.reshape(-1, 3), axis=0)
            dist = np.linalg.norm(view.astype(np.float32) - med, axis=2)
            mask = (dist > max(45.0, float(np.percentile(dist, 92)))).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            area = cv2.contourArea(c)
            if area < spec.min_area or (spec.max_area and area > spec.max_area):
                continue
            x, y, w, h = cv2.boundingRect(c)
            if spec.aspect:
                ratio = w / max(1, h)
                if not (spec.aspect[0] <= ratio <= spec.aspect[1]):
                    continue
            if best is None or area > best[0]:
                best = (area, x, y, w, h)
        if best is None:
            return done(None, 0.0, error="NO_BLOB")
        return done((int(best[1] + ox), int(best[2] + oy), int(best[3]), int(best[4])),
                    float(best[0]))

    if spec.locator is Locator.STRUCTURE:
        if not spec.slots:
            return done(None, 0.0, error="SLOTS_UNSET")
        h, w = view.shape[:2]
        idx = spec.slot_index if spec.slot_index is not None else 0
        if spec.slot_axis == "x":
            sw = w / spec.slots
            bbox = (int(idx * sw + ox), int(oy), int(sw), int(h))
        else:
            sh = h / spec.slots
            bbox = (int(ox), int(idx * sh + oy), int(w), int(sh))
        return done(bbox, 1.0, slot_index=idx)

    if spec.locator is Locator.PHASH:
        from .image_hash import hamming, phash
        if not spec.phash_hex:
            return done(None, 0.0, error="PHASH_UNSET")
        got = phash(_pil_array(view))
        dist = hamming(got, spec.phash_hex)
        if dist > spec.phash_max_distance:
            return done(None, float(dist), error="PHASH_TOO_FAR")
        return done((int(ox), int(oy), int(view.shape[1]), int(view.shape[0])),
                    1.0 - dist / 64.0, phash_distance=dist)

    return done(None, 0.0, error="UNSUPPORTED_LOCATOR")


ROOT_TEMPLATES = _FS(__file__).resolve().parents[1] / "dataset" / "candidate" / "templates"


def _pil(path):
    from PIL import Image
    return Image.open(_FS(path)).convert("RGB")


def _pil_array(arr: np.ndarray):
    from PIL import Image
    return Image.fromarray(arr).convert("RGB")


def first_found(localisations: Iterable[Localization]) -> Localization | None:
    """Section E in one line: return the first hit in priority order, no reordering."""
    for loc in localisations:
        if loc.found:
            return loc
    return None


def localize_by_priority(frame: np.ndarray, specs: Sequence[TargetSpec], *,
                         index: int = 0, counters: VisionCounters | None = None
                         ) -> Localization:
    """Try specs in the order given — the CALLER must pass them priority-ordered.

    Kept separate from ``localize`` so the priority rule is visible at the call
    site rather than hidden inside a heuristic.
    """
    last: Localization | None = None
    for spec in specs:
        last = localize(frame, spec, index=index, counters=counters)
        if last.found:
            return last
    return last or Localization(found=False, method="NONE")
