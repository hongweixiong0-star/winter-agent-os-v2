"""Report which pieces of the stamina/recall wiring are present and executable.

The project files are edited from two places at once, and an external editor has
repeatedly flushed a stale buffer over the tree, silently dropping changes that
a text grep still "finds" elsewhere.  This checks the *executable* surface
instead: imported objects, real decisions on real states, and the config the
runtime reads.
"""

from __future__ import annotations

import ast
import builtins
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PKG = ROOT / "winter_agent_v2"

problems: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(("OK   " if condition else "MISS "), label, detail)
    if not condition:
        problems.append(label)


# ---------------------------------------------------------------------------
# Static "does this call site resolve to a definition anymore" analysis.
#
# Motivation (failure 0aw, 2026-09-15): HybridVision.observe called
# `self._next_supply_seconds(...)`, a method that existed on no class.  Because
# the call is syntactically valid Python, every gate passed -- import, pytest,
# and this file -- and the AttributeError would only have fired at runtime on
# the GET_MORE_STAMINA panel, which is the only path to the free stamina gift.
#
# So "a method is called" must not be conflated with "the method exists".  This
# walks the AST of every module in the package and flags call sites that cannot
# resolve to a definition.  It is deliberately conservative: an unresolvable
# name is reported, never silently accepted, but the name-only fallback for
# cross-module bases means we prefer a false alarm over a false negative.
# ---------------------------------------------------------------------------

_COMMON_DUNDERS = frozenset(
    {
        "__init__",
        "__enter__",
        "__exit__",
        "__repr__",
        "__str__",
        "__eq__",
        "__ne__",
        "__hash__",
        "__len__",
        "__iter__",
        "__next__",
        "__contains__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__call__",
        "__bool__",
        "__format__",
        "__lt__",
        "__le__",
        "__gt__",
        "__ge__",
    }
)


def _parse_package(pkg: Path | None = None) -> dict[str, ast.Module]:
    # ``pkg`` is resolved at call time, never captured: the tests point ``PKG``
    # at a scratch copy and must keep working without touching this default.
    root = PKG if pkg is None else pkg
    trees: dict[str, ast.Module] = {}
    for path in sorted(root.glob("*.py")):
        try:
            trees[path.stem] = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - surfaced as a miss
            print("SYNTAX_ERROR", path.name, exc)
            problems.append(f"parse:{path.name}")
    return trees


def _definitions(pkg: Path | None = None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (class-name -> method-names, module -> module-level function names)."""
    trees = _parse_package(pkg)
    class_methods: dict[str, set[str]] = {}
    module_funcs: dict[str, set[str]] = {}
    for mod, tree in trees.items():
        funcs = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        module_funcs[mod] = funcs
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = {
                    item.name
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                class_methods.setdefault(node.name, set()).update(methods)
    return class_methods, module_funcs


def _base_names(cls: ast.ClassDef) -> list[str]:
    out: list[str] = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            out.append(base.id)
        elif isinstance(base, ast.Attribute):
            out.append(base.attr)
    return out


def dangling_self_calls(pkg: Path | None = None) -> list[tuple[str, str]]:
    """Every `self.foo(...)` whose `foo` resolves to no method on the class.

    ``pkg`` selects the directory to sweep and defaults to the package, so the
    caller can also point it at ``tools/`` or ``tests/`` -- see main().

    Deliberately scoped so the signal stays trustworthy:
      * only attributes starting with `_` are considered -- that is the private
        helper convention this package uses, and it cuts the entire false-positive
        population (injected callables, collaborators, dataclass field defaults)
        which are never private helpers;
      * the name must exist nowhere in the package as a method, so a helper
        reached via a base class in another module is not reported;
      * methods reached through a locally-bound `self` parameter are still
        covered because their callee is a `self.` attribute of some class.
    """
    trees = _parse_package(pkg)
    class_methods, _ = _definitions(pkg)
    package_wide = set()
    for methods in class_methods.values():
        package_wide |= methods

    found: list[tuple[str, str]] = []
    for mod, tree in trees.items():
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            available = set()
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    available.add(item.name)
            # simple assignment targets in the class body (e.g. self.x = fn in
            # a factory) and base-class names resolved by name across modules
            for item in ast.walk(cls):
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Attribute):
                            available.add(target.attr)
                        elif isinstance(target, ast.Name):
                            available.add(target.id)
                elif isinstance(item, (ast.AnnAssign, ast.AugAssign)):
                    target = item.target
                    if isinstance(target, ast.Attribute):
                        available.add(target.attr)
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in item.args.args:
                        available.add(arg.arg)
            for base_name in _base_names(cls):
                available |= class_methods.get(base_name, set())
                available.add(base_name)

            for call in ast.walk(cls):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not isinstance(func, ast.Attribute):
                    continue
                value = func.value
                if not (isinstance(value, ast.Name) and value.id == "self"):
                    continue
                attr = func.attr
                if not attr.startswith("_"):
                    continue
                if attr in available or attr in _COMMON_DUNDERS:
                    continue
                if attr in package_wide:
                    continue
                found.append(
                    (
                        f"self-call resolves:{mod}.{cls.name}.{attr}",
                        f"line {call.lineno}: self.{attr}() has no definition",
                    )
                )
    return found


def _module_scope_names(tree: ast.Module) -> set[str]:
    """Names bound at module scope: imports, defs, classes, assignments, params."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            # a factory returning `cls(...)` binds cls as a parameter
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    names.add(arg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, ast.Lambda):
            for arg in node.args.args:
                names.add(arg.arg)
    return names


def dangling_module_calls(pkg: Path | None = None) -> list[tuple[str, str]]:
    """Every bare `foo(...)` that resolves to no function, import, or builtin.

    The pay-off case is a module-level helper that a class calls but nobody
    defines -- removing or renaming ``read_next_supply_seconds`` while leaving
    the call in ``HybridVision.observe`` is exactly the 0aw shape one step to the
    left.  Unlike the self-call sweep this cannot be narrowed to private names,
    because helpers in this package are public-named (``read_hud_stamina``,
    ``parse_stamina_number``); the false-positive population is instead removed
    by collecting every binding at module scope, including imports, class names,
    assignments, comprehension targets, and function parameters.
    """
    trees = _parse_package(pkg)
    builtin_names = set(dir(builtins))
    found: list[tuple[str, str]] = []
    for mod, tree in trees.items():
        scope = _module_scope_names(tree) | builtin_names
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not isinstance(func, ast.Name):
                continue
            name = func.id
            if name in scope:
                continue
            found.append(
                (
                    f"module-call resolves:{mod}.{name}",
                    f"line {call.lineno}: {name}() has no definition/import",
                )
            )
    return found


def main() -> int:
    import dataclasses

    from winter_agent_v2 import models, ocr, runtime, skills, verifier, vision
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import MarchState, Page, WorldState

    check("WorldState.stamina field", "stamina" in {f.name for f in dataclasses.fields(WorldState)})
    check("WorldState.normal_idle_slots", "normal_idle_slots" in {f.name for f in dataclasses.fields(WorldState)})

    check("ocr.HUD_STAMINA_ROI", hasattr(ocr, "HUD_STAMINA_ROI"))
    check("ocr.MARCH_COUNT_ROI", hasattr(ocr, "MARCH_COUNT_ROI"))
    check("ocr.read_hud_stamina", hasattr(ocr, "read_hud_stamina"))
    check("ocr.parse_stamina_number", hasattr(ocr, "parse_stamina_number"))
    check("ocr.read_march_count", hasattr(ocr, "read_march_count"))

    geometry = vision.SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").semantic
    check("semantic.stamina_gauge_center", hasattr(geometry, "stamina_gauge_center"))
    check("semantic.march_row_1_center", hasattr(geometry, "march_row_1_center"))

    for name in (
        "verify_march_recall_dialog_open",
        "verify_march_recalled",
        "verify_stamina_sources_open",
        "verify_free_stamina_claimed",
    ):
        check(f"verifier.{name}", hasattr(verifier, name))

    registered = {skill.id for skill in skills.v2_registry().all()}
    for skill_id in (
        "OPEN_STAMINA_SOURCES",
        "CLAIM_FREE_STAMINA",
        "SELECT_MARCH_TO_RECALL",
        "RECALL_MARCH",
    ):
        check(f"registry.{skill_id}", skill_id in registered)
        check(f"dispatchable.{skill_id}", skill_id in runtime.LiveRuntime.VERIFIED_ATOMIC)

    check("LiveRuntime.OPEN_INTEL verifier", runtime.LiveRuntime.VERIFIED_ATOMIC.get("OPEN_INTEL") is verifier.verify_open_intel)

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    check("config.stamina_policy.claim_free_stamina", config.get("stamina_policy", {}).get("claim_free_stamina") is True)
    check("config.march_policy.recall_on_demand", config.get("march_policy", {}).get("recall_on_demand") is True)
    check("config.reserve_for_stamina", int(config.get("march_policy", {}).get("reserve_for_stamina", 0)) >= 1,
          f"={config.get('march_policy', {}).get('reserve_for_stamina')}")

    # The config value above is the operator's INTENT, not a number of slots.
    # RuleBrain caps it by the observed capacity so the reservation can never claim
    # the whole army: if it did, `idle <= reserved` would hold at every occupancy and
    # the goal would be permanently dead rather than merely blocked.  That is exactly
    # what a capacity-2 role with a standing reserve of 2 did on 2026-09-16 -- three
    # GATHER_RESOURCE runs in a row produced no episode.  Checked here rather than
    # only in a unit test because the config value alone cannot reveal the problem.
    reservation_brain = RuleBrain(
        current_goal="GATHER_RESOURCE",
        reserve_marches=int(config.get("march_policy", {}).get("reserve_for_stamina", 0)),
    )
    for capacity in (1, 2, 3, 4, 6):
        reserved = reservation_brain.reserved_slots(WorldState(page=Page.MAP, march_max=capacity))
        check(f"reservation.leaves_a_usable_slot.capacity_{capacity}", reserved < capacity, f"reserved={reserved}")

    registry = skills.v2_registry()

    def decide(state, **kwargs):
        return RuleBrain(**kwargs).decide(state, registry)

    panel_free = WorldState(page=Page.POPUP, popup="GET_MORE_STAMINA",
                            stamina={"current": 200, "free_claim_available": True}, confidence=0.99)
    panel_used = WorldState(page=Page.POPUP, popup="GET_MORE_STAMINA",
                            stamina={"current": 350, "free_claim_available": False}, confidence=0.99)
    check("brain: panel with free gift -> CLAIM_FREE_STAMINA",
          decide(panel_free).skill == "CLAIM_FREE_STAMINA")
    check("brain: panel without free gift -> BACK",
          decide(panel_used).skill == "BACK")

    dialog = WorldState(page=Page.POPUP, popup="MARCH_RECALL", confidence=0.99)
    check("brain: unexplained recall dialog -> CLOSE_POPUP",
          decide(dialog).skill == "CLOSE_POPUP")
    with_intent = RuleBrain(recall_on_demand=True)
    with_intent.pending_recall = True
    check("brain: recall dialog with intent -> RECALL_MARCH",
          with_intent.decide(dialog, registry).skill == "RECALL_MARCH")

    full = WorldState(page=Page.MAP, march_used=6, march_max=6,
                      marches=(MarchState.GATHERING,), confidence=0.99)
    check("brain: full queue freezes gathering when recall is off",
          decide(full).skill == "SAFE_STOP")
    check("brain: full queue recalls a gathering march when allowed",
          decide(full, recall_on_demand=True).skill == "SELECT_MARCH_TO_RECALL")

    map_ready = WorldState(page=Page.MAP, march_used=5, march_max=6,
                           marches=(MarchState.GATHERING,), stamina={"current": 350}, confidence=0.99)
    check("brain: map checks the free gift once per run",
          decide(map_ready, claim_free_stamina=True).skill == "OPEN_STAMINA_SOURCES")

    # The 任务 panel OPEN_DAILY opens is a dead end when it holds nothing
    # claimable: leaving it is what keeps the next run usable, and the flag is
    # what keeps the loop from re-opening the panel it just left.
    empty_panel = WorldState(page=Page.DAILY, daily={"status": "AVAILABLE", "claimable_count": 0},
                             confidence=0.99)
    panel_brain = RuleBrain(current_goal="DAILY")
    check("brain: empty daily panel is left, not stranding the run",
          panel_brain.decide(empty_panel, registry).skill == "BACK")
    home_after = WorldState(page=Page.HOME, confidence=0.99)
    check("brain: the panel is not re-opened after it was read",
          panel_brain.decide(home_after, registry).skill == "SAFE_STOP")
    claimable_panel = WorldState(page=Page.DAILY, daily={"status": "CLAIMABLE", "claimable_count": 2},
                                 confidence=0.99)
    check("brain: a claimable daily panel is still claimed",
          decide(claimable_panel).skill == "DAILY_CLAIM_REWARDS")

    # The panel opens on 章节任务 while the page classifier names the page from the
    # 每日任务 string on the tab bar, so the daily skills were reading another tab's
    # content.  One tap switches it, and it must be one tap only.
    other_tab = WorldState(page=Page.DAILY,
                           daily={"tab": "NOT_TASKS", "status": "AVAILABLE", "claimable_count": 0},
                           confidence=0.99)
    tab_brain = RuleBrain(current_goal="DAILY")
    check("brain: daily panel on another tab -> SELECT_DAILY_TAB",
          tab_brain.decide(other_tab, registry).skill == "SELECT_DAILY_TAB")
    check("brain: the daily tab is not tapped twice",
          tab_brain.decide(other_tab, registry).skill != "SELECT_DAILY_TAB")
    on_daily_tab = WorldState(page=Page.DAILY,
                              daily={"tab": "TASKS", "status": "CLAIMABLE", "claimable_count": 2},
                              confidence=0.99)
    check("brain: the daily tab is not re-tapped when it already shows",
          decide(on_daily_tab).skill == "DAILY_CLAIM_REWARDS")

    goals_source = (ROOT / "winter_agent_v2/goal_library.py").read_text(encoding="utf-8")
    check("goal_library reads world.stamina", "world.stamina" in goals_source)

    # The 战力 route: HOME -> 加成总览 -> 实力详情 -> 部队实力 提升 -> camp focus -> 训练.
    # It is four skills whose decisions all already existed; what it never had was
    # templates that resolve on today's client, so `world.training` stayed empty and
    # every branch below was unreachable.  Pinned here because a decision that no
    # frame can trigger is indistinguishable from a missing decision.
    train = RuleBrain(current_goal="TRAIN")
    check("brain: TRAIN on HOME enters the power route",
          train.decide(WorldState(page=Page.HOME, confidence=0.99), registry).skill
          == "OPEN_POWER_OVERVIEW")
    check("brain: TRAIN on the power overview opens the details panel",
          train.decide(WorldState(page=Page.POPUP, popup="POWER_OVERVIEW", confidence=0.99),
                       registry).skill == "OPEN_POWER_DETAILS")
    check("brain: TRAIN on the details panel focuses the infantry camp",
          train.decide(WorldState(page=Page.POPUP, popup="POWER_DETAILS", confidence=0.99),
                       registry).skill == "NAVIGATE_INFANTRY_CAMP")
    focused_camp = WorldState(page=Page.HOME,
                              training={"building": "INFANTRY_CAMP", "menu_open": True,
                                        "queue_available": True},
                              confidence=0.99)
    check("brain: TRAIN on the focused camp opens the training page",
          train.decide(focused_camp, registry).skill == "OPEN_INFANTRY_TRAINING")
    busy_queue = WorldState(page=Page.TRAINING,
                            training={"troop_type": "INFANTRY", "status": "IN_PROGRESS",
                                      "queue_available": False},
                            confidence=0.99)
    check("brain: TRAIN on a busy queue stops instead of spending",
          train.decide(busy_queue, registry).skill == "SAFE_STOP")
    free_queue = WorldState(page=Page.TRAINING,
                            training={"troop_type": "INFANTRY", "status": "AVAILABLE",
                                      "queue_available": True, "trainable": True},
                            confidence=0.99)
    check("brain: a free training queue starts a batch",
          decide(free_queue).skill == "TRAIN_TROOPS")

    for step in ("OPEN_POWER_OVERVIEW", "OPEN_POWER_DETAILS", "NAVIGATE_INFANTRY_CAMP",
                 "OPEN_INFANTRY_TRAINING", "TRAIN_TROOPS"):
        check(f"runtime: {step} has a verifier",
              step in runtime.LiveRuntime.VERIFIED_ATOMIC)

    # The 科技研究 route: the same four hops, one category row across (科技实力 instead
    # of 部队实力).  The route was measured on 2026-09-04 and again on 2026-09-17, but
    # the RESEARCH goal had no navigation at all -- it could only ever stop with
    # research_entry_not_verified, which is why the goal sat BLOCKED.
    research = RuleBrain(current_goal="RESEARCH")
    check("brain: RESEARCH on HOME enters the power route",
          research.decide(WorldState(page=Page.HOME, confidence=0.99), registry).skill
          == "OPEN_POWER_OVERVIEW")
    check("brain: RESEARCH on the power overview opens the details panel",
          research.decide(WorldState(page=Page.POPUP, popup="POWER_OVERVIEW", confidence=0.99),
                          registry).skill == "OPEN_POWER_DETAILS")
    check("brain: RESEARCH on the details panel focuses the 科研所",
          research.decide(WorldState(page=Page.POPUP, popup="POWER_DETAILS", confidence=0.99),
                          registry).skill == "NAVIGATE_RESEARCH_LAB")
    focused_lab = WorldState(page=Page.HOME,
                             research={"building": "RESEARCH_LAB", "menu_open": True},
                             confidence=0.99)
    check("brain: RESEARCH on the focused lab opens the technology page",
          research.decide(focused_lab, registry).skill == "OPEN_RESEARCH")
    check("brain: TRAIN on the focused lab does not take the research hop",
          train.decide(focused_lab, registry).skill != "OPEN_RESEARCH")
    check("brain: a research page with nothing startable stops by name",
          research.decide(WorldState(page=Page.RESEARCH,
                                     research={"status": "UNKNOWN"}, confidence=0.99),
                          registry).reason == "research_page_no_startable_node")
    for step in ("NAVIGATE_RESEARCH_LAB", "OPEN_RESEARCH"):
        check(f"runtime: {step} has a verifier",
              step in runtime.LiveRuntime.VERIFIED_ATOMIC)
    # The skill factory's own contract for this goal -- it names the two skills the
    # goal needs, so a rename has to be caught here.
    from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS
    check("factory: KEEP_RESEARCH_PRODUCTIVE still names OPEN_RESEARCH + RESEARCH",
          GOAL_REQUIREMENTS["KEEP_RESEARCH_PRODUCTIVE"] == ("OPEN_RESEARCH", "RESEARCH"))

    print("\n-- dangling self-call sites (the 0aw class) --")
    for label, detail in dangling_self_calls():
        check(label, False, detail)
    check("no dangling self-call sites", not dangling_self_calls())

    print("\n-- dangling module-level call sites --")
    for label, detail in dangling_module_calls():
        check(label, False, detail)
    check("no dangling module-level call sites", not dangling_module_calls())

    # The package is not where new code comes from.  Every session adds scripts
    # under tools/ and tests/, neither of which had ever been swept -- and the
    # unattended entry points (run_live.py, run_intel_pins.py) live in tools/.
    # The 0aw class of bug is just as easy to introduce there: a call site that
    # resolves to no definition is syntactically valid, so import and pytest stay
    # green and the AttributeError waits for the one path that reaches it.
    #
    # Measured before extending (2026-09-15): 0 hits in both directories across
    # 162 files, so this adds signal rather than noise.
    print("\n-- dangling call sites outside the package (tools/, tests/) --")
    for extra in (ROOT / "tools", ROOT / "tests"):
        self_hits = dangling_self_calls(extra)
        mod_hits = dangling_module_calls(extra)
        for label, detail in self_hits + mod_hits:
            check(label, False, detail)
        check(f"no dangling calls in {extra.name}/", not (self_hits or mod_hits))

    print(f"\nproblems: {len(problems)}")
    for name in problems:
        print("  -", name)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
