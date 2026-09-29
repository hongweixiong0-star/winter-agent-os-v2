# -*- coding: utf-8 -*-
"""Live exploration round 5: advance the LIVE fishing run and record the mechanics.

Round 4 entered 普通关卡 and found the run sitting in a TUTORIAL state: a large hand
sprite points at a glowing circle on the ice, waiting for a tap.  The screen was
otherwise static, which is why the burst recorded near-zero change.

This script taps that spot and records what happens next at full frame rate,
saving every frame whose scene change exceeds a threshold (the transition frames
are the ones the detector has to survive) plus a regular sample.

usage: python tools/fishing_explore5.py [seconds] [x] [y]
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

TUTORIAL_TAP = (357, 632)
CHANGE_SAVE_THRESHOLD = 2.5


def sig(f: np.ndarray) -> np.ndarray:
    h, w = f.shape[:2]
    ys = np.linspace(0, h - 1, 48).astype(int)
    xs = np.linspace(0, w - 1, 48).astype(int)
    s = f[ys][:, xs]
    return (s.mean(axis=2) if s.ndim == 3 else s).astype(np.float32)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 14.0
    tx = int(sys.argv[2]) if len(sys.argv) > 2 else TUTORIAL_TAP[0]
    ty = int(sys.argv[3]) if len(sys.argv) > 3 else TUTORIAL_TAP[1]

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "raw" / "fishing_tournament" / f"explore5_{stamp}"
    (outd / "key_frames").mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISHING_EXPLORE5", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=600, reason="advance the live fishing run and record it")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT)), "tap": [tx, ty]}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3

        f = ad.capture()
        Image.fromarray(f).save(outd / "00_before_tap.png")
        before_txt = " ".join(t["text"] for t in read_all(Image.fromarray(f)))
        out["before_tap_text"] = before_txt[:300]
        print("BEFORE TAP:", before_txt[:200])

        if tx > 0 and ty > 0:
            print(f">>> tapping ({tx},{ty})")
            ad.click(tx, ty)
        else:
            print(">>> passive recording (no tap)")

        rows: list[dict] = []
        t0 = time.monotonic()
        prev = sig(f)
        i = 0
        last_key = None
        while time.monotonic() - t0 < seconds:
            c0 = time.perf_counter()
            fr = ad.capture()
            cap_ms = (time.perf_counter() - c0) * 1000.0
            if fr is None:
                i += 1
                continue
            s = sig(fr)
            change = float(np.mean(np.abs(s - prev)))
            prev = s
            row = {"i": i, "t": round(time.monotonic() - t0, 3), "change": round(change, 3),
                   "brightness": round(float(s.mean()), 2), "capture_ms": round(cap_ms, 2)}
            key = change >= CHANGE_SAVE_THRESHOLD
            if key:
                name = f"key_{i:04d}.png"
                Image.fromarray(fr).save(outd / "key_frames" / name)
                row["key"] = name
                last_key = fr
            rows.append(row)
            i += 1
        dt = time.monotonic() - t0
        out["frames"] = i
        out["hz"] = round(i / dt, 2) if dt else None
        out["key_frames"] = sum(1 for r in rows if r.get("key"))
        out["rows"] = rows
        out["change_profile"] = [{"i": r["i"], "t": r["t"], "change": r["change"]}
                                 for r in rows[::20]]

        fr = ad.capture()
        Image.fromarray(fr).save(outd / "zz_after.png")
        after_txt = " ".join(t["text"] for t in read_all(Image.fromarray(fr)))
        out["after_text"] = after_txt[:600]
        (outd / "explore5.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print(f"\nframes={i} hz={out['hz']} key_frames={out['key_frames']}")
        print("AFTER:", after_txt[:400])
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="fishing explore5 finished")


if __name__ == "__main__":
    raise SystemExit(main())
