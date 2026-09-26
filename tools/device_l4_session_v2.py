"""One-lease device L4 session v2 (2026-09-26 evening).

Lessons baked in from the v1 attempts (see learning/device_l4_session_20260926.json
crash history):
  * Text recognition is RapidOCR, never MAA (MAA resource has no OCR model).
  * One frame per OCR round: adapter.frame() can return None on rapid repeats.
  * HOME = city view; its quick panel is NOT always visible, so HOME markers
    are 统帅 (top HUD) + the bottom bar, not the panel rows.
  * BACK at root views opens the exit-game dialog -> dismiss via OCR-located
    取消, never press BACK at a root view twice.
  * The bottom-right chip reads 野外 when the city view is active; tapping it
    goes OUTSIDE.  Do not tap it to "reach home".

Flow (all inside ONE lease and ONE process):
  1. mail/profile popups -> exit via top-left back arrow zone
  2. ROLE read on 领主档案 if reachable, else open it from the avatar
  3. OPEN_RESEARCH STRUCTURE test -> research page verify -> back
  4. BEAR_AUTO_JOIN state machine on the alliance war page
  5. BTN_WAR_TAB_RALLY recognition hit
Evidence -> learning/device_l4_session_20260926_v2.json
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

from PIL import Image  # noqa: E402

from winter_agent_v2.device_lease import DeviceLease  # noqa: E402
from winter_agent_v2.executor_router import (  # noqa: E402
    ExecutorRouter, RoutingTable, _rapid_ocr_results)
from winter_agent_v2.maa_executor import MaaExecutorAdapter  # noqa: E402

CONFIG = json.loads((PROJECT_ROOT / "config/v2.json").read_text(encoding="utf-8"))
DEVICE = CONFIG["device"]
OUT = PROJECT_ROOT / "learning" / "device_l4_session_20260926_v2.json"
EV = PROJECT_ROOT / "dataset" / "evidence" / "device_l4_session"

ADAPTER = None
ROUTER = None
EVID: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "tests": {}}


def log(msg: str) -> None:
    print(f"[{_stamp()}] {msg}", flush=True)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%H%M%S")


def frame() -> Image.Image | None:
    for _ in range(4):
        f = ADAPTER.frame()
        if f is not None:
            return Image.fromarray(f)
        time.sleep(1.0)
    return None


def tokens(img: Image.Image | None = None):
    img = img or frame()
    if img is None:
        return []
    return _rapid_ocr_results(__import__("numpy").asarray(img), None, [])


def text_of(img: Image.Image | None = None) -> str:
    return " ".join(t["text"] for t in tokens(img))


def save(tag: str) -> str:
    EV.mkdir(parents=True, exist_ok=True)
    img = frame()
    if img is not None:
        img.save(EV / f"v2_{tag}_{_stamp()}.png")
    return tag


def click(x: int, y: int) -> bool:
    ok, reason = ADAPTER.click(int(x), int(y))
    if not ok:
        log(f"click refused: {reason}")
    return ok


def tap_token(pred, img=None) -> bool:
    for t in tokens(img):
        box = t.get("box")
        if box and pred(t["text"], box):
            x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
            log(f"tap {t['text']!r} at ({x},{y})")
            return click(x, y)
    return False


def dismiss_popups(rounds: int = 3) -> None:
    """Exit-game dialog -> 取消; generic top-left back arrow for sub-pages."""
    for _ in range(rounds):
        ts = tokens()
        text = " ".join(t["text"] for t in ts)
        if "退出游戏" in text:
            tap_token(lambda s, b: "取消" in s)
            time.sleep(1.5)
            continue
        break


def exit_subpage(rounds: int = 3) -> None:
    """Pages with a top-left ← arrow: tap the arrow zone to go back."""
    for _ in range(rounds):
        img = frame()
        if img is None:
            return
        ts = tokens(img)
        text = " ".join(t["text"] for t in ts)
        if "退出游戏" in text:
            tap_token(lambda s, b: "取消" in s, img)
            time.sleep(1.5)
            continue
        if any(w in text for w in ("领主档案", "邮件", "设置")):
            click(45, 45)  # top-left back arrow zone
            time.sleep(1.8)
            continue
        return


def at_city() -> bool:
    text = text_of()
    return "统帅" in text and "退出游戏" not in text


def walk_to_city(max_steps: int = 8) -> bool:
    """Generic recovery: any view without the 统帅 HUD is a subpage or the
    map/wild view; the top-left back arrow zone exits subpages, 取消 dismisses
    the exit dialog, and the 野外 chip (label of the OUTSIDE toggle) is left
    alone — the game boots to city after relaunch when everything else fails.
    """
    for i in range(max_steps):
        img = frame()
        if img is None:
            time.sleep(1.0)
            continue
        ts = _rapid_ocr_results(__import__("numpy").asarray(img), None, [])
        text = " ".join(t["text"] for t in ts)
        if "退出游戏" in text:
            tap_token(lambda s, b: "取消" in s, img)
            time.sleep(1.5)
            continue
        if "统帅" in text:
            log(f"city reached at step {i}")
            return True
        log(f"step {i}: subpage/view, tapping top-left back zone")
        click(45, 45)
        time.sleep(1.8)
    return at_city()


# ------------------------------------------------------------------- tests
def role_confirm() -> dict:
    """Open 领主档案 (profile) and store role identity."""
    rec: dict = {}
    text = text_of()
    if "领主档案" not in text:
        # avatar is the top-left portrait zone
        save("before_avatar")
        click(45, 60)
        time.sleep(2.0)
        text = text_of()
    if "领主档案" in text:
        rec["page"] = "PROFILE"
        save("profile")
        # name token: the one right before 账号 marker / containing zoe
        name = ""
        for t in tokens():
            if "小号" in t["text"] or ("zoe" in t["text"] and "联盟" not in t["text"]):
                name = t["text"]
                break
        rec["role_name"] = name
        rec["alliance"] = next((t["text"] for t in tokens() if t["text"].startswith("联盟")), "")
        if name:
            (PROJECT_ROOT / "learning" / "bear_role.json").write_text(
                json.dumps({"role_name": name, "confirmed_at": datetime.now(timezone.utc).isoformat(),
                            "frame": "领主档案"}, ensure_ascii=False, indent=1), encoding="utf-8")
            rec["verifier"] = "ROLE_STORED"
            rec["level"] = "ROLE_CONFIRMED"
        else:
            rec["verifier"] = "NAME_NOT_READ"
            rec["level"] = "ROLE_UNCONFIRMED"
        click(45, 45)  # leave profile
        time.sleep(1.8)
    else:
        rec["verifier"] = "PROFILE_NOT_OPENED"
        rec["level"] = "ROLE_UNCONFIRMED"
    return rec


def test_open_research() -> dict:
    rec = {"frame_before": save("research_before")}
    node = ROUTER.routing.recognition_node("OPEN_RESEARCH", "BTN_OPEN_RESEARCH")
    rec["node_kind"] = node.get("kind") if node else None
    point = ROUTER.maa_resolver("BTN_OPEN_RESEARCH", "OPEN_RESEARCH")
    rec["resolver"] = "NONE:" + str(ROUTER.last_recognition_error) if point is None else "OK"
    if point is None:
        rec["level"] = "FAIL"
        return rec
    f = frame()
    px, py = int(point[0] * f.width), int(point[1] * f.height)
    rec["tap_px"] = [px, py]
    rec["clicked"] = click(px, py)
    time.sleep(2.0)
    # research page: 研究 button bottom-right region (page-specific)
    img = frame()
    hits = [t for t in tokens(img) if "研究" in t["text"]
            and t["box"][1] > 850 and t["box"][0] > 380]
    rec["after_frame"] = save("research_after")
    rec["verifier"] = "PAGE_REACHED" if hits else "PAGE_NOT_CONFIRMED"
    rec["level"] = "L4" if hits else "L3_FAIL"
    ADAPTER.press_back()
    time.sleep(1.5)
    return rec


def bear_auto_join() -> dict:
    rec: dict = {"state_machine": []}
    from winter_agent_v2.bear_state import read_state_from_image
    # navigate: 联盟 bottom bar -> war page entry
    ok = tap_token(lambda s, b: s.strip() == "联盟" and b[1] > 1150)
    rec["tapped_alliance_bar"] = ok
    time.sleep(2.5)
    text = text_of()
    if "联盟" not in text:
        rec["level"] = "NAV_FAIL"
        return rec
    save("alliance")
    open_rec = ROUTER.maa_resolver("BTN_ALLIANCE_WAR", "OPEN_BEAR_RALLY_LIST")
    if open_rec is None:
        rec["open_rally"] = f"NONE:{ROUTER.last_recognition_error}"
        rec["level"] = "NAV_FAIL"
        return rec
    f = frame()
    click(int(open_rec[0] * f.width), int(open_rec[1] * f.height))
    time.sleep(2.5)
    img = frame()
    before = read_state_from_image(img)
    rec["state_before"] = before
    rec["state_machine"].append(before["state"])
    if before["state"] == "ON":
        rec["verifier"] = "NOOP_ALREADY_ON"
        rec["level"] = "L4_NOOP"
    elif before["state"] == "UNKNOWN":
        rec["verifier"] = "BLOCKED_UNKNOWN_STATE"
        rec["level"] = "BLOCKED"
    else:
        pt = ROUTER.maa_resolver("BTN_BEAR_AUTO_JOIN", "BEAR_AUTO_JOIN")
        rec["resolver"] = "NONE:" + str(ROUTER.last_recognition_error) if pt is None else "OK"
        if pt is None:
            rec["level"] = "FAIL"
            return rec
        click(int(pt[0] * f.width), int(pt[1] * f.height))
        time.sleep(2.0)
        after = read_state_from_image(frame())
        rec["state_after"] = after
        rec["state_machine"].append(after["state"])
        rec["verifier"] = ("TOGGLED_OFF_TO_ON"
                           if before["state"] == "OFF" and after["state"] == "ON"
                           else f"UNEXPECTED_{after['state']}")
        rec["level"] = "L4" if rec["verifier"] == "TOGGLED_OFF_TO_ON" else "FAIL"
    # rally tab OCR hit (same page)
    img = frame()
    hits = [t for t in tokens(img) if "集结" in t["text"] and t["box"][1] < 200]
    rec["BTN_WAR_TAB_RALLY"] = {"hit": bool(hits), "level": "L3" if hits else "L3_FAIL"}
    return rec


def main() -> int:
    global ADAPTER, ROUTER
    lease = DeviceLease(PROJECT_ROOT)
    record, reason = lease.acquire(owner="DEVICE_L4_SESSION_V2", capability_id="L2_DIGESTION",
                                   trace_id="l4_session_v2", ttl_seconds=900,
                                   reason="one-lease L2->L4 session")
    if record is None:
        print(json.dumps({"lease": "REFUSED", "reason": reason}, ensure_ascii=False))
        return 2
    EVID["lease_id"] = record.lease_id
    try:
        ADAPTER = MaaExecutorAdapter(adb_path=DEVICE["adb_path"], serial=str(DEVICE["serial"]),
                                     production=True,
                                     template_dir=PROJECT_ROOT / "dataset/candidate/templates",
                                     log_dir=PROJECT_ROOT / "learning/maa_logs")
        ok, why = ADAPTER.ensure_ready()
        EVID["maa_ready"] = {"ok": ok, "reason": why}
        if not ok:
            EVID["aborted"] = "MAA_NOT_READY"
            return 3
        ROUTER = ExecutorRouter(adb_executor=None, maa_adapter=ADAPTER,
                                routing=RoutingTable.load())
        time.sleep(1.0)
        walk_to_city()
        log(f"city={at_city()} text[:120]={text_of()[:120]!r}")
        EVID["city_view"] = at_city()
        save("start")

        log("role_confirm")
        EVID["tests"]["ROLE"] = role_confirm()
        log(f"ROLE -> {EVID['tests']['ROLE'].get('level')}")

        walk_to_city()
        log("OPEN_RESEARCH")
        EVID["tests"]["OPEN_RESEARCH"] = test_open_research()
        log(f"OPEN_RESEARCH -> {EVID['tests']['OPEN_RESEARCH'].get('level')}")

        exit_subpage()
        walk_to_city()
        log("BEAR_AUTO_JOIN")
        EVID["tests"]["BEAR_AUTO_JOIN"] = bear_auto_join()
        log(f"BEAR -> {EVID['tests']['BEAR_AUTO_JOIN'].get('level')}")
        EVID["finished_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        lease.release(result="DONE", reason="session end")
        OUT.write_text(json.dumps(EVID, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(EVID["tests"], ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
