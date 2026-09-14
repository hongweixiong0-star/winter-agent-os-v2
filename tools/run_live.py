from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.goal_library import GoalStateStore
from winter_agent_v2.candidate_policy import CandidateAttemptPool
from winter_agent_v2.vision import SemanticWorldVision
from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore
from winter_agent_v2.resource_rotation import ResourceRotationStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded, verifier-gated V2 live loop")
    parser.add_argument("--max-actions", type=int, default=10)
    parser.add_argument("--capture-dir", type=Path, default=ROOT / "dataset/raw/live_runtime")
    parser.add_argument("--goal", choices=["HOME", "GATHER_RESOURCE", "BEAST_HUNT", "INTEL", "MAIL", "EXPLORATION", "DAILY", "ALLIANCE", "RESEARCH", "TRAIN"], default=None)
    parser.add_argument("--stop-after", default=None, help="Stop after this skill passes its verifier")
    parser.add_argument("--serial", default=None, help="Device selected by the control panel")
    args = parser.parse_args()

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    if not config.get("production") or config.get("dry_run"):
        raise RuntimeError("LIVE_RUNTIME_REQUIRES_PRODUCTION_TRUE_AND_DRY_RUN_FALSE")

    device = ADBDevice(
        Path(config["device"]["adb_path"]),
        args.serial or config["device"]["serial"],
        production=True,
    )
    if args.serial is None:
        device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    vision = HybridVision(
        template,
        OCRService(
            ResilientOCRBackend(
                RapidOCRBackend(Path(config["ocr"]["module_path"]))
            )
        ),
    )
    verifier_skills = set(LiveRuntime.VERIFIED_ATOMIC)
    result = LiveRuntime(
        device=device,
        vision=vision,
        semantic_vision=template.semantic,
        capture_dir=args.capture_dir,
        brain=RuleBrain(
            current_goal=args.goal,
            reserve_marches=int(config.get("march_policy", {}).get("reserve_for_stamina", 0)),
            # Operator directive 2026-09-14: a march may be recalled at any time
            # when a higher-priority task (stamina spending, or a verification
            # run that needs a slot) has a better use for it.
            recall_on_demand=bool(config.get("march_policy", {}).get("recall_on_demand", False)),
            claim_free_stamina=bool(config.get("stamina_policy", {}).get("claim_free_stamina", False)),
        ),
        episode_store=EpisodeStore(ROOT / "learning/episodes.jsonl", limit=int(config.get("retention", {}).get("episode_limit", 10000))),
        goal_store=GoalStateStore(ROOT / "learning/goal_state.json"),
        candidate_pool=CandidateAttemptPool(ROOT / "learning/candidate_attempt_pool.json",
                                            verifier_skills=verifier_skills,
                                            recovery_skills=verifier_skills,
                                            threshold=5),
        runtime_store=RuntimeSnapshotStore(ROOT / "learning/runtime_snapshot.json"),
        resource_rotation=ResourceRotationStore(ROOT / "learning/resource_rotation.json"),
    ).run(max_actions=args.max_actions, stop_after_skill=args.stop_after)
    print(json.dumps(asdict(result), ensure_ascii=False, default=str))
    accepted_stops = {"TARGET_SKILL_VERIFIED", "MAX_ACTIONS_REACHED", "no_idle_march", "reserved_march_for_stamina", "verified_beast_target_not_visible", "intel_available_no_claim", "mail_all_clear", "exploration_income_not_ready", "daily_no_claimable_rewards", "daily_state_unknown_or_not_actionable", "alliance_action_not_needed", "research_queue_busy", "training_queue_busy"}
    verified = all(step.verification is None or step.verification.ok for step in result.steps)
    return 0 if verified and result.stop_reason in accepted_stops else 2


if __name__ == "__main__":
    raise SystemExit(main())
