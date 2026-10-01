"""The production OCR fallback must not crash when it recognizes daily tasks.

2026-10-01 worker evidence: observing after OPEN_MAP reached DAILY and called
an activity-badge helper that was never implemented. Classifier-only tests had
missed the public observe path, while the static audit allowlisted the defect.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import HybridVision, OCRResult, OCRToken


def _token(text: str, x: int, y: int) -> OCRToken:
    return OCRToken(text, 0.99, ((x, y), (x + 160, y), (x + 160, y + 24), (x, y + 24)))


class _UnknownTemplateVision:
    def observe(self, _frame: Path) -> WorldState:
        return WorldState()


class _CurrentFrameOCR:
    def __init__(self, tokens):
        self.result = OCRResult(tuple(tokens), "current-frame-test")

    def recognize(self, _frame: Path, _roi=None):
        return self.result


@pytest.mark.parametrize("claim_control", [False, True])
def test_public_observe_preserves_actual_daily_controls_and_task_evidence(tmp_path, claim_control):
    frame = tmp_path / "daily.png"
    Image.new("RGB", (720, 1280), "white").save(frame)
    tokens = [
        _token("每日任务", 280, 90),
        _token("325", 560, 300),
        _token("65", 320, 335),
        _token("研究1次科技（0/1）", 60, 695),
        _token("前往", 560, 767),
    ]
    if claim_control:
        tokens.append(_token("一键领取", 300, 1050))

    state = HybridVision(_UnknownTemplateVision(), _CurrentFrameOCR(tokens)).observe(frame)

    assert state.page is Page.DAILY
    assert state.daily["activity"] == 65
    assert state.daily["status"] == ("CLAIMABLE" if claim_control else "AVAILABLE")
    assert state.daily["claimable_count"] == (1 if claim_control else 0)
    task = state.daily["tasks"][0]
    assert task["task_id"] == "DAILY_RESEARCH"
    assert task["source_frame"] == state.daily["source_frame"]
    assert task["timestamp"] == state.daily["observed_at"]
    assert task["timestamp"]


def test_daily_red_artwork_does_not_invent_an_unmeasured_reward_badge(tmp_path):
    frame = tmp_path / "daily_red_artwork.png"
    image = Image.new("RGB", (720, 1280), "white")
    # Even a large red circle is not permission to infer an unknown badge ROI.
    ImageDraw.Draw(image).ellipse((600, 300, 630, 330), fill="red")
    image.save(frame)
    state = HybridVision(
        _UnknownTemplateVision(), _CurrentFrameOCR([_token("每日任务", 280, 90)])
    ).observe(frame)

    assert state.page is Page.DAILY
    assert state.daily["claimable_count"] == 0
    assert state.red_dots["BTN_OPEN_DAILY"]["state"] == "UNKNOWN"
    assert all(record["state"] == "UNKNOWN" for record in state.red_dots.values())
