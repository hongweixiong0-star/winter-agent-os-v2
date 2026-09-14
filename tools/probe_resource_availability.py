"""Live experiment: is RESOURCE_NOT_FOUND resource-specific availability?

Run 1 of the gather acceptance produced a full MEAT closure, while WOOD returned
RESOURCE_NOT_FOUND at every level from 1 to 8.  Before changing recovery logic
the cause must be pinned down: either the search is broken for WOOD, or WOOD
simply has no eligible node in range right now (in which case the correct
product behaviour is to rotate to another resource, not to abort the goal).

This selects each gatherable tab in turn using the shipped relative-layout model
and submits the search, so it also re-validates SELECT_RESOURCE live.
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
from winter_agent_v2.vision import SemanticWorldVision

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
device.resolve_connection()
vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
sem = vision.semantic

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / "dataset/truth_audit" / f"resource_availability_{stamp}"
out.mkdir(parents=True, exist_ok=True)
print("out:", out)

BAND_Y = (sem.resource_tab_band[0] + sem.resource_tab_band[1]) / 2
SEARCH_BTN = (0.5, 0.918)

log: list[dict] = []


def shot(label: str) -> Path:
    path = out / f"{stamp}_{label}.png"
    device.screenshot(path)
    return path


def tap_norm(point) -> None:
    device.tap(round(point[0] * 720), round(point[1] * 1280))


def observe(path: Path) -> dict:
    return {
        "page": vision.observe(path).page.value,
        "selected": (lambda m: m.semantic if m else None)(sem.selected_resource(path)),
        "level": sem.resource_level(path),
        "search_open": bool(sem.find(path, "BTN_RESOURCE_SEARCH_SUBMIT")),
    }


def record(label: str) -> dict:
    path = shot(label)
    info = observe(path)
    info.update({"label": label, "file": path.name})
    log.append(info)
    print(f"  {label:28s} page={info['page']:16s} selected={info['selected']} "
          f"level={info['level']} panel_open={info['search_open']}")
    return info


print("== ensure the panel is open and learn the strip offset ==")
baseline = record("baseline")
if not baseline["search_open"]:
    print("!! the resource search panel is not open; rerun after opening it")
    raise SystemExit(1)

for resource in ("MEAT", "WOOD", "COAL", "IRON"):
    # Locate the tab from the anchor observed on the current frame.
    probe = shot("offset_probe")
    if sem.selected_resource(probe) is None:
        print(f"  {resource}: cannot read the anchor; skipping")
        continue
    centre = sem.resource_cell_center_norm(resource)
    if centre is None:
        delta = sem.resource_tab_swipe_for(resource)
        print(f"  {resource}: cell off-screen (swipe delta {delta}); skipping")
        continue
    print(f"\n== select {resource} at {centre[0]:.4f} and search ==")
    tap_norm((centre[0], BAND_Y))
    time.sleep(1.4)
    record(f"select_{resource}")

    tap_norm(SEARCH_BTN)
    time.sleep(3.0)
    after = record(f"search_{resource}")
    log[-1]["search_result"] = "RESOURCE_DETAIL" if after["page"] == "RESOURCE_DETAIL" else "NOT_FOUND"
    print(f"    -> {log[-1]['search_result']}")

    if after["page"] == "RESOURCE_DETAIL":
        # Leave the detail page so the next resource can be searched.
        device.press_back()
        time.sleep(2.0)

(out / "probe.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwritten", out / "probe.json")
print("\nsummary:")
for row in log:
    if "search_result" in row:
        print(f"  {row['label']:28s} -> {row['search_result']}")
