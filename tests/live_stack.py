"""Build the production vision stack for tests that must read real frames.

``SemanticWorldVision`` cannot count marches by design: a reviewed counter
template is the only authored evidence for the number, and no single template
matches every count.  It used to add a hardcoded ``calibrated_baseline_used``
of 1 anyway, which meant a frame with six gathering marches still reported 1/6
(six free slots at a glance).  That baseline is gone, so a test that asserts a
*march count* must use the production stack -- the same template+OCR
combination ``tools/run_live.py`` builds -- or it would only be re-testing the
removed constant.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def production_vision(manifest: str = "template_manifest.json"):
    """Return the template+OCR stack used in production, or ``None``.

    ``None`` means the OCR runtime or its module path is unavailable in this
    environment; callers should skip rather than silently fall back to the
    template-only layer, which would hide the very gap this helper exists for.
    """
    try:
        from winter_agent_v2.ocr import (
            HybridVision,
            OCRService,
            RapidOCRBackend,
            ResilientOCRBackend,
        )
        from winter_agent_v2.vision import SemanticWorldVision
    except Exception:  # noqa: BLE001 - optional OCR dependency
        return None
    try:
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        backend = ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    except Exception:  # noqa: BLE001 - OCR runtime or config missing
        return None
    return HybridVision(SemanticWorldVision(ROOT / "dataset/candidate" / manifest), OCRService(backend))
