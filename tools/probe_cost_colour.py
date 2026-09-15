"""Measure whether a stamina cost rendered in red means "you cannot afford this".

Why this exists
---------------
Measured live 2026-09-15T04:11:16Z: ``DISPATCH_INTEL_BEAST`` failed with
``SEMANTIC_TARGET_NOT_VERIFIED`` on a frame where the 出征 button is plainly
visible at its registered ROI.  The cause is not a missing control:

* the ``BTN_BEAST_DISPATCH`` template (captured from
  ``live_beast_march_selection.png``) shows 出征 with a **white** cost ``10``;
* the live frame shows the same button with the cost ``10`` rendered **red**;
* on the parent frame the template matches at distance **0** (it was cropped
  from that very ROI -- the circular-proof trap), on the live frame ``find``
  returns ``None``;
* but with the ccoeff matcher at scale 1.0 the live frame scores **0.9152**,
  so the *shape* is present and it is specifically the colour that differs.

The client appears to encode affordability in the cost's own colour: white when
the cost is payable, red when it is not.  That would be a free, OCR-free
affordability signal -- much more reliable than the HUD gauge, which reads only
19 of 25 frames and cannot read a lone ``0`` at all (see
``tools/probe_stamina_zero.py``).

This probe tests that hypothesis instead of assuming it: for every frame it can
find, count red and white pixels inside the cost-bearing button ROI and report
them next to the known stamina at that moment.

Read-only; writes nothing outside ``dataset/probe_output/``.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

# (label, frame, semantic whose ROI holds the cost, known stamina at that moment)
CASES = (
    ("dispatch / stamina 0, cost 10",
     "dataset/raw/live_zero_stamina_claim_20260915"
     "/live_zero_stamina_claim_20260915_step_007_before_20260915T041114783780.png",
     "BTN_BEAST_DISPATCH", 0),
    ("dispatch parent (template source)",
     "dataset/raw/live_beast_march_selection.png", "BTN_BEAST_DISPATCH", None),
    ("camp panel / stamina 7, cost 10",
     "dataset/truth_audit/camp_panel_stamina_gate_20260915/03_camp_panel_unaffordable_live.png",
     "BTN_HERO_CAMP_FIGHT", 7),
    ("camp panel / stamina 16, cost 10",
     "dataset/truth_audit/camp_panel_stamina_gate_20260915/01_camp_panel_stamina_read_live.png",
     "BTN_HERO_CAMP_FIGHT", 16),
    ("squad page / stamina 10, cost 10 (dispatch succeeded)",
     "dataset/raw/live_free_gift_claim_20260915"
     "/live_free_gift_claim_20260915_step_008_before_20260915T040053584071.png",
     "BTN_HERO_FIGHT", 10),
)


def is_red(pixel) -> bool:
    r, g, b = pixel[:3]
    return r > 110 and (r - g) > 45 and (r - b) > 45


def is_white(pixel) -> bool:
    r, g, b = pixel[:3]
    return r > 195 and g > 195 and b > 195


def main() -> int:
    manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    rois = {r["semantic"]: r["roi_norm"] for r in manifest["records"] if r.get("roi_norm")}
    print(f"{'case':<44} {'semantic':<22} {'red':>6} {'white':>7}  verdict")
    for label, relative, semantic, stamina in CASES:
        path = ROOT / relative
        if not path.is_file():
            print(f"{label:<44} {semantic:<22} MISSING {path}")
            continue
        roi = rois.get(semantic)
        if roi is None:
            print(f"{label:<44} {semantic:<22} no ROI registered")
            continue
        with Image.open(path) as source:
            image = source.convert("RGB")
        x0 = int(roi["x_norm"] * image.width)
        y0 = int(roi["y_norm"] * image.height)
        x1 = int((roi["x_norm"] + roi["w_norm"]) * image.width)
        y1 = int((roi["y_norm"] + roi["h_norm"]) * image.height)
        crop = image.crop((x0, y0, x1, y1))
        # The cost sits to the right of the label in every one of these rows.
        right = crop.crop((crop.width // 2, 0, crop.width, crop.height))
        red = sum(1 for pixel in right.getdata() if is_red(pixel))
        white = sum(1 for pixel in right.getdata() if is_white(pixel))
        verdict = "RED=blocked" if red > white else ("white=affordable" if white else "no digits")
        print(f"{label:<44} {semantic:<22} {red:>6} {white:>7}  {verdict}"
              + (f"   (stamina={stamina})" if stamina is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
