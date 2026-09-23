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


def code_only(source: str) -> str:
    """Source with comments removed.

    A check that forbids a literal must read *code*, not prose: the panel now carries a
    comment that quotes ``text="xhw"`` to explain why it was removed, and a comment that
    can trip a check is a check that will be quietly worked around.
    """
    kept: list[str] = []
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            continue
        quote_seen = False
        cut = len(line)
        for index, char in enumerate(line):
            if char in "\"'":
                quote_seen = not quote_seen
            elif char == "#" and not quote_seen and index and line[index - 1] in " \t":
                cut = index
                break
        kept.append(line[:cut].rstrip())
    return "\n".join(kept)


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


def unhidden_process_calls(pkg: Path | None = None,
                           extra_roots: "tuple[Path, ...]" = ()) -> list[tuple[str, str]]:
    """Every background process started without the one runner's hidden-window flags.

    Operator P0, 2026-09-18: the panel flashed a black console window every few seconds.
    The cause was one call -- ``state_truth._head()`` running ``git rev-parse`` per refresh
    with no creation flags -- while *every other* call site in the package was already
    hidden.  That is the shape of this whole defect class: fixing most call sites is a
    state, not a rule, and the next refresh path added re-opens it.

    So the rule is mechanical: ``subprocess.run/Popen/call/check_output`` and
    ``os.system/os.popen`` must either pass ``creationflags`` / ``startupinfo`` directly,
    or splat ``**hidden_kwargs()`` from ``winproc`` -- or live in a file that is on
    ``HUMAN_TERMINAL_TOOLS`` below, whose reason is written out rather than assumed.

    Deliberately checks the package *and* the tools the GUI and AUTO execute, so a new
    diagnostic that shells out from a scheduled path is caught at the gate rather than by
    the operator watching windows appear.
    """
    roots = [pkg or PKG, ROOT / "tools", *extra_roots]
    strict = {
        (PKG / "winproc.py").resolve(): "this is the runner",
    }
    skip_files = {p.resolve() for p in strict}
    # ``HumanTerminalTools``: one-shot diagnostics an operator runs by hand in a terminal,
    # where a console is the point.  Every (path, reason) pair is explicit, so adding
    # another one is a decision rather than a silent exemption -- and the reason has to be
    # *true*: measured 2026-09-19, ``unattended_closure.py`` sat here as an "operator-run
    # closure ladder" while ``control_panel`` imported it and called ``heads()`` on the
    # refresh path, so the guard reported ``problems: 0`` over the one call site that was
    # raising a modal ERROR_NO_DATA (232) dialog from the console-less panel and silently
    # returning no commits.  It is not on this list any more: a tool the GUI imports is
    # production code, whatever an operator can also do with it by hand.  ``reached_tools``
    # below keeps that from being re-decided by accident.
    for name, reason in HUMAN_TERMINAL_TOOLS:
        path = (ROOT / "tools" / name).resolve()
        if path.exists():
            strict[path] = reason
            skip_files.add(path)
    found: list[tuple[str, str]] = []
    watched = {"subprocess.run", "subprocess.Popen", "subprocess.call",
               "subprocess.check_output", "os.system", "os.popen"}
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            resolved = path.resolve()
            if resolved in skip_files or "__pycache__" in path.parts:
                continue
            # A tree copied into the repo by an analyzer's own test is not production code.
            if any(part.startswith("_pt") for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
                    continue
                name = f"{func.value.id}.{func.attr}"
                if name not in watched:
                    continue
                keywords = {keyword.arg for keyword in node.keywords}
                splat = ast.dump(node)
                hidden = ("creationflags" in keywords or "startupinfo" in keywords
                          or None in keywords or "hidden_kwargs" in splat)
                shelled = any(
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                )
                # A path outside the repo (a test's temp root) must still be *labelled*,
                # not raise: a guard that crashes cannot be trusted, and the crash would
                # hide the finding rather than report it.
                try:
                    rel = path.relative_to(ROOT).as_posix()
                except ValueError:
                    rel = path.as_posix()
                if not hidden:
                    found.append((f"unhidden-process:{rel}:{node.lineno}",
                                  f"{name} without creationflags/hidden_kwargs()"))
                elif shelled:
                    found.append((f"shell-process:{rel}:{node.lineno}",
                                  f"{name}(shell=True) -- use winproc.run_shell and hide it"))
    return found


# One-shot tools a human runs from a terminal.  Named with their reason so the exemption
# is auditable, and so a *new* tool does not inherit it by accident.
HUMAN_TERMINAL_TOOLS: tuple[tuple[str, str], ...] = (
    ("cq_0ba_check.py", "one-shot probe bound from a terminal"),
    ("cq_0ba_live_probe.py", "one-shot probe bound from a terminal"),
    ("cq_recon.py", "one-shot reconnaissance from a terminal"),
    ("escape_to_known_page.py", "interactive device helper"),
    ("git_sync.py", "operator-run git/CI tool; runs in a terminal by definition"),
    ("probe_maa.py", "one-shot MAA probe"),
    ("probe_maa_api.py", "one-shot MAA probe"),
    ("probe_maa_api2.py", "one-shot MAA probe"),
    ("run_intel_loop.py", "interactive loop driven by hand"),
    ("run_intel_pins.py", "interactive loop driven by hand"),
    ("run_recall_e2e.py", "interactive end-to-end script"),
    ("run_tests_batched.py", "operator-run test runner"),
    ("scan_public_repo.py", "operator-run pre-push gate"),
    ("simulate_new_account.py", "interactive account simulation"),
    ("update_workbuddy_handoff.py", "operator-run handoff generator"),
    ("wait_for_known_page.py", "interactive device helper"),
)


def reached_tools(pkg: Path | None = None) -> list[tuple[str, str]]:
    """Every ``HUMAN_TERMINAL_TOOLS`` entry that other code imports.

    The exemption above rests on one premise -- "an operator runs this by hand in a
    terminal" -- and that premise is what makes an unhidden console acceptable for it.  The
    premise therefore has to be *checked*, because its failure is silent in both
    directions: an exempted tool that the window calls is production code drawing a
    terminal's privileges, and the guard keeps reporting zero problems while the panel
    raises dialog boxes at the operator.

    Measured 2026-09-19: ``unattended_closure.py`` was exempt on exactly that premise while
    ``tools/control_panel.py`` did ``import unattended_closure as closure`` and called
    ``closure.heads()`` from its refresh path.  That entry is removed rather than
    re-explained; this check is what stops the next one from being fiction.
    """
    stems = {Path(name).stem: name for name, _reason in HUMAN_TERMINAL_TOOLS}
    if not stems:
        return []
    exempt = {(ROOT / "tools" / name).resolve() for name, _reason in HUMAN_TERMINAL_TOOLS}
    found: list[tuple[str, str]] = []
    for root in (pkg or PKG, ROOT / "tools"):
        for path in sorted(root.rglob("*.py")):
            if path.resolve() in exempt or "__pycache__" in path.parts:
                continue
            # A tree copied into the repo by an analyzer's own test is not production code.
            if any(part.startswith("_pt") for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                imported: list[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [alias.name for alias in node.names]
                for name in imported:
                    leaf = name.rsplit(".", 1)[-1]
                    if leaf not in stems:
                        continue
                    try:
                        rel = path.relative_to(ROOT).as_posix()
                    except ValueError:
                        rel = path.as_posix()
                    found.append((
                        f"exempted-tool-imported:{rel}:{node.lineno}",
                        f"imports {stems[leaf]}, exempted as a human terminal tool -- "
                        f"a tool the GUI or AUTO executes is not one"))
    return found


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
    from winter_agent_v2 import beast_targets
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

    # What the reservation refuses, and what it does not.
    #
    # Measured live 2026-09-21T03:17:51Z: one round ran a single action and then stopped
    # with stop_reason 'reserved_march_for_stamina' while the frame read
    # marches GATHERING+RETURNING, march_used 2, march_max 3 -- one free slot, exactly the
    # reserved one.  The refusal itself is right; ending the whole cycle because of it is
    # not, and the two are pinned separately so neither can be "fixed" by weakening the
    # other.  This is the same frame the runtime guard below refers to.
    incident = WorldState(page=Page.MAP, march_used=2, march_max=3,
                          stamina={"current": 175, "source": "MAP_HUD"}, confidence=0.99)
    intent = int(config.get("march_policy", {}).get("reserve_for_stamina", 0))
    _reservation_registry = skills.v2_registry()
    check("reservation.refuses_the_last_slot_to_the_gather_route",
          RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=intent).decide(
              incident, _reservation_registry).reason == "reserved_march_for_stamina")
    check("reservation.does_not_refuse_it_to_the_stamina_goal",
          RuleBrain(current_goal="BEAST_HUNT", reserve_marches=intent).decide(
              incident, _reservation_registry).skill == "SCAN_MAP_FOR_BEAST",
          "the slot is held FOR this goal, so it must be able to use it")

    # ...and the runtime hands the cycle over instead of ending it, for EVERY reason the
    # project does not call fatal.
    #
    # What is asserted is the shape of the decision, not a list, and that is the point of the
    # change: the previous version of this check named 'reserved_march_for_stamina', so it
    # only ever covered that one reason -- which is how the same defect (one goal's refusal
    # ending the whole cycle) survived untouched in 'alliance_state_unknown', 'no_idle_march',
    # 'camp_entry_is_a_guided_step_not_a_selection' and the rest.  `is_fatal_stop` is the run's
    # own line between DEGRADED and FATAL_STOPPED, so a new non-fatal reason is covered the day
    # it appears and a genuinely fatal one still stops.
    _runtime_source = (PKG / "runtime.py").read_text(encoding="utf-8")
    check("runtime: a non-fatal refusal hands the cycle over instead of ending the run",
          "not is_fatal_stop(decision.reason)" in _runtime_source
          and "_yield_to_next_goal(" in _runtime_source)
    check("runtime: ...for every reason the project does not call fatal, not a hand-picked one",
          'decision.reason == "reserved_march_for_stamina"' not in _runtime_source,
          "the single-reason special case must be gone, not duplicated")
    check("runtime: ...and the handover stays bounded by the remaining budget",
          "not is_fatal_stop(decision.reason)\n                    and index < max_actions"
          in _runtime_source,
          "yielding costs an iteration, so it needs one to yield in")

    # Every wait for a worker is bounded, so a child that never exits cannot end the cycle.
    #
    # Live 2026-09-21 11:43:24: the round's worker finished its loop and never exited; the panel
    # waited on its pipe for the rest of the session, no round started, and the window had to be
    # restarted.  The bound is one helper; this fails if any call site goes back to a bare wait.
    _panel_source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    check("panel: no unbounded wait for a worker anywhere",
          ".communicate()" not in _panel_source,
          "a bare communicate() waits for EOF, which a grandchild can hold open for ever")
    check("panel: ...every wait goes through the bounded helper",
          _panel_source.count("await_worker(") >= 16
          and "WORKER_WAIT_SECONDS = " in _panel_source
          and "WORKER_ABANDONED_CODE = " in _panel_source)
    check("panel: ...and giving up is not the worker's own exit code",
          "WORKER_ABANDONED_CODE = 130" in _panel_source)

    # The training page is read by OCR, and its numbers are readings.
    #
    # Live evidence 2026-09-21: `PAGE_TRAINING_*` and `TRAINING_QUEUE_TIMER` are CANDIDATE records
    # that match nothing on the client, so `world.training` was always empty and `TRAIN_TROOPS`
    # (which requires Page.TRAINING) could never run; the branch that was meant to fill it carried
    # `tier: 10` / `batch_count: 806` from an old screenshot.  The OCR classifier reads the same
    # frames exactly, and is consulted only when the template layer has nothing.
    _ocr_source = (PKG / "ocr.py").read_text(encoding="utf-8")
    _vision_body = "\n".join(
        line for line in (PKG / "vision.py").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    check("training: the page is consulted through OCR when the templates have nothing",
          "if primary.page is Page.UNKNOWN and not primary.training:" in _ocr_source
          and "if secondary.page is Page.TRAINING and secondary.training:" in _ocr_source)
    check("training: ...and the branch no longer serves an old screenshot's numbers as readings",
          '"batch_count": 806' not in _vision_body and '"tier": 10' not in _vision_body)

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
    # A goal that cannot name the page under the dialog must still not stop on it.
    # The client declares the exit on the dialog itself (点击任意位置退出), so
    # clearing a blocker is not a guess about which page to return to -- this used
    # to be SAFE_STOP.  Measured live 2026-09-20 (open issue #64): five of six AUTO
    # rounds inside twenty minutes ended on this dialog, and each one ended the run
    # instead of clearing it, so the next round met the same dialog again.
    neutral = decide(reward_popup)
    check("brain: reward popup without goal context is closed by the dialog's own exit",
          neutral.skill == "DISMISS_SHARED_REWARD"
          and neutral.reason == "shared_reward_popup_dismissed_by_its_declared_exit")
    # ...and the surface they tap is the footer exit band, not the title band.
    # vision.py recognises the dialog by ``banner OR footer``, so the footer alone
    # is enough to report POPUP/GENERIC_REWARD -- but the dismisses asked for the
    # banner, and the banner rides its own tolerance (14, 16, 18, 20, 26 across six
    # live dialog frames, against 16) while the footer scores 0-2 against 8.  In the
    # live log 45 of the 51 all-time failures of the old target are
    # SEMANTIC_TARGET_NOT_VERIFIED: recognised, and no tap could be aimed at it.
    # This is not the claim that the banner is inert -- a banner tap did close the
    # dialog at 2026-09-20T13:09:49Z -- only that it is the signal that keeps
    # falling outside its gate while the footer never does.
    dismiss_skills = ("DISMISS_MAIL_GENERIC_REWARD", "DISMISS_DAILY_GENERIC_REWARD",
                      "DISMISS_INTEL_GENERIC_REWARD",
                      "DISMISS_EXPLORATION_GENERIC_REWARD",
                      "DISMISS_ALLIANCE_GENERIC_REWARD", "DISMISS_SHARED_REWARD")
    check("skills: every generic-reward dismiss taps the dialog's declared exit",
          all(registry.get(name) is not None
              and registry.get(name).action.target == skills.SHARED_REWARD_EXIT
              for name in dismiss_skills))
    check("dispatchable.DISMISS_SHARED_REWARD",
          runtime.LiveRuntime.VERIFIED_ATOMIC.get("DISMISS_SHARED_REWARD")
          is verifier.verify_popup_closed)

    # A skill the loop may select must name a target the vision can actually resolve.
    # The registry and the template manifest are two files edited by two different
    # sessions, so "the skill exists" and "the button exists" can drift apart silently:
    # the step is selected, the executor cannot resolve the target, and the episode comes
    # back SEMANTIC_TARGET_NOT_VERIFIED with no hint that a template is what is missing.
    # Audited 2026-09-20 (the operator's generic-semantics pass): exactly one schedulable
    # skill was in that state -- RESEARCH -> BTN_START_RESEARCH -- and the reason is not a
    # missing crop.  The 科技研究 route lands on the TECH TREE
    # (dataset/truth_audit/ui_semantics_corpus/RESEARCH__01__live_runtime_step_001_after_*.png):
    # the page shows tabs 发展/经济/战斗 and research nodes with 1/3 badges, and no 研究
    # button at all -- that control only exists after a node is selected, and the route has
    # no node-selection step.  Recorded as issue #71; the check is here so the next one is
    # visible instead of being discovered from a live failure.
    _manifest_paths = json.loads(
        (ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    _manifest_semantics = {row["semantic"] for row in _manifest_paths["records"]}
    # Targets resolved from the frame by arithmetic rather than by a template -- the branches
    # in LiveRuntime._resolve_semantic_target plus the one reviewed normalized fallback.
    # BEAST_SEARCH_TAB joined on 2026-09-21: it is tapped where this frame's own OCR read the
    # 野兽 label (ocr.read_resource_tab_labels), because the strip reorders and the three
    # position-pinned beast-search templates matched nothing on the live client.
    # TRAINING_CAMP_NEXT joined 2026-09-22: the training page draws all three barracks tabs at
    # once, so no template and no remembered coordinate can say which one to tap -- the target
    # is the next camp after the one the page title says is open, read off this frame by
    # ocr.read_training_camp_tabs.  It is the hop that lets a busy 盾兵营 stop ending the whole
    # training goal (operator §八).
    # ``ORDINARY_CONTROL`` is derived the same way as the pin and the tab answers: the
    # frame's own words, not a template.  It stands for "the ordinary control this frame
    # named", so by construction nothing in the manifest can resolve it -- the same reason
    # ``INTEL_PIN`` is here.
    _derived_targets = {"RESOURCE_DYNAMIC", "HUD_STAMINA_GAUGE", "MARCH_ROW_1",
                        "RESOURCE_LEVEL_MINUS", "INTEL_PIN", "BTN_EXPLORATION_IDLE_CLAIM",
                        "BEAST_ON_MAP", "TRAINING_CAMP_IN_RING", "BEAST_SEARCH_TAB",
                        "TRAINING_CAMP_NEXT", "ORDINARY_CONTROL"}
    # ``QUICK_PANEL_ROW_*`` is the same category, and it is the largest family of them: the
    # 快捷面板 draws its rows at coordinates that depend on which rows the client chose to show
    # and on the list's own scroll, so no template can pin one.  What the resolver acts on is the
    # ROW the frame itself reports -- ``rows[].arrow_norm`` for the enter-arrow targets and
    # ``rows[].done_norm`` for the finished ones (measured 2026-09-23: the tick's own centre came
    # out at x 0.5618 on three independent frames, and the live tap landed at (404, 556)).  A
    # target whose point comes from the frame belongs here by construction, exactly like
    # ORDINARY_CONTROL above, and keeping the four pre-existing enter-arrow rows out of it left
    # this check red for reasons that had nothing to do with the rows being unactionable.
    _derived_prefixes = ("QUICK_PANEL_ROW_",)
    _unresolvable = []
    for _skill in registry.all():
        if _skill.action.kind != "TAP_SEMANTIC":
            continue
        if _skill.id not in runtime.LiveRuntime.VERIFIED_ATOMIC:
            continue
        target = _skill.action.target
        if (target in _manifest_semantics or target in _derived_targets
                or target.startswith(_derived_prefixes)):
            continue
        _unresolvable.append(f"{_skill.id}->{target}")
    # Known, recorded exception -- issue #71.  The set is pinned EXACTLY rather than
    # filtered, so this check stays useful in both directions: a new offender turns it red,
    # and if RESEARCH is repaired the stale entry turns it red until somebody removes it.
    # An allow-list that silently absorbed anything would be worse than no check.
    _known_unresolvable = {"RESEARCH->BTN_START_RESEARCH"}
    check("skills: the only unresolvable scheduler target is the recorded one (#71)",
          set(_unresolvable) == _known_unresolvable,
          f"unresolvable={sorted(_unresolvable)} known={sorted(_known_unresolvable)}")
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

    # A goal that does not own the alliance panel must leave it, not end the run.
    # Measured live 2026-09-21: goal AUTO_DISCOVERY, page ALLIANCE, {"section": "HOME"},
    # ONE step, stop_reason alliance_state_unknown -- on a frame that plainly showed
    # 联盟科技 with a 25 badge and 联盟互助 with a 6.  ``SAFE_STOP`` is not "skip this
    # observation" in the runtime: it records DEGRADED and returns from the run, and
    # nothing moved the client off the panel, so the next cycle opened on the same screen.
    # section HOME reached that line 56 times over the history, GIFTS/UNKNOWN 14,
    # TECHNOLOGY with no status field 6.
    alliance_home = WorldState(page=Page.ALLIANCE, alliance={"section": "HOME"}, confidence=0.98)
    foreign = RuleBrain(current_goal="AUTO_DISCOVERY")
    check("brain: a goal that does not own the alliance panel leaves it",
          foreign.decide(alliance_home, registry).skill == "BACK")
    check("brain: ...and leaves it only once -- the second answer is the honest stop",
          foreign.decide(alliance_home, registry).skill == "SAFE_STOP")
    # Scoped to a named goal: with no goal the scheduler is probing, and a Back there
    # would look like work and displace an observation that has real work waiting.
    check("brain: with no goal the alliance panel is still a plain stop",
          RuleBrain().decide(alliance_home, registry).skill == "SAFE_STOP")
    # The gifts hop is decided by the 联盟宝箱 tile's **own** badge (operator directive 2026-09-23 §三),
    # and until that rule the check below pinned the opposite: the goal that owns the panel opened the
    # gifts page whatever the tile said.  Measured over the 97 production steps that entered it: the
    # tile's badge was ABSENT in 93.  ``alliance_home`` above carries no ledger, so the tile is
    # UNKNOWN there and the honest answer is now a stop -- the pair below states both halves.
    check("brain: the goal that owns the panel opens its gifts hop only with the tile's own badge",
          RuleBrain(current_goal="ALLIANCE").decide(
              WorldState(
                  page=Page.ALLIANCE, alliance={"section": "HOME"}, confidence=0.98,
                  red_dots={"TILE_ALLIANCE_GIFTS": {"state": "PRESENT"}},
              ),
              registry).skill == "OPEN_ALLIANCE_GIFTS")
    check("brain: ...and does not enter the gifts page when that badge is not there",
          RuleBrain(current_goal="ALLIANCE").decide(alliance_home, registry).skill == "SAFE_STOP")
    check("brain: an unreadable status on the owned panel is still reported, not papered over",
          RuleBrain(current_goal="ALLIANCE").decide(
              WorldState(page=Page.ALLIANCE, alliance={"section": "GIFTS", "status": "UNKNOWN"},
                         confidence=0.98), registry).skill == "SAFE_STOP")

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

    # The stamina floor is exclusive, and it is stated in two modules that each own a copy.
    #
    # The operator's requirement is stamina UNDER 30 -- confirmed explicitly as "体力达到30时
    # 仍未低于30" -- so 30 itself is still unmet.  Both copies used to read it inclusively:
    # the goal answered COMPLETE at exactly 30 and the policy answered NONE there, each one
    # point early, and one point is a whole beast dispatch.  Checked behaviourally rather
    # than by grepping for a comparison, because what has to hold is the answer, not the
    # spelling of the expression that produces it.
    from winter_agent_v2 import goal_library as _goal_library
    from winter_agent_v2.goal_library import STAMINA_FLOOR
    from winter_agent_v2.operations_policy import choose_stamina_goal as _choose_stamina

    check("stamina: the floor is 30", STAMINA_FLOOR == 30, f"got {STAMINA_FLOOR}")

    def _stamina_goal(current):
        found = [
            goal
            for goal in _goal_library.GoalLibrary().discover(
                WorldState(page=Page.MAP, stamina={"current": current})
            )
            if goal.goal_id == "AVOID_STAMINA_WASTE"
        ]
        return found[0] if found else None

    _at_floor = _stamina_goal(STAMINA_FLOOR)
    _below = _stamina_goal(STAMINA_FLOOR - 1)
    check("stamina: at the floor the goal is still unfinished",
          _at_floor is not None and _at_floor.status is _goal_library.GoalStatus.READY,
          "30 is not under 30, so there is still a point to spend")
    check("stamina: ...and still owes exactly that one point",
          _at_floor is not None and _at_floor.distance == 1.0)
    check("stamina: below the floor it is finished",
          _below is not None and _below.status is _goal_library.GoalStatus.COMPLETE)
    check("stamina: the policy agrees with the goal at the same boundary",
          _choose_stamina(STAMINA_FLOOR, "AVAILABLE", True, True).goal != "NONE"
          and _choose_stamina(STAMINA_FLOOR - 1, "AVAILABLE", True, True).goal == "NONE",
          "one boundary, two modules, one answer")

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
    # Stage A: the camp highlighted with no radial menu drawn.  The route used to only wait
    # here -- 45 of this goal's 127 steps -- because the single 2026-09-17 attempt landed on
    # the world map.  That was a coordinate error, not the finger: measured over 46 live stage A
    # frames, the template's own centre is (346, 682) on every one of them while the ring sits
    # at (313, 585), i.e. 88 px below the ring's own lower edge, on bare ground.
    from winter_agent_v2 import camp_ring as _camp_ring
    from winter_agent_v2 import verifier as _verifier_module
    _stage_a_frame = (ROOT / "dataset" / "truth_audit" / "training_stage_a_20260921" / "key"
                      / "01_stage_a_ring_and_finger_20260921T163802.png")
    _template_window = {"x_norm": 0.185, "y_norm": 0.39, "w_norm": 0.59, "h_norm": 0.285}
    _ring = _camp_ring.ring_centre_norm(_stage_a_frame, _template_window)
    check("vision: the selection ring is read from the frame, not from the template's centre",
          _ring is not None and 250 <= _ring[0] * 720 <= 380 and 520 <= _ring[1] * 1280 <= 660,
          f"ring={_ring}")
    check("vision: a window with no ring answers None, not a fallback point",
          _camp_ring.ring_centre_norm(_stage_a_frame,
                                      {"x_norm": 0.02, "y_norm": 0.45,
                                       "w_norm": 0.06, "h_norm": 0.06}) is None)
    # The pair a human verified by hand.  Both carry the same semantic; one tap opened the
    # menu, the other jumped to the map.  Their template distances are 0.0 and 8.0 -- the
    # second sits ON the gate -- which is why the recorded conclusion was that the signal
    # cannot separate them.  The ring does: 205x112 against a 7x15 fleck.
    _ambiguity = ROOT / "dataset" / "truth_audit" / "training_camp_highlight_ambiguity_20260917"
    _opens = _ambiguity / "camp_with_gold_ring__click_opens_menu__20260908.png"
    _jumps = _ambiguity / "camp_with_officer_badge__click_jumps_to_map__20260917.png"
    _ambiguity_vision = vision.SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    _opens_match = _ambiguity_vision.semantic.find(_opens, "TARGET_INFANTRY_CAMP_HIGHLIGHTED")
    _jumps_match = _ambiguity_vision.semantic.find(_jumps, "TARGET_INFANTRY_CAMP_HIGHLIGHTED")
    check("vision: the frame whose tap opened the menu yields a ring point",
          _opens_match is not None
          and _camp_ring.ring_centre_norm(_opens, _opens_match.roi) is not None)
    check("vision: the frame whose tap jumped to the map yields none, so the route waits",
          _jumps_match is not None
          and _camp_ring.ring_centre_norm(_jumps, _jumps_match.roi) is None)
    _stage_a_state = WorldState(page=Page.HOME,
                                training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED",
                                          "queue_available": True,
                                          "camp_tap_norm": (0.435, 0.4565)},
                                confidence=0.99)
    _stage_a_brain = RuleBrain(current_goal="TRAIN")
    # The tap was built, wired, and then TRIED ON THE DEVICE.  Live 2026-09-20T18:43:51Z:
    # the ring's measured centre (0.441, 0.4551) = (317, 583), action_backend ADB, outcome
    # FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN with after.training EMPTY -- the ring was gone and
    # no menu appeared.  Four live taps, four failures (three at the template's own centre on
    # bare ground, one inside the ring).  So aiming was not the problem, the tap is withdrawn,
    # and these two checks now pin the withdrawal rather than the experiment.
    # Since 2026-09-23 the ring is known to be drawn by the client on its own schedule (issue
    # #92: 17:50:32 no ring, 17:51:00 the same city view with it, the panel state unchanged), so
    # Stage A spends no step waiting on it and blocks at once.
    check("brain: stage A blocks at once -- the ring draws itself, so a wait would wait on an animation",
          _stage_a_brain.decide(_stage_a_state, registry).skill == "SAFE_STOP")
    check("brain: ...and does not substitute another action",
          _stage_a_brain.decide(_stage_a_state, registry).skill == "SAFE_STOP")
    check("brain: nothing in the brain taps the highlighted camp while its meaning is unknown",
          'return Decision("SELECT_INFANTRY_CAMP"' not in
          (PKG / "brain.py").read_text(encoding="utf-8"))
    check("brain: stage A without a measured point behaves the same -- it blocks",
          RuleBrain(current_goal="TRAIN").decide(
              WorldState(page=Page.HOME,
                         training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED",
                                   "queue_available": True},
                         confidence=0.99),
              registry).skill == "SAFE_STOP")
    check("dispatchable.SELECT_INFANTRY_CAMP targets the ring and keeps the menu verifier",
          registry.get("SELECT_INFANTRY_CAMP").action.target == "TRAINING_CAMP_IN_RING"
          and runtime.LiveRuntime.VERIFIED_ATOMIC.get("SELECT_INFANTRY_CAMP")
          is _verifier_module.verify_infantry_camp_selected)
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

    # SPEND_STAMINA_ON_BEAST (2026-09-18 escalation
    # SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST).  The pan had
    # no converging hop; the route now goes mammoth sprite -> beast card 攻击 ->
    # formation page -> DISPATCH_BEAST.  Pin the same three links -- registered
    # skill, bound verifier, brain decision -- for both new hops, plus the
    # capability mapping that makes an episode count for the capability.
    check("registry: SELECT_BEAST_TARGET_MAMMOTH taps the mammoth sprite",
          registry.get("SELECT_BEAST_TARGET_MAMMOTH") is not None
          and registry.get("SELECT_BEAST_TARGET_MAMMOTH").required_page is Page.MAP
          and registry.get("SELECT_BEAST_TARGET_MAMMOTH").action.target == "TARGET_BEAST_MAMMOTH_5")
    check("registry: ATTACK_BEAST_CARD taps the beast card 攻击 control",
          registry.get("ATTACK_BEAST_CARD") is not None
          and registry.get("ATTACK_BEAST_CARD").required_page is Page.BEAST
          and registry.get("ATTACK_BEAST_CARD").action.target == "BTN_BEAST_CARD_ATTACK")
    check("dispatchable: both new skills are bound to verifiers",
          "SELECT_BEAST_TARGET_MAMMOTH" in runtime.LiveRuntime.VERIFIED_ATOMIC
          and "ATTACK_BEAST_CARD" in runtime.LiveRuntime.VERIFIED_ATOMIC)
    _mammoth_brain = RuleBrain()
    _mammoth_brain.current_goal = "BEAST_HUNT"
    check("brain: a visible mammoth emits SELECT_BEAST_TARGET_MAMMOTH",
          _mammoth_brain.decide(
              WorldState(page=Page.MAP,
                         beast={"visible_target": "MAMMOTH", "level": 5, "available": True},
                         confidence=0.99),
              registry).skill == "SELECT_BEAST_TARGET_MAMMOTH")
    check("brain: an attack card emits ATTACK_BEAST_CARD",
          RuleBrain().decide(
              WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99),
              registry).skill == "ATTACK_BEAST_CARD")
    from winter_agent_v2.escalation_queue import capability_for_skill as _cfs
    check("capability: both new skills are SPEND_STAMINA_ON_BEAST in the project's table",
          _cfs("SELECT_BEAST_TARGET_MAMMOTH") == "SPEND_STAMINA_ON_BEAST"
          and _cfs("ATTACK_BEAST_CARD") == "SPEND_STAMINA_ON_BEAST")
    # The isolation half: the 攻击 branch must not steal the musk-ox card, the
    # 前往-only card, or an empty map.
    check("vision: the musk-ox card is still the musk-ox route",
          vision.SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").observe(
              ROOT / "dataset/raw/stamina_emergency/beast9_round3_target.png"
          ).beast.get("name") == "麝牛")

    # SPEND_STAMINA_ON_BEAST, second pass (2026-09-20 operator P0: "intel is finished, spend the
    # stamina that is left").  The hops above each tap ONE species' sprite, so the route could only
    # act on a beast somebody had pre-approved or cut a template for -- and the measured cost was a
    # live frame whose 霜鳞避役/20 read perfectly (label 0.89, badge 1.00, row registered) and still
    # produced nothing, after which the route went back to panning.  The new hop taps whatever the
    # client's own label names, at the point that label's box measures.  Same three links as above.
    check("registry: SELECT_BEAST_TARGET_LABELLED taps the beast the client labelled",
          registry.get("SELECT_BEAST_TARGET_LABELLED") is not None
          and registry.get("SELECT_BEAST_TARGET_LABELLED").required_page is Page.MAP
          and registry.get("SELECT_BEAST_TARGET_LABELLED").action.kind == "TAP_SEMANTIC"
          and registry.get("SELECT_BEAST_TARGET_LABELLED").action.target == "BEAST_ON_MAP")
    check("dispatchable: the labelled hop is bound to verify_beast_card_opened",
          runtime.LiveRuntime.VERIFIED_ATOMIC.get("SELECT_BEAST_TARGET_LABELLED")
          is verifier.verify_beast_card_opened)
    _labelled_brain = RuleBrain()
    _labelled_brain.current_goal = "BEAST_HUNT"
    check("brain: a beast the client labelled is tapped instead of panning for it",
          _labelled_brain.decide(
              WorldState(page=Page.MAP,
                         beast={"visible_target": "FROST_SCALED_RUNNER", "level": 20,
                                "available": True, "source": "BEAST_LABEL",
                                "tap_norm": (0.2687, 0.6551)},
                         confidence=0.99),
              registry).skill == "SELECT_BEAST_TARGET_LABELLED")
    check("brain: the same branch resets the pan budget, so a labelled target is progress",
          _labelled_brain.beast_scans_used == 0)
    # The safety half.  Identity alone must never authorise a spend, and a target the client has
    # already refused must not even be tapped -- otherwise the generalisation would have traded one
    # silent failure (a full map read as empty) for another (stamina spent on an unwinnable fight).
    check("safety: an unmeasured species is tappable but not spendable",
          beast_targets.may_evaluate(
              {"visible_target": "FROST_SCALED_RUNNER", "level": 20, "available": True})
          and not beast_targets.is_dispatchable(
              {"visible_target": "FROST_SCALED_RUNNER", "level": 20, "available": True}))
    check("safety: the client's own 胜券在握 is what authorises the spend",
          beast_targets.is_dispatchable(
              {"visible_target": "FROST_SCALED_RUNNER", "level": 20,
               "victory_assessment": beast_targets.GREEN_ASSESSMENT}))
    check("safety: a target the client already refused is neither tapped nor spendable",
          not beast_targets.may_evaluate(
              {"visible_target": "SNOW_LEOPARD", "level": 29, "available": True})
          and not beast_targets.is_dispatchable(
              {"visible_target": "SNOW_LEOPARD", "level": 29,
               "victory_assessment": beast_targets.GREEN_ASSESSMENT}))
    check("safety: the pre-cleared musk ox keeps spending without a verdict on the frame",
          beast_targets.is_dispatchable(
              {"visible_target": "MUSK_OX", "level": 9, "available": True}))
    check("runtime: the executor resolves BEAST_ON_MAP only on the frame it was measured on",
          'if semantic == "BEAST_ON_MAP":' in (PKG / "runtime.py").read_text(encoding="utf-8"))
    check("capability: the labelled hop is SPEND_STAMINA_ON_BEAST in the project's table",
          _cfs("SELECT_BEAST_TARGET_LABELLED") == "SPEND_STAMINA_ON_BEAST")
    # The second half of the same pass: the band and the level key were each rejecting a beast the
    # pan had already brought into view.  Measured over 40 live MAP frames, a registered name was
    # read on 2 -- and both were outside the old x 0.05-0.50 / y 0.45-0.80 box, while the third
    # measurement (the beast at 霜鳞避役/19 on the 23:26 map frame) showed a badge that disagreed
    # with the only row for its species.  Pin the geometry and the key, not just the hop.
    _band = ocr.BEAST_LABEL_BAND
    check("vision: the beast label band covers where the client draws animals",
          all(
              _band["x_norm"] <= x <= _band["x_norm"] + _band["w_norm"]
              and _band["y_norm"] <= y <= _band["y_norm"] + _band["h_norm"]
              for x, y in ((0.269, 0.655), (0.516, 0.283), (0.724, 0.243))
          ),
          f"band={_band}; the three measured label positions must all be inside it")
    check("vision: a one-glyph misread of a registered name is still that name",
          ocr.named_beast_label(
              (ocr.OCRToken(text="霜解避役", confidence=0.78, box=((0, 0), (60, 0), (60, 16), (0, 16))),),
              ("霜鳞避役", "猛犸象"),
          ) == "霜鳞避役")
    check("vision: a beast card's title is not mistaken for the map's nameplate",
          ocr.named_beast_label(
              (
                  ocr.OCRToken(text="等级7霜鳞避役", confidence=1.0, box=((300, 340), (420, 340), (420, 364), (300, 364))),
                  ocr.OCRToken(text="霜鳞避役", confidence=0.88, box=((340, 830), (410, 830), (410, 854), (340, 854))),
              ),
              ("霜鳞避役",),
          ) == "霜鳞避役",
          "the card title carries a digit and the map nameplate does not")
    check("vision: a name two glyphs off is not",
          ocr.named_beast_label(
              (ocr.OCRToken(text="霜解难役", confidence=0.95, box=((0, 0), (60, 0), (60, 16), (0, 16))),),
              ("霜鳞避役",),
          ) is None)
    check("vision: an ambiguous near-miss is refused rather than picked",
          ocr.named_beast_label(
              (ocr.OCRToken(text="霜解避役", confidence=0.95, box=((0, 0), (60, 0), (60, 16), (0, 16))),),
              ("霜鳞避役", "霜解避役"),
          ) in (None, "霜解避役"),
          "an exact match wins; what must never happen is a coin flip between two names")
    check("safety: a known species at an unlisted level is tappable but not spendable",
          beast_targets.may_evaluate(
              {"visible_target": "FROST_SCALED_RUNNER", "level": 19, "available": True})
          and not beast_targets.is_dispatchable(
              {"visible_target": "FROST_SCALED_RUNNER", "level": 19, "available": True}))
    check("safety: the client's verdict still authorises it at that unlisted level",
          beast_targets.is_dispatchable(
              {"visible_target": "FROST_SCALED_RUNNER", "level": 19,
               "victory_assessment": beast_targets.GREEN_ASSESSMENT}))

    # OPEN_MARCH_FORMATION (2026-09-18 escalation
    # OPEN_MARCH_FORMATION|NO_GOAL_PROGRESS|SUBMIT_RESOURCE_SEARCH).  The same three
    # links as the two blocks above -- registered skill, bound verifier, and a brain
    # decision that really emits it -- plus the fourth link that escalation was
    # actually about: the capability name the project maps that skill to, so an
    # episode of this step is evidence for *this capability* and not merely for a
    # skill that happens to be registered somewhere.
    gather = registry.get("START_GATHER")
    check("registry: START_GATHER is the detail-page skill that opens the formation page",
          gather is not None and gather.required_page is Page.RESOURCE_DETAIL
          and gather.action.target == "BTN_GATHER")
    check("dispatchable: START_GATHER is bound to a verifier",
          "START_GATHER" in runtime.LiveRuntime.VERIFIED_ATOMIC)
    check("runtime: START_GATHER's binding is verify_march_page_open",
          runtime.LiveRuntime.VERIFIED_ATOMIC.get("START_GATHER") is verifier.verify_march_page_open)
    check("brain: a goal-less RESOURCE_DETAIL sweep emits START_GATHER",
          RuleBrain().decide(
              WorldState(page=Page.RESOURCE_DETAIL, resource_available=True, confidence=0.99),
              registry).skill == "START_GATHER")
    from winter_agent_v2.escalation_queue import capability_for_skill as _capability_for_skill
    check("capability: START_GATHER is OPEN_MARCH_FORMATION in the project's own table",
          _capability_for_skill("START_GATHER") == "OPEN_MARCH_FORMATION")
    # The isolation half: the formation page is not proven while the detail page is
    # still on screen, which is the failure the capability's history is made of.
    check("verifier: an unmoved detail page is not a formed march",
          not verifier.verify_march_page_open(
              WorldState(page=Page.RESOURCE_DETAIL, resource_available=True,
                         resource_target="WOOD", confidence=0.99),
              WorldState(page=Page.RESOURCE_DETAIL, resource_available=True,
                         resource_target="WOOD", confidence=0.99),
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
    # Measured 2026-09-18: the no-progress deferral for AVOID_STAMINA_WASTE went
    # out with an empty capability, the signature collapsed to two fields, and the
    # queue read the failure type as the capability -- a key no goal can route back
    # to.  What has to hold is that the capability the *goal's own* skills resolve
    # to is named, and that the capability field is never dropped.
    _gate_source = (PKG / "capability_gate.py").read_text(encoding="utf-8")
    _stalled = CapabilityGate(
        compositions={"G": _GoalComposition("G", "ANY_OF", ("SPEND_STAMINA_ON_BEAST",))},
        streaks={"G": (3, datetime.now(timezone.utc) - timedelta(minutes=1), "SCAN_MAP_FOR_BEAST")},
        attempted={"G": frozenset({"SCAN_MAP_FOR_BEAST"})},
        reached={"G": frozenset({"SCAN_MAP_FOR_BEAST"})},
    ).blocks(_GoalState("G", _GoalStatus.READY, available_skills=("INTEL_CLAIM_REWARDS", "BEAST_HUNT")))
    check("gate: a stalled beast route is named as SPEND_STAMINA_ON_BEAST, not as its own failure",
          "for skill in declared_skills:" in _gate_source
          and "capability_for_skill" in _gate_source
          and _stalled is not None
          and _stalled.capability == "SPEND_STAMINA_ON_BEAST"
          and _stalled.failure_signature
              == "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST")
    _nameless = CapabilityGate(
        # Two capabilities, neither reached and neither mapped from any skill, so
        # there is genuinely no name to hand over and the field stays empty.
        compositions={"G": _GoalComposition("G", "ANY_OF", ("CAP_A", "CAP_B"))},
        streaks={"G": (3, datetime.now(timezone.utc) - timedelta(minutes=1), "SWIPE")},
        attempted={"G": frozenset({"SWIPE"})},
        reached={"G": frozenset({"SWIPE"})},
    ).blocks(_GoalState("G", _GoalStatus.READY, available_skills=("SWIPE",)))
    check("gate: a no-progress signature is always the three positional fields",
          'failure_signature=f"{capability}|NO_GOAL_PROGRESS|{last_skill}"' in _gate_source
          and _nameless is not None
          and _nameless.failure_signature == "|NO_GOAL_PROGRESS|SWIPE")
    _march_states = {g.goal_id: g for g in _GoalLibrary().discover(
        WorldState(page=Page.MAP, march_used=2, march_max=6, confidence=0.99)
    )}
    check("goal: idle marches are a measurable goal",
          _march_states.get("KEEP_MARCHES_PRODUCTIVE") is not None
          and _march_states["KEEP_MARCHES_PRODUCTIVE"].distance == 4.0
          and _march_states["KEEP_MARCHES_PRODUCTIVE"].status is _GoalStatus.READY)

    # Measured 2026-09-18: OPEN_MARCH_FORMATION was escalated as the wall of
    # KEEP_MARCHES_PRODUCTIVE because the two steps that open the formation page and
    # dispatch it run on pages where no goal is discoverable, so they were recorded
    # under the synthetic AUTO_DISCOVERY placeholder -- a name that owns no meter.
    # The goal therefore never showed progress, its frontier never advanced, and the
    # capability the no-progress rule named as "never reached" was the one that works
    # (16/16 live attempts that day).  What has to hold is the executable fact: a step
    # on a page that discovers no goal carries the goal the run committed to, while
    # the named task mode and a truly goal-less run keep the labels they always had.
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as _scratch:
        _label_probe = runtime.LiveRuntime(
            device=object(), vision=object(), semantic_vision=object(),
            capture_dir=Path(_scratch),
        )
        _label_probe._committed_goal = "KEEP_MARCHES_PRODUCTIVE"
        check("runtime: a page that discovers no goal is labelled with the committed goal",
              _label_probe._step_goal(None) == "KEEP_MARCHES_PRODUCTIVE")
        _label_probe.brain.current_goal = "TRAIN"
        check("runtime: the named task mode still outranks the commitment",
              _label_probe._step_goal(None) == "TRAIN")
        _label_probe.brain.current_goal = None
        _label_probe._committed_goal = ""
        check("runtime: a run that never committed to a goal still says AUTO_DISCOVERY",
              _label_probe._step_goal(None) == "AUTO_DISCOVERY")
        # Every site that names the goal must go through the one derivation: a
        # leftover inline fallback would keep labelling some steps AUTO_DISCOVERY.
        _runtime_source = (PKG / "runtime.py").read_text(encoding="utf-8")
        check("runtime: all four goal-naming sites use the one derivation",
              _runtime_source.count("self._step_goal(best_goal)") == 4
              and '(self.brain.current_goal or "AUTO_DISCOVERY")' not in _runtime_source)

    # -- the escalation queue's clock ---------------------------------------
    #
    # The live defect these exist for (operator P0, 2026-09-18): the consumer was
    # only ever called from the end of an AUTO cycle, so "created" did not mean
    # "will reach the bridge".  A queue with a consumer but no clock looks healthy
    # from every file and still leaves records sitting NEW.  These checks fail if
    # the pump is removed from the window, if the pump stops being the same
    # consumer, or if the window stops starting it.
    _queue_source = (PKG / "escalation_queue.py").read_text(encoding="utf-8")
    _bridge_source = (PKG / "workbuddy_bridge.py").read_text(encoding="utf-8")
    _panel_source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    _reload_source = (PKG / "runtime_reload.py").read_text(encoding="utf-8")
    _bootstrap_source = (PKG / "capability_bootstrap.py").read_text(encoding="utf-8")
    _knowledge_source = (PKG / "knowledge_preload.py").read_text(encoding="utf-8")
    _truth_source = (PKG / "state_truth.py").read_text(encoding="utf-8")
    from winter_agent_v2 import capability_bootstrap as _bootstrap
    from winter_agent_v2 import escalation_queue as _escalation
    from winter_agent_v2 import knowledge_preload as _knowledge
    from winter_agent_v2 import state_truth as _truth
    from tools import control_panel as _panel

    check("queue: a no-progress deferral is never filed under the failure type",
          'if failure_type not in fields:' in _queue_source
          and 'if not capability:' in _queue_source
          and 'fields.index(failure_type)' in _queue_source)
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
    check("pump: every tick is written where a reader outside the GUI can see it",
          'PUMP_STATE_PATH = LOG_ROOT / "pump.json"' in _panel_source
          and "def _persist(self)" in _panel_source
          and _panel_source.count("self._persist()") >= 3)
    check("pump: the operator's stop gates it, a pause does not",
          "self.operator_intent != \"STOPPED\"" in _panel_source)
    check("slot: the timebox the job is told is the one that is enforced",
          "timebox_minutes=self.policy.job_timebox_minutes" in _queue_source
          and "box = self.policy.job_timebox_minutes" in _queue_source)
    # Two independent reasons to take the slot back, and the guard has to name both or it
    # would pin the half that cannot fire on an empty queue.  Measured 2026-09-19: job
    # c743127e held the only slot for 66 minutes with an empty queue and a progress clock
    # frozen 6 seconds after it started; the waiting-behind half could never act on that.
    check("slot: a job loses the slot either for starving the queue or for being wedged",
          "if not waiting or record.submitted_at is None:" not in _queue_source
          and "def _reclaim_expired_slot(" in _queue_source
          and "stalled = _progress_stall_minutes(status, moment)" in _queue_source
          and "def _progress_stall_minutes(" in _queue_source
          and "job_progress_stall_minutes" in _queue_source)
    check("slot: 'cannot judge' the progress clock must not become 'assume the worst'",
          "if stalled is None or stalled < self.policy.job_progress_stall_minutes:" in _queue_source
          and "class JobStatus" in _bridge_source
          and "def progress_at(" in _bridge_source)
    # A goal that is scheduled but has no route does nothing, quietly -- which is how four panel
    # routines stayed invisible while every capability they needed already worked.  The mapping
    # lives in runtime.py and is the only place a goal id becomes a brain route, so a new
    # schedulable goal has to appear in it.
    _runtime_source = (PKG / "runtime.py").read_text(encoding="utf-8")
    _goal_routes = {
        "CLEAR_INTEL": "INTEL",
        "AVOID_STAMINA_WASTE": "BEAST_HUNT",
        "KEEP_TRAINING_PRODUCTIVE": "TRAIN",
        "KEEP_RESEARCH_PRODUCTIVE": "RESEARCH",
        "MAIL_ROUTINE": "MAIL",
        "DAILY_ACTIVITY_TARGET": "DAILY",
        "ALLIANCE_ROUTINE": "ALLIANCE",
        "CLAIM_EXPLORATION_IDLE": "EXPLORATION",
    }
    missing_route = [
        goal for goal, route in _goal_routes.items()
        if f'"{goal}": "{route}"' not in _runtime_source
    ]
    check("goals: every schedulable goal id has a brain route in the one mapping table",
          not missing_route,
          detail=f"no route for {missing_route}")
    check("order: a changed tree waits for its own activation before any verification",
          "VERSION_ACTIVATION_PENDING" in _queue_source
          and "LIVE_VERIFY_PENDING = \"LIVE_VERIFY_PENDING\"" in _queue_source
          and "LIVE_VERIFY_PENDING," not in _queue_source.split("ACTIVE_STATES = ")[1].split("\n")[0])
    check("order: the activation boundary is the gateway's terminal time, not now",
          "def _from_millis(" in _queue_source
          and "version_since=_from_millis(status.first_terminal_at)" in _queue_source
          and "settled_at=record.version_since" in _queue_source)
    check("order: a version awaiting its examination does not hold the agent slot",
          "def _note_activation_pending(" in _queue_source
          and 'record.state = LIVE_VERIFY_PENDING' in _queue_source)
    check("lease: the runtime yields at an atomic boundary when another owner holds it",
          "self.device_lease.holder()" in (PKG / "runtime.py").read_text(encoding="utf-8")
          and "held.owner != OWNER_GAMEPLAY" in (PKG / "runtime.py").read_text(encoding="utf-8"))
    check("lease: releasing really returns the device",
          "if record.released_at is not None:" in (PKG / "device_lease.py").read_text(encoding="utf-8"))
    check("lease: an expired owner does not hold it",
          "def expired(" in (PKG / "device_lease.py").read_text(encoding="utf-8")
          and "if record.expired(now):" in (PKG / "device_lease.py").read_text(encoding="utf-8"))
    check("lease: the window reports the owner from the lease file",
          "def _report_device_owner(" in _panel_source
          and '"lease": PENDING' in _panel_source)
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

    # -- Capability Bootstrap / Preload -------------------------------------
    # The operator's two hard constraints on this mechanism are "不得建立第二套
    # Skill Registry 或第二套开发系统" and "Bootstrap 完成 ≠ LIVE_VERIFIED".  Both
    # are checkable, which is the only reason they are worth writing down.
    check("preload: it prepares a capability and hands it to the one queue",
          hasattr(_escalation.EscalationQueueAdapter, "preload")
          and "def preload(" in _queue_source
          and "condition=CAPABILITY_MISSING" in _queue_source
          and 'origin = "bootstrap_seed" if seed else "bootstrap"' in _queue_source)
    # The seed's "one at a time" rule counts records whose origin is ``bootstrap_seed``, so an
    # origin that never reaches the ledger silently disables the rule.  Both of preload's dispatch
    # sites -- recorded-but-not-submitted, and submitted -- plus ``_submit``'s own ``_record`` must
    # therefore carry the computed value rather than a literal.  Pinning "no literal" is what makes
    # this a rule instead of a coincidence: the version that hard-coded ``origin="bootstrap"`` at
    # both sites looked perfectly correct and never wrote the seed origin at all.
    check("preload: the seed's origin is computed once and reaches every dispatch site",
          'origin = "bootstrap_seed" if seed else "bootstrap"' in _queue_source
          and _queue_source.count("origin=origin") >= 3
          and 'origin="bootstrap"' not in _queue_source
          and 'origin="bootstrap_seed"' not in _queue_source)
    check("preload: selection has one authority, so the seed's candidate policy cannot be bypassed",
          "bootstrap.KnowledgeBootstrapController(self.root).select(" in _queue_source
          and "chosen = plan if plan is not None else candidates[0]" not in _queue_source)
    check("preload: it is an origin on the one ledger, not a second pipeline",
          _bootstrap_source.count("DEFAULT_LEDGER") >= 1
          and '"learning/workbuddy_escalations.jsonl"' not in _bootstrap_source
          and _bootstrap_source.count("ledger.append") == 0
          and ".events()" in _bootstrap_source
          and _queue_source.count("DEFAULT_LEDGER = ") == 1)
    check("preload: no second registry, scheduler or store lives in it",
          not any(
              word in _bootstrap_source
              for word in ("class BootstrapRegistry", "class BootstrapScheduler",
                           "class BootstrapLedger", "class BootstrapStore")
          )
          and "v2_registry" in _bootstrap_source
          and "capability_catalog.json" in _bootstrap_source
          and "capability_states" in _bootstrap_source)
    check("preload: a bootstrap can never promote a capability by itself",
          _bootstrap.BOOTSTRAP_MAX_LIFECYCLE == "READY_FOR_LIVE_VERIFY"
          and "LIVE_VERIFIED" in _bootstrap.FORBIDDEN_LIFECYCLES
          and "def lifecycle_allowed(" in _bootstrap_source
          and _bootstrap.lifecycle_allowed("CANDIDATE")
          and not _bootstrap.lifecycle_allowed("LIVE_VERIFIED"))
    check("preload: it yields to every rung the operator ranked above it",
          _bootstrap.GATE_NOT_ARMED in _bootstrap_source
          and _bootstrap.GATE_REAL_GAP_WAITING in _bootstrap_source
          and _bootstrap.GATE_AGENT_SLOT_BUSY in _bootstrap_source
          and _bootstrap.GATE_DEVICE_LEASED in _bootstrap_source
          and _bootstrap.GATE_REALTIME_ACTIVITY in _bootstrap_source)
    check("preload: the knowledge ladder is the operator's, in his order",
          _bootstrap.KNOWLEDGE_LADDER == (
              "V2_EVIDENCE", "LEGACY_ASSET", "EXTERNAL_MAP",
              "OPEN_SOURCE_UNINDEXED", "GAME_DB_WIKI", "SELF_EXPLORATION")
          and [tier for tier in (_bootstrap.PRIORITY_TIER.get(name) for name in
                                 _bootstrap.PRIORITY_LADDER)] == ["P0", "P1", "P2", "P3", "P4", "P5"]
          and _bootstrap.PRIORITY_LADDER == (
              "REAL_GAP", "UNLOCKED_MISSING", "HIGH_FREQ_FREE_VALUE",
              "OTHER_UNLOCKED", "NEAR_UNLOCK", "FUTURE_LOCKED"))
    check("preload: a capability already in the pipeline is refused by name",
          "CANDIDATE" in _bootstrap_source
          and 'return "CANDIDATE"' in _bootstrap_source
          and "LIVE_VERIFY_PENDING" in _bootstrap_source
          and "def _in_flight(" in _bootstrap_source)
    check("preload: the window runs the loop on a slower clock than the consumer",
          "PRELOAD_EVERY = 20" in _panel_source
          and "def _preload_tick(self)" in _panel_source
          and "KnowledgeBootstrapController(" in _panel_source
          and "controller.cycle()" in _panel_source
          and '"preload_note": ""' in _panel_source)
    check("preload: the window can tell a dead controller from a quiet one",
          "def alive(self)" in _panel_source
          and "def revive(self)" in _panel_source
          and "if not self.pump.alive():" in _panel_source
          and "STATE.json" in _panel_source)
    check("preload: it arms itself when the main loop is proven, not before",
          "def arm_state(" in _bootstrap_source
          and "MAIN_LOOP_P0_PASS" in _bootstrap_source
          and "P0_LOOP_STATUS.json" in _bootstrap_source
          and "OPERATOR_OVERRIDE" in _bootstrap_source)

    # -- Knowledge Preload (the persistent half) ----------------------------
    check("knowledge: the nine-rung acquisition order is the operator's",
          tuple(_knowledge.ACQUISITION_ORDER) == (
              "LIVE_VERIFIED_ASSET", "INTERNAL_KNOWLEDGE", "EPISODE_EVIDENCE",
              "LEGACY_VERIFIED_ASSET", "FAILURE_PATTERN", "EXTERNAL_MAP",
              "OPEN_SOURCE_PROJECT", "GAME_WIKI", "SELF_EXPLORATION")
          and len(_knowledge.LOCAL_RUNGS) == 5)
    check("knowledge: a record stores the operator's fields, not a free-form blob",
          set(_knowledge.GATE_FIELDS) <= set(_knowledge.KNOWLEDGE_FIELDS)
          and len(_knowledge.KNOWLEDGE_FIELDS) >= 12
          and "live_calibration_status" in _knowledge_source
          and "client_specific_notes" in _knowledge.KNOWLEDGE_FIELDS)
    check("knowledge: every preload source maps onto a named acquisition rung",
          set(_bootstrap.SOURCE_TO_RUNG) == set(_bootstrap.KNOWLEDGE_LADDER)
          and all(
              _bootstrap.acquisition_rung_for(src) in _knowledge.ACQUISITION_ORDER
              for src in _bootstrap.KNOWLEDGE_LADDER
          )
          and _bootstrap.acquisition_rung_for(_bootstrap.SRC_V2_EVIDENCE) == "LIVE_VERIFIED_ASSET")
    check("knowledge: a prior can never outrank live evidence",
          _knowledge.TRUST_RANK["PRIOR"] < _knowledge.TRUST_RANK["UNVERIFIED"]
          < _knowledge.TRUST_RANK["OBSERVED"] < _knowledge.TRUST_RANK["CONFIRMED"]
          and "def confirm_from_live(" in _knowledge_source
          and "def mark_conflict(" in _knowledge_source)
    check("knowledge: it refuses to re-read a manual it already answered",
          "def needs_research(" in _knowledge_source
          and "already answered at" in _knowledge_source
          and "def local_knowledge_check(" in _knowledge_source
          and "禁止重新联网研究" in _knowledge_source)
    check("knowledge: reading is only half of READ ONCE -- the answer comes back and lands",
          "def ingest(" in _knowledge_source
          and "def pending_research(" in _knowledge_source
          and "class ResearchIngest" in _knowledge_source
          and "def trust_for_source(" in _knowledge_source
          and "not in KNOWLEDGE_FIELDS" in _knowledge_source
          and "self.write_index(now=moment)" in _knowledge_source)
    check("knowledge: an answer may never outrank what the real client showed",
          _knowledge.trust_for_source(_knowledge.SELF_EXPLORATION) == _knowledge.OBSERVED
          and _knowledge.trust_for_source(_knowledge.GAME_WIKI) == _knowledge.PRIOR
          and _knowledge.trust_for_source(_knowledge.OPEN_SOURCE_PROJECT) == _knowledge.PRIOR
          and _knowledge.trust_for_source(_knowledge.LIVE_VERIFIED_ASSET) == _knowledge.UNVERIFIED
          and _knowledge.CONFIRMED not in {
              _knowledge.trust_for_source(rung) for rung in _knowledge.ACQUISITION_ORDER
          })
    check("knowledge: a hole is never confirmed, so research cannot un-schedule its own row",
          "def headline_status(" in _knowledge_source
          and "if self.missing and TRUST_RANK.get(weakest, 0) >= TRUST_RANK[CONFIRMED]" in _knowledge_source
          and "and not record.sufficient" in _bootstrap_source)
    check("knowledge: the ingest runs before the selection that it must be able to change",
          "ingest = self._ingest(now=moment)" in _bootstrap_source
          and _bootstrap_source.index("ingest = self._ingest(now=moment)")
          < _bootstrap_source.index("plan, skipped = self.select(scanner, arm_reason=arm_reason)")
          and "def _ingest(" in _bootstrap_source)
    check("knowledge: the controller reports its named running state, not just a heartbeat",
          _bootstrap.BOOTSTRAP_STATES == (
              "RUNNING", "LEARNING", "PRELOADING", "WAITING_LIVE_VERIFY",
              "LIVE_CALIBRATING", "BLOCKED", "IDLE_NO_WORK")
          and "def machine_state(" in _bootstrap_source
          and '"status": self.machine_state(' in _bootstrap_source
          and '"waiting_live_verify_count"' in _bootstrap_source
          and '"queue_depth"' in _bootstrap_source
          and '"last_ingest"' in _bootstrap_source)
    check("knowledge: the window shows the state the controller recorded, not its own opinion",
          "BOOTSTRAP_STATE_ZH" in _panel_source
          and '"preload_status"' in _panel_source
          and '"preload_ingest"' in _panel_source)

    # -- truth sources: a displayed state must name its source, or say it does not know --
    # The operator found the window printing 当前角色 xhw from a string literal while the
    # client was a different role, next to a literal claiming the device was online.  A
    # literal cannot be distinguished from a measurement, so these checks fail if a state
    # cell goes back to being one, or if the audit stops covering the key states.
    check("truth: every key state the operator listed has an auditor",
          set(_truth.audited_names()) >= {
              "current_role", "current_page", "current_goal", "current_skill",
              "auto_state", "march_capacity", "resources", "queues", "feature_unlock",
              "event_state", "executor_backend", "version_active", "verifier",
              "workbuddy_jobs", "device_lease", "capability_lifecycle"}
          and "def report(" in _truth_source)
    check("truth: the ladder is the operator's, and a literal sits below a stale value",
          _truth.STATUS_RANK[_truth.LIVE_OBSERVED] > _truth.STATUS_RANK[_truth.FRESH_RUNTIME]
          > _truth.STATUS_RANK[_truth.PERSISTED] > _truth.STATUS_RANK[_truth.REQUESTED]
          and _truth.STATUS_RANK[_truth.ASSUMED] < _truth.STATUS_RANK[_truth.PERSISTED]
          and _truth.STATUS_RANK[_truth.UNKNOWN] < _truth.STATUS_RANK[_truth.ASSUMED])
    check("truth: a cached value may not impersonate a current one",
          "def display(" in _truth_source
          and 'f"{UNKNOWN}（{STATUS_ZH.get(self.status, self.status)}）"' in _truth_source
          and "STALE" in _truth_source
          and "def stale(" in _truth_source)
    check("truth: two sources disagreeing is a finding, not a tie-break",
          "class Conflict" in _truth_source
          and "STATE_CONFLICT" in _truth.Conflict("x", (("a", "1"),)).describe()
          and "self._conflicts.append(" in _truth_source)
    check("truth: the role scopes the states that belong to an account",
          "def role(" in _truth_source
          and "未按当前角色确认" in _truth_source
          and "role_id=role.role_id" in _truth_source)
    check("truth: it owns no state -- it reads the artifacts that already exist",
          not any(
              word in _truth_source
              for word in ("def save(", "def write_index(", "class TruthStore",
                           "class WorldState")
          )
          # Exactly one writer, and it is the role artifact: the vision reader existed and
          # nothing wrote its answer anywhere, which is why the window had a literal.
          and _truth_source.count(".write_text(") == 1
          and "def record_role(" in _truth_source
          and _truth_source.count("_read_json(") >= 5)
    _panel_code = code_only(_panel_source)
    check("truth: the window reads the audit instead of printing a constant",
          'text="xhw"' not in _panel_code
          and "● 在线" not in _panel_code
          and 'self.values["role"]' in _panel_code
          and "def _poll_truth(self)" in _panel_code
          and "self._poll_truth()" in _panel_code
          and "def _refresh_truth(self)" in _panel_code)
    check("truth: the audit does not run on the UI thread",
          "_poll_truth" in _panel_source
          and _panel_source.index("def _poll_truth(self)")
          < _panel_source.index("def _refresh_truth(self)")
          and "TruthAudit(" in _panel_source)
    _learning_source = (PKG / "learning.py").read_text(encoding="utf-8")
    _runtime_source = (PKG / "runtime.py").read_text(encoding="utf-8")
    _run_live_source = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    check("truth: an episode carries the role it was taken under",
          "role_id: str = \"\"" in _learning_source
          and "role_scope: str = \"\"" in _learning_source
          and "role_id=self.role_id" in _runtime_source
          and "role_scope=self.role_scope" in _runtime_source
          and "role_id=role_id," in _run_live_source
          and "role_scope=role_scope," in _run_live_source)
    check("truth: an unscoped episode stays visibly unscoped",
          'role_id = role.role_id if role is not None else ""' in _run_live_source
          and 'role_scope = role.status if role is not None else ""' in _run_live_source
          and "def episode_role_scope(" in _truth_source
          and "全部未按角色限定" in _truth_source
          and "有别的角色的 episode 混在同一份语料里" in _truth_source)

    # -- the control centre: eight indicators, one vocabulary, no second state --
    check("gui: the top bar is eight cells in one vocabulary, not prose",
          "SYSTEM_INDICATORS" in _panel_source
          and _panel_code.count("SYSTEM_INDICATORS") >= 1
          and 'DOT_TEXT: dict[str, str]' in _panel_source
          and set(_truth.STATUS_ZH) >= {_truth.LIVE_OBSERVED, _truth.STALE,
                                        _truth.UNKNOWN, _truth.CONFLICT}
          and "def health_of(" in _truth_source
          and "def _set_health(" in _panel_source)
    check("gui: the health words are the operator's six and no others",
          {word for word in
           (v.split(" ", 1)[-1] for v in _panel.DOT_TEXT.values())}
          <= {"正常", "工作中", "等待", "降级", "异常", "未确认"}
          and len(_panel.DOT_TEXT) == 6
          and "def health_of(" in _truth_source
          and all(
              _truth.health_of(_truth.TruthValue(name="x", value=text))[0]
              in {"正常", "工作中", "等待", "降级", "未确认", "异常"}
              for text in ("", "研发中", "等待下一轮", "fallback 用了", "有问题")
          ))
    check("gui: MAA is graded on what ran, never on the config flag alone",
          "def maa_state(" in _truth_source
          and "已启用但最近没有真实执行" in _truth_source
          and "已关闭" in _truth_source
          and "降级到 ADB" in _truth_source
          and 'self._set_health("dot_maa", report.by_name("maa_state"))' in _panel_source)
    check("gui: 'why is nothing moving' is answerable from the window",
          "def why_idle(" in _truth_source
          and "UNEXPLAINED_IDLE" in _truth_source
          and '"why_idle"' in _panel_source
          and "现在为什么不动" in _panel_source)
    check("gui: action progress and goal progress are shown apart",
          "def _progress_line(" in _panel_source
          and "无目标进展" in _panel_source
          and "goal_progress" in _panel_source)
    check("gui: the attention centre exists and heals itself",
          "def anomalies(" in _truth_source
          and "auto_recovered" in _truth_source
          and "def needs_attention(" in _truth_source
          and '"attention"' in _panel_source
          and "需要关注" in _panel_source)
    check("gui: watchdog separates current health from a lifetime counter",
          "ROUND_GAP_SECONDS" in _truth_source
          and "轮次之间" in _truth_source
          and "历史累计重启" in _truth_source
          and "重启：UNKNOWN" in _truth_source)
    check("gui: the twelve flat tabs are grouped under the operator's headings",
          "TAB_GROUP" in _panel_source
          and "运行·任务" in _panel_source
          and "能力·覆盖" in _panel_source
          and "证据·日志" in _panel_source)
    check("gui: debug furniture is off until asked for",
          "vision_debug" in _panel_source
          and "视觉调试" in _panel_source
          and "if debug:" in _panel_source)
    check("gui: one window owns the clock; a second one opens read-only",
          "def panel_clock_owner(" in _panel_source
          and "def observes_only(" in _panel_source
          and "PANEL_CLOCK_MAX_AGE_SECONDS" in _panel_source
          and _panel_source.count("observes_only(self)") >= 4
          and "else:\n            self.pump.start()" in _panel_source)
    check("gui: the window grades the gateway, never the job's last known state",
          "def gateway_health(" in _truth_source
          and 'self._set_health("dot_wb", report.by_name("gateway_health"))' in _panel_source
          and "不能" in _truth_source
          and "def gateway_probe_path(" in _panel_source
          and "path = gateway_probe_path()" in _panel_source
          and '"consecutive_failures"' in _panel_source)
    check("gui: a timing-out gateway backs off instead of being retried flat out",
          "GATEWAY_BACKOFF" in _panel_source
          and "self._gateway_next_at" in _panel_source
          and "30.0, 60.0, 120.0, 300.0" in _panel_source)
    check("truth: an activity record is graded by its own window, and history is not current",
          "def events(" in _truth_source
          and "def legacy_event_row(" in _truth_source
          and "planner_usable" in _truth_source
          and "当前活动尚未实时确认" in _truth_source
          and "legacy_event_row_for(" in _panel_source
          and "历史参考（不参与当前 Planner）" in _panel_source)
    check("truth: the role headline refuses a value that is not current",
          "def headline(" in _truth_source
          and "def last_known(" in _truth_source
          and 'self.values["role"].set(role.headline)' in _panel_source
          and "Last Known：" in _panel_source)
    check("truth: AUTO is graded on work, not on the legacy in-process flags",
          "def auto_state(" in _truth_source
          and "AUTO_WORKING_SECONDS" in _truth_source
          and "上一代" in _truth_source
          and "本轮之间" in _truth_source)
    check("truth: a released lease is history, not an orphan",
          "if self.released_at is not None:\n            return False" in
          (PKG / "device_lease.py").read_text(encoding="utf-8")
          and "VALIDATION_LEASE_ORPHANED" in _truth_source
          and "expired_unreleased" not in _truth_source)
    check("gui: the operator's eight words come from one mapping",
          "CATEGORY_OF" in _truth_source
          and set(_truth.STATUS_RANK) <= set(_truth.CATEGORY_OF))
    check("gui: a switch never renders its state as a cross",
          "def policy_toggle_label(" in _panel_source
          and "ttk.Checkbutton(grid, text=name" not in _panel_source
          and "def _toggle_policy(" in _panel_source)
    check("gui: every background process goes through one hidden-window runner",
          (PKG / "winproc.py").is_file()
          and "def hidden_kwargs(" in (PKG / "winproc.py").read_text(encoding="utf-8")
          and "STARTF_USESHOWWINDOW" in (PKG / "winproc.py").read_text(encoding="utf-8")
          and "def run_shell(" in (PKG / "winproc.py").read_text(encoding="utf-8")
          and not unhidden_process_calls())
    check("gui: the top bar grades the gateway, and the job is only its last known state",
          "def workbuddy_header(" in _panel_source
          and 'self.values["workbuddy"].set(workbuddy_header(gateway))' in _panel_source
          and "下一次探测" in _panel_source
          and "最后成功" in _panel_source)
    check("truth: a hidden subprocess cannot raise on this locale's console output",
          "OEM_ENCODING = \"oem\"" in (PKG / "winproc.py").read_text(encoding="utf-8")
          and 'errors": "replace"' in (PKG / "winproc.py").read_text(encoding="utf-8"))
    check("gui: an independent verifier checks every field against its source",
          (ROOT / "tools/gui_wiring_verify.py").is_file()
          and "WIRING" in (ROOT / "tools/gui_wiring_verify.py").read_text(encoding="utf-8")
          and "the panel and the verifier must read one report"
          in (ROOT / "tools/gui_wiring_verify.py").read_text(encoding="utf-8"))
    check("knowledge: calibration fixes differences instead of discarding the prior",
          "def prior_vs_live_diff(" in _knowledge_source
          and "PRIOR_VS_LIVE_DIFF" in _knowledge_source
          and "def calibrate(" in _knowledge_source)
    check("knowledge: the loop ends by naming the next capability",
          "def completion_hook(" in _bootstrap_source
          and "def _next_after(" in _bootstrap_source
          and "NEXT_SELECTED" in _bootstrap_source
          and "knowledge_updated" in _queue_source)
    check("knowledge: only a dispatched job advances a capability's state",
          _bootstrap_source.count("sent = dispatched.startswith(\"job dispatched\")") == 2
          and "PENDING_RESEARCH if sent else" in _bootstrap_source
          and "if sent else \"\"" in _bootstrap_source)
    check("knowledge: a degraded capability is refused as a repair, not preloaded",
          "DEGRADED_MIN_FAILURES = 2" in _bootstrap_source
          and "CLASS_DEGRADED" in _bootstrap_source
          and 'return "DEGRADED"' in _bootstrap_source)
    check("knowledge: a real failure merges into the running job instead of a second one",
          "def _merge_into_active_job(" in _queue_source
          and "MERGED_INTO_ACTIVE_JOB" in _queue_source
          and "evidence_appended" in _queue_source
          and "priority_raised" in _queue_source
          and 'if record.origin == "bootstrap":' in _queue_source
          and "record.key == candidate.signature.key" in _queue_source)
    check("knowledge: one capability can never have two jobs, whatever the signature key",
          "is the same capability as" in _queue_source
          and "must not have two jobs" in _queue_source
          and "and capability in {other.capability, other.skill}" in _queue_source
          and "other.key != candidate.signature.key" in _queue_source)
    check("knowledge: coverage is reported over the unlocked subset, with definitions",
          "def coverage(" in _bootstrap_source
          and '"unlocked": tally(unlocked)' in _bootstrap_source
          and '"definitions"' in _bootstrap_source
          and "external_share" in _bootstrap_source)

    # -- the device hand-off for a version waiting to be examined -----------
    check("lease: the queue asks for the device for a version waiting to be examined",
          "def validation_lease_target(" in _queue_source
          and "def service_validation_lease(" in _queue_source
          and 'event": "validation_lease_requested"' in _queue_source.replace("'", '"'))
    check("lease: it refuses to ask when nobody could drive the validation",
          "def validation_lease_consumer(" in _queue_source
          and "PANEL_HEARTBEAT_MAX_AGE_SECONDS" in _queue_source
          and 'validation_lease_deferred' in _queue_source
          and "would make V2 stand down with nobody to drive" in _queue_source)
    check("lease: the device always goes back, and only for its own record",
          "def release_validation_lease(" in _queue_source
          and "expect_key" in _queue_source
          and "if record.state == LIVE_VERIFY_PENDING:" in _queue_source
          and "expect_key=record.key" in _queue_source)
    check("lease: the window is the consumer that drives it, and bounded",
          "VALIDATION_MAX_ACTIONS" in _panel_source
          and "def _maybe_validate(self)" in _panel_source
          and "def _run_validation_worker(self" in _panel_source
          and '"--goal", goal' in _panel_source
          and "self._release_validation_lease(result," in _panel_source)

    print("\n-- dangling self-call sites (the 0aw class) --")
    for label, detail in dangling_self_calls():
        check(label, False, detail)
    check("no dangling self-call sites", not dangling_self_calls())

    print("\n-- background processes started without the hidden-window runner --")
    for label, detail in unhidden_process_calls():
        print("    ", label, "|", detail)
    check("no unhidden or shell background process in the GUI/AUTO path",
          not unhidden_process_calls())

    for label, detail in reached_tools():
        print("    ", label, "|", detail)
    check("no human-terminal exemption is imported by the code",
          not reached_tools())

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

    print("\n-- the derived navigation matrix --")
    # `knowledge/ui/navigation_matrix.json` is a projection of the registry, so the way it rots is
    # by going stale or by the operator-function queries silently matching nothing after a rename.
    # Both are checked here rather than trusted: a stale projection is worse than no projection,
    # because a reader takes it for the current state of the tree.
    try:
        import importlib.util as _ilu

        _spec = _ilu.spec_from_file_location("ui_navigation_matrix", ROOT / "tools" / "ui_navigation_matrix.py")
        _mod = _ilu.module_from_spec(_spec)
        assert _spec and _spec.loader
        _spec.loader.exec_module(_mod)
        _fresh = _mod.build()
        _committed_path = ROOT / "knowledge" / "ui" / "navigation_matrix.json"
        _committed = json.loads(_committed_path.read_text(encoding="utf-8"))
        check("ui: the committed navigation matrix matches a fresh projection of the registry",
              _committed["counts"] == _fresh["counts"],
              f"committed={_committed['counts']} fresh={_fresh['counts']} -- rerun "
              f"tools/ui_navigation_matrix.py")
        _skills = [e["skill"] for e in _fresh["entries"]]
        check("ui: every registered skill appears in the matrix exactly once",
              len(_skills) == len(set(_skills)) and len(_skills) == len(registry.all()),
              f"{len(_skills)} rows for {len(registry.all())} skills")
        # The functions the operator named whose paths DO exist must keep resolving.  A rename that
        # quietly drops one to zero would otherwise read as "nothing was ever there".
        _covered = {"情报/灯塔", "兵营/盾兵-矛兵-射手", "邮件", "城镇/野外快捷面板", "体力HUD"}
        _zeroed = [
            f["function"] for f in _fresh["operator_functions"]
            if f["function"] in _covered and f["path_count"] == 0
        ]
        check("ui: the operator functions that had paths still have them",
              not _zeroed, f"went to zero: {_zeroed}")
        # And the ones known to be absent stay visible as absent rather than being quietly dropped.
        _absent = {f["function"] for f in _fresh["operator_functions"] if f["path_count"] == 0}
        check("ui: the functions with no path are still reported, not silently omitted",
              "巨兽/自动加入" in {f["function"] for f in _fresh["operator_functions"]},
              f"absent today: {sorted(_absent)}")
    except Exception as exc:  # noqa: BLE001 - a broken generator must be reported, not swallowed
        check("ui: the navigation matrix generator runs", False, f"{type(exc).__name__}: {exc}")

    print(f"\nproblems: {len(problems)}")
    for name in problems:
        print("  -", name)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
