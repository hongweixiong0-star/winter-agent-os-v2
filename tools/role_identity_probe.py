"""Find where the client shows *which role is logged in*.

Why this exists
---------------
The operator's product definition (2026-09-16) makes role identity a
precondition, not a nicety: "它登录到哪个角色 → 识别当前角色 → 读取当前角色的发展
状态".  The project has no role concept at all, and the corpus has already been
built from at least two different accounts (see `docs/ROLE_SCOPED_CAPABILITY_AUDIT.md`
and the two frames it cites: 70,206,322 power / 6 march slots on 2026-09-14 vs
542,443 power / 2 march slots on 2026-09-16).  Every historical metric that pools
them is therefore un-scoped.

The top-left HUD was measured first and carries no name: it shows the avatar
portrait, power, stamina, the alliance rank (统帅N) and the date.  So identity has
to come from a panel, and the canonical one is the profile panel behind the
avatar.

Bounds (deliberate, and the reason this is safe to run)
-------------------------------------------------------
* Read the current page first and refuse to act unless it is HOME or MAP.  An
  unknown page already deserves recovery, not a blind tap.
* Exactly ONE tap, on the avatar.  Nothing inside the resulting panel is ever
  tapped -- that panel leads to account settings, and `config.risk.
  block_account_or_role_delete` exists precisely because that is dangerous.
* If the outcome does not classify as a known page, press Back once and verify
  the return.  A bounded, self-recovering exploration rather than an open one.

Writes: dataset/raw/role_identity/<stamp>/
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.models import Page
from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.vision import SemanticWorldVision

W, H = 720, 1280

# Measured, not guessed: the avatar's rounded frame occupies x 5-88, y 8-95 on a
# 720x1280 frame (4x crop in out_crop_role/avatar_zoom.png).  The red-dot badge
# sits at its top-right corner, so the tap goes to the centre.
AVATAR_CENTRE = (47, 51)


def main() -> int:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "dataset/raw/role_identity" / stamp
    out.mkdir(parents=True, exist_ok=True)
    print("out:", out)

    log: list[dict] = []

    def shot(label: str):
        path = out / f"{stamp}_{label}.png"
        device.screenshot(path)
        state = vision.observe(path)
        entry = {
            "label": label,
            "file": path.name,
            "page": state.page.value,
            "confidence": round(state.confidence, 3),
            "march_used": state.march_used,
            "march_max": state.march_max,
        }
        log.append(entry)
        print("  {:<24s} page={:<12s} conf={:.2f} march={}/{}".format(
            label, state.page.value, state.confidence, state.march_used, state.march_max))
        return path, state

    print("\n== step 0: read the current page ==")
    before_path, before = shot("00_before")
    if before.page not in {Page.HOME, Page.MAP}:
        print("\nABORT: the client is on {} ({}), which is not a page this probe may act from.".format(
            before.page.value, before.confidence))
        (out / "probe.json").write_text(
            json.dumps({"aborted": "page not HOME/MAP", "log": log}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 2

    print("\n== step 1: one tap on the avatar ({}), nothing else ==".format(AVATAR_CENTRE))
    device.tap(*AVATAR_CENTRE)
    time.sleep(2.5)
    after_path, after = shot("01_after_avatar_tap")

    print("\n== step 2: what does that frame say? (production OCR, conf >= 0.80) ==")
    result = ocr.recognize(after_path)
    tokens = [(t.text.strip(), round(t.confidence, 3), t.box) for t in result.tokens if t.confidence >= 0.80]
    named = []
    for text, conf, box in tokens:
        cx = cy = None
        if box:
            cx = round((box[0][0] + box[2][0]) / 2 / W, 4)
            cy = round((box[0][1] + box[2][1]) / 2 / H, 4)
        print("    {!r:<28} conf={:<6} centre=({}, {})".format(text, conf, cx, cy))
        # The profile panel's identity row is a proper name: CJK or mixed
        # alphanumerics.  Everything else on the panel is a label or a number.
        if text and not text.isdigit() and not text.replace(",", "").isdigit():
            named.append({"text": text, "confidence": conf, "centre_norm": [cx, cy]})
    (out / "ocr_tokens.json").write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")

    recovered = None
    if after.page in {Page.UNKNOWN, Page.LOADING, Page.MAINTENANCE}:
        print("\n== step 3: unclassified result -> one bounded Back, then re-observe ==")
        device.press_back()
        time.sleep(2.5)
        _, back_state = shot("02_after_back")
        recovered = back_state.page.value

    summary = {
        "stamp": stamp,
        "avatar_centre_px": AVATAR_CENTRE,
        "before": {"page": before.page.value, "confidence": round(before.confidence, 3)},
        "after": {"page": after.page.value, "confidence": round(after.confidence, 3)},
        "after_back_page": recovered,
        "candidate_identity_tokens": named,
        "log": log,
    }
    (out / "probe.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwritten", out / "probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
