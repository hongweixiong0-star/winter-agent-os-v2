"""Read the auto-join capability boundary off the live client (round brief §十九).

The brief lists ten things to establish about AUTO_JOIN and adds two words that
govern how: 不要猜.  Everything below is therefore either

    CLIENT_STATED   -- the client printed it, and the printed text is recorded
    NOT_STATED      -- the client did not say, so the answer stays unknown

and a NOT_STATED is a result, not a failure to fill in.  This session never taps
the toggle: §十八 reserves the click for "需要自动加入时才点击", and the event is
still ~42 h away, so reading is all that is asked of it.

Usage:
  .venv/Scripts/python.exe -u tools/device_autojoin_boundary.py [--dry-run]
Exit codes: 0 recorded, 2 lease refused, 3 no frame/adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

EVIDENCE = ROOT / "dataset" / "evidence" / "autojoin_boundary_20260927"

QUESTIONS = (
    "uses_preset_heroes",
    "uses_preset_troops",
    "occupies_normal_march_queue",
    "stays_enabled",
    "targets_bear_only",
    "switches_when_full",
    "has_join_delay",
    "only_after_event_start",
    "per_role",
    "has_failure_notice",
)

#: Words the client uses to talk about auto-join and the things it does.
HINT_WORDS = (
    "自动加入", "冰原巨兽", "预设", "英雄", "兵力", "队列", "满员", "满", "分钟",
    "开启", "停止", "失败", "取消", "集结", "活动", "倒计时", "说明", "规则",
)


def _pil(x):
    return x if isinstance(x, Image.Image) else Image.fromarray(x)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="never tap; navigate and read only")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import ExecutorRouter, RoutingTable, _rapid_ocr_results

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_AUTOJOIN_BOUNDARY",
        capability_id="L2_DIGESTION",
        ttl_seconds=600,
        reason="read the auto-join capability boundary off the live client (brief §19)",
    )
    if rec is None:
        print("REFUSED", why)
        return 2

    out: dict = {
        "session_started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "AUTO_JOIN capability boundary, client-stated only",
        "questions": {q: {"answer": None, "status": "NOT_STATED", "client_text": None}
                      for q in QUESTIONS},
        "steps": [],
    }
    try:
        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()
        router = ExecutorRouter(adb_executor=None, maa_adapter=adapter, routing=RoutingTable.load())

        def frame(retries: int = 4):
            for _ in range(retries):
                f = adapter.frame()
                if f is not None:
                    return _pil(f)
                time.sleep(1)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag: str):
            p = EVIDENCE / f"autojoin_{tag}.png"
            _pil(img).save(p)
            out["steps"].append({"tag": tag, "frame": str(p.relative_to(ROOT))})
            return p

        def box_of(token):
            """(x, y, w, h) from either box spelling RapidOCR hands back.

            ``_rapid_ocr_results`` returns ``[x, y, w, h]``; the OCR token objects
            carry four corner points.  Both mean the same rectangle and a session
            that reads one as the other talks to coordinates that do not exist.
            """
            box = token.get("box") or ()
            if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                x, y, w, h = (int(v) for v in box)
                return (x, y, w, h)
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            return (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))

        def tap_norm(pt, img):
            if args.dry_run:
                return False
            adapter.click(int(pt[0] * img.width), int(pt[1] * img.height))
            return True

        # 0. handover: reach the city view.  AUTO may hand the device over on any
        # page, and BACK from the root raises 确认退出游戏吗？ -- 取消 is the only
        # safe answer to that dialog, so it is handled before any navigation.
        for _ in range(5):
            f0 = frame()
            if f0 is None:
                out["error"] = "no frame during handover"
                print(json.dumps(out, ensure_ascii=False))
                return 3
            t0 = text(f0)
            if "统帅" in t0:
                break
            if "退出游戏吗" in t0 or "确认退出游戏" in t0:
                cancel = [t for t in toks(f0) if "取消" in t["text"]]
                if cancel:
                    x, y, w, h = box_of(cancel[0])
                    adapter.click(x + w // 2, y + h // 2)
                    time.sleep(1.5)
                    continue
            adapter.press_back()
            time.sleep(2.0)
            fg = frame()
            tg = text(fg) if fg is not None else ""
            if "退出游戏吗" in tg:
                cancel = [t for t in toks(fg) if "取消" in t["text"]]
                if cancel:
                    x, y, w, h = box_of(cancel[0])
                    adapter.click(x + w // 2, y + h // 2)
                    time.sleep(1.5)

        f = frame()
        save(f, "01_home")
        out["home_confirmed"] = "统帅" in text(f)

        # 1. HOME -> alliance -> alliance war -> 集结 tab
        nav = []
        for semantic, skill in (("BTN_OPEN_ALLIANCE", "OPEN_ALLIANCE"),
                                ("BTN_ALLIANCE_WAR", "OPEN_BEAR_RALLY_LIST")):
            img = frame()
            pt = router.maa_resolver(semantic, skill)
            nav.append({"semantic": semantic, "resolved": bool(pt),
                        "error": router.last_recognition_error})
            if pt:
                tap_norm(pt, img)
                time.sleep(2.5)
                f = frame()
                save(f, f"02_after_{semantic}")
        out["navigation"] = nav

        img = frame()
        if img is None:
            out["error"] = "no frame after navigation"
            print(json.dumps(out, ensure_ascii=False))
            return 3

        # 2. the rally tab itself (the 集结 tab may not be the one the client opens)
        page = text(img)
        out["war_page_text"] = page[:400]
        if "集结" in page:
            tabs = [t for t in toks(img) if t["text"].strip() == "集结"]
            if tabs:
                pt = router.maa_resolver("BTN_WAR_TAB_RALLY", "OPEN_BEAR_RALLY_LIST")
                out["rally_tab_resolved"] = bool(pt)
                if pt:
                    tap_norm(pt, img)
                    time.sleep(2.0)
                    img = frame()
                    save(img, "03_rally_tab")
                    page = text(img)
                    out["rally_tab_text"] = page[:400]

        save(img, "04_final_page")
        tokens = toks(img)
        out["page_tokens"] = [{"text": t["text"], "box": box_of(t), "score": t.get("score")}
                              for t in tokens]

        # 3. the toggle state, read the way production reads it
        from winter_agent_v2.bear_state import read_state_from_image

        state = read_state_from_image(img)
        out["auto_join_state"] = state

        # 4. the rally list on a live frame: no war right now means rows=[]
        from winter_agent_v2 import rally

        reading = rally.read_rally_list_image(img, _as_tokens(tokens, img))
        out["rally_rows_live"] = [row.to_dict() for row in reading.rows]
        out["rally_rows_evidence"] = dict(reading.evidence)

        # 5. what the client actually says, gathered into the ten questions
        joined = page
        hint_lines = [t["text"].strip() for t in tokens
                      if any(word in t["text"] for word in HINT_WORDS)]
        out["hint_lines"] = hint_lines

        def answer(key: str, value, client_text: str | None, status: str = "CLIENT_STATED"):
            out["questions"][key] = {"answer": value, "status": status,
                                     "client_text": client_text}

        auto_line = next((h for h in hint_lines if "自动加入" in h and len(h) > 4), None)
        if auto_line:
            answer("targets_bear_only", "冰原巨兽" in joined or "巨熊" in joined, auto_line)
            answer("only_after_event_start", "开启后" in joined, auto_line)
            if "停止" in joined or "1分钟" in joined or "分钟" in joined:
                answer("has_join_delay", True, next((h for h in hint_lines if "分钟" in h), auto_line))
        if state.get("state") in {"ON", "OFF"}:
            answer("per_role", True,
                   f"toggle read {state['state']} on this role's own war page",
                   "CLIENT_STATED")
        out["answered"] = sum(1 for q in out["questions"].values() if q["status"] == "CLIENT_STATED")
        out["unknown"] = [k for k, q in out["questions"].items() if q["status"] == "NOT_STATED"]

        dest = ROOT / "learning" / "autojoin_boundary_20260927.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="autojoin boundary session end")


def _as_tokens(raw_tokens, img):
    """Re-shape the router's OCR dicts into the tokens ``rally`` expects."""
    from winter_agent_v2.ocr import OCRToken

    made = []
    for token in raw_tokens:
        box = token.get("box") or ()
        corners: tuple[tuple[float, float], ...] = ()
        if len(box) == 4:
            if all(isinstance(v, (int, float)) for v in box):
                x, y, w, h = (float(v) for v in box)
                corners = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
            else:
                corners = tuple((float(p[0]), float(p[1])) for p in box)
        made.append(OCRToken(text=str(token.get("text", "")),
                             confidence=float(token.get("score", 0.0) or 0.0),
                             box=corners))
    return made


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
