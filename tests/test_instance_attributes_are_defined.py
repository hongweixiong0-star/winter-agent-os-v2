"""Every ``self.X`` read must resolve to something that defines it.

Why this file exists (measured 2026-09-30, 03:52):

    File "winter_agent_v2/runtime.py", line 7302, in run
        and self._training_continuation_goal == best_goal.goal_id
    AttributeError: 'LiveRuntime' object has no attribute '_training_continuation_goal'

    Commit ``015e4f2`` ported the two *read* sites of a focused-camp retry into
    ``runtime.py`` but not the ``__init__`` assignment (that name was later folded
    into ``self._committed_goal``).  Nothing ever created the attribute, so the
    first focused training camp whose action bar failed to prove raised.  Training
    camps are a core daily goal, so AUTO crashed nearly every round: the panel
    logged ``本轮结束：暂无结构化结果`` and produced zero episodes for 5.4 hours.

``tools/check_wiring.py`` already audits *dangling calls* (``self.X()`` with no
definition) and it did not catch this, because this was a dangling *read* on a
plain attribute comparison.  That is the gap this file closes.

The audit is deliberately static: an attribute that is read but never assigned is
a defect the moment the branch is reached, and reaching it costs a production run.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "winter_agent_v2"

# The file whose dangling read crashed production.  Held to zero, with no allowlist.
STRICT_FILES = ("winter_agent_v2/runtime.py",)

# Known debt elsewhere in the package, discovered by running this same audit.
# Each entry is (attribute, why it is still here).  Fixing one means deleting its
# entry here -- the ledger test fails on a stale or missing entry by construction.
KNOWN_DANGLING = set()


def _dangling_reads(path: Path) -> list[tuple[str, int]]:
    """``self.X`` reads that nothing in the file defines.

    Counted as defining: ``self.X = ...`` / ``self.X: T = ...`` anywhere in the
    file, class-body names (an instance reads a class attribute through
    ``self``), method names, and explicit ``getattr(self, "X", ...)`` /
    ``setattr(self, "X", ...)`` guards.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined: set[str] = set()
    read: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    targets = item.targets
                elif isinstance(item, ast.AnnAssign):
                    targets = [item.target]
                else:
                    targets = []
                for target in targets:
                    for inner in ast.walk(target):
                        if isinstance(inner, ast.Name):
                            defined.add(inner.id)
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined.add(item.name)

        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id != "self":
                continue
            if isinstance(node.ctx, ast.Store):
                defined.add(node.attr)
            elif isinstance(node.ctx, ast.Load):
                read.setdefault(node.attr, node.lineno)

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"getattr", "setattr"} and len(node.args) >= 2:
                owner, name = node.args[0], node.args[1]
                if (isinstance(owner, ast.Name) and owner.id == "self"
                        and isinstance(name, ast.Constant)):
                    defined.add(str(name.value))

    return sorted(
        ((attr, line) for attr, line in read.items()
         if attr not in defined and not attr.startswith("__")),
        key=lambda item: item[1],
    )


class TheRetiredTrainingContinuationNameIsGone(unittest.TestCase):
    """Pins the exact defect: a name from a superseded design must not come back."""

    def test_runtime_does_not_read_the_retired_name(self):
        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("_training_continuation_goal", source)

    def test_the_route_identity_is_the_committed_goal(self):
        """The camp route carries ``_committed_goal`` -- the name that IS assigned."""
        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("self._committed_goal == expected_goal", source)
        self.assertIn("self._committed_goal == best_goal.goal_id", source)


class RuntimeReadsOnlyWhatItDefines(unittest.TestCase):

    def test_runtime_has_no_dangling_reads(self):
        findings = {f"{Path(f).name}:self.{attr}": line
                    for f in STRICT_FILES
                    for attr, line in _dangling_reads(ROOT / f)}
        self.assertEqual(findings, {}, f"dangling self reads in runtime.py: {findings}")


class ThePackageLedgerMatchesTheAudit(unittest.TestCase):
    """New dangling reads fail the build; fixed ones must leave the ledger."""

    def test_ledger_is_exactly_the_live_findings(self):
        live = {f"{path.name}:self.{attr}"
                for path in sorted(PACKAGE.glob("*.py"))
                for attr, _line in _dangling_reads(path)}
        self.assertEqual(
            live, KNOWN_DANGLING,
            "the dangling-read ledger is stale: "
            f"new={sorted(live - KNOWN_DANGLING)} fixed={sorted(KNOWN_DANGLING - live)}",
        )


if __name__ == "__main__":
    unittest.main()
