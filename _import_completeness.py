"""Is the tree that gets shipped import-complete?

A repin does `git checkout` of code only, so anything untracked stays in the dev tree and never
reaches the pin tree.  If a *tracked* module imports an *untracked* one, the pin tree ships a
package that cannot import -- and nothing in the current gates notices, because check_wiring works
on the dev tree and the dev tree has the file.

Measures: for every tracked .py under winter_agent_v2/ and tools/, every first-party import target,
and whether that target is tracked.  Read-only.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = "winter_agent_v2"


def tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}


tracked = tracked_files()
print("tracked files:", len(tracked))

sources = sorted(p for p in tracked if p.startswith((f"{PKG}/", "tools/")) and p.endswith(".py"))
print("tracked sources scanned:", len(sources))

untracked_present = []
for path in ROOT.rglob("*.py"):
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith(("out/", "out12", "__pycache__")) or "/__pycache__/" in rel:
        continue
    if rel.startswith((f"{PKG}/", "tools/")) and rel not in tracked:
        untracked_present.append(rel)
print("untracked .py sitting inside the package or tools/:", len(untracked_present))
for rel in sorted(untracked_present):
    print("   ", rel)


def first_party_target(node: ast.AST, current: str) -> str | None:
    """`winter_agent_v2.X` or the relative `.X` resolved against the importing file."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == PKG or alias.name.startswith(PKG + "."):
                return alias.name
        return None
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            base = Path(current).parent
            for _ in range(node.level - 1):
                base = base.parent
            parts = [*base.parts, *(node.module.split(".") if node.module else [])]
            return "/".join(parts)
        if node.module and (node.module == PKG or node.module.startswith(PKG + ".")):
            return node.module
    return None


def resolves(target: str | None, current: str) -> tuple[bool, str]:
    if not target:
        return True, ""
    cands = [f"{target}.py", f"{target}/__init__.py"]
    if target.endswith(PKG):
        cands += [f"{PKG}/__init__.py"]
    for cand in cands:
        cand = cand.replace("\\", "/")
        if cand in tracked:
            return True, cand
        if (ROOT / cand).exists():
            return False, cand  # present on disk but NOT tracked -> will not ship
    return True, ""  # third-party or a name we do not own


broken: list[tuple[str, str, str]] = []
for rel in sources:
    try:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        print("   parse failed:", rel, exc)
        continue
    for node in ast.walk(tree):
        target = first_party_target(node, rel)
        if target is None:
            continue
        ok, cand = resolves(target, rel)
        if not ok:
            broken.append((rel, target, cand))

print()
if broken:
    print("SHIPPED-TREE IMPORTS THAT WOULD NOT RESOLVE:", len(broken))
    for rel, target, cand in broken:
        print("   %s\n       imports %s  ->  %s exists on disk, is not tracked" % (rel, target, cand))
else:
    print("every first-party import in the tracked tree resolves to a tracked file")
