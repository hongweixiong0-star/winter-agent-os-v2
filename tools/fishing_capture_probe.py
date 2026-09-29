# -*- coding: utf-8 -*-
"""Decisive experiment: can MAA's fast screencap see the fishing dive at all?

Round 5 recorded the fishing run and found a suspicious pattern:

    t=0.4 .. 10.0 s   cutscene, brightness ~102, animating
    t=10.25 .. 12.45  brightness 13.2, change EXACTLY 0.00 for ~2.3 s   <- black
    t=12.9 s          result page, brightness ~142

A frozen, pixel-identical dark screen where the actual dive gameplay should be is
the classic signature of a video/cinematic surface that the fast (EmulatorExtras)
screencap path cannot read.  If that is what is happening, a visual servo built on
that channel would be steering a game it cannot see, and the fix is a different
capture method — not a better detector.

So this script runs one more level and captures BOTH channels at the same instant:

    MAA  post_screencap  (EmulatorExtras, ~12 ms, the fast path)
    ADB  exec-out screencap -p  (full framebuffer, ~250 ms, the slow path)

and reports, per sample, the brightness of each.  Where they disagree, the fast
path is blind and both frames are saved as evidence.

Costs one bait.  Results decide the capture strategy for PHASE 5+.

usage: python tools/fishing_capture_probe.py [seconds]
"""

from __future__ import annotations

import json
import subprocess
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


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 55.0
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "raw" / "fishing_tournament" / f"capture_probe_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISH_CAPTURE_PROBE", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=600, reason="compare screencap channels during the dive")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    adb = cfg["device"]["adb_path"]
    serial = cfg["device"]["serial"]

    def adb_frame():
        """Full-framebuffer capture, bypassing MAA entirely."""
        try:
            raw = subprocess.run([adb, "-s", serial, "exec-out", "screencap", "-p"],
                                 capture_output=True, timeout=15)
        except Exception as exc:  # noqa: BLE001
            return None, f"ADB_EXC:{type(exc).__name__}"
        if raw.returncode != 0 or len(raw.stdout) < 1024:
            return None, f"ADB_RC={raw.returncode} bytes={len(raw.stdout)}"
        import io
        try:
            img = Image.open(io.BytesIO(raw.stdout)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            return None, f"ADB_DECODE:{type(exc).__name__}"
        return np.asarray(img), ""

    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT))}
    try:
        ad = MaaExecutorAdapter(adb_path=adb, serial=serial, production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3
        out["negotiated"] = ad.negotiated

        def maa_frame():
            f = ad.capture()
            return (None, "NULL") if f is None else (f, "")

        def txt_of(f):
            return " ".join(t["text"] for t in read_all(Image.fromarray(f)))

        # ---- 0. start from wherever we are; make sure we are on the result page or home ----
        f, _ = maa_frame()
        t = txt_of(f)
        Image.fromarray(f).save(outd / "00_start.png")
        print("START:", t[:200])

        if "本次收获" in t:
            hit = [x for x in read_all(Image.fromarray(f)) if "退出" in x["text"]]
            if hit:
                ad.click(*hit[0]["centre"])
                time.sleep(2.2)
                f, _ = maa_frame()
                t = txt_of(f)
                print("after 退出:", t[:160])
        if "普通关卡" not in t:
            # try to find our way to the fishing home
            hit = [x for x in read_all(Image.fromarray(f)) if "钓鱼锦标赛" in x["text"]]
            if hit:
                ad.click(*hit[0]["centre"])
                time.sleep(2.4)
                f, _ = maa_frame()
                t = txt_of(f)
        if "普通关卡" not in t:
            print("NOT ON FISHING HOME:", t[:200])
            (outd / "probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
            return 4

        print(">>> entering 普通关卡")
        ad.click(*NORMAL_STAGE)
        time.sleep(2.0)
        print(f">>> tapping the tutorial circle {TUTORIAL_TAP}")
        ad.click(*TUTORIAL_TAP)

        # ---- dual-channel sampling ----
        rows: list[dict] = []
        t0 = time.monotonic()
        i = 0
        saved_pairs = 0
        while time.monotonic() - t0 < seconds:
            mf, mreason = maa_frame()
            m_bri = round(float(np.asarray(mf).mean()), 2) if mf is not None else None
            af, areason = adb_frame()
            a_bri = round(float(np.asarray(af).mean()), 2) if af is not None else None
            disagree = (m_bri is not None and a_bri is not None and abs(m_bri - a_bri) > 25)
            row = {"i": i, "t": round(time.monotonic() - t0, 2),
                   "maa_bri": m_bri, "adb_bri": a_bri,
                   "maa_err": mreason or None, "adb_err": areason or None,
                   "disagree": disagree}
            if disagree and saved_pairs < 12:
                Image.fromarray(mf).save(outd / f"pair{saved_pairs:02d}_maa.png")
                Image.fromarray(af).save(outd / f"pair{saved_pairs:02d}_adb.png")
                saved_pairs += 1
                row["pair"] = saved_pairs - 1
            rows.append(row)
            if i % 5 == 0:
                print(f"  t={row['t']:6.2f} maa={m_bri} adb={a_bri} "
                      f"{'DISAGREE' if disagree else ''}")
            # stop once the result page is on the MAA channel
            if mf is not None and i % 5 == 0 and "本次收获" in txt_of(mf):
                print("  RESULT PAGE reached")
                break
            i += 1

        out["samples"] = rows
        out["disagreements"] = sum(1 for r in rows if r["disagree"])
        out["saved_pairs"] = saved_pairs
        out["maa_min_bri"] = min((r["maa_bri"] for r in rows if r["maa_bri"] is not None),
                                 default=None)
        out["adb_min_bri"] = min((r["adb_bri"] for r in rows if r["adb_bri"] is not None),
                                 default=None)
        f, _ = maa_frame()
        Image.fromarray(f).save(outd / "99_end_maa.png")
        out["end_text"] = txt_of(f)[:400]
        (outd / "probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        print(f"\nsamples={len(rows)} disagreements={out['disagreements']} "
              f"saved_pairs={saved_pairs}")
        print(f"maa_min_bri={out['maa_min_bri']} adb_min_bri={out['adb_min_bri']}")
        print("END:", out["end_text"][:200])
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="capture probe finished")


if __name__ == "__main__":
    raise SystemExit(main())
