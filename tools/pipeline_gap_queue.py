"""Build a prioritized, evidence-aware queue of missing recognition targets.

The queue is a planning artifact. A target is never wired merely because a
dictionary label or a past Episode exists; generation still needs a real frame
and positive/negative MAA validation.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from pipeline_coverage import ROOT, SEMANTIC_DICT, build


def family(semantic: str) -> str:
    name = semantic.upper()
    for token, group in (("CLAIM", "CLAIM"), ("REWARD", "CLAIM"),
                         ("DISMISS", "POPUP"), ("CLOSE", "POPUP"),
                         ("BACK", "POPUP"), ("SEARCH", "SEARCH"),
                         ("BEAST", "MARCH"), ("MARCH", "MARCH"),
                         ("RALLY", "MARCH"), ("ROW", "LIST"),
                         ("SCROLL", "LIST")):
        if token in name:
            return group
    return "NAV"


def priority(semantic: str, goals: set[str]) -> str:
    name = semantic.upper()
    if "BEAR" in name or "RALLY" in name or "PARTICIPATE_BEAR" in goals:
        return "P0"
    if goals or any(word in name for word in
                    ("DAILY", "MAIL", "INTEL", "ALLIANCE", "RESEARCH",
                     "BUILD", "SEARCH", "DISPATCH", "REWARD", "CLAIM")):
        return "P1"
    return "P2"


def build_queue() -> dict:
    coverage = build()
    dictionary = json.loads(SEMANTIC_DICT.read_text(encoding="utf-8"))
    records = {str(row.get("id")): row for row in dictionary.get("records", [])
               if isinstance(row, dict) and row.get("id")}
    goal_by_skill: dict[str, set[str]] = defaultdict(set)
    for goal in coverage["goals"]:
        for skill in goal["missing_nodes"]:
            goal_by_skill[skill].add(goal["goal"])

    grouped: dict[str, dict] = {}
    for row in coverage["skills"]:
        if row["action_kind"] != "TAP_SEMANTIC" or row["has_maa_node"]:
            continue
        semantic = row["semantic"]
        item = grouped.setdefault(semantic, {
            "semantic": semantic, "skills": [], "goals": set(), "pages": set(),
            "production_attempts": 0,
        })
        item["skills"].append(row["skill_id"])
        item["goals"].update(goal_by_skill[row["skill_id"]])
        if row["required_page"]:
            item["pages"].add(row["required_page"])
        item["production_attempts"] += row["production"]["live_executed"]

    queue = []
    for semantic, item in grouped.items():
        record = records.get(semantic, {})
        words = [str(word) for word in record.get("ocr", []) if str(word).strip()]
        if not words and record.get("cn"):
            words = [str(record["cn"])]
        item["pages"].update(str(page) for page in record.get("pages", []))
        item["goals"] = sorted(item["goals"])
        item["pages"] = sorted(item["pages"])
        item["family"] = family(semantic)
        item["priority"] = priority(semantic, set(item["goals"]))
        item["record_type"] = record.get("type")
        item["visible_words"] = words
        # A label on a row or page heading does not identify its tap control.
        item["generator_ready"] = bool(words and record.get("type") in {
            "BUTTON", "TAB", "INTERACTIVE_CONTROL", "NAVIGATION", "CONTROL", "CARD",
        })
        item["next_step"] = ("find real page frame and validate MAA candidate"
                             if item["generator_ready"] else
                             "observe clickable control and record its true bounds")
        queue.append(item)
    queue.sort(key=lambda item: (item["priority"], item["pages"], item["family"], item["semantic"]))
    return {"baseline": coverage["totals"], "queue": queue}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write JSON queue to this path")
    args = parser.parse_args()
    payload = build_queue()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"missing targets: {len(payload['queue'])}")
    for level in ("P0", "P1", "P2"):
        rows = [x for x in payload["queue"] if x["priority"] == level]
        print(f"{level}: {len(rows)}; generator-ready: {sum(x['generator_ready'] for x in rows)}")
    if not args.out:
        for row in payload["queue"]:
            print(row["priority"], ",".join(row["pages"]), row["family"], row["semantic"],
                  "READY" if row["generator_ready"] else "OBSERVE")


if __name__ == "__main__":
    main()
