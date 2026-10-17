"""Cluster CURRENT production failures, not the all-time pile.

``tools/build_top_failures.py`` answers "what has failed most since the corpus
began", which is the wrong question after a version change: 370 lifetime
``SEMANTIC_TARGET_NOT_VERIFIED`` may all predate the code that is on the device
now.  This tool answers the narrow question the operator asks before touching
code:

    which failures happened *after* AUTO was resumed *and* on the currently
    deployed production commit?

Only that window is clustered, by ``skill`` x ``failure_type`` x ``page`` x
``role_id`` x ``goal_id``, so a fix targets what is really blocking today.

Usage::

    python tools/build_current_failures.py                 # defaults below
    python tools/build_current_failures.py --since 2026-09-29T16:40:00+00:00
    python tools/build_current_failures.py --prod-commit 0eca6115
    python tools/build_current_failures.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
#: AUTO was resumed on the new pinned commit at this instant (2026-09-30 00:40 +08:00).
DEFAULT_SINCE = "2026-09-29T16:40:00+00:00"
DEFAULT_PROD_COMMIT = "0eca6115"


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _page(episode: dict) -> str:
    for key in ("state_before", "state_after"):
        state = episode.get(key)
        if isinstance(state, dict) and state.get("page"):
            return str(state["page"])
    return "UNKNOWN"


def _is_failure(episode: dict) -> bool:
    if str(episode.get("result", "")).upper() == "FAILURE":
        return True
    return episode.get("verifier_ok") is False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cluster current production failures")
    parser.add_argument("--episodes", type=Path, default=EPISODES)
    parser.add_argument("--since", default=DEFAULT_SINCE,
                        help="ISO time; only episodes at/after this count (default: AUTO resume)")
    parser.add_argument("--prod-commit", default=DEFAULT_PROD_COMMIT,
                        help="only episodes whose repo_revision starts with this (default: 0eca6115)")
    parser.add_argument("--json", type=Path, default=None, help="also write the machine-readable result here")
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args(argv)

    since = _parse(args.since)
    window: list[dict] = []
    for line in args.episodes.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = episode.get("recorded_at")
        if not stamp:
            continue
        try:
            when = _parse(str(stamp))
        except ValueError:
            continue
        if when < since:
            continue
        revision = str(episode.get("repo_revision") or "")
        if args.prod_commit and not revision.startswith(args.prod_commit):
            continue
        window.append(episode)

    failures = [e for e in window if _is_failure(e)]
    success = [e for e in window if str(e.get("result", "")).upper() == "SUCCESS"]
    verified = [e for e in window if e.get("verifier_ok") is True]

    clusters: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "sample": None, "goals": Counter()})
    for episode in failures:
        key = (
            str(episode.get("failure_type") or "NO_FAILURE_TYPE"),
            str(episode.get("skill") or "?"),
            _page(episode),
            str(episode.get("role_id") or "?"),
            str(episode.get("goal_id") or "?"),
        )
        row = clusters[key]
        row["count"] += 1
        if row["sample"] is None:
            row["sample"] = episode

    ordered = sorted(clusters.items(), key=lambda kv: -kv[1]["count"])

    print(f"WINDOW since={since.isoformat()} prod_commit={args.prod_commit}")
    print(f"episodes in window : {len(window)}")
    print(f"  SUCCESS          : {len(success)}")
    print(f"  verifier_ok=True : {len(verified)}")
    print(f"  FAILURE          : {len(failures)}")
    if window:
        print(f"  success rate     : {100.0 * len(success) / len(window):.1f}%")
    print()
    print("TOP_CURRENT_FAILURE_CLUSTERS (failure_type x skill x page x role x goal)")
    print("=" * 100)
    for index, ((failure_type, skill, page, role, goal), row) in enumerate(ordered[:args.top], 1):
        print(f"{index:>2}. {failure_type}  x{row['count']}")
        print(f"      skill={skill}  page={page}  role={role}  goal={goal}")
        sample = row["sample"] or {}
        print(f"      reason={str(sample.get('decision_reason'))[:90]}")
        print(f"      action={json.dumps(sample.get('action'), ensure_ascii=False)[:110]}")
        print(f"      observed_change={sample.get('observed_change')} verifier_ok={sample.get('verifier_ok')}")
        print(f"      before={sample.get('before_screenshot')}")
        print(f"      after ={sample.get('after_screenshot')}")
    if not ordered:
        print("(no failures in window)")

    if args.json:
        payload = {
            "since": since.isoformat(),
            "prod_commit": args.prod_commit,
            "episodes": len(window),
            "success": len(success),
            "failures": len(failures),
            "success_rate": (len(success) / len(window)) if window else None,
            "clusters": [
                {
                    "failure_type": key[0], "skill": key[1], "page": key[2],
                    "role_id": key[3], "goal_id": key[4], "count": row["count"],
                    "sample_episode_id": (row["sample"] or {}).get("episode_id"),
                    "sample_decision_reason": (row["sample"] or {}).get("decision_reason"),
                }
                for key, row in ordered
            ],
        }
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
