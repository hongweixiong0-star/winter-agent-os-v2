# -*- coding: utf-8 -*-
"""§1 acceptance: the static differential is wired into the EXISTING chain, end to end.

The chain, with the code location of every hop:

    BootstrapScanner.load(root)                    capability_bootstrap.py:1310 (approx, in `load`)
      -> static_knowledge_drift(base)               capability_bootstrap.py, module level
      -> self.static_drift / self._drift_by_skill   BootstrapScanner.__init__
      -> report()['static_drift']                   BootstrapScanner.report
      -> _plan(row) attaches to the row whose       BootstrapScanner._plan, the `drift = ...` block
         `existing_skill` names the spec
      -> candidates()                               BootstrapScanner.candidates (sole preload input)
      -> EscalationQueueAdapter.preload(plan=...)   escalation_queue.py:2296
      -> write_brief(root, plan)                    capability_bootstrap.py:2392 (writes to disk)
      -> EscalationQueueAdapter._record             escalation_queue.py:2936 (appends to the ledger)
      -> EscalationLedger.append                    the existing durable record

Two facts about persistence, stated rather than implied:

* **preload does persist.** `_record` appends to the existing ``EscalationLedger``, and
  ``write_brief`` writes the plan (whose ``as_row()`` carries the drift notes) to
  ``bootstrap/briefs/<code>.json`` **before** anything reaches the bridge.
* **dedup already exists.** ``_record`` opens with "one row the first time a key is seen", keyed on
  ``FailureSignature.key`` = ``capability|failure_type|skill``. Two scans of the same capability
  therefore produce one row, and nothing here needed to add that.

The limitation this file also pins: the ledger KEY does not include the drift, so two *different*
drifts on one capability collapse into a single record. The detail lives in the brief and the plan
notes instead. Reported, not hidden.
"""
from __future__ import annotations

import json
from pathlib import Path

from winter_agent_v2 import capability_bootstrap as cb
from winter_agent_v2.escalation_queue import (
    Dispatch, NOT_ESCALATABLE,
    CAPABILITY_MISSING, DEFAULT_LEDGER, EscalationCandidate, EscalationLedger,
    EscalationQueueAdapter, FailureSignature,
)

SPEC_ID = "_ZZ_CHAIN_PROBE"
POISON = {
    "skill_id": SPEC_ID,
    "required_page": "PAGE_THAT_DOES_NOT_EXIST",
    "required_vision": ["BTN_CHAIN_MISSING_ELEMENT"],
}


def _root(base: Path, *, poison: bool, corrupt_spec: bool = False) -> Path:
    root = base / (f"poisoned{poison}-corrupt{corrupt_spec}")
    for sub in ("knowledge/skills", "knowledge/game", "knowledge/ui", "winter_agent_v2"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "knowledge/ui/pages.json").write_text(json.dumps({"pages": ["HOME"]}), encoding="utf-8")
    (root / "knowledge/game/capability_catalog.json").write_text(json.dumps({"capabilities": [{
        "capability_id": "CAP-ZZ01", "code": "READ_ZZ_PROBE", "name_cn": "probe",
        "category": "Z", "existing_skill": SPEC_ID, "implementation_status": "MISSING",
    }]}), encoding="utf-8")
    if corrupt_spec:
        # A spec that is not valid JSON at all - the "corrupt input" case.
        (root / "knowledge/skills" / f"{SPEC_ID}.json").write_text("{ this is not json", encoding="utf-8")
    elif poison:
        (root / "knowledge/skills" / f"{SPEC_ID}.json").write_text(
            json.dumps(POISON, ensure_ascii=False), encoding="utf-8")
    return root


# ---------------------------------------------------------------- 1. detection and propagation


def test_the_chain_carries_a_synthetic_inconsistency_from_scan_to_the_plan(tmp_path):
    """Hop 1-4: a deterministically bad spec is found by the scan and attached to the right plan."""
    scanner = cb.BootstrapScanner.load(_root(tmp_path, poison=True))

    reported = scanner.report()["static_drift"]["findings"]
    mine = [f for f in reported if f["spec_file"] == f"{SPEC_ID}.json"]
    assert {f["missing"] for f in mine} == {
        "PAGE_THAT_DOES_NOT_EXIST", "BTN_CHAIN_MISSING_ELEMENT", SPEC_ID}
    assert {f["kind"] for f in mine} == {"page", "element", "registry"}

    plan = next(p for p in scanner.candidates() if p.capability_id == "CAP-ZZ01")
    notes = " ".join(plan.notes)
    assert "PAGE_THAT_DOES_NOT_EXIST" in notes and "BTN_CHAIN_MISSING_ELEMENT" in notes
    assert "BTN_CHAIN_MISSING_ELEMENT" in plan.missing_semantics


def test_the_brief_written_for_that_plan_carries_the_finding_on_disk(tmp_path):
    """Hop 5-6: the plan handed onward is materialised, and the materialised copy has the drift."""
    scanner = cb.BootstrapScanner.load(_root(tmp_path, poison=True))
    plan = next(p for p in scanner.candidates() if p.capability_id == "CAP-ZZ01")

    path = cb.write_brief(scanner.root, plan)
    assert path.is_file(), "write_brief did not persist anything"
    brief = json.loads(path.read_text(encoding="utf-8"))
    blob = json.dumps(brief, ensure_ascii=False)
    assert "PAGE_THAT_DOES_NOT_EXIST" in blob and "BTN_CHAIN_MISSING_ELEMENT" in blob, (
        "the persisted brief does not name the inconsistency"
    )
    # The brief is the pre-edit file's copy of the plan; the notes must survive into it.
    assert any("静态规范漂移" in note for note in brief.get("notes") or [])


# ---------------------------------------------------------------- 2. dedup on a repeat scan


def test_the_signature_key_is_stable_so_a_repeat_scan_dedups(tmp_path):
    """The dedup precondition: the same capability yields the same key on two separate scans."""
    first = cb.BootstrapScanner.load(_root(tmp_path, poison=True))
    second = cb.BootstrapScanner.load(_root(tmp_path, poison=True))
    plan_a = next(p for p in first.candidates() if p.capability_id == "CAP-ZZ01")
    plan_b = next(p for p in second.candidates() if p.capability_id == "CAP-ZZ01")

    key = lambda p: FailureSignature(  # noqa: E731 - the same construction preload uses
        capability=p.code or p.capability_id, failure_type=CAPABILITY_MISSING, skill=p.skill).key
    assert key(plan_a) == key(plan_b), "a repeat scan would create a second record"


def test_recording_the_same_capability_twice_writes_one_ledger_row(tmp_path):
    """Hop 7: `_record` is the recording primitive the preload path calls, and it is idempotent.

    Called directly because the preload gate withholds the public entry point (see the gate test in
    test_static_drift_reaches_the_existing_loop.py); this is the same method that path invokes.

    The dispatch object is the real `Dispatch`, not a stub: `_record` reads `dispatch.action` and
    `dispatch.reason`, and it wraps its body in a broad `except Exception: pass`. A stub missing
    those attributes therefore persisted NOTHING and reported no error - which is itself the
    "record write failure is silent" case from §1.5, so it is recorded in the acceptance report.
    """
    root = tmp_path / "root"
    root.mkdir()
    ledger = EscalationLedger(root / DEFAULT_LEDGER)
    adapter = EscalationQueueAdapter(root=root, bridge=object(), ledger=ledger)
    candidate = EscalationCandidate(
        signature=FailureSignature(capability="READ_ZZ_PROBE", failure_type=CAPABILITY_MISSING,
                                   skill=SPEC_ID),
        condition=CAPABILITY_MISSING, reason="static spec drift", goal="", evidence=())
    dispatch = Dispatch(NOT_ESCALATABLE, "not submitted in this test")

    adapter._record(candidate, dispatch=dispatch)
    adapter._record(candidate, dispatch=dispatch)

    record = ledger.snapshot().get(candidate.signature.key)
    assert record is not None, "nothing was persisted at all"
    rows = [e for e in ledger.events()
            if e.get("event") == "escalation_created" and e.get("key") == candidate.signature.key]
    assert len(rows) == 1, f"a repeat scan wrote {len(rows)} rows for one capability"


def test_the_ledger_key_does_not_include_the_drift_and_that_is_reported(tmp_path):
    """The documented limitation, asserted so it cannot be mistaken for completeness."""
    key = FailureSignature(capability="READ_ZZ_PROBE", failure_type=CAPABILITY_MISSING,
                           skill=SPEC_ID).key
    assert "PAGE_THAT_DOES_NOT_EXIST" not in key
    assert key == f"READ_ZZ_PROBE|{CAPABILITY_MISSING}|{SPEC_ID}"


# ---------------------------------------------------------------- 3. recovery after a fix


def test_fixing_the_spec_closes_the_finding(tmp_path):
    """Recovery: with the bad spec removed, the same scan reports nothing new for it."""
    poisoned = cb.BootstrapScanner.load(_root(tmp_path, poison=True))
    assert [f for f in poisoned.report()["static_drift"]["findings"]
            if f["spec_file"] == f"{SPEC_ID}.json"]

    fixed = cb.BootstrapScanner.load(_root(tmp_path, poison=False))
    assert not [f for f in fixed.report()["static_drift"]["findings"]
                if f["spec_file"] == f"{SPEC_ID}.json"], (
        "the finding survived the fix, so the check is not reading the current tree"
    )


# ---------------------------------------------------------------- 4. unrelated results untouched


def test_an_unrelated_scan_is_unaffected_by_the_injected_spec(tmp_path):
    """Scoping: adding the bad spec must not perturb any other finding."""
    clean = cb.BootstrapScanner.load(_root(tmp_path, poison=False)).report()["static_drift"]
    poisoned = cb.BootstrapScanner.load(_root(tmp_path, poison=True)).report()["static_drift"]

    def counts_by_kind(payload):
        return {k: v for k, v in payload["by_kind"].items()}

    clean_counts, poisoned_counts = counts_by_kind(clean), counts_by_kind(poisoned)
    spec_kinds = {"page", "element", "registry"}
    for kind, count in clean_counts.items():
        if kind in spec_kinds:
            continue
        assert poisoned_counts.get(kind) == count, f"the {kind} check changed for an unrelated spec"

    # And the non-spec kinds are literally the same findings, not merely the same count.
    def non_spec(payload):
        return sorted((f["kind"], f["missing"]) for f in payload["findings"]
                      if f["kind"] not in spec_kinds)

    assert non_spec(clean) == non_spec(poisoned)


# ---------------------------------------------------------------- 5. failure handling


def test_a_corrupt_spec_does_not_crash_or_invent_a_finding(tmp_path):
    """Corrupt input: skipped, not raised, and nothing is promoted on the strength of it."""
    scanner = cb.BootstrapScanner.load(_root(tmp_path, poison=False, corrupt_spec=True))
    report = scanner.report()
    assert report["summary"]["catalog_rows"] == 1, "a corrupt spec must not remove real rows"
    assert not [f for f in report["static_drift"]["findings"] if f["spec_file"] == f"{SPEC_ID}.json"], (
        "a file that could not be parsed produced a finding, which would be invented evidence"
    )


def test_an_unavailable_queue_does_not_hide_the_finding(tmp_path):
    """Detection is independent of the queue: the gate refusing must not lose the finding."""
    scanner = cb.BootstrapScanner.load(_root(tmp_path, poison=True))
    root = scanner.root
    adapter = EscalationQueueAdapter(root=root, bridge=object(),
                                     ledger=EscalationLedger(root / DEFAULT_LEDGER))
    plan = next(p for p in scanner.candidates() if p.capability_id == "CAP-ZZ01")
    observation = adapter.preload(now=None, plan=plan, mode="PRELOAD")
    note = str(getattr(observation, "preload_note", "") or "")
    assert not getattr(observation, "preloaded", ()), (
        f"preload dispatched something; the gate test expects a refusal, got {note!r}"
    )
    # The finding is still fully readable through the scan even though the queue refused.
    still = cb.BootstrapScanner.load(root).report()["static_drift"]["findings"]
    assert [f for f in still if f["spec_file"] == f"{SPEC_ID}.json"]
