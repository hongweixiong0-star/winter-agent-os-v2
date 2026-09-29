# -*- coding: utf-8 -*-
"""Live exploration round 4: enter 普通关卡 and record the minigame at full rate.

This is the frame source for PHASE 8.  The detector cannot be written offline —
the project rule is capture-first — so this run photographs the real minigame and
saves:

* a dense PNG sample (every Nth frame, plus the whole opening transition),
* a per-frame metric row for EVERY frame (mean/brightness/hash/change),
* the full token dump of the pre-cast and post-run screens.

One bait is spent, which the operator explicitly authorised for exploration.

usage: python tools/fishing_explore4.py [seconds]
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENTRY = (664, 476)
NORMAL_STAGE = (500, 1170)      # 普通关卡 button (token 普通关卡 @ (518,1175))
SAVE_EVERY = 4
SAVE_FIRST = 10


def sig(f: np.ndarray) -> np.ndarray:
    h, w = f.shape[:2]
    ys = np.linspace(0, h - 1, 48).astype(int)
    xs = np.linspace(0, w - 1, 48).astype(int)
    s = f[ys][:, xs]
    return (s.mean(axis=2) if s.ndim == 3 else s).astype(np.float32)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "raw" / "fishing_tournament" / f"explore4_{stamp}"
    (outd / "frames").mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISHING_EXPLORE4", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=600, reason="record the fishing minigame on real pixels")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT))}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3

        def frame():
            for _ in range(3):
                f = ad.capture()
                if f is not None:
                    return f
                time.sleep(0.3)
            raise RuntimeError("SCREENCAP_FAILED")

        def dump(tag: str, save_png=True) -> tuple[np.ndarray, str]:
            f = frame()
            if save_png:
                Image.fromarray(f).save(outd / f"{tag}.png")
            txt = " ".join(t["text"] for t in read_all(Image.fromarray(f)))
            print(f"[{tag}] {txt[:180]}")
            return f, txt

        def tap(c, wait=2.4):
            ad.click(int(c[0]), int(c[1]))
            time.sleep(wait)

        # ---- reach the home page ----
        f, txt = dump("00_start")
        if "钓鱼锦标赛" not in txt or "普通关卡" not in txt:
            h = [t for t in read_all(Image.fromarray(f)) if "钓鱼锦标赛" in t["text"]]
            if h:
                tap(h[0]["centre"], 2.6)
            f, txt = dump("01_home")
        if "普通关卡" not in txt:
            print("NOT ON FISHING HOME — aborting")
            (outd / "explore4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
            return 4

        # bait before, straight from the live page
        import re
        m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
        out["bait_before_text"] = m.group(0) if m else None
        out["home_text"] = txt[:500]
        print("BAIT BEFORE (as read):", out["bait_before_text"])

        # ---- enter 普通关卡 ----
        print(f"\n>>> tapping 普通关卡 at {NORMAL_STAGE}")
        tap(NORMAL_STAGE, 1.2)

        # ---- record the minigame as fast as the device allows ----
        rows: list[dict] = []
        t0 = time.monotonic()
        prev = None
        saved = 0
        i = 0
        while time.monotonic() - t0 < seconds:
            c0 = time.perf_counter()
            f = ad.capture()
            cap_ms = (time.perf_counter() - c0) * 1000.0
            if f is None:
                rows.append({"i": i, "capture_ms": round(cap_ms, 2), "null": True})
                i += 1
                continue
            s = sig(f)
            change = float(np.mean(np.abs(s - prev))) if prev is not None else None
            prev = s
            row = {"i": i, "t": round(time.monotonic() - t0, 3), "capture_ms": round(cap_ms, 2),
                   "change": round(change, 3) if change is not None else None,
                   "brightness": round(float(s.mean()), 2)}
            if i < SAVE_FIRST or (i % SAVE_EVERY == 0):
                Image.fromarray(f).save(outd / "frames" / f"f{i:04d}.png")
                row["saved"] = True
                saved += 1
            rows.append(row)
            i += 1
        dt = time.monotonic() - t0
        out["frames"] = i
        out["saved_frames"] = saved
        out["capture_hz"] = round(i / dt, 2) if dt else None
        out["capture_ms_mean"] = round(sum(r["capture_ms"] for r in rows) / len(rows), 2)
        out["rows"] = rows

        f, txt = dump("zz_after_burst", save_png=True)
        out["after_burst_text"] = txt[:600]
        (outd / "explore4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print(f"\nframes={i} saved={saved} hz={out['capture_hz']} "
              f"capture_ms_mean={out['capture_ms_mean']}")
        print("AFTER BURST:", txt[:300])
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="fishing explore4 finished")


if __name__ == "__main__":
    raise SystemExit(main())
