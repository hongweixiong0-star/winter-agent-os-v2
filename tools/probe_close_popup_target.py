"""Where does ``CLOSE_POPUP`` actually tap, and where is the popup's own X?

``CLOSE_POPUP`` is ``TAP_SEMANTIC BTN_CLOSE`` on ``Page.POPUP``.  ``BTN_CLOSE`` carries four
reviewed records, none of them registered on the panel that is actually on screen in the failures,
and the phash branch of ``SemanticROIVision._find_in_roi`` reports the **registered ROI** as the
match location -- so the tap goes to wherever the winning record was registered, never to where a
close button is on the frame in front of it.

Live evidence this instrument exists for: 2026-09-23 05:23:10Z..05:30:47Z, eight consecutive runs
of one step each, ~63 s apart, every one ``CLOSE_POPUP`` -> ``POPUP_CLOSE_NOT_PROVEN`` with
``tap_point [635, 456]`` and an after-frame identical to the before-frame (#109).

What it measures, per frame, with no device:

* the phash distance of every ``BTN_CLOSE`` record and which one wins -- i.e. which record's
  registration the tap inherited, and how far that is from a genuine match;
* what OpenCV's normalised cross-correlation finds for the same templates, and where, which is the
  same comparison ``tools/ab_matcher.py`` runs before a ``matcher``/``search_band`` change;
* a marked-up crop for review, because the point of the exercise is a picture, not a number.

It changes nothing: no manifest edit, no threshold, no code path.

Usage:
    python tools/probe_close_popup_target.py
    python tools/probe_close_popup_target.py --limit 12 --band-search
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
DEFAULT_OUT = ROOT / "dataset/truth_audit/close_popup_20260923"

#: The band a moving close-X would be searched in, taken from the measured population rather than
#: chosen: the six X centres a reviewed template found on live popup frames are x 0.8722..0.9236,
#: y 0.1129..0.3559, and the template is 68x77 (0.0944 x 0.0602 normalized) at scales 0.9..1.1.
DEFAULT_BAND = {"x_norm": 0.80, "y_norm": 0.07, "w_norm": 0.20, "h_norm": 0.36}


def _rows() -> list[dict]:
    out: list[dict] = []
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _close_popup_steps(rows: list[dict]) -> list[dict]:
    steps = [row for row in rows if str(row.get("skill")) == "CLOSE_POPUP"]
    steps.sort(key=lambda row: str(row.get("recorded_at")))
    return steps


def _per_record_phash(vision, frame: Path) -> list[dict]:
    """The phash branch of ``_find_in_roi``, unrolled so every record's distance is visible.

    Same crop, same digest, same hamming function as production -- the only difference is that
    production returns ``min`` and this returns the whole list.
    """
    from winter_agent_v2.image_hash import hamming, phash  # noqa: PLC0415

    candidates = [row for row in vision.records if row["semantic"] == "BTN_CLOSE"]
    image = vision._decoded(frame)  # noqa: SLF001 - the instrument measures the real code path
    width, height = image.size
    out: list[dict] = []
    for row in candidates:
        roi = row["roi_norm"]
        bounds = (
            round(roi["x_norm"] * width),
            round(roi["y_norm"] * height),
            round((roi["x_norm"] + roi["w_norm"]) * width),
            round((roi["y_norm"] + roi["h_norm"]) * height),
        )
        template_hash = vision._template_digest(  # noqa: SLF001
            Path(row["template_path"]), size=8, kind="phash"
        )
        if not template_hash:
            continue
        distance = hamming(phash(image.crop(bounds), size=8), template_hash)
        out.append({
            "template_id": row.get("template_id"),
            "template_path": row.get("template_path"),
            "roi_norm": [roi["x_norm"], roi["y_norm"], roi["w_norm"], roi["h_norm"]],
            "roi_center_px": [round((roi["x_norm"] + roi["w_norm"] / 2) * width),
                              round((roi["y_norm"] + roi["h_norm"] / 2) * height)],
            "matcher": row.get("matcher") or "phash",
            "has_search_band": bool(row.get("search_band")),
            "phash_distance": int(distance),
        })
    return out


def _ccoeff_points(frame: Path, records: list[dict], *, whole_frame: bool) -> list[dict]:
    from winter_agent_v2.matchers import match_ccoeff  # noqa: PLC0415

    out: list[dict] = []
    for row in records:
        band = row.get("search_band")
        region = band or row["roi_norm"]
        margin = 0 if band else 40
        if whole_frame:
            region = {"x_norm": 0.0, "y_norm": 0.0, "w_norm": 1.0, "h_norm": 1.0}
            margin = 0
        found = match_ccoeff(frame, Path(row["template_path"]), region, margin=margin)
        out.append({
            "template_id": row.get("template_id"),
            "score": None if found is None else round(found.score, 4),
            "center_norm": None if found is None else list(found.center_norm),
            "scale": None if found is None else found.scale,
            "region": [region["x_norm"], region["y_norm"], region["w_norm"], region["h_norm"]],
            "whole_frame": whole_frame,
        })
    return out


def _review_crop(frame: Path, marks: list[tuple[str, tuple[float, float]]], out: Path) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    image = Image.open(frame).convert("RGB")
    draw = ImageDraw.Draw(image)
    colours = {"tapped": (255, 60, 60), "ccoeff": (0, 200, 80), "ccoeff_whole": (255, 200, 0)}
    for label, (nx, ny) in marks:
        x, y = nx * image.width, ny * image.height
        colour = colours.get(label, (255, 0, 255))
        r = 18
        draw.ellipse((x - r, y - r, x + r, y + r), outline=colour, width=4)
        draw.line((x - r - 10, y, x + r + 10, y), fill=colour, width=2)
        draw.line((x, y - r - 10, x, y + r + 10), fill=colour, width=2)
    image.resize((image.width * 3 // 4, image.height * 3 // 4)).save(out)


def _records_by_popup(vision, rows: list[dict], limit_per_popup: int = 1) -> dict[str, str]:
    """One frame per popup identity, so every reviewed record can be asked which screen it is of."""
    out: dict[str, str] = {}
    for row in rows:
        state = row.get("state_before") or {}
        page = str((state.get("page") or {}).get("value")
                   if isinstance(state.get("page"), dict) else state.get("page") or "")
        if page != "POPUP":
            continue
        name = str(state.get("popup") or "")
        frame = str(row.get("before_screenshot") or "")
        if not name or name in out or not Path(frame).is_file():
            continue
        out[name] = frame
        if len(out) >= limit_per_popup and False:  # kept explicit: one frame per popup is the ask
            break
    return out


def _survey(rows: list[dict], out_dir: Path, band: dict) -> dict:
    """Which screen each ``BTN_CLOSE`` record belongs to, and how well a band finds the X on each.

    This is the measurement issue #109 is built on.  Two questions, both answered with the project's
    own reviewed templates and its own matcher:

    * **whose registration is a record?**  Each record was cropped from a parent frame; the parent's
      own reading says which popup that was, and that is the screen the coordinate belongs to.
    * **does a band find the X?**  ``match_ccoeff`` over the band the record would search, scored on
      one frame per popup: the frames that draw an X versus the ones that do not.
    """
    from winter_agent_v2.matchers import match_ccoeff  # noqa: PLC0415
    from winter_agent_v2.vision import SemanticWorldVision  # noqa: PLC0415

    vision = SemanticWorldVision(MANIFEST)
    records = [row for row in vision.semantic.records if row["semantic"] == "BTN_CLOSE"]

    # (1) the screen behind every registration
    provenance = []
    for row in records:
        parent = Path(str(row.get("parent_screenshot") or ""))
        entry = {
            "template_id": row.get("template_id"),
            "roi_center_px": [round((row["roi_norm"]["x_norm"] + row["roi_norm"]["w_norm"] / 2) * 720),
                              round((row["roi_norm"]["y_norm"] + row["roi_norm"]["h_norm"] / 2) * 1280)],
            "matcher": row.get("matcher") or "phash",
            "parent_frame": str(parent),
            "parent_reads_as": None,
        }
        if parent.is_file():
            world = vision.observe(parent)
            entry["parent_reads_as"] = f"{getattr(world.page, 'value', world.page)}|{world.popup}"
        provenance.append(entry)

    # (2) the band, scored one frame per popup
    screens = _records_by_popup(vision, rows)
    scored = []
    for name, frame in sorted(screens.items()):
        best = None
        for row in records:
            found = match_ccoeff(Path(frame), Path(row["template_path"]), band, margin=0)
            if found is None:
                continue
            if best is None or found.score > best[0]:
                best = (found.score, found.center_norm, row.get("template_id"))
        scored.append({
            "popup": name,
            "frame": frame,
            "best_score": None if best is None else round(best[0], 4),
            "distance": None if best is None else int(round((1.0 - best[0]) * 64)),
            "centre": None if best is None else list(best[1]),
            "template_id": None if best is None else best[2],
        })

    positives = [row for row in scored if row["distance"] is not None and row["distance"] <= 8]
    negatives = [row for row in scored if row["distance"] is None or row["distance"] > 8]
    report = {
        "band": band,
        "band_note": (
            "x 0.80..1.00, y 0.07..0.43 -- the region the six measured X centres occupy, plus room "
            "for the 68x77 template at every scale"
        ),
        "registrations": provenance,
        "screens": scored,
        "separation": {
            "positives": len(positives),
            "positive_distances": sorted(row["distance"] for row in positives),
            "negatives": len(negatives),
            "negative_distances": sorted(row["distance"] for row in negatives if row["distance"] is not None),
        },
    }
    print()
    print("=== which screen each BTN_CLOSE record was registered on ===")
    for row in provenance:
        print(f"  {str(row['template_id'])[:38]:<40} roi_center={row['roi_center_px']} "
              f"parent reads as {row['parent_reads_as']}")
    print()
    print(f"=== the band, one frame per popup (distance = round((1-score)*64), threshold 8) ===")
    for row in scored:
        print(f"  {row['popup']:<26} d={str(row['distance']):>5} "
              f"score={str(row['best_score']):>7} centre={row['centre']} {str(row['template_id'])[:30]}")
    print()
    print("separation:", json.dumps(report["separation"], ensure_ascii=False))
    (out_dir / "survey.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out_dir / "survey.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40, help="how many CLOSE_POPUP steps to measure")
    parser.add_argument("--band-search", action="store_true",
                        help="also search the whole frame, to locate the X without assuming where it is")
    parser.add_argument("--survey", action="store_true",
                        help="which screen each BTN_CLOSE record belongs to, and the band's separation")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    from winter_agent_v2.vision import SemanticWorldVision

    all_rows = _rows()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.survey:
        _survey(all_rows, args.out, dict(DEFAULT_BAND))
        return 0

    vision = SemanticWorldVision(MANIFEST).semantic
    threshold = vision.semantic_max_distance.get("BTN_CLOSE", vision.max_distance)
    steps = _close_popup_steps(all_rows)[-args.limit:]

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "threshold_for_BTN_CLOSE": threshold,
        "threshold_source": (
            "semantic_max_distance has no BTN_CLOSE entry"
            if "BTN_CLOSE" not in vision.semantic_max_distance
            else "semantic_max_distance[BTN_CLOSE]"
        ),
        "frames": [],
    }
    disagree = 0

    for index, step in enumerate(steps):
        # ``Path("")`` is ``Path(".")``, which *exists*, so the empty-string case has to be caught
        # before the existence check rather than by it.
        raw_frame = str(step.get("before_screenshot") or "")
        if not raw_frame:
            continue
        frame = Path(raw_frame)
        if not frame.is_file():
            continue
        records = [row for row in vision.records if row["semantic"] == "BTN_CLOSE"]
        per_record = _per_record_phash(vision, frame)
        if not per_record:
            continue
        winner = min(per_record, key=lambda row: row["phash_distance"])
        winner_index = next(i for i, row in enumerate(records)
                            if row.get("template_id") == winner["template_id"])

        ccoeff = _ccoeff_points(frame, records, whole_frame=False)
        best_ccoeff = max((row for row in ccoeff if row["score"] is not None),
                          key=lambda row: row["score"], default=None)
        whole = _ccoeff_points(frame, records, whole_frame=True) if args.band_search else []
        best_whole = max((row for row in whole if row["score"] is not None),
                         key=lambda row: row["score"], default=None)

        tap = tuple(winner["roi_center_px"])
        norm_tap = (tap[0] / 720.0, tap[1] / 1280.0)
        marks = [("tapped", norm_tap)]
        if best_ccoeff is not None:
            marks.append(("ccoeff", tuple(best_ccoeff["center_norm"])))
        if best_whole is not None:
            marks.append(("ccoeff_whole", tuple(best_whole["center_norm"])))
        args.out.mkdir(parents=True, exist_ok=True)
        crop = args.out / f"review_{index:02d}_{str(step.get('recorded_at'))[11:19].replace(':', '')}.png"
        _review_crop(frame, marks, crop)

        entry = {
            "recorded_at": str(step.get("recorded_at")),
            "result": str(step.get("result")),
            "failure_type": str(step.get("failure_type")),
            "goal": str(step.get("goal_id")),
            "popup": str((step.get("state_before") or {}).get("popup") or ""),
            "frame": str(frame),
            "review_crop": str(crop),
            "winner_index": winner_index,
            "winner_template_id": winner["template_id"],
            "winner_phash_distance": winner["phash_distance"],
            "winner_within_threshold": winner["phash_distance"] <= threshold,
            "winner_roi_center_px": winner["roi_center_px"],
            "tapped_point_norm": [round(norm_tap[0], 4), round(norm_tap[1], 4)],
            "per_record": per_record,
            "ccoeff": ccoeff,
            "ccoeff_best": best_ccoeff,
            "ccoeff_whole_frame_best": best_whole,
        }
        report["frames"].append(entry)

        if len(entry["ccoeff"]) and best_ccoeff is not None and best_ccoeff["center_norm"] is not None:
            gap = abs(best_ccoeff["center_norm"][1] - norm_tap[1]) * 1280
            if gap > 60:
                disagree += 1
        print(f"{entry['recorded_at'][11:19]} {entry['result']:<7} {entry['failure_type'][:24]:<24} "
              f"popup={entry['popup']:<16} winner=#{winner_index} d={winner['phash_distance']}"
              f"(thr {threshold}) tap={tap}")
        for row in per_record:
            print(f"      #{records.index(next(r for r in records if r.get('template_id') == row['template_id']))}"
                  f" {row['matcher']:<6} d={row['phash_distance']:>3} "
                  f"roi_center={row['roi_center_px']} band={row['has_search_band']} "
                  f"{str(row['template_id'])[:38]}")
        if best_ccoeff is not None:
            print(f"      ccoeff best: {best_ccoeff['score']} at {best_ccoeff['center_norm']} "
                  f"(scale {best_ccoeff['scale']})")
        if best_whole is not None:
            print(f"      ccoeff whole-frame best: {best_whole['score']} at {best_whole['center_norm']}")

    report["summary"] = {
        "frames_measured": len(report["frames"]),
        "winners": dict(Counter(entry["winner_template_id"] for entry in report["frames"])),
        "winner_distances": dict(Counter(entry["winner_phash_distance"] for entry in report["frames"])),
        "winner_within_threshold": sum(1 for entry in report["frames"] if entry["winner_within_threshold"]),
        "frames_where_ccoeff_disagrees_with_the_tap_by_over_60px": disagree,
        "results": dict(Counter(entry["result"] for entry in report["frames"])),
        "failure_types": dict(Counter(entry["failure_type"] for entry in report["frames"])),
        "popups": dict(Counter(entry["popup"] for entry in report["frames"])),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print("summary:", json.dumps(report["summary"], ensure_ascii=False))
    print("wrote", args.out / "probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
