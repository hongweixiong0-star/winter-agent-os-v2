from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.semantic_gate import audit_vision_asset, semantic_robustness_gate
from winter_agent_v2.skills import v2_registry


def main() -> int:
    manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    assets = manifest.get("records", [])
    asset_results = [(row, audit_vision_asset(row)) for row in assets]
    skills = v2_registry().all()
    skill_results = [(skill, semantic_robustness_gate(skill)) for skill in skills]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "SEMANTIC_FIRST",
        "vision_assets": {
            "total": len(asset_results),
            "passed": sum(result.ok for _, result in asset_results),
            "failed": sum(not result.ok for _, result in asset_results),
            "failures": [{"template_id":row.get("template_id"), "reasons":result.failures}
                         for row, result in asset_results if not result.ok],
        },
        "skills": {
            "total": len(skill_results),
            "semantic_contract_complete": sum(result.ok for _, result in skill_results),
            "legacy_or_incomplete": sum(not result.ok for _, result in skill_results),
            "failures": [{"skill_id":skill.id, "state":skill.state.value, "reasons":result.failures}
                         for skill, result in skill_results if not result.ok],
        },
    }
    target = ROOT / "evidence/semantic_first_audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    print(json.dumps({"report":str(target), "vision_assets":payload["vision_assets"],
                      "skills":{"total":payload["skills"]["total"],
                                "semantic_contract_complete":payload["skills"]["semantic_contract_complete"],
                                "legacy_or_incomplete":payload["skills"]["legacy_or_incomplete"]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
