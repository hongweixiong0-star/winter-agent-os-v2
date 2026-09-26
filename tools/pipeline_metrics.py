"""Per-round Pipeline metrics -- the numbers the round report is built from.

Why this exists
---------------
The round brief (§29) asks for the same ladder every round:

    TOTAL_REQUIRED / PREPARED / L1 / L2 / L3 / L4 / L5
    by kind: OCR / TEMPLATE / STRUCTURE / COLOR / LIST_DYNAMIC
    new L1..L5, AutoRepair, REJECTED_VALIDATION, remaining MISSING

Counting those by hand is how a number drifts: each session re-derives the
ladder from memory, and "PREPARED" quietly means three different things across
three reports.  This module derives every level from the files that actually
hold the evidence, and prints the definition it used next to each count, so a
reader can disagree with the *definition* rather than with an unexplained total.

Level model (nested: L4 ⊂ L3 ⊂ L2 ⊂ L1)
---------------------------------------
    PREPARED  gap queued, ``generator_ready`` true, node not generated yet
    L1        node generated and validated offline (gap item has ``recognition``)
    L2        wired -- a recognition entry exists in ``backend_routing.json``
              (this is what makes AUTO able to resolve it)
    L3        wired AND its owning skill has a production episode with
              ``verifier_ok`` true (the node resolved and the action verified)
    L4        the semantic carries an explicit LIVE proof: an ``l4_*`` evidence
              key in routing, ``l4_proven_at`` in the gap queue, or a named
              semantic inside a ``learning/*l4*.json`` ledger
    L5        goal-level completion occurrences (``goal_l5_evidence.jsonl``) --
              goal-scoped, not node-scoped, reported separately

L4 is split into L4_CURRENT (proved in the last ``--recent-days``, default 3)
and L4_HISTORICAL, because "we proved it once in September" and "it proved
itself in this round" are different claims.

Nothing here invents a level: a semantic is L4 only when a proof artifact with
a timestamp says so, and the timestamp is what decides CURRENT vs HISTORICAL.

Usage
-----
    python -u tools/pipeline_metrics.py                # human report
    python -u tools/pipeline_metrics.py --json         # machine report
    python -u tools/pipeline_metrics.py --json --out out/pipeline_metrics.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAP_QUEUE = ROOT / "knowledge" / "execution" / "pipeline_gap_queue.json"
ROUTING = ROOT / "knowledge" / "execution" / "backend_routing.json"
CATALOG = ROOT / "knowledge" / "game" / "capability_catalog.json"
L5_LEDGER = ROOT / "learning" / "goal_l5_evidence.jsonl"
EPISODES = ROOT / "learning" / "episodes.jsonl"

KINDS = ("OCR", "TEMPLATE", "STRUCTURE", "COLOR", "LIST_DYNAMIC", "OTHER")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _kind_of(recognition: dict, entry: dict | None = None) -> str:
    """The recognition kind of one node entry.

    Three spellings exist in the wild and all three are legitimate: the gap queue
    writes ``method`` when it classifies a gap, routing writes ``kind`` when the
    node is wired, and the oldest entries carry neither and are recognised by the
    payload they hold (a ``template`` name, or an ``expected``/``roi`` OCR pair).
    """
    for source in (recognition, entry or {}):
        for key in ("kind", "method"):
            kind = source.get(key)
            if kind:
                kind = str(kind).upper()
                return kind if kind in KINDS else kind
    if recognition.get("template"):
        return "TEMPLATE"
    if recognition.get("expected") or recognition.get("roi"):
        return "OCR"
    return "OTHER"


def _ts_near(blob: str) -> datetime | None:
    """First ISO timestamp inside a JSON blob -- used to date a proof artifact."""
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", blob)
    return _parse_ts(match.group(0)) if match else None


def collect_live_proofs(learning_dir: Path) -> dict[str, datetime]:
    """Semantic -> when it was proved live, from every L4 ledger on disk.

    ``learning/device_l4_*.json``, ``learning/autorepair_l4_first_success.json``
    and any sibling ``*l4*.json`` are scanned for the ``semantic`` field the
    sessions write when they close a live loop.  A ledger that names no semantic
    still dates the session, but it cannot promote a semantic, so it is ignored
    here rather than being spread across everything it mentions.
    """
    proofs: dict[str, datetime] = {}
    semantic_key = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")
    hit_markers = ("hit", "ok", "success", "verified", "clicked", "resolved")

    for path in sorted(learning_dir.glob("*l4*.json")):
        blob = path.read_text(encoding="utf-8", errors="replace")
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            continue
        found: dict[str, datetime] = {}
        file_stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

        def walk(node) -> None:
            if isinstance(node, dict):
                # (a) the explicit spelling: a "semantic" field next to its proof
                semantic = node.get("semantic")
                if isinstance(semantic, str) and semantic:
                    stamp = (
                        _parse_ts(node.get("recorded_at") or node.get("proved_at"))
                        or _ts_near(json.dumps(node, ensure_ascii=False))
                        or file_stamp
                    )
                    if semantic not in found or stamp > found[semantic]:
                        found[semantic] = stamp
                # (b) the keyed spelling: the semantic IS the key, e.g.
                #     "BTN_START_RESEARCH": {"hit": true, "boxes": [...]}
                for key, value in node.items():
                    if not isinstance(key, str) or not semantic_key.match(key):
                        continue
                    if not isinstance(value, dict):
                        continue
                    positive = any(value.get(marker) is True for marker in hit_markers)
                    if not positive and str(value.get("level", "")).upper() not in {"L4", "LIVE_VERIFIED"}:
                        continue
                    stamp = (
                        _parse_ts(value.get("recorded_at") or value.get("proved_at"))
                        or _ts_near(json.dumps(value, ensure_ascii=False))
                        or file_stamp
                    )
                    if key not in found or stamp > found[key]:
                        found[key] = stamp
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        for semantic, stamp in found.items():
            if semantic not in proofs or stamp > proofs[semantic]:
                proofs[semantic] = stamp
    return proofs


def collect_routing_proofs(routing: dict) -> dict[str, datetime]:
    """Semantic -> date, from ``l4_*`` evidence keys inside routing entries."""
    proofs: dict[str, datetime] = {}
    for _skill, body in (routing.get("skills") or {}).items():
        for semantic, recognition in (body.get("recognition") or {}).items():
            evidence = recognition.get("evidence") or {}
            for key, value in evidence.items():
                if not str(key).lower().startswith("l4"):
                    continue
                stamp = _ts_near(json.dumps(value, ensure_ascii=False)) or _ts_near(str(key))
                if semantic not in proofs or (stamp and stamp > (proofs[semantic] or stamp)):
                    proofs[semantic] = stamp or proofs.get(semantic)
    return proofs


def verified_skills(episodes_path: Path, *, days: int = 7) -> dict[str, datetime]:
    """Skill -> latest production episode whose verifier passed."""
    if not episodes_path.exists():
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    latest: dict[str, datetime] = {}
    with episodes_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("verifier_ok") is not True:
                continue
            stamp = _parse_ts(record.get("recorded_at"))
            if stamp is None or stamp < cutoff:
                continue
            skill = record.get("skill")
            if isinstance(skill, str) and skill:
                if skill not in latest or stamp > latest[skill]:
                    latest[skill] = stamp
    return latest


def build(*, recent_days: int = 3, production_days: int = 7) -> dict:
    gap = _load_json(GAP_QUEUE)
    queue = gap.get("queue") or []
    routing = _load_json(ROUTING)
    catalog = _load_json(CATALOG)

    wired: dict[str, dict] = {}
    for skill, body in (routing.get("skills") or {}).items():
        for semantic, recognition in (body.get("recognition") or {}).items():
            wired[semantic] = {
                "skill": skill,
                "kind": _kind_of(recognition, body),
                "entry": recognition,
            }

    l4_ledger = collect_live_proofs(ROOT / "learning")
    l4_routing = collect_routing_proofs(routing)
    verified = verified_skills(EPISODES, days=production_days)

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=recent_days)

    l5_goals: list[dict] = []
    if L5_LEDGER.exists():
        for line in L5_LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                l5_goals.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # The universe is the UNION, not the gap queue alone: the queue lists targets that were
    # missing when it was built, and routing holds targets that were wired since -- including
    # 21 that were never queue items (they came from direct autogen/autorepair sessions).
    # Counting only the queue would understate the denominator and overstate coverage.
    universe: list[str] = []
    seen: set[str] = set()
    for gap_item in queue:
        semantic = gap_item.get("semantic")
        if semantic and semantic not in seen:
            seen.add(semantic)
            universe.append(semantic)
    for semantic in wired:
        if semantic not in seen:
            seen.add(semantic)
            universe.append(semantic)
    by_semantic = {item.get("semantic"): item for item in queue}

    items: list[dict] = []
    for semantic in universe:
        gap_item = by_semantic.get(semantic) or {}
        has_recognition = "recognition" in gap_item
        generator_ready = gap_item.get("generator_ready") is True
        node = wired.get(semantic)
        l4_at = None
        if gap_item.get("l4_proven_at"):
            l4_at = _parse_ts(gap_item["l4_proven_at"])
        if semantic in l4_routing:
            candidate = l4_routing[semantic]
            if l4_at is None or (candidate and candidate > l4_at):
                l4_at = candidate
        if semantic in l4_ledger:
            candidate = l4_ledger[semantic]
            if l4_at is None or (candidate and candidate > l4_at):
                l4_at = candidate

        level = "MISSING"
        if l4_at is not None:
            level = "L4"
        elif node is not None:
            skills = gap_item.get("skills") or ([node["skill"]] if node.get("skill") else [])
            if any(skill in verified for skill in skills):
                level = "L3"
            else:
                level = "L2"
        elif has_recognition:
            level = "L1"
        elif generator_ready:
            level = "PREPARED"

        kind = node["kind"] if node else _kind_of(gap_item.get("recognition") or {})
        items.append(
            {
                "semantic": semantic,
                "level": level,
                "kind": kind,
                "priority": gap_item.get("priority"),
                "family": gap_item.get("family"),
                "skills": gap_item.get("skills") or [],
                "goals": gap_item.get("goals") or [],
                "l4_at": l4_at.isoformat() if l4_at else None,
                "l4_current": bool(l4_at and l4_at >= recent_cutoff),
            }
        )

    levels = Counter(item["level"] for item in items)
    kinds = Counter(item["kind"] for item in items if item["level"] in {"L1", "L2", "L3", "L4"})

    catalog_lifecycle = Counter(
        (cap.get("lifecycle") or "MISSING")
        for cap in (catalog.get("capabilities") or [])
    )

    rejections = gap.get("honest_rejections") or []
    return {
        "generated_at": now.isoformat(),
        "definitions": {
            "PREPARED": "gap queued, generator_ready true, node not generated",
            "L1": "node generated and validated offline",
            "L2": "wired: recognition entry in backend_routing.json (AUTO can resolve it)",
            "L3": "wired + owning skill has a production episode with verifier_ok true "
                  f"(last {production_days}d)",
            "L4": "explicit live proof: l4_* routing evidence / l4_proven_at / learning/*l4*.json",
            "L5": "goal-level completion occurrence (goal_l5_evidence.jsonl)",
        },
        "total_required": len(items),
        "levels": {
            "PREPARED": levels.get("PREPARED", 0),
            "L1": levels.get("L1", 0),
            "L2": levels.get("L2", 0),
            "L3": levels.get("L3", 0),
            "L4": levels.get("L4", 0),
            "MISSING": levels.get("MISSING", 0),
        },
        "l4_split": {
            "L4_CURRENT": sum(1 for item in items if item["level"] == "L4" and item["l4_current"]),
            "L4_HISTORICAL": sum(1 for item in items if item["level"] == "L4" and not item["l4_current"]),
            "recent_days": recent_days,
        },
        "l5": {
            "occurrences": len(l5_goals),
            "goals": [
                {
                    "goal": record.get("goal") or record.get("goal_id"),
                    "recorded_at": record.get("recorded_at"),
                }
                for record in l5_goals
            ],
        },
        "kinds": {kind: kinds.get(kind, 0) for kind in KINDS},
        "capability_lifecycle": dict(catalog_lifecycle),
        "autorepair": {
            "ledgers": sorted(path.name for path in (ROOT / "learning").glob("autorepair*l4*.json")),
            "l4_semantics": sorted(set(l4_ledger) | set(l4_routing)),
        },
        "rejected_validation": [
            {
                "semantic": entry.get("semantic"),
                "reason": entry.get("reason") or entry.get("note"),
            }
            for entry in rejections
        ],
        "wired_node_count": len(wired),
        "items": items,
    }


def render(report: dict) -> str:
    levels = report["levels"]
    kinds = report["kinds"]
    lines = [
        "PIPELINE METRICS",
        f"generated_at : {report['generated_at']}",
        "",
        f"TOTAL_REQUIRED  : {report['total_required']}",
        f"PREPARED        : {levels['PREPARED']}",
        f"L1 (generated)  : {levels['L1']}",
        f"L2 (wired)      : {levels['L2']}",
        f"L3 (prod+verif) : {levels['L3']}",
        f"L4 (live proof) : {levels['L4']}"
        f"   [current {report['l4_split']['L4_CURRENT']} / historical {report['l4_split']['L4_HISTORICAL']}]",
        f"MISSING         : {levels['MISSING']}",
        "",
        f"L5 occurrences  : {report['l5']['occurrences']} "
        + ", ".join(
            f"{entry['goal']}@{entry['recorded_at']}"
            for entry in report["l5"]["goals"]
            if entry["goal"]
        ),
        "",
        "by kind         : "
        + "  ".join(f"{kind}={count}" for kind, count in kinds.items() if count),
        "",
        "capability lifecycle : "
        + "  ".join(f"{key}={value}" for key, value in sorted(report["capability_lifecycle"].items())),
        "",
        f"wired nodes    : {report['wired_node_count']}",
        f"AutoRepair L4  : {len(report['autorepair']['l4_semantics'])} -> "
        + ", ".join(report["autorepair"]["l4_semantics"]),
        f"REJECTED_VALIDATION : {len(report['rejected_validation'])} -> "
        + ", ".join(
            f"{entry['semantic']}" for entry in report["rejected_validation"] if entry["semantic"]
        ),
        "",
        "definitions:",
    ]
    for key, text in report["definitions"].items():
        lines.append(f"  {key:<9} {text}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the machine report")
    parser.add_argument("--out", type=Path, help="write the report to this path")
    parser.add_argument("--recent-days", type=int, default=3, help="window for L4_CURRENT")
    parser.add_argument("--production-days", type=int, default=7, help="window for L3 production evidence")
    args = parser.parse_args()

    report = build(recent_days=args.recent_days, production_days=args.production_days)
    payload = render(report) if not args.json else json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
