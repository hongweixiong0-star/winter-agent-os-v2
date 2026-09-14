"""MaaExecutorAdapter — MaaFramework as the UI-automation backend ("the hands").

Why this module exists (2026-09-14, operator directive "MAA 强制生产接入"):

Before this module every frame came from ``adb exec-out screencap -p`` and every
tap went out as ``adb shell input tap``.  Measured on this machine against MuMu
over ``127.0.0.1:7555``:

    adb exec-out screencap -p   ->  246.2 ms / frame (5 samples, new process each time)
    MaaFramework EmulatorExtras ->   12.1 ms / frame (5 samples, one controller)

That is a 20x difference on the single hottest call in the loop, and input goes
through MuMu's native channel instead of shelling out to ``input tap``.

Scope discipline — this is a **thin adapter inside the existing Executor
boundary**, not a second architecture:

* It does NOT own scheduling, world state, skills or goals.  Those stay in
  ``scheduler.py`` / ``models.py`` / ``skills.py`` / ``brain.py``.
* It deliberately mirrors ``ADBDevice``'s surface (``status`` / ``screenshot`` /
  ``tap`` / ``swipe`` / ``press_back`` / ``launch`` / ``resolve_connection``) so
  ``Executor`` and ``LiveRuntime`` can hold either backend without knowing which
  one they got.
* It exposes the recognition/action verb set the operator asked for
  (``recognize`` / ``click`` / ``swipe`` / ``wait_page`` / ``wait_disappear`` /
  ``ocr`` / ``match_template`` / ``run_task`` / ``recover``).

Honesty constraints baked in:

* ``available()`` is decided by an actual round trip (connect + screencap), never
  by "the package imports".  A dead backend must degrade to ADB, not pretend.
* Every verb records latency and outcome into ``stats()`` so an A/B claim can be
  backed by numbers instead of adjectives.
* OCR requires an onnx model bundle.  MaaFramework's pip package ships none, so
  ``ocr()`` reports ``OCR_MODEL_MISSING`` rather than returning an empty list
  that could be mistaken for "no text on screen".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

from .device import DeviceStatus

BACKEND = "MAA"
ANDROID_KEYCODE_BACK = 4

# MaaFramework resolves a template name to a file under ``image/``; the caller
# passes the bare name (no extension).  Verified 2026-09-14: passing
# "BTN_HERO_FIGHT.png" fails with "templates or threshold is empty" because MAA
# appends the extension itself.
DEFAULT_TEMPLATE_THRESHOLD = 0.7


def _is_maa_bundle(path: Path) -> bool:
    """True only for a directory MaaFramework can actually load as a bundle.

    ``post_bundle`` handed an ordinary template folder corrupts the resource
    state: every later ``post_recognition`` then fails instantly with
    "Tasker not inited" at ~0.8 ms, which reads like a matcher problem instead of
    a setup problem.  Verified the hard way on 2026-09-14.
    """
    try:
        return (path / "interface.json").is_file() or (path / "pipeline").is_dir()
    except OSError:
        return False


@dataclass(frozen=True)
class RecognitionOutcome:
    """One recognition attempt, with everything needed to audit it."""

    hit: bool
    semantic: str
    backend: str = BACKEND
    box: tuple[int, int, int, int] | None = None  # x, y, w, h in pixels
    score: float | None = None
    algorithm: str = ""
    latency_ms: float = 0.0
    error: str | None = None
    image_size: tuple[int, int] | None = None  # width, height of the searched frame

    def center(self) -> tuple[int, int] | None:
        if self.box is None:
            return None
        x, y, w, h = self.box
        return (x + w // 2, y + h // 2)

    def center_norm(self) -> tuple[float, float] | None:
        if self.box is None or not self.image_size:
            return None
        center = self.center()
        if center is None:
            return None
        width, height = self.image_size
        if width <= 0 or height <= 0:
            return None
        return (center[0] / width, center[1] / height)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hit": self.hit, "semantic": self.semantic, "backend": self.backend,
            "box": list(self.box) if self.box else None, "score": self.score,
            "algorithm": self.algorithm, "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "image_size": list(self.image_size) if self.image_size else None,
        }


@dataclass
class _VerbStats:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_ms: float = 0.0
    last_error: str | None = None

    def record(self, ok: bool, ms: float, error: str | None = None) -> None:
        self.attempts += 1
        self.successes += 1 if ok else 0
        self.failures += 0 if ok else 1
        self.total_ms += ms
        if error:
            self.last_error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts, "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.successes / self.attempts, 4) if self.attempts else None,
            "mean_ms": round(self.total_ms / self.attempts, 2) if self.attempts else None,
            "last_error": self.last_error,
        }


class MaaExecutorAdapter:
    """MaaFramework-backed device + recognition backend.

    Construction never raises: a machine without MaaFramework, or a MuMu that is
    not running, yields an adapter whose ``available()`` is ``False`` and whose
    ``unavailable_reason`` says why.  The router then keeps using ADB.
    """

    def __init__(
        self,
        *,
        adb_path: Path | str,
        serial: str,
        production: bool = False,
        template_dir: Path | str | None = None,
        ocr_model_dir: Path | str | None = None,
        log_dir: Path | str | None = None,
        save_draw: bool = True,
        status_package_ttl_s: float = 60.0,
        stdout_level: str = "error",
    ) -> None:
        self.adb_path = Path(adb_path)
        self.serial = serial
        self.production = production
        self.template_dir = Path(template_dir) if template_dir else None
        self.ocr_model_dir = Path(ocr_model_dir) if ocr_model_dir else None
        self.log_dir = Path(log_dir) if log_dir else None
        self.save_draw = save_draw
        self.status_package_ttl_s = status_package_ttl_s
        self.stdout_level = stdout_level

        self._controller: Any = None
        self._resource: Any = None
        self._tasker: Any = None
        self._ready = False
        self._unavailable_reason: str | None = None
        self._loaded_templates: set[str] = set()
        self._last_frame: np.ndarray | None = None
        self._last_frame_at: float = 0.0
        self._package: str | None = None
        self._package_at: float = 0.0
        self._stats: dict[str, _VerbStats] = {}
        self._draw_dir: Path | None = None

    # ------------------------------------------------------------------ stats
    def _stat(self, verb: str) -> _VerbStats:
        return self._stats.setdefault(verb, _VerbStats())

    def stats(self) -> dict[str, Any]:
        return {verb: value.to_dict() for verb, value in self._stats.items()}

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    @property
    def last_frame(self) -> np.ndarray | None:
        return self._last_frame

    @property
    def last_frame_age_s(self) -> float | None:
        if self._last_frame_at <= 0.0:
            return None
        return time.monotonic() - self._last_frame_at

    # ---------------------------------------------------------------- lifecycle
    def ensure_ready(self) -> tuple[bool, str]:
        """Import, connect and prove the backend with a real screencap.

        The screencap is the proof: a controller can report ``connected`` and
        still hand back black frames (wrong screencap method, drm surface).  An
        unproven backend must not be selected as a production path.
        """
        if self._ready:
            return True, ""
        try:
            from maa.controller import AdbController
            from maa.resource import Resource
            from maa.tasker import Tasker
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = f"MAA_IMPORT_FAILED:{type(exc).__name__}"
            return False, self._unavailable_reason

        try:
            controller = self._build_controller(AdbController)
            job = controller.post_connection().wait()
            if not job.succeeded:
                self._unavailable_reason = "MAA_CONNECT_FAILED"
                return False, self._unavailable_reason
            shot = controller.post_screencap().wait()
            if not shot.succeeded:
                self._unavailable_reason = "MAA_SCREENCAP_FAILED"
                return False, self._unavailable_reason
            frame = shot.get()
            if frame is None or getattr(frame, "size", 0) == 0:
                self._unavailable_reason = "MAA_SCREENCAP_EMPTY"
                return False, self._unavailable_reason
            if float(np.asarray(frame).mean()) < 3.0:
                # A black frame means the screencap channel is wrong; ADB is
                # then strictly better than a MAA backend that sees nothing.
                self._unavailable_reason = "MAA_SCREENCAP_BLACK"
                return False, self._unavailable_reason

            resource = Resource()
            # ``post_bundle`` must only be handed a real MaaFramework bundle
            # (``interface.json`` and/or ``pipeline/``).  Pointing it at an
            # ordinary template folder corrupts the resource state: every later
            # ``post_recognition`` then fails instantly with "Tasker not inited"
            # at ~0.8 ms, which reads like a matcher problem instead of a setup
            # problem.  Verified the hard way on 2026-09-14.
            if self.template_dir and _is_maa_bundle(self.template_dir):
                resource.post_bundle(str(self.template_dir)).wait()
            if self.ocr_model_dir and self.ocr_model_dir.is_dir():
                resource.post_ocr_model(str(self.ocr_model_dir)).wait()
            tasker = Tasker()
            if not tasker.bind(resource, controller):
                self._unavailable_reason = "MAA_BIND_FAILED"
                return False, self._unavailable_reason
            if getattr(tasker, "inited", True) is False:
                # ``bind`` can return True while the tasker is still unusable.
                # Without this check the first recognition fails at ~0.8 ms and
                # reads as "no match on screen", which sends the operator hunting
                # for a template bug instead of a setup bug.
                self._unavailable_reason = "MAA_TASKER_NOT_INITED"
                return False, self._unavailable_reason
            if self.log_dir is not None:
                try:
                    tasker.set_log_dir(str(self.log_dir))
                except Exception:  # noqa: BLE001
                    pass
            try:
                tasker.set_stdout_level(self._stdout_level())
            except Exception:  # noqa: BLE001
                pass
            try:
                tasker.set_save_draw(bool(self.save_draw))
            except Exception:  # noqa: BLE001
                pass

            self._controller, self._resource, self._tasker = controller, resource, tasker
            self._accept_frame(frame)
            self._ready = True
            self._unavailable_reason = None
            return True, ""
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = f"MAA_SETUP_FAILED:{type(exc).__name__}:{exc}"
            return False, self._unavailable_reason

    def _build_controller(self, controller_cls: Any) -> Any:
        """Prefer MuMu's native extras, fall back to a plain ADB controller.

        ``Toolkit.find_adb_devices`` reports the emulator's own screencap/input
        method bits and the ``extras.mumu`` block (instance path + index).  Those
        extras are what make screencap cost 12 ms instead of 246 ms, so they are
        requested first; the configured serial wins over the discovered address,
        because the discovered one (16384) is not always the attached instance.
        """
        screencap_methods = -1
        input_methods = -1
        config: dict[str, Any] | None = None
        try:
            from maa.toolkit import Toolkit
            devices = Toolkit.find_adb_devices(str(self.adb_path))
            if devices:
                device = devices[0]
                screencap_methods = int(getattr(device, "screencap_methods", -1))
                input_methods = int(getattr(device, "input_methods", -1))
                config = getattr(device, "config", None) or None
        except Exception:  # noqa: BLE001
            pass
        return controller_cls(
            adb_path=str(self.adb_path),
            address=self.serial,
            screencap_methods=screencap_methods,
            input_methods=input_methods,
            config=config,
        )

    def close(self) -> None:
        self._controller = None
        self._resource = None
        self._tasker = None
        self._ready = False

    def _stdout_level(self) -> Any:
        """Map a plain name to MaaFramework's logging enum (default: error)."""
        try:
            from maa.define import LoggingLevelEnum
            return getattr(LoggingLevelEnum, str(self.stdout_level).capitalize(),
                           LoggingLevelEnum.Error)
        except Exception:  # noqa: BLE001
            return 2

    def available(self) -> bool:
        return self.ensure_ready()[0]

    # ------------------------------------------------- ADBDevice-compatible view
    def resolve_connection(self) -> str:
        ok, reason = self.ensure_ready()
        if not ok:
            raise RuntimeError(reason)
        return self.serial

    def status(self) -> DeviceStatus:
        """Device status without paying two adb shell round trips per call.

        ``ADBDevice.status()`` shells out to ``wm size`` and ``dumpsys window``
        every time, and ``Executor`` calls it before every tap.  Here the
        resolution comes from a frame we actually captured, and the foreground
        package is cached for a bounded TTL — still real observations, just
        observed once instead of per call.
        """
        ok, reason = self.ensure_ready()
        if not ok:
            return DeviceStatus(False, self.serial, None, None)
        resolution = None
        if self._last_frame is not None:
            height, width = self._last_frame.shape[:2]
            resolution = (int(width), int(height))
        return DeviceStatus(True, self.serial, resolution, self._foreground_package())

    def _foreground_package(self) -> str | None:
        now = time.monotonic()
        if self._package is not None and (now - self._package_at) < self.status_package_ttl_s:
            return self._package
        package = None
        try:
            from .device import ADBDevice
            package = ADBDevice(self.adb_path, self.serial, production=False).status().foreground_package
        except Exception:  # noqa: BLE001
            package = None
        self._package, self._package_at = package, now
        return package

    # ------------------------------------------------------------------- frames
    def _accept_frame(self, frame: np.ndarray) -> np.ndarray:
        self._last_frame = frame
        self._last_frame_at = time.monotonic()
        return frame

    def frame(self, *, max_age_s: float = 1.5) -> np.ndarray | None:
        """Return a frame, reusing a recent one instead of re-capturing.

        The recognition path and the evidence path want the same pixels; taking
        two captures for one step used to cost an extra 246 ms and could even
        straddle an animation and describe two different screens.
        """
        age = self.last_frame_age_s
        if self._last_frame is not None and age is not None and age <= max_age_s:
            return self._last_frame
        return self.capture()

    def capture(self) -> np.ndarray | None:
        started = time.perf_counter()
        ok, reason = self.ensure_ready()
        if not ok:
            self._stat("screen").record(False, 0.0, reason)
            return None
        job = self._controller.post_screencap().wait()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not job.succeeded:
            self._stat("screen").record(False, elapsed_ms, "MAA_SCREENCAP_FAILED")
            return None
        frame = job.get()
        if frame is None:
            self._stat("screen").record(False, elapsed_ms, "MAA_SCREENCAP_EMPTY")
            return None
        self._stat("screen").record(True, elapsed_ms)
        return self._accept_frame(np.asarray(frame))

    def screenshot(self, destination: Path) -> Path:
        """Write the current frame to ``destination`` (atomic, validated).

        Kept signature-compatible with ``ADBDevice.screenshot`` because
        ``LiveRuntime`` uses it for every evidence frame.
        """
        frame = self.capture()
        if frame is None:
            raise RuntimeError(self._unavailable_reason or "MAA_SCREENCAP_FAILED")
        if frame.shape[0] < 16 or frame.shape[1] < 16:
            raise RuntimeError("SCREENSHOT_DAMAGED")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp.png")
        Image.fromarray(frame).save(temporary, format="PNG")
        temporary.replace(destination)
        return destination

    # -------------------------------------------------------------- recognition
    def _load_template(self, name: str, image: np.ndarray | Path | None = None) -> bool:
        """Register a template by name so pipeline nodes can reference it.

        ``override_image`` keeps the template in memory, so a live session never
        depends on a stale PNG on disk; the file-backed bundle stays as the
        debugger/repro path.
        """
        if name in self._loaded_templates:
            return True
        if image is None:
            if self.template_dir is None:
                return False
            for candidate in (self.template_dir / f"{name}.png", self.template_dir / name):
                if candidate.is_file():
                    image = candidate
                    break
            if image is None:
                return False
        try:
            array = (np.array(Image.open(image).convert("RGB")) if isinstance(image, (str, Path))
                     else np.asarray(image))
        except Exception:  # noqa: BLE001
            return False
        ok = bool(self._resource.override_image(name, array))
        if ok:
            self._loaded_templates.add(name)
        return ok

    @staticmethod
    def _coerce_box(value: Any) -> tuple[int, int, int, int] | None:
        """Read a box from any shape MaaFramework hands back (Rect/tuple/list)."""
        if value is None:
            return None
        if hasattr(value, "x") and hasattr(value, "w"):
            return (int(value.x), int(value.y), int(value.w), int(value.h))
        try:
            x, y, w, h = (int(v) for v in value)
            return (x, y, w, h)
        except (TypeError, ValueError):
            return None

    def _first_node(self, detail: Any) -> Any:
        nodes = getattr(detail, "nodes", None) or []
        return nodes[0] if nodes else None

    def _read_recognition(self, task_detail: Any) -> tuple[Any, Any]:
        node = self._first_node(task_detail)
        return node, (getattr(node, "recognition", None) if node is not None else None)

    def match_template(
        self,
        image: np.ndarray | None = None,
        template: str | Sequence[str] = (),
        *,
        semantic: str = "",
        roi: tuple[int, int, int, int] | None = None,
        threshold: float | Sequence[float] = DEFAULT_TEMPLATE_THRESHOLD,
        method: int = 5,
        green_mask: bool = False,
        images: dict[str, np.ndarray | Path] | None = None,
    ) -> RecognitionOutcome:
        """Template match through MaaFramework's own matcher.

        ``method=5`` is TM_CCOEFF_NORMED, the same algorithm the project's own
        A/B script measured as the winner over perceptual hashing on the battle
        button (1.000 vs 0.216/0.142).  Using MAA's implementation gets multi
        template, multi threshold and ROI without maintaining that code here.
        """
        names = [template] if isinstance(template, str) else list(template)
        label = semantic or (names[0] if names else "?")
        started = time.perf_counter()

        ok, reason = self.ensure_ready()
        if not ok:
            self._stat("match_template").record(False, 0.0, reason)
            return RecognitionOutcome(False, label, error=reason)
        frame = self.frame() if image is None else np.asarray(image)
        if frame is None:
            self._stat("match_template").record(False, 0.0, "NO_FRAME")
            return RecognitionOutcome(False, label, error="NO_FRAME")

        for name in names:
            if not self._load_template(name, (images or {}).get(name)):
                reason = f"TEMPLATE_NOT_REGISTERED:{name}"
                self._stat("match_template").record(False, (time.perf_counter() - started) * 1000.0, reason)
                return RecognitionOutcome(False, label, error=reason,
                                          image_size=(int(frame.shape[1]), int(frame.shape[0])))

        thresholds = [float(threshold)] if isinstance(threshold, (int, float)) else [float(t) for t in threshold]
        try:
            from maa.pipeline import JRecognitionType, JTemplateMatch
            param = JTemplateMatch(
                template=list(names),
                roi=tuple(roi) if roi else (0, 0, 0, 0),
                threshold=thresholds,
                method=int(method),
                green_mask=bool(green_mask),
            )
            job = self._tasker.post_recognition(JRecognitionType.TemplateMatch, param, frame)
            detail = job.wait().get()
            node, reco = self._read_recognition(detail)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if reco is None:
                # The task produced no recognition node at all, which means the
                # request was rejected rather than "the target is absent".
                # Reporting NO_MATCH here would send a debugger hunting for a
                # template problem that does not exist.
                self._stat("match_template").record(False, elapsed_ms, "MAA_NO_RECOGNITION_NODE")
                return RecognitionOutcome(False, label, error="MAA_NO_RECOGNITION_NODE",
                                          latency_ms=elapsed_ms,
                                          image_size=(int(frame.shape[1]), int(frame.shape[0])))
            hit = bool(getattr(reco, "hit", False))
            box = self._coerce_box(getattr(reco, "box", None)) if hit else None
            score = None
            best = getattr(reco, "best_result", None)
            if best is not None:
                score = float(getattr(best, "score", 0.0) or 0.0) or None
            if score is None:
                results = getattr(reco, "all_results", None) or []
                if results:
                    score = float(getattr(results[0], "score", 0.0) or 0.0) or None
            self._stat("match_template").record(hit, elapsed_ms, None if hit else "NO_MATCH")
            return RecognitionOutcome(
                hit, label, box=box, score=score, algorithm="TemplateMatch",
                latency_ms=elapsed_ms,
                image_size=(int(frame.shape[1]), int(frame.shape[0])),
                error=None if hit else "NO_MATCH",
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            reason = f"MAA_RECO_FAILED:{type(exc).__name__}"
            self._stat("match_template").record(False, elapsed_ms, reason)
            return RecognitionOutcome(False, label, error=reason, latency_ms=elapsed_ms)

    def find(
        self,
        image: np.ndarray | None,
        semantic: str,
        *,
        template: str | Sequence[str] | None = None,
        roi: tuple[int, int, int, int] | None = None,
        threshold: float | Sequence[float] = DEFAULT_TEMPLATE_THRESHOLD,
    ) -> RecognitionOutcome:
        """Semantic lookup: template name defaults to the semantic itself."""
        return self.match_template(
            image, template if template is not None else semantic,
            semantic=semantic, roi=roi, threshold=threshold,
        )

    # Alias kept because the operator's interface list names ``recognize()``.
    def recognize(self, image: np.ndarray | None = None, **kwargs: Any) -> RecognitionOutcome:
        return self.match_template(image, **kwargs)

    def ocr(
        self,
        image: np.ndarray | None = None,
        *,
        expected: Sequence[str] = (),
        roi: tuple[int, int, int, int] | None = None,
        threshold: float = 0.3,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Recognise text.  Returns ``(results, error)``.

        An empty list with ``error=None`` would be indistinguishable from "this
        screen has no text", so a missing model is reported explicitly instead.
        """
        ok, reason = self.ensure_ready()
        if not ok:
            return [], reason
        if getattr(self._resource, "loaded", False) is False and self.ocr_model_dir is None:
            return [], "OCR_MODEL_MISSING"
        frame = self.frame() if image is None else np.asarray(image)
        if frame is None:
            return [], "NO_FRAME"
        started = time.perf_counter()
        try:
            from maa.pipeline import JOCR, JRecognitionType
            param = JOCR(expected=list(expected), roi=tuple(roi) if roi else (0, 0, 0, 0),
                         threshold=float(threshold))
            job = self._tasker.post_recognition(JRecognitionType.OCR, param, frame)
            detail = job.wait().get()
            _node, reco = self._read_recognition(detail)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if reco is None:
                self._stat("ocr").record(False, elapsed_ms, "NO_DETAIL")
                return [], "NO_DETAIL"
            results = []
            for item in getattr(reco, "all_results", None) or []:
                text = getattr(item, "text", None)
                if text is None and isinstance(item, (list, tuple)) and len(item) >= 3:
                    text = item[2]
                results.append({
                    "text": text,
                    "box": list(self._coerce_box(getattr(item, "box", None)) or ()),
                    "score": round(float(getattr(item, "score", 0.0)), 4),
                })
            self._stat("ocr").record(True, elapsed_ms)
            return results, None
        except Exception as exc:  # noqa: BLE001
            reason = f"MAA_OCR_FAILED:{type(exc).__name__}"
            self._stat("ocr").record(False, (time.perf_counter() - started) * 1000.0, reason)
            return [], reason

    def wait_page(
        self,
        any_of: Sequence[str],
        *,
        timeout_s: float = 8.0,
        poll_interval_s: float = 0.25,
        threshold: float | Sequence[float] = DEFAULT_TEMPLATE_THRESHOLD,
        frame_fn: Callable[[], np.ndarray | None] | None = None,
    ) -> tuple[bool, str, RecognitionOutcome | None]:
        """Poll until one of ``any_of`` appears — the page-state wait MAA is good at.

        Returns ``(found, semantic_or_reason, outcome)``.  Never blocks longer
        than ``timeout_s``; a timeout is a normal, reportable outcome, not an
        exception, because the caller has a fallback backend.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        last: RecognitionOutcome | None = None
        while True:
            for semantic in any_of:
                frame = frame_fn() if frame_fn else self.capture()
                if frame is None:
                    continue
                outcome = self.find(frame, semantic, threshold=threshold)
                if outcome.hit:
                    return True, semantic, outcome
                last = outcome
            if time.monotonic() >= deadline:
                return False, "WAIT_PAGE_TIMEOUT", last
            time.sleep(max(0.02, poll_interval_s))

    def wait_disappear(
        self,
        semantic: str,
        *,
        template: str | Sequence[str] | None = None,
        roi: tuple[int, int, int, int] | None = None,
        timeout_s: float = 8.0,
        poll_interval_s: float = 0.25,
        threshold: float | Sequence[float] = DEFAULT_TEMPLATE_THRESHOLD,
        frame_fn: Callable[[], np.ndarray | None] | None = None,
    ) -> tuple[bool, str, RecognitionOutcome | None]:
        """Poll until ``semantic`` is no longer recognisable."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        last: RecognitionOutcome | None = None
        while True:
            frame = frame_fn() if frame_fn else self.capture()
            if frame is not None:
                last = self.find(frame, semantic, template=template, roi=roi, threshold=threshold)
                if not last.hit:
                    return True, semantic, last
            if time.monotonic() >= deadline:
                return False, "WAIT_DISAPPEAR_TIMEOUT", last
            time.sleep(max(0.02, poll_interval_s))

    # ----------------------------------------------------------------- actions
    def click(self, x: int, y: int) -> tuple[bool, str]:
        if not self.production:
            return False, "DRY_RUN_BLOCKED_DEVICE_ACTION"
        ok, reason = self.ensure_ready()
        if not ok:
            return False, reason
        started = time.perf_counter()
        try:
            job = self._controller.post_click(int(x), int(y)).wait()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._stat("click").record(job.succeeded, elapsed_ms,
                                       None if job.succeeded else "MAA_CLICK_FAILED")
            return bool(job.succeeded), "" if job.succeeded else "MAA_CLICK_FAILED"
        except Exception as exc:  # noqa: BLE001
            reason = f"MAA_CLICK_FAILED:{type(exc).__name__}"
            self._stat("click").record(False, (time.perf_counter() - started) * 1000.0, reason)
            return False, reason

    def tap(self, x: int, y: int) -> None:
        """Signature-compatible with ``ADBDevice.tap`` (raises on refusal)."""
        ok, reason = self.click(x, y)
        if not ok:
            raise PermissionError(reason) if reason == "DRY_RUN_BLOCKED_DEVICE_ACTION" else RuntimeError(reason)

    def click_semantic(
        self,
        image: np.ndarray | None,
        semantic: str,
        *,
        template: str | Sequence[str] | None = None,
        roi: tuple[int, int, int, int] | None = None,
        threshold: float | Sequence[float] = DEFAULT_TEMPLATE_THRESHOLD,
        allow_legacy: bool = False,
    ) -> tuple[bool, str, RecognitionOutcome | None]:
        """Recognise then click the recognised centre — never a hardcoded coordinate.

        This is the shape the operator demanded: if the button cannot be
        recognised, nothing is tapped and the caller falls back to ADB, instead
        of a blind coordinate tap that would land somewhere else on a drifted
        layout.
        """
        outcome = self.find(image, semantic, template=template, roi=roi, threshold=threshold)
        if not outcome.hit:
            self._stat("click_semantic").record(False, outcome.latency_ms, outcome.error or "NO_MATCH")
            return False, outcome.error or "NOT_RECOGNISED", outcome
        center = outcome.center()
        if center is None:
            self._stat("click_semantic").record(False, outcome.latency_ms, "BOX_UNREADABLE")
            return False, "BOX_UNREADABLE", outcome
        ok, reason = self.click(*center)
        self._stat("click_semantic").record(ok, outcome.latency_ms, reason or None)
        if ok:
            return True, "", outcome
        if allow_legacy and not self.production:
            return False, reason, outcome
        return False, reason, outcome

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        if not self.production:
            raise PermissionError("DRY_RUN_BLOCKED_DEVICE_ACTION")
        ok, reason = self.ensure_ready()
        if not ok:
            raise RuntimeError(reason)
        started = time.perf_counter()
        job = self._controller.post_swipe(int(x1), int(y1), int(x2), int(y2),
                                         max(50, int(duration_ms))).wait()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._stat("swipe").record(job.succeeded, elapsed_ms,
                                   None if job.succeeded else "MAA_SWIPE_FAILED")
        if not job.succeeded:
            raise RuntimeError("MAA_SWIPE_FAILED")

    def press_back(self) -> None:
        if not self.production:
            raise PermissionError("DRY_RUN_BLOCKED_DEVICE_ACTION")
        ok, reason = self.ensure_ready()
        if not ok:
            raise RuntimeError(reason)
        started = time.perf_counter()
        job = self._controller.post_press_key(ANDROID_KEYCODE_BACK).wait()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._stat("back").record(job.succeeded, elapsed_ms,
                                  None if job.succeeded else "MAA_BACK_FAILED")
        if not job.succeeded:
            raise RuntimeError("MAA_BACK_FAILED")

    def launch(self, package_name: str) -> None:
        ok, reason = self.ensure_ready()
        if not ok:
            raise RuntimeError(reason)
        job = self._controller.post_start_app(package_name).wait()
        self._stat("launch").record(job.succeeded, 0.0, None if job.succeeded else "MAA_LAUNCH_FAILED")
        if not job.succeeded:
            raise RuntimeError("MAA_LAUNCH_FAILED")

    # ------------------------------------------------------------- task / flow
    def run_task(
        self,
        entry: str,
        *,
        pipeline: dict[str, Any] | None = None,
        timeout_s: float = 30.0,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Run a MaaFramework pipeline entry with our node overrides merged in.

        Nodes are authored in ``knowledge/execution/maa_pipeline.json`` and merged
        per call, so several skills share one entry and differ only by parameters
        (``SELECT_RESOURCE(resource_type)`` rather than four near-identical
        scripts — see the operator's parameterisation rule).
        """
        ok, reason = self.ensure_ready()
        if not ok:
            return False, reason, {}
        if pipeline:
            if not self._resource.override_pipeline(pipeline):
                return False, "MAA_PIPELINE_REJECTED", {}
        started = time.perf_counter()
        try:
            job = self._tasker.post_task(entry, pipeline or None)
            detail = job.wait().get()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            status = str(getattr(getattr(detail, "status", None), "name", "")).lower()
            ok_run = "success" in status or "succeed" in status
            if not ok_run and detail is None:
                ok_run = False
            nodes = []
            for node in (getattr(detail, "nodes", None) or []):
                reco = getattr(node, "recognition", None)
                nodes.append({
                    "name": getattr(node, "name", ""),
                    "hit": bool(getattr(reco, "hit", False)) if reco is not None else None,
                    "box": list(self._coerce_box(getattr(reco, "box", None)) or ()) if reco is not None else None,
                    "completed": bool(getattr(node, "completed", False)),
                })
            self._stat("run_task").record(ok_run, elapsed_ms, None if ok_run else f"MAA_TASK_{status}")
            return ok_run, "" if ok_run else f"MAA_TASK_{status}", {
                "nodes": nodes, "latency_ms": round(elapsed_ms, 2),
            }
        except Exception as exc:  # noqa: BLE001
            reason = f"MAA_TASK_FAILED:{type(exc).__name__}"
            self._stat("run_task").record(False, (time.perf_counter() - started) * 1000.0, reason)
            return False, reason, {}

    def recover(self, *, max_back: int = 2, settle_s: float = 0.6) -> str:
        """Bounded, non-destructive recovery: reconnect if needed, then Back.

        Deliberately conservative: it never taps a game control it has not
        recognised, because a recovery that guesses can trigger a purchase
        surface.  Only ``BACK`` (navigation) and a controller reconnect.
        """
        if not self._ready:
            ok, reason = self.ensure_ready()
            if not ok:
                return reason
            return "MAA_RECONNECTED"
        if getattr(self._controller, "connected", True) is False:
            try:
                job = self._controller.post_connection().wait()
                if job.succeeded:
                    return "MAA_RECONNECTED"
            except Exception as exc:  # noqa: BLE001
                return f"MAA_RECONNECT_FAILED:{type(exc).__name__}"
        presses = 0
        for _ in range(max(0, int(max_back))):
            try:
                self.press_back()
                presses += 1
                time.sleep(max(0.0, settle_s))
            except Exception as exc:  # noqa: BLE001
                return f"MAA_BACK_FAILED:{type(exc).__name__}"
        return f"MAA_BACK_x{presses}"

    # -------------------------------------------------------------- diagnostics
    def save_annotated(
        self,
        image: np.ndarray,
        box: tuple[int, int, int, int] | None,
        destination: Path,
        *,
        label: str = "",
        color: tuple[int, int, int] = (255, 0, 0),
    ) -> Path:
        """Draw a recognised box onto the frame and save it.

        This exists because of a specific 2-hour loss: the battle-button template
        had been cropped 103 px too high, and a template re-matched against its
        own source frame always returns distance 0, so the wiring "proved"
        itself.  Only drawing the box on the frame exposed it.  Now every
        first-time node registration is meant to pass through here.
        """
        canvas = Image.fromarray(np.asarray(image)).convert("RGB")
        if box:
            from PIL import ImageDraw
            x, y, w, h = box
            ImageDraw.Draw(canvas).rectangle([x, y, x + w, y + h], outline=color, width=3)
            if label:
                ImageDraw.Draw(canvas).text((x, max(0, y - 14)), label, fill=color)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(destination, format="PNG")
        return destination
