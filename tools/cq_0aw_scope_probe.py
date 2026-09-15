"""WB-0AW evidence: how noisy is the resolver if it also covers tools/ and tests/?

The existing checker only walks winter_agent_v2/.  Every session adds new code to
tools/ and tests/ instead, and neither has ever been swept for the 0aw class of
bug (a call site that resolves to no definition, invisible to import and pytest
alike).  Before extending the scope, measure what the existing analyzer says
about those two directories -- an analyzer that reports noise gets disabled.

Read-only.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("_cw", ROOT / "tools/check_wiring.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    sys.path.insert(0, str(ROOT))
    cw = load()
    real_pkg = cw.PKG

    for name in ("winter_agent_v2", "tools", "tests"):
        d = ROOT / name
        if not d.exists():
            print("%-18s MISSING" % name)
            continue
        py = sorted(p for p in d.glob("*.py") if not p.name.startswith("_pt"))
        cw.PKG = d
        self_hits = cw.dangling_self_calls()
        mod_hits = cw.dangling_module_calls()
        print(
            "%-18s files=%-4d self_hits=%-4d module_hits=%-4d"
            % (name, len(py), len(self_hits), len(mod_hits))
        )
        for label, detail in (self_hits + mod_hits)[:25]:
            print("     -", label, "|", detail)

    cw.PKG = real_pkg
    print()
    print("restored PKG =", cw.PKG)


if __name__ == "__main__":
    main()
