# -*- coding: utf-8 -*-
"""BEAR_FAST_DRY_RUN -- timing probe on the live rally page, no actions sent.

Measures the per-step cost components the bear flow will pay tonight:
frame capture, full-frame OCR, page text, rally-row parse, FrameChangeProbe,
settle policy decision, and a simulated state-driven settle loop.  Nothing is
clicked; the only navigation is opening 联盟战争 -> 集结 (an empty/read-only
page for role A right now).
"""
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
EVID = ROOT / "dataset" / "evidence" / f"bear_fast_dry_run_{STAMP}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2 import settle_policy

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_BEAR_FAST_DRYRUN", capability_id="BEAR_HUNT",
        ttl_seconds=600, reason="fast-mode timing dry run, no game actions")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat()}
    try:
        # 1. static gate check
        pol = settle_policy.choose("JOIN_RALLY", goal="PARTICIPATE_BEAR",
                                   rally_list_visible=True)
        out["static_gate"] = {"policy": pol.name, "first_wait_s": pol.first_wait_s,
                              "retry_wait_s": pol.retry_wait_s}
        pol_neg = settle_policy.choose("JOIN_RALLY", goal="PARTICIPATE_BEAR",
                                       bear_status="")
        out["static_gate_without_visible_rally_or_active"] = pol_neg.name

        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()

        def shoot(path: Path) -> float:
            t0 = time.monotonic()
            f = adapter.frame()
            img = f if isinstance(f, Image.Image) else Image.fromarray(f)
            img.save(path)
            return (time.monotonic() - t0) * 1000

        def tap(x, y, wait=2.0):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        # navigate to the rally page (read-only)
        def back_to_city():
            for _ in range(8):
                f = adapter.frame()
                if f is None:
                    continue
                img = f if isinstance(f, Image.Image) else Image.fromarray(f)
                t = text(img)
                if "统帅" in t and "常规活动" in t:
                    return img
                if "退出游戏" in t:
                    for tk in toks(img):
                        if "取消" in tk["text"]:
                            bx = tk.get("box") or (0, 0, 0, 0)
                            tap(int(bx[0]) + int(bx[2]) // 2, int(bx[1]) + int(bx[3]) // 2, 1.5)
                            break
                    continue
                adapter.press_back()
                time.sleep(2.0)
            return None

        back_to_city()
        tap(511, 1243, 2.5)
        f = adapter.frame()
        img0 = f if isinstance(f, Image.Image) else Image.fromarray(f)
        joined = False
        for tk in toks(img0):
            if "联盟战争" in tk["text"]:
                bx = tk.get("box") or (0, 0, 0, 0)
                tap(int(bx[0]) + int(bx[2]) // 2, int(bx[1]) + int(bx[3]) // 2, 2.5)
                joined = True
                break
        if not joined:
            tap(246, 669, 2.5)
        f = adapter.frame()
        img = f if isinstance(f, Image.Image) else Image.fromarray(f)
        if "集结" in text(img):
            for tk in toks(img):
                if tk["text"].strip() == "集结":
                    bx = tk.get("box") or (0, 0, 0, 0)
                    tap(int(bx[0]) + int(bx[2]) // 2, int(bx[1]) + int(bx[3]) // 2, 2.5)
                    break
        else:
            for _ in range(3):
                back_to_city()
                tap(511, 1243, 2.5)
                f = adapter.frame()
                img = f if isinstance(f, Image.Image) else Image.fromarray(f)
                hit = False
                for tk in toks(img):
                    if "联盟战争" in tk["text"]:
                        bx = tk.get("box") or (0, 0, 0, 0)
                        tap(int(bx[0]) + int(bx[2]) // 2, int(bx[1]) + int(bx[3]) // 2, 2.5)
                        hit = True
                        break
                if not hit:
                    tap(246, 669, 2.5)
                f = adapter.frame()
                img = f if isinstance(f, Image.Image) else Image.fromarray(f)
                if "集结" in text(img):
                    for tk in toks(img):
                        if tk["text"].strip() == "集结":
                            bx = tk.get("box") or (0, 0, 0, 0)
                            tap(int(bx[0]) + int(bx[2]) // 2, int(bx[1]) + int(bx[3]) // 2, 2.5)
                            break
                    break
        f = adapter.frame()
        img = f if isinstance(f, Image.Image) else Image.fromarray(f)
        out["rally_page_text_head"] = text(img)[:150]

        # --- measured loop on the rally page ---
        before_path = EVID / "before.png"
        probe = None
        iterations = []
        for i in range(6):
            step: dict = {"i": i}
            step["frame_capture_ms"] = round(shoot(before_path), 1)

            t0 = time.monotonic()
            img = Image.open(before_path)
            tokens = toks(img)
            step["full_ocr_ms"] = round((time.monotonic() - t0) * 1000, 1)
            step["ocr_tokens"] = len(tokens)
            page_text = " ".join(t["text"] for t in tokens)

            t0 = time.monotonic()
            # rally-row parse proxy: locate 加入/集结 markers in tokens
            rows = [t["text"] for t in tokens if any(w in t["text"] for w in ("集结", "加入", "巨熊", "队伍"))]
            step["rally_parse_ms"] = round((time.monotonic() - t0) * 1000, 1)
            step["rally_markers"] = rows[:6]

            t0 = time.monotonic()
            p = settle_policy.choose("JOIN_RALLY", goal="PARTICIPATE_BEAR",
                                     rally_list_visible=bool(rows))
            step["policy_ms"] = round((time.monotonic() - t0) * 1000, 3)
            step["policy"] = p.name

            if probe is None:
                probe = settle_policy.FrameChangeProbe(before_path)
            after_path = EVID / f"after_{i}.png"
            settle_limit = min(3.0, 0.75) if p.name == "P0_EVENT_FAST_MODE" else 3.0
            deadline = time.monotonic() + settle_limit
            first_wait = round(min(settle_limit, p.first_wait_s) * 1000, 1)
            t0 = time.monotonic()
            time.sleep(min(settle_limit, p.first_wait_s))
            step["post_action_wait_ms"] = round((time.monotonic() - t0) * 1000, 1)
            probes = 0
            settle_total = step["post_action_wait_ms"]
            while probes < 8:
                probes += 1
                fc = shoot(after_path)
                changed, frac = probe.changed(after_path)
                settle_total += fc
                remaining = deadline - time.monotonic()
                if changed or remaining <= 0 or probes == 8:
                    break
                t0 = time.monotonic()
                time.sleep(min(p.retry_wait_s, max(remaining, 0)))
                settle_total += (time.monotonic() - t0) * 1000
            step["settle_probes"] = probes
            step["settle_total_ms"] = round(settle_total, 1)
            step["page_head"] = page_text[:120]
            iterations.append(step)
        out["iterations"] = iterations

        def avg(k):
            vals = [it[k] for it in iterations if it.get(k) is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        out["summary_avg"] = {
            "frame_capture_ms": avg("frame_capture_ms"),
            "full_ocr_ms": avg("full_ocr_ms"),
            "rally_parse_ms": avg("rally_parse_ms"),
            "policy_ms": avg("policy_ms"),
            "post_action_wait_ms": avg("post_action_wait_ms"),
            "settle_total_ms": avg("settle_total_ms"),
        }
        fast = [it for it in iterations if it["policy"] == "P0_EVENT_FAST_MODE"]
        out["fast_mode_hit_in_loop"] = len(fast)
        out["estimated_bear_step_fast_ms"] = round(
            (out["summary_avg"]["frame_capture_ms"] or 0)
            + (out["summary_avg"]["full_ocr_ms"] or 0)
            + (out["summary_avg"]["rally_parse_ms"] or 0)
            + (out["summary_avg"]["settle_total_ms"] or 0), 1)
        out["note"] = ("estimated_bear_step_fast_ms is capture+OCR+parse+settle under the "
                       "fast policy; production _observe costs more (median 15.7s single "
                       "read) because it reads queues/risk popups beyond this proxy.")

        back_to_city()
        dest = ROOT / "out" / "bear_fast_dry_run.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="dry run done")


if __name__ == "__main__":
    raise SystemExit(main())
