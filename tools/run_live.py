from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The config path is overridable so an experiment can run against a modified
# copy without touching the tracked config that tests read.
CONFIG_PATH = Path(os.environ.get("WINTER_AGENT_CONFIG", ROOT / "config/v2.json"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.executor_router import build_maa_adapter
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.goal_library import GoalStateStore
from winter_agent_v2.candidate_policy import CandidateAttemptPool
from winter_agent_v2.vision import SemanticWorldVision
from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore
from winter_agent_v2.resource_rotation import ResourceRotationStore
from winter_agent_v2.stamina_supply import StaminaSupplyStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded, verifier-gated V2 live loop")
    parser.add_argument("--max-actions", type=int, default=10)
    parser.add_argument("--capture-dir", type=Path, default=ROOT / "dataset/raw/live_runtime")
    parser.add_argument("--goal", choices=["HOME", "GATHER_RESOURCE", "BEAST_HUNT", "INTEL", "MAIL", "EXPLORATION", "DAILY", "ALLIANCE", "RESEARCH", "TRAIN"], default=None)
    parser.add_argument("--stop-after", default=None, help="Stop after this skill passes its verifier")
    parser.add_argument("--serial", default=None, help="Device selected by the control panel")
    parser.add_argument(
        "--no-stamina-check",
        action="store_true",
        help="Skip the once-per-run free-stamina panel check.  Kept as a "
             "diagnostic escape hatch only: it was added on 2026-09-14 for "
             "loops that invoke this runner many times per hour, to suppress "
             "failure_type=STAMINA_SOURCES_NOT_OPEN episodes -- which turned "
             "out to be correct actions recorded as failures by the "
             "one-decision-per-step bug (Scheduler.tick now takes the "
             "runtime's decision).  No caller passes it any more; "
             "config/v2.json asks for the free gift to be claimed.",
    )
    parser.add_argument(
        "--no-escalate",
        action="store_true",
        help="Do not hand a stuck capability to a local WorkBuddy agent at the "
             "end of the run.  The escalation queue is what makes AUTO able to "
             "keep playing while a development agent works; this flag exists so a "
             "diagnostic run can be kept purely observational.",
    )
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not config.get("production") or config.get("dry_run"):
        raise RuntimeError("LIVE_RUNTIME_REQUIRES_PRODUCTION_TRUE_AND_DRY_RUN_FALSE")

    device = ADBDevice(
        Path(config["device"]["adb_path"]),
        args.serial or config["device"]["serial"],
        production=True,
    )
    if args.serial is None:
        device.resolve_connection()
    # MAA is the preferred UI-automation backend (operator directive 2026-09-14).
    # It replaces the observation device too, because frame capture is the hottest
    # call in the loop: 12.1 ms through MuMu's native channel against 246.2 ms for
    # `adb exec-out screencap -p`.  The ADB device is still passed so the router's
    # fallback goes to ADB rather than back to MAA.
    maa_adapter = build_maa_adapter(config, production=True)
    observation_device = device
    if maa_adapter is not None:
        ok, reason = maa_adapter.ensure_ready()
        if ok:
            observation_device = maa_adapter
        else:
            print(f"[executor] MAA requested but unavailable ({reason}); observations stay on ADB")
    else:
        print("[executor] MAA disabled by config (executor.maa.enabled=false)")
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    vision = HybridVision(
        template,
        OCRService(
            ResilientOCRBackend(
                RapidOCRBackend(Path(config["ocr"]["module_path"]))
            )
        ),
    )
    # Safety net: this tree is edited from two places at once, and an external
    # editor has repeatedly flushed a stale buffer over runtime.py.  When that
    # happens a verifier can silently point at the wrong function -- one run
    # recorded OPEN_INTEL as STAMINA_SOURCES_NOT_OPEN, which looks like a real
    # product failure in the episode stream.  Fail loudly instead.
    from winter_agent_v2.verifier import (
        verify_open_intel,
        verify_open_map,
        verify_wood_dispatch_from_march,
    )

    for skill_id, expected in (
        ("OPEN_INTEL", verify_open_intel),
        ("OPEN_MAP", verify_open_map),
        ("DISPATCH_MARCH", verify_wood_dispatch_from_march),
    ):
        actual = LiveRuntime.VERIFIED_ATOMIC.get(skill_id)
        if actual is not expected:
            raise SystemExit(
                f"VERIFIER_MAPPING_CORRUPT: {skill_id} -> "
                f"{getattr(actual, '__name__', None)} (expected {expected.__name__}). "
                "The source tree was rewritten while it was loaded; do not run live."
            )
    verifier_skills = set(LiveRuntime.VERIFIED_ATOMIC)
    started_at = datetime.now(timezone.utc)
    result = LiveRuntime(
        device=observation_device,
        adb_device=device,
        maa_adapter=maa_adapter,
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
            claim_free_stamina=bool(config.get("stamina_policy", {}).get("claim_free_stamina", True)) and not args.no_stamina_check,
        ),
        episode_store=EpisodeStore(ROOT / "learning/episodes.jsonl", limit=int(config.get("retention", {}).get("episode_limit", 10000))),
        goal_store=GoalStateStore(ROOT / "learning/goal_state.json"),
        candidate_pool=CandidateAttemptPool(ROOT / "learning/candidate_attempt_pool.json",
                                            verifier_skills=verifier_skills,
                                            recovery_skills=verifier_skills,
                                            threshold=5),
        runtime_store=RuntimeSnapshotStore(ROOT / "learning/runtime_snapshot.json"),
        resource_rotation=ResourceRotationStore(ROOT / "learning/resource_rotation.json"),
        stamina_supply=StaminaSupplyStore(ROOT / "learning/stamina_supply.json"),
    ).run(max_actions=args.max_actions, stop_after_skill=args.stop_after)
    print(json.dumps(asdict(result), ensure_ascii=False, default=str))

    # The AUTO hook.  It runs *after* the last atomic action has finished and
    # before the exit code is decided, and it never waits for a development
    # agent: it reconciles jobs that already ended, hands off at most the number
    # of decisions the concurrency cap allows, and returns.  A gateway that is
    # down, a slow status read or a broken ledger are all reported on the
    # observation -- AUTO must keep playing either way, so nothing here may raise
    # or change the exit code.
    if not args.no_escalate:
        try:
            from winter_agent_v2.escalation_queue import (
                EscalationQueueAdapter,
                failures_since,
            )

            adapter = EscalationQueueAdapter(root=ROOT)
            observation = adapter.observe_run(
                stop_reason=result.stop_reason,
                failures=failures_since(started_at, root=ROOT),
            )
            print(observation.line)
            for key, why in observation.skipped:
                print(f"[escalation]   skipped {key}: {why}")
            for error in observation.errors:
                print(f"[escalation]   error {error}")
        except Exception as exc:  # noqa: BLE001 - the hook must never break a run
            print(f"[escalation] unavailable ({type(exc).__name__}: {exc}); run unaffected")

    accepted_stops = {"TARGET_SKILL_VERIFIED", "MAX_ACTIONS_REACHED", "no_idle_march", "reserved_march_for_stamina", "verified_beast_target_not_visible", "intel_available_no_claim", "intel_not_available", "intel_expired", "mail_all_clear", "exploration_income_not_ready", "daily_no_claimable_rewards", "daily_state_unknown_or_not_actionable", "alliance_action_not_needed", "research_queue_busy", "training_queue_busy"}
    verified = all(step.verification is None or step.verification.ok for step in result.steps)
    accepted_stops.add("intel_no_untried_pins")
    # Added 2026-09-16 with the panel exit: the DAILY goal now leaves the 任务
    # panel before stopping, so the honest "nothing claimable" end of a run is
    # reported as ``daily_panel_already_read_not_actionable`` instead of
    # ``daily_no_claimable_rewards``.  Same class: all verifiers passed, the
    # client was left somewhere a later run can work from.
    accepted_stops.add("daily_panel_already_read_not_actionable")
    # Added 2026-09-17 with the research route: the goal can now actually reach the
    # 科技研究 page, and today the page offers nothing startable (the node/cost reading
    # does not exist yet).  Every hop's verifier passed and the client is standing on
    # the research page, so this is the honest end of the run -- the same class as
    # ``research_queue_busy``, not a failure.
    accepted_stops.add("research_page_no_startable_node")
    # Added 2026-09-17 with the terminal-page exit: the training and research pages
    # are leaves, so a run that ends there used to park the client and the NEXT run
    # stopped within seconds with ``goal_page_mismatch`` (hit live twice that day).
    # Both goals now Back off the page once before stopping, so their honest end
    # arrives from HOME and is named after the page that was read.  Same class as
    # the panel exit above: every verifier passed, and the client was left where a
    # later run can work from.
    accepted_stops.add("training_page_already_read_not_actionable")
    accepted_stops.add("research_page_already_read_not_actionable")
    return 0 if verified and result.stop_reason in accepted_stops else 2


if __name__ == "__main__":
    raise SystemExit(main())
