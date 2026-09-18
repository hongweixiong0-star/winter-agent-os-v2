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
from datetime import datetime, timedelta, timezone
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

    # The quit dialog has its own branch so a future BTN_CLOSE record cannot
    # silently repoint the close at 确定.  Measured 2026-09-17: the winning record's
    # ROI centre (635,455) is the X in the title bar, and the two buttons that can
    # quit the client sit in one row at y 748..842.
    quit_dialog = WorldState(page=Page.POPUP, popup="EXIT_CONFIRM", confidence=0.99)
    quit_decision = decide(quit_dialog)
    check("brain: the quit dialog is closed by name, not as a generic popup",
          quit_decision.skill == "CLOSE_POPUP"
          and quit_decision.reason == "exit_confirm_closed_via_its_close_button")
    check("brain: a session-disconnected popup still reconnects, not closes",
          decide(WorldState(page=Page.POPUP, popup="SESSION_DISCONNECTED",
                            confidence=0.99)).skill == "RECONNECT_SESSION")

    # The client's shared 获得奖励 dialog: one drawing for every reward source, so
    # vision reports the goal-neutral label and the goal picks the dismiss.  Each
    # of the five goals that can produce it has to reach its own dismiss, and a
    # goal that cannot produce it must refuse to guess which page to return to.
    reward_popup = WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)
    for goal, dismiss in (("MAIL", "DISMISS_MAIL_GENERIC_REWARD"),
                          ("DAILY", "DISMISS_DAILY_GENERIC_REWARD"),
                          ("INTEL", "DISMISS_INTEL_GENERIC_REWARD"),
                          ("EXPLORATION", "DISMISS_EXPLORATION_GENERIC_REWARD"),
                          ("ALLIANCE", "DISMISS_ALLIANCE_GENERIC_REWARD")):
        check(f"brain: reward popup during {goal} -> {dismiss}",
              RuleBrain(current_goal=goal).decide(reward_popup, registry).skill == dismiss)
    check("brain: reward popup without goal context stops rather than guessing",
          decide(reward_popup).reason == "generic_reward_without_goal_context")
    # Every one of those dismisses is only usable if its verifier accepts the
    # shared label as the popup before-state -- that is the whole reason the label
    # can be goal-neutral.
    from winter_agent_v2 import verifier as _verifier
    for name in ("verify_intel_reward_dismissed", "verify_daily_reward_advanced",
                 "verify_mail_reward_dismissed", "verify_exploration_reward_dismissed",
                 "verify_alliance_reward_dismissed"):
        source = _verifier.__dict__[name].__code__.co_consts
        check(f"verifier: {name} accepts the shared reward label",
              any(isinstance(c, frozenset) and "GENERIC_REWARD" in c for c in source)
              or any(c == "GENERIC_REWARD" for c in source))

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
    check("brain: TRAIN on a busy queue leaves the page before stopping",
          train.decide(busy_queue, registry).skill == "BACK")
    # ... and the same run then stops by name instead of walking the route again.
    check("brain: TRAIN does not re-route after leaving the training page",
          train.decide(WorldState(page=Page.HOME, confidence=0.99), registry).reason
          == "training_page_already_read_not_actionable")
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
    # The page is a leaf, so the run leaves it first and names the stop on the next
    # tick -- ending on the page is what made the following run answer
    # goal_page_mismatch.  Both halves are checked, because either one alone can
    # regress without the other noticing.
    check("brain: a research page with nothing startable is left first",
          research.decide(WorldState(page=Page.RESEARCH,
                                     research={"status": "UNKNOWN"}, confidence=0.99),
                          registry).skill == "BACK")
    check("brain: a research page with nothing startable then stops by name",
          research.decide(WorldState(page=Page.HOME, confidence=0.99), registry).reason
          == "research_page_already_read_not_actionable")
    check("brain: the named stop the run reports is still a research page state",
          "research_page_no_startable_node" in
          (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8"))
    for stop in ("training_page_already_read_not_actionable",
                 "research_page_already_read_not_actionable"):
        check(f"run_live accepts the stop {stop}",
              stop in (ROOT / "tools/run_live.py").read_text(encoding="utf-8"))
    for step in ("NAVIGATE_RESEARCH_LAB", "OPEN_RESEARCH"):
        check(f"runtime: {step} has a verifier",
              step in runtime.LiveRuntime.VERIFIED_ATOMIC)
    # The skill factory's own contract for this goal -- it names the two skills the
    # goal needs, so a rename has to be caught here.
    from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS
    check("factory: KEEP_RESEARCH_PRODUCTIVE still names OPEN_RESEARCH + RESEARCH",
          GOAL_REQUIREMENTS["KEEP_RESEARCH_PRODUCTIVE"] == ("OPEN_RESEARCH", "RESEARCH"))

    # The beast hunting search hop (2026-09-17 escalation SCAN_MAP_FOR_BEAST).
    # A verifier bound to a skill no decision can reach is the defect class this
    # file exists for (see knowledge/failure_patterns/architecture/
    # VERIFIER_SHAPE_MISMATCH.md), so all three links are pinned: registered skill,
    # bound verifier, and a brain decision that really emits it -- plus the
    # isolation half, because a scan that fires while a verified target is on
    # screen would pan away from the thing it is looking for.
    beast = RuleBrain(current_goal="BEAST_HUNT")
    no_target = WorldState(page=Page.MAP, march_used=0, confidence=0.99)
    with_target = WorldState(page=Page.MAP, march_used=0,
                             beast={"visible_target": "MUSK_OX", "level": 9, "available": True},
                             confidence=0.99)
    check("brain: BEAST_HUNT on the map without a target scans for one",
          beast.decide(no_target, registry).skill == "SCAN_MAP_FOR_BEAST")
    check("brain: BEAST_HUNT does not scan past a verified target",
          beast.decide(with_target, registry).skill == "SELECT_BEAST_TARGET")
    check("runtime: SCAN_MAP_FOR_BEAST is bound to a verifier",
          "SCAN_MAP_FOR_BEAST" in runtime.LiveRuntime.VERIFIED_ATOMIC)
    scan_judge = runtime.LiveRuntime.VERIFIED_ATOMIC.get("SCAN_MAP_FOR_BEAST")
    check("runtime: the scan's binding is the map-pan verifier",
          getattr(scan_judge, "__name__", "") == "verify_beast_scan_observed")
    from winter_agent_v2.verifier import verify_beast_scan_observed
    # The live 2026-09-17 failure frame: an alliance gift popup covered the map
    # mid-pan and the client read as HOME.  The verifier must fail-closed there
    # rather than call the spend proven.
    check("verifier: a pan that lands on a covered map is not proven",
          not verify_beast_scan_observed(
              no_target, WorldState(page=Page.HOME, confidence=0.98)).ok)
    check("verifier: a readable map before and after is proven",
          verify_beast_scan_observed(no_target, no_target).ok)

    # NAVIGATE_TO_MAP (2026-09-18 escalation OPEN_MAP_NOT_PROVEN).  Same three
    # links as the beast block above -- registered skill, bound verifier, and a
    # brain decision that really emits it -- because a verifier nothing can
    # dispatch is the defect class this file exists for.  The escalated run was
    # a goal-less AUTO_DISCOVERY sweep sitting on HOME, so that path is pinned
    # explicitly alongside the named goal that shares the same first hop.
    nav_skill = registry.get("OPEN_MAP")
    check("registry: OPEN_MAP is the HOME skill that opens the world map",
          nav_skill is not None and nav_skill.required_page is Page.HOME
          and nav_skill.action.target == "PAGE_MAP")
    check("dispatchable: OPEN_MAP is bound to a verifier",
          "OPEN_MAP" in runtime.LiveRuntime.VERIFIED_ATOMIC)
    check("runtime: OPEN_MAP's binding is verify_open_map",
          runtime.LiveRuntime.VERIFIED_ATOMIC.get("OPEN_MAP") is verifier.verify_open_map)
    check("brain: a goal-less HOME sweep emits OPEN_MAP",
          RuleBrain().decide(WorldState(page=Page.HOME, confidence=0.98),
                             registry).skill == "OPEN_MAP")
    check("brain: the INTEL goal reaches the map through OPEN_MAP",
          RuleBrain(current_goal="INTEL").decide(
              WorldState(page=Page.HOME, confidence=0.98), registry).skill == "OPEN_MAP")
    # The live 2026-09-14 defect: the map really opened, and the verifier still
    # said NOT_PROVEN because an unrelated march-counter read came back empty.
    # That term must stay out of the pass condition.
    check("verifier: a proven HOME->MAP counts even with no counter read",
          verifier.verify_open_map(
              WorldState(page=Page.HOME, confidence=0.98),
              WorldState(page=Page.MAP, march_used=None, march_max=None, confidence=0.99),
          ).ok)
    # The isolation half: an unmodelled page after the tap is still a failure.
    check("verifier: an unreadable page after the tap is not proven",
          not verifier.verify_open_map(
              WorldState(page=Page.HOME, confidence=0.98),
              WorldState(page=Page.UNKNOWN, confidence=0.0),
          ).ok)
    check("verifier: staying on HOME is not proven",
          not verifier.verify_open_map(
              WorldState(page=Page.HOME, confidence=0.98),
              WorldState(page=Page.HOME, confidence=0.98),
          ).ok)

    # The operator's 2-minute Reuse Check (2026-09-17) is a rule about behaviour, so
    # what can be pinned here is that it still exists where a session will read it and
    # that the tool which answers it is runnable.  A rule that quietly disappears from
    # the route document is how the TRAIN/RESEARCH rounds nearly re-researched routes
    # that were already in the repository.
    route_doc = (ROOT / "docs" / "ADDING_A_LIVE_ROUTE.md").read_text(encoding="utf-8")
    check("docs: the route document still opens with the Reuse Check",
          "2 分钟 Reuse Check" in route_doc)
    check("docs: both prohibitions are still stated",
          "禁止已经有成熟本地实现还跑去 GitHub" in route_doc
          and "自己摸 UI 两小时" in route_doc)
    check("docs: the escalation ladder still points at the external index",
          "external_capability_map.json" in route_doc)
    check("tooling: the Reuse Check is runnable as one command",
          (ROOT / "tools" / "reuse_check.py").is_file())
    start_here = (ROOT / "START_HERE.md").read_text(encoding="utf-8")
    check("START_HERE: step 5 still requires the Reuse Check before a capability",
          "Reuse Check" in start_here)

    # The deferral gate (2026-09-18).  Its whole value is that a capability the
    # development pipeline cannot fix stops being re-selected, so what has to be
    # pinned is that the gate is on the scheduler's input path at all -- a gate that
    # nothing consults, or one that a schema filter drops, is the silent-failure class
    # this file exists for.
    from winter_agent_v2.capability_gate import BLOCKED, CapabilityGate
    from winter_agent_v2.goal_library import GoalComposition as _GoalComposition
    from winter_agent_v2.goal_library import GoalLibrary as _GoalLibrary
    from winter_agent_v2.goal_library import GoalState as _GoalState
    from winter_agent_v2.goal_library import GoalStatus as _GoalStatus
    from winter_agent_v2.runtime_snapshot import RuntimeSnapshot as _RuntimeSnapshot

    _gate = CapabilityGate(
        compositions={"G": _GoalComposition("G", "SEQUENCE", ("CAP",))},
        capabilities={"CAP": (BLOCKED, "repair budget exhausted", None)},
        streaks={"G": (9, datetime.now(timezone.utc) - timedelta(minutes=1), "SKILL")},
        attempted={"G": frozenset({"SKILL"})},
        reached={"G": frozenset({"CAP"})},
    )
    _blocked = _gate.blocks(_GoalState("G", _GoalStatus.READY))
    check("gate: a blocked capability defers the goal that needs it",
          _blocked is not None and _blocked.state == BLOCKED and _blocked.capability == "CAP")
    check("gate: an empty gate leaves the same goal alone",
          CapabilityGate.empty().allows(_GoalState("G", _GoalStatus.READY)))
    check("gate: the runtime consults it when it selects a goal",
          "self._selectable(goals, deferrals)" in (PKG / "runtime.py").read_text(encoding="utf-8"))
    check("gate: the snapshot can carry the deferrals it is given",
          "deferred_goals" in _RuntimeSnapshot.__dataclass_fields__)
    _march_states = {g.goal_id: g for g in _GoalLibrary().discover(
        WorldState(page=Page.MAP, march_used=2, march_max=6, confidence=0.99)
    )}
    check("goal: idle marches are a measurable goal",
          _march_states.get("KEEP_MARCHES_PRODUCTIVE") is not None
          and _march_states["KEEP_MARCHES_PRODUCTIVE"].distance == 4.0
          and _march_states["KEEP_MARCHES_PRODUCTIVE"].status is _GoalStatus.READY)

    # -- the escalation queue's clock ---------------------------------------
    #
    # The live defect these exist for (operator P0, 2026-09-18): the consumer was
    # only ever called from the end of an AUTO cycle, so "created" did not mean
    # "will reach the bridge".  A queue with a consumer but no clock looks healthy
    # from every file and still leaves records sitting NEW.  These checks fail if
    # the pump is removed from the window, if the pump stops being the same
    # consumer, or if the window stops starting it.
    _queue_source = (PKG / "escalation_queue.py").read_text(encoding="utf-8")
    _panel_source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    _reload_source = (PKG / "runtime_reload.py").read_text(encoding="utf-8")
    from winter_agent_v2 import escalation_queue as _escalation

    check("pump: the adapter exposes one consume pass with no run behind it",
          hasattr(_escalation.EscalationQueueAdapter, "pump")
          and "self._drain(" in _queue_source
          and "stop_reason=PUMP_STOP_REASON" in _queue_source)
    check("pump: its stop reason is in neither the wall table nor the weather list",
          _escalation.PUMP_STOP_REASON not in _escalation.NON_ESCALATABLE_STOP_REASONS
          and _escalation.PUMP_STOP_REASON not in _escalation.STOP_REASON_WALLS)
    check("pump: the window owns one and starts it with the window",
          "self.pump = QueuePump(enabled=self._auto_development_allowed)" in _panel_source
          and "self.pump.start()" in _panel_source)
    check("pump: closing the window stops it",
          "self.pump.stop()" in _panel_source)
    check("pump: the operator's stop gates it, a pause does not",
          "self.operator_intent != \"STOPPED\"" in _panel_source)
    check("slot: the timebox the job is told is the one that is enforced",
          "timebox_minutes=self.policy.job_timebox_minutes" in _queue_source
          and "box = self.policy.job_timebox_minutes" in _queue_source)
    check("slot: an expired job is only cancelled when records wait behind it",
          "if not waiting or record.submitted_at is None:" in _queue_source
          and "def _reclaim_expired_slot(" in _queue_source)
    check("proof: a no-progress signature needs a measured move, not a green step",
          "PROOF_IS_GOAL_PROGRESS = frozenset({\"NO_GOAL_PROGRESS\"})" in _queue_source
          and "require_goal_progress and row.get(\"goal_progress\") is not True"
              in _queue_source
          and "require_goal_progress=str(failure_type).upper() in PROOF_IS_GOAL_PROGRESS"
              in _queue_source)
    check("proof: the release path uses the same bar as reconciliation",
          _queue_source.count("in PROOF_IS_GOAL_PROGRESS") >= 3)
    check("reload: an active job never holds AUTO off",
          "if active_jobs > 0:" not in _reload_source
          and "not held for it" in _reload_source)
    check("reload: the settle window follows the newest write, not the marker",
          "newest_write_at" in _reload_source and "def newest_write(" in _reload_source
          and "newest_write_at=newest_write(ROOT)" in _panel_source)

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
