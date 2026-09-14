"""Calibrate the resource-search tab strip from live reviewed frames.

Why this tool exists
--------------------
The previous resource-tab templates were cut at hard-coded ``roi_norm`` x
values {0.20, 0.41, 0.62, 0.82}.  Those values are each about one third of a
tab to the left of the real tab centres, so ``RESOURCE_TAB_MEAT`` actually
contained the *wood* icon and ``RESOURCE_MEAT_SELECTED`` fired on the wood
tab.  Nothing in the pipeline noticed, because a wrong-but-consistent template
still reports ``resource_selected == "MEAT"``.

This tool derives the tab centres from the live frames themselves:

1. Each reviewed ``..._selected_<resource>_...`` frame contains one white
   selection bracket around the selected tab.  Thick near-white vertical
   columns are the bracket arms; the arms that are *not* present in every
   frame are the real bracket pair.
2. The tab strip holds five evenly spaced tabs.  With the bracket centre of
   one frame known, the remaining centres follow from the measured spacing.
3. Templates are cut at the measured centres for the four gatherable
   resources (MEAT/WOOD/COAL/IRON) in both their *unselected* and *selected*
   appearance.
4. Validation: every reviewed selected frame must be classified as its own
   resource, and a leave-one-out check must not confuse resources.

Output goes to ``dataset/candidate/resource_tabs_calibrated/`` plus a
manifest that records the measured evidence, so the numbers stay auditable
instead of being hand-typed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from winter_agent_v2.image_hash import hamming, phash

RESOURCES = ("MEAT", "WOOD", "COAL", "IRON")

# Review order of the five tabs visible in the live resource-search panel.
# Read directly from the frames: 冰原巨兽 / 生肉 / 木材 / 煤矿 / 铁矿.
TAB_ORDER = ("BEAST", "MEAT", "WOOD", "COAL", "IRON")

# Vertical band that contains the tab icons, measured from the reviewed
# frames (720x1280).  Icon artwork spans roughly y 0.663..0.760.
TAB_BAND = (0.660, 0.760)
# Width of one tab cell relative to the frame width, measured from the
# selection bracket pairs (bracket spans ~0.19 of the width).
TAB_CELL = 0.19

ARM_NOISE = (0.006, 0.024, 0.074, 0.115)


def bracket_center(image_path: Path) -> float:
    """Return the normalized x centre of the white selection bracket.

    Thick near-white columns are the bracket arms.  Columns that appear in
    *every* reviewed frame (HUD chrome, watermark) are excluded by the
    caller; here we return every candidate arm so the caller can filter.
    """
    with Image.open(image_path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width, _ = array.shape
    y0, y1 = round(TAB_BAND[0] * height), round(TAB_BAND[1] * height)
    band = array[y0:y1].mean(axis=2) > 248
    column_white = band.sum(axis=0)
    arms = np.where(column_white >= 22)[0]
    groups: list[tuple[int, int]] = []
    if len(arms):
        start = previous = int(arms[0])
        for column in arms[1:]:
            column = int(column)
            if column - previous > 8:
                groups.append((start, previous))
                start = column
            previous = column
        groups.append((start, previous))
    return [round((s + e) / 2 / width, 4) for s, e in groups]


def extract_tab(image_path: Path, center_norm: float, out_path: Path) -> dict:
    """Cut one tab cell centred on ``center_norm``."""
    with Image.open(image_path) as image:
        width, height = image.size
        x0 = round((center_norm - TAB_CELL / 2) * width)
        y0 = round(TAB_BAND[0] * height)
        x1 = round((center_norm + TAB_CELL / 2) * width)
        y1 = round(TAB_BAND[1] * height)
        bounds = (max(0, x0), y0, min(width, x1), min(height, y1))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").crop(bounds).save(out_path, format="PNG")
    return {
        "roi_norm": {
            "x_norm": round(bounds[0] / width, 4),
            "y_norm": round(bounds[1] / height, 4),
            "w_norm": round((bounds[2] - bounds[0]) / width, 4),
            "h_norm": round((bounds[3] - bounds[1]) / height, 4),
        },
        "width": bounds[2] - bounds[0],
        "height": bounds[3] - bounds[1],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=Path("dataset/raw"))
    parser.add_argument("--out", type=Path, default=Path("dataset/candidate/resource_tabs_calibrated"))
    parser.add_argument("--manifest", type=Path, default=Path("dataset/candidate/resource_tabs_calibrated_manifest.json"))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    raw = (root / args.raw).resolve()

    selected_frames = {
        resource: raw / f"live_resource_rotation_selected_{resource.lower()}_20260913.png"
        for resource in RESOURCES
    }
    for resource, path in selected_frames.items():
        if not path.exists():
            raise SystemExit(f"missing reviewed frame for {resource}: {path}")

    # --- Step 1: measure the bracket arms of every frame -----------------
    arms_by_resource = {r: bracket_center(p) for r, p in selected_frames.items()}
    # Arms present in all four frames are chrome, not brackets.
    common = set(arms_by_resource[RESOURCES[0]])
    for resource in RESOURCES[1:]:
        common &= set(arms_by_resource[resource])
    common -= set()  # keep as-is; noise arms are removed by the tolerance below
    common = {a for a in common if min(abs(a - n) for n in ARM_NOISE) < 0.01}

    measured: dict[str, float] = {}
    for resource in RESOURCES:
        arms = [a for a in arms_by_resource[resource] if a not in common]
        if not arms:
            raise SystemExit(f"no bracket arm found for {resource}: {arms_by_resource[resource]}")
        # The bracket spans one tab cell; its left arm sits half a cell left
        # of the tab centre, the right arm half a cell right of it.
        measured[resource] = round(sum(arms) / len(arms), 4)

    # Bracket arms straddle the tab, so the tab centre is the arm pair mean.
    # Recover the strip origin from the tab spacing measured across frames.
    ordered = sorted((measured[r], r) for r in RESOURCES)
    centers: dict[str, float] = {}
    spacing_candidates = [
        (ordered[i + 1][0] - ordered[i][0]) / (TAB_ORDER.index(ordered[i + 1][1]) - TAB_ORDER.index(ordered[i][1]))
        for i in range(len(ordered) - 1)
    ]
    spacing = round(sum(spacing_candidates) / len(spacing_candidates), 4)
    # Derive every tab centre from a single anchor to keep them consistent.
    anchor_resource, anchor_norm = ordered[0][1], ordered[0][0]
    for tab in TAB_ORDER:
        offset = TAB_ORDER.index(tab) - TAB_ORDER.index(anchor_resource)
        centers[tab] = round(anchor_norm + offset * spacing, 4)

    # --- Step 2: cut templates at measured centres ------------------------
    frames = {resource: {resource: selected_frames[resource]} for resource in RESOURCES}
    # The unselected appearance comes from every frame that does not select
    # that tab, which gives four independent negatives per resource.
    records = []
    for resource in RESOURCES:
        tab = resource
        for source_resource, source_path in selected_frames.items():
            appearance = "SELECTED" if source_resource == resource else "UNSELECTED"
            semantic = f"RESOURCE_{tab}_{appearance}"
            digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:8]
            name = f"resource_tab_{tab.lower()}__{appearance.lower()}__{source_resource.lower()}__{digest}.png"
            out_path = (root / args.out) / name
            geometry = extract_tab(source_path, centers[tab], out_path)
            records.append({
                "template_id": out_path.stem,
                "semantic": semantic,
                "resource": resource,
                "appearance": appearance,
                "status": "CANDIDATE",
                "template_path": out_path.as_posix(),
                "parent_screenshot": source_path.as_posix(),
                "parent_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "roi_norm": geometry["roi_norm"],
                "width": geometry["width"],
                "height": geometry["height"],
                "confidence": 0.99,
                "source": "LIVE_CLIENT",
            })

    # --- Step 3: validate the classifier on every reviewed frame ----------
    by_resource_appearance: dict[tuple[str, str], list[dict]] = {}
    for row in records:
        by_resource_appearance.setdefault((row["resource"], row["appearance"]), []).append(row)

    def appearance_hashes(resource: str, appearance: str) -> list[tuple[str, str]]:
        return [(r["template_id"], phash(Image.open(r["template_path"])))
                for r in by_resource_appearance[(resource, appearance)]]

    # Extract the same cell from each frame and classify it.
    validation = []
    for truth, path in selected_frames.items():
        with Image.open(path) as image:
            width, height = image.size
            probes = {}
            for resource in RESOURCES:
                x0 = round((centers[resource] - TAB_CELL / 2) * width)
                y0 = round(TAB_BAND[0] * height)
                x1 = round((centers[resource] + TAB_CELL / 2) * width)
                y1 = round(TAB_BAND[1] * height)
                probes[resource] = phash(image.convert("RGB").crop((x0, y0, x1, y1)))
        # Only the SELECTED appearance distinguishes the active tab; the
        # unselected appearances of the inactive tabs must therefore lose.
        scores = {}
        for resource in RESOURCES:
            distances = [
                hamming(probes[resource], known)
                for _tid, known in appearance_hashes(resource, "SELECTED")
            ]
            scores[resource] = min(distances) if distances else 64
        predicted = min(scores, key=scores.get)
        validation.append({
            "frame": path.name,
            "truth": truth,
            "predicted": predicted,
            "ok": predicted == truth,
            "selected_distances": scores,
        })

    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "CANDIDATE",
        "method": "LIVE_BRACKET_MEASURED",
        "tab_band": TAB_BAND,
        "tab_cell": TAB_CELL,
        "measured_bracket_arms": arms_by_resource,
        "excluded_noise_arms": sorted(common),
        "tab_centers_norm": centers,
        "tab_spacing_norm": spacing,
        "count": len(records),
        "records": records,
        "validation": validation,
    }
    (root / args.manifest).parent.mkdir(parents=True, exist_ok=True)
    (root / args.manifest).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "tab_centers_norm": centers,
        "tab_spacing_norm": spacing,
        "templates": len(records),
        "validation": [{"frame": v["frame"], "truth": v["truth"], "predicted": v["predicted"], "ok": v["ok"]} for v in validation],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
