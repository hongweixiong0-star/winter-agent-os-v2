"""Executor Reality Audit — what each skill will ACTUALLY use, not what we wish.

The operator directive of 2026-09-14 requires a scan of every registered skill
that answers four questions per skill:

* which backend is it on today (from recorded executions, not from intent),
* which backend would run if it were dispatched now,
* does its recognition come from MAA or from the V2 semantic vision,
* and how has it performed on the live client.

Everything is joined from real files:

``winter_agent_v2/skills.py``            the registry (the definition of "a skill")
``LiveRuntime.VERIFIED_ATOMIC``          skills that can actually be dispatched
``knowledge/execution/backend_routing.json``  the routing decisions + their evidence
``learning/episodes.jsonl``              production attempts and outcomes
``learning/executor_backend.jsonl``      which backend really ran, per action

Nothing here is hand-written, so the audit cannot drift away from the code.

    E:/dongri-mumu-bot/.venv/Scripts/python.exe -u tools/executor_audit.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.executor_router import ADB, HYBRID, MAA, NOT_IMPLEMENTED, RoutingTable  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

EPISODES = ROOT / "learning/episodes.jsonl"
LEDGER = ROOT / "learning/executor_backend.jsonl"
MAP_PATH = ROOT / "knowledge/coverage/executor_backend_map.json"
DOC_PATH = ROOT / "docs/EXECUTOR_REALITY_AUDIT.md"
# The historical path: Python decides the target from a fixed ROI and ADB taps.
HISTORICAL = "ADB_PYTHON_VISION"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def classify(skill_id: str, has_verifier: bool, route, ledger_rows: list[dict]) -> tuple[str, str]:
    """Return ``(classification, current_backend)``.

    ``classification`` says what the skill WOULD use now; ``current_backend`` says
    what it has actually used, taken from the ledger so it cannot be aspirational.
    """
    if not has_verifier:
        return NOT_IMPLEMENTED, "NONE"
    used = Counter(
        row.get("used_backend") for row in ledger_rows
        if row.get("skill_id") == skill_id and row.get("executed")
    )
    if used:
        current = used.most_common(1)[0][0] or "NONE"
    elif route.preferred == MAA:
        current = MAA
    else:
        current = HISTORICAL
    if route.preferred != MAA:
        return HISTORICAL, current
    recognition = route.recognition_backend or ("MAA" if route.recognition else "LEGACY")
    if recognition in {"MAA", "NONE"}:
        return MAA, current
    return HYBRID, current


def main() -> int:
    registry = v2_registry()
    routing = RoutingTable.load()
    episodes = read_jsonl(EPISODES)
    ledger = read_jsonl(LEDGER)

    attempts: dict[str, Counter] = defaultdict(Counter)
    for row in episodes:
        skill = str(row.get("skill") or "")
        if not skill:
            continue
        attempts[skill]["attempts"] += 1
        # ``result`` is the authoritative outcome: the runtime sets it to SUCCESS
        # only when the action executed AND the verifier passed.  ``verifier_ok``
        # is only populated on the newer code path (it is None for most of the
        # 918 historical episodes), so counting on it reported OPEN_HOME as 0/23
        # when its episodes actually read 20 SUCCESS / 3 FAILURE.
        if row.get("result") == "SUCCESS":
            attempts[skill]["success"] += 1
        verifier = row.get("verifier_ok")
        attempts[skill][
            "verifier_true" if verifier is True
            else "verifier_false" if verifier is False
            else "verifier_unknown"
        ] += 1
        backend = str(row.get("executor_backend") or "UNRECORDED")
        attempts[skill][f"backend:{backend}"] += 1

    rows: list[dict] = []
    for skill in registry.all():
        route = routing.route(skill.id)
        promoted = routing.skills.get(skill.id, {})
        has_verifier = skill.id in LiveRuntime.VERIFIED_ATOMIC
        verifier = LiveRuntime.VERIFIED_ATOMIC.get(skill.id)
        classification, current = classify(skill.id, has_verifier, route, ledger)
        stats = attempts.get(skill.id, Counter())
        total = stats.get("attempts", 0)
        success = stats.get("success", 0)
        rows.append({
            "skill_id": skill.id,
            "required_page": None if skill.required_page is None else skill.required_page.value,
            "action_kind": skill.action.kind,
            "current_backend": current,
            "classification": classification,
            "preferred_backend": route.preferred if route.source == "table" else ADB,
            "fallback_backend": route.fallback if route.source == "table" else ADB,
            "vision_backend": (promoted.get("recognition_backend")
                               or ("MAA" if promoted.get("recognition") else "V2_SEMANTIC")),
            "verifier_backend": ("V2:" + getattr(verifier, "__name__", "?")) if has_verifier else "NONE",
            "live_attempts": total,
            "live_success": success,
            "success_rate": round(success / total, 4) if total else None,
            "verifier_ok_true": stats.get("verifier_true", 0),
            "verifier_ok_false": stats.get("verifier_false", 0),
            "verifier_ok_unrecorded": stats.get("verifier_unknown", 0),
            "backends_seen": {k.split(":", 1)[1]: v for k, v in stats.items()
                              if k.startswith("backend:")},
            "migration_priority": promoted.get("migration_priority", "P3"),
            "evidence": bool(promoted.get("evidence")),
            # Promotion gate state, so the doc can list what is promoted but not
            # yet validated.  ``None`` means the axis needs no recognition node.
            "corpus_sufficient": (promoted.get("evidence") or {}).get("corpus_sufficient"),
            "validation_gap": (promoted.get("evidence") or {}).get("validation_gap", ""),
        })

    rows.sort(key=lambda r: (r["migration_priority"], -r["live_attempts"], r["skill_id"]))
    summary = Counter(r["classification"] for r in rows)
    promoted = [r for r in rows if r["preferred_backend"] == MAA]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry_size": len(rows),
        "dispatchable": sum(1 for r in rows if r["classification"] != NOT_IMPLEMENTED),
        "classification": dict(summary),
        "promoted_to_maa": len(promoted),
        "device_axis": routing.device_evidence,
        "ledger_rows": len(ledger),
        "skills": rows,
    }
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Executor Reality Audit",
        "",
        "Generated by `tools/executor_audit.py` — do not hand-edit.",
        f"Generated at {payload['generated_at']}.",
        "",
        "## What this measures",
        "",
        "Per registered skill: the backend that would run now, the backend that has",
        "actually run (from the production ledger, never from configuration), who does",
        "the recognition, who judges the result, and the live record.",
        "",
        "Classification counts: " + ", ".join(f"**{k}** {v}" for k, v in sorted(summary.items())),
        "",
        f"Skills promoted to MAA: **{payload['promoted_to_maa']}** "
        f"of {payload['dispatchable']} dispatchable ({payload['registry_size']} registered).",
        "",
        "## Device axis (measured on the live client)",
        "",
        "```json",
        json.dumps(routing.device_evidence, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Skills",
        "",
        "| skill | classification | current | preferred | fallback | vision | verifier | attempts | success | backends recorded | priority |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        rate = "-" if r["success_rate"] is None else f"{r['success_rate']:.0%}"
        seen = r["backends_seen"] or {}
        seen_text = ", ".join(f"{k}×{v}" for k, v in sorted(seen.items())) or "-"
        lines.append(
            f"| `{r['skill_id']}` | {r['classification']} | {r['current_backend']} | "
            f"{r['preferred_backend']} | {r['fallback_backend']} | {r['vision_backend']} | "
            f"{r['verifier_backend']} | {r['live_attempts']} | {rate} | {seen_text} | "
            f"{r['migration_priority']} |"
        )
    recorded = sum(1 for r in rows for k in r["backends_seen"] if k != "UNRECORDED")
    lines += [
        "",
        "## Two measurement caveats, stated rather than smoothed over",
        "",
        "1. **`success` is read from the episode's `result` field**, not from",
        "   `verifier_ok`.  The runtime sets `result = SUCCESS` only when the action",
        "   executed *and* the verifier passed, and it is populated on every",
        "   episode; `verifier_ok` is `None` on most of the 918 historical rows, so",
        "   counting on it reported `OPEN_HOME` as 0/23 when its episodes read",
        "   20 SUCCESS / 3 FAILURE.",
        f"2. **`executor_backend` is a new field.**  {recorded} recorded backend",
        "   observations exist so far; every historical row reads `UNRECORDED`,",
        "   which is the honest value - those steps ran before the field existed and",
        "   nothing here will retro-label them as MAA.",
        "",
        "## Promoted but not yet validated",
        "",
        "These skills run on MAA and have a measured recognition node, but their",
        "corpus is below the >=3-independent-positives gate.  They must not be",
        "called validated.  The gate exists because a one-frame corpus promoted",
        "`BTN_OPEN_INTEL_WILD_HUD` and it regressed production on the first live",
        "frame (correct box, correlation 0.448 against a 0.7 threshold, because the",
        "control animates).",
        "",
    ]
    gaps = [r for r in rows if r["corpus_sufficient"] is False]
    if gaps:
        for r in gaps:
            lines.append(f"- `{r['skill_id']}` — {r['validation_gap']}")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Reading the classification",
        "",
        "- `MAA` — MAA captures and either MAA or no recogniser resolves the target;",
        "  ADB stays as the fallback backend.",
        "- `HYBRID` — MAA captures and clicks, the V2 semantic vision resolves the target.",
        "  The honest state for a skill whose recognition node has not been measured yet.",
        "- `ADB_PYTHON_VISION` — the historical path, unchanged.",
        "- `NOT_IMPLEMENTED` — no verifier registered, so the scheduler will never",
        "  dispatch it. It cannot be migrated before it exists.",
        "",
        "## Known gap",
        "",
        "A promoted skill shows `HYBRID` until a recognition node for its semantic is",
        "authored AND measured by `tools/maa_migrate.py`. Promotion of the device axis is",
        "evidence-backed today; promotion of the recognition axis is per semantic and is",
        "tracked in `knowledge/execution/backend_routing.json`.",
        "",
    ]
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"registry {len(rows)}  dispatchable {payload['dispatchable']}  "
          f"promoted {payload['promoted_to_maa']}")
    print("classification:", dict(summary))
    print(f"wrote {MAP_PATH.relative_to(ROOT)}")
    print(f"wrote {DOC_PATH.relative_to(ROOT)}")
    print("\npromoted skills:")
    for r in promoted:
        print(f"  {r['skill_id']:32s} {r['classification']:8s} vision={r['vision_backend']:10s} "
              f"attempts={r['live_attempts']:3d} success={r['success_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
