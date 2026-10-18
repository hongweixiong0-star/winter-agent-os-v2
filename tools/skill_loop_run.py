"""Run one registry skill against the live client and let its verifier judge the result.

    python tools/skill_loop_run.py --skill DISMISS_GET_MORE_STAMINA --purpose "close the stamina offer"
    python tools/skill_loop_run.py --skill DISMISS_GET_MORE_STAMINA --purpose ... --dry-run

Why this exists
---------------
``tools/explore_step.py`` can issue one arbitrary action, but it is an *exploration* tool: it
takes a coordinate or a printed label, it has no idea what a Skill is, and by design it cannot
record a verifier verdict.  ``tools/control_panel.py`` runs the whole AUTO loop, which is far too
much for "did the skill I just generated actually work".

That left a gap with a very specific shape: a generated skill could be loaded (the registry is
code) and could be scheduled (the brain names it), but nobody could run **just that skill once**
and get an episode that says whether its verifier passed.  Without that, the loop's last arrow --
"verifier confirms, record episode, promote" -- had no implementation at all.

What it refuses
---------------
* a skill the registry does not hold, or one with no ``VERIFIED_ATOMIC`` binding: an unverified
  action is exactly what the project forbids, so this is a refusal and not a warning;
* a frame whose state does not satisfy ``skill.ready``: the precondition is the skill's own
  contract, and running outside it would produce a failure that teaches nothing;
* Auto mode (via ``explore_step._require_manual_mode``): exploration and execution do not share
  a device, and the project already owns that check.

What it writes
--------------
One row to ``learning/episodes.jsonl`` in the runtime's own schema (the fields the ledger's
consumers actually read), and one row to ``learning/skill_loop/outcomes.jsonl`` describing the
loop's decision.  Replay is not offered here at all: this tool only runs live, so a row it writes
can never be mistaken for a simulation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from winter_agent_v2 import skill_loop  # noqa: E402
from winter_agent_v2.models import WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import p0_registry, v2_registry  # noqa: E402

EPISODE_LEDGER = ROOT / "learning" / "episodes.jsonl"


def _registry_skill(skill_id: str):
    for registry in (p0_registry(), v2_registry()):
        skill = registry.get(skill_id)
        if skill is not None:
            return skill
    return None


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--purpose", required=True, help="what this run is trying to prove")
    parser.add_argument("--config", default=str(ROOT / "config" / "v2.json"))
    parser.add_argument("--settle", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="read the live frame and decide, issue nothing")
    args = parser.parse_args(argv)

    skill = _registry_skill(args.skill)
    if skill is None:
        print(f"REFUSED: {args.skill} is not in the registry")
        return 3
    verifier = LiveRuntime.VERIFIED_ATOMIC.get(skill.id)
    if verifier is None:
        print(f"REFUSED: {skill.id} has no verifier binding; an unverified action may not run")
        return 3

    import explore_step as ex  # noqa: PLC0415 - tools/ on sys.path above

    ex._require_manual_mode()  # noqa: SLF001 - the project's one mode gate
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.executor import Executor
    from winter_agent_v2.executor_router import build_maa_adapter

    config = ex._load_config(Path(args.config))  # noqa: SLF001
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = ex.FRAME_ROOT / f"skill_{run_id}"
    out.mkdir(parents=True, exist_ok=True)

    adapter = build_maa_adapter(config, production=True)
    if adapter is None or not adapter.available():
        print(f"MAA 不可用：{adapter.unavailable_reason if adapter else 'disabled'}")
        return 4
    vision = ex._vision(ex._ocr(config), config)  # noqa: SLF001
    lease = DeviceLease(root=ROOT)
    held, why = lease.acquire(owner="SKILL_LOOP_RUN", capability_id=skill.id,
                              reason=args.purpose)
    if not held:
        print(f"REFUSED: device lease not acquired ({why or 'held elsewhere'})")
        return 5

    episode_id = _now_id()
    before_path, after_path = out / "before.png", out / "after.png"
    try:
        adapter.screenshot(before_path)
        before: WorldState = vision.observe(before_path)
        if not skill.ready(before):
            print(f"REFUSED: precondition not met (page={before.page.value} popup={before.popup})")
            return 6
        if args.dry_run:
            print(json.dumps({
                "skill": skill.id, "action": {"kind": skill.action.kind,
                                              "target": skill.action.target},
                "page": before.page.value, "popup": before.popup,
                "verifier": getattr(verifier, "__name__", "?"),
                "would_execute": True, "mode": "DRY_RUN",
            }, ensure_ascii=False, indent=2))
            return 0

        executor = Executor(production=True, dry_run=False, device=adapter, backend="MAA")
        started = time.monotonic()
        result = executor.execute(skill.action)
        time.sleep(max(0.0, args.settle))
        adapter.screenshot(after_path)
        after: WorldState = vision.observe(after_path)
        verification = verifier(before, after)
        duration = round(time.monotonic() - started, 2)
    finally:
        try:
            lease.release(result="DONE")
        except Exception:  # noqa: BLE001 - a failed release must not hide the verdict
            pass

    episode = {
        "skill": skill.id,
        "state_before": {"page": before.page.value, "popup": before.popup},
        "action": {"kind": skill.action.kind, "target": skill.action.target},
        "state_after": {"page": after.page.value, "popup": after.popup},
        "result": "SUCCESS" if verification.ok else "FAILURE",
        "failure_type": None if verification.ok else verification.reason,
        "duration": duration,
        "mode": "PRODUCTION",
        "episode_id": episode_id,
        "goal_id": "",
        "step_id": "",
        "before_screenshot": str(before_path),
        "after_screenshot": str(after_path),
        "verifier_ok": bool(verification.ok),
        "verifier_evidence": verification.evidence,
        "executor_backend": result.backend,
        "execution_mode": "PRODUCTION",
        "decision_reason": "skill_loop_run",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    EPISODE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with EPISODE_LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(episode, ensure_ascii=False) + "\n")
    skill_loop.record_outcome(
        skill.id,
        verdict="VERIFIED" if verification.ok else "FAILED",
        evidence={"episode_id": episode_id, "verifier": getattr(verifier, "__name__", "?"),
                  "evidence": verification.evidence, "frames": [str(before_path), str(after_path)]},
        note=args.purpose,
    )
    print(json.dumps({k: episode[k] for k in
                      ("skill", "result", "failure_type", "verifier_ok",
                       "verifier_evidence", "executor_backend", "duration", "episode_id")},
                     ensure_ascii=False, indent=2))
    verdict = skill_loop.promotion_verdict(skill.id, skill_loop.read_new_episodes(
        {"episodes_offset": 0})[0])
    print(json.dumps({"promotion": verdict}, ensure_ascii=False, indent=2))
    return 0 if verification.ok else 7


if __name__ == "__main__":
    raise SystemExit(main())
