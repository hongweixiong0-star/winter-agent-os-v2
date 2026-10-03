"""A barracks that can be started must hand over the point that starts it.

Measured 2026-10-03, episode ``20261003_223009_533887``.  The route reached ``Page.TRAINING``,
``SELECT_TRAINING_CAMP`` switched to 射手营, and the reading said exactly what it should:

    {"troop_type": "MARKSMAN", "status": "AVAILABLE", "queue_available": true, "trainable": true}

-- and carried no ``train_button_norm``.  With no train point, ``TRAIN_TROOPS`` could not
resolve, the registry offered only ``BACK``, the brain fell through to ``TRY_ORDINARY_CONTROL``
(``goal_TRAIN_has_only_BACK_left_on_this_page``), and the run left the page having trained
nothing:

    14:33:08 OPEN_INFANTRY_TRAINING  ft=None        page=TRAINING
    14:33:14 SELECT_TRAINING_CAMP    ft=None        page=TRAINING
    14:33:16 TRY_ORDINARY_CONTROL    ft=SEMANTIC_TARGET_NOT_VERIFIED
    14:33:21 BACK                    ft=None        page=HOME

The cause is one condition, and it covered the wrong half of the page.  ``HybridVision`` merges
a second OCR reading into the training state only when ``status == "IN_PROGRESS"`` -- the state
where a *timer* is what is wanted, and where nothing needs starting.  In ``AVAILABLE`` it never
ran, which is the one state where the coordinate decides whether anything happens at all.

Both directions are pinned: the merge must fire when the point is missing, and must not spend a
second OCR pass when the reading is already complete.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

#: The recorded after-frame of ``SELECT_TRAINING_CAMP``: 射手营 selected, queue free.  This is
#: the frame production read and got no train point from.
AVAILABLE_FRAME = Path(
    r"E:\无尽冬日智能体\dataset\raw\control_panel\runtime_auto\20261003_223009_533887"
    r"\20261003_223009_533887_step_014_after_refresh_1_20261003T143313279833.png"
)
#: The next step's before-frame: same page, same state.
AVAILABLE_FRAME_2 = Path(
    r"E:\无尽冬日智能体\dataset\raw\control_panel\runtime_auto\20261003_223009_533887"
    r"\20261003_223009_533887_step_015_before_20261003T143314860184.png"
)
#: The 盾兵营 frame: a queue running (status=IN_PROGRESS), which is what the old condition did
#: cover.
BUSY_FRAME = Path(
    r"E:\无尽冬日智能体\dataset\raw\control_panel\runtime_auto\20261003_223009_533887"
    r"\20261003_223009_533887_step_014_before_20261003T143308507286.png"
)


def _vision():
    """The real stack.  Skips rather than fails when OCR or the manifest is unavailable."""
    try:
        from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision
    except Exception as exc:  # noqa: BLE001
        pytest.skip("stack unavailable: %s" % exc)
    manifest = ROOT / "dataset/candidate/template_manifest.json"
    if not manifest.is_file():
        pytest.skip("template manifest missing")
    try:
        ocr = OCRService(RapidOCRBackend())
    except Exception as exc:  # noqa: BLE001
        pytest.skip("RapidOCR unavailable: %s" % exc)
    return HybridVision(SemanticWorldVision(manifest), ocr)


class TheTrainableBarracksHandsOverItsPointTests:
    def test_the_frame_production_could_not_train_from_now_carries_the_point(self):
        """The regression, on the recorded frame, through the whole stack."""
        if not AVAILABLE_FRAME.is_file():
            pytest.skip("archived frame missing")
        state = _vision().observe(AVAILABLE_FRAME)
        training = state.training or {}
        assert training.get("status") == "AVAILABLE", training
        assert training.get("trainable") is True, training
        assert training.get("train_button_norm"), (
            "AVAILABLE with trainable=true and no train point is exactly the state that left "
            "the run standing on a barracks doing nothing: %r" % (training,)
        )

    def test_both_recorded_available_frames_agree(self):
        """Two consecutive frames of the same page must not disagree about the control."""
        frames = [f for f in (AVAILABLE_FRAME, AVAILABLE_FRAME_2) if f.is_file()]
        if len(frames) < 2:
            pytest.skip("archived frames missing")
        vision = _vision()
        points = []
        for frame in frames:
            training = vision.observe(frame).training or {}
            assert training.get("status") == "AVAILABLE", training
            points.append(tuple(training.get("train_button_norm") or ()))
        assert points[0] == points[1], points
        assert points[0], points

    def test_a_busy_queue_still_reads_its_timer(self):
        """The half the old condition did cover must not regress."""
        if not BUSY_FRAME.is_file():
            pytest.skip("archived frame missing")
        training = _vision().observe(BUSY_FRAME).training or {}
        assert training.get("status") == "IN_PROGRESS", training
        assert training.get("timer"), training


class TheConditionCoversBothStatesTests:
    """The gate itself, stated as code rather than inferred from a frame.

    Reading the branch's source is the honest way to pin this: the defect was that one state
    was absent from it, and a frame test can only show the symptom.
    """

    def _source(self) -> str:
        return (ROOT / "winter_agent_v2/ocr.py").read_text(encoding="utf-8")

    def test_the_training_merge_names_both_states(self):
        source = self._source()
        assert "needs_timer" in source and "needs_train_point" in source, (
            "the training merge must distinguish the two reasons it can be needed"
        )
        assert "needs_timer or needs_train_point" in source, (
            "gating on needs_timer alone is the original defect: it fires while a queue is "
            "busy and stays silent when the coordinate is the thing that matters"
        )

    def test_the_available_reason_is_the_missing_point(self):
        source = self._source()
        assert 'primary.training.get("status") == "AVAILABLE"' in source
        assert 'primary.training.get("train_button_norm") is None' in source, (
            "the merge should only spend a second OCR pass when the point is actually absent"
        )
