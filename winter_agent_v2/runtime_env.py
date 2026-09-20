"""The interpreter that is allowed to run the production loop, and why.

Why this exists
---------------
On 2026-09-17 the desktop launcher ``Start-Winter-Agent-V2.ps1`` pinned

    C:\\Users\\xhw\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe

a generic runtime that ships ``numpy``/``PIL`` and nothing else.  The control
panel then spawned its worker with ``Path(sys.executable).with_name("python.exe")``,
so the worker inherited whatever interpreter launched the panel.  The panel
running at the time had been started with that crippled interpreter (verified
from the live process command line), and the worker's piped stdout -- the only
thing written into ``learning/control_panel/latest.log`` -- said so::

    [executor] MAA requested but unavailable (MAA_IMPORT_FAILED:ModuleNotFoundError);
    observations stay on ADB

Scope, stated exactly.  ``learning/executor_backend.jsonl`` shows that no
*executed* step in those runs belonged to one of the ten skills promoted to MAA
in ``knowledge/execution/backend_routing.json`` (every ADB row is a skill the
policy leaves on ADB on purpose), so the cost was latent rather than already
paid.  What it was not is visible: the ledger records executed steps, the
degradation lived in a worker's stdout, and nothing compared the two.  A skill
promoted to MAA that runs on ADB takes the 324 ms ``exec-out screencap -p`` path
instead of MAA EmulatorExtras' 8.92 ms -- a 36x difference on the hottest call
in the loop, measured live with 20 alternating samples -- and MAA recognition
nodes are unavailable entirely.  ``winter_agent_v2.matchers`` additionally
imports ``cv2`` at module scope, which that interpreter also lacked, so the
``Start-Winter-Agent-V2.ps1`` path running ``tools/run_live.py`` could not run
at all.

The operator's rule of 2026-09-17 makes MAA the default UI engine and permits a
non-MAA path only when MAA has really failed **with evidence**.  A silent
fallback is therefore a defect, not a graceful degradation, and
``TOOLING_MISELECTION_MAA_UNUSED`` had already written the same lesson down
("协商结果必须落盘记录，防止静默降级再次伪装成性能数据").  This module is the
guard: it names what production needs, resolves the interpreter that has it, and
reports the gap instead of hiding it.

What it is not
--------------
No new engine, no second registry: it is a leaf module of pure stdlib used by
``tools/preflight.py``, ``tools/control_panel.py`` and the launchers.  It never
imports ``numpy``/``cv2``/``maa`` itself -- the whole point is that the process
asking the question may be the one that cannot import them, so every answer
comes from probing a *child* process.
"""

from __future__ import annotations

from .winproc import hidden_kwargs

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

# The environment every project script is documented to run in (see the handoff
# rule and config/v2.json's ocr.module_path, which already points inside it).
# Kept as a fallback rather than the only answer: if the operator moves the venv,
# config `runtime.python_path` and the ocr.module_path derivation still work.
PROJECT_VENV = Path(r"E:\无尽冬日智能体\.venv")

# How long a single interpreter probe may take.  ``import maa`` loads the native
# MaaFramework library, which is the slow one; everything else is milliseconds.
PROBE_TIMEOUT_SECONDS = 180.0

_MARKER = "@@WINTER_PREFLIGHT@@"


@dataclass(frozen=True)
class Requirement:
    """One importable module production depends on, and which axis needs it."""

    module: str          # import name
    role: str            # frames | vision | executor | ocr
    why: str             # what breaks without it
    needs_maa: bool = False   # only required while the MAA backend is enabled


# Derived from the code, not from taste: ``matchers.py`` imports cv2 at module
# scope, so a missing cv2 is an ImportError before any page is read;
# ``ocr.py`` reaches for ``rapidocr_onnxruntime`` lazily but it is the only text
# reader, and text feeds stamina, timers and counts.
REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("numpy", "frames", "frame buffers, hashes and pixel reads"),
    Requirement("PIL", "frames", "PNG decode for every screenshot"),
    Requirement("cv2", "vision", "matchers.py imports it at module scope"),
    Requirement(
        "maa",
        "executor",
        "MAA capture + tap; without it the 36x-faster frame path is gone",
        needs_maa=True,
    ),
    Requirement("rapidocr_onnxruntime", "ocr", "the only text reader (doctrine: text -> RapidOCR)"),
)


@dataclass
class InterpreterReport:
    """What a single interpreter can do, as measured by probing it."""

    python_exe: Path
    exists: bool
    present: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    errors: dict[str, str] = field(default_factory=dict)
    fell_back_from: Path | None = None
    candidates: tuple[tuple[str, bool], ...] = ()

    @property
    def ok(self) -> bool:
        return self.exists and not self.missing

    @property
    def reason(self) -> str:
        if not self.exists:
            return f"INTERPRETER_MISSING:{self.python_exe}"
        if self.missing:
            return "MISSING_MODULES:" + ",".join(self.missing)
        return "OK"

    def describe(self) -> str:
        lines = [f"interpreter : {self.python_exe}", f"verdict     : {self.reason}"]
        if self.fell_back_from is not None:
            lines.append(f"fell back from: {self.fell_back_from} (not production-ready)")
        for req in REQUIREMENTS:
            mark = "OK  " if req.module in self.present else "FAIL"
            detail = req.module if req.module in self.present else self.errors.get(req.module, "not importable")
            lines.append(f"  [{mark}] {detail:24s} {req.role:9s} {req.why}")
        return "\n".join(lines)


def required_modules(*, maa_enabled: bool = True) -> tuple[Requirement, ...]:
    """The requirements that apply to this configuration."""
    return tuple(r for r in REQUIREMENTS if maa_enabled or not r.needs_maa)


def venv_from_ocr_module_path(module_path: object) -> Path | None:
    """Recover a venv root from ``config.ocr.module_path``.

    The config already points at ``<venv>\\Lib\\site-packages``; walking back up
    gives the interpreter that owns those packages, so the OCR escape hatch and
    the runtime interpreter cannot drift apart.
    """
    if not module_path:
        return None
    text = str(module_path)
    if not text.strip():
        return None
    path = Path(text)
    # <venv>/Lib/site-packages -> <venv>
    for parent in list(path.parents)[:4]:
        if (parent / "Scripts" / "python.exe").is_file() or (parent / "bin" / "python").is_file():
            return parent
    return None


def _as_python_exe(candidate: Path) -> Path:
    """Accept either a venv directory or a python executable."""
    if candidate.is_dir():
        for name in ("Scripts/python.exe", "bin/python", "python.exe"):
            exe = candidate / name
            if exe.is_file():
                return exe
        return candidate / "Scripts" / "python.exe"
    if candidate.name.lower() == "pythonw.exe":
        # Never probe or spawn a worker with pythonw: it has no console and any
        # import-time error becomes invisible instead of loud.
        return candidate.with_name("python.exe")
    return candidate


def candidate_interpreters(
    root: Path | None = None,
    configured: object = None,
) -> tuple[Path, ...]:
    """Ordered interpreter candidates: explicit config first, convention second.

    ``root`` is accepted for callers that resolve it from their own file
    location; no candidate is derived from the repository layout, because the
    dependencies live in the venv and not in the checkout.
    """
    raw: list[Path] = []
    if configured:
        raw.append(Path(str(configured)))
    ocr_venv = venv_from_ocr_module_path(_configured_ocr_module_path(root))
    if ocr_venv is not None:
        raw.append(ocr_venv)
    raw.append(PROJECT_VENV)
    raw.append(Path(sys.executable))

    seen: set[str] = set()
    ordered: list[Path] = []
    for item in raw:
        exe = _as_python_exe(item)
        key = os.path.normcase(str(exe))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(exe)
    return tuple(ordered)


def _configured_ocr_module_path(root: Path | None) -> str | None:
    """Best-effort read of ``ocr.module_path`` without importing project code."""
    if root is None:
        return None
    config_path = Path(root) / "config/v2.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing/broken config must not crash a probe
        return None
    ocr = data.get("ocr")
    if isinstance(ocr, dict):
        value = ocr.get("module_path")
        if isinstance(value, str):
            return value
    return None


def _probe_source(modules: Sequence[str]) -> str:
    names = json.dumps(list(modules))
    return (
        "import importlib, json, sys\n"
        f"names = json.loads({names!r})\n"
        "out = {}\n"
        "for name in names:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "        out[name] = ''\n"
        "    except BaseException as exc:\n"
        "        out[name] = type(exc).__name__ + ': ' + str(exc)\n"
        f"sys.stdout.write({_MARKER!r} + json.dumps(out))\n"
    )


def probe_interpreter(python_exe: Path, modules: Sequence[str]) -> dict[str, str]:
    """Import each module in a child interpreter; return ``{module: error}``.

    Empty string means the import succeeded.  Probed in a child on purpose: the
    process asking the question is often the one that cannot import the modules,
    so an in-process probe would answer the wrong question.
    """
    if not python_exe.is_file():
        return {name: "INTERPRETER_MISSING" for name in modules}
    try:
        result = subprocess.run(
            [str(python_exe), "-c", _probe_source(modules)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            **hidden_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return {name: "PROBE_TIMEOUT" for name in modules}
    except OSError as exc:
        return {name: f"PROBE_FAILED: {exc}" for name in modules}

    out = result.stdout or ""
    index = out.rfind(_MARKER)
    if index < 0:
        detail = (result.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else "no output"
        return {name: f"PROBE_NO_RESULT: {tail}" for name in modules}
    try:
        payload = json.loads(out[index + len(_MARKER):])
    except json.JSONDecodeError:
        return {name: "PROBE_BAD_JSON" for name in modules}
    return {name: str(payload.get(name, "PROBE_MISSING_KEY")) for name in modules}


def check(
    python_exe: Path,
    *,
    maa_enabled: bool = True,
    fell_back_from: Path | None = None,
) -> InterpreterReport:
    """Probe one interpreter against the requirements that apply."""
    required = required_modules(maa_enabled=maa_enabled)
    exe = _as_python_exe(python_exe)
    if not exe.is_file():
        return InterpreterReport(python_exe=exe, exists=False, missing=tuple(r.module for r in required))
    errors = probe_interpreter(exe, [r.module for r in required])
    present = tuple(name for name, err in errors.items() if not err)
    missing = tuple(name for name, err in errors.items() if err)
    return InterpreterReport(
        python_exe=exe,
        exists=True,
        present=present,
        missing=missing,
        errors={name: err for name, err in errors.items() if err},
        fell_back_from=fell_back_from,
    )


def resolve(
    root: Path | None = None,
    configured: object = None,
    *,
    maa_enabled: bool = True,
) -> InterpreterReport:
    """Pick the first production-ready candidate; otherwise report the best gap.

    "Best gap" is the first existing candidate, so the message names the
    interpreter the launcher would actually have used.  ``fell_back_from`` marks
    the case where an explicitly configured interpreter was skipped because it
    could not import the requirements -- never silent, always recorded.
    """
    candidates = candidate_interpreters(root, configured)
    first_existing: InterpreterReport | None = None
    trace: list[tuple[str, bool]] = []
    for index, exe in enumerate(candidates):
        report = check(exe, maa_enabled=maa_enabled)
        trace.append((str(exe), report.ok))
        if report.ok:
            if index > 0:
                report.fell_back_from = candidates[0]
            report.candidates = tuple(trace)
            return report
        if report.exists and first_existing is None:
            first_existing = report

    if first_existing is None:
        report = InterpreterReport(
            python_exe=candidates[0],
            exists=False,
            missing=tuple(r.module for r in required_modules(maa_enabled=maa_enabled)),
        )
    else:
        report = first_existing
    report.candidates = tuple(trace)
    return report


def maa_enabled_from_config(root: Path | None) -> bool:
    """Read ``executor.maa.enabled``; default on, because MAA is the default engine."""
    if root is None:
        return True
    try:
        data = json.loads((Path(root) / "config/v2.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return True
    executor = data.get("executor")
    if isinstance(executor, dict):
        maa = executor.get("maa")
        if isinstance(maa, dict) and "enabled" in maa:
            return bool(maa["enabled"])
    return True


def configured_python_path(root: Path | None) -> str | None:
    """Read the optional ``runtime.python_path`` override."""
    if root is None:
        return None
    try:
        data = json.loads((Path(root) / "config/v2.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    runtime = data.get("runtime")
    if isinstance(runtime, dict):
        value = runtime.get("python_path")
        if isinstance(value, str) and value.strip():
            return value
    return None


def resolve_for_project(root: Path) -> InterpreterReport:
    """Convenience wrapper: honour config, then probe and resolve."""
    return resolve(
        root=root,
        configured=configured_python_path(root),
        maa_enabled=maa_enabled_from_config(root),
    )


def requirements_table(*, maa_enabled: bool = True) -> Iterable[tuple[str, str, str]]:
    """``(module, role, why)`` rows, for reports that do not want the dataclass."""
    return ((r.module, r.role, r.why) for r in required_modules(maa_enabled=maa_enabled))
