"""Why did the map frame after a successful dispatch classify as Page.EVENT?

`DISPATCH_NOT_PROVEN` fired 28 times and the post-dispatch frame in this run is
the world map with `6/6` marches and five 采集中 rows — i.e. the march really was
sent.  The verifier only failed because the observation was wrong.

This prints, for one real frame: the template layer's verdict, and the OCR
tokens the fallback classifier saw, so the misclassification can be attributed
instead of guessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (
    HybridVision,
    OCRPageClassifier,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
)
from winter_agent_v2.vision import SemanticWorldVision

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
frame = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    ROOT / "dataset/raw/control_panel/runtime_auto/accept_20260914_132309_run01"
    / "accept_20260914_132309_run01_step_005_after_refresh_2_20260914T052510027985.png"
)
print("frame:", frame.name)

template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
primary = template.observe(frame)
print(f"\n--- template layer ---")
print(f"page={primary.page.value} known={primary.known} confidence={primary.confidence}")
print(f"marches={[m.value for m in primary.marches]} march_used={primary.march_used}/{primary.march_max}")
print("probes:")
for name in (
    "PAGE_MAP", "BTN_OPEN_HOME", "BTN_OPEN_RESOURCE_SEARCH", "STATUS_GATHERING",
    "STATUS_MARCHING", "STATUS_RETURNING", "MARCH_COUNT_1_OF_6", "MARCH_COUNT_2_OF_6",
):
    match = template.semantic.find(frame, name)
    print(f"   {name:28s} -> {None if match is None else match.distance}")

ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
result = ocr.recognize(frame)
print(f"\n--- OCR ({len(result.tokens)} tokens) ---")
eligible = []
for token in sorted(result.tokens, key=lambda t: -t.confidence):
    flag = "*" if token.confidence >= 0.88 else " "
    print(f"  {flag} {token.confidence:.3f}  {token.text!r}")
    if token.confidence >= 0.88:
        eligible.append(token.text.strip())

print("\n--- exact-text rule hits (classifier threshold 0.88) ---")
exact = set(eligible)
for page, keywords in OCRPageClassifier.RULES:
    hits = [k for k in keywords if k in exact]
    if hits:
        print(f"  {page.value}: {hits}")

secondary = OCRPageClassifier().classify(result)
print(f"\nclassifier verdict: page={secondary.page.value} confidence={secondary.confidence}")

hybrid = HybridVision(template, OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))))
final = hybrid.observe(frame)
print(f"hybrid verdict:     page={final.page.value} known={final.known} "
      f"marches={[m.value for m in final.marches]} march_used={final.march_used}")
