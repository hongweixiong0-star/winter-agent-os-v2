"""The driver that turns finished examinations into rungs -- and the reuse that ends the chain.

Until this existed the gates were tested and unreachable: nothing called
`validation_settlement`, nothing appended `live_tried` or `live_verified`, and the
production-reuse detector had no record in the state it looks for.  A gate nothing invokes is
not a guard, it is a comment.

What these tests defend is the *order* and the *exclusions*, because those are what stop the
chain from certifying itself:

  validation outcome -> live_tried / live_verified / a named refusal
  live_verified + the device actually returned -> rejoined (and only then)
  a PRODUCTION episode on the produced version -> production_reuse -> DONE
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    DONE, LIVE_TRIED, LIVE_VERIFIED, LIVE_VERIFY_PENDING, REJOINED, VERSION_ACTIVE,
    EscalationLedger, EscalationQueueAdapter,
)

KEY = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"
JOB = "5b525aa4"
AFTER = "b" * 40
NOW = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)


class _NoBridge:
    def status(self, job_id):  # pragma: no cover
        raise AssertionError("settlement must not need the gateway")


def _rows(*extra) -> list[dict]:
    base = [
        {"event": "escalation_created", "key": KEY, "capability": "SPEND_STAMINA_ON_BEAST",
         "skill": "SCAN_MAP_FOR_BEAST", "failure_type": "NO_GOAL_PROGRESS", "state": "NEW",
         "recorded_at": "2026-09-18T22:00:00+00:00"},
        {"event": "submitted", "key": KEY, "job_id": JOB,
         "recorded_at": "2026-09-18T22:01:00+00:00"},
        {"event": "reconciled", "key": KEY, "job_id": JOB, "outcome": VERSION_ACTIVE,
         "job_state": DONE, "before_version": "a" * 40, "after_version": AFTER,
         "recorded_at": "2026-09-18T22:02:00+00:00"},
        {"event": "version_active", "key": KEY, "job_id": JOB, "after_version": AFTER,
         "active_version": AFTER, "activation_episode_id": "ep-act",
         "recorded_at": "2026-09-18T22:03:00+00:00"},
        # The examination was requested by §一's driver; this is the state the settlement
        # driver looks for.
        {"event": "live_verify_pending", "key": KEY, "job_id": JOB, "outcome": VERSION_ACTIVE,
         "recorded_at": "2026-09-18T22:04:00+00:00"},
    ]
    return base + list(extra)


def _validation_episode(**over) -> dict:
    row = {
        "episode_id": "ep-val-1", "execution_mode": "DEVELOPMENT_VALIDATION",
        "trace_id": KEY, "job_id": JOB, "capability": "SPEND_STAMINA_ON_BEAST",
        "skill": "SCAN_MAP_FOR_BEAST", "repo_revision": AFTER,
        "expected_after_version": AFTER, "verifier_ok": True, "goal_progress": True,
        "before_screenshot": "dataset/raw/a.png", "after_screenshot": "dataset/raw/b.png",
        "recorded_at": "2026-09-18T22:05:00+00:00",
    }
    row.update(over)
    return row


def _production_episode(**over) -> dict:
    row = _validation_episode(episode_id="ep-prod-1", execution_mode="PRODUCTION")
    row.pop("trace_id")
    row.pop("expected_after_version")
    # After the rejoin, on purpose: §9's evidence is ordinary play *following* the capability's
    # return to the production pool.  A production episode from before it is play that happened
    # while the capability was still being examined.
    row["recorded_at"] = "2026-09-18T23:30:00+00:00"
    row.update(over)
    return row


def _adapter(tmp_path: Path, *, episodes: list[dict], rows: list[dict] | None = None,
             lease_holder: str = ""):
    (tmp_path / "learning").mkdir(parents=True, exist_ok=True)
    ledger_path = tmp_path / "learning/workbuddy_escalations.jsonl"
    ledger_path.write_text("\n".join(json.dumps(r) for r in (rows or _rows())) + "\n",
                           encoding="utf-8")
    (tmp_path / "learning/episodes.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in episodes), encoding="utf-8")
    if lease_holder:
        (tmp_path / "learning/DEVICE_LEASE.json").write_text(
            json.dumps({"holder": lease_holder}), encoding="utf-8")
    return EscalationQueueAdapter(root=tmp_path, ledger=EscalationLedger(ledger_path),
                                  bridge=_NoBridge())


def test_a_passing_examination_reaches_live_verified(tmp_path: Path):
    adapter = _adapter(tmp_path, episodes=[_validation_episode()])
    events = adapter.settle_validations(NOW)
    assert any("LIVE_VERIFIED" in e for e in events), events
    record = adapter.ledger.snapshot().get(KEY)
    assert record.outcome == LIVE_VERIFIED
    assert record.live_verify_episode_id == "ep-val-1"


def test_rejoin_happens_after_verification_and_only_when_the_device_is_back(tmp_path: Path):
    """§8, and the two halves are tested separately because either alone is a claim."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode()])
    adapter.settle_validations(NOW)
    assert adapter.ledger.snapshot().get(KEY).state == REJOINED, "the device was free"

    # Now a record that verifies while an examination still holds the device.
    other = tmp_path / "held"
    adapter2 = _adapter(other, episodes=[_validation_episode()],
                        lease_holder="OWNER_DEVELOPMENT_VALIDATION")
    events = adapter2.settle_validations(NOW)
    record2 = adapter2.ledger.snapshot().get(KEY)
    assert record2.outcome == LIVE_VERIFIED
    assert record2.state != REJOINED, "a held device must not be recorded as re-joined"
    assert any("设备尚未归还" in e for e in events), events


def test_rejoin_carries_no_reuse_episode_id(tmp_path: Path):
    """§9: re-joining is not reuse, and one field must not conflate them."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode()])
    adapter.settle_validations(NOW)
    rows = [r for r in adapter.ledger.events() if r.get("event") == "rejoined"]
    assert rows, "the rejoin must be recorded"
    assert "production_reuse_episode_id" not in rows[-1]


def test_a_failed_attempt_is_live_tried_and_not_verified(tmp_path: Path):
    adapter = _adapter(tmp_path, episodes=[_validation_episode(verifier_ok=False)])
    events = adapter.settle_validations(NOW)
    record = adapter.ledger.snapshot().get(KEY)
    assert record.outcome == LIVE_TRIED
    assert record.live_try_episode_id == "ep-val-1"
    assert not record.production_reuse_episode_id
    assert any("LIVE_TRIED" in e for e in events), events


def test_a_version_mismatch_goes_back_to_the_activation_rung(tmp_path: Path):
    """A failed measurement is not a failed capability, and must not spend the repair budget."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode(repo_revision="c" * 40)])
    events = adapter.settle_validations(NOW)
    record = adapter.ledger.snapshot().get(KEY)
    assert any("VALIDATION_VERSION_MISMATCH" in e for e in events), events
    assert record.state == LIVE_VERIFY_PENDING, "it waits for the right version to run"
    assert record.outcome == "VERSION_ACTIVATION_PENDING"


def test_an_ordinary_production_episode_ends_the_chain_at_done(tmp_path: Path):
    """§10: the only evidence that WorkBuddy taught V2 the capability.

    The reuse is found on the same pass that records the rejoin, because the fixture's
    production episode is *after* the rejoin -- which is the condition §9 states.  So the
    assertion reads that pass's events, and the second call proves the pass adds nothing.
    """
    adapter = _adapter(tmp_path, episodes=[_validation_episode(), _production_episode()])
    events = adapter.settle_validations(NOW)
    record = adapter.ledger.snapshot().get(KEY)
    assert record.state == DONE
    assert record.production_reuse_episode_id == "ep-prod-1"
    assert any("PRODUCTION_REUSE" in e for e in events), events
    assert adapter.settle_validations(NOW) == [], "one chain, one set of rungs"


def test_a_validation_episode_can_never_be_the_production_reuse(tmp_path: Path):
    """§10's hard rule.  Only a PRODUCTION row may fill that field."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode()])
    adapter.settle_validations(NOW)
    for _ in range(3):
        adapter.settle_validations(NOW)
    record = adapter.ledger.snapshot().get(KEY)
    assert record.state == REJOINED, "a passing examination is not production reuse"
    assert record.production_reuse_episode_id == ""


def test_a_production_episode_on_the_wrong_version_is_not_reuse(tmp_path: Path):
    """The old code still working is not the new code being used."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode(),
                                          _production_episode(repo_revision="c" * 40)])
    adapter.settle_validations(NOW)
    adapter.settle_validations(NOW)
    record = adapter.ledger.snapshot().get(KEY)
    assert record.production_reuse_episode_id == ""
    assert record.state == REJOINED


def test_goal_progress_is_required_where_the_defect_demands_it(tmp_path: Path):
    """§7's condition, applied to the reuse pass as well as the examination."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode(),
                                          _production_episode(goal_progress=False)])
    adapter.settle_validations(NOW)
    adapter.settle_validations(NOW)
    assert adapter.ledger.snapshot().get(KEY).production_reuse_episode_id == ""


def test_settlement_is_idempotent(tmp_path: Path):
    """A second pass over unchanged rows must not append a second verdict."""
    adapter = _adapter(tmp_path, episodes=[_validation_episode(verifier_ok=False)])
    adapter.settle_validations(NOW)
    before = len(adapter.ledger.events())
    adapter.settle_validations(NOW)
    assert len(adapter.ledger.events()) == before, "one attempt, one rung"


def test_the_driver_runs_on_the_consume_pass(tmp_path: Path):
    """Structural: a driver nothing calls is a comment."""
    source = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
    reconcile_at = source.find("def reconcile(self")
    assert reconcile_at != -1
    body = source[reconcile_at:reconcile_at + 40000]
    assert "self.settle_validations(moment)" in body, (
        "the consume pass must settle examinations, or nothing ever will"
    )
    assert "self._request_validation(snapshot, moment)" in body
    assert body.find("self._request_validation(snapshot, moment)") < body.find(
        "self.settle_validations(moment)"), "request first, settle after: one rung per pass"
