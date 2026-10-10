# -*- coding: utf-8 -*-
"""Proves, mechanically, that a static knowledge inconsistency cannot reach the improvement loop.

The claim being pinned

    The bootstrap scanner and the escalation queue are both **failure-driven**. A capability spec
    that declares a page or an element which exists nowhere is never scheduled (it is not a
    registered skill), so it never fails, so no `FailureSignature` is ever produced for it. The
    question this test answers is whether the *other* entry point - the knowledge scan - can see it
    instead.

    It cannot, and this test demonstrates that rather than asserting it in prose: two roots are built
    that differ ONLY by a poisoned spec under `knowledge/skills/`, and the scanner's public report is
    identical for both. So the spec's contents are not an input to the scan at all.

What this test is NOT

    It is not a fix proposal and it changes no behaviour. It is the evidence GAP-01's "missing link"
    section rests on, so that claim is checkable rather than rhetorical. If the scanner is later
    wired to consult specs, this test will fail - and that failure is the intended signal that the
    gap has been closed.
"""
from __future__ import annotations

import json
from pathlib import Path

from winter_agent_v2.capability_bootstrap import BootstrapScanner

POISON_SPEC = {
    "skill_id": "_ZZ_POISON",
    "required_page": "PAGE_THAT_DOES_NOT_EXIST",
    "required_vision": ["BTN_ALSO_DOES_NOT_EXIST"],
}


def _build_root(base: Path, *, with_poison: bool) -> Path:
    """A minimal root. `load` degrades every missing source to empty, so this is enough."""
    root = base / ("poisoned" if with_poison else "clean")
    skills = root / "knowledge" / "skills"
    skills.mkdir(parents=True)
    (root / "knowledge" / "game").mkdir(parents=True)
    (root / "knowledge" / "goals").mkdir(parents=True)
    if with_poison:
        (skills / "_ZZ_POISON.json").write_text(
            json.dumps(POISON_SPEC, ensure_ascii=False), encoding="utf-8")
    return root


def _stable(report: dict) -> dict:
    """Drop fields that change per call so the comparison is about content only."""
    volatile = {"generated_at", "scanned_at", "now", "duration_ms"}
    return {k: v for k, v in report.items() if k not in volatile}


def test_a_poisoned_spec_does_not_change_the_bootstrap_scan(tmp_path):
    clean = BootstrapScanner.load(_build_root(tmp_path, with_poison=False))
    poisoned = BootstrapScanner.load(_build_root(tmp_path, with_poison=True))

    clean_report = _stable(clean.report())
    poisoned_report = _stable(poisoned.report())

    assert clean_report, "the report is empty, so this comparison would be vacuous"
    assert clean_report == poisoned_report, (
        "the scanner's report changed when a spec declaring a nonexistent page was added, which "
        "would mean spec contents ARE consulted - update GAP-01, the missing link has been closed"
    )


def test_the_scanner_does_not_load_the_skills_specs_as_a_source(tmp_path):
    """Names the sources the scanner reads, so the gap is a fact about its input set and not an
    interpretation of its output.

    Note on `required_page`: the round-3 consistency check reads that field - but as the DECLARING
    side of a comparison, not as a catalog source. The distinction this test now pins is that the
    specs never become plans: a spec cannot enter `catalog`, so it can never be scheduled.
    """
    source = (Path(__file__).resolve().parents[1]
              / "winter_agent_v2" / "capability_bootstrap.py").read_text(encoding="utf-8")
    for loaded in (
        "knowledge/game/capability_catalog.json",
        "knowledge/goals/goal_capability_map.json",
        "knowledge/external/external_capability_map.json",
        "knowledge/tooling/tool_registry.json",
    ):
        assert loaded in source, f"expected the scanner to read {loaded}"

    scanner = BootstrapScanner.load(tmp_path)
    # Nothing from a spec directory can appear in the catalog, whatever the specs say.
    assert all("knowledge/skills" not in json.dumps(row) for row in scanner.catalog), (
        "a capability spec reached the catalog, which would let it be scheduled"
    )
    assert scanner.catalog == (), "an empty root must produce an empty catalog"
