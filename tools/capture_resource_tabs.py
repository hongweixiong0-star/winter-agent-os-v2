"""Select the remaining resource tabs on the live client and capture each cell.

Geometry already measured from the same strip: pitch ~157.3 px, cell width 144 px.
In the current scroll state WOOD's bracket left sits at x=244.5, so
MEAT=87.2, WOOD=244.5, COAL=401.8, IRON=559.1.  Tapping a cell centre is what
selects it; the capture names the frame by the tab we intended to hit and the
bracket read-back confirms where the selection actually landed.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
device.resolve_connection()

BAND = (0.672, 0.789)
BAND_Y = (BAND[0] + BAND[1]) / 2
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / "dataset/truth_audit" / f"resource_cells_{stamp}"
out.mkdir(parents=True, exist_ok=True)
print("out:", out)


def strokes(path: Path, thr: int = 238) -> list[tuple[float, int]]:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        y0, y1 = round(BAND[0] * h), round(BAND[1] * h)
        counts = []
        for x in range(w):
            c = 0
            for y in range(y0, y1):
                r, g, b = im.getpixel((x, y))
                if r >= thr and g >= thr and b >= thr:
                    c += 1
            counts.append(c)
    bandh = y1 - y0
    groups = []
    cur = None
    for x, c in enumerate(counts):
        if c >= 0.18 * bandh:
            cur = [x, x, c] if cur is None else [cur[0], x, max(cur[2], c)]
        else:
            if cur:
                groups.append(tuple(cur))
                cur = None
    if cur:
        groups.append(tuple(cur))
    return [((a + b) / 2, b - a + 1) for a, b, _ in groups]


def bracket(path: Path) -> tuple[float, float] | None:
    cand = [s for s in strokes(path) if s[1] >= 3]
    for i, (a, _) in enumerate(cand):
        for b, _ in cand[i + 1:]:
            if 130 <= b - a <= 175:
                return (a, b)
    return None


step = 0


def capture(label: str) -> Path:
    global step
    step += 1
    p = out / f"{stamp}_c_{step:03d}_{label}.png"
    device.screenshot(p)
    br = bracket(p)
    print(f"  {p.name}  bracket={br}")
    return p


def tap(x_norm: float) -> None:
    device.tap(round(x_norm * 720), round(BAND_Y * 1280))


print("\n== current state ==")
p = capture("current")
br = bracket(p)
if br is None:
    print("!! no bracket found; is the search panel open?")
    raise SystemExit(1)

left0 = br[0]
PITCH = 157.3
CELL = 144.0
print(f"anchor left={left0}")

# In this layout WOOD is anchored at 244.5 (measured); derive the offset from it.
NOMINAL_WOOD_LEFT = 244.5
offset = left0 - NOMINAL_WOOD_LEFT
NOMINAL = {"MEAT": 87.2, "WOOD": 244.5, "COAL": 401.8, "IRON": 559.1}

for res in ("MEAT", "WOOD", "COAL", "IRON"):
    left = NOMINAL[res] + offset
    centre = left + CELL / 2
    if not (0.03 <= centre / 720 <= 0.97):
        print(f"  {res}: cell centre {centre:.0f}px off-screen, skipping")
        continue
    print(f"\n== tap {res} at {centre:.0f}px ({centre/720:.4f}) ==")
    tap(centre / 720)
    time.sleep(1.5)
    capture(f"select_{res}")

(out / "geometry.json").write_text(json.dumps(
    {"stamp": stamp, "pitch": PITCH, "cell": CELL, "nominal": NOMINAL, "anchor_left": left0},
    ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwritten", out / "geometry.json")
