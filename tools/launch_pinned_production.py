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
WORKTREE_HOME = CODE_ROOT.parent
DEFAULT_MANIFEST = WORKTREE_HOME / "PRODUCTION_PIN.json"
DATA_DIR_NAMES = ("config", "knowledge", "learning", "dataset")


class PinError(RuntimeError):
    pass


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=CODE_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=20, check=False,
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


def verify_pin(manifest_path: Path = DEFAULT_MANIFEST) -> tuple[str, Path]:
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
        if not any(path == name or path.startswith(name + "/") for name in DATA_DIR_NAMES):
            unexpected.append(line)
    if unexpected:
        raise PinError("production code worktree has unreviewed changes: " + " | ".join(unexpected[:8]))
    return actual_commit, data_root


def _startup_log(data_root: Path) -> Path:
    return data_root / "learning" / "control_panel" / "desktop_startup.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch only the pinned Winter Agent V2 production tree")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--check-only", action="store_true", help="verify pin and mounts without starting AUTO")
    args = parser.parse_args(argv)
    try:
        commit, data_root = verify_pin(args.manifest)
        identity = f"CODE_COMMIT={commit} WORKTREE_CLEAN=true DATA_ROOT={data_root}"
        print(identity, flush=True)
        if args.check_only:
            return 0
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
        try:
            with (WORKTREE_HOME / "PRODUCTION_LAUNCH.log").open("a", encoding="utf-8") as stream:
                stream.write(failure)
        except OSError:
            pass
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
