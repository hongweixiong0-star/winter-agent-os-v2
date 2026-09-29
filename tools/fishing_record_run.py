# -*- coding: utf-8 -*-
"""Dense recording of one whole fishing level, with nothing else in the loop.

The previous probe sampled only 21 times across a whole level because it called
the full-screen OCR inside the capture loop (seconds per call).  This one does
NOTHING in the loop except capture: brightness and change are computed on the
already-downsampled signature, and every Nth frame is written to disk.

That produces a continuous timeline of the level, which is what is needed to find
out where the dive actually is and what has to be detected in it.

usage: python tools/fishing_record_run.py [seconds] [save_every]
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

NORMAL_STAGE = (500, 1170)
TUTORIAL_TAP = (357, 632)


def sig(f: np.ndarray, n: int = 48) -> np.ndarray:
    h, w = f.shape[:2]
    ys = np.linspace(0, h - 1, n).astype(int)
    xs = np.linspace(0, w - 1, n).astype(int)
    s = f[ys][:, xs]
    return (s.mean(axis=2) if s.ndim == 3 else s).astype(np.float32)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    save_every = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "raw" / "fishing_tournament" / f"run_{stamp}"
    (outd / "frames").mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISH_RECORD", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=700, reason="dense recording of one fishing level")
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

        def txt_of(f):
            return " ".join(t["text"] for t in read_all(Image.fromarray(f)))

        f = ad.capture()
        t = txt_of(f)
        out["before_text"] = t[:300]
        print("BEFORE:", t[:180])

        # exit the old result page if needed
        if "本次收获" in t:
            hit = [x for x in read_all(Image.fromarray(f)) if "退出" in x["text"]]
            if hit:
                ad.click(*hit[0]["centre"])
                time.sleep(2.2)
                f = ad.capture()
                t = txt_of(f)
        if "普通关卡" not in t:
            hit = [x for x in read_all(Image.fromarray(f)) if "钓鱼锦标赛" in x["text"]]
            if hit:
                ad.click(*hit[0]["centre"])
                time.sleep(2.4)
                f = ad.capture()
                t = txt_of(f)
        if "普通关卡" not in t:
            print("NOT ON FISHING HOME:", t[:200])
            return 4
        Image.fromarray(f).save(outd / "00_home.png")
        out["home_text"] = t[:400]

        print(">>> entering 普通关卡, then the tutorial tap")
        ad.click(*NORMAL_STAGE)
        time.sleep(2.0)
        ad.click(*TUTORIAL_TAP)
        # a second tap in case the tutorial has a second step
        time.sleep(0.8)
        ad.click(*TUTORIAL_TAP)

        rows: list[dict] = []
        t0 = time.monotonic()
        prev = None
        i = 0
        saved = 0
        while time.monotonic() - t0 < seconds:
            c0 = time.perf_counter()
            fr = ad.capture()
            cap_ms = (time.perf_counter() - c0) * 1000.0
            if fr is None:
                i += 1
                continue
            s = sig(fr)
            change = float(np.mean(np.abs(s - prev))) if prev is not None else None
            prev = s
            rows.append({"i": i, "t": round(time.monotonic() - t0, 3),
                         "change": round(change, 3) if change is not None else None,
                         "bri": round(float(s.mean()), 2), "cap_ms": round(cap_ms, 2)})
            if i % save_every == 0:
                name = f"f{i:05d}.png"
                Image.fromarray(fr).save(outd / "frames" / name)
                rows[-1]["saved"] = name
                saved += 1
            i += 1
        dt = time.monotonic() - t0
        out["frames"] = i
        out["saved"] = saved
        out["hz"] = round(i / dt, 2) if dt else None
        out["rows"] = rows
        fr = ad.capture()
        Image.fromarray(fr).save(outd / "99_end.png")
        out["end_text"] = txt_of(fr)[:500]
        (outd / "run.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        print(f"\nframes={i} saved={saved} hz={out['hz']}")
        print("END:", out["end_text"][:250])
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="fishing record finished")


if __name__ == "__main__":
    raise SystemExit(main())
