# -*- coding: utf-8 -*-
"""Goal A: static spec drift is detected by the ORDINARY scan and reaches the EXISTING loop.

No new controller and no second queue. The three things this proves, in order:

1. the normal scan path -- ``BootstrapScanner.load(root).report()`` -- carries the drift, because
   ``report()`` now has a ``static_drift`` section fed by ``static_knowledge_drift(root)``;
2. a drifting spec that a catalog row points at via ``existing_skill`` attaches to that row's
   ``BootstrapPlan`` (a note plus the unregistered names folded into ``missing_semantics``), so it
   flows plan -> ``candidates()`` -> ``EscalationQueueAdapter.preload()`` like any other capability;
3. a synthetic bad spec is detected and, once removed, the scan returns to its previous state.

Why this exists at all: a spec is not a registered skill, so it is never scheduled, never fails, and
the failure-driven loop can never see it. Measured 2026-10-10, ``CAP-J02 READ_INTEL_LIST`` is marked
``implementation_status: EXISTING`` while its spec declares ``INTEL_PIN_COUNT``, which no
authoritative store contains.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winter_agent_v2 import capability_bootstrap as cb

ROOT = Path(__file__).resolve().parents[1]

POISON = {
    "skill_id": "_ZZ_STATIC_DRIFT_PROBE",
    "required_page": "PAGE_THAT_DOES_NOT_EXIST",
    "required_vision": ["BTN_ALSO_DOES_NOT_EXIST", "some plain prose entry", "WILDCARD_*"],
}


def _temp_root(base: Path, *, with_poison: bool) -> Path:
    root = base / ("poisoned" if with_poison else "clean")
    for sub in ("knowledge/skills", "knowledge/game", "knowledge/ui", "winter_agent_v2"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    (root / "knowledge" / "ui" / "pages.json").write_text(
        json.dumps({"pages": ["HOME", "MAP"]}), encoding="utf-8")
    # A catalog row that points at the spec through `existing_skill` - the join key the runtime uses.
    (root / "knowledge" / "game" / "capability_catalog.json").write_text(
        json.dumps({"capabilities": [{
            "capability_id": "CAP-ZZ01", "code": "READ_ZZ_PROBE", "name_cn": "probe",
            "category": "Z", "existing_skill": "_ZZ_STATIC_DRIFT_PROBE",
            "implementation_status": "EXISTING",
        }]}), encoding="utf-8")
    if with_poison:
        (root / "knowledge" / "skills" / "_ZZ_STATIC_DRIFT_PROBE.json").write_text(
            json.dumps(POISON, ensure_ascii=False), encoding="utf-8")
    return root


def test_the_ordinary_scan_reports_static_drift_on_the_real_repo():
    """Criterion: the normal scan path can detect spec drift."""
    scanner = cb.BootstrapScanner.load(ROOT)
    report = scanner.report()

    assert "static_drift" in report, "report() no longer carries the drift section"
    drift = report["static_drift"]
    assert drift["total"] > 0, "the real repo is known to have drift; finding none means the check broke"
    assert set(drift["by_kind"]) <= {"page", "element", "registry", "goal", "promotion", "ambiguity", "duplicate"}
    # The record must locate file, field, missing reference and type.
    for finding in drift["findings"]:
        assert finding["spec_file"].endswith((".json", ".py"))
        assert finding["field"]
        assert finding["missing"]
        assert finding["kind"]


def test_prose_and_wildcards_are_never_reported_as_missing():
    """Criterion: no false positives on prose or patterns."""
    findings = cb.static_knowledge_drift(ROOT)
    missing = {f.missing for f in findings}
    assert "some plain prose entry" not in missing
    assert not any("*" in name for name in missing), (
        f"a wildcard declaration was reported as a missing concrete id: "
        f"{[n for n in missing if '*' in n]}"
    )
    # And an element finding must be a concrete reference the classifier would accept.
    for f in findings:
        if f.kind == "element":
            assert cb._is_element_reference(f.missing), f"{f.missing} is not an element reference"


def test_a_synthetic_drifting_spec_is_detected_then_recovery_is_clean(tmp_path):
    """Criterion: a synthetic error is found, and removing it restores the scan exactly.

    Measured as a DELTA, not as an absolute zero. The goal and promotion checks compare a temp root's
    goal map against the *real* skill registry and dispatch table - those two are process-global and
    cannot be scoped to a temp root - so a temp root legitimately reports the repo's own cross-registry
    drift as well. The spec-side checks are the ones a temp root controls, and it is their delta that
    the synthetic spec must produce.
    """
    clean_scanner = cb.BootstrapScanner.load(_temp_root(tmp_path, with_poison=False))
    clean_report = clean_scanner.report()["static_drift"]

    poisoned_scanner = cb.BootstrapScanner.load(_temp_root(tmp_path, with_poison=True))
    poisoned_report = poisoned_scanner.report()["static_drift"]

    spec_side = {"page", "element", "registry"}
    clean_spec = {k: v for k, v in clean_report["by_kind"].items() if k in spec_side}
    poisoned_spec = {k: v for k, v in poisoned_report["by_kind"].items() if k in spec_side}
    assert not clean_spec, (
        f"the clean temp root already reports spec-side drift, so the comparison is not meaningful: "
        f"{[f for f in clean_report['findings'] if f['kind'] in spec_side]}"
    )
    assert poisoned_spec == {"page": 1, "element": 1, "registry": 1}, (
        f"expected one page + one element + one registry finding, got {poisoned_spec}"
    )
    new = {f["missing"] for f in poisoned_report["findings"] if f["kind"] in spec_side}
    # The prose entry and the wildcard must have been classified away, not reported.
    assert new == {"PAGE_THAT_DOES_NOT_EXIST", "BTN_ALSO_DOES_NOT_EXIST", "_ZZ_STATIC_DRIFT_PROBE"}

    # Recovery: re-reading the clean root reproduces its previous report exactly.
    again = cb.BootstrapScanner.load(_temp_root(tmp_path, with_poison=False)).report()["static_drift"]
    assert again == clean_report


def test_the_drift_attaches_to_the_plan_that_points_at_that_spec(tmp_path):
    """Criterion: the record reaches the existing candidate mechanism, not a side list."""
    scanner = cb.BootstrapScanner.load(_temp_root(tmp_path, with_poison=True))
    plans = {p.capability_id: p for p in scanner.plans()}
    plan = plans["CAP-ZZ01"]

    drift_notes = [n for n in plan.notes if "静态规范漂移" in n]
    assert drift_notes, "the plan for the drifting capability carries no drift note"
    joined = " ".join(drift_notes)
    assert "PAGE_THAT_DOES_NOT_EXIST" in joined
    assert "BTN_ALSO_DOES_NOT_EXIST" in joined
    # The unregistered element name is folded into the field the preload brief already renders.
    assert "BTN_ALSO_DOES_NOT_EXIST" in plan.missing_semantics

    # And it reaches candidates(), which is the sole input to a preload pass.
    assert plan.capability_id in {p.capability_id for p in scanner.candidates()}


def test_the_drift_reaches_the_preload_stage_and_names_the_gate_that_stops_it(tmp_path):
    """The candidate stage is reached; the ledger stage is one existing gate away.

    This test states the boundary rather than papering over it. Driving the real
    ``EscalationQueueAdapter.preload`` on a temp root returns the *existing* refusal
    ``NOT_ARMED_MAIN_LOOP_P0`` - the preload gate, which withholds every preload candidate until the
    main loop's P0 items are measured. That gate is **not** about the drift, and proving
    drift-independence is the point of the second half of this test. Forcing it open would mean
    fabricating P0 measurements, so it is left closed and reported.
    """
    from winter_agent_v2.escalation_queue import (
        DEFAULT_LEDGER, EscalationLedger, EscalationQueueAdapter,
    )

    drifting_root = _temp_root(tmp_path / "drift", with_poison=True)
    clean_root = _temp_root(tmp_path / "clean", with_poison=False)

    def _preload_note(root: Path) -> str:
        scanner = cb.BootstrapScanner.load(root)
        candidates = scanner.candidates()
        adapter = EscalationQueueAdapter(
            root=root, bridge=object(),
            ledger=EscalationLedger(root / DEFAULT_LEDGER),
        )
        observation = adapter.preload(now=None, plan=candidates[0] if candidates else None,
                                     mode="PRELOAD")
        return str(getattr(observation, "preload_note", "") or "")

    drifting_note = _preload_note(drifting_root)
    clean_note = _preload_note(clean_root)

    # The drift reached the preload stage - the call was made with a plan built from the drifting row.
    assert "NOT_ARMED_MAIN_LOOP_P0" in drifting_note, (
        f"expected the existing preload gate to refuse; got {drifting_note!r}. If it now proceeds, "
        "the ledger stage is reachable and the drift has fully entered the loop - assert the record "
        "instead of the refusal"
    )
    # And the refusal is drift-independent: the same gate stops a clean root equally.
    assert clean_note == drifting_note, (
        "the gate refused differently for a drifting and a clean root, so it is NOT drift-independent "
        "and this conclusion needs re-checking"
    )
    # The drift itself is still visible on the candidate that would have been offered.
    plan = next(p for p in cb.BootstrapScanner.load(drifting_root).candidates()
                if p.capability_id == "CAP-ZZ01")
    assert any("静态规范漂移" in n for n in plan.notes)


def test_the_drift_is_reachable_from_the_skill_index():
    """A caller holding a skill id can ask the scanner directly, with no second implementation."""
    scanner = cb.BootstrapScanner.load(ROOT)
    assert scanner.static_drift_for("READ_INTEL_LIST"), (
        "READ_INTEL_LIST declares INTEL_PIN_COUNT, which no authoritative store contains"
    )
    assert scanner.static_drift_for("NOT_A_SKILL") == ()


def test_the_check_does_not_re_read_the_declaring_side_or_its_own_report():
    """The corpus must exclude the declaring specs and any report about the missing names, or the
    check silently finds nothing. Checked against the actual file list and glob patterns, not against
    the docstring - the docstring names both paths precisely because they are excluded."""
    assert not any("skills" in name for name in cb._STATIC_UI_FILES), (
        "the authoritative UI file list reaches into the declaring side"
    )
    source = (ROOT / "winter_agent_v2" / "capability_bootstrap.py").read_text(encoding="utf-8")
    body = source.split("def _authoritative_element_corpus")[1].split("def static_knowledge_drift")[0]
    globbed = body.split("for pattern in (")[1].split(")", 1)[0]
    assert "skills" not in globbed, f"the corpus globs the declaring side: {globbed}"
    assert "screenshot_audit" not in globbed, (
        f"the corpus globs this audit's own output, which lists the missing names: {globbed}"
    )
    # And behaviourally: a spec declaring a nonsense element is still reported, which it could not be
    # if the declaring side were part of the corpus.
    findings = cb.static_knowledge_drift(ROOT)
    assert any(f.kind == "element" for f in findings)
