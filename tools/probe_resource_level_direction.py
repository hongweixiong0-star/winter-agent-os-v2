"""Live experiment: does raising the level filter make the WOOD search succeed?

Observed on the real client (2026-09-14): with WOOD selected and the level filter
at its minimum (1级) the search returns nothing, and the relax-downward recovery
cannot help because there is nothing below 1.  Before adding an upward recovery
the direction must be verified rather than guessed.

The panel also exposes a checkbox 「仅搜索资源为满的资源点」 ("only search FULL
resource nodes"); its state is captured here because it can suppress results on
its own.

Writes: dataset/truth_audit/level_probe_<stamp>/
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
out = ROOT / "dataset/truth_audit" / f"level_probe_{stamp}"
out.mkdir(parents=True, exist_ok=True)
print("out:", out)

PLUS = sem.resource_level_plus
MINUS = sem.resource_level_minus
SEARCH_BTN = (0.5, 0.918)  # measured: the 搜索 control spans the panel width


def tap_norm(point) -> None:
    device.tap(round(point[0] * 720), round(point[1] * 1280))


def shot(label: str) -> Path:
    path = out / f"{stamp}_{label}.png"
    device.screenshot(path)
    return path


def state(path: Path) -> dict:
    return {
        "page": vision.observe(path).page.value if False else None,
        "selected": (lambda m: m.semantic if m else None)(sem.selected_resource(path)),
        "level": sem.resource_level(path),
        "search_open": bool(sem.find(path, "BTN_RESOURCE_SEARCH_SUBMIT")),
    }


log: list[dict] = []


def record(label: str) -> dict:
    path = shot(label)
    info = state(path)
    info["label"] = label
    info["file"] = path.name
    log.append(info)
    print(f"  {label:24s} selected={info['selected']} level={info['level']} open={info['search_open']}")
    return info


print("== baseline ==")
record("baseline")

print("== raise the level filter by 3 steps, then search ==")
for i in range(3):
    tap_norm(PLUS)
    time.sleep(0.8)
record("level_plus_3")

print("== submit the search at the raised level ==")
tap_norm(SEARCH_BTN)
time.sleep(3.0)
after = record("search_at_raised_level")

print("== if still on the panel, raise again and retry ==")
if after["search_open"]:
    for i in range(4):
        tap_norm(PLUS)
        time.sleep(0.8)
    record("level_plus_7")
    tap_norm(SEARCH_BTN)
    time.sleep(3.0)
    record("search_at_level_7")

(out / "probe.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwritten", out / "probe.json")
