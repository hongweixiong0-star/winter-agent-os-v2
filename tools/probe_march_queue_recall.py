"""Locate the march-queue recall control on the live client.

`RECALL_MARCH` is registered but absent from `LiveRuntime.VERIFIED_ATOMIC`, so
the loop can never dispatch a recall — which is the blocker for the operator's
directive "recall the gathering marches and spend the stamina instead".

This captures the march-queue UI and looks for the recall affordance, saving the
frames as evidence so the next account can add a template + verifier from real
frames instead of guessing.

Writes: dataset/truth_audit/march_queue_<stamp>/
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
from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.vision import SemanticWorldVision

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
device.resolve_connection()
vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / "dataset/truth_audit" / f"march_queue_{stamp}"
out.mkdir(parents=True, exist_ok=True)
print("out:", out)

W, H = 720, 1280
log: list[dict] = []


def shot(label: str) -> Path:
    path = out / f"{stamp}_{label}.png"
    device.screenshot(path)
    return path


def describe(label: str) -> Path:
    path = shot(label)
    state = vision.observe(path)
    tokens = [t for t in ocr.recognize(path).tokens if t.confidence >= 0.80]
    interesting = [
        (t.text.strip(), round(t.confidence, 3),
         None if not t.box else (round((t.box[0][0] + t.box[2][0]) / 2 / W, 4),
                                 round((t.box[0][1] + t.box[2][1]) / 2 / H, 4)))
        for t in tokens
        if any(key in t.text for key in ("行军", "撤退", "召回", "返回", "队列", "采集中", "行军中", "驻扎"))
    ]
    entry = {"label": label, "file": path.name, "page": state.page.value,
             "march": f"{state.march_used}/{state.march_max}", "tokens": interesting}
    log.append(entry)
    print(f"  {label:22s} page={state.page.value:12s} march={entry['march']}")
    for text, conf, box in interesting:
        print(f"      {text!r} conf={conf} centre={box}")
    return path


print("\n== current map frame ==")
describe("map_before")

# The march counter sits at the top-left of the world map.  Tap it to open the
# queue panel, which is where a recall affordance would live.
print("\n== tap the top-left march counter ==")
device.tap(round(0.09 * W), round(0.09 * H))
time.sleep(2.5)
describe("after_march_counter_tap")

print("\n== tap the first march row (left list) ==")
device.tap(round(0.12 * W), round(0.20 * H))
time.sleep(2.5)
describe("after_first_row_tap")

(out / "probe.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwritten", out / "probe.json")
