"""Which defined goals can the runtime actually produce?  Measured, not asserted.

The operator's P0-B, stated exactly: ``goal_capability_map.json`` defines a set of goals, and
``GoalLibrary.discover()`` produces a set of goals, and **they are not the same set**.  Nothing
in the project compared them, so a goal could be defined, documented, have its capability chain
mapped -- and never once exist at runtime.  ``CLEAR_INTEL`` is the worked example: it is listed
in the map, the panel has a row for it, and the engine emits it only when
``world.intel["status"] != "UNKNOWN"``, which never happens because nothing reads the intel page.

So this tool answers three questions with three different kinds of evidence:

  DEFINED       the map's own goal ids -- read from ``knowledge/goals/goal_capability_map.json``
  DISCOVERABLE  the goal ids ``discover()`` can emit **at all** -- measured by feeding it one
                synthetic WorldState per domain and recording what comes out.  This is the
                important one to measure rather than read: a branch can exist in the source and
                still be unreachable because its field is never populated.
  OBSERVED      what it emits for the world as it actually is right now (``goal_state.json``)

Anything in DEFINED but not in DISCOVERABLE has no discovery entry at all -- the operator's
``GOAL_DISCOVERY_MISSING``.  Read-only: it writes nothing and changes nothing.

Usage:
    python tools/goal_discovery_audit.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import GoalLibrary  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402

GOAL_MAP = ROOT / "knowledge/goals/goal_capability_map.json"
GOAL_STATE = ROOT / "learning/goal_state.json"


def defined_goals() -> dict[str, list[str]]:
    """The map's goal ids, with the capabilities each one declares."""
    payload = json.loads(GOAL_MAP.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for name, body in (payload.get("goals") or {}).items():
        caps = [str(c.get("capability") or "") for c in (body.get("capabilities") or [])]
        out[str(name)] = [c for c in caps if c]
    return out


#: One probe per domain the engine *could* read.  Each probe carries the observation the
#: corresponding branch tests for, so a goal that comes out is genuinely reachable and a goal
#: that does not come out from any probe has no branch that can reach it.
PROBES: tuple[tuple[str, WorldState], ...] = (
    ("intel.status", WorldState(page=Page.MAP, intel={"status": "AVAILABLE"})),
    ("stamina.current", WorldState(page=Page.MAP, stamina={"current": 500})),
    ("training", WorldState(page=Page.MAP, training={"queue_available": True})),
    ("research", WorldState(page=Page.MAP, research={"queue_available": True})),
    ("building", WorldState(page=Page.MAP, building={"queue_available": True})),
    # idle_marches is a property, not a field: it comes off the march counter, so the probe
    # sets the inputs the client actually draws rather than a number that does not exist.
    ("idle_marches", WorldState(page=Page.MAP, march_used=2, march_max=3)),
    ("events.minimum_guarantee", WorldState(page=Page.MAP,
                                            events={"minimum_guarantee": {"points_missing": 5}})),
    ("events.bear", WorldState(page=Page.MAP,
                               events={"bear": {"status": "ACTIVE", "remaining_seconds": 60}})),
    ("rewards.verified_claimable",
     WorldState(page=Page.MAP,
                rewards={"verified_claimable": ["PROBE"], "skills": {"PROBE": ["CLAIM_REWARD"]}})),
    # Domains with a WorldState field but (as measured below) no branch in discover().  They are
    # probed on purpose: "the field exists" is exactly the assumption that hid this gap.
    ("daily", WorldState(page=Page.MAP, daily={"status": "AVAILABLE"})),
    ("mail", WorldState(page=Page.MAP, mail={"status": "UNREAD"})),
    ("alliance", WorldState(page=Page.MAP, alliance={"status": "AVAILABLE"})),
    ("exploration", WorldState(page=Page.MAP, exploration={"idle_claimable": True})),
    ("attempts", WorldState(page=Page.MAP, attempts={"arena_free": 3})),
    ("rally", WorldState(page=Page.MAP, rally={"status": "ACTIVE"})),
    ("queues", WorldState(page=Page.MAP, queues={"intel": {"available": True}})),
)


def discoverable_goals() -> dict[str, list[str]]:
    """``goal_id -> the probes that produced it``, by probing the real engine."""
    library = GoalLibrary()
    out: dict[str, list[str]] = {}
    for label, world in PROBES:
        try:
            goals = library.discover(world)
        except Exception as exc:  # noqa: BLE001 - a probe that crashes is a finding, not a stop
            out.setdefault(f"<probe crashed: {type(exc).__name__}>", []).append(label)
            continue
        for goal in goals:
            out.setdefault(goal.goal_id, []).append(label)
    return out


def observed_goals() -> list[str]:
    try:
        payload = json.loads(GOAL_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(g.get("goal_id") or "") for g in (payload.get("goals") or [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit goal discovery coverage")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    defined = defined_goals()
    discoverable = discoverable_goals()
    observed = observed_goals()

    # A defined id is covered when the engine emits that exact id, or -- for the aggregating
    # goals -- one of its dynamic children (CLAIM_FREE_<page> stands for CLAIM_FREE_REWARDS).
    covered = set(discoverable)
    if any(g.startswith("CLAIM_FREE_") for g in discoverable):
        covered.add("CLAIM_FREE_REWARDS")
    missing = sorted(name for name in defined if name not in covered)

    report = {
        "defined_count": len(defined),
        "discoverable_count": len(discoverable),
        "currently_observed_count": len(observed),
        "defined_goals": sorted(defined),
        "discoverable_goals": sorted(discoverable),
        "observed_goals": observed,
        "missing_discovery_goals": missing,
        "discovery_entry": {
            name: {"probes": discoverable.get(name, []),
                   "needs": "WorldState discover rule | periodic observation producer | "
                           "event/deadline producer"}
            for name in sorted(defined)
        },
        "probes_run": [label for label, _ in PROBES],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    print("GOAL DISCOVERY AUDIT")
    print(f"  defined            : {report['defined_count']}")
    print(f"  discoverable       : {report['discoverable_count']}  (measured by probing the engine)")
    print(f"  observed right now : {report['currently_observed_count']}")
    print()
    print("  -- discoverable, with the probe that proves it --")
    for name in sorted(discoverable):
        print(f"     {name:34s} {', '.join(discoverable[name])}")
    print()
    print(f"  -- GOAL_DISCOVERY_MISSING ({len(missing)}) --")
    for name in missing:
        caps = ", ".join(defined[name][:3]) or "(no capability declared)"
        print(f"     {name:34s} needs: {caps}")
    print()
    print("  -- observed right now --")
    for name in observed:
        print(f"     {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
