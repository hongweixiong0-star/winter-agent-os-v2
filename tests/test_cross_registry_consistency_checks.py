# -*- coding: utf-8 -*-
"""The four cross-registry checks, each proven to fail on a synthetic error.

`static_knowledge_drift` compares pairs of AUTHORITATIVE sources rather than guessing:

    goal       knowledge/goals/capability_skill_map.json  vs  the skill registry
    promotion  LiveRuntime.VERIFIED_ATOMIC (dispatchable) vs  the registry's SkillState
    ambiguity  knowledge/ui/icon_label_controls.json      (a label the project places on 2 pages)
    page/element/registry  (covered in test_declared_pages_and_elements_are_registered.py)

The synthetic errors are injected by replacing `_registry_view`, which is the single place the
registry is read, so these tests exercise the real check body and not a replica of it.

A note on what is NOT checked, and why that is deliberate: an earlier draft flagged skills for
having no `verifier` on the `Skill` object. That would have reported 46 of the 47 VERIFIED skills,
and it would have been wrong - the verifier binding lives in `VERIFIED_ATOMIC`, whose 141 entries all
carry a bound callable. Reading the real binding instead of the empty field is what keeps this check
from being noise.
"""
from __future__ import annotations

import json
from pathlib import Path

from winter_agent_v2 import capability_bootstrap as cb

ROOT = Path(__file__).resolve().parents[1]


def _kinds(findings) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return counts


# ------------------------------------------------------------------ the real repo


def test_the_real_repo_exercises_every_check_kind():
    """Each check must be live, not silently returning nothing."""
    findings = cb.static_knowledge_drift(ROOT)
    counts = _kinds(findings)
    for kind in ("page", "element", "registry", "goal", "promotion", "ambiguity"):
        assert counts.get(kind, 0) > 0, (
            f"the {kind} check reports nothing on the real repo, so it is not actually running. "
            f"measured kinds: {counts}"
        )


def test_every_finding_names_both_sides_of_the_comparison():
    """A finding is only actionable if it says which file and which field disagree."""
    for f in cb.static_knowledge_drift(ROOT):
        assert f.spec_file, f"{f.kind} finding has no source file"
        assert f.field, f"{f.kind} finding has no field"
        assert f.missing, f"{f.kind} finding names no missing object"
        assert f.detail, f"{f.kind} finding has no explanation"


# ------------------------------------------------------------------ goal


def test_a_goal_naming_an_unregistered_skill_is_detected(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "knowledge" / "goals").mkdir(parents=True)
    (root / "knowledge" / "goals" / "capability_skill_map.json").write_text(json.dumps({
        "goals": [{"goal": "G", "capabilities": [
            {"capability": "C", "alternatives": ["REAL_SKILL"],
             "implemented_by": "REAL_SKILL", "live_verified_by": "REAL_SKILL"},
            {"capability": "D", "alternatives": ["GHOST_SKILL"],
             "implemented_by": "GHOST_SKILL", "live_verified_by": None},
        ]}],
    }), encoding="utf-8")
    monkeypatch.setattr(cb, "_registry_view",
                        lambda base: ({"REAL_SKILL"}, {"REAL_SKILL": "VERIFIED"}, {"REAL_SKILL"}))

    found = [f for f in cb._cross_registry_drift(root) if f.kind == "goal"]
    assert [f.missing for f in found] == ["GHOST_SKILL"], (
        f"expected exactly the unregistered name, got {[f.missing for f in found]}"
    )
    assert "no execution path" in found[0].detail


# ------------------------------------------------------------------ promotion


def test_a_candidate_that_is_dispatchable_is_NOT_flagged(tmp_path, monkeypatch):
    """Adjudicated 2026-10-10: CANDIDATE is an executable state in this project.

    `capability_coverage.EXECUTABLE_STATES` is `{CANDIDATE, STABLE, VERIFIED}`, and `runtime.py`
    gates dispatch on `VERIFIED_ATOMIC` membership without consulting `state`. So a CANDIDATE skill
    that is dispatchable is the DESIGN, not a contradiction. The first version of this check compared
    against `(VERIFIED, STABLE)` and reported 95 such cases - all of them wrong.
    """
    monkeypatch.setattr(cb, "_registry_view",
                        lambda base: ({"A"}, {"A": "CANDIDATE"}, {"A"}))
    assert [f for f in cb._cross_registry_drift(tmp_path) if f.kind == "promotion"] == []


def test_a_blocked_skill_that_is_dispatchable_is_detected(tmp_path, monkeypatch):
    """BLOCKED is NOT an executable state, so reaching it through the dispatch table is a real
    contradiction. Three such skills exist today (COLLECT_FINISHED_TRAINING_*)."""
    monkeypatch.setattr(cb, "_registry_view",
                        lambda base: ({"A"}, {"A": "BLOCKED"}, {"A"}))
    found = [f for f in cb._cross_registry_drift(tmp_path) if f.kind == "promotion"]
    assert [f.missing for f in found] == ["A"]
    assert "EXECUTABLE_STATES" in found[0].detail


def test_a_verified_skill_the_loop_cannot_dispatch_is_detected(tmp_path, monkeypatch):
    # Both entries are VERIFIED, so the only contradiction present is B's absence from the dispatch
    # table. (An earlier draft also made A a CANDIDATE, which is a second contradiction by design
    # and made the test expect one finding while the check correctly produced two.)
    monkeypatch.setattr(cb, "_registry_view",
                        lambda base: ({"A", "B"}, {"A": "VERIFIED", "B": "VERIFIED"}, {"A"}))
    found = [f for f in cb._cross_registry_drift(tmp_path) if f.kind == "promotion"]
    assert [f.missing for f in found] == ["B"], "only the verified-but-undispatchable case"
    # The message must carry its own severity: classified 2026-10-10 as bookkeeping, not a defect.
    assert "LOW SEVERITY" in found[0].detail
    assert "not in the dispatch table" in found[0].detail


def test_a_consistent_registry_reports_no_promotion_drift(tmp_path, monkeypatch):
    """The counter-case: when the two sources agree, the check must stay silent."""
    monkeypatch.setattr(cb, "_registry_view",
                        lambda base: ({"A", "B"}, {"A": "VERIFIED", "B": "CANDIDATE"}, {"A"}))
    assert [f for f in cb._cross_registry_drift(tmp_path) if f.kind == "promotion"] == []


# ------------------------------------------------------------------ ambiguity


def test_a_label_registered_on_two_pages_is_detected(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "knowledge" / "ui").mkdir(parents=True)
    (root / "knowledge" / "ui" / "icon_label_controls.json").write_text(json.dumps({
        "controls": {
            "确定": {"pages": ["HOME"]},
            "登录好礼": {"pages": ["MAP", "HOME"]},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(cb, "_registry_view", lambda base: ({"S"}, {"S": "VERIFIED"}, {"S"}))

    found = [f for f in cb._cross_registry_drift(root) if f.kind == "ambiguity"]
    assert [f.missing for f in found] == ["登录好礼"], (
        f"expected only the two-page label, got {[f.missing for f in found]}"
    )
    assert "cannot identify the page" in found[0].detail


def test_a_label_on_one_page_is_not_ambiguity(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "knowledge" / "ui").mkdir(parents=True)
    (root / "knowledge" / "ui" / "icon_label_controls.json").write_text(
        json.dumps({"controls": {"确定": {"pages": ["HOME"]}}}), encoding="utf-8")
    monkeypatch.setattr(cb, "_registry_view", lambda base: ({"S"}, {"S": "VERIFIED"}, {"S"}))
    assert [f for f in cb._cross_registry_drift(root) if f.kind == "ambiguity"] == []


# ------------------------------------------------------------------ duplicate specs


def test_the_real_repo_has_duplicate_spec_ids_and_they_are_reported():
    """Measured 2026-10-10: two skill_ids carry both a top-level spec and a candidate copy, and the
    two copies disagree about the skill's lifecycle."""
    found = [f for f in cb.static_knowledge_drift(ROOT) if f.kind == "duplicate"]
    ids = sorted(f.missing for f in found)
    assert ids == ["READ_DAILY_PROGRESS", "READ_INTEL_LIST"], (
        f"expected exactly the two measured duplicates; got {ids}. If a duplicate was genuinely "
        "resolved, update this expectation deliberately rather than loosening it"
    )
    for f in found:
        assert "candidate" in f.spec_file and "," in f.spec_file, (
            "a duplicate finding must name both files, or it cannot be acted on"
        )


def test_a_skill_id_in_two_places_is_detected(tmp_path):
    """Synthetic: the same id at the top level and under candidate/ must be reported."""
    root = tmp_path / "root"
    (root / "knowledge" / "skills" / "candidate").mkdir(parents=True)
    (root / "knowledge" / "ui").mkdir(parents=True)
    (root / "knowledge" / "ui" / "pages.json").write_text(json.dumps({"pages": ["HOME"]}),
                                                          encoding="utf-8")
    body = {"skill_id": "SOME_SKILL", "required_page": "HOME"}
    (root / "knowledge" / "skills" / "SOME_SKILL.json").write_text(json.dumps(body), encoding="utf-8")
    (root / "knowledge" / "skills" / "candidate" / "SOME_SKILL.json").write_text(
        json.dumps({**body, "required_page": None}), encoding="utf-8")

    found = [f for f in cb.static_knowledge_drift(root) if f.kind == "duplicate"]
    assert [f.missing for f in found] == ["SOME_SKILL"]
    assert "SOME_SKILL.json" in found[0].spec_file and "candidate" in found[0].spec_file


def test_one_spec_per_skill_id_reports_no_duplicate(tmp_path):
    """The counter-case: a single spec must stay silent."""
    root = tmp_path / "root"
    (root / "knowledge" / "skills" / "candidate").mkdir(parents=True)
    (root / "knowledge" / "ui").mkdir(parents=True)
    (root / "knowledge" / "ui" / "pages.json").write_text(json.dumps({"pages": ["HOME"]}),
                                                          encoding="utf-8")
    (root / "knowledge" / "skills" / "ONLY.json").write_text(
        json.dumps({"skill_id": "ONLY_ONE", "required_page": "HOME"}), encoding="utf-8")
    assert [f for f in cb.static_knowledge_drift(root) if f.kind == "duplicate"] == []


def test_the_spec_walk_is_recursive(tmp_path):
    """The first version globbed the top level only, so a candidate spec's declarations were never
    checked at all."""
    root = tmp_path / "root"
    (root / "knowledge" / "skills" / "candidate").mkdir(parents=True)
    (root / "knowledge" / "ui").mkdir(parents=True)
    (root / "knowledge" / "ui" / "pages.json").write_text(json.dumps({"pages": ["HOME"]}),
                                                          encoding="utf-8")
    (root / "knowledge" / "skills" / "candidate" / "DEEP.json").write_text(
        json.dumps({"skill_id": "DEEP_SKILL", "required_page": "PAGE_NOWHERE"}),
        encoding="utf-8")

    found = [f for f in cb.static_knowledge_drift(root) if f.kind == "page"]
    assert [f.missing for f in found] == ["PAGE_NOWHERE"], (
        "a spec under candidate/ was not walked, so its page declaration was never checked"
    )
    assert "candidate" in found[0].spec_file


# ------------------------------------------------------------------ no false positives


def test_an_unreadable_registry_does_not_produce_noise(tmp_path, monkeypatch):
    """If neither registry can be read, the check must report nothing rather than everything.

    An empty temp root is not enough to produce this state - the package is already imported, so
    `_registry_view` would return the REAL registry. The view is therefore scripted to be empty,
    which is what the guard inside `_cross_registry_drift` exists for.
    """
    monkeypatch.setattr(cb, "_registry_view", lambda base: (set(), {}, set()))
    assert cb._cross_registry_drift(tmp_path) == []
