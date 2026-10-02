"""Does a successful camp tap use the ring centre, or a point offset from it?

The picker's docstring says the ring is a focus marker and not the building's hit area, while the
code taps the ring centre outright.  That contradiction is only worth acting on if the frames can
say which is right, so: recompute the picker's own point on every TAP_FOCUSED_TRAINING_CAMP_* step
today -- successes and failures alike -- and compare.

Read-only.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.camp_ring import _hsv, focused_camp_body_tap_norm  # noqa: E402

RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"
P = ROOT / "learning" / "episodes.jsonl"


def tail_rows(nbytes: int):
    size = P.stat().st_size
    with P.open("rb") as f:
        f.seek(max(0, size - nbytes))
        blob = f.read().decode("utf-8", "replace")
    out = []
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


rows = [r for r in tail_rows(30_000_000)
        if str(r.get("skill") or "").startswith("TAP_FOCUSED_TRAINING_CAMP_")]
print("TAP_FOCUSED_TRAINING_CAMP_* steps today:", len(rows),
      dict(collections.Counter(r.get("result") for r in rows)))

by_result = collections.defaultdict(list)
for r in rows:
    shot = str(r.get("before_screenshot") or "")
    ep = str(r.get("episode_id") or "")
    if not shot:
        continue
    path = RUNS / ep / Path(shot.replace("\\", "/")).name
    if not path.exists():
        continue
    point = focused_camp_body_tap_norm(path)
    sb = r.get("state_before") or {}
    tr = sb.get("training") or {}
    by_result[r.get("result")].append({
        "at": str(r.get("recorded_at"))[11:19],
        "camp": str(r.get("skill")).replace("TAP_FOCUSED_TRAINING_CAMP_", ""),
        "point": point,
        "state_focus": tr.get("camp_focus_tap_norm"),
        "state_nav": tr.get("navigation"),
        "ft": r.get("failure_type"),
        "after_menu": (r.get("state_after") or {}).get("training", {}).get("menu_open")
        if isinstance((r.get("state_after") or {}).get("training"), dict) else None,
    })

for result in ("SUCCESS", "FAILURE"):
    items = by_result.get(result) or []
    print("\n===", result, len(items))
    for it in items:
        print("   %s %-9s point=%-22s state_focus=%-22s nav=%-20s after_menu=%s ft=%s" % (
            it["at"], it["camp"], str(it["point"]), str(it["state_focus"]),
            str(it["state_nav"]), it["after_menu"], it["ft"]))

print("\n-- do the picker and the state agree? --")
agree = sum(1 for result in by_result for it in by_result[result]
            if it["point"] is not None and it["state_focus"] is not None
            and abs(it["point"][0] - it["state_focus"][0]) < 1e-4
            and abs(it["point"][1] - it["state_focus"][1]) < 1e-4)
total = sum(len(v) for v in by_result.values())
print("   identical: %d of %d" % (agree, total))

# What is under the chosen point on a SUCCESS frame vs a FAILURE frame?  The building body is
# measurable as the largest non-snow, non-warm object, so instead of guessing: report the gap
# between the chosen centre and the frame centre, and whether the frame downstream showed a menu.
print("\n-- chosen y, grouped by outcome (the ring centre is the only x the picker can return) --")
for result in ("SUCCESS", "FAILURE"):
    ys = [round(it["point"][1], 4) for it in by_result.get(result) or [] if it["point"]]
    print("   %-8s y=%s" % (result, sorted(ys)))
