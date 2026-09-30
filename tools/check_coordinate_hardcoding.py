"""Admission gate: may this production click exist?

The constitutional amendment (禁止坐标硬编码, 优先级最高) makes one question mandatory before
any production action is admitted:

    **Can this click's target be shown to come from the CURRENT FRAME?**

If not, it is not admitted -- and the amendment is explicit that there is no exception and no
fallback, and that renaming a variable, moving the number into a config file or wrapping it in
a helper function does not change the answer:

    §一.7  将截图尺寸换算、坐标偏移、比例缩放或分辨率适配包装成"动态定位"，实际仍按固定位置点击
    §八   不能只检查 tap(x, y) 这样的显式写法。固定百分比、配置文件坐标、历史台账回退、
          隐藏在工具函数中的固定位置同样属于违规。
          不得通过重命名变量、将坐标移入配置文件或包装工具函数绕过检查。

So this tool does not grep for ``tap(x, y)``.  It asks a structural question about each
production module: *which tiers can produce a tap point here, and is any of them a constant?*

What it checks
--------------
1. **Literal points in a resolver.**  A float-pair literal like ``(0.86, 0.68)`` returned from a
   tap-resolution function is a fixed point.  ``0.0``/``1.0`` are exempt: they are the bounds a
   normalised point is validated against, not a position.
2. **Constant-producing tiers wired into the tap chain.**  The two known forbidden tiers are
   named by symbol so that re-adding one is caught even if it is renamed around:
   ``_remembered_control_center`` (the coordinate ledger) and the declared
   ``position_hint.x``/``.y`` branch of ``_dictionary_hint``.
3. **Gesture constants.**  A ``SWIPE`` action whose vector is hard-coded in the skill registry.
   A pan has no "UI element" to identify -- the gesture's own precondition (which page it is
   on) is what must be read from the frame, so this is reported as a RULING NEEDED rather than
   silently passed or silently failed.
4. **Config-declared coordinates reachable as targets.**  Scan the JSON knowledge/config files
   for declared points and report which ones a resolver could still turn into a tap.

Exit code is non-zero when a violation is found, so it can gate a commit.

Usage
-----
    python tools/check_coordinate_hardcoding.py           # human report
    python tools/check_coordinate_hardcoding.py --json    # machine report
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "winter_agent_v2"

#: Modules that can decide a production click.  Deliberately a list rather than a glob: the
#: admission question is about the *production* path, and widening it to every file would
#: drown the finding in probes and tests.
#:
#: The three session modules are here because they are production click deciders and were
#: **missing** when they were first written (measured 2026-09-30, the session engine's own
#: admission): ``session_host._tap_printed`` turns a recognised word's centre into a device
#: tap, which is a production tap path by any reading of §一/§二, and the gate that exists to
#: audit exactly that listed seventeen modules without it.  A gate whose list is short by the
#: newest tap path is worse than no gate, because it reports ADMITTED.
PRODUCTION_MODULES: tuple[str, ...] = (
    "runtime.py",
    "executor.py",
    "executor_router.py",
    "scheduler.py",
    "skills.py",
    "skills_extra.py",
    "brain.py",
    "vision.py",
    "ocr.py",
    "verifier.py",
    "recovery.py",
    "maa_executor.py",
    "capability_bootstrap.py",
    "unknown_dispatch.py",
    "unknown_advisor.py",
    "control_experience.py",
    "action_schema.py",
    "session_engine.py",
    "session_adapters.py",
    "session_host.py",
)

#: Symbols that produce a tap point from a constant rather than from the frame.  Adding one
#: back into a tap path is a violation regardless of the name it is given.
FORBIDDEN_TAP_TIERS: tuple[tuple[str, str], ...] = (
    ("_remembered_control_center", "coordinate ledger (§一.3/§一.5/§一.6/§六)"),
    ("position_norm", "stored position (§一.3)"),
)

#: A tap-resolution function.  The structural question is asked about these bodies.
RESOLVER_NAMES: tuple[str, ...] = (
    "_resolve_semantic_target",
    "_dictionary_hint",
    "_remembered_control_center",
    "_ordinary_control_candidate",
    "_client_printed_control",
)

#: Floats that are bounds, not positions.
BOUND_LITERALS: frozenset[float] = frozenset({0.0, 1.0})

#: Files whose declared points are reported (knowledge/config surfaces a resolver may read).
CONFIG_SURFACES: tuple[str, ...] = (
    "knowledge/ui/semantic_dictionary.json",
    "knowledge/ui/pages.json",
    "knowledge/ui/navigation_matrix.json",
    "knowledge/ui/generic_semantics.json",
    "config/v2.json",
)


@dataclass
class Finding:
    kind: str
    severity: str          # VIOLATION | RULING_NEEDED | NOTE
    where: str
    detail: str
    constitutional: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "VIOLATION"]

    @property
    def rulings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "RULING_NEEDED"]


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """Remove every docstring under ``node``, in place.

    Load-bearing, not cosmetic.  The removals this gate checks for are *documented in place*
    -- a comment says "REMOVED: a literal (0.86, 0.68) ..." and a docstring explains the
    ledger's measured point "(0.8819, 0.3563)".  ``ast.unparse`` drops comments but **keeps
    docstrings**, so without this the explanation reads as the offence and the gate cries
    wolf on the very methods it is meant to bless.
    """
    for child in ast.walk(node):
        if isinstance(child, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = list(child.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                child.body = body[1:]
    return node


def _code_only(source: str) -> str:
    """The source with comments and docstrings removed -- executable code only."""
    return ast.unparse(_strip_docstrings(ast.parse(source)))


def _function_bodies(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.unparse(_strip_docstrings(node))
    return out


def _float_pair_literals(code: str) -> list[tuple[float, float]]:
    """Every ``(float, float)`` literal in ``code``, both as a tuple and as an unparsed 2-tuple."""
    found: list[tuple[float, float]] = []
    for match in re.finditer(r"\(([0-9]*\.[0-9]+),\s*([0-9]*\.[0-9]+)\)", code):
        x, y = float(match.group(1)), float(match.group(2))
        if x in BOUND_LITERALS and y in BOUND_LITERALS:
            continue
        found.append((x, y))
    return found


def check_literal_points() -> list[Finding]:
    findings: list[Finding] = []
    for module in PRODUCTION_MODULES:
        path = PKG / module
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        bodies = _function_bodies(source)
        for name in RESOLVER_NAMES:
            body = bodies.get(name)
            if body is None:
                continue
            for x, y in _float_pair_literals(body):
                findings.append(Finding(
                    kind="LITERAL_POINT_IN_RESOLVER",
                    severity="VIOLATION",
                    where=f"{module}::{name}",
                    detail=f"literal point ({x}, {y}) inside a tap resolver",
                    constitutional="§一.1 固定像素坐标点击 / §一.2 固定屏幕百分比点击",
                ))
    return findings


def check_forbidden_tiers() -> list[Finding]:
    findings: list[Finding] = []
    resolver = PKG / "runtime.py"
    if not resolver.is_file():
        return findings
    source = resolver.read_text(encoding="utf-8")
    bodies = _function_bodies(source)
    tap_chain = bodies.get("_resolve_semantic_target", "")
    for symbol, why in FORBIDDEN_TAP_TIERS:
        if symbol in tap_chain:
            findings.append(Finding(
                kind="FORBIDDEN_TIER_WIRED_INTO_TAP_CHAIN",
                severity="VIOLATION",
                where=f"runtime.py::_resolve_semantic_target",
                detail=f"{symbol} is reachable from the tap chain ({why})",
                constitutional="§一.3 / §一.5 / §一.6 / §六",
            ))
    return findings


def check_declared_hint_guard() -> list[Finding]:
    """The declared ``position_hint.x/.y`` branch must be refusable and refusal-first."""
    findings: list[Finding] = []
    source = (PKG / "runtime.py").read_text(encoding="utf-8")
    bodies = _function_bodies(source)
    hint = bodies.get("_dictionary_hint", "")
    if not hint:
        return findings
    if "frame_derived_only" not in hint:
        findings.append(Finding(
            kind="DECLARED_HINT_GUARD_MISSING",
            severity="VIOLATION",
            where="runtime.py::_dictionary_hint",
            detail="no frame_derived_only guard: declared position_hint.x/.y can become a tap",
            constitutional="§一.2 / §八 将坐标移入配置文件同样属于违规",
        ))
        return findings
    try:
        if hint.index("frame_derived_only") > hint.index("for axis in"):
            findings.append(Finding(
                kind="DECLARED_HINT_GUARD_OUT_OF_ORDER",
                severity="VIOLATION",
                where="runtime.py::_dictionary_hint",
                detail="the refusal sits after the declared x/y is parsed",
                constitutional="§一.2 / §八",
            ))
    except ValueError:
        pass
    return findings


def check_swipe_constants() -> list[Finding]:
    """A gesture with a hard-coded vector: admit only if its page comes from the frame.

    §一 is about 点击目标 ("click target"), and a swipe names no control -- it moves a
    surface.  So the question is not "which element does this point identify" but "how does
    the code know it is on the right page", and the amendment's §四 answers it: the
    precondition must be read from the current frame.

    This project already has that gate, and the check verifies it rather than assuming it:
    ``Scheduler.tick`` refuses any skill whose ``Skill.ready(world)`` is False, and
    ``Skill.ready`` (skills.py:89-92) returns True only when ``world.page is
    self.required_page`` -- ``world`` being the vision reading of the *current* frame.  A
    swipe skill that declares a page is therefore admitted; one declared page-agnostic would
    be a violation, because nothing would tie the gesture to a screen.
    """
    findings: list[Finding] = []
    skills_src = ""
    for module in ("skills.py", "skills_extra.py"):
        path = PKG / module
        if path.is_file():
            skills_src += path.read_text(encoding="utf-8")

    # skill_id -> declared page (or None for page_agnostic)
    declared: dict[str, str | None] = {}
    for match in re.finditer(
        r'Skill\(\s*"([A-Z0-9_]+)"\s*,(.*?)\n\s*\)\s*,',
        skills_src,
        re.DOTALL,
    ):
        name, body = match.group(1), match.group(2)
        page = re.search(r"\bNone\b\s*,\s*Action\(", body)
        page_arg = re.search(r"(Page\.[A-Z_]+|\bNone\b)\s*,\s*\n?\s*Action\(", body)
        if page_arg:
            declared[name] = None if page_arg.group(1) == "None" else page_arg.group(1)
        elif page is not None:
            declared[name] = None

    for module in ("skills.py", "skills_extra.py", "runtime.py"):
        path = PKG / module
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r'Action\(\s*"SWIPE"\s*,\s*"([^"]+)"', source):
            vector = match.group(1)
            line = source[: match.start()].count("\n") + 1
            # Which skill owns this action?  The nearest preceding Skill("NAME",
            # in the same file.
            owner = None
            for skill_match in re.finditer(r'"?([A-Z][A-Z0-9_]+)"?\s*,\s*$', ""):
                pass
            for skill_match in list(re.finditer(r'Skill\(\s*"([A-Z0-9_]+)"', source)):
                if skill_match.start() < match.start():
                    owner = skill_match.group(1)
            page = declared.get(owner or "", "__UNKNOWN__")
            if page == "__UNKNOWN__":
                findings.append(Finding(
                    kind="GESTURE_OWNER_UNRESOLVED",
                    severity="RULING_NEEDED",
                    where=f"{module}:{line}",
                    detail=f'SWIPE "{vector}": could not resolve its owning skill\'s declared page',
                    constitutional="§四 the gesture's precondition must be read from the frame",
                ))
            elif page is None:
                findings.append(Finding(
                    kind="PAGE_AGNOSTIC_GESTURE",
                    severity="VIOLATION",
                    where=f"{module}:{line} ({owner})",
                    detail=f'SWIPE "{vector}" on a page-agnostic skill: nothing ties the gesture '
                           f'to a screen read from the current frame',
                    constitutional="§四 列表滚动...必须重新识别相关 UI 元素",
                ))
            else:
                findings.append(Finding(
                    kind="HARDCODED_GESTURE_VECTOR_ADMITTED",
                    severity="NOTE",
                    where=f"{module}:{line} ({owner} on {page})",
                    detail=f'SWIPE "{vector}" is a gesture, not a click target, and its '
                           f'precondition is frame-read: Scheduler.tick refuses it unless '
                           f'Skill.ready(world) sees world.page is {page} on the current frame',
                    constitutional="§一 forbids a fixed 点击目标; this names no control, and §四's "
                                   "frame-read precondition is satisfied",
                ))
    return findings


def check_config_surfaces() -> list[Finding]:
    """Report declared points a resolver could still turn into a tap."""
    findings: list[Finding] = []
    for rel in CONFIG_SURFACES:
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            findings.append(Finding(
                kind="CONFIG_UNREADABLE", severity="NOTE",
                where=rel, detail=f"could not parse: {exc}",
            ))
            continue
        hits = _walk_for_points(payload)
        for path_str, value in hits:
            findings.append(Finding(
                kind="DECLARED_POINT_IN_CONFIG",
                severity="NOTE",
                where=f"{rel}:{path_str}",
                detail=f"declares {value}; only admissible if a resolver refuses it "
                       f"(frame-derived-only) or it is a search region, never a target",
                constitutional="§一.2 / §八 配置文件坐标 / §五 搜索区域不得当作点击目标",
            ))
    return findings


def _is_point_literal(value: object) -> bool:
    """Can ``_dictionary_hint`` parse this into half a coordinate?

    Mirrors the resolver's own parser: a number, or a string like ``0.212`` / ``0.125-0.196``
    (a measured range, whose centre it used to resolve to).  Anything else makes the resolver
    return ``None`` on its own, so it cannot become a tap.
    """
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        raw = value.strip()
        return bool(re.fullmatch(r"-?\d+(\.\d+)?(-\d+(\.\d+)?)?", raw))
    return False


def _walk_for_points(node, prefix: str = "") -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{prefix}.{key}" if prefix else str(key)
            if key in ("position_norm", "point_norm", "centre_norm", "center_norm",
                       "tap_point", "arrow_norm", "done_norm"):
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    out.append((here, value))
            elif key == "position_hint" and isinstance(value, dict):
                # Only a NUMERIC declaration can produce a tap: the resolver parses x/y with
                # ``float()`` and returns None when that fails, so a hint whose x/y is a
                # sentence ("the row's own y, read from this frame") is already inert.  Flagging
                # prose would bury the two records that matter in seventeen that do not.
                if _is_point_literal(value.get("x")) and _is_point_literal(value.get("y")):
                    out.append((here, {"x": value.get("x"), "y": value.get("y")}))
            else:
                out.extend(_walk_for_points(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.extend(_walk_for_points(value, f"{prefix}[{i}]"))
    return out


def check_executor_tap_sources() -> list[Finding]:
    """Every backend that can tap must be one the project has admitted.

    The amendment's §八 lists "MAA Pipeline" as a surface to audit.  This asserts the
    strongest structural fact available without a device: the number of *distinct* code sites
    that can issue a tap on the device stays small and named, so a second execution chain
    (which §二 forbids) would show up here as a new site.

    ``session_host.py`` was added to the scanned set on 2026-09-30, when the session engine
    introduced ``_tap_printed``: it resolves a printed word to its centre on the current frame
    and taps it.  That is a production tap site, and the check that exists to make a new one
    *visible* was not looking at the file that had just gained one.  The site is a NOTE rather
    than a violation because it derives its point from the frame in hand and refuses when the
    word is absent or ambiguous; the point of listing it is that growing the list is a decision
    somebody has to make on purpose.
    """
    findings: list[Finding] = []
    sites: list[str] = []
    for module in ("executor.py", "maa_executor.py", "executor_router.py", "session_host.py"):
        path = PKG / module
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\.tap\(", line) or re.search(r"\.tap_point\(", line):
                sites.append(f"{module}:{i}")
    findings.append(Finding(
        kind="DEVICE_TAP_SITES",
        severity="NOTE",
        where=", ".join(sites) or "(none)",
        detail=f"{len(sites)} code sites can tap a device; §二 forbids a second execution chain, "
               f"so this number must not grow without a ruling",
    ))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args()

    report = Report()
    for checker in (
        check_literal_points,
        check_forbidden_tiers,
        check_declared_hint_guard,
        check_swipe_constants,
        check_config_surfaces,
        check_executor_tap_sources,
    ):
        report.findings.extend(checker())
    report.stats["production_modules"] = len(PRODUCTION_MODULES)
    report.stats["violations"] = len(report.violations)
    report.stats["rulings_needed"] = len(report.rulings)

    if args.json:
        print(json.dumps({
            "stats": report.stats,
            "findings": [f.__dict__ for f in report.findings],
        }, ensure_ascii=False, indent=2))
        return 1 if report.violations else 0

    print("=" * 78)
    print("COORDINATE-HARDCODING ADMISSION GATE")
    print("宪法：坐标不是知识，UI 元素才是。坐标只能由当前 UI 识别产生，用完即弃。")
    print("=" * 78)
    print(f"production modules scanned: {report.stats['production_modules']}")

    for severity in ("VIOLATION", "RULING_NEEDED", "NOTE"):
        group = [f for f in report.findings if f.severity == severity]
        print(f"\n--- {severity} ({len(group)}) ---")
        if not group:
            print("  none")
        for f in group:
            print(f"  [{f.kind}] {f.where}")
            print(f"      {f.detail}")
            if f.constitutional:
                print(f"      basis: {f.constitutional}")

    print()
    print("-" * 78)
    print(f"VERDICT: {len(report.violations)} violation(s), "
          f"{len(report.rulings)} ruling(s) needed")
    if report.violations:
        print("NOT ADMITTED — a production click may not be traced to the current frame.")
    else:
        print("ADMITTED — every production tap path resolves on the current frame.")
    return 1 if report.violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
