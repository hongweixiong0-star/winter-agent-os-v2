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

# Operator §B: capture the version this process is *about to load*, before it loads it.
# Everything below this line is the code under test, and the revision is read from git only
# here.  Reading it later -- which is what this file used to do, inside `main()` after fifteen
# runtime imports -- describes the disk at that moment, not the code those imports actually
# pulled in.  A cycle that started before a job finished and read its revision afterwards
# would have stamped the *new* version on an episode produced by the old one.
#
# Safe to call this early because `version_identity` is stdlib-only by design, and
# `winter_agent_v2/__init__.py` is three lines: nothing of the runtime is imported to get here.
from winter_agent_v2.version_identity import (  # noqa: E402
    freeze_process_revision, startup_fence,
)

#: The revision object, kept whole: the episode wants the token plus the parts it was built
#: from, and re-parsing a token back into them would be a second decoder to keep in step.
PROCESS_CODE_REVISION_DETAIL = freeze_process_revision(ROOT)
PROCESS_CODE_REVISION = PROCESS_CODE_REVISION_DETAIL.token

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.executor_router import build_maa_adapter
from winter_agent_v2.brain import RuleBrain
# The route domains are read from the one table that also maps goals onto them, so this
# parser can never accept a domain the scheduler does not use, nor reject one it does.
from winter_agent_v2.goal_library import ROUTE_DOMAINS
from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.goal_library import GoalStateStore
from winter_agent_v2.device_lease import DeviceLease
from winter_agent_v2.candidate_policy import CandidateAttemptPool
from winter_agent_v2.capability_gate import CapabilityGate
# ``repo_revision`` is deliberately NOT imported any more: this process stamps the *frozen*
# revision it captured before its own imports (operator §B), and a live read available here
# would be an invitation to write "what the disk says now" onto an episode again.
from winter_agent_v2.vision import SemanticWorldVision
from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore
from winter_agent_v2.resource_rotation import ResourceRotationStore
from winter_agent_v2.stamina_supply import StaminaSupplyStore


#: Which kind of cycle this process is.  An ordinary AUTO cycle is PRODUCTION; a cycle that
#: exists to examine a version a development job produced is DEVELOPMENT_VALIDATION, and the
#: two must be tellable apart on the episode row -- the operator's §8 rule is that a validation
#: episode may never be read as production reuse.
PRODUCTION_MODE = "PRODUCTION"
VALIDATION_MODE = "DEVELOPMENT_VALIDATION"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded, verifier-gated V2 live loop")
    parser.add_argument("--max-actions", type=int, default=10)
    parser.add_argument("--capture-dir", type=Path, default=ROOT / "dataset/raw/live_runtime")
    parser.add_argument("--goal", choices=list(ROUTE_DOMAINS), default=None)
    parser.add_argument("--stop-after", default=None, help="Stop after this skill passes its verifier")
    parser.add_argument("--serial", default=None, help="Device selected by the control panel")
    # Operator §2: the validation context travels as explicit arguments, not as environment
    # variables.  An environment variable is inherited by whatever the process spawns and is
    # silently lost by whatever forgets to pass it -- and this context decides whether an
    # episode may be credited to a version, so it must be impossible to half-carry it.
    parser.add_argument(
        "--execution-mode", default=PRODUCTION_MODE, choices=(PRODUCTION_MODE, VALIDATION_MODE),
        help="PRODUCTION for an ordinary AUTO cycle; DEVELOPMENT_VALIDATION when this cycle "
             "exists to examine a version a development job produced.",
    )
    parser.add_argument("--trace-id", default="",
                        help="The escalation key this validation belongs to (validation only)")
    parser.add_argument("--job-id", default="", help="The development job id (validation only)")
    parser.add_argument("--capability", default="",
                        help="The capability under examination (validation only)")
    parser.add_argument(
        "--expected-after-version", default="",
        help="The version this cycle must be running for its evidence to count.  Checked "
             "against the frozen process revision *before* the first device action, because "
             "an episode that has to be thrown away afterwards has already touched the game.",
    )
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
    # The tree this process is about to import its code from, read once and stamped on
    # every episode.  It is what lets a later reconciliation separate "this run used
    # the version the job produced" from "AUTO succeeded again while the job was still
    # open" -- the difference between learning a capability and being credited for it.
    #
    # Read from the *frozen* revision (operator §B): re-reading git here would answer "what is
    # on the disk now", which is not "what this process loaded".  Measured 2026-09-18, the
    # fifteen runtime imports above happen at module scope, so the old read happened after the
    # code it was describing had already been imported -- and a job finishing mid-cycle would
    # have its new revision credited to an episode that ran the old one.
    code_revision = PROCESS_CODE_REVISION
    revision = PROCESS_CODE_REVISION_DETAIL
    print(f"[code] revision {code_revision or 'unknown'}", flush=True)

    # Startup version fence (operator, 2026-09-18).  R1 was frozen before this process imported
    # anything; R2 is the version-relevant tree *now*, after the imports and the verifier
    # mapping assertion above.  Between them another agent may have committed, a reload may
    # have swapped files, or a checkout may have run -- and then this process is executing a
    # mixture whose episodes would be evidence for no particular version.
    #
    # Refusing here costs one cycle.  Not refusing would write episodes that a later reader
    # (activation, version binding, production reuse) would attribute to whichever version
    # they assumed -- which is exactly the class of false credit this whole chain exists to
    # prevent.  No device action happens, so nothing is left half-done; the next cycle after a
    # safe reload starts from a tree that agrees with the frozen revision again.
    fence_ok, frozen_revision, current_revision = startup_fence(ROOT)
    if not fence_ok:
        print(
            f"STARTUP_VERSION_CHANGED: 加载时冻结 R1={frozen_revision.token or 'unknown'}，"
            f"启动前复测 R2={current_revision.token or 'unknown'}；"
            "本轮不执行真机动作，不产生任何可用于 VERSION_ACTIVE / LIVE_VERIFIED 的 Episode，"
            "等安全 reload 后由下一轮重新开始。",
            flush=True,
        )
        return 3

    # ---------------------------------------------------------------- §3 version binding
    # The most important gate in the chain, and it is here on purpose: *before* LiveRuntime is
    # constructed, which is the first thing that can touch the device.
    #
    # A validation cycle exists to answer one question -- does this version make the capability
    # work.  If the version it is running is not the version under examination, then every
    # action it takes proves something about the wrong code, and the only safe amount of device
    # activity is none.  Checking *after* the episode exists would mean the game had already
    # been clicked, and the options would be to discard a real episode or to credit it to the
    # wrong version -- which is the false credit this whole chain exists to prevent.
    #
    # Not a refusal to recover from mid-run: nothing has happened yet, so this costs one cycle
    # and leaves no half-done work.
    if args.expected_after_version and args.expected_after_version != code_revision:
        print(
            "VALIDATION_VERSION_MISMATCH: "
            f"trace_id={args.trace_id or 'unknown'} job_id={args.job_id or 'unknown'} "
            f"capability={args.capability or 'unknown'} "
            f"expected_version={args.expected_after_version} actual_version={code_revision or 'unknown'} "
            "—— 进程加载的版本不是被验证的版本；本轮不执行任何真机动作，不产生可记功的 "
            "Validation Episode，不写 LIVE_TRIED / LIVE_VERIFIED；等待正确版本重新激活后再验证。",
            flush=True,
        )
        return 4
    # Which account this run's episodes belong to, read once from the one role artifact.
    # Deliberately allowed to be empty: an episode with no role is an *unscoped* episode,
    # and that fact must stay visible.  Filling it from config or a default is what let the
    # window print a role nobody had observed.
    from winter_agent_v2.state_truth import TruthAudit

    role = TruthAudit(ROOT).report().by_name("current_role")
    role_id = role.role_id if role is not None else ""
    role_scope = role.status if role is not None else ""
    print(f"[role] {role_id or 'unscoped'} ({role_scope or 'UNKNOWN'})", flush=True)
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
        # Which goal paths must step aside, projected from this project's escalation
        # ledger and episode stream.  Read once per run because a run is one cycle of
        # the scheduler: a deferral that appears mid-run would change the route under
        # the step it is about to take.
        capability_gate=CapabilityGate.load(ROOT),
        code_revision=code_revision,
        role_id=role_id,
        role_scope=role_scope,
        # §2: the context that decides what this cycle's evidence may be used for.  Passed
        # explicitly and stamped on every episode, so a reader never has to infer from the
        # caller's intent whether a step was production play or an examination.
        execution_mode=args.execution_mode,
        trace_id=args.trace_id,
        job_id=args.job_id,
        capability=args.capability,
        expected_after_version=args.expected_after_version,
        # The single-UI-owner lock.  Gameplay holds the device by default; a development
        # validation takes it, and this run yields at the next atomic boundary rather
        # than being interrupted mid-transaction (operator §8/§19).
        device_lease=DeviceLease(ROOT),
    ).run(max_actions=args.max_actions, stop_after_skill=args.stop_after)
    for deferral in result.deferrals:
        print(f"[schedule] deferred {deferral.get('goal_id')} -> {deferral.get('state')}"
              f" on {deferral.get('capability') or '(unnamed path)'}: {deferral.get('reason')}")
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
                # A goal the scheduler refused to re-enter is a wall the run reached
                # without failing a step, so it would otherwise leave no trace at all
                # for the queue to act on.
                deferrals=result.deferrals,
            )
            print(observation.line)
            for key in observation.released:
                print(f"[escalation]   released {key}: the device proved it without a job")
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
