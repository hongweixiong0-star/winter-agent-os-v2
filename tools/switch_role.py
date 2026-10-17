# -*- coding: utf-8 -*-
"""Switch to the role whose name contains KEY (argv[1]). Reuses proven chain."""
import json, re, sys, time
from pathlib import Path
from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    key = sys.argv[1]
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=f"DEVICE_SWITCH_{key}", capability_id="ROLE_SWITCH",
                             ttl_seconds=420, reason=f"switch to role {key}")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False)); return 2
    out = {"target": key}
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
        def tap(x, y, w=2.0):
            ad.click(int(x), int(y)); time.sleep(w)
        def tap_tok(img, needle, w=2.5, exact=False):
            cs = [t for t in toks(img) if (t["text"].strip() == needle if exact else needle in t["text"])]
            if not cs: return False
            t = max(cs, key=lambda k: (k.get("box") or (0, 0, 0, 0))[1])
            b = t.get("box") or ()
            if len(b) == 4:
                tap(int(b[0] + b[2]) // 2, int(b[1] + b[3]) // 2, w); return True
            return False
        def back_to_city():
            for _ in range(8):
                f = frame()
                if f is None: continue
                t = text(f)
                if "退出游戏" in t:
                    tap_tok(f, "取消", w=1.5, exact=True); continue
                if "统帅" in t and ("背包" in t or "城镇" in t or "野外" in t):
                    return f
                ad.press_back(); time.sleep(1.4)
            return frame()
        def popups(n=4):
            for _ in range(n):
                f = frame()
                t = text(f)
                if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益", "祝贺你")):
                    tap_tok(f, "确定", w=1.5) or tap_tok(f, "确认", w=1.5)
                    time.sleep(1.0)
                else:
                    break
        def profile_name():
            f = back_to_city()
            popups()
            f = back_to_city()
            tap(44, 44, 3.0)
            f = frame()
            name = None
            for tk in toks(f):
                m = re.search(r"\[[A-Za-z0-9]+\]\S+", tk["text"])
                if m and "分享" not in tk["text"] and "布局" not in tk["text"]:
                    name = m.group(0); break
            back_to_city()
            return name
        cur = profile_name()
        out["current_role"] = cur
        if cur and key in cur:
            out["action"] = "already"
        else:
            popups(); back_to_city()
            tap(44, 44, 3.0)
            f = frame()
            if "领主档案" not in text(f):
                popups(); tap(44, 44, 3.0); f = frame()
            if not tap_tok(f, "设置"):
                try:
                    ad.swipe(360, 1000, 360, 800)
                except Exception:
                    pass
                time.sleep(1.5); f = frame(); tap_tok(f, "设置")
            # verified geometry (720x1280): profile 设置 gear at (627,1250)
            reached = False
            for _ in range(3):
                f = frame()
                if "角色管理" in text(f):
                    reached = True
                    break
                if not tap_tok(f, "设置", w=2.5):
                    ad.click(627, 1250); time.sleep(2.5)
            f = frame()
            out["settings_ok"] = reached
            # settings 角色管理 entry at (222,338) on 720x1280; token fallback
            if not tap_tok(f, "角色管理", w=3.0):
                ad.click(222, 338); time.sleep(3.0)
                f = frame()
                if "角色管理" not in text(f) and "大熔炉" not in text(f):
                    try:
                        ad.swipe(360, 900, 360, 700)
                    except Exception:
                        pass
                    time.sleep(1.5); f = frame(); tap_tok(f, "角色管理", w=3.0)
            f = frame()
            try:
                f.save(ROOT / "learning" / "switch_roles_page.png")
            except Exception:
                pass
            roles = text(f)
            out["roles_page"] = roles[:200]
            if key not in roles:
                # role rows may scroll: swipe up and re-check
                try:
                    ad.swipe(360, 950, 360, 650)
                except Exception:
                    pass
                time.sleep(1.5)
                f = frame()
                roles = text(f)
                out["roles_page_scrolled"] = roles[:200]
            if key not in roles:
                out["error"] = "target role row not found"
            else:
                if tap_tok(f, key, w=3.0):
                    f = frame()
                    if not tap_tok(f, "确认", w=3.0):
                        tap_tok(f, "确定", w=3.0)
                    t0 = time.time()
                    while time.time() - t0 < 120:
                        f = frame()
                        if f is None: time.sleep(3); continue
                        t = text(f)
                        if "统帅" in t and ("常规活动" in t or "背包" in t or "城镇" in t):
                            break
                        if any(w in t for w in ("确定", "确认")) and "退出游戏" not in t:
                            tap_tok(f, "确定", w=2.0) or tap_tok(f, "确认", w=2.0)
                        time.sleep(3)
                    final = profile_name()
                    out["verified_role"] = final
                    out["switched"] = bool(final and key in final)
                else:
                    out["error"] = "role row tap failed"
        print(json.dumps(out, ensure_ascii=False, indent=1))
        (ROOT / "learning" / f"switch_role_{key}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    finally:
        lease.release(result="DONE", reason="switch done")

if __name__ == "__main__":
    raise SystemExit(main())
