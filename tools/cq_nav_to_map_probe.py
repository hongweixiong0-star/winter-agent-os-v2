"""Probe NAVIGATE_TO_MAP / OPEN_MAP on the two escalation frames.

Read-only. Prints, for each frame:
  * the full WorldState the production vision returns;
  * every PAGE_MAP candidate's roi bounds, template crop and phash distance;
  * a saved annotated crop of the PAGE_MAP ROI and of the real bottom nav bar.

No device access, no clicks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from winter_agent_v2.vision import SemanticWorldVision, SemanticROIVision  # noqa: E402
from winter_agent_v2.image_hash import phash, hamming  # noqa: E402

EP = ROOT / "dataset/raw/control_panel/runtime_auto/20260918_071842_873395"
FRAMES = [
    EP / "20260918_071842_873395_step_002_before_20260917T231909587334.png",
    EP / "20260918_071842_873395_step_002_after_20260917T231921546245.png",
]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
OUT = ROOT / "dataset/truth_audit/nav_to_map_20260918"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidates = [r for r in payload["records"] if r["semantic"] == "PAGE_MAP"]
    vision = SemanticWorldVision(MANIFEST)
    roi_vision = SemanticROIVision(MANIFEST)

    report: dict = {"frames": []}
    for frame in FRAMES:
        with Image.open(frame) as im:
            w, h = im.size
        state = vision.observe(frame)
        entry = {
            "frame": frame.name,
            "size": [w, h],
            "state": {"page": state.page.value, "confidence": state.confidence,
                      "march_used": state.march_used,
                      "resource_search_open": state.resource_search_open},
            "page_map_candidates": [],
        }
        for row in candidates:
            roi = row["roi_norm"]
            bounds = (
                round(roi["x_norm"] * w),
                round(roi["y_norm"] * h),
                round((roi["x_norm"] + roi["w_norm"]) * w),
                round((roi["y_norm"] + roi["h_norm"]) * h),
            )
            with Image.open(frame) as im:
                dist = hamming(phash(im.crop(bounds)), phash(Image.open(row["template_path"])))
            entry["page_map_candidates"].append({
                "template_id": row["template_id"],
                "parent": row["parent_screenshot"],
                "roi_norm": roi,
                "bounds": bounds,
                "center_px": [round((bounds[0] + bounds[2]) / 2), round((bounds[1] + bounds[3]) / 2)],
                "distance": dist,
                "threshold": roi_vision.semantic_max_distance.get("PAGE_MAP", roi_vision.max_distance),
            })
            # save the exact crop the matcher compares
            with Image.open(frame) as im:
                im.crop(bounds).save(OUT / f"{frame.stem}__{row['template_id']}__crop.png")
        match = roi_vision.find(frame, "PAGE_MAP")
        entry["find_result"] = None if match is None else {
            "distance": match.distance,
            "roi": match.roi,
            "center_norm": match.center_norm,
            "center_px": [round(match.center_norm[0] * w), round(match.center_norm[1] * h)],
        }
        # Annotate: PAGE_MAP rois in red, the realized bottom nav bar band in green.
        with Image.open(frame).convert("RGB") as im:
            draw = ImageDraw.Draw(im)
            for row in candidates:
                roi = row["roi_norm"]
                draw.rectangle(
                    [round(roi["x_norm"] * w), round(roi["y_norm"] * h),
                     round((roi["x_norm"] + roi["w_norm"]) * w),
                     round((roi["y_norm"] + roi["h_norm"]) * h)],
                    outline=(255, 0, 0), width=3,
                )
            draw.rectangle([0, round(0.82 * h), w, h], outline=(0, 255, 0), width=2)
            im.save(OUT / f"{frame.stem}__annotated.png")
        report["frames"].append(entry)

    (OUT / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
