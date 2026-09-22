"""Keep the test suite out of the AUTO's live learning assets.

Operator directive 2026-09-22 §九: "开发测试使用独立目录，不能覆盖或回滚正式 AUTO 的学习资产".
Measured the same day, and it was not a hypothetical: this store is a module constant pointing at
the live file, several tests drive a whole ``LiveRuntime`` (which writes it back at the end of a
run), and ``learning/control_experience.json`` went from 52 records to 4 across one suite run --
taking with it the L1 registration a real step had just proved on the device.

So every store a test could write through *by default* is redirected to a per-session temporary
directory here, once, for the whole session:

* ``control_experience.STATE_PATH``   the experience ledger (learning/)
* ``ui_collection.CANDIDATE_ROOT``    element candidates (knowledge/perception/candidates/)
* ``page_knowledge.PAGE_ROOT``        unnamed-page candidates (knowledge/perception/pages/)
* ``page_knowledge.TRANSITIONS_PATH`` the learned page transitions (knowledge/ui/)

A test that wants its own paths still passes them explicitly, exactly as before; what changes is
only what "no path given" means inside a test run.  ``online`` no-ops for anyone importing these
modules outside pytest.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience, page_knowledge, ui_collection  # noqa: E402


def _seed(source: Path, target: Path) -> Path:
    """Copy a live asset into the scratch tree so *reads* keep working.

    Redirecting a module constant to a path that does not exist would be a worse bug than the one
    this file fixes: plenty of tests legitimately read the template manifest or the candidate index
    to build a vision layer.  So the live content is copied once per session and only *writes* are
    diverted.  A missing source is not an error -- a fresh checkout simply starts with empty
    scratch assets.
    """
    try:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except OSError:
        pass
    return target


@pytest.fixture(scope="session", autouse=True)
def _protect_the_live_learning_assets():
    scratch = Path(tempfile.mkdtemp(prefix="winter-tests-"))
    previous = {
        control_experience: {"STATE_PATH": control_experience.STATE_PATH},
        ui_collection: {
            "CANDIDATE_ROOT": ui_collection.CANDIDATE_ROOT,
            "TEMPLATE_MANIFEST": ui_collection.TEMPLATE_MANIFEST,
            "TEMPLATE_DIR": ui_collection.TEMPLATE_DIR,
        },
        page_knowledge: {
            "PAGE_ROOT": page_knowledge.PAGE_ROOT,
            "TRANSITIONS_PATH": page_knowledge.TRANSITIONS_PATH,
        },
    }
    control_experience.STATE_PATH = _seed(
        control_experience.STATE_PATH, scratch / "learning/control_experience.json"
    )
    ui_collection.CANDIDATE_ROOT = _seed(
        ui_collection.CANDIDATE_ROOT, scratch / "knowledge/perception/candidates"
    )
    # The template manifest is the one the live vision layer reads: seeded, so a test that builds a
    # vision layer still sees the real templates, while a "learned" template a test might write
    # lands in the copy.
    ui_collection.TEMPLATE_MANIFEST = _seed(
        ui_collection.TEMPLATE_MANIFEST, scratch / "dataset/candidate/template_manifest.json"
    )
    ui_collection.TEMPLATE_DIR = _seed(
        ui_collection.TEMPLATE_DIR, scratch / "dataset/candidate/auto_collected"
    )
    page_knowledge.PAGE_ROOT = _seed(
        page_knowledge.PAGE_ROOT, scratch / "knowledge/perception/pages"
    )
    page_knowledge.TRANSITIONS_PATH = _seed(
        page_knowledge.TRANSITIONS_PATH, scratch / "knowledge/ui/page_transitions.json"
    )
    try:
        yield
    finally:
        for module, attributes in previous.items():
            for name, value in attributes.items():
                setattr(module, name, value)
        shutil.rmtree(scratch, ignore_errors=True)
