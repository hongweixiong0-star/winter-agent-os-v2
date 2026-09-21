"""Is the point the ledger remembers actually a control on a real frame?

The reuse branch returns a coordinate the device tapped before.  That is only safe if the
point really is on the control -- otherwise the branch converts "the template is missing"
into "tap whatever is at this pixel", which is worse than refusing.

So: take the newest production frames for the two pages involved, draw the remembered point
on them, and crop a band around it.  A human reads the crop; the probe does not claim to
recognise anything itself.

Read-only apart from writing the crops under ``out_experience_points/``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

OUT = ROOT / "out_experience_points"

#: (page, semantic) -> remembered normalized point, taken from the live ledger.
TARGETS = {
    "HOME|PAGE_MAP": (0.9236111111111112, 0.95390625),
    "MAP|BTN_OPEN_HOME": (0.9236111111111112, 0.95390625),
}

#: Which observed page a frame must report for it to be the relevant one.
WANT_PAGE = {"HOME|PAGE_MAP": "HOME", "MAP|BTN_OPEN_HOME": "MAP"}


def newest_frames() -> dict[str, Path]:
    """The newest captured frame per page, read from the episode stream's own paths."""
    found: dict[str, Path] = {}
    path = ROOT / "learning/episodes.jsonl"
    rows = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for row in reversed(rows):
        if str(row.get("execution_mode")) != "PRODUCTION":
            continue
        before = row.get("state_before") or {}
        page = str(before.get("page") or "")
        shot = Path(str(row.get("before_screenshot") or ""))
        if page and page not in found and shot.exists():
            found[page] = shot
    return found


def main() -> int:
    OUT.mkdir(exist_ok=True)
    frames = newest_frames()
    print("newest production frame per page:")
    for page, path in sorted(frames.items()):
        print(f"  {page:14} {path}")
    print()

    for key, (x_norm, y_norm) in TARGETS.items():
        page = WANT_PAGE[key]
        frame = frames.get(page)
        print(f"=== {key}  remembered ({x_norm:.4f}, {y_norm:.4f})")
        if frame is None:
            print(f"    no production frame captured on page {page}")
            continue
        image = Image.open(frame).convert("RGB")
        width, height = image.size
        x, y = round(x_norm * width), round(y_norm * height)
        print(f"    frame {frame.name}  {width}x{height}  -> pixel ({x}, {y})")

        marked = image.copy()
        draw = ImageDraw.Draw(marked)
        radius = 26
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 0, 0), width=4)
        draw.line((x - radius * 2, y, x + radius * 2, y), fill=(255, 0, 0), width=2)
        draw.line((x, y - radius * 2, x, y + radius * 2), fill=(255, 0, 0), width=2)
        out_full = OUT / f"{key.replace('|', '_')}_full.png"
        marked.save(out_full)

        band_top = max(0, y - 110)
        band_bottom = min(height, y + 110)
        band = marked.crop((max(0, x - 240), band_top, min(width, x + 240), band_bottom))
        band = band.resize((band.width * 2, band.height * 2), Image.NEAREST)
        out_band = OUT / f"{key.replace('|', '_')}_band2x.png"
        band.save(out_band)
        print(f"    wrote {out_full.name} and {out_band.name}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
