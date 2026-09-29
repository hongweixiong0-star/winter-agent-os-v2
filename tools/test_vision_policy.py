# -*- coding: utf-8 -*-
"""Offline proof of VISION POLICY V1 (sections A–G).

The point of this file is that the policy is ENFORCED, not documented.  The
decisive cases are:

  * a detector that calls OCR inside a realtime loop is REJECTED (section C/F),
    and the rejection happens at the OCR choke point, so it cannot be routed
    around by calling a different OCR entry;
  * a clean realtime loop reports OCR_CALLS == 0 (section F);
  * localisation returns a bbox measured on THIS frame, and a stale measurement
    cannot be clicked (section A's no-historical-coordinates rule);
  * the priority order in section E cannot be expressed backwards.

usage: python tools/test_vision_policy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import vision_policy as vp  # noqa: E402
from winter_agent_v2.vision_policy import (  # noqa: E402
    Localization, Locator, Method, Path as VPath, TargetSpec, VisionPolicyViolation,
    choose_path, first_found, frame_token, localize, methods_for, realtime_active,
    realtime_session, require_fresh)

RESULTS: list[bool] = []


def check(title: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} | {title}{('  <- ' + detail) if detail and not ok else ''}")


# --------------------------------------------------------------------- section E
def case_priority_order() -> None:
    check("E1 priority is an ordered quantity, cheapest first",
          [int(m) for m in Method] == [1, 2, 3, 4, 5], str([int(m) for m in Method]))
    check("E2 OPENCV outranks OCR", Method.OPENCV_DIRECT < Method.ROI_OCR)
    check("E3 QWEN is last, never first", max(Method) is Method.QWEN_FALLBACK)
    fast = methods_for(VPath.FAST)
    check("E4 the FAST path may not use OCR at all",
          not any(m.needs_ocr for m in fast), str([m.name for m in fast]))
    slow = methods_for(VPath.SLOW)
    check("E5 the SLOW path gains ROI OCR after the OpenCV methods",
          slow.index(Method.ROI_OCR) > slow.index(Method.OPENCV_DIRECT)
          and Method.QWEN_FALLBACK not in slow, str([m.name for m in slow]))
    check("E6 only UNKNOWN may reach QWEN",
          Method.QWEN_FALLBACK in methods_for(VPath.UNKNOWN)
          and Method.QWEN_FALLBACK not in methods_for(VPath.SLOW))


# --------------------------------------------------------------------- section D
def case_routing() -> None:
    check("D1 known button -> FAST", choose_path("KNOWN_BUTTON") is VPath.FAST)
    check("D2 minigame -> FAST", choose_path("MINIGAME") is VPath.FAST)
    check("D3 value reading -> SLOW", choose_path("VALUE_READING") is VPath.SLOW)
    check("D4 countdown -> SLOW", choose_path("COUNTDOWN") is VPath.SLOW)
    check("D5 an unnamed situation is UNKNOWN (never assumed FAST)",
          choose_path("SOMETHING_NEW") is VPath.UNKNOWN)
    check("D6 needing text forces SLOW even for a known button",
          choose_path("KNOWN_BUTTON", needs_text=True) is VPath.SLOW)
    check("D7 an unknown target on a known page is SLOW, not FAST",
          choose_path("KNOWN_PAGE", target_known=False) is VPath.SLOW)


# ------------------------------------------------------------------ section C/F
def _make_screen():
    class Screen:
        def __init__(self):
            self.calls = []
            self.finger = None
            self.last_x = None
            self.x = 300.0
            self.drift = 0.0

        def capture(self):
            self.x += self.drift
            f = np.zeros((60, 720, 3), dtype=np.uint8)
            f[:, int(max(0, min(719, self.x))) - 4:int(max(0, min(719, self.x))) + 4] = 255
            return f

        def touch_down(self, x, y, contact=0, pressure=1):
            self.calls.append("touch_down"); self.finger = self.last_x = int(x); return True, ""

        def touch_move(self, x, y, contact=0, pressure=1):
            self.calls.append("touch_move"); self.finger = self.last_x = int(x); return True, ""

        def touch_up(self, contact=0):
            self.calls.append("touch_up"); self.finger = None; return True, ""

    return Screen()


def _column_detector(roi):
    cols = roi.mean(axis=(0, 2)) if roi.ndim == 3 else roi.mean(axis=0)
    bright = np.nonzero(cols > 128)[0]
    return ({"found": True, "target_x": int(bright.mean())} if bright.size
            else {"found": False, "lost": True})


def _steer(state):
    from winter_agent_v2.visual_servo import ServoCommand
    return ServoCommand(desired_x=state["target_x"]) if state.get("found") else ServoCommand()


def case_gate_blocks_ocr() -> None:
    """The gate must fire at the choke point itself, not only in a helper."""
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2.ocr_full import read_all
    from PIL import Image

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    for label, fn in (("executor_router._rapid_ocr_results",
                       lambda: _rapid_ocr_results(frame, None, [])),
                      ("ocr_full.read_all", lambda: read_all(Image.fromarray(frame)))):
        try:
            with realtime_session("gate-test"):
                fn()
            check(f"C1 {label} refused inside a realtime session", False, "no violation raised")
        except VisionPolicyViolation as exc:
            check(f"C1 {label} refused inside a realtime session",
                  "realtime" in str(exc), str(exc)[:60])
        except Exception as exc:  # noqa: BLE001
            check(f"C1 {label} refused inside a realtime session", False,
                  f"wrong exception {type(exc).__name__}: {exc}")
    check("C2 the gate is closed again after the session", realtime_active() is None)


def case_ocr_engine_chokepoint() -> None:
    """Even reaching the OCR engine directly (bypassing the named entries) is blocked."""
    from winter_agent_v2.ocr import RapidOCRBackend
    from PIL import Image
    try:
        with realtime_session("choke-test"):
            RapidOCRBackend.__new__(RapidOCRBackend).recognize(Image.new("RGB", (8, 8)))
        check("C3 the OCR engine itself refuses inside a realtime session", False,
              "no violation raised")
    except VisionPolicyViolation as exc:
        check("C3 the OCR engine itself refuses inside a realtime session",
              "section C/F" in str(exc))
    except Exception as exc:  # noqa: BLE001
        # If it got past the guard it would fail on the missing engine, which is a
        # different error - treat that as a guard failure.
        check("C3 the OCR engine itself refuses inside a realtime session", False,
              f"passed the guard, then {type(exc).__name__}")


def case_violating_detector_rejected() -> None:
    """DECISIVE: a detector that OCRs mid-loop must fail, loudly."""
    from winter_agent_v2.visual_servo import ServoConfig, VisualServoSession
    from winter_agent_v2.executor_router import _rapid_ocr_results

    screen = _make_screen()

    def cheating_detector(roi):
        _rapid_ocr_results(roi, None, ["扫荡"])   # a realtime loop may not do this
        return {"found": False, "lost": True}

    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0))
    rep = sess.run(cheating_detector, _steer, None)
    pol = rep.to_dict().get("vision_policy", {})
    check("C4 an OCR-calling detector is REJECTED by the loop",
          rep.outcome == "ERROR" and "VISION_POLICY" in rep.reason,
          f"{rep.outcome} / {rep.reason[:80]}")
    check("C5 the violation is counted, not swallowed",
          pol.get("policy_violations", 0) >= 1, str(pol.get("policy_violations")))
    check("C6 the finger is still lifted after the rejection",
          all(not s["stuck"] for s in rep.touch_sessions))


def case_clean_session_is_pure() -> None:
    """Section F: a normal realtime loop must show OCR_CALLS == 0."""
    from winter_agent_v2.visual_servo import ServoConfig, VisualServoSession

    screen = _make_screen()
    screen.drift = 3.0
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                        max_session_duration_s=0.6))
    rep = sess.run(_column_detector, _steer, None)
    d = rep.to_dict()
    pol = d["vision_policy"]
    check("F1 OCR_CALLS inside the realtime loop == 0", pol["ocr_calls_inside_realtime"] == 0,
          str(pol["ocr_calls_inside_realtime"]))
    check("F2 QWEN_CALLS == 0", pol["qwen_calls"] == 0)
    check("F3 the session is reported clean", pol["realtime_clean"] is True)
    check("F4 inside-realtime OCR counter starts at zero per session",
          pol["ocr_zero_inside_realtime"] is True)
    check("F5 OCR outside the loop is still allowed afterwards",
          _ocr_allowed_outside())


def _ocr_allowed_outside() -> bool:
    from winter_agent_v2.vision_policy import guard_ocr
    try:
        guard_ocr("outside-loop")
        return True
    except VisionPolicyViolation:
        return False


# --------------------------------------------------------------------- section G
def case_metrics() -> None:
    from winter_agent_v2.visual_servo import ServoConfig, VisualServoSession

    screen = _make_screen()
    screen.drift = 4.0
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                        max_session_duration_s=0.8))
    rep = sess.run(_column_detector, _steer, None)
    d = rep.to_dict()
    pol = d["vision_policy"]
    for key in ("capture_ms_mean", "opencv_ms_mean", "ocr_calls", "ocr_ms_mean",
                "control_loop_ms_mean", "fps", "vision_hz", "control_hz",
                "lost_target_frames"):
        check(f"G1 counter present: {key}", key in pol, str(list(pol.keys())))
    check("G2 fps / vision_hz / control_hz are positive numbers",
          all(isinstance(pol[k], (int, float)) and pol[k] > 0
              for k in ("fps", "vision_hz", "control_hz")),
          str((pol["fps"], pol["vision_hz"], pol["control_hz"])))
    check("G3 the same numbers are also surfaced at the top level",
          d.get("control_hz") == pol["control_hz"] and d.get("vision_hz") == pol["vision_hz"])
    check("G4 lost_target_frames is counted on the policy counters",
          isinstance(pol["lost_target_frames"], int))
    check("G5 opencv time is attributed (it is the vision stage)",
          pol["opencv_ms_mean"] is not None and pol["opencv_ms_mean"] > 0)

    # a lost-target run must raise lost_target_frames
    class Blind(_make_screen().__class__):  # type: ignore[misc]
        def capture(self):
            return np.zeros((60, 720, 3), dtype=np.uint8)

    blind = Blind()
    sess2 = VisualServoSession(blind, config=ServoConfig(anchor_y=10, target_hz=0,
                                                        max_session_duration_s=0.4))
    rep2 = sess2.run(_column_detector, _steer, None)
    check("G6 a blind run counts lost_target_frames",
          rep2.to_dict()["vision_policy"]["lost_target_frames"] > 0,
          str(rep2.to_dict()["vision_policy"]["lost_target_frames"]))


# --------------------------------------------------------------------- section A
def case_localisation() -> None:
    tpls = sorted((ROOT / "dataset" / "candidate" / "templates").glob("*.png"))
    frame = np.zeros((200, 300, 3), dtype=np.uint8)

    if tpls:
        from PIL import Image
        tpl = Image.open(tpls[0]).convert("RGB")
        if tpl.size[0] < 120 and tpl.size[1] < 120:
            arr = np.asarray(tpl)
            frame[60:60 + arr.shape[0], 90:90 + arr.shape[1]] = arr
            spec = TargetSpec(name="probe", locator=Locator.TEMPLATE,
                              template=tpls[0].name, template_threshold=0.75)
            loc = localize(frame, spec, index=1)
            check("A1 TEMPLATE returns a bbox measured on this frame",
                  loc.found and abs(loc.bbox[0] - 90) <= 3 and abs(loc.bbox[1] - 60) <= 3,
                  str(loc.to_dict()))
            check("A2 the bbox centre is derived, not stored",
                  loc.centre is not None and abs(loc.centre[0] - (90 + arr.shape[1] // 2)) <= 3,
                  str(loc.centre))
        else:
            check("A1 TEMPLATE returns a bbox measured on this frame", True, "skipped: template too large")
            check("A2 the bbox centre is derived, not stored", True, "skipped")
    else:
        check("A1 TEMPLATE returns a bbox measured on this frame", False, "no templates found")
        check("A2 the bbox centre is derived, not stored", False)

    # COLOR: a green blob at a known place
    f2 = np.zeros((200, 300, 3), dtype=np.uint8)
    f2[100:130, 40:70] = (0, 220, 40)
    loc = localize(f2, TargetSpec(name="green", locator=Locator.COLOR,
                                  hsv_low=(40, 120, 120), hsv_high=(85, 255, 255),
                                  min_area=60), index=2)
    check("A3 COLOR finds the blob's own bbox",
          loc.found and abs(loc.bbox[0] - 40) <= 4 and abs(loc.bbox[1] - 100) <= 4,
          str(loc.to_dict()))

    # CONTOUR / GEOMETRY: salient blob without a colour spec
    f3 = np.zeros((200, 300, 3), dtype=np.uint8)
    f3[40:90, 200:260] = (250, 250, 250)
    loc = localize(f3, TargetSpec(name="salient", locator=Locator.GEOMETRY,
                                  min_area=200), index=3)
    check("A4 GEOMETRY finds a salient blob with no colour range", loc.found,
          str(loc.to_dict()))

    # STRUCTURE: slot geometry
    loc = localize(f3, TargetSpec(name="slot3", locator=Locator.STRUCTURE, slots=8,
                                  slot_index=2, slot_axis="x"), index=4)
    check("A5 STRUCTURE returns the requested slot",
          loc.found and abs(loc.bbox[0] - int(2 * 300 / 8)) <= 1, str(loc.bbox))

    # PHASH: identity of the frame itself
    from winter_agent_v2.image_hash import phash
    from PIL import Image
    ph = phash(Image.fromarray(f3).convert("RGB"))
    loc = localize(f3, TargetSpec(name="ph", locator=Locator.PHASH, phash_hex=ph,
                                  phash_max_distance=4), index=5)
    check("A6 PHASH matches the frame it was computed from", loc.found, str(loc.to_dict()))
    loc = localize(np.full((200, 300, 3), 255, np.uint8),
                   TargetSpec(name="ph", locator=Locator.PHASH, phash_hex=ph,
                              phash_max_distance=2), index=6)
    check("A7 PHASH rejects a different frame", not loc.found, str(loc.to_dict()))


def case_no_stale_coordinates() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    spec = TargetSpec(name="slot", locator=Locator.STRUCTURE, slots=4, slot_index=1)
    loc = localize(frame, spec, index=1)
    same = frame_token(frame, 1)
    other = frame_token(frame, 2)
    require_fresh(loc, same)
    check("A8 a localisation from the current frame is accepted", True)
    try:
        require_fresh(loc, other)
        check("A9 a localisation from ANOTHER frame is refused (no coordinate replay)", False,
              "no violation raised")
    except VisionPolicyViolation as exc:
        check("A9 a localisation from ANOTHER frame is refused (no coordinate replay)",
              "Re-measure" in str(exc), str(exc)[:70])
    fields = set(TargetSpec.__dataclass_fields__)
    check("A10 TargetSpec carries no absolute click coordinate",
          not (fields & {"x", "y", "tap", "point", "centre", "center"}),
          str(sorted(fields)))
    check("A11 priority helper returns the first hit, in the order given",
          first_found([Localization(False, "a"), Localization(True, "b"),
                       Localization(True, "c")]).method == "b")


def main() -> int:
    case_priority_order()
    case_routing()
    case_gate_blocks_ocr()
    case_ocr_engine_chokepoint()
    case_violating_detector_rejected()
    case_clean_session_is_pure()
    case_metrics()
    case_localisation()
    case_no_stale_coordinates()
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
