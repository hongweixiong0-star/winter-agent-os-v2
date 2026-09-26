"""One-lease device L4 verification session (operator directive 2026-09-26 #3).

Single process: acquire lease -> MAA connect -> sequential node tests ->
release lease.  Every test drives the PRODUCTION dispatch path
(ExecutorRouter.maa_resolver on the real routing entry), never a test-only
shortcut, and records the full evidence chain:

  skill -> semantic -> node kind -> anchor/recognition -> computed tap ->
  MAA click result -> after-page OCR -> verifier verdict.

Tests
  A  OPEN_RESEARCH       STRUCTURE anchor+offset -> research page
  A2 BTN_START_RESEARCH  live OCR recognition hit on the research page (L3)
  B  OPEN_POWER_OVERVIEW template node -> power page
  C  OPEN_BUILDING_UPGRADE template node -> building page
  D  BEAR_AUTO_JOIN      state machine: ON=NOOP / UNKNOWN=no click /
                         OFF=click -> must read ON  (only OFF->click->ON = L4)
  D2 BTN_WAR_TAB_RALLY   live OCR recognition hit on the war page (L3)

Verdicts are hard: L4 requires a page/state change read back from the client.

Usage:
  .venv/Scripts/python.exe tools/device_l4_session.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from winter_agent_v2.device_lease import DeviceLease  # noqa: E402
from winter_agent_v2.executor_router import ExecutorRouter, RoutingTable  # noqa: E402
from winter_agent_v2.maa_executor import MaaExecutorAdapter  # noqa: E402

CONFIG = json.loads((PROJECT_ROOT / "config/v2.json").read_text(encoding="utf-8"))
DEVICE = CONFIG["device"]
EVIDENCE_DIR = PROJECT_ROOT / "dataset" / "evidence" / "device_l4_session"
OUT_PATH = PROJECT_ROOT / "learning" / "device_l4_session_20260926.json"

ROUTER = None
ADAPTER = None
EVIDENCE: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "tests": {}}


def _log(msg: str) -> None:
    line = f"[session {_stamp()}] {msg}"
    print(line, flush=True)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _save_frame(name: str) -> str:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{name}_{_stamp()}.png"
    frame = ADAPTER.frame()
    if frame is not None:
        from PIL import Image
        Image.fromarray(frame).save(path)
    return str(path)


def _rapid_tokens(frame):
    """Project doctrine: text -> RapidOCR.  Accepts np arrays and PIL images."""
    from PIL import Image as _Img
    from winter_agent_v2.ocr import RapidOCRBackend
    if not isinstance(frame, _Img.Image):
        frame = _Img.fromarray(frame)
    return RapidOCRBackend().recognize(frame)


def _ocr_text() -> str:
    frame = ADAPTER.frame()
    if frame is None:
        return ""
    return "".join(t.text for t in _rapid_tokens(frame))


def _tap_norm(nx: float, ny: float) -> tuple[bool, str, tuple[int, int]]:
    frame = ADAPTER.frame()
    if frame is None:
        return False, "NO_FRAME", (0, 0)
    h, w = frame.shape[0], frame.shape[1]
    px, py = int(nx * w), int(ny * h)
    ok, reason = ADAPTER.click(px, py)
    return ok, reason, (px, py)


def _resolver_tap(semantic: str, skill: str) -> dict:
    """Production dispatch path: routing node -> maa_resolver -> click."""
    node = ROUTER.routing.recognition_node(skill, semantic)
    if node is None:
        return {"ok": False, "reason": "NO_ROUTING_NODE", "node_kind": None}
    info = {"node_kind": node.get("kind"), "node": node}
    point = ROUTER.maa_resolver(semantic, skill)
    if point is None:
        info["ok"] = False
        info["reason"] = ROUTER.last_recognition_error or "RESOLVER_NONE"
        return info
    info["resolver_point_norm"] = [round(point[0], 4), round(point[1], 4)]
    ok, reason, px = _tap_norm(*point)
    info["ok"] = ok
    info["click"] = {"px": list(px), "reason": reason}
    return info


def _wait_words(words: tuple[str, ...], *, timeout_s: float = 6.0) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        text = _ocr_text()
        for w in words:
            if w in text:
                return True, w
        time.sleep(0.6)
    return False, ""


def _dismiss_exit_dialog() -> bool:
    """If the exit-game confirm dialog is open, click 取消 (OCR-located)."""
    frame = ADAPTER.frame()
    if frame is None:
        return False
    for t in _rapid_tokens(frame):
        if "取消" in t.text and t.box:
            xs = [p[0] for p in t.box]
            ys = [p[1] for p in t.box]
            px, py = int(sum(xs) / len(xs)), int(sum(ys) / len(ys))
            ADAPTER.click(px, py)
            time.sleep(1.0)
            return True
    return False


def _at_home() -> bool:
    """City view only: the quick panel prints the 科技研究/部队训练 rows."""
    text = _ocr_text()
    return "科技研究" in text or "部队训练" in text


def _tap_city_toggle() -> bool:
    """The bottom-right 城镇/野外 chip.  When it reads 野外 we are in the
    wilderness camera; tapping it returns to the city (城镇) view."""
    frame = ADAPTER.frame()
    if frame is None:
        return False
    h, w = frame.shape[0], frame.shape[1]
    for t in _rapid_tokens(frame):
        if "野外" in t.text and t.box:
            xs = [p[0] for p in t.box]
            ys = [p[1] for p in t.box]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            if cx > w * 0.6 and cy > h * 0.85:  # bottom-right chip only
                ADAPTER.click(int(cx), int(cy))
                time.sleep(1.8)
                return True
    return False


def _back_to_home(max_backs: int = 6) -> bool:
    for i in range(max_backs):
        _log(f"back_to_home iter {i}")
        if _at_home():
            return True
        # wilderness view -> switch the city/wilderness chip back to 城镇
        if _tap_city_toggle():
            if _at_home():
                return True
            continue
        # MAP/world view -> the verified HOME chip brings us back to the city
        home_node = ROUTER.routing.recognition_node("OPEN_HOME", "BTN_OPEN_HOME")
        if home_node is not None:
            point = ROUTER.maa_resolver("BTN_OPEN_HOME", "OPEN_HOME")
            if point is not None:
                _tap_norm(*point)
                time.sleep(1.5)
                if _at_home():
                    return True
        if not _dismiss_exit_dialog():
            ADAPTER.press_back()
        time.sleep(1.2)
    return False


# ------------------------------------------------------------------- tests
def test_open_research() -> dict:
    rec: dict = {"frame_before": _save_frame("research_before")}
    rec.update(_resolver_tap("BTN_OPEN_RESEARCH", "OPEN_RESEARCH"))
    # Page verify must be research-page-SPECIFIC: the 研究 button in the
    # bottom-right region.  (HOME itself contains 科技研究 text, so a global
    # word wait produced a false L4 on the first session — voided.)
    time.sleep(1.5)
    frame = ADAPTER.frame()
    hit = False
    if frame is not None:
        from PIL import Image as _Img
        img = frame if isinstance(frame, _Img.Image) else _Img.fromarray(frame)
        hits = [t for t in _rapid_tokens(img.crop((400, 860, 640, 980)))
                if "研究" in t.text]
        hit = bool(hits)
    rec["after_frame"] = _save_frame("research_after")
    rec["verifier"] = "PAGE_REACHED" if hit else "PAGE_NOT_CONFIRMED"
    rec["level"] = "L4" if hit else "L3_FAIL"
    ADAPTER.press_back()
    time.sleep(1.0)
    return rec


def test_start_research_hit() -> dict:
    """Recognition-only: research page must show the 研究 button in ROI."""
    frame = ADAPTER.frame()
    if frame is None:
        return {"ok": False, "error": "NO_FRAME", "level": "L3_FAIL"}
    from PIL import Image as _Img
    crop = _Img.fromarray(frame).crop((400, 860, 640, 980))
    hits = [t for t in _rapid_tokens(crop) if "研究" in t.text]
    return {"ok": bool(hits), "results": [
        {"text": t.text, "confidence": round(t.confidence, 3)} for t in hits],
        "verifier": "RECOGNITION_HIT" if hits else "NO_HIT",
        "level": "L3" if hits else "L3_FAIL"}


def _region_has_words(region, words) -> tuple[bool, str]:
    frame = ADAPTER.frame()
    if frame is None:
        return False, ""
    from PIL import Image as _Img
    img = frame if isinstance(frame, _Img.Image) else _Img.fromarray(frame)
    x, y, w, h = region
    text = "".join(t.text for t in _rapid_tokens(img.crop((x, y, x + w, y + h))))
    for word in words:
        if word in text:
            return True, word
    return False, text[:60]


def test_power_overview() -> dict:
    rec = _resolver_tap("BTN_OPEN_POWER_OVERVIEW_ICON", "OPEN_POWER_OVERVIEW")
    time.sleep(1.5)
    found, word = _region_has_words((60, 60, 600, 300), ("实力", "统计", "战力", "详情"))
    rec["after_frame"] = _save_frame("power_after")
    rec["after_ocr_word"] = word
    rec["verifier"] = "PAGE_REACHED" if found else "PAGE_NOT_CONFIRMED"
    rec["level"] = "L4" if found else "L3_UNCONFIRMED"
    ADAPTER.press_back()
    time.sleep(1.0)
    return rec


def test_building_upgrade() -> dict:
    rec = _resolver_tap("BTN_SELECTED_BUILDING_UPGRADE", "OPEN_BUILDING_UPGRADE")
    time.sleep(1.5)
    # popup body region only: HOME's quick-panel 「大熔炉升级中」 row sits
    # lower on screen and must not satisfy this verifier
    found, word = _region_has_words((150, 300, 420, 500), ("升级", "详情", "要求", "建筑"))
    rec["after_frame"] = _save_frame("building_after")
    rec["after_ocr_word"] = word
    rec["verifier"] = "PAGE_REACHED" if found else "PAGE_NOT_CONFIRMED"
    rec["level"] = "L4" if found else "L3_UNCONFIRMED"
    ADAPTER.press_back()
    time.sleep(1.0)
    return rec


def test_bear_auto_join() -> dict:
    from tools.bear_auto_join_state import read_state
    rec: dict = {"state_machine": []}

    # open the rally list: alliance-war entry
    open_rec = _resolver_tap("BTN_ALLIANCE_WAR", "OPEN_BEAR_RALLY_LIST")
    rec["open_rally_list"] = {k: v for k, v in open_rec.items() if k != "node"}
    time.sleep(1.5)

    before = read_state(_save_frame("bear_before"))
    rec["state_before"] = before
    rec["state_machine"].append(before["state"])
    if before["state"] == "ON":
        rec["verifier"] = "NOOP_ALREADY_ON"
        rec["level"] = "L4_NOOP"
    elif before["state"] == "UNKNOWN":
        rec["verifier"] = "BLOCKED_UNKNOWN_STATE"
        rec["level"] = "BLOCKED"
    else:  # OFF
        click_rec = _resolver_tap("BTN_BEAR_AUTO_JOIN", "BEAR_AUTO_JOIN")
        rec["click"] = {k: v for k, v in click_rec.items() if k != "node"}
        time.sleep(1.5)
        after = read_state(_save_frame("bear_after"))
        rec["state_after"] = after
        rec["state_machine"].append(after["state"])
        if before["state"] == "OFF" and after["state"] == "ON":
            rec["verifier"] = "TOGGLED_OFF_TO_ON"
            rec["level"] = "L4"
        else:
            rec["verifier"] = f"UNEXPECTED_AFTER_{after['state']}"
            rec["level"] = "FAIL"
    return rec


def test_war_tab_rally_hit() -> dict:
    frame = ADAPTER.frame()
    if frame is None:
        return {"ok": False, "error": "NO_FRAME", "level": "L3_FAIL"}
    from PIL import Image as _Img
    crop = _Img.fromarray(frame).crop((40, 95, 280, 165))
    hits = [t for t in _rapid_tokens(crop) if "集结" in t.text]
    return {"ok": bool(hits), "results": [
        {"text": t.text, "confidence": round(t.confidence, 3)} for t in hits],
        "verifier": "RECOGNITION_HIT" if hits else "NO_HIT",
        "level": "L3" if hits else "L3_FAIL"}


def main(argv: list[str]) -> int:
    global ROUTER, ADAPTER
    dry = "--dry-run" in argv
    production = not dry

    lease = DeviceLease(PROJECT_ROOT)
    record, reason = lease.acquire(
        owner="DEVICE_L4_SESSION", capability_id="L2_DIGESTION",
        trace_id="l4_session_20260926", reason="one-lease L2->L4 verification session",
    )
    if record is None:
        print(json.dumps({"lease": "REFUSED", "reason": reason}, ensure_ascii=False))
        return 2
    EVIDENCE["lease_id"] = record.lease_id
    try:
        ADAPTER = MaaExecutorAdapter(
            adb_path=DEVICE["adb_path"], serial=str(DEVICE["serial"]),
            production=production,
            template_dir=PROJECT_ROOT / "dataset/candidate/templates",
            log_dir=PROJECT_ROOT / "learning/maa_logs",
        )
        ok, why = ADAPTER.ensure_ready()
        EVIDENCE["maa_ready"] = {"ok": ok, "reason": why}
        if not ok:
            EVIDENCE["aborted"] = "MAA_NOT_READY"
            return 3
        ROUTER = ExecutorRouter(adb_executor=None, maa_adapter=ADAPTER,
                                routing=RoutingTable.load())

        at_home = _back_to_home()
        if not at_home:
            # Deterministic recovery: restart the game client; it always
            # boots into the city view.
            _log("relaunching game client for deterministic HOME recovery")
            ADAPTER.launch(DEVICE["package_name"])
            time.sleep(25)
            at_home = _back_to_home(max_backs=4)
        _log(f"back_to_home done: {at_home}")
        EVIDENCE["home_confirmed"] = at_home
        EVIDENCE["home_frame"] = _save_frame("home")
        if not at_home:
            EVIDENCE["aborted"] = "HOME_NOT_CONFIRMED"
            return 4

        tests = EVIDENCE["tests"]
        _log("starting OPEN_RESEARCH")
        tests["OPEN_RESEARCH"] = test_open_research()
        _log(f"OPEN_RESEARCH -> {tests['OPEN_RESEARCH'].get('level')}")
        tests["BTN_START_RESEARCH"] = test_start_research_hit()
        # research page left us one level deep -> recover before next test
        if not _back_to_home():
            EVIDENCE["warn"] = "home recovery failed mid-session"
        _log("starting OPEN_POWER_OVERVIEW")
        tests["OPEN_POWER_OVERVIEW"] = test_power_overview()
        _log(f"OPEN_POWER_OVERVIEW -> {tests['OPEN_POWER_OVERVIEW'].get('level')}")
        if not _back_to_home():
            EVIDENCE["warn"] = "home recovery failed after power test"
        _log("starting OPEN_BUILDING_UPGRADE")
        tests["OPEN_BUILDING_UPGRADE"] = test_building_upgrade()
        _log(f"OPEN_BUILDING_UPGRADE -> {tests['OPEN_BUILDING_UPGRADE'].get('level')}")
        if not _back_to_home():
            EVIDENCE["warn"] = "home recovery failed after building test"
        _log("starting BEAR_AUTO_JOIN")
        tests["BEAR_AUTO_JOIN"] = test_bear_auto_join()
        _log(f"BEAR_AUTO_JOIN -> {tests['BEAR_AUTO_JOIN'].get('level')}")
        tests["BTN_WAR_TAB_RALLY"] = test_war_tab_rally_hit()
        _log("all tests done")
    finally:
        lease.release(result="DONE", reason="session end")
        EVIDENCE["finished_at"] = datetime.now(timezone.utc).isoformat()
        OUT_PATH.write_text(json.dumps(EVIDENCE, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(json.dumps(EVIDENCE["tests"], ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
