"""The constitutional gate, as a test.

`tools/check_coordinate_hardcoding.py` can be run by hand, and a gate that is only run by
hand is a gate that gets skipped.  These tests make the constitution part of the suite:

    §二  本约束不设置生产点击例外
    §八  任何新增或修改的生产操作，如果不能证明点击目标来自当前 UI 元素识别，
         不得接入正式 AUTO

The four checks are deliberately different in kind, because a single "grep for tap(x, y)"
cannot see the evasions §八 names:

1. **The whole gate reports no violation.**  Broadest; catches a literal reintroduced
   anywhere in a scanned production module.
2. **The two specific removals stay removed**, by *behaviour* rather than by source text --
   a source assertion would be defeated by a rename, which is the §八 evasion.
3. **A frame-less resolver answers ``None``.**  The constitutional contract itself: no
   evidence of the current frame, no tap.  Driven through the real object, so it holds
   whatever the code is named.
4. **The gate can actually fail.**  A test that cannot fail proves nothing, so the
   detector is exercised against a planted literal.

Why (2) is behavioural: ``_remembered_control_center`` must not be reachable from
``_resolve_semantic_target``.  Reading the source and looking for the *name* would pass if
someone aliased it; asking the resolver for an answer on a frame with a populated ledger is
the property that actually matters.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GATE = ROOT / "tools/check_coordinate_hardcoding.py"


def _run_gate() -> dict:
    proc = subprocess.run(
        [sys.executable, str(GATE), "--json"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert proc.stdout, f"gate produced no output; stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def test_the_gate_reports_no_violation():
    """§八: no production module may carry a coordinate-driven tap."""
    report = _run_gate()
    violations = [f for f in report["findings"] if f["severity"] == "VIOLATION"]
    assert not violations, (
        "the admission gate found coordinate-hardcoding violations:\n"
        + "\n".join(f"  {v['kind']} {v['where']}: {v['detail']}" for v in violations)
    )
    assert report["stats"]["violations"] == 0


def test_the_gate_scans_a_real_set_of_production_modules():
    """A gate that scans nothing passes trivially; this pins that it is looking."""
    report = _run_gate()
    assert report["stats"]["production_modules"] >= 15, (
        "the scanned module list has shrunk to the point where the gate proves nothing"
    )
    # And it must actually reach the tap path, not just peripheral modules.
    where = " ".join(f["where"] for f in report["findings"])
    assert "executor.py" in where or any(
        "runtime.py" in f["where"] for f in report["findings"]
    ), "the gate must cover the executor and the resolver"


def test_the_removed_ledger_tier_cannot_answer_a_tap_even_with_a_full_ledger():
    """§一.3/§一.5/§一.6, by behaviour rather than by symbol.

    Builds the exact ledger entry that used to be spent -- a resolved ``PAGE_MAP`` control
    with a measured position on HOME, the shape the live file is really in -- and asks the
    **tap resolver** for a point.  It must not answer with the stored coordinate.

    Asserting on the symbol ``_remembered_control_center`` in the source body would be the
    §八 evasion: rename the method and the test passes while the behaviour returns.
    """
    from winter_agent_v2 import control_experience
    from winter_agent_v2.models import Page, WorldState

    frame = ROOT / "dataset/truth_audit/role_identity_20260916/profile_panel_live_20260916T184004.png"
    entry = control_experience.ControlExperience(
        page="HOME", control="PAGE_MAP",
        position_norm=(0.9236, 0.9539),
        read_from_frame=str(frame),
        known_result="PAGE_MAP", known_change="PAGE_CHANGED",
        attempts=5, last_result="PAGE_CHANGED",
        last_at="2026-09-22T00:00:00+00:00",
    )

    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime._control_ledger = {"HOME|PAGE_MAP": entry}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_screen_refusals = set()
    runtime._printed_declared_refusals = set()

    world = WorldState(page=Page.HOME)
    point = runtime._resolve_semantic_target("PAGE_MAP", world)

    assert point != (0.9236, 0.9539), (
        "the tap resolver answered with the ledger's stored coordinate; the constitution "
        "forbids a stored position from becoming a click target (§一.3/§一.5/§一.6)"
    )
    assert runtime._remembered_reuse == [], (
        "and it must not even report a reuse: the ledger is diagnostic now, not a resolver"
    )


def test_no_frame_means_no_tap():
    """The contract in one line: no current-frame evidence, no click (§五/§二).

    A semantic the project has never registered, on a frame that cannot be read, must
    resolve to ``None`` -- which the executor turns into ``SEMANTIC_TARGET_NOT_VERIFIED``,
    ending the step instead of tapping an invented point.
    """
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_screen_refusals = set()
    runtime._printed_declared_refusals = set()

    point = runtime._resolve_semantic_target(
        "A_CONTROL_THIS_PROJECT_HAS_NEVER_SEEN", WorldState(page=Page.HOME)
    )
    assert point is None, (
        "an unknown control on an unread frame must resolve to nothing; anything else is an "
        "invented click target"
    )


def _load_gate_module():
    """Import the gate as a module object so its detectors can be exercised directly.

    ``sys.modules`` must be populated *before* ``exec_module``: the gate defines a
    ``@dataclass``, and ``dataclasses`` resolves annotations through
    ``sys.modules[cls.__module__]``.  Without the registration the exec raises
    ``AttributeError: 'NoneType' object has no attribute '__dict__'`` from inside the
    stdlib -- which reads like a gate bug and is not one.
    """
    import importlib.util

    name = "coord_gate_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_gate_can_fail_on_a_planted_literal():
    """A detector that cannot fail is not a detector.

    Plants the exact shape the gate exists to catch -- a float-pair literal returned from a
    resolver -- and asserts the detector sees it.  Does not touch the real runtime; the
    literal is fed straight to the scanner.
    """
    gate = _load_gate_module()

    planted = '''
def _resolve_semantic_target(self, semantic, frame):
    if semantic == "SOMETHING":
        return (0.86, 0.68)
    return None
'''
    literals = gate._float_pair_literals(gate._code_only(planted))
    assert (0.86, 0.68) in literals, "the detector missed the literal it exists to catch"

    # And the bounds must NOT be reported: (0.0, 1.0) is a validation range, not a position.
    bounds = '''
def _resolve_semantic_target(self, semantic, frame):
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
'''
    assert gate._float_pair_literals(gate._code_only(bounds)) == [], (
        "validation bounds are not coordinate literals; reporting them would make the gate "
        "unusable and train everyone to ignore it"
    )


def test_the_detector_ignores_docstrings_that_merely_quote_the_defect():
    """The removals are documented in place and quote their own forbidden values.

    ``runtime.py``'s comments and docstrings name ``(0.86, 0.68)`` and ``(0.8819, 0.3563)``
    to explain what was removed.  A scanner that reads the explanation as the offence would
    fail the very commit that fixed it -- so the detector must look at code, not prose.
    """
    gate = _load_gate_module()

    documenting = '''
def _resolve_semantic_target(self, semantic, frame):
    """REMOVED: a literal (0.86, 0.68) used to be returned here."""
    # the ledger held (0.8819, 0.3563) and was spent on the wrong panel
    return None
'''
    assert gate._float_pair_literals(gate._code_only(documenting)) == [], (
        "a docstring quoting a removed literal is not a live literal"
    )
