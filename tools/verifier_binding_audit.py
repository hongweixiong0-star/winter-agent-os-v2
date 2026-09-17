"""Read-only audit: which capabilities are one piece of the puzzle away from live?

Why this exists (2026-09-17)
----------------------------
The operator's standing order is to raise ``LIVE_VERIFIED`` fast.  Trying
capabilities one at a time is slow and silently repeats itself: the same gap --
"the brain dispatches it, the vision target exists, the verifier was written, and
it is still never dispatched" -- had been re-found by hand at least three times
(``ALLIANCE_GIFTS``, ``CHECK_MARCH``, the reward-popup source work).

So this lays the puzzle out.  For every registered skill it answers five questions
and prints the skills missing exactly one piece:

    1. is a verifier bound?           LiveRuntime.VERIFIED_ATOMIC
    2. does a brain route exist?      Decided by brain.py
    3. is its action target observed? Appears in vision.py
    4. has it ever succeeded live?    Episodes carrying a recorded_at
    5. can the runtime call what is bound?

Question 5 is the one that hides.  ``LiveRuntime.Verifier`` is
``Callable[[WorldState, WorldState], VerificationResult]`` and the step loop calls
``VERIFIED_ATOMIC[skill](before, after)``, so the runtime cannot pass a decision's
identity down.  Verifiers that want one were written to three shapes the runtime
does not have, and a mismatched function binds without raising anything -- so
"cannot be bound" looks exactly like "was never written".

    PARAMETER  e.g. verify_building_upgrade(before, after, building_id)
    FRAME      e.g. verify_alliance_gifts_claim(before, reward, after)
    STATE      e.g. verify_research_queue(state)

Three of the PARAMETER verifiers (BUILDING_UPGRADE, TRAIN_TROOPS, RESEARCH) are
bound anyway, through a lambda in ``runtime.py`` that injects the value read from
the **before** frame.  That is not automatically wrong -- ``verify_training_started``
compares the injected ``troop_type`` against the **after** state, so it stays a real
cross-check -- but it does decide, per verifier, whether the injected argument is
still doing work or has become a tautology.  This tool reports the injected
expression so that judgement is made from the source, not from the parameter list.

Read-only: it never edits the registry, the verifier file or the episodes.

Usage
-----
    python tools/verifier_binding_audit.py
    python tools/verifier_binding_audit.py --unbound-verifiers
    python tools/verifier_binding_audit.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"

# Parameter names that mean "an intermediate frame", not "a skill argument".
# A name list rather than a positional rule: verify_mail_tab_selected puts its
# parameter first, so position alone cannot classify these.
_FRAME_PARAM_NAMES = {
    "result", "reward", "reward_frame", "feedback", "mid", "observed",
    "alliance_start", "contribution_results", "daily_claimable",
}


@dataclass(frozen=True)
class VerifierShape:
    name: str
    params: tuple[str, ...]

    @property
    def kind(self) -> str:
        if len(self.params) == 2:
            return "TWO_FRAME"
        if len(self.params) == 1:
            return "STATE"
        if len(self.params) >= 3 and any(p in _FRAME_PARAM_NAMES for p in self.params[1:]):
            return "FRAME"
        return "PARAMETER"

    @property
    def callable_by_runtime(self) -> bool:
        return self.kind == "TWO_FRAME"


@dataclass(frozen=True)
class AdapterBinding:
    """A skill bound through ``lambda before, after: verify_x(before, after, EXPR)``."""

    skill: str
    verifier: str
    injected: str

    @property
    def reads_before_frame(self) -> bool:
        return self.injected.startswith("before.") or "before." in self.injected


@dataclass(frozen=True)
class SkillRow:
    skill: str
    state: str
    target: str | None
    verifier: str | None
    verifier_kind: str | None
    binding_kind: str | None          # DIRECT | ADAPTER | None
    injected: str | None
    brain_route: bool
    vision_target: bool
    live_attempts: int
    live_success: int

    @property
    def dispatchable(self) -> bool:
        """Bound at all -- the runtime only needs a 2-arg callable, adapters count."""
        return self.binding_kind is not None

    @property
    def missing(self) -> tuple[str, ...]:
        gaps = []
        if not self.dispatchable:
            if self.verifier and self.verifier_kind:
                gaps.append(f"verifier_shape:{self.verifier_kind}")
            else:
                gaps.append("verifier_binding")
        if not self.brain_route:
            gaps.append("brain_route")
        if self.target and not self.vision_target:
            gaps.append("vision_target")
        return tuple(gaps)

    @property
    def ready_but_unproven(self) -> bool:
        return self.dispatchable and self.brain_route and self.vision_target


def verifier_shapes() -> dict[str, VerifierShape]:
    """``{name: shape}`` parsed straight out of verifier.py."""
    from winter_agent_v2 import verifier as verifier_mod

    source = Path(verifier_mod.__file__).read_text(encoding="utf-8")
    out: dict[str, VerifierShape] = {}
    for match in re.finditer(r"^def (verify_\w+)\(([^)]*)\)", source, re.M):
        params = tuple(
            p.split(":")[0].strip()
            for p in match.group(2).split(",")
            if p.strip() and p.strip() != "..."
        )
        out[match.group(1)] = VerifierShape(match.group(1), params)
    return out


_ADAPTER_RE = re.compile(
    r'"(\w+)":\s*lambda\s+before,\s*after:\s*(verify_\w+)\(before,\s*after,\s*(.+?)\),\s*$',
    re.M,
)


def adapter_bindings() -> dict[str, AdapterBinding]:
    """Lambda adapters in ``runtime.py``, with the argument they inject."""
    from winter_agent_v2 import runtime as runtime_mod

    source = Path(runtime_mod.__file__).read_text(encoding="utf-8")
    out: dict[str, AdapterBinding] = {}
    for match in _ADAPTER_RE.finditer(source):
        skill, verifier, injected = match.group(1), match.group(2), match.group(3).strip()
        out[skill] = AdapterBinding(skill=skill, verifier=verifier, injected=injected)
    return out


def live_history() -> dict[str, tuple[int, int]]:
    """``{skill: (attempts, successes)}`` over production rows only.

    A row with no ``recorded_at`` is an imported/legacy line: no timestamp, no
    episode id, no verifier result.  The project counts only dated rows, and
    counting the others once manufactured four phantom successes for a skill that
    has never actually run (ALLIANCE_TECH_CONTRIBUTE).
    """
    counts: dict[str, list[int]] = {}
    if not EPISODES.is_file():
        return {}
    for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("recorded_at"):
            continue
        skill = row.get("skill")
        if not skill:
            continue
        slot = counts.setdefault(str(skill), [0, 0])
        slot[0] += 1
        if str(row.get("result", "")).upper() == "SUCCESS":
            slot[1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def collect() -> tuple[list[SkillRow], dict[str, VerifierShape], dict[str, AdapterBinding]]:
    from winter_agent_v2 import brain as brain_mod
    from winter_agent_v2 import vision as vision_mod
    from winter_agent_v2.runtime import LiveRuntime
    from winter_agent_v2.skills import v2_registry

    brain_src = Path(brain_mod.__file__).read_text(encoding="utf-8")
    vision_src = Path(vision_mod.__file__).read_text(encoding="utf-8")
    shapes = verifier_shapes()
    adapters = adapter_bindings()
    history = live_history()
    table = LiveRuntime.VERIFIED_ATOMIC

    rows = []
    for skill in v2_registry().all():
        sid = skill.id
        target = getattr(getattr(skill, "action", None), "target", None)
        bound = table.get(sid)
        adapter = adapters.get(sid)
        name = getattr(bound, "__name__", None)
        if adapter is not None:
            name = adapter.verifier
            binding_kind = "ADAPTER"
        elif bound is not None:
            binding_kind = "DIRECT"
        else:
            binding_kind = None
        attempts, successes = history.get(sid, (0, 0))
        rows.append(SkillRow(
            skill=sid,
            state=str(getattr(skill.state, "value", skill.state)),
            target=target,
            verifier=name if name and name != "<lambda>" else None,
            verifier_kind=shapes[name].kind if name in shapes else None,
            binding_kind=binding_kind,
            injected=adapter.injected if adapter else None,
            brain_route=f'"{sid}"' in brain_src,
            vision_target=bool(target) and f'"{target}"' in vision_src,
            live_attempts=attempts,
            live_success=successes,
        ))
    return rows, shapes, adapters


def unbound_families(
    rows: list[SkillRow],
    shapes: dict[str, VerifierShape],
    adapters: dict[str, AdapterBinding],
) -> dict[str, list[str]]:
    """Verifiers no skill can reach, grouped by the reason."""
    reached = {r.verifier for r in rows if r.verifier}
    adapted = {a.verifier for a in adapters.values()}
    families: dict[str, list[str]] = {"FRAME": [], "PARAMETER": [], "STATE": []}
    for name, shape in sorted(shapes.items()):
        if name in reached or name in adapted or shape.callable_by_runtime:
            continue
        if shape.kind in families:
            families[shape.kind].append(name)
    return {k: v for k, v in families.items() if v}


def _print(title: str, rows: list[SkillRow], limit: int = 30) -> None:
    print(f"== {title} ({len(rows)}) ==")
    for r in rows[:limit]:
        gaps = ",".join(r.missing) or "-"
        print(f"  {r.skill:40s} state={r.state:10s} gaps={gaps:22s} "
              f"target={str(r.target)[:26]:26s} live={r.live_success}/{r.live_attempts}")
    if len(rows) > limit:
        print(f"  ... and {len(rows) - limit} more")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verifier binding / dispatch readiness audit")
    parser.add_argument("--unbound-verifiers", action="store_true",
                        help="print the verifiers no skill can reach, plus the adapters in use")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows, shapes, adapters = collect()
    one_piece = [r for r in rows if len(r.missing) == 1]
    ready = [r for r in rows if r.ready_but_unproven and r.live_success == 0]
    families = unbound_families(rows, shapes, adapters)

    if args.json:
        print(json.dumps({
            "skills": len(rows),
            "verified_atomic_entries": sum(1 for r in rows if r.dispatchable),
            "ready_but_unproven": [r.skill for r in ready],
            "missing_one_piece": {r.skill: list(r.missing) for r in one_piece},
            "unreachable_verifiers": families,
            "lambda_adapters": {
                s: {"verifier": a.verifier, "injected": a.injected,
                    "reads_before_frame": a.reads_before_frame}
                for s, a in sorted(adapters.items())
            },
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"registry: {len(rows)} skills | "
          f"dispatchable (any 2-arg binding): {sum(1 for r in rows if r.dispatchable)}")
    print()

    _print("A. every piece present, never succeeded live (fastest LIVE_VERIFIED)", ready)
    _print("B. exactly one piece missing", one_piece)

    if args.unbound_verifiers:
        print("== verifiers no skill can reach ==")
        print("   The runtime calls VERIFIED_ATOMIC[skill](before, after), so it cannot")
        print("   hand a decision's identity to a verifier.  These were written to a shape")
        print("   the runtime does not have, so the skill they serve is never dispatched.")
        print("   The fixes are NOT the same:")
        print()
        for kind, why in (
            ("PARAMETER", "the extra argument is a SKILL PARAMETER (which building / which\n"
                          "              research / which troop / which target) the runtime must\n"
                          "              pass down -- not a second screenshot."),
            ("FRAME", "the extra argument is an intermediate FRAME: the feedback banner\n"
                      "              between the tap and the settled page, which the step loop\n"
                      "              never captures."),
            ("STATE", "a single-argument observation assertion; the runtime has no shape\n"
                      "              for it either."),
        ):
            names = families.get(kind, [])
            if not names:
                continue
            print(f"  [{kind}] {len(names)}  -- {why}")
            for n in names:
                print(f"      {n:46s} {shapes[n].params}")
            print()

        if adapters:
            print(f"== lambda adapters already in use ({len(adapters)}) ==")
            print("   These ARE dispatchable, because the adapter has two parameters.  What")
            print("   they inject decides whether the verifier still proves what it says:")
            print("   an expression read from the *before* frame cannot also be checked")
            print("   against that same frame, but it is still a real cross-check wherever")
            print("   the verifier compares it with the *after* state.")
            for skill, adapter in sorted(adapters.items()):
                source = "BEFORE frame" if adapter.reads_before_frame else "constant"
                print(f"  {skill:22s} -> {adapter.verifier:30s} injects {adapter.injected}  [{source}]")
            print()

    print(f"verdict: {len(ready)} skill(s) need only a live success; "
          f"{len(one_piece)} need exactly one piece; "
          f"{sum(len(v) for v in families.values())} written verifier(s) are unreachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
