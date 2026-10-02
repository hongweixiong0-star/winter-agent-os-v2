"""WB-1002-24 A/B with verified backups, for this round's files."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
BACKUP = ROOT / "tools/_ab24"
FILES = [
    "winter_agent_v2/goal_library.py",
    "winter_agent_v2/goal_utility.py",
    "winter_agent_v2/runtime.py",
]


def md5(path: pathlib.Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stash"
    BACKUP.mkdir(parents=True, exist_ok=True)
    if mode == "stash":
        manifest = {}
        for rel in FILES:
            source = ROOT / rel
            target = BACKUP / rel.replace("/", "__")
            want = md5(source)
            shutil.copy2(source, target)
            assert md5(target) == want, f"backup of {rel} does not match its source"
            manifest[rel] = want
        (BACKUP / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("stashed", manifest)
        return 0
    if mode == "head":
        for rel in FILES:
            (ROOT / rel).write_bytes(git("show", f"HEAD:{rel}"))
        print("working tree now carries HEAD bytes for", FILES)
        return 0
    if mode == "restore":
        manifest = json.loads((BACKUP / "manifest.json").read_text(encoding="utf-8"))
        for rel, want in manifest.items():
            source = BACKUP / rel.replace("/", "__")
            assert md5(source) == want, f"backup of {rel} drifted"
            shutil.copy2(source, ROOT / rel)
            got = md5(ROOT / rel)
            assert got == want, f"{rel} restored to {got}, expected {want}"
        print("restored", manifest)
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    sys.exit(main())
