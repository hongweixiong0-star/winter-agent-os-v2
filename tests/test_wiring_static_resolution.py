"""Guard the static resolution checkers in tools/check_wiring.py.

Origin: failure 0aw (2026-09-15).  ``HybridVision.observe`` called
``self._next_supply_seconds(...)``, a method defined on no class.  The call is
syntactically valid Python, so every gate the project had -- import, pytest, and
``tools/check_wiring.py`` itself -- reported green.  The ``AttributeError`` would
only have fired on the ``GET_MORE_STAMINA`` panel, which is the only route to the
free stamina gift, i.e. on the unattended path.

``tools/check_wiring.py`` now walks the AST for call sites that resolve to no
definition.  These tests are what stop that analyzer from quietly becoming a
rubber stamp: the negative controls re-inject the real bug into a throwaway copy
of the package and assert it is caught, and the positive controls assert the live
tree stays clean.
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "winter_agent_v2"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_cw", ROOT / "tools/check_wiring.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


@pytest.fixture()
def scratch_pkg(checker, tmp_path):
    """A throwaway copy of the package the tests may mutate freely.

    ``checker`` reads ``checker.PKG`` at call time, so pointing it here keeps the
    real tree untouched -- the project forbids editing evidence or source just to
    make an assertion pass.

    Deliberately function-scoped rather than module-scoped: the fixture swaps a
    module global, and a module-scoped copy would stay in force for the tests that
    do NOT request it, some of which assert against the real tree and some of
    which mutate the copy.  Each test therefore gets its own copy, which is fine
    for the host's bulk-delete guard as long as a copy stays small -- so sources
    only.  ``__pycache__``/``*.pyc`` are ignored because 36 sources plus 36
    bytecode files is how this fixture previously produced directories past the
    ~50-file threshold, and an aborted rmtree is what turned into the cascade of
    errors described in pytest.ini.  The analyzer reads text; the bytecode was
    never needed.
    """
    dst = tmp_path / "winter_agent_v2"
    shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    original = checker.PKG
    checker.PKG = dst
    try:
        yield dst
    finally:
        checker.PKG = original


def test_real_tree_has_no_dangling_self_calls(checker):
    assert checker.dangling_self_calls() == []


def test_real_tree_has_no_dangling_module_calls(checker):
    assert checker.dangling_module_calls() == []


def test_analyzer_catches_the_0aw_call_site(checker, scratch_pkg):
    """The exact 0aw bug: a self-call to a method that exists on no class."""
    target = scratch_pkg / "ocr.py"
    source = target.read_text(encoding="utf-8")
    assert "countdown = read_next_supply_seconds(" in source
    target.write_text(
        source.replace(
            "countdown = read_next_supply_seconds(",
            "countdown = self._next_supply_seconds(",
            1,
        ),
        encoding="utf-8",
    )
    hits = checker.dangling_self_calls()
    labels = [label for label, _ in hits]
    assert any("_next_supply_seconds" in label for label in labels), hits
    assert any("ocr" in label and "HybridVision" in label for label in labels), hits


def test_analyzer_catches_a_module_helper_called_after_removal(checker, scratch_pkg):
    """The mirror case: a module-level helper is called but no longer defined.

    This is the module-scope analyzer's job, not the self-call one: the call
    ``read_next_supply_seconds(...)`` inside the method is a bare name, so when
    its definition is renamed away it becomes unresolvable at module scope.
    """
    target = scratch_pkg / "ocr.py"
    source = target.read_text(encoding="utf-8")
    assert "def read_next_supply_seconds(" in source
    target.write_text(
        source.replace(
            "def read_next_supply_seconds(",
            "def _renamed_away_supply_seconds(",
            1,
        ),
        encoding="utf-8",
    )
    labels = [label for label, _ in checker.dangling_module_calls()]
    assert any("read_next_supply_seconds" in label for label in labels), labels


def test_analyzer_does_not_flag_injected_callables(checker):
    """Naming a collaborator ``self.sleeper`` is a seam, not a bug.

    Non-underscore attributes are the injected-collaborator convention in this
    package (``sleeper``, ``target_resolver``, ``adb_resolver``, ``_engine``
    used as an attribute).  Flagging them would make the checker noise and it
    would be disabled within a week, so the scope is deliberately private-only.
    """
    labels = [label for label, _ in checker.dangling_self_calls()]
    for benign in ("sleeper", "target_resolver", "adb_resolver"):
        assert not any(label.endswith(benign) for label in labels), labels


def test_analyzer_reports_instead_of_guessing(checker, scratch_pkg):
    """An unresolvable private name is reported, never silently accepted."""
    target = scratch_pkg / "brain.py"
    source = target.read_text(encoding="utf-8")
    probe = "\n\nclass _Probe:\n    def go(self):\n        return self._now_defined_nowhere()\n"
    target.write_text(source + probe, encoding="utf-8")
    labels = [label for label, _ in checker.dangling_self_calls()]
    assert any("_now_defined_nowhere" in label for label in labels), labels


def test_analyzer_tolerates_a_real_private_helper(checker, scratch_pkg):
    """A private helper that *is* defined must not be reported."""
    target = scratch_pkg / "brain.py"
    source = target.read_text(encoding="utf-8")
    probe = (
        "\n\nclass _Probe:"
        "\n    def _defined_here(self):\n        return 1"
        "\n    def go(self):\n        return self._defined_here()\n"
    )
    target.write_text(source + probe, encoding="utf-8")
    labels = [label for label, _ in checker.dangling_self_calls()]
    assert not any("_defined_here" in label for label in labels), labels


# ---------------------------------------------------------------------------
# Scope: the sweep must cover where new code is actually written.
#
# Failure 0aw was fixed by adding AST resolution, but the sweep only walked
# winter_agent_v2/.  Every session adds scripts under tools/ and tests/ instead,
# and the unattended entry points (run_live.py, run_intel_pins.py) live in
# tools/, so the same class of bug could reappear there unseen.
# ---------------------------------------------------------------------------


def test_the_sweep_analyses_the_directory_it_is_given(checker, tmp_path):
    """A sweep that ignored its argument would report tools/ clean unconditionally.

    Without this control, ``dangling_self_calls(ROOT / "tools")`` could quietly
    analyse the package and still pass the real-tree assertion.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "broken.py").write_text(
        "class A:\n    def go(self):\n        return self._not_defined_anywhere()\n",
        encoding="utf-8",
    )
    labels = [label for label, _ in checker.dangling_self_calls(scratch)]
    assert any("_not_defined_anywhere" in label for label in labels), labels
    assert all("broken" in label for label in labels), labels


def test_real_tools_and_tests_are_clean(checker):
    for name in ("tools", "tests"):
        directory = ROOT / name
        assert directory.is_dir(), directory
        assert checker.dangling_self_calls(directory) == [], name
        assert checker.dangling_module_calls(directory) == [], name
