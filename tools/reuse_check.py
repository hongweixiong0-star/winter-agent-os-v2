"""The 2-minute Reuse Check, as one command.

Why this exists
---------------
The operator's rule (2026-09-17): before developing ANY capability, spend two
minutes checking whether V2 already has it, and only then escalate outward.

    禁止已经有成熟本地实现还跑去 GitHub 重新研究。
    禁止外部已有成熟实现却自己摸 UI 两小时。

A written rule is advisory; this makes it a command.  Twice now (TRAIN and RESEARCH>
on 2026-09-17) a whole route turned out to already exist -- the brain route, the
verifier bindings, the factory contract and even the measured route in
``knowledge/skills/<X>_RESEARCH.md`` -- and the only thing missing was a template
that resolves on today's client.  In both cases the time went into assuming the UI
had to be explored from scratch.

Usage
-----
    python tools/reuse_check.py ARENA
    python tools/reuse_check.py ARENA ALLIANCE_HELP BUILD

Read-only: it reports, it does not modify anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The escalation triggers, exactly as the operator listed them.  This tool can
# detect the first one and the last one; the rest are judgement calls it prints as
# a checklist so the decision is made deliberately rather than drifted into.
ESCALATION_TRIGGERS = (
    "MISSING (not in the capability catalog at all)",
    "never implemented (no skill / no verifier)",
    "UI unknown (does not know the entry or its appearance)",
    "gameplay unknown (does not know the inputs and outcomes)",
    "navigation unknown (does not know which page, which hops)",
    "repeated live failure",
    "15-30 min spent without a reliable implementation",
)


def _term_regex(term: str) -> re.Pattern[str]:
    return re.compile(re.escape(term), re.IGNORECASE)


def registry_hits(term: str) -> list[str]:
    from winter_agent_v2.skills import v2_registry

    rx = _term_regex(term)
    rows = []
    for skill in v2_registry().all():
        action = getattr(skill, "action", None)
        target = getattr(action, "target", None) or getattr(action, "kind", None)
        blob = " ".join(str(x) for x in (skill.id, target, skill.required_page, skill.semantic_goal))
        if rx.search(blob):
            rows.append(
                f"{skill.id}  state={getattr(skill.state, 'value', skill.state)}"
                f"  page={skill.required_page}  action={target}"
            )
    return rows


def brain_hits(term: str) -> list[str]:
    rx = _term_regex(term)
    path = ROOT / "winter_agent_v2" / "brain.py"
    return [
        f"brain.py:{number}  {line.strip()[:120]}"
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1)
        if rx.search(line)
    ]


def verifier_hits(term: str) -> tuple[list[str], list[str]]:
    """(bindings that exist, bindings with a live episode behind them)."""
    from winter_agent_v2.runtime import LiveRuntime

    rx = _term_regex(term)
    bound = []
    for key, verifier in sorted(LiveRuntime.VERIFIED_ATOMIC.items()):
        name = getattr(verifier, "__name__", str(verifier))
        if rx.search(f"{key} {name}"):
            bound.append(f"{key}  ->  {name}")
    live = []
    episodes = ROOT / "learning" / "episodes.jsonl"
    if episodes.is_file():
        counter: Counter[tuple[str, str]] = Counter()
        last: dict[str, str] = {}
        for line in episodes.read_text(encoding="utf-8", errors="replace").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            skill = str(row.get("skill") or "")
            if not rx.search(skill):
                continue
            # Only rows carrying recorded_at count as live evidence (the project's
            # own gate); the rest come from the legacy writer.
            if not row.get("recorded_at"):
                counter[(skill, "NO_recorded_at")] += 1
                continue
            counter[(skill, str(row.get("result")))] += 1
            if row.get("verifier_ok") is not None:
                last[skill] = row["recorded_at"]
        for (skill, result), count in counter.most_common(12):
            stamp = f"  last={last.get(skill, '-')}" if result == "SUCCESS" else ""
            live.append(f"{skill:<34} {result:<16} x{count}{stamp}")
    return bound, live


def contract_hits(term: str) -> list[str]:
    rx = _term_regex(term)
    from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS

    return [
        f"{goal}  requires {skills}"
        for goal, skills in GOAL_REQUIREMENTS.items()
        if rx.search(goal) or any(rx.search(str(s)) for s in skills)
    ]


def knowledge_hits(term: str) -> list[str]:
    rx = _term_regex(term)
    rows = []
    for base in ("knowledge", "docs"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.is_file() and rx.search(path.name):
                rows.append(str(path.relative_to(ROOT)))
    return rows[:20]


def legacy_evidence(term: str) -> list[str]:
    """Measured coordinates/ROI/routes the project already recorded."""
    rx = _term_regex(term)
    rows = []
    for base in ("dataset/truth_audit", "evidence"):
        directory = ROOT / base
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and rx.search(str(path.relative_to(ROOT))):
                rows.append(str(path.relative_to(ROOT)))
    return rows[:20]


def external_hits(term: str) -> list[dict]:
    path = ROOT / "knowledge" / "external" / "external_capability_map.json"
    if not path.is_file():
        return []
    rx = _term_regex(term)
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for card in payload.get("capabilities", []):
        blob = " ".join(str(v) for v in card.values())
        if rx.search(blob):
            rows.append(card)
    return rows


def local_path_exists(term: str) -> bool:
    """True when V2 already has a usable route: a verifier AND (route or skill).

    The operator's rule is that a local route means the external search does not
    happen at all, so this predicate is the whole decision.  It is deliberately
    conservative: a verifier binding alone does not count, because a verifier with
    no route or skill is not something you can run.
    """
    bound, _ = verifier_hits(term)
    return bool(bound) and (bool(brain_hits(term)) or bool(registry_hits(term)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("terms", nargs="+", help="capability names, e.g. ARENA BUILD")
    args = parser.parse_args()

    for term in args.terms:
        print("=" * 78)
        print(f"REUSE CHECK :: {term}")
        print("=" * 78)

        print("\n-- 1. skill (v2_registry) --")
        for row in registry_hits(term) or ["(none)"]:
            print("   ", row)

        print("\n-- 2. brain route (no route != no capability) --")
        for row in brain_hits(term) or ["(none)"]:
            print("   ", row)

        print("\n-- 3. verifier binding + live history --")
        bound, live = verifier_hits(term)
        for row in bound or ["(none)"]:
            print("   ", row)
        if live:
            print("    live episodes (recorded_at only counts):")
            for row in live:
                print("      ", row)

        print("\n-- 4. factory contract --")
        for row in contract_hits(term) or ["(none)"]:
            print("   ", row)

        print("\n-- 5. knowledge / docs --")
        for row in knowledge_hits(term) or ["(none)"]:
            print("   ", row)

        print("\n-- 6. legacy evidence on disk --")
        for row in legacy_evidence(term) or ["(none)"]:
            print("   ", row)

        cards = external_hits(term)
        print(f"\n-- 7. external index ({len(cards)} card(s)) --")
        for card in cards:
            files = card.get("source_files") or []
            print(f"    {card.get('capability')}  [{card.get('repo')}]  "
                  f"reuse={card.get('reuse_level')}  license={str(card.get('license'))[:40]}")
            for source in files[:4]:
                print(f"        source: {source}")
            if card.get("current_gap"):
                print(f"        gap:    {str(card['current_gap'])[:150]}")

        # Verdict: a local route that exists is reused, not re-researched.
        local_exists = local_path_exists(term)
        print("\n-- 8. verdict --")
        if local_exists:
            print("    LOCAL PATH EXISTS -> reuse it. Do not open GitHub.")
            print("    Next: measure which template/decision is missing on today's client,")
            print("    then follow docs/ADDING_A_LIVE_ROUTE.md from step 1.")
        else:
            print("    NO LOCAL PATH -> escalate, in this order:")
            for index, trigger in enumerate(ESCALATION_TRIGGERS, 1):
                print(f"      {index}. {trigger}")
            print("    Then: knowledge/external/external_capability_map.json -> its")
            print("    source_files, and write any NEW finding back into that index.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
