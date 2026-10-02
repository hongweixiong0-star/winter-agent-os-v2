"""Commit a set of paths from their current bytes, without trusting the working tree to survive.

Same technique as _wb1002_22_deliver.py: read the bytes, write blobs with `hash-object -w`, assemble
a tree in a temporary index seeded from HEAD, `commit-tree`, `update-ref`.  Used because this tree
has been seen reverting tracked files mid-session.

usage:  python _wb1002_commit_paths.py "<message file>" <path> [<path> ...]
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import os
import hashlib

ROOT = pathlib.Path(__file__).resolve().parent


def git(*args: str, env: dict | None = None, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True,
                          input=stdin, env=env).stdout


def main() -> int:
    message_file = pathlib.Path(sys.argv[1])
    paths = sys.argv[2:]
    message = message_file.read_text(encoding="utf-8")

    blobs: dict[str, bytes] = {}
    for rel in paths:
        path = ROOT / rel
        if not path.is_file():
            print(f"  skipped (absent): {rel}")
            continue
        blobs[rel] = path.read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(pathlib.Path(tmp) / "index"))
        git("read-tree", "HEAD", env=env)
        for rel, blob in blobs.items():
            sha = git("hash-object", "-w", "--stdin", stdin=blob).decode().strip()
            git("update-index", "--add", "--cacheinfo", f"100644,{sha},{rel}", env=env)
        tree = git("write-tree", env=env).decode().strip()

    commit = git("commit-tree", tree, "-p", "HEAD", "-m", message).decode().strip()
    git("update-ref", "HEAD", commit)
    print("commit", commit, f"({len(blobs)} files)")

    for rel, blob in blobs.items():
        committed = git("show", f"HEAD:{rel}")
        assert committed == blob, f"{rel} does not match what was committed"
        print(f"  verified {rel} ({len(blob)} bytes, md5 {hashlib.md5(blob).hexdigest()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
