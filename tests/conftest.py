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
* ``unknown_advisor.REQUEST_ROOT``    the UNKNOWN question queue (learning/unknown_requests/)
* ``control_panel.PUMP_STATE_PATH``   the AUTO queue clock's ownership heartbeat
* ``control_panel.PANEL_LOG_PATH``    the panel log, its pid file and its gateway probe

The last two were added 2026-09-30, after the pump's heartbeat was measured to be the reason
AUTO would not start.  ``QueuePump._write_state`` writes ``PUMP_STATE_PATH`` and stamps it with
``os.getpid()``, and that path resolves to the *live* ``learning/control_panel/pump.json`` in a
plain test process.  So any test that ticks a real pump claimed the production clock:

    03:41:11  另一个实例正在运行（pid 3168）：本窗口只读，不消费队列、不启动 AUTO、不申请设备租约。
    03:42:00  不自动启动 AUTO：另一个实例（pid 3168）正在运行。本窗口只读。

pid 3168 did not exist; it was a test process that had already exited, and ``panel_clock_owner``
read it out of the live heartbeat file.  Sampled every 20 s during the outage the file named
3168, then 29048 (a running pytest), then the panel's own pid -- three owners in ninety seconds,
none of them the panel.  ``PANEL_LOG_PATH`` is redirected with it because ``panel_pid_path()``,
``gateway_probe_path()`` and the log the operator reads are all derived from it, so a test that
appended a line -- or wrote a pid the restart tool would then try to kill -- did it to the live
files.

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

from tools import control_panel  # noqa: E402
from winter_agent_v2 import (  # noqa: E402
    control_experience,
    page_knowledge,
    ui_collection,
    unknown_advisor,
)


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
        unknown_advisor: {"REQUEST_ROOT": unknown_advisor.REQUEST_ROOT},
        control_panel: {
            "PUMP_STATE_PATH": control_panel.PUMP_STATE_PATH,
            "PANEL_LOG_PATH": control_panel.PANEL_LOG_PATH,
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
    # Not seeded: a test run starts with an empty question queue.  Copying the live requests would
    # hand a test the AUTO's real questions -- and, with the dispatcher in the loop, would let a test
    # suite dispatch jobs about screens the device really asked about.
    unknown_advisor.REQUEST_ROOT = scratch / "learning/unknown_requests"
    # Not seeded either, and for the same reason: a seeded heartbeat would hand a test the pid of
    # whichever process is really ticking the clock, and a panel under test would then read itself
    # as the *second* instance.  An empty heartbeat is what "no owner" honestly looks like.
    control_panel.PUMP_STATE_PATH = scratch / "learning/control_panel/pump.json"
    # Seeded, because the log is read by tests that parse it for real lines.
    control_panel.PANEL_LOG_PATH = _seed(
        control_panel.PANEL_LOG_PATH, scratch / "learning/control_panel/panel.log"
    )
    try:
        yield
    finally:
        for module, attributes in previous.items():
            for name, value in attributes.items():
                setattr(module, name, value)
        shutil.rmtree(scratch, ignore_errors=True)
