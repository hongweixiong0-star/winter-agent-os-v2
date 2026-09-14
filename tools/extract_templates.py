"""Extract candidate templates from reviewed normalized replay ROIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def roi_pixels(roi: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    x = round(float(roi["x_norm"]) * width)
    y = round(float(roi["y_norm"]) * height)
    w = round(float(roi["w_norm"]) * width)
    h = round(float(roi["h_norm"]) * height)
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError(f"ROI outside image: {(x, y, w, h)} / {(width, height)}")
    return x, y, x + w, y + h


def extract(labels_path: Path, output_dir: Path) -> dict:
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if payload.get("status") != "SIMULATION":
        raise ValueError("labels must be SIMULATION candidates")
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for sample in payload.get("samples", []):
        image_path = (labels_path.parent / sample["image"]).resolve()
        parent_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
        with Image.open(image_path) as image:
            for index, element in enumerate(sample.get("elements", [])):
                bounds = roi_pixels(element["roi"], *image.size)
                # Capture folders commonly reuse names such as
                # ``step_001_before.png``. Include the parent screenshot hash
                # so one reviewed live sample can never overwrite another.
                name = f"{safe_name(element['semantic'])}__{safe_name(image_path.stem)}__{parent_sha[:8]}__{index}.png"
                target = output_dir / name
                image.crop(bounds).save(target, format="PNG")
                records.append({
                    "template_id":target.stem,
                    "semantic":element["semantic"],
                    "status":"CANDIDATE",
                    "template_path":target.as_posix(),
                    "parent_screenshot":image_path.as_posix(),
                    "parent_sha256":parent_sha,
                    "roi_norm":element["roi"],
                    "width":bounds[2]-bounds[0],
                    "height":bounds[3]-bounds[1],
                    "confidence":float(element.get("confidence", 0.0)),
                    "source":"REPLAY_HUMAN_REVIEWED_SCREENSHOT",
                })
    return {"schema_version":"1.0","generated_at":datetime.now(timezone.utc).isoformat(),"status":"CANDIDATE","count":len(records),"records":records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = extract(args.labels.resolve(), args.output_dir.resolve())
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"CANDIDATE":manifest["count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
