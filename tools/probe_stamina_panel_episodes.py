"""Read-only: what did the free-stamina panel check actually do in production?

``--no-stamina-check`` was added to ``tools/run_intel_pins.py`` on 2026-09-14
19:23, five hours after the panel check itself landed (``eeac37d``, 14:17).
Its help text says the flag exists because "repeated failed claim attempts are
pure episode noise".  This probe reads the recorded corpus instead of the
claim: it counts every step whose skill or failure type belongs to the
free-stamina path, and prints the surrounding evidence.

The episode store is *flat* -- one JSON object per step, not one per episode.

Usage: python tools/probe_stamina_panel_episodes.py
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning" / "episodes.jsonl"

PATH_SKILLS = ("OPEN_STAMINA_SOURCES", "CLAIM_FREE_STAMINA")
PATH_MARKERS = ("GET_MORE_STAMINA", "free_claim_available", "STAMINA_PANEL")


def load() -> list[dict]:
    if not EPISODES.exists():
        return []
    rows: list[dict] = []
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def main() -> int:
    rows = load()
    print(f"episodes: {len(rows)} step records")

    executions = collections.Counter(
        str(row.get("skill")) for row in rows if str(row.get("skill")) in PATH_SKILLS
    )
    print("\n-- skills on the free-stamina path")
    for skill in PATH_SKILLS:
        print(f"   {executions.get(skill, 0):4d}  {skill}")

    touches = [
        row
        for row in rows
        if any(
            marker in json.dumps(
                {key: row.get(key) for key in ("state_before", "state_after", "failure_type", "verifier")},
                ensure_ascii=False,
            )
            for marker in PATH_MARKERS
        )
    ]
    print(f"\n-- steps that ever touched the stamina panel: {len(touches)}")
    for row in touches:
        after = row.get("state_after") or {}
        print(
            f"   {str(row.get('recorded_at') or '')[:19]}  "
            f"{row.get('skill')}  result={row.get('result')}  "
            f"failure_type={row.get('failure_type')}  "
            f"after={after.get('page')}/{after.get('popup')}  "
            f"stamina={(after.get('stamina') or {})}",
            flush=True,
        )

    print("\n-- every step recorded as a FAILURE whose reason mentions stamina")
    for row in rows:
        blob = json.dumps(row.get("failure_type"), ensure_ascii=False) + json.dumps(
            row.get("verifier"), ensure_ascii=False
        )
        if "STAMINA" in blob.upper() and str(row.get("result")).upper() != "SUCCESS":
            print(
                f"   {str(row.get('recorded_at') or '')[:19]}  {row.get('skill')}  "
                f"result={row.get('result')}  failure_type={row.get('failure_type')}  "
                f"verifier={row.get('verifier')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
