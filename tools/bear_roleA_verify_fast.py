# -*- coding: utf-8 -*-
"""Fast role verify: tap avatar, read profile name, back. No other actions."""
from __future__ import annotations

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

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVID = ROOT / "dataset" / "evidence" / f"roleA_verify_{STAMP}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_ROLE_VERIFY", capability_id="BEAR_HUNT",
        ttl_seconds=240, reason="fast role verify before bear open")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {}
    try:
        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()

        def frame(retries=4):
            for _ in range(retries):
                f = adapter.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(1)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            p = EVID / f"{tag}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(p)
            return p

        def tap(x, y, wait=2.0):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle, wait=2.5):
            for t in toks(img):
                if needle in t["text"]:
                    box = t.get("box") or ()
                    if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                        x, y, w, h = (int(v) for v in box)
                    else:
                        xs = [float(p[0]) for p in box]
                        ys = [float(p[1]) for p in box]
                        x, y, w, h = int(min(xs)), int(min(ys)), 10, 10
                    adapter.click(x + w // 2, y + h // 2)
                    time.sleep(wait)
                    return True
            return False

        # back to city first
        for _ in range(6):
            f = frame()
            t = text(f)
            if "统帅" in t:
                break
            if "退出游戏" in t:
                tap_token(f, "取消", 1.5)
                continue
            adapter.press_back()
            time.sleep(2.0)

        tap(44, 44, 3.0)
        f = frame()
        save(f, "profile")
        t = text(f)
        out["profile_text"] = t[:400]
        if "零氪" not in t:
            # might be on 装扮 tab: press back once and retap avatar
            adapter.press_back()
            time.sleep(2.0)
            tap(44, 44, 3.0)
            f = frame()
            save(f, "profile_retry")
            t = text(f)
            out["profile_text_retry"] = t[:400]
        out["role_confirmed"] = "零氪" in t and "ioi" in t
        out["role"] = "[ioi]零氪纯盾流" if out["role_confirmed"] else "UNKNOWN"
        # back to city, leave game on safe screen
        for _ in range(6):
            f = frame()
            if "统帅" in text(f):
                break
            adapter.press_back()
            time.sleep(2.0)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="role verify done")


if __name__ == "__main__":
    raise SystemExit(main())
