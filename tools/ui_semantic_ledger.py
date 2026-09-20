"""Build the generic-UI-semantics ledger the operator asked for -- DERIVED, not authored.

The operator's step 2 asks for one entry per repeated UI element carrying: real
screenshot or OCR evidence, the original text, the generic meaning, the page, the object
it belongs to, the clickable area, the risk, the Skill and the Verifier -- with UNKNOWN
kept where the project has not measured it.

Every one of those fields already exists somewhere in this repository, so this tool
*derives* the ledger instead of writing a second dictionary by hand.  That is the point:
a hand-written ledger would be a second source of truth for facts the manifest, the
registry and the verifier table already own, and the two would drift.

Sources, and which field each one supplies:

    dataset/candidate/template_manifest.json   evidence (templates, status, source, matcher),
                                               clickable area (roi_norm), page (via the
                                               semantic dictionary where it names one)
    winter_agent_v2/skills.py                  role (action kind + the skill's own
                                               semantic_goal), risk, page, used_by_skills
    winter_agent_v2/runtime.py VERIFIED_ATOMIC verifier, and therefore schedulability
    knowledge/ui/semantic_dictionary.json      the candidate text/aliases and pages
    knowledge/ui/semantic_evidence.json        whether the current client actually shows it
    out_semantic_reuse.json                    how many distinct pages it matches on

Anything none of those can answer stays UNKNOWN -- notably "which object does this
element belong to", which is a per-frame question and not a property of the element.

Usage:
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/ui_semantic_ledger.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
DICTIONARY = ROOT / "knowledge" / "ui" / "semantic_dictionary.json"
EVIDENCE = ROOT / "knowledge" / "ui" / "semantic_evidence.json"
REUSE = ROOT / "out_semantic_reuse.json"
OUT = ROOT / "knowledge" / "ui" / "generic_semantics.json"

UNKNOWN = "UNKNOWN"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]
    dictionary = json.loads(DICTIONARY.read_text(encoding="utf-8"))["records"]
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {}
    reuse = json.loads(REUSE.read_text(encoding="utf-8")) if REUSE.exists() else {}

    by_semantic: dict[str, list[dict]] = {}
    for record in manifest:
        by_semantic.setdefault(record["semantic"], []).append(record)

    registry = v2_registry()
    skills_by_target: dict[str, list] = {}
    for skill in registry.all():
        if skill.action.target:
            skills_by_target.setdefault(skill.action.target, []).append(skill)

    dict_by_id = {r["id"]: r for r in dictionary}
    evidence_by_id = {r["id"]: r for r in evidence.get("confirmed", [])}
    evidence_gap = {r["id"]: r for r in evidence.get("unconfirmed", [])}
    reuse_by_semantic = {r["semantic"]: r for r in reuse.get("rows", [])}

    entries = []
    for semantic in sorted(by_semantic):
        records = by_semantic[semantic]
        skills = skills_by_target.get(semantic, [])
        bound = [s for s in skills if s.id in LiveRuntime.VERIFIED_ATOMIC]
        verifiers = sorted({LiveRuntime.VERIFIED_ATOMIC[s.id].__name__ for s in bound})
        reuse_row = reuse_by_semantic.get(semantic, {})
        entry = {
            "semantic": semantic,
            # what it is
            "kind": "TEMPLATE_BACKED",
            "evidence": {
                "templates": len(records),
                "statuses": sorted({r.get("status", UNKNOWN) for r in records}),
                "sources": sorted({r.get("source", UNKNOWN) for r in records}),
                "matchers": sorted({r.get("matcher", "phash") for r in records}),
                "measured": any(r.get("measured") for r in records),
            },
            "clickable_area": records[0].get("roi_norm", UNKNOWN),
            # where it lives
            "pages_measured": reuse_row.get("by_page", UNKNOWN),
            "pages_declared": dict_by_id.get(semantic, {}).get("pages", UNKNOWN),
            "best_distance": reuse_row.get("best_distance", UNKNOWN),
            "gate": reuse_row.get("gate", UNKNOWN),
            # who uses it, and how it is proved
            "used_by_skills": [s.id for s in skills] or [],
            "schedulable_skills": [s.id for s in bound],
            "verifiers": verifiers or [],
            "risk": sorted({s.risk for s in skills}) or UNKNOWN,
            "page": sorted({s.required_page.value for s in skills if s.required_page}) or UNKNOWN,
            "role": sorted({s.semantic_goal for s in skills if s.semantic_goal}) or UNKNOWN,
            # what it belongs to: a per-frame question, not a property of the element
            "belongs_to": UNKNOWN,
            "unknown_reason": "所属对象是逐帧上下文（哪张任务卡/哪支队伍），不是元素自身属性；由 WorldState 提供",
        }
        if not skills:
            entry["role"] = UNKNOWN
            entry["unknown_reason_zh"] = "没有任何技能点名这个语义 ⇒ 它是识别专用（页面身份/状态标记），或尚未接入"
        entries.append(entry)

    # The dictionary candidates that have no visual evidence at all: the operator's
    # "尚需校准" list, kept in the same ledger so the gap is not a separate document.
    candidates = []
    for record in dictionary:
        hit = [s for s in by_semantic if s == record["id"]
               or s == (record.get("icon_semantic") or "").upper()]
        if hit:
            continue
        candidates.append({
            "candidate_id": record["id"],
            "kind": "CANDIDATE_NO_VISUAL_EVIDENCE",
            "cn": record.get("cn"),
            "text_aliases": record.get("ocr"),
            "declared_pages": record.get("pages"),
            "client_evidence": evidence_by_id.get(record["id"], {}).get("pages_seen", []),
            "client_text_seen": evidence_by_id.get(record["id"], {}).get("strings_seen", UNKNOWN),
            "status": record.get("status", "CANDIDATE"),
            "source": record.get("source", UNKNOWN),
            "clickable_area": UNKNOWN,
            "verifier": UNKNOWN,
            "requires": "真机模板注册（≥3 独立正样本 + 反例 + 实测闸门）",
            "blocked_evidence": evidence_gap.get(record["id"], {}).get("wanted", UNKNOWN),
        })

    payload = {
        "schema_version": "1.0",
        "purpose": "通用 UI 语义台账：每个元素的证据、页面、可点区域、风险、对应 Skill 与 Verifier。"
                   "**派生**自已有的 manifest / registry / VERIFIED_ATOMIC / 语义词典 / 复用测量 / OCR 证据，"
                   "不是手写第二份事实。字段缺失一律 UNKNOWN。",
        "generated_by": "tools/ui_semantic_ledger.py",
        "sources": {
            "manifest": str(MANIFEST.relative_to(ROOT)),
            "registry": "winter_agent_v2/skills.py",
            "verifier_table": "winter_agent_v2/runtime.py::LiveRuntime.VERIFIED_ATOMIC",
            "dictionary": str(DICTIONARY.relative_to(ROOT)),
            "client_evidence": str(EVIDENCE.relative_to(ROOT)) if EVIDENCE.exists() else UNKNOWN,
            "reuse_measurement": str(REUSE.relative_to(ROOT)) if REUSE.exists() else UNKNOWN,
        },
        "counts": {
            "template_backed_semantics": len(entries),
            "template_backed_with_a_schedulable_skill": sum(1 for e in entries if e["schedulable_skills"]),
            "template_backed_recognition_only": sum(1 for e in entries if not e["used_by_skills"]),
            "candidates_without_visual_evidence": len(candidates),
        },
        "entries": entries,
        "candidates_without_visual_evidence": candidates,
        "unnamed_client_strings": evidence.get("strings_unnamed_by_the_dictionary", []),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
