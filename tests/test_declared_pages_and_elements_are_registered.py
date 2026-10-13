# -*- coding: utf-8 -*-
"""A capability spec must not name a page or a vision element that does not exist.

This test is now a thin assertion layer over the runtime's own check. The classifier lives in
``winter_agent_v2.capability_bootstrap.static_knowledge_drift`` and the ordinary scan path already
consumes it, so a runtime scan and this test can never disagree about what counts as drift. The
first version of this file carried a second, private copy of the classifier; that duplication is
what this revision removes.

The gap being guarded

    `knowledge/skills/*.json` are capability SPECIFICATIONS. `winter_agent_v2/skills.py` is the
    authoritative skill REGISTRY (143 `Skill(...)` entries in code) and `knowledge/ui/pages.json` is
    the authoritative page vocabulary (29 names). Those two sides had no meeting point: a spec could
    declare a page or a vision element that exists nowhere, and nothing noticed.

    Measured 2026-10-10: three specs declare pages outside the vocabulary, and
    `CAP-J02 READ_INTEL_LIST` is marked `implementation_status: EXISTING` while its spec declares
    `INTEL_PIN_COUNT`, which no authoritative store contains.

    The failure mode is silence: such a spec is not a registered skill, so it is never scheduled,
    never attempted, never fails, and therefore never reaches a failure-driven improvement loop.

What is quarantined, and why that is honest

    ``QUARANTINED_ELEMENT_REFS`` and ``QUARANTINED_PAGE_DECLARATIONS`` list the drift that exists
    TODAY, by name and with a reason. Quarantining by name (not by count) means a NEW drift still
    fails the guard, and ``test_the_quarantine_list_has_no_stale_entries`` makes a stale entry fail
    too - so the list cannot rot into a blanket exemption.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from winter_agent_v2 import capability_bootstrap as cb

ROOT = Path(__file__).resolve().parents[1]
PAGES_JSON = ROOT / "knowledge" / "ui" / "pages.json"
SKILLS_PY = ROOT / "winter_agent_v2" / "skills.py"

#: Concrete references known not to resolve today, each with the reason it is tolerated. Every entry
#: belongs to a shop capability spec or to an intel/training spec, and the reason is the same: the
#: element is named in a specification but was never registered in any authoritative store.
QUARANTINED_ELEMENT_REFS: dict[str, str] = {
    "BTN_免费刷新": "VISIT_MYSTERY_SHOP spec; free-refresh button never registered",
    "CARD_ANCHOR_剩余：N": "VISIT_ALLIANCE_SHOP spec; per-card anchor never registered",
    "CARD_BODY_ZONE": "VISIT_WANDERING_MERCHANT spec; overlay-probe zone never registered",
    "CARD_DISCOUNT": "VISIT_MYSTERY_SHOP spec; discount badge never registered",
    "CARD_PRICE": "VISIT_WANDERING_MERCHANT spec; card price token never registered",
    "DIALOG_确定购买": "VISIT_MYSTERY_SHOP spec; purchase overlay never registered",
    "INTEL_PIN_COUNT": "READ_INTEL_LIST spec; pin counter never registered",
    "NAV_ALLIANCE_联盟": "VISIT_ALLIANCE_SHOP spec; bottom-nav entry never registered",
    "NAV_STORE_商店": "VISIT_MYSTERY_SHOP spec; bottom-nav entry never registered",
    "ORANGE_PRICE_BUTTON": "VISIT_MYSTERY_SHOP spec; orange price button never registered",
    "OVERLAY_确定购买": "VISIT_ALLIANCE_SHOP spec; purchase overlay never registered",
    "SHOP_BANNER_下次刷新": "VISIT_ALLIANCE_SHOP spec; refresh banner never registered",
    "SHOP_HEADER_联盟商店": "VISIT_ALLIANCE_SHOP spec; shop header never registered",
    "SHOP_TABS_今日/本周": "VISIT_ALLIANCE_SHOP spec; tab strip never registered",
    "TAB_游荡商人": "VISIT_WANDERING_MERCHANT spec; store tab never registered",
    "TAB_神秘商店": "VISIT_MYSTERY_SHOP spec; store tab never registered",
    "TILE_联盟商店": "VISIT_ALLIANCE_SHOP spec; entry tile never registered",
    "TOP_BAR_金牌币": "VISIT_MYSTERY_SHOP spec; medal currency never registered",
    "WALLET_ONE_NUMBER_ONLY": "VISIT_ALLIANCE_SHOP spec; wallet reader never registered",
    "WALLET_钻石": "VISIT_WANDERING_MERCHANT spec; gem wallet never registered",
}

#: Specs that declare a page the vocabulary does not contain, by name, with a reason.
QUARANTINED_PAGE_DECLARATIONS: dict[str, str] = {
    "VISIT_ALLIANCE_SHOP": "declares ALLIANCE_SHOP, absent from knowledge/ui/pages.json",
    "VISIT_MYSTERY_SHOP": "declares SHOP_MYSTERY, absent from knowledge/ui/pages.json",
    "VISIT_WANDERING_MERCHANT": "declares SHOP_WANDERING_MERCHANT, absent from knowledge/ui/pages.json",
}


@pytest.fixture(scope="module")
def drift() -> tuple[cb.StaticKnowledgeDrift, ...]:
    findings = cb.static_knowledge_drift(ROOT)
    assert findings, (
        "the runtime's own check reports no drift at all, which contradicts the repo's known state; "
        "either the drift was fixed (then re-measure and update this file) or the check broke"
    )
    return findings


# ----------------------------------------------------------------- the guard


def test_every_concrete_vision_reference_resolves_or_is_quarantined(drift):
    """The core guard: nothing may reference an element that exists nowhere, silently."""
    unquarantined = sorted({f.missing for f in drift if f.kind == "element"}
                           - set(QUARANTINED_ELEMENT_REFS))
    assert not unquarantined, (
        "these vision element ids are declared by a capability spec but exist in no authoritative "
        "store, and they are not quarantined. Either register them or add them to "
        "QUARANTINED_ELEMENT_REFS with a reason:\n  "
        + "\n  ".join(f"{name} (declared by "
                      f"{', '.join(sorted({f.spec_file for f in drift if f.missing == name}))})"
                      for name in unquarantined)
    )


def test_every_declared_page_is_in_the_vocabulary_or_quarantined(drift):
    vocabulary = set(json.loads(PAGES_JSON.read_text(encoding="utf-8"))["pages"])
    assert vocabulary, "the page vocabulary is empty"
    offenders = sorted({f.skill_id for f in drift
                        if f.kind == "page" and f.skill_id not in QUARANTINED_PAGE_DECLARATIONS})
    assert not offenders, (
        "these specs declare a page that is not in knowledge/ui/pages.json and is not quarantined:\n  "
        + "\n  ".join(offenders)
    )


def test_the_quarantine_list_has_no_stale_entries(drift):
    """A quarantined name that now resolves must be removed, so the list cannot rot into a blanket
    exemption that hides future drift."""
    still_missing = {f.missing for f in drift if f.kind == "element"}
    stale = sorted(name for name in QUARANTINED_ELEMENT_REFS if name not in still_missing)
    assert not stale, (
        "these entries are quarantined but now resolve, so the entry is stale and must be removed:\n  "
        + "\n  ".join(stale)
    )
    declared = {f.skill_id for f in drift if f.kind == "page"}
    stale_pages = sorted(s for s in QUARANTINED_PAGE_DECLARATIONS if s not in declared)
    assert not stale_pages, f"quarantined page declarations that no longer exist: {stale_pages}"


def test_a_quarantined_spec_is_reported_as_a_specification_not_a_live_skill(drift):
    """The distinction that makes the gap invisible: a spec whose id is absent from the registry is a
    candidate, so it is never scheduled and can never fail. The check names which is which."""
    registered = set(re.findall(r'Skill\(\s*"([A-Z0-9_]+)"',
                                SKILLS_PY.read_text(encoding="utf-8", errors="replace")))
    assert registered, "could not read any skill id from the registry - the check would be vacuous"

    unregistered = {f.skill_id for f in drift if f.kind == "registry"}
    assert unregistered, "no registry findings at all, so the registry comparison is not running"
    # The runtime derives this from the registry itself, so it cannot disagree with it.
    assert not (unregistered & registered), (
        f"the check calls these unregistered but they ARE in the registry: {unregistered & registered}"
    )
    for spec_skill in QUARANTINED_PAGE_DECLARATIONS:
        assert spec_skill not in registered, (
            f"{spec_skill} is quarantined as an unregistered specification, but it IS in the "
            "registry - the quarantine reason is wrong and must be re-checked"
        )


def test_the_record_locates_file_field_missing_reference_and_type(drift):
    """Criterion: the record must name file, field, missing reference and type."""
    known_kinds = {"page", "element", "registry", "goal", "promotion", "ambiguity", "duplicate"}
    for finding in drift:
        assert finding.spec_file.endswith((".json", ".py"))
        assert finding.field
        assert finding.missing
        assert finding.kind in known_kinds, f"unknown drift kind {finding.kind!r}"
        assert finding.detail


def test_prose_and_wildcards_are_never_reported(drift):
    """`required_vision` mixes element ids with prose and with wildcard patterns; none of those may be
    reported as a missing concrete id."""
    missing = {f.missing for f in drift}
    for prose in ("building identity", "mission markers", "current/target", "prerequisite checks"):
        assert prose not in missing, f"prose was reported as a missing element: {prose!r}"
    assert not [m for m in missing if "*" in m], (
        f"a wildcard declaration was reported as a missing concrete id: {[m for m in missing if '*' in m]}"
    )
    for finding in drift:
        if finding.kind == "element":
            assert cb._is_element_reference(finding.missing)
