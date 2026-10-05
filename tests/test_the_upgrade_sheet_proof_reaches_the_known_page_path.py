"""The upgrade-sheet proof has to reach the path that runs when the template layer *succeeds*.

``upgrade_dialog_visible`` is what the ``OPEN_BUILDING_UPGRADE`` verifier reads
(``runtime.py:548-555``).  Only the OCR **classifier** used to set it, and only inside the branch
that runs when the template layer could not name the page -- so on a frame the template layer
*calls* ``Page.BUILDING``, which is what production mostly gets, the key was simply missing and the
verifier reported ``BUILDING_UPGRADE_PANEL_NOT_PROVEN`` for a sheet that was open and readable.

That is why these tests go through ``_read_building_identity`` (the known-page reader) rather than
through ``OCRPageClassifier.classify``.  A test that called the classifier directly would have
passed the whole time this was broken -- which is the same shape of mistake the surrounding module
documents three times: *a lower layer passing does not mean the production entry point reaches it.*

Frame: the after-shot of the last recorded failure, 2026-10-05T15:52:05Z, kept under
``dataset/truth_audit/`` because ``dataset/raw/control_panel/`` is retention-pruned.  The OCR in it
reads ``城墙 | 升级效果 | 城墙耐久度 | … | 需要条件 | 大熔炉等级29`` -- the header layout an
ordinary selected building is drawn with.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState

FRAME = ROOT / "dataset/truth_audit/building_upgrade_sheet_20261005/after_upgrade_sheet_720x1280.png"


class _TemplateLayerThatNamesThePage:
    """Stands in for the template layer *succeeding* -- the case that used to lose the proof."""

    def observe(self, image_path):  # noqa: ARG002 - the stub answers regardless of the frame
        return WorldState(page=Page.BUILDING, building={})


@pytest.fixture(scope="module")
def vision():
    ocr = pytest.importorskip("winter_agent_v2.ocr")
    return ocr.HybridVision(_TemplateLayerThatNamesThePage(), ocr.OCRService(ocr.RapidOCRBackend()))


def test_the_real_failure_frame_yields_the_proof_the_verifier_asks_for(vision):
    """The exact frame that produced the failure, through the reader production actually uses.

    The frame is **not** in git: ``.gitignore:39`` excludes new ``dataset/truth_audit/**/*.png``,
    and that rule is deliberate -- frames live in the data root, not in the repository.  So this
    skips when the data is absent, and the skip is not evidence that the fix is unverified: the
    run that mattered happened on the frame itself (see the module docstring) and
    ``_building_upgrade_sheet_evidence`` is exercised on synthetic tokens by the classifier's own
    tests regardless.
    """
    if not FRAME.is_file():
        pytest.skip(f"evidence frame missing (data lives outside git): {FRAME}")

    out = vision._read_building_identity(FRAME, WorldState(page=Page.BUILDING, building={}))

    assert out is not None, "this frame is the upgrade sheet; the reader must claim it"
    assert out.page is Page.BUILDING
    assert out.building.get("upgrade_dialog_visible") is True, (
        "the verifier in runtime.py:548-555 reads this key; absent means every correct tap is "
        "recorded as BUILDING_UPGRADE_PANEL_NOT_PROVEN"
    )


def test_the_fix_does_not_claim_the_sheet_on_a_non_building_frame(vision, tmp_path):
    """The key may only be corroboration for a BUILDING page, never a relabelling.

    A HOME frame is the one case the same function also accepts, so the guard that keeps
    ``upgrade_dialog_visible`` off it is what stops the verifier from crediting a tap that never
    left the city.
    """
    out = vision._read_building_identity(FRAME, WorldState(page=Page.MAP, building={}))
    assert out is None, "MAP is neither the dialog nor the selected-building city frame"
