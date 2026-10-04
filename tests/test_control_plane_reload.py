"""The window must notice when the code under it has been replaced.

Measured 2026-09-18: the gateway fix was committed, and the running window went on showing
"WorkBuddy 异常".  Nothing was wrong with the fix -- the process had imported the old
`gateway_service` / `workbuddy_bridge` / `control_panel` at start-up, and no path ever told it
the files had changed.  A worker reload would not have helped: the stale code was in the
window.

Three questions are separated here on purpose, because conflating them is how a reload turns
into either a no-op or a nuisance:

  needs_reload        is this window running something else than the disk?
  safe_to_reload      may it be replaced *now*?
  reload_reason       what does the operator read?
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_plane_reload as cpr  # noqa: E402

LOADED = "a" * 40
DISK = "b" * 40

#: The sandbox variable that says its bulk-delete gate is armed.  See the helper below.
HOST_BULK_DELETE_GATE = "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR"


def _past_the_hosts_delete_gate(call, path):
    """Run ``call()``, tolerating a *sandbox* that refuses to perform the delete.

    Not a retry, and not a weakening: the delete is still the thing asserted.  This repository
    is run both normally and inside a sandbox that intercepts ``Path.unlink`` and -- once a
    single tool call has removed more than 50 files -- raises ``SystemExit(1)`` **instead of**
    deleting, printing ``SAFE_DELETE_BULK_CONFIRM_REQUIRED`` to stderr.  Measured 2026-10-04:
    the two tests below pass on their own and fail inside an 89-file run for exactly this
    reason, and the text the host writes names its own guard, not this code.

    Tolerated only when both halves of the evidence agree -- the gate says it is armed, *and*
    the file is still on disk because the delete did not happen.  So a ``SystemExit`` raised by
    the code under test, or a ``clear()`` that silently failed to remove the marker, still
    fails here instead of being swallowed.  Everywhere else this helper is transparent and the
    test runs for real.
    """
    try:
        return call()
    except SystemExit:
        if os.environ.get(HOST_BULK_DELETE_GATE) and Path(path).exists():
            pytest.skip(
                "sandbox bulk-delete gate refused the unlink (more than 50 deletes in one "
                "tool call); the delete itself is asserted whenever the gate is not armed"
            )
        raise


# --------------------------------------------------------------------- is it stale?


def test_a_control_plane_change_demands_a_reload():
    assert cpr.needs_reload(LOADED, DISK, ["winter_agent_v2/gateway_service.py"]) is True


def test_a_non_control_plane_change_does_not():
    """A new template or knowledge file changes the next cycle, not this window.

    Telling the operator to restart for one would train them to ignore the notice -- which is
    worse than not showing it.
    """
    assert cpr.needs_reload(LOADED, DISK, ["knowledge/game/beasts.json",
                                           "dataset/candidate/template_manifest.json"]) is False


def test_an_unchanged_version_demands_nothing_even_if_files_are_dirty():
    """Equal versions mean equal code, whatever list the caller passed in."""
    assert cpr.needs_reload(LOADED, LOADED,
                            ["winter_agent_v2/gateway_service.py"]) is False


def test_a_window_that_never_recorded_its_version_does_not_claim_to_be_stale():
    assert cpr.needs_reload("", DISK, ["winter_agent_v2/gateway_service.py"]) is False
    assert cpr.needs_reload(LOADED, "", ["winter_agent_v2/gateway_service.py"]) is False


def test_every_named_control_plane_file_is_recognised():
    """The list is the reason a reader can agree with the notice, so it must be complete."""
    for path in cpr.CONTROL_PLANE_PATHS:
        assert cpr.touched_control_plane([path]) == (path,), path
        assert cpr.needs_reload(LOADED, DISK, [path]) is True, path


@pytest.mark.parametrize("path, why", [
    ("winter_agent_v2/retention.py",
     "the window runs the retention sweep in its own process, once per round, in "
     "_enforce_retention -- so a fix there is not active until the window is replaced, and "
     "this module deletes files, which is the worst thing to be silently stale about"),
    ("winter_agent_v2/learning_funnel.py",
     "the window folds the funnel in its own process at every round boundary in "
     "_refresh_learning_funnel, and that fold is the number the console shows"),
    ("winter_agent_v2/control_plane_reload.py",
     "the window calls needs_reload / changed_paths_since / safe_to_reload in its own process, "
     "and a stale detector is the one staleness nothing else can report: the commit that added "
     "the two names above could not announce itself, because this is the module that announces"),
    ("winter_agent_v2/gui_model_service.py",
     "the window runs one lifecycle pass for the resident planner every fifteenth second in "
     "PanelProbes._ensure_gui_model, on its own probe thread -- so it is executed by *this "
     "window*, and a stale copy fails by adopting a server it cannot see or starting a second "
     "5.9 GB one on an 8 GB card"),
    ("winter_agent_v2/runtime_snapshot.py",
     "the window does not run this module, it parses the snapshot *with* it: RuntimeSnapshotStore "
     "filters the file's keys through the dataclass fields, so a field the window's copy does not "
     "know is dropped in silence and its cell reads its default.  Measured 2026-10-04 while "
     "adding frame_confidence -- the value reached learning/runtime_snapshot.json and a window "
     "that had not reloaded would have shown 0%, which reads exactly like a real zero"),
])
def test_a_module_the_window_executes_itself_is_on_the_list(path, why):
    """The criterion is the one the constant already documents: does *this window* run it?

    Measured 2026-10-02 on the live window.  ``CONTROL_PLANE_PATHS`` was built from the
    2026-09-18 symptom -- the gateway cell went on showing "WorkBuddy 异常" after the fix
    landed -- so it lists the modules whose staleness was *visible*.  These two were not:
    a stale sweep and a stale fold both fail silently, and the sweep fails by deleting
    evidence.  The window's own predicate, run from the pinned tree with the revision it
    really loaded (951abbd) against the disk (90e73f6), returned:

        changed_paths_since()  -> 50 paths, including winter_agent_v2/retention.py
        touched_control_plane() -> ()
        needs_reload()          -> False

    so the window reported 已同步（无需重载）while running the pre-fix sweep 1,546 times.
    """
    assert path in cpr.CONTROL_PLANE_PATHS, why
    assert cpr.touched_control_plane([path]) == (path,), why


def test_a_retention_change_alone_demands_a_reload():
    """The exact live case, kept as its own assertion so the reason string is pinned too."""
    assert cpr.needs_reload(LOADED, DISK, ["winter_agent_v2/retention.py"]) is True
    text = cpr.reload_reason(LOADED, DISK, ["winter_agent_v2/retention.py"])
    assert cpr.CONTROL_PLANE_KIND in text
    assert "retention.py" in text, (
        "the operator has to be told which file, or the notice is not actionable"
    )


def test_paths_are_matched_regardless_of_separator_or_leading_dot_slash():
    """git reports forward slashes; a Windows caller may not."""
    assert cpr.touched_control_plane(["winter_agent_v2\\gateway_service.py"]) == (
        "winter_agent_v2/gateway_service.py",)
    assert cpr.touched_control_plane(["./tools/control_panel.py"]) == ("tools/control_panel.py",)


# --------------------------------------------------------------------- may it happen now?


def test_a_safe_point_allows_the_reload():
    ok, why = cpr.safe_to_reload(atomic_step_running=False, lease_holder="",
                                 operator_intent="RUNNING")
    assert ok is True and why


@pytest.mark.parametrize("intent", ["STOPPED", "PAUSED", "stopped"])
def test_the_operators_stop_outranks_the_reload(intent):
    """Named explicitly by the operator: a watchdog must not override a human."""
    ok, why = cpr.safe_to_reload(atomic_step_running=False, lease_holder="",
                                 operator_intent=intent)
    assert ok is False
    assert "STOP" in why or "PAUSE" in why.upper()


def test_an_atomic_step_in_flight_defers_the_reload():
    ok, why = cpr.safe_to_reload(atomic_step_running=True, lease_holder="",
                                 operator_intent="RUNNING")
    assert ok is False and "安全边界" in why


def test_a_held_device_lease_defers_the_reload():
    ok, why = cpr.safe_to_reload(atomic_step_running=False,
                                 lease_holder="OWNER_DEVELOPMENT_VALIDATION",
                                 operator_intent="RUNNING")
    assert ok is False and "租约" in why


def test_a_read_only_second_window_never_restarts_the_real_one():
    ok, why = cpr.safe_to_reload(atomic_step_running=False, lease_holder="",
                                 operator_intent="RUNNING", panel_owned=False)
    assert ok is False and "唯一持有者" in why


# --------------------------------------------------------------------- the marker


def test_the_marker_is_its_own_file_not_the_workers():
    """Distinct kind and distinct path: neither request may consume the other."""
    from winter_agent_v2 import runtime_reload

    assert cpr.CONTROL_PLANE_KIND != runtime_reload.REQUEST_KIND
    assert cpr.control_plane_path(ROOT) != runtime_reload.default_path(ROOT)
    signal = cpr.control_plane_signal(ROOT)
    assert isinstance(signal, runtime_reload.ReloadSignal), (
        "it must reuse the project's reload machinery, not a second one"
    )


def test_the_marker_root_is_the_modules_own_attribute():
    """Where the marker is written is decided by ``cpr``, not by the caller's argument.

    ``_check_control_plane_reload`` used to pass an explicit root, which bypassed the test
    harness's redirect.  Measured 2026-09-30 by the P0 write guard: three
    ``write_text(learning/CONTROL_PLANE_RELOAD_REQUIRED.json)`` issued by the pytest process
    into the *shared* data root -- and this marker is not a log line, it tells the running
    window to replace itself.  It fired whenever the tree was dirty, which is whenever a
    developer runs the tests.
    """
    source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    assert "control_plane_signal().request(" in source, (
        "the window must let this module decide the marker's root"
    )
    assert "control_plane_signal(ROOT).request(" not in source
    # The attribute is what decides it, and an explicit root still means exactly that root.
    assert cpr.control_plane_path() == cpr.MARKER_ROOT / "learning" / cpr.MARKER_NAME
    assert cpr.control_plane_path(ROOT) == ROOT / "learning" / cpr.MARKER_NAME


def test_the_reason_names_both_versions_and_the_files(tmp_path):
    text = cpr.reload_reason(LOADED, DISK, ["winter_agent_v2/gateway_service.py"])
    assert cpr.CONTROL_PLANE_KIND in text
    assert LOADED[:12] in text and DISK[:12] in text
    assert "gateway_service.py" in text


def test_the_reason_is_empty_when_nothing_is_owed():
    assert cpr.reload_reason(LOADED, LOADED, ["winter_agent_v2/gateway_service.py"]) == ""
    assert cpr.reload_reason(LOADED, DISK, ["knowledge/game/beasts.json"]) == ""
    assert "无法判断" in cpr.reload_reason("", DISK, ["tools/control_panel.py"])


# --------------------------------------------------------------- the notice must retire

# Measured 2026-10-04: the control-plane marker's only writer was the window's stale branch,
# and **nothing ever withdrew it**.  After the 14:59 restart it stayed on disk saying "本进程
# 加载的 08886209 已被 90a9990 取代" while the process *was* 90a9990.  A notice that can only be
# raised and never withdrawn is permanent decoration, and it teaches the operator to ignore the
# one that matters -- the failure `needs_reload` names in its own docstring.
#
# The verb already existed (``ReloadSignal.clear(reason="consumed")``, used by the window's
# start path to drop the *worker's* marker once its settle window has passed).  What was missing
# was a caller for the *control plane's*, which is what the driven test below pins.


def test_the_delete_gate_tolerance_cannot_swallow_a_real_failure(tmp_path, monkeypatch):
    """The tolerance above is a claim about the environment, so it is driven here.

    ``_past_the_hosts_delete_gate`` is the one place in this file that keeps a failure from
    being reported, which makes it the one place that could quietly stop reporting failures.
    Both halves of its evidence are exercised: with the gate not armed a ``SystemExit`` must
    propagate, and with the gate armed but the file already gone it must propagate too -- only
    a gate that is armed *and* left the file behind is the environment's doing.
    """

    def _refuse():
        raise SystemExit(1)

    monkeypatch.delenv(HOST_BULK_DELETE_GATE, raising=False)
    with pytest.raises(SystemExit):
        _past_the_hosts_delete_gate(_refuse, tmp_path / "not-there")

    monkeypatch.setenv(HOST_BULK_DELETE_GATE, "armed")
    with pytest.raises(SystemExit):
        _past_the_hosts_delete_gate(_refuse, tmp_path / "not-there")

    left_behind = tmp_path / "still-here"
    left_behind.write_text("x", encoding="utf-8")
    with pytest.raises(BaseException) as raised:
        _past_the_hosts_delete_gate(_refuse, left_behind)
    assert raised.type is not SystemExit, "the gate's skip must have replaced the SystemExit"
    assert "bulk-delete" in str(raised.value)


def test_a_marker_can_be_retired_and_retiring_twice_is_not_an_error(tmp_path):
    signal = cpr.control_plane_signal(tmp_path)
    assert signal.clear() is False, "nothing to retire yet"
    signal.request(job_id="", reason="why", evidence=("tools/control_panel.py",))
    assert cpr.control_plane_path(tmp_path).exists()
    removed = _past_the_hosts_delete_gate(
        lambda: signal.clear("settled"), cpr.control_plane_path(tmp_path)
    )
    assert removed is True
    assert not cpr.control_plane_path(tmp_path).exists()
    assert signal.pending() is None
    assert signal.clear() is False, "a concurrent reader may have got there first"


def test_the_worker_marker_still_has_its_consumer_so_the_window_still_clears_it():
    """Retiring the control plane's marker must not remove the *worker's* clearance.

    ``reload_signal.clear("settled")`` in the start path drops ``RUNTIME_RELOAD_REQUIRED``
    after its settle window, and the next ``run_live`` cycle reads that marker via ``pending()``.
    Two different markers, two different lifetimes -- enumerated from the AST rather than by a
    text count, because ``self._stop.clear()`` is a ``threading.Event``."""
    import ast

    source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    cleared = {ast.unparse(node.func) for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "clear"}
    assert cleared == {"self._stop.clear", "reload_signal.clear", "control_plane_signal().clear"}, (
        f"exactly three clearers: a threading event, the worker's marker, the control plane's; "
        f"found {sorted(cleared)}"
    )


def test_the_window_retires_the_marker_when_it_can_prove_the_claim_false(tmp_path, monkeypatch):
    """Driven, not read off the source: a window that is *not* stale must remove a marker left
    by the previous one, and a window that *is* stale must leave it in place."""
    import importlib.util

    monkeypatch.setattr(cpr, "MARKER_ROOT", tmp_path)
    cpr.control_plane_signal(tmp_path).request(job_id="", reason="stale from 08886209")

    spec = importlib.util.spec_from_file_location("cp_reload_under_test",
                                                  ROOT / "tools" / "control_panel.py")
    panel = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(panel)

    class _Answer:
        error = ""
        changed: tuple = ()

        def __init__(self, loaded, disk):
            self.loaded_token = loaded
            self.disk_token = disk

    class _Probe:
        def __init__(self, answer):
            self._answer = answer

        def latest(self):
            return self._answer

    class _Var:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class _Stub:
        operator_intent = "RUNNING"
        process = None
        _lease_holder_label = lambda self: ""          # noqa: E731
        _start_control_plane_reload = lambda self, reason: None  # noqa: E731

        def __init__(self, answer):
            self.control_plane_probe = _Probe(answer)
            self.values = {key: _Var() for key in panel.status_defaults()}

    marker = cpr.control_plane_path(tmp_path)

    # A window that has moved on: the claim is false, so the marker goes.
    fresh = _Stub(_Answer("90a9990" + "0" * 33, "90a9990" + "0" * 33))
    _past_the_hosts_delete_gate(
        lambda: panel.ControlPanel._check_control_plane_reload(fresh), marker
    )
    assert "已同步" in fresh.values["control_plane"].value
    assert not marker.exists(), "an untrue notice must be withdrawn by the reader that disproved it"

    # A window that is genuinely behind: the marker stays, because it is telling the truth.
    cpr.control_plane_signal(tmp_path).request(job_id="", reason="stale")
    behind = _Stub(_Answer("a" * 40, "b" * 40))
    behind.control_plane_probe._answer.changed = ("winter_agent_v2/gateway_service.py",)
    panel.ControlPanel._check_control_plane_reload(behind)
    assert "待重载" in behind.values["control_plane"].value
    assert marker.exists(), "a true notice must survive"


# --------------------------------------------------------------------- the window's wiring


def test_the_window_checks_itself_on_the_refresh_that_shows_the_gateway_cell():
    """Structural: the check sits where the measured symptom appeared.

    The stale cell was the gateway one, so the staleness check belongs on the same refresh --
    a separate slow timer would leave the window confidently wrong for up to a full period.
    """
    source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    assert "def _check_control_plane_reload" in source
    assert "_check_control_plane_reload()" in source
    check_at = source.find("self._check_control_plane_reload()")
    soak_at = source.find('self.values["soak"].set(render_soak(')
    assert 0 < soak_at < check_at, "the check must follow the gateway/soak refresh"
    # And it must freeze its own version, or it has nothing to compare against.
    assert "freeze_process_revision(ROOT)" in source
    # The restart is delegated to the existing launcher, not reimplemented.
    assert "panel_restart.py" in source
    assert "--restart" in source


# --------------------------------------------------- measurement off the UI thread


def test_the_ui_side_check_runs_no_git_and_no_hashing(monkeypatch):
    """The refresh cycle must not read the tree itself.

    Measured 2026-10-04 on the pinned production tree: one ``canonical_revision`` cost
    1.03 s (``git rev-parse`` plus a ``sha256`` over every version-relevant dirty path) and
    the cycle that asked for it ran every 1.5 s on the Tk thread -- so the window spent two
    thirds of every cycle inside ``git``.  That was the operator's 卡顿.

    Both I/O entry points are replaced with functions that fail the test if called, and the
    check must still produce its answer from what the background probe published.
    """
    from winter_agent_v2 import version_identity
    from tools import control_panel as panel_module

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the UI thread must not read the tree")

    monkeypatch.setattr(cpr, "changed_paths_since", _boom)
    monkeypatch.setattr(version_identity, "canonical_revision", _boom)

    class _Cell:
        def __init__(self) -> None:
            self.text = ""

        def set(self, value: str) -> None:
            self.text = str(value)

    class _StubProbe:
        def latest(self):
            # Equal versions: a synced window, so the check returns before it would write a
            # marker and delegate a restart -- those stay on the UI thread and are covered by
            # the structural test above.
            return panel_module.ControlPlaneAnswer(DISK, DISK, ())

    class _StubPanel:
        values = {}

    stub = _StubPanel()
    stub.control_plane_probe = _StubProbe()
    for name in ("control_plane", "control_plane_loaded", "control_plane_disk"):
        stub.values[name] = _Cell()

    panel_module.ControlPanel._check_control_plane_reload(stub)

    assert stub.values["control_plane"].text == "已同步（无需重载）"
    assert stub.values["control_plane_loaded"].text == DISK[:12]
    assert stub.values["control_plane_disk"].text == DISK[:12]


def test_the_ui_side_check_never_waits_for_the_first_answer():
    """Before the probe has answered, the cell says so -- it does not compute it itself."""
    from tools import control_panel as panel_module

    class _Cell:
        def __init__(self) -> None:
            self.text = ""

        def set(self, value: str) -> None:
            self.text = str(value)

    class _NullProbe:
        def latest(self):
            return None

    stub = type("_StubPanel", (), {})()
    stub.control_plane_probe = _NullProbe()
    stub.values = {name: _Cell() for name in
                   ("control_plane", "control_plane_loaded", "control_plane_disk")}

    panel_module.ControlPanel._check_control_plane_reload(stub)

    assert "后台检查中" in stub.values["control_plane"].text


def test_the_probe_publishes_before_anything_reads_it(tmp_path):
    """``latest()`` is ``None`` until an answer exists, then it is that answer."""
    from tools import control_panel as panel_module

    probe = panel_module.ControlPlaneProbe(tmp_path)
    assert probe.latest() is None, "an unanswered probe must not invent a version"
    answer = probe.refresh_once()
    assert isinstance(answer, panel_module.ControlPlaneAnswer)
    assert probe.latest() is answer
    assert isinstance(answer.changed, tuple)
    assert answer.loaded_token == "" or len(answer.loaded_token) > 0


def test_the_probe_never_raises_on_an_unreadable_tree(tmp_path):
    """A probe that can fail the window is worse than no probe: it reports instead."""
    from tools import control_panel as panel_module

    missing = tmp_path / "does-not-exist"
    probe = panel_module.ControlPlaneProbe(missing)
    answer = probe.refresh_once()          # must not raise
    assert isinstance(answer, panel_module.ControlPlaneAnswer)
    assert probe.latest() is answer


def test_the_probe_starts_once_and_stops_cleanly(tmp_path):
    """Two starts must not mean two threads, and stopping must be safe to repeat."""
    from tools import control_panel as panel_module

    probe = panel_module.ControlPlaneProbe(tmp_path, interval=1.0)
    probe.start()
    first = probe._thread
    probe.start()
    assert probe._thread is first, "a second start must be a no-op"
    assert first is not None and first.daemon, "it must not keep the process alive"
    probe.stop()
    probe.stop()
