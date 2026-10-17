# -*- coding: utf-8 -*-
"""JOIN_RALLY via city banner, round 4: go home via 城镇 nav button, not back."""
import json, re, sys, time
from pathlib import Path
from PIL import Image
import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from datetime import datetime
    STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset/evidence" / f"rally_banner2_{STAMP}"
    outd.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_BANNER_JOIN2", capability_id="RALLY_ENGINE",
                             ttl_seconds=480, reason="banner route round4")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False)); return 2
    out = {"flow": "JOIN_RALLY", "target_type": "ICEFIELD_BEAST", "route": "city_banner_r4"}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ad.ensure_ready()
        def frame(retries=4):
            for _ in range(retries):
                f = ad.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(0.8)
        def toks(img): return _rapid_ocr_results(np.asarray(img), None, [])
        def text(img): return " ".join(t["text"] for t in toks(img))
        def save(img, tag): img.save(outd / f"{tag}.png")
        def tap(x, y, w=1.6):
            ad.click(int(x), int(y)); time.sleep(w)
        def tokbox(t):
            b = t.get("box") or ()
            if len(b) == 4: return int(b[0] + b[2]) // 2, int(b[1] + b[3]) // 2
        def tap_tok(img, needle, w=2.0, exact=False):
            cs = [t for t in toks(img) if (t["text"].strip() == needle if exact else needle in t["text"])]
            if not cs: return False
            t = max(cs, key=lambda k: (k.get("box") or (0, 0, 0, 0))[1])
            c = tokbox(t)
            if c: tap(*c, w); return True
            return False
        def guard(f):
            t = text(f)
            if "退出游戏" in t:
                tap_tok(f, "取消", w=1.5, exact=True); return True
            if any(w in t for w in ("￥", "支付", "购买", "礼包", "祝贺你", "超越传说", "离线收益", "欢迎回来")):
                cs = [tt for tt in toks(f) if tt["text"].strip() in ("取消", "关闭")]
                if cs:
                    c = tokbox(cs[0])
                    if c: tap(*c, 1.5)
                else:
                    ad.press_back(); time.sleep(1.2)
                return True
            return False
        def at_city(f):
            t = text(f)
            if "退出游戏" in t: return False
            return "统帅" in t or ("背包" in t and "城镇" in t)
        def go_home(maxn=6):
            for _ in range(maxn):
                f = frame()
                if f is None: continue
                if guard(f): continue
                if at_city(f): return True
                # bottom nav 城镇 (rightmost); fallback fixed coords
                if not tap_tok(f, "城镇", w=2.2, exact=True):
                    tap(593, 1243, 2.2)
            return False
        BEAST = ("避役", "雪豹", "猛犸", "巨兽", "野兽", "犀牛", "棕熊", "麋鹿", "霜鳞", "冰原", "巨型")
        if not go_home():
            out["error"] = "cannot reach city"
            print(json.dumps(out, ensure_ascii=False)); return 1
        deadline = time.time() + 300; joined = False; rounds = 0; banner_seen = 0
        while time.time() < deadline and not joined:
            rounds += 1
            f = frame()
            if f is None: continue
            if guard(f): continue
            if not at_city(f):
                go_home(); continue
            t = text(f)
            save(f, f"city_{rounds:02d}")
            if "集结中" not in t:
                time.sleep(8); continue
            banner_seen += 1
            if not tap_tok(f, "集结中", w=2.5, exact=True):
                time.sleep(6); continue
            f = frame(); save(f, f"detail_{rounds:02d}")
            if guard(f): continue
            dt = text(f)
            out.setdefault("details", []).append(dt[:220])
            is_beast = any(w in dt for w in BEAST) and "巨熊" not in dt
            out["last_kind"] = "BEAST" if is_beast else "OTHER"
            if not is_beast:
                tap_tok(f, "关闭", w=1.5) or ad.press_back(); time.sleep(1.5); time.sleep(6); continue
            bgr = np.asarray(f.convert("RGB"))[:, :, ::-1].copy()
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (35, 120, 120), (85, 255, 255))
            band = mask[300:700, 380:720]
            ys, xs = np.nonzero(band)
            out["green"] = int(len(xs))
            if len(xs) < 60:
                ad.press_back(); time.sleep(6); continue
            cy = int(np.mean(ys)) + 300; cx = int(np.mean(xs)) + 380
            out["join_centre"] = (cx, cy)
            tap(cx, cy, 2.5)
            for i in range(5):
                df = frame()
                if df is None: continue
                save(df, f"dial_{i}")
                if guard(df): break
                if not any(tap_tok(df, w2, w=2.0, exact=(w2 == "出征")) for w2 in ("出征", "立即加入", "确定", "加入")):
                    break
            time.sleep(6)
            vf = frame(); save(vf, "after")
            at = text(vf); out["after_text"] = at[:200]
            joined = "xhw" in at or "已抵达" in at
            if not joined:
                ad.press_back(); time.sleep(6)
        out["joined_seen"] = joined; out["rounds"] = rounds; out["banner_seen"] = banner_seen
        go_home()
        time.sleep(1); f = frame(); save(f, "city_final")
        m = re.search(r"行军\s*(\d)\s*/\s*(\d)", text(f))
        out["march_final"] = m.group(0) if m else None
        out["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="banner r4 done")

if __name__ == "__main__":
    raise SystemExit(main())
