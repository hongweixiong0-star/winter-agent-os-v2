"""Split winter_agent_v2/skills.py's working-tree diff into two index patches.

The current diff carries two independent work units that happen to touch the
same file:

  * the rally fixes (START_RALLY / JOIN_RALLY actions made deliverable), and
  * the new CLAIM_LOGIN_GIFT skill.

This project's commit-evidence-linking rule wants them in separate commits, so
this script cuts the unified diff at its hunk boundaries and writes two patch
files that can be applied to the Git index one after the other.

Usage: python tools/_split_skills_diff.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET = "winter_agent_v2/skills.py"


def main() -> int:
    raw = subprocess.run(
        ["git", "diff", "--", TARGET],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout
    lines = raw.splitlines(keepends=True)

    # Everything up to the first "@@" is the header; each "@@" starts a hunk.
    header: list[str] = []
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("@@"):
            current = [line]
            hunks.append(current)
        elif current is None:
            header.append(line)
        else:
            current.append(line)

    if not hunks:
        print("no hunks in the diff; nothing to split")
        return 1

    print(f"{len(hunks)} hunks in {TARGET}")
    for i, hunk in enumerate(hunks, start=1):
        print(f"  hunk {i}: {hunk[0].strip()}")

    def write(path: str, pieces: list[list[str]]) -> None:
        # newline="\n": on Windows the default text mode would rewrite every "\n"
        # as "\r\n", and ``git apply`` then refuses the patch.
        body = "".join(header) + "".join("".join(p) for p in pieces)
        if not body.endswith("\n"):
            body += "\n"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        print(f"wrote {path} ({len(body)} bytes)")

    # The rally fixes are the hunks before the one that adds CLAIM_LOGIN_GIFT.
    rally_index = len(hunks)
    for i, hunk in enumerate(hunks):
        if "CLAIM_LOGIN_GIFT" in "".join(hunk):
            rally_index = i
            break
    write("learning/_patch_skills_rally.txt", hunks[:rally_index])
    write("learning/_patch_skills_logingift.txt", hunks[rally_index:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
