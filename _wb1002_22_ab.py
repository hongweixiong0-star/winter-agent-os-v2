"""WB-1002-22 A/B with a verified backup.

The earlier attempt in this round lost its own edits because the backup was never checked before
being written over.  This one records the md5 of the working version, copies it, **verifies the
copy**, only then restores HEAD, and restores from the copy when ``--restore`` is passed.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
BACKUP = ROOT / "tools/_ab_verify"
FILES = [
    "knowledge/execution/backend_routing.json",
    "winter_agent_v2/pipeline_autogen.py",
]


def md5(path: pathlib.Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def stash() -> dict[str, str]:
    BACKUP.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for rel in FILES:
        source = ROOT / rel
        target = BACKUP / rel.replace("/", "__")
        want = md5(source)
        shutil.copy2(source, target)
        got = md5(target)
        assert got == want, f"backup of {rel} does not match the file it came from"
        manifest[rel] = want
    (BACKUP / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore_head() -> None:
    for rel in FILES:
        (ROOT / rel).write_bytes(subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=True).stdout)


def restore_backup() -> dict[str, str]:
    manifest = json.loads((BACKUP / "manifest.json").read_text(encoding="utf-8"))
    for rel, want in manifest.items():
        source = BACKUP / rel.replace("/", "__")
        assert md5(source) == want, f"backup of {rel} drifted"
        shutil.copy2(source, ROOT / rel)
        got = md5(ROOT / rel)
        assert got == want, f"{rel} restored to {got}, expected {want}"
    return manifest


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        print("restored", restore_backup())
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--head":
        restore_head()
        print("working tree now carries HEAD bytes for", FILES)
        return 0
    print("stashed", stash())
    return 0


if __name__ == "__main__":
    sys.exit(main())
