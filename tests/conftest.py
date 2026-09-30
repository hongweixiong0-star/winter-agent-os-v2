"""Keep the test suite out of the AUTO's live runtime state.

Operator directive 2026-09-22 §九: "开发测试使用独立目录，不能覆盖或回滚正式 AUTO 的学习资产".
Measured the same day, and it was not a hypothetical: this store is a module constant pointing at
the live file, several tests drive a whole ``LiveRuntime`` (which writes it back at the end of a
run), and ``learning/control_experience.json`` went from 52 records to 4 across one suite run --
taking with it the L1 registration a real step had just proved on the device.

Production Sprint NEXT (2026-09-30) P0 asked for this to be finished rather than patched again:
"不要只修单个测试. 在 tests/conftest.py 建立统一 TEST_RUNTIME_ROOT", with the acceptance
``PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS = 0``.

The 2026-09-30 measurement that drove the rewrite
------------------------------------------------
The suite was run with a write tripwire recording every write a test process made into the real
``learning/`` and ``config/`` trees.  Production AUTO was live at the time, so a plain
before/after fingerprint could not have attributed anything; interception plus the writing pid
could.  Seventeen writes landed on eleven production paths:

    learning/decisions.jsonl              learning/observation_state.json
    learning/goal_fairness.json (+.tmp)   learning/autogen_repair_events.jsonl
    learning/_tmp_planner_call_test.jsonl learning/control_panel/ (created)
    config/policy_state.json (+.tmp)      learning/ and config/ (created)

``config/policy_state.json`` is the one that mattered most: a test constructing a real
``ControlPanel`` calls ``_save_policy_state`` from ``__init__``, so a suite run rewrote the
operator's own policy file -- the same file whose erasure had to be repaired by hand earlier the
same day.  A test could also have taken the *device*: ``DeviceLease()`` with no argument defaulted
to the live root.

Two mechanisms, because one is not enough
-----------------------------------------
1. **Redirection** -- every runtime-mutable path this project has a nameable constant for is
   repointed into one session-scoped ``TEST_RUNTIME_ROOT``.  Live content is *copied* in first
   (``_seed``) so reads keep working; only writes are diverted.
2. **A guard** -- the constants above are a list somebody has to maintain, and the list was already
   incomplete.  So writes are also intercepted and refused at the moment they happen: anything
   under ``learning/`` or ``config/`` is the running loop's state, whatever it is called.  The
   project's own enumeration (``tools/build_runtime_state_manifest.py``) is quoted in the refusal
   so the path can be recognised, but it does not decide -- an earlier version let it decide, and
   its own regression test caught the hole: ``classify`` falls back to ``VERSIONED_EVIDENCE`` for
   an unlisted path under ``learning/``, which would have left ``learning/goal_fairness.json``
   writable and any newly introduced runtime path invisible.  The guard raises *before* the write,
   so a test that swallows exceptions still cannot leave a mark.

Why refuse rather than only report: the metric is zero, and a report arrives after the damage.
The permanent regression is ``tests/test_suite_isolation.py``.
"""

from __future__ import annotations

import builtins
import contextlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------------------
# THE unified test runtime root
# ---------------------------------------------------------------------------------------
#: Every runtime-mutable path a test could write is redirected here.  Created once at import
#: time (not inside a fixture) so that module-level constants computed at import -- which is
#: most of them -- can point at it, and exported through the environment so a subprocess a
#: test spawns inherits the same answer instead of falling back to production.
TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="winter-test-runtime-"))
os.environ["WINTER_TEST_RUNTIME_ROOT"] = str(TEST_RUNTIME_ROOT)


def _runtime_relative(relative: str) -> Path:
    """Where a live path is redirected to, preserving its shape under the test root.

    ``learning/goal_fairness.json`` becomes ``<root>/learning/goal_fairness.json`` rather than
    ``<root>/goal_fairness.json``.  The shape is preserved deliberately: several stores derive a
    *second* path from the first by walking up to the ``learning`` directory
    (``QueuePump._build`` reads ``ledger_path.parents[1]`` to decide the adapter's root), and a
    flattened scratch tree would silently send those derived paths back to production.
    """
    return TEST_RUNTIME_ROOT / relative


#: ``(module, attribute, live path, seed from live)``.
#:
#: Seeding is for stores a test *reads* to build something real -- a vision layer needs the live
#: template manifest.  A store a test must never *see* live content through is left empty on
#: purpose: seeding the pump heartbeat would hand a test the pid of whichever process really owns
#: the clock, and seeding the escalation ledger would let a test suite dispatch jobs about screens
#: the production device really asked about.
_REDIRECTS: tuple[tuple[str, str, str, bool], ...] = (
    # -- learning: role/gameplay stores ------------------------------------------------
    ("winter_agent_v2.control_experience", "STATE_PATH",
     "learning/control_experience.json", True),
    ("winter_agent_v2.observation_store", "STATE_PATH",
     "learning/observation_state.json", True),
    ("winter_agent_v2.goal_utility", "STATE_PATH",
     "learning/goal_fairness.json", True),
    ("winter_agent_v2.goal_utility", "DECISIONS_PATH",
     "learning/decisions.jsonl", False),
    ("winter_agent_v2.event_schedule", "STATE_PATH",
     "learning/timed_event_schedule.json", True),
    ("winter_agent_v2.stamina_supply", "DEFAULT_PATH",
     "learning/stamina_supply.json", True),
    ("winter_agent_v2.fishing_state", "DEFAULT_PATH",
     "learning/fishing_state.json", True),
    ("winter_agent_v2.fishing_state", "DEFAULT_LEDGER_PATH",
     "learning/fishing_runs.jsonl", False),
    # -- learning: ledgers and counters -------------------------------------------------
    ("winter_agent_v2.semantic_executor", "METRICS_PATH",
     "learning/semantic_click_metrics.jsonl", False),
    ("winter_agent_v2.semantic_executor", "COUNTERS_PATH",
     "learning/semantic_click_counters.json", True),
    ("winter_agent_v2.executor_router", "DEFAULT_LEDGER_PATH",
     "learning/executor_backend.jsonl", False),
    ("winter_agent_v2.local_gui_model", "LEDGER_PATH",
     "learning/local_gui_model_calls.jsonl", False),
    ("winter_agent_v2.unknown_dispatch", "DISPATCH_LEDGER",
     "learning/unknown_dispatch.jsonl", False),
    ("winter_agent_v2.capability_bootstrap", "STATE_PATH",
     "learning/knowledge_bootstrap/STATE.json", True),
    ("winter_agent_v2.pipeline_autogen", "DEFAULT_REPAIR_EVENTS_PATH",
     "learning/autogen_repair_events.jsonl", False),
    # -- knowledge / dataset candidates a test may "learn" into -------------------------
    ("winter_agent_v2.ui_collection", "CANDIDATE_ROOT",
     "knowledge/perception/candidates", True),
    ("winter_agent_v2.ui_collection", "TEMPLATE_MANIFEST",
     "dataset/candidate/template_manifest.json", True),
    ("winter_agent_v2.ui_collection", "TEMPLATE_DIR",
     "dataset/candidate/auto_collected", True),
    ("winter_agent_v2.page_knowledge", "PAGE_ROOT",
     "knowledge/perception/pages", True),
    ("winter_agent_v2.page_knowledge", "TRANSITIONS_PATH",
     "knowledge/ui/page_transitions.json", True),
    # -- unknown questions a test must not answer on the AUTO's behalf -------------------
    ("winter_agent_v2.unknown_advisor", "REQUEST_ROOT",
     "learning/unknown_requests", False),
    # The control panel: its clock, its log, and the operator's own intent --------------
    ("tools.control_panel", "PUMP_STATE_PATH",
     "learning/control_panel/pump.json", False),
    ("tools.control_panel", "PANEL_LOG_PATH",
     "learning/control_panel/panel.log", True),
    # ``PANEL_STATE_PATH`` is the operator's intent (RUNNING / PAUSED / STOPPED).  A test that
    # constructed a panel without redirecting it could stop the production AUTO by writing one
    # word, so it is seeded and redirected like the rest.
    ("tools.control_panel", "PANEL_STATE_PATH",
     "config/control_panel_state.json", True),
    # ``ControlPanel.__init__`` calls ``_save_policy_state``, which rewrites the policy file.  This
    # is the write the 2026-09-30 tripwire actually caught, and it is the worst one: the same file
    # whose erasure had to be repaired by hand hours earlier.  Both writers are redirected, and the
    # runtime's own reader with them, so the panel and the scheduler cannot disagree mid-test.
    ("tools.control_panel", "POLICY_STATE_PATH",
     "config/policy_state.json", True),
    ("winter_agent_v2.runtime", "POLICY_STATE_PATH",
     "config/policy_state.json", True),
    # The pump builds a real adapter on this ledger unless a test redirects it, and the adapter
    # appends rows.
    ("tools.control_panel", "_ESCALATION_LEDGER_PATH",
     "learning/workbuddy_escalations.jsonl", False),
    # The single device lock.  Production helpers call ``DeviceLease()`` with no argument, so
    # before ``DEFAULT_ROOT`` existed a test of that shape owned the real MuMu.
    ("winter_agent_v2.device_lease", "DEFAULT_ROOT", ".", False),
    # The window's own "replace me" marker.  ``_check_control_plane_reload`` writes it whenever
    # the tree is dirty and a control-plane file has moved, and it used to pass an explicit root:
    # the P0 write guard caught three ``write_text(learning/CONTROL_PLANE_RELOAD_REQUIRED.json)``
    # from the pytest process against the shared data root.  That is not a log line -- it asks
    # the *running* panel to restart, so a test run could have replaced production mid-round.
    ("winter_agent_v2.control_plane_reload", "MARKER_ROOT", ".", False),
)


def _prepare(target: Path, live_relative: str) -> None:
    """Make ``target`` usable without turning a file path into a directory.

    ``learning/control_panel/pump.json`` is a *file*; calling ``mkdir(parents=True)`` on it
    creates a directory of that name and every later write fails with a permission error that
    looks nothing like its cause.  Measured on the first run of this file.  So: an existing live
    directory (or a path with no suffix and no live counterpart) is created as a directory, and
    anything else gets its parent created instead.
    """
    if live_relative == ".":
        target.mkdir(parents=True, exist_ok=True)
        return
    live = ROOT / live_relative
    if live.is_dir() or (not live.exists() and not live.suffix):
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)


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


# ---------------------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------------------
class ProductionRuntimeWriteError(RuntimeError):
    """A test tried to write the running loop's own state.  Raised *before* the write."""


#: Every refused write, in order.  ``tests/test_suite_isolation.py`` asserts this is empty; it is
#: also readable during a debugging session without re-running the suite, and the session teardown
#: below re-checks it after the last test.
PRODUCTION_WRITES: list[dict] = []

#: The positive control for the redirection: a production-shaped file the operator asked for
#: (``process = 123456``, ``sentinel = KEEP_ME``), planted *inside the live runtime tree* so that a
#: leak is visible, and planted here rather than by a test so that the test writes nothing itself.
#:
#: It is deliberately **not** the live ``learning/control_panel/pump.json``.  That file is read to
#: decide who owns the AUTO clock, so a file naming pid 123456 makes the running panel treat itself
#: as the second instance and refuse to start AUTO -- exactly the 2026-09-30 03:41 outage.  AUTO is
#: live while the suite runs.  This path sits beside it under the same manifest rule
#: (``learning/control_panel/**`` -> RUNTIME_MUTABLE), so the guard covers it identically.
SENTINEL_RELATIVE = "learning/control_panel/autotest_isolation_sentinel.json"
SENTINEL_CONTENT = {"process": 123456, "sentinel": "KEEP_ME"}


def _plant_sentinel() -> None:
    """Create the positive control once, and only if it is not already correct.

    Only-if-different matters: rewriting it every session would move its mtime and make the
    byte-comparison in the regression test look like activity.
    """
    try:
        sentinel = ROOT / SENTINEL_RELATIVE
        wanted = json.dumps(SENTINEL_CONTENT, ensure_ascii=False, indent=1)
        if sentinel.exists() and sentinel.read_text(encoding="utf-8") == wanted:
            return
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(wanted, encoding="utf-8")
    except OSError:
        pass


#: The two trees the AUTO's own state lives in.  A test writing anywhere under either of them is
#: writing the running loop, whether or not the path is one the manifest happens to name.
#:
#: This is deliberately broader than ``manifest.classify(...) == RUNTIME_MUTABLE``.  The first
#: version of this guard used the manifest alone, and its own regression test caught the hole:
#: ``classify`` falls back to ``VERSIONED_EVIDENCE`` for anything under ``learning/`` that no glob
#: names, so ``learning/goal_fairness.json`` -- the file the panel rewrites on every start-up --
#: would have been written happily, and a brand-new runtime path would have been invisible until
#: somebody added a glob for it.  The manifest is now used to *describe* the path (known
#: runtime-mutable, or an unclassified path under a guarded tree); it no longer decides.
GUARDED_TREES = ("learning", "config")


def _manifest():
    """The project's own runtime-mutable enumeration, imported lazily.

    Lazy because this module is imported before ``tools/`` is on ``sys.path``, and because a broken
    manifest must degrade to "redirect only" rather than take the suite down.  Used for the wording
    of a refusal, never for the decision.
    """
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import build_runtime_state_manifest as manifest

        return manifest
    except Exception:  # noqa: BLE001 - the guard is an addition, not a dependency
        return None


def classify_production_write(target: object) -> str | None:
    """Return the repo-relative path if writing ``target`` would touch live runtime state.

    ``None`` means "not live runtime state", which is the fast path: most writes in a test go to
    ``%TEMP%`` and never reach the classifier.
    """
    try:
        text = os.fspath(target)
    except TypeError:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    if not isinstance(text, str):
        return None
    if not text.startswith(str(ROOT)):
        return None
    try:
        relative = Path(text).resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return None
    if not relative:
        return None
    if relative.split("/", 1)[0] not in GUARDED_TREES:
        return None
    return relative


@contextlib.contextmanager
def probe_ledger():
    """Run a *deliberate* refusal without polluting the session's violation ledger.

    The guard's own tests have to trip it, and a tripped guard is a recorded violation.  Without
    this, proving the guard works would itself make ``PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS``
    non-zero -- and a metric that cannot be reached while testing it is a metric nobody keeps.
    The real ledger is put back untouched afterwards.
    """
    saved = list(PRODUCTION_WRITES)
    PRODUCTION_WRITES.clear()
    try:
        yield PRODUCTION_WRITES
    finally:
        PRODUCTION_WRITES[:] = saved


def _refuse(op: str, target: object, relative: str) -> None:
    manifest = _manifest()
    try:
        verdict = manifest.classify(relative) if manifest is not None else "UNKNOWN"
    except Exception:  # noqa: BLE001
        verdict = "UNKNOWN"
    PRODUCTION_WRITES.append({"op": op, "path": relative, "verdict": verdict, "pid": os.getpid()})
    raise ProductionRuntimeWriteError(
        f"a test tried to write the AUTO's live runtime state through {op}():\n"
        f"    {relative}   (manifest verdict: {verdict})\n"
        f"tests/conftest.py redirects every runtime-mutable path into\n"
        f"    {TEST_RUNTIME_ROOT}\n"
        f"If this path is not covered, add its module constant to ``_REDIRECTS``; do not weaken the "
        f"guard.  Operator directive 2026-09-30 P0 requires "
        f"PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS = 0."
    )


def _install_write_guard() -> dict:
    """Refuse writes to live runtime state for the rest of the session.  Returns the originals."""
    originals = {
        "builtins.open": builtins.open,
        "Path.open": Path.open,
        "Path.write_text": Path.write_text,
        "Path.write_bytes": Path.write_bytes,
        "Path.touch": Path.touch,
        "Path.mkdir": Path.mkdir,
        "os.replace": os.replace,
        "os.rename": os.rename,
        "os.remove": os.remove,
        "os.unlink": os.unlink,
        "shutil.copy": shutil.copy,
        "shutil.copy2": shutil.copy2,
        "shutil.copytree": shutil.copytree,
        "shutil.move": shutil.move,
    }

    write_modes = set("wxa+")

    def _writes(mode: object) -> bool:
        return bool(mode) and bool(set(str(mode)) & write_modes)

    real_open = originals["builtins.open"]

    def open_hook(file, mode="r", *args, **kwargs):
        if _writes(mode):
            relative = classify_production_write(file)
            if relative is not None:
                _refuse("open", file, relative)
        return real_open(file, mode, *args, **kwargs)

    real_path_open = originals["Path.open"]

    def path_open_hook(self, mode="r", *args, **kwargs):
        if _writes(mode):
            relative = classify_production_write(self)
            if relative is not None:
                _refuse("Path.open", self, relative)
        return real_path_open(self, mode, *args, **kwargs)

    def _simple(name: str, original):
        def hook(self, *args, **kwargs):
            relative = classify_production_write(self)
            if relative is not None:
                _refuse(name, self, relative)
            return original(self, *args, **kwargs)

        return hook

    real_mkdir = originals["Path.mkdir"]

    def mkdir_hook(self, *args, **kwargs):
        # Only a directory that does not already exist is a write worth refusing; ``mkdir`` on an
        # existing directory is a no-op, and refusing it would fail tests that harm nothing.
        if not self.exists():
            relative = classify_production_write(self)
            if relative is not None:
                _refuse("mkdir", self, relative)
        return real_mkdir(self, *args, **kwargs)

    def _to(name: str, original, index: int):
        def hook(*args, **kwargs):
            if len(args) > index:
                relative = classify_production_write(args[index])
                if relative is not None:
                    _refuse(name, args[index], relative)
            return original(*args, **kwargs)

        return hook

    builtins.open = open_hook
    Path.open = path_open_hook
    Path.write_text = _simple("write_text", originals["Path.write_text"])
    Path.write_bytes = _simple("write_bytes", originals["Path.write_bytes"])
    Path.touch = _simple("touch", originals["Path.touch"])
    Path.mkdir = mkdir_hook
    os.replace = _to("os.replace", originals["os.replace"], 1)
    os.rename = _to("os.rename", originals["os.rename"], 1)
    os.remove = _to("os.remove", originals["os.remove"], 0)
    os.unlink = _to("os.unlink", originals["os.unlink"], 0)
    shutil.copy = _to("shutil.copy", originals["shutil.copy"], 1)
    shutil.copy2 = _to("shutil.copy2", originals["shutil.copy2"], 1)
    shutil.copytree = _to("shutil.copytree", originals["shutil.copytree"], 1)
    shutil.move = _to("shutil.move", originals["shutil.move"], 1)
    return originals


def _uninstall_write_guard(originals: dict) -> None:
    for name, value in originals.items():
        if name == "builtins.open":
            builtins.open = value
        elif name.startswith("Path."):
            setattr(Path, name.split(".", 1)[1], value)
        elif name.startswith("os."):
            setattr(os, name.split(".", 1)[1], value)
        elif name.startswith("shutil."):
            setattr(shutil, name.split(".", 1)[1], value)


# ---------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _protect_the_live_learning_assets():
    previous: dict[tuple[object, str], object] = {}
    for module_name, attribute, live_relative, seed in _REDIRECTS:
        try:
            module = __import__(module_name, fromlist=["_"])
        except Exception:  # noqa: BLE001 - a module that will not import cannot be written
            continue
        if not hasattr(module, attribute):
            continue
        previous[(module, attribute)] = getattr(module, attribute)
        target = _runtime_relative(live_relative)
        if seed and live_relative != ".":
            _seed(ROOT / live_relative, target)
        else:
            _prepare(target, live_relative)
        setattr(module, attribute, target)

    PRODUCTION_WRITES.clear()
    _plant_sentinel()
    originals = _install_write_guard()
    try:
        yield
    finally:
        _uninstall_write_guard(originals)
        for (module, attribute), value in previous.items():
            setattr(module, attribute, value)
        shutil.rmtree(TEST_RUNTIME_ROOT, ignore_errors=True)
        # The metric, re-checked after the very last test.  A single asserting test cannot cover a
        # violation raised by a file that sorts after it, so the session closes the loop itself.
        if PRODUCTION_WRITES:
            raise ProductionRuntimeWriteError(
                "PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS != 0 -- "
                f"{len(PRODUCTION_WRITES)} write(s) reached the AUTO's live runtime state:\n"
                + "\n".join(f"    {row['op']}({row['path']})" for row in PRODUCTION_WRITES)
            )


@pytest.fixture(scope="session")
def test_runtime_root() -> Path:
    """The scratch tree every redirected runtime path lives under."""
    return TEST_RUNTIME_ROOT


@pytest.fixture(scope="session")
def production_write_violations() -> list[dict]:
    """Writes a test made into live runtime state.  Empty is the only acceptable answer."""
    return PRODUCTION_WRITES
