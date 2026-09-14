"""Drive the GATHER_RESOURCE closure repeatedly and tally it per resource.

The acceptance gate for the gather workflow is not "it worked once": it is
**each of MEAT / WOOD / COAL / IRON completing the full chain at least three
times**, with verifier evidence for every step.  One-off manual runs cannot
establish that, and they leave no machine-readable tally.

This harness runs the real bounded live loop, one closure per invocation, and
records for every run:

* which resource the rotation policy asked for,
* every step's skill and verifier outcome,
* the stop reason,
* whether the *whole* chain verified (so "3 successes" cannot be satisfied by
  a lucky sub-step).

Output: ``evidence/gather_acceptance_<stamp>.json`` plus one capture directory
per run, so each claim is traceable to frames.

Usage
-----
    python tools/run_gather_acceptance.py --runs 4
    python tools/run_gather_acceptance.py --target 3      # stop when every resource has 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.candidate_policy import CandidateAttemptPool
from winter_agent_v2.device import ADBDevice
from winter_agent_v2.goal_library import GoalStateStore
from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.resource_rotation import ResourceRotationStore
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore
from winter_agent_v2.vision import SemanticWorldVision

CHAIN = ("SUBMIT_RESOURCE_SEARCH", "SELECT_RESOURCE", "START_GATHER", "DISPATCH_MARCH")
REQUIRED_FINAL_SKILL = "DISPATCH_MARCH"
RESOURCES = ("MEAT", "WOOD", "COAL", "IRON")


class ForcedRotation:
    """Test double that pins the next resource while delegating real bookkeeping.

    Rotation reaches a resource only when it happens to be the least-dispatched
    one, which is fine for production but useless for acceptance: COAL and IRON
    would never be exercised while MEAT/WOOD still had deficits.  The acceptance
    rule is per-resource ("each resource >= 3 verified closures"), so the harness
    has to name the resource under test.

    ``unavailable`` / ``completed`` still go to the real store, so the run's side
    effects on policy state are genuine.
    """

    def __init__(self, inner: ResourceRotationStore, resource: str) -> None:
        self._inner = inner
        self.resource = resource

    def target(self, stock=None) -> str:  # noqa: ANN001 - mirrors the real signature
        return self.resource

    def unavailable(self, resource: str) -> None:
        self._inner.unavailable(resource)

    def completed(self, resource: str) -> None:
        self._inner.completed(resource)


def build_runtime(config: dict, serial: str | None, capture_dir: Path, planned: str | None = None) -> LiveRuntime:
    device = ADBDevice(Path(config["device"]["adb_path"]), serial or config["device"]["serial"], production=True)
    if serial is None:
        device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    vision = HybridVision(
        template,
        OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
    )
    verifier_skills = set(LiveRuntime.VERIFIED_ATOMIC)
    rotation: object = ResourceRotationStore(ROOT / "learning/resource_rotation.json")
    if planned:
        rotation = ForcedRotation(rotation, planned)
    return LiveRuntime(
        device=device,
        vision=vision,
        semantic_vision=template.semantic,
        capture_dir=capture_dir,
        brain=RuleBrain(
            current_goal="GATHER_RESOURCE",
            reserve_marches=int(config.get("march_policy", {}).get("reserve_for_stamina", 0)),
        ),
        episode_store=EpisodeStore(
            ROOT / "learning/episodes.jsonl",
            limit=int(config.get("retention", {}).get("episode_limit", 10000)),
        ),
        goal_store=GoalStateStore(ROOT / "learning/goal_state.json"),
        candidate_pool=CandidateAttemptPool(
            ROOT / "learning/candidate_attempt_pool.json",
            verifier_skills=verifier_skills,
            recovery_skills=verifier_skills,
            threshold=5,
        ),
        runtime_store=RuntimeSnapshotStore(ROOT / "learning/runtime_snapshot.json"),
        resource_rotation=rotation,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=4, help="maximum closures to attempt")
    parser.add_argument("--target", type=int, default=0, help="stop early when every resource reaches this many")
    parser.add_argument("--max-actions", type=int, default=12)
    parser.add_argument("--serial", default=None)
    parser.add_argument("--settle", type=float, default=None, help="override per-step settle seconds")
    parser.add_argument(
        "--resources",
        default=",".join(RESOURCES),
        help="comma separated resources to exercise, one closure per entry",
    )
    parser.add_argument(
        "--plan",
        default="auto",
        help="'auto' walks the given resources in order; 'rotation' lets the policy choose",
    )
    args = parser.parse_args()

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    if not config.get("production") or config.get("dry_run"):
        raise RuntimeError("GATHER_ACCEPTANCE_REQUIRES_PRODUCTION_TRUE_AND_DRY_RUN_FALSE")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out_path = evidence_dir / f"gather_acceptance_{stamp}.json"

    tally: dict[str, dict] = {name: {"attempts": 0, "full_chain_success": 0} for name in RESOURCES}
    runs: list[dict] = []
    rotation = ResourceRotationStore(ROOT / "learning/resource_rotation.json")

    wanted = [name.strip().upper() for name in args.resources.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in RESOURCES]
    if unknown:
        raise SystemExit(f"unknown resources: {unknown}; known: {list(RESOURCES)}")

    # Build the schedule.  The acceptance rule is per resource, so the default
    # walks every requested resource in turn (least-attempted first) instead of
    # hoping the rotation policy happens to reach the off-screen ones.
    schedule: list[str | None] = []
    if args.plan == "rotation":
        schedule = [None] * args.runs
    else:
        order = sorted(wanted, key=lambda name: RESOURCES.index(name))
        while len(schedule) < args.runs:
            for name in order:
                if len(schedule) >= args.runs:
                    break
                schedule.append(name)

    for index in range(1, args.runs + 1):
        planned_override = schedule[index - 1]
        planned = planned_override or rotation.target({})
        capture_dir = ROOT / "dataset/raw/control_panel/runtime_auto" / f"accept_{stamp}_run{index:02d}"
        print(f"\n=== run {index}/{args.runs}  planned_resource={planned}"
              f"{' (pinned)' if planned_override else ''} ===", flush=True)
        run_record: dict = {"run": index, "planned_resource": planned, "pinned": bool(planned_override),
                            "capture_dir": str(capture_dir)}
        try:
            runtime = build_runtime(config, args.serial, capture_dir, planned=planned_override)
            if args.settle is not None:
                runtime.settle_seconds = args.settle
            result = runtime.run(max_actions=args.max_actions, stop_after_skill=REQUIRED_FINAL_SKILL)
            steps = []
            chain_ok = True
            saw_final = False
            for step in result.steps:
                verification = step.verification
                ok = None if verification is None else bool(verification.ok)
                steps.append({
                    "index": step.index,
                    "skill": step.decision.skill,
                    "executed": None if step.execution is None else bool(step.execution.executed),
                    "error": None if step.execution is None else step.execution.error,
                    "verifier_ok": ok,
                    "verifier_reason": None if verification is None else verification.reason,
                    "before_page": step.before.page.value,
                    "after_page": None if step.after is None else step.after.page.value,
                    "resource_selected": step.before.resource_selected,
                    "marches_after": [] if step.after is None else [m.value for m in step.after.marches],
                    "march_used_after": None if step.after is None else step.after.march_used,
                })
                if step.decision.skill == REQUIRED_FINAL_SKILL:
                    saw_final = True
                    if verification is None or not verification.ok:
                        chain_ok = False
                elif step.decision.skill in CHAIN and verification is not None and not verification.ok:
                    chain_ok = False
            accepted = result.stop_reason == "TARGET_SKILL_VERIFIED"
            full = bool(chain_ok and saw_final and accepted)
            run_record.update({
                "stop_reason": result.stop_reason,
                "steps": steps,
                "full_chain_success": full,
                "accepted_stop": accepted,
            })
            tally[planned]["attempts"] += 1
            tally[planned]["full_chain_success"] += int(full)
            print(f"  stop_reason={result.stop_reason} full_chain_success={full}", flush=True)
            for step in steps:
                print(f"    {step['index']:>2} {step['skill']:<26} verifier={step['verifier_ok']} "
                      f"{step['verifier_reason'] or ''} | {step['before_page']} -> {step['after_page']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad run must not end the sweep
            run_record.update({"stop_reason": f"EXCEPTION:{type(exc).__name__}", "error": str(exc),
                               "full_chain_success": False, "accepted_stop": False})
            tally[planned]["attempts"] += 1
            print(f"  EXCEPTION {type(exc).__name__}: {exc}", flush=True)
        runs.append(run_record)

        # The acceptance criterion is bounded by march slots, not by time.  Each
        # closure occupies one march for hours, so once every slot is gathering
        # there is nothing to dispatch and further runs would only burn budget
        # producing identical no_idle_march results.
        if run_record.get("stop_reason") == "no_idle_march":
            print("\nstopping: all march slots are busy (no_idle_march). "
                  "The remaining closures must wait for a march to return.", flush=True)
            run_record["sweep_aborted"] = "no_idle_march"
            abort_reason = "no_idle_march"
        else:
            abort_reason = None

        payload = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "tools/run_gather_acceptance.py",
            "acceptance_rule": "each resource completes the full chain (SUBMIT -> SELECT -> START_GATHER -> DISPATCH_MARCH) with every verifier passing",
            "planned_runs": args.runs,
            "plan": args.plan,
            "schedule": schedule,
            "resources_requested": wanted,
            "completed_runs": len(runs),
            "aborted": abort_reason,
            "tally": tally,
            "runs": runs,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.target and all(row["full_chain_success"] >= args.target for row in tally.values()):
            print(f"\nacceptance target reached: every resource has {args.target} verified closures", flush=True)
            break
        if abort_reason:
            break

    print("\n=== tally ===")
    for name in RESOURCES:
        row = tally[name]
        print(f"  {name:5s} attempts={row['attempts']} full_chain_success={row['full_chain_success']}")
    print(f"\nwritten {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
