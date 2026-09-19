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
CATALOG = ROOT / "knowledge/game/capability_catalog.json"


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


def unmatched_capability_tokens() -> dict[str, list[str]]:
    """Goal-map tokens the catalog does not carry **under that name**.  Deliberately not called
    "missing": measured 2026-09-19, the three vocabularies are unreconciled rather than absent.

      OPEN_ARENA_PAGE / OPEN_BUILDING_PAGE / CLAIM_DAILY_REWARD  -- synonyms of catalog codes
        (OPEN_ARENA, OPEN_BUILDING, CLAIM_REWARD) that the map spells differently
      OPEN_MAIL_PAGE / CLAIM_MAIL_ATTACHMENTS / NAVIGATE_TO_MAP  -- no catalog counterpart at
        all, while ``OPEN_MAIL`` and ``MAIL_CLAIM_REWARDS`` are registered skills that ran live
        today -- so the catalog simply does not carry those rows

    An earlier version of this function reported these as capabilities the catalog "lacks" and a
    reader would have concluded three goals were undevelopable.  That would have been a fabricated
    gap about working software.  What is true is narrower and still worth acting on: goal map
    tokens, catalog codes and skill ids are three vocabularies that have never been reconciled,
    so "is this capability covered" cannot be answered by looking at any one of them.
    """
    try:
        rows = json.loads(CATALOG.read_text(encoding="utf-8")).get("capabilities") or []
    except (OSError, json.JSONDecodeError):
        return {}
    known = {str(r.get("code") or "") for r in rows}
    out: dict[str, list[str]] = {}
    for name, caps in defined_goals().items():
        missing = [c for c in caps if c not in known]
        if missing:
            out[name] = missing
    return out


def catalog_overclaims() -> list[dict[str, str]]:
    """Rows that claim an implementation the skill registry does not have.

    A real inconsistency, and unlike the vocabulary mismatch above it is checkable both ways:
    the catalog says the capability exists, and the only table of executable skills says there is
    no such skill.  ``lifecycle`` is what the planner reads, so an overstated row can make a
    capability look covered when nothing can run it.
    """
    try:
        import winter_agent_v2.skills as skills_module

        rows = json.loads(CATALOG.read_text(encoding="utf-8")).get("capabilities") or []
        registry = skills_module.v2_registry()
    except Exception:  # noqa: BLE001 - an unreadable registry is not a finding
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("implementation_status")) != "EXISTING":
            continue
        claimed = str(row.get("existing_skill") or "")
        if claimed and registry.get(claimed) is None:
            out.append({"code": str(row.get("code") or ""), "existing_skill": claimed,
                        "lifecycle": str(row.get("lifecycle") or "")})
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

    unmatched = unmatched_capability_tokens()
    overstated = catalog_overclaims()

    report = {
        "unmatched_capability_tokens": unmatched,
        "unmatched_count": sum(len(v) for v in unmatched.values()),
        "catalog_overclaims": overstated,
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
    probe_labels = {label for label, _ in PROBES}
    for name in sorted(discoverable):
        probes = discoverable[name]
        if set(probes) == probe_labels:
            # An observation goal: emitted with no reading at all, which is the point --
            # it is how "never looked" stays schedulable instead of invisible.
            print(f"     {name:34s} (every probe: emitted as an observation goal)")
        else:
            print(f"     {name:34s} {', '.join(probes)}")
    print()
    print(f"  -- GOAL_DISCOVERY_MISSING ({len(missing)}) --")
    for name in missing:
        caps = ", ".join(defined[name][:3]) or "(no capability declared)"
        print(f"     {name:34s} needs: {caps}")
    print()
    print("  -- observed right now --")
    for name in observed:
        print(f"     {name}")
    print()
    total = sum(len(v) for v in unmatched.values())
    print(f"  -- vocabulary the map uses that the catalog does not carry by that name ({total}) --")
    print("     (unreconciled names, NOT proven absence -- see the docstring)")
    for name in sorted(unmatched):
        print(f"     {name:34s} {', '.join(unmatched[name])}")
    print()
    print(f"  -- catalog rows claiming EXISTING with no such skill in the registry ({len(overstated)}) --")
    for row in overstated:
        print(f"     {row['code']:26s} says existing_skill={row['existing_skill']!r}, "
              f"lifecycle={row['lifecycle']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
