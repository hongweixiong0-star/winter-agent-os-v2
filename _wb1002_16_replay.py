"""Before/after on the real refused step: which clause blocked it, and what is left.

Reads the recorded row for the one DISPATCH_MARCH attempt in the ledger, replays the formation
clause exactly as the old code computed it and exactly as the new code computes it, and prints what
each says about the same recorded formation.

    .venv/Scripts/python.exe _wb1002_16_replay.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.hero_portraits import evaluate_gather_formation  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.verifier import verify_wood_dispatch_from_march  # noqa: E402

WINDOW = 4_000_000


def the_attempt():
    path = ROOT / "learning" / "episodes.jsonl"
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - WINDOW))
        for line in stream.read().decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("skill") == "DISPATCH_MARCH":
                return row
    return None


def rebuild(state: dict, keys) -> WorldState:
    fields = {key: state[key] for key in keys if key in state}
    if isinstance(fields.get("page"), str):
        page = fields["page"]
        fields["page"] = Page(page) if page in set(Page) else Page.UNKNOWN
    return WorldState(**fields)


def main() -> int:
    row = the_attempt()
    if row is None:
        print("no DISPATCH_MARCH row in the ledger window")
        return 1
    before_state = row.get("state_before") or {}
    after_state = row.get("state_after") or {}
    print(f"the attempt: {row.get('recorded_at')}  {row.get('result')}  {row.get('failure_type')}")
    print(f"  goal={row.get('goal_id')}  role={row.get('role_id')}  rev={str(row.get('repo_revision'))[:7]}")
    print()

    formation = ((before_state.get("hero_troop") or {}).get("gather_formation")) or {}
    plan = str(before_state.get("resource_target") or "")
    print(f"  plan (what the run meant to send) : {plan!r}")
    print(f"  formation.resource_type as recorded: {formation.get('resource_type')!r}")
    print(f"  formation.resource_observed (new)  : {formation.get('resource_observed')!r}")
    print(f"  formation.resource_source (new)    : {formation.get('resource_source')!r}")
    print()

    # --- the old clause, verbatim ---
    old_clause = (
        formation.get("status") == "OBSERVED"
        and formation.get("page") == "PAGE_FORMATION"
        and formation.get("role_scope") in {"LIVE_OBSERVED", "FRESH_RUNTIME"}
        and bool(str(formation.get("role_id") or "").strip())
        and bool(str(formation.get("source_frame") or "").strip())
        and bool(str(before_state.get("timestamp") or ""))
        and str(formation.get("observed_at") or "") == str(before_state.get("timestamp") or "")
        and str(formation.get("resource_type") or "").upper() == plan.upper()
    )
    print(f"  old role_scoped_current (8 clauses) : {old_clause}"
          f"   <- false only because resource_type {formation.get('resource_type')!r} != {plan!r}")
    for label, value in (
        ("status == OBSERVED", formation.get("status") == "OBSERVED"),
        ("page == PAGE_FORMATION", formation.get("page") == "PAGE_FORMATION"),
        ("role_scope live", formation.get("role_scope") in {"LIVE_OBSERVED", "FRESH_RUNTIME"}),
        ("role_id present", bool(str(formation.get("role_id") or "").strip())),
        ("source_frame present", bool(str(formation.get("source_frame") or "").strip())),
        ("timestamp present", bool(str(before_state.get("timestamp") or ""))),
        ("observed_at == before.timestamp",
         str(formation.get("observed_at") or "") == str(before_state.get("timestamp") or "")),
        ("resource_type == plan",
         str(formation.get("resource_type") or "").upper() == plan.upper()),
    ):
        print(f"      {label:<30} {value}")
    print()

    # --- what the new runtime hands the verifier ---
    runtime = object.__new__(LiveRuntime)
    keys = {field for field in WorldState.__dataclass_fields__}
    before = rebuild(before_state, keys)
    stamped = runtime._stamp_gather_formation_resource(before, plan)
    stamped_formation = (stamped.hero_troop or {}).get("gather_formation") or {}
    print(f"  after the new stamp: resource_type={stamped_formation.get('resource_type')!r} "
          f"resource_source={stamped_formation.get('resource_source')!r} "
          f"resource_observed={stamped_formation.get('resource_observed')!r}")
    policy = evaluate_gather_formation(plan, stamped_formation)
    print(f"  policy({plan!r}) -> {policy.get('status')} remove_slots={policy.get('remove_slots')}")
    print()

    print("  new verifier on the SAME recorded formation:")
    result = verify_wood_dispatch_from_march(stamped, rebuild(after_state, keys))
    for key, value in sorted((result.evidence or {}).items()):
        print(f"      {key:<42} {value}")
    print(f"      verdict                                  ok={result.ok} reason={result.reason}")
    print()

    # The decisive part: the tap that was recorded as a failure had in fact been accepted.
    from winter_agent_v2.models import MarchState
    print("  did the refused tap actually dispatch?  compare the two states the row carries:")
    for label, state in (("before", before_state), ("after ", after_state)):
        marches = [str(getattr(m, "value", m)) for m in (state.get("marches") or ())]
        print(f"      {label}: page={state.get('page')}  marches={marches}  "
              f"march_used={state.get('march_used')}")
    before_had_none = not (before_state.get("marches") or ())
    after_has_march = any(str(getattr(m, "value", m)) == MarchState.MARCHING.value
                          for m in (after_state.get("marches") or ()))
    print()
    if before_had_none and after_has_march:
        print("      => a march began between the two frames, so the tap WAS delivered and the game")
        print("         accepted it.  The row says FAILURE anyway.  This was not a blocked dispatch:")
        print("         it was a dispatched march recorded as a failure, after which the run walked")
        print("         the whole search/gather/clear flow again (steps 17-20) toward a second one.")
    else:
        print("      => no march began, so the tap did not dispatch and the refusal cost only time.")
    print()
    print("  Caveat, recorded rather than glossed: the after-side clause accepts *any* march, not")
    print("  provably one this tap created.  That is a separate weakness of this verifier and is not")
    print("  fixed here -- what is fixed is the formation clause that refused a ready formation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
