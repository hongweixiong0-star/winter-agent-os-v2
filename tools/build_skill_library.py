from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from winter_agent_v2.skill_factory import SkillFactory
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime import LiveRuntime
import json

factory = SkillFactory(v2_registry(), ROOT / "knowledge/skills/candidate")
written = factory.generate_candidates()
factory.write_coverage(ROOT / "docs/SKILL_COVERAGE.md")
manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
semantics = {item["semantic"] for item in manifest.get("records", [])}
episode_counts = {}
try:
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        skill = json.loads(line).get("skill")
        if skill: episode_counts[skill] = episode_counts.get(skill, 0) + 1
except (OSError, json.JSONDecodeError): pass
audit = factory.automation_audit(set(LiveRuntime.VERIFIED_ATOMIC), semantics, episode_counts)
(ROOT / "docs/GOAL_AUTOMATION_COVERAGE.md").write_text(factory.audit_markdown(audit), encoding="utf-8")
(ROOT / "knowledge/skills/goal_skill_graph.json").write_text(json.dumps(factory.goal_skill_graph(), ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "learning/goal_coverage.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"candidate_specs_written={len(written)}")
