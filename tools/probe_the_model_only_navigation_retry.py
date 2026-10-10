# -*- coding: utf-8 -*-
"""Does the model-only navigation retry ever answer, and for which semantics?

Why this question exists

    ``runtime.py:10954`` queues a recovery when a navigation skill's real verifier fails:
    "give this selected Goal one fresh model-grounded attempt".  On a later round
    ``_take_failed_navigation_retry`` (``runtime.py:7036``) re-issues that skill, and
    ``resolve`` takes the forced branch -- which calls **only** ``_unknown_navigation_target``
    and never ``_resolve_semantic_target``.  So the recovery is model-only by construction.

    That matters because the two layers answer different questions.  ``_resolve_semantic_target``
    reads *measured geometry* off this frame (for ``EVENT_CALENDAR_NEXT_DETAIL``, the one row
    that is still uninspected).  ``_unknown_navigation_target`` answers from the client's own
    printed names -- ``knowledge/ui/semantic_dictionary.json`` -- and falls back to one
    ``_advised_control`` call.  A semantic with no dictionary record has no printed-name route,
    and no model can know which row is uninspected.

So this prints the cross-tab that decides whether the retry is worth its step: per semantic,
how often the advisor answered versus answered nothing, against whether the dictionary covers
that semantic at all.

Measured 2026-10-10 (48 retry episodes in ``learning/episodes.jsonl``):

    semantic                          in dictionary   answered   silent
    BEAST_SEARCH_TAB                  no                     0       18
    EVENT_CALENDAR_NEXT_DETAIL        no                     0       11
    BTN_OPEN_INTEL_WILD_HUD           no                     0        3
    QUICK_PANEL_ROW_BUILDING          yes                    2        2
    QUICK_PANEL_ROW_LANCER_CAMP_ENTRY yes                    2        0
    REGULAR_EVENT_ENTRY               yes                    0        2

    dictionary-absent  -> 0 answered in 32 episodes
    dictionary-present -> 4 answered in 8 episodes (plus 2 silent)

Usage
    python tools/probe_the_model_only_navigation_retry.py
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

EPISODES = ROOT / "learning" / "episodes.jsonl"
DICTIONARY = ROOT / "knowledge" / "ui" / "semantic_dictionary.json"
RETRY_PREFIX = "ONLINE_UNKNOWN_NAVIGATION:"
SILENT = "UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING"


def dictionary_ids() -> set[str]:
    records = json.loads(DICTIONARY.read_text(encoding="utf-8")).get("records") or []
    return {str(r.get("id")) for r in records if isinstance(r, dict) and r.get("id")}


def main() -> int:
    known = dictionary_ids()
    print(f"dictionary records: {len(known)}")
    print()

    rows: list[dict] = []
    total = 0
    with EPISODES.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            total += 1
            if str(row.get("decision_reason") or "").startswith(RETRY_PREFIX):
                rows.append(row)
    print(f"episodes scanned: {total}")
    print(f"episodes decided by the model-only retry: {len(rows)}")
    print()

    # semantic -> [covered, answered, silent]
    table: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    covered = [0, 0, 0]
    uncovered = [0, 0, 0]
    for row in rows:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        semantic = str(action.get("target") or "<none>")
        error = str(row.get("recognition_error") or "")
        in_dict = semantic in known
        table[semantic][0] = 1 if in_dict else 0
        if error == SILENT:
            table[semantic][2] += 1
            (covered if in_dict else uncovered)[2] += 1
        elif error:
            # Any other non-empty code means the advisor got past "nothing" -- it produced a
            # candidate that then failed downstream (e.g. MAA_TEMPLATE:NO_MATCH).
            table[semantic][1] += 1
            (covered if in_dict else uncovered)[1] += 1

    print(f"{'semantic':34s} {'in dict':>7s} {'answered':>9s} {'silent':>7s}")
    print("-" * 62)
    for semantic, (in_dict, answered, silent) in sorted(
            table.items(), key=lambda kv: kv[1][0], reverse=True):
        print(f"  {semantic:32s} {'yes' if in_dict else 'NO':>7s} {answered:>9d} {silent:>7d}")
    print("-" * 62)
    print(f"  {'dictionary-ABSENT subtotal':32s} {'':>7s} {uncovered[1]:>9d} {uncovered[2]:>7d}")
    print(f"  {'dictionary-PRESENT subtotal':32s} {'':>7s} {covered[1]:>9d} {covered[2]:>7d}")
    print()

    problems: list[str] = []
    if not rows:
        problems.append("no retry episodes found -- the ledger may have rotated")
    print("READING:")
    print(f"  For a semantic the dictionary does not cover, the advisor answered "
          f"{uncovered[1]} times out of {uncovered[1] + uncovered[2]}.")
    print("  Its only route then is one _advised_control call, and the controls that fail this")
    print("  way are identified by measured geometry (which row is uninspected), which no model")
    print("  can supply.  So for those semantics the retry step is spent asking a question whose")
    print("  answer is already on file as PROVIDER_ANSWERED_NOTHING.")
    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
