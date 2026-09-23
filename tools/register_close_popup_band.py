"""Register a searching ``BTN_CLOSE`` record so the close-X is *found* rather than assumed.

The problem it fixes (issue #109, measured 2026-09-23):

``BTN_CLOSE``'s four records are all ``phash`` records, and ``_find_in_roi``'s phash branch reports
the **registered ROI** as the match location -- it verifies "the thing is still where it was", it
does not search.  The four registrations sit at (612,131), (613,148), (635,456) and (682,38), and
they belong to four *different* screens: ``PURCHASE_POPUP``, ``PURCHASE_POPUP``, ``EXIT_CONFIRM``
and an alliance chest layer.  The close-X of the panels in the corpus moves -- 0.8819/0.3559 on
退出确认, 0.9236/0.1301 on 加成总览, 0.9236/0.1129 on 获得更多体力, 0.9208/0.2277 on 实力详情,
0.9194/0.2027 on 离线奖励 -- which is exactly the case ``match_ccoeff`` with a ``search_band``
exists for ("A ROI that is both 'where it is' and 'where to look' cannot express that", vision.py).

This tool does not invent anything.  It reuses the one reviewed template that is a picture of a
close-X (``btn_close__step_001_before__1``), gives it the band the measured centres imply, and
**refuses to write unless the separation holds** on the corpus: the frames that draw an X come in at
distance <= 8 and the frames that draw none come in well above it.  Both halves are recomputed here
rather than quoted, so a later drift in the corpus moves the answer instead of hiding behind it.

Usage:
    python tools/register_close_popup_band.py --dry-run
    python tools/register_close_popup_band.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
EPISODES = ROOT / "learning/episodes.jsonl"

TEMPLATE_PATH = "dataset/candidate/templates/btn_close__step_001_before__1.png"
#: The record this one borrows its picture and its registration from.  Named rather than searched
#: for by prefix: which reviewed crop is the X is a fact about the corpus, not a naming convention.
REVIEWED_CROP_ID = "btn_close__step_001_before__1"
TEMPLATE_ID = "btn_close__popup_titlebar_band__0"
#: The band, and where it comes from: a reviewed X template scored 0.98-0.999 on six live popup
#: frames at x 0.8722..0.9236, y 0.1129..0.3559; the template is 68x77 (0.0944 x 0.0602) at scales
#: 0.9..1.1, so the band is those centres plus half a template plus a margin.
BAND = {"x_norm": 0.80, "y_norm": 0.07, "w_norm": 0.20, "h_norm": 0.36}
THRESHOLD = 8


def _frames_by_popup(limit: int | None = None) -> dict[str, str]:
    """One frame per popup identity, newest first -- the population the separation is measured on."""
    out: dict[str, str] = {}
    rows: list[dict] = []
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for row in reversed(rows):
        state = row.get("state_before") or {}
        page = state.get("page")
        page = str(page.get("value") if isinstance(page, dict) else page or "")
        if page != "POPUP":
            continue
        name = str(state.get("popup") or "")
        frame = str(row.get("before_screenshot") or "")
        if not name or name in out or not Path(frame).is_file():
            continue
        out[name] = frame
        if limit is not None and len(out) >= limit:
            break
    return out


def measure() -> dict:
    """Score the band on one frame per popup, using the matcher the record will use."""
    from winter_agent_v2.matchers import match_ccoeff
    from winter_agent_v2.vision import SemanticWorldVision

    vision = SemanticWorldVision(MANIFEST)
    records = [row for row in vision.semantic.records if row["semantic"] == "BTN_CLOSE"]
    template = next(row for row in records if row.get("template_id") == REVIEWED_CROP_ID)
    scored = []
    for name, frame in sorted(_frames_by_popup().items()):
        found = match_ccoeff(Path(frame), ROOT / TEMPLATE_PATH, BAND, margin=0)
        scored.append({
            "popup": name,
            "frame": frame,
            "score": None if found is None else round(found.score, 4),
            "distance": None if found is None else int(round((1.0 - found.score) * 64)),
            "centre": None if found is None else list(found.center_norm),
        })
    inside = [row for row in scored if row["distance"] is not None and row["distance"] <= THRESHOLD]
    outside = [row for row in scored if row["distance"] is None or row["distance"] > THRESHOLD]
    return {
        "template_path": TEMPLATE_PATH,
        "template_id_of_the_reviewed_crop": template.get("template_id"),
        "band": BAND,
        "threshold": THRESHOLD,
        "scored": scored,
        "inside": len(inside),
        "outside": len(outside),
        "inside_distances": sorted(row["distance"] for row in inside),
        "outside_distances": sorted(row["distance"] for row in outside if row["distance"] is not None),
    }


def verdict(measured: dict) -> tuple[bool, str]:
    """Two populations, one threshold, and the gap has to be the threshold's, not the author's."""
    inside, outside = measured["inside_distances"], measured["outside_distances"]
    if len(inside) < 4:
        return False, f"only {len(inside)} popup frames draw a close-X in the band; not a population"
    if not outside:
        return False, "no frame without a close-X was measured, so the band has no negative control"
    if max(inside) >= THRESHOLD:
        return False, f"the closest non-match inside the band is {max(inside)}"
    if min(outside) <= max(inside) + 8:
        return False, (f"the gap is {min(outside) - max(inside)} between {max(inside)} and "
                       f"{min(outside)}; the threshold would sit on the edge of a population")
    return True, (f"X drawn: {inside} (max {max(inside)}) vs not drawn: "
                  f"{len(outside)} (min {min(outside)}) -- threshold {THRESHOLD} sits inside the gap")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="measure and report, write nothing")
    args = parser.parse_args()

    measured = measure()
    ok, why = verdict(measured)
    print(f"template : {measured['template_id_of_the_reviewed_crop']} ({TEMPLATE_PATH})")
    print(f"band     : {BAND}")
    for row in measured["scored"]:
        print(f"  {row['popup']:<28} d={str(row['distance']):>5} score={str(row['score']):>7} "
              f"centre={row['centre']}")
    print(f"separation: {why}")
    if not ok:
        print("REFUSED: the band does not separate on this corpus, so nothing is written")
        return 1
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = list(payload.get("records", []))
    if any(row.get("template_id") == TEMPLATE_ID for row in records):
        print(f"already registered: {TEMPLATE_ID}")
        return 0
    template_record = next(row for row in records if row.get("template_id")
                           == measured["template_id_of_the_reviewed_crop"])
    records.append({
        "semantic": "BTN_CLOSE",
        "template_path": TEMPLATE_PATH,
        "roi_norm": dict(template_record["roi_norm"]),
        # The window, not the registration.  With a band, ``range(roi)`` is only the fallback when
        # the matcher cannot be evaluated, and the match reports the bounds it FOUND -- which is
        # what makes this a search rather than a confirmation.
        "search_band": dict(BAND),
        "matcher": "ccoeff",
        "source": "LIVE_CLIENT",
        "provenance": "LIVE_CLIENT",
        "reviewed_from": "LIVE_CLIENT_REPLAY",
        "confidence": 0.99,
        "status": "CANDIDATE",
        "template_id": TEMPLATE_ID,
        "width": template_record["width"],
        "height": template_record["height"],
        "note": (
            "The popup's own close-X, searched in its title bar instead of being assumed at a "
            "registration. Measured 2026-09-23 over one frame per popup identity "
            "(tools/register_close_popup_band.py recomputes both halves): a reviewed X crop scores "
            f"{measured['inside_distances']} (distance) on the {measured['inside']} popups that draw "
            f"one and {measured['outside_distances']} on the {measured['outside']} that do not, so "
            f"threshold {THRESHOLD} sits inside the gap. The four phash records are registrations on "
            "other screens -- PURCHASE_POPUP x2, EXIT_CONFIRM, an alliance chest layer -- and a "
            "registration cannot express a control that moves (issue #109)."
        ),
    })
    payload["records"] = records
    payload["count"] = len(records)
    # indent=1 is what this file uses on disk; see tools/merge_template_manifest.py for what the
    # other indent cost (7499 insertions for one added record).
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"registered {TEMPLATE_ID}; records {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
