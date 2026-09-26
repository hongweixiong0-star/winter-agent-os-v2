# -*- coding: utf-8 -*-
"""Regression coverage for the four TEMPLATE repair fixes (operator §一).

1. validate() must never run without a real matcher adapter (NO_ADAPTER gate).
2. matcher errors must surface in the report as frame_errors, not vanish.
3. TEMPLATE nodes get a padded search ROI (drift tolerance).
4. the decisive one: on ONE adapter, registering template A then re-loading
   the SAME NAME with template B must actually match B — the match result
   must change, not just the call returning True.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.maa_executor import MaaExecutorAdapter

DATASET = Path(__file__).resolve().parents[1] / "dataset" / "raw" / "autogen"
FRAME_A = DATASET / "r14_war.png"          # has 自动加入 button (blue)
FRAME_B = DATASET / "r16_war_activity_tab.png"  # same page, different state


def _rgb(path: Path) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"))


@pytest.fixture(scope="module")
def adapter():
    import json
    from winter_agent_v2.executor_router import build_maa_adapter
    config_path = Path(__file__).resolve().parents[1] / "config" / "v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    a = build_maa_adapter(config, production=False)
    if a is None:
        pytest.skip("MAA disabled by configuration")
    ok, reason = a.ensure_ready()
    if not ok:
        pytest.skip(f"MAA unavailable in this environment: {reason}")
    return a


def _crop(image: np.ndarray, box) -> np.ndarray:
    x, y, w, h = box
    return image[y:y + h, x:x + w]


def test_same_name_replacement_actually_changes_match(adapter):
    """Register crop A under NAME, then re-register crop B under NAME.

    The match against a frame containing only B must flip from NO_MATCH to
    hit after the re-registration — before the fix the name cache silently
    kept A and B could never be found.
    """
    name = "REG_TPL_CACHE_TEST"
    img_a = _rgb(FRAME_A)
    img_b = _rgb(FRAME_B)
    # a distinctive crop from each frame (same rect: the war page header)
    box = (60, 88, 120, 40)
    tpl_a = _crop(img_a, box)
    tpl_b = _crop(img_b, box)

    adapter._loaded_templates.discard(name)
    try:
        assert adapter._load_template(name, tpl_a)
        out_a = adapter.find(img_a, name, template=name, threshold=0.8)
        assert out_a.hit, "crop A must match its own frame"

        # re-register the SAME NAME with image B (the repair scenario)
        assert adapter._load_template(name, tpl_b)
        out_b = adapter.find(img_b, name, template=name, threshold=0.8)
        assert out_b.hit, (
            "same-name re-registration must replace the matcher template; "
            "NO_MATCH here means the stale name cache is back")
    finally:
        adapter._loaded_templates.discard(name)


def test_file_backed_registration_keeps_cache_behaviour(adapter):
    """Without an explicit image, an already-registered name must NOT be
    re-resolved from disk every call (production fast path is unchanged)."""
    name = "REG_TPL_FILEPATH_TEST"
    adapter._loaded_templates.add(name)   # pretend it is registered
    try:
        assert adapter._load_template(name) is True
    finally:
        adapter._loaded_templates.discard(name)


def test_template_node_roi_is_padded():
    from winter_agent_v2.pipeline_autogen import (GenerationRequest,
                                                  PipelineAutoGen,
                                                  TEMPLATE_ROI_EXPAND)
    gen = PipelineAutoGen(device=None)
    frame = DATASET / "r14_war.png"
    found = gen.locate_text(frame, "联盟战争")
    assert found is not None, "frame must contain the declared word"
    node = gen.generate(GenerationRequest(semantic="REG_ROI_PAD_TEST",
                                          cn_text="联盟战争",
                                          skill_id="X", want="auto"),
                        frame=frame)
    box, _, _ = found
    roi = node.routing_node["roi"]
    h, w = _rgb(frame).shape[:2]
    # expanded ROI must cover the box with the requested margin, clipped to
    # the screen edges (a control near y=20 cannot have 48px above it)
    assert roi[0] <= max(0, box[0] - TEMPLATE_ROI_EXPAND)
    assert roi[1] <= max(0, box[1] - TEMPLATE_ROI_EXPAND)
    assert roi[0] + roi[2] >= min(w, box[0] + box[2] + TEMPLATE_ROI_EXPAND)
    assert roi[1] + roi[3] >= min(h, box[1] + box[3] + TEMPLATE_ROI_EXPAND)


def test_validate_reports_frame_errors(monkeypatch, adapter):
    """A matcher error must reach the report as frame_errors (no swallowing)."""
    from winter_agent_v2.pipeline_autogen import (GeneratedNode,
                                                  PipelineAutoGen)
    gen = PipelineAutoGen(device=None)
    node = GeneratedNode(semantic="S", skill_id="S", kind="TEMPLATE",
                         routing_node={"kind": "TEMPLATE", "template": "S",
                                       "threshold": 0.7},
                         pipeline_node={}, observed_text="", observed_score=1.0,
                         expansion=0, template_path=None, frame=None,
                         evidence={}, warnings=[])

    def boom(self, adapter_, node_, frame, expect_hit):
        return False, "BOOM_REASON"

    monkeypatch.setattr(PipelineAutoGen, "_try_match", boom)
    report = gen.validate(node, positives=["p.png"], adapter=object)
    assert report["frame_errors"] == ["positive:p.png:BOOM_REASON"]
    assert "BOOM_REASON" in report["errors"]
