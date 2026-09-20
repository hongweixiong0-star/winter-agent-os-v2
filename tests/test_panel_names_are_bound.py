"""The panel's refresh path must not use a name it never binds.

Real failure, 2026-09-20: `_narrate_pump` computed `development = view.get("current")` while `view`
was never assigned in that method.  Two sibling refreshes do `view = escalation_view()`; this one had
lost the line, so the name resolved to nothing.  The NameError did not surface, because the block sits
inside a `try` with a broad `except` -- the consistency card therefore failed on every single refresh
and reported nothing, which is the exact shape of silence this panel exists to prevent.

That is why the check is static and specific rather than a call-the-method smoke test: constructing
the window needs Tk, the failure is invisible at runtime by design, and the defect is a *missing line*
-- so the only honest guard is to read the code and ask whether every name it uses is bound.

Scope is deliberately one method plus its module-level context, because that is where the defect was
and a whole-file reachability analysis is a linter's job, not a test's.  `pyflakes` found this in one
run; this test keeps the answer from regressing without adding a linter dependency to the suite.
"""

from __future__ import annotations

import ast
import builtins
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PANEL = ROOT / "tools/control_panel.py"

#: The method that broke, and the two siblings that show the missing line was not a design choice.
WATCHED = ("_narrate_pump", "_refresh_runtime_snapshot", "_refresh_learning")


def _bound_names(module: ast.Module) -> set[str]:
    names = set(dir(builtins))
    for node in module.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
            # a module-level conditional import still binds the name
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    for alias in inner.names:
                        names.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(inner, ast.Assign):
                    for target in inner.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    return names


def _locally_bound(function: ast.AST) -> set[str]:
    names: set[str] = set()
    args = getattr(function, "args", None)
    for group in (getattr(args, "posonlyargs", []), getattr(args, "args", []),
                  getattr(args, "kwonlyargs", [])):
        names.update(a.arg for a in group)
    if getattr(args, "vararg", None):
        names.add(args.vararg.arg)
    if getattr(args, "kwarg", None):
        names.add(args.kwarg.arg)
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            for inner in ast.walk(node.target):
                if isinstance(inner, ast.Name):
                    names.add(inner.id)
    return names


class NoNameIsUsedBeforeItIsBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PANEL.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.module_names = _bound_names(cls.tree)

    def test_the_panel_module_is_readable(self):
        self.assertTrue(PANEL.is_file())
        self.assertIn("class ControlPanel", self.source)

    def test_the_watched_methods_use_only_names_they_bind_or_import(self):
        for name in WATCHED:
            with self.subTest(method=name):
                function = next(
                    (n for n in ast.walk(self.tree)
                     if isinstance(n, ast.FunctionDef) and n.name == name), None)
                self.assertIsNotNone(function, f"{name} not found in {PANEL.name}")
                available = self.module_names | _locally_bound(function)
                used = {n.id for n in ast.walk(function)
                        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                unbound = sorted(used - available)
                self.assertEqual(
                    unbound, [],
                    f"{name} uses names it never binds: {unbound} -- this is how the consistency "
                    f"card failed silently on every refresh",
                )

    def test_the_consistency_block_can_see_the_view_it_reads(self):
        """The specific line, pinned by name so the reason travels with it."""
        function = next(n for n in ast.walk(self.tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "_narrate_pump")
        body = ast.get_source_segment(self.source, function) or ""
        self.assertIn("view = escalation_view()", body,
                      "the development view must be folded here, as its sibling refreshes do")
        self.assertIn('development = view.get("current")', body)


if __name__ == "__main__":
    unittest.main()
