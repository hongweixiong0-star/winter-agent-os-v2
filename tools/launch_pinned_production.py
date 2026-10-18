"""Launch the control panel only from the locally pinned production checkout.

The manifest lives beside the managed worktree (outside Git) and names the
existing mutable data directories mounted into this code checkout.  This keeps
the deployed source revision explicit while preserving the one live game-state
database.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR_NAMES = ("config", "knowledge", "learning", "dataset")
#: Paths the runtime or its host writes during ordinary use.  Dirty rows under these are not
#: "unreviewed changes" to production code: the four data directories are the mounted corpus,
#: and ``.workbuddy/`` is the agent host's own session memory, which it appends to every day.
#: Excluding only the four data directories meant a main-checkout launch could never pass --
#: ``M .workbuddy/memory/<date>.md`` was always present and has nothing to do with the product.
MUTABLE_WRITE_DIRS = (*DATA_DIR_NAMES, ".workbuddy")
LEGACY_RUNTIME_OUTPUT_DIRS = {"evidence/gui_workbuddy_loop"}

#: Environment override for the manifest.  Exists for the test suite and for an operator who
#: has moved the tree; the normal launch reads no environment at all.
ENV_PRODUCTION_PIN = "WINTER_PRODUCTION_PIN"

#: Where the pin lives, expressed as two names rather than a path, so the search below stays
#: derived (`.worktrees/prod/PRODUCTION_PIN.json` under whichever ancestor is the repository).
_PIN_HOME_PARTS = (".worktrees", "prod")
_PIN_FILE_NAME = "PRODUCTION_PIN.json"


class PinError(RuntimeError):
    pass


def _pin_home() -> Path:
    """The ``.worktrees/prod`` directory that owns the pin, found by walking up.

    ``CODE_ROOT`` is ``E:\\WinterAgent`` when this file runs from the main checkout and
    ``E:\\WinterAgent\\.worktrees\\prod\\repo`` when it runs from the pinned worktree -- both
    are legitimate launch paths, and before 2026-10-18 they resolved the manifest differently
    (``parent/PRODUCTION_PIN.json``), which made the main-checkout launch fail on
    ``E:\\PRODUCTION_PIN.json``.  Walking up to the first ``.worktrees/prod`` makes the answer
    independent of which copy started the process and independent of ``Path.cwd()``.
    """
    for parent in (CODE_ROOT, *CODE_ROOT.parents):
        candidate = parent.joinpath(*_PIN_HOME_PARTS)
        if candidate.is_dir():
            return candidate
    # Nothing exists yet: name the location the repository would use, so the failure message
    # and the failure log still point at one place instead of at the drive root.
    return CODE_ROOT.joinpath(*_PIN_HOME_PARTS)


def resolve_manifest(explicit: Path | None = None) -> Path:
    """The one manifest this launch will verify, or a :class:`PinError` naming every candidate.

    Precedence: ``--manifest`` > ``WINTER_PRODUCTION_PIN`` > the repository's
    ``.worktrees/prod/PRODUCTION_PIN.json`` > a legacy ``<ancestor>/PRODUCTION_PIN.json``.
    The last entry is compatibility only; it is never preferred over the canonical home.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    override = os.environ.get(ENV_PRODUCTION_PIN, "").strip()
    if override:
        return Path(override).expanduser()
    canonical = _pin_home() / _PIN_FILE_NAME
    if canonical.is_file():
        return canonical
    # Legacy fallback: a manifest sitting at a checkout root (the pre-2026-10-17 layout).
    for parent in (CODE_ROOT, *CODE_ROOT.parents):
        candidate = parent / _PIN_FILE_NAME
        if candidate.is_file():
            return candidate
    looked = "\n  ".join(str(p) for p in (canonical, *(p / _PIN_FILE_NAME for p in CODE_ROOT.parents)))
    raise PinError(
        "production pin manifest not found. Pass --manifest, set "
        f"{ENV_PRODUCTION_PIN}, or restore the canonical file. Looked at:\n  {looked}"
    )


#: ``CREATE_NO_WINDOW``.  This file runs under ``pythonw`` from the Task Scheduler action, so
#: it has no console of its own; a bare ``subprocess.run`` here would pop one on the operator's
#: desktop every launch.  ``tools/check_wiring.py`` scans this file on purpose -- it is the
#: panel's launch path, not an operator diagnostic -- so the flag is passed directly rather
#: than exempting the file.
CREATE_NO_WINDOW = 0x08000000


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=CODE_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=20, check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise PinError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    # Preserve leading status columns from ``git status --porcelain``.
    return result.stdout.rstrip("\r\n")


def _manifest(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinError(f"production pin manifest unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise PinError("production pin manifest has an unsupported schema")
    return data


def _is_legacy_runtime_output(path: str, *, code_root: Path = CODE_ROOT) -> bool:
    """Accept only the known pre-DATA_ROOT soak report, never arbitrary evidence files."""
    normalized = str(path).replace("\\", "/").strip().rstrip("/")
    if normalized not in LEGACY_RUNTIME_OUTPUT_DIRS:
        return False
    directory = code_root / Path(normalized)
    expected = f"{normalized}/latest.json"
    try:
        files = sorted(p.relative_to(code_root).as_posix()
                       for p in directory.rglob("*") if p.is_file())
    except OSError:
        return False
    if files != [expected]:
        return False
    try:
        payload = json.loads((code_root / Path(expected)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    return isinstance(payload, dict) and payload.get("kind") == "GatewaySoakAcceptance"


def verify_pin(manifest_path: Path | None = None) -> tuple[str, Path]:
    manifest_path = resolve_manifest(manifest_path)
    manifest = _manifest(manifest_path)
    expected_commit = str(manifest.get("expected_commit") or "").strip().lower()
    actual_commit = _git("rev-parse", "HEAD").lower()
    if len(expected_commit) != 40 or actual_commit != expected_commit:
        raise PinError(f"commit mismatch: expected={expected_commit or 'unset'} actual={actual_commit}")

    data_root = Path(str(manifest.get("data_root") or "")).expanduser().resolve(strict=True)
    mounts = manifest.get("mounts")
    if not isinstance(mounts, dict):
        raise PinError("manifest mounts must map each mutable data directory to its source")
    for name in DATA_DIR_NAMES:
        source_text = mounts.get(name)
        if not isinstance(source_text, str) or not source_text:
            raise PinError(f"manifest is missing the {name} data mount")
        expected = Path(source_text).resolve(strict=True)
        destination = CODE_ROOT / name
        if not destination.is_dir():
            raise PinError(f"production data mount is missing: {destination}")
        try:
            actual = destination.resolve(strict=True)
            same = os.path.samefile(actual, expected)
        except OSError as exc:
            raise PinError(f"cannot resolve {name} data mount: {exc}") from exc
        if not same:
            raise PinError(f"{name} is not mounted from the declared data source: {actual}")
        try:
            actual.relative_to(data_root)
        except ValueError as exc:
            raise PinError(f"{name} mount resolves outside DATA_ROOT: {actual}") from exc

    # ``normal`` reports an untracked data directory once instead of walking
    # the 18+ GB screenshot corpus file by file on every panel launch.
    dirty = _git("-c", "core.quotepath=false", "status", "--porcelain=v1", "--untracked-files=normal")
    unexpected: list[str] = []
    for line in dirty.splitlines():
        if len(line) < 4:
            unexpected.append(line)
            continue
        path = line[3:].strip().replace("\\", "/")
        if not any(path == name or path.startswith(name + "/") for name in MUTABLE_WRITE_DIRS):
            if _is_legacy_runtime_output(path):
                continue
            unexpected.append(line)
    if unexpected:
        raise PinError("production code worktree has unreviewed changes: " + " | ".join(unexpected[:8]))
    return actual_commit, data_root


def _startup_log(data_root: Path) -> Path:
    return data_root / "learning" / "control_panel" / "desktop_startup.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch only the pinned Winter Agent V2 production tree")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="manifest to verify (default: the repository's single production pin)")
    parser.add_argument("--check-only", action="store_true", help="verify pin and mounts without starting AUTO")
    args = parser.parse_args(argv)
    manifest_path: Path | None = None
    try:
        manifest_path = resolve_manifest(args.manifest)
        commit, data_root = verify_pin(manifest_path)
        identity = f"CODE_COMMIT={commit} WORKTREE_CLEAN=true DATA_ROOT={data_root}"
        print(identity, flush=True)
        if args.check_only:
            return 0
        # Runtime evidence belongs beside the shared mutable data, not in the
        # pinned code checkout where it would make the next startup look dirty.
        os.environ["WINTER_AGENT_DATA_ROOT"] = str(data_root)
        log_path = _startup_log(data_root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", buffering=1) as stream:
            stream.write(f"\n[{datetime.now().astimezone().isoformat()}] {identity}\n")
            stream.write(f"launcher={Path(__file__).resolve()} interpreter={sys.executable}\n")
            os.chdir(CODE_ROOT)
            with redirect_stdout(stream), redirect_stderr(stream):
                runpy.run_path(str(CODE_ROOT / "tools" / "control_panel.py"), run_name="__main__")
        return 0
    except BaseException as exc:  # startup failures must remain diagnosable under pythonw
        failure = f"[{datetime.now().astimezone().isoformat()}] {type(exc).__name__}: {exc}\n"
        # The log follows the pin, never the drive root: with the manifest resolved this is
        # ``.worktrees/prod/``, and when resolution itself failed it is the same directory's
        # would-be location.  Writing ``CODE_ROOT.parent`` here used to recreate
        # ``E:\PRODUCTION_LAUNCH.log`` on every failed main-checkout launch.
        log_root = manifest_path.parent if manifest_path is not None else _pin_home()
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            with (log_root / "PRODUCTION_LAUNCH.log").open("a", encoding="utf-8") as stream:
                stream.write(failure)
        except OSError:
            pass
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
