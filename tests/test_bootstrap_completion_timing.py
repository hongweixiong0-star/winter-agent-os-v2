"""A job finishing is not a capability being learned.

Operator §一/§二, and the measured defect is precise: `_settle` called
`KnowledgeBootstrapController.completion_hook(...)` on **every** outcome, including
`CODE_CHANGED`.  So "the agent stopped editing" was indistinguishable from "the capability was
learned", and the bootstrap advanced to the next capability before anything had been loaded,
examined, or used in ordinary play.

The correct rung is the last one in the chain:

    production_reuse + a real production_reuse_episode_id + state DONE
    -> completion_hook(outcome="PRODUCTION_REUSE_PASS")
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    CODE_CHANGED, DONE, EscalationLedger, EscalationQueueAdapter,
)

KEY = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"
NOW = datetime(2026, 9, 19, 0, 30, tzinfo=timezone.utc)
SOURCE = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")


class _NoBridge:
    def status(self, job_id):  # pragma: no cover
        raise AssertionError("this test does not talk to the gateway")


def _adapter(tmp_path: Path, rows: list[dict] | None = None) -> EscalationQueueAdapter:
    (tmp_path / "learning").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "learning/workbuddy_escalations.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in (rows or [])), encoding="utf-8")
    return EscalationQueueAdapter(root=tmp_path, ledger=EscalationLedger(path),
                                  bridge=_NoBridge())


# --------------------------------------------------------------------- where the hook lives


def test_the_settle_stage_no_longer_completes_a_capability():
    """Structural, because the *placement* is the fix.

    The settle path may record that the development work ended; it may not report the capability
    learned, and it may not advance the bootstrap.

    Sliced as ``_settle``'s own body -- from its ``def`` to the next method.  Two earlier
    versions got this wrong in different ways (a slice to a method defined earlier, then a slice
    between the two methods when ``_complete_bootstrap`` happens to come first), and both times
    the assertion could not have failed for the right reason.  Slicing by "the next ``def``" is
    the form that does not depend on how the file grew.
    """
    start = SOURCE.find("    def _settle(")
    assert start != -1, "the method must exist"
    following = SOURCE.find("\n    def ", start + 10)
    settle = SOURCE[start:following if following != -1 else len(SOURCE)]
    assert "development_completed" in settle, "settling must record an intermediate state"
    assert "KnowledgeBootstrapController" not in settle, (
        "a job that stopped editing is not a capability that was learned"
    )
    for premature in ("VERSION_ACTIVE", "LIVE_VERIFIED", "LIVE_TRIED"):
        assert f'outcome="{premature}"' not in settle, premature


def test_the_hook_runs_from_the_production_reuse_path():
    detector = SOURCE[SOURCE.find("    def detect_production_reuse"):
                      SOURCE.find("    def _complete_bootstrap")]
    assert "_complete_bootstrap(" in detector, (
        "the completion hook belongs after production reuse, and nowhere else"
    )
    assert '"PRODUCTION_REUSE_PASS"' in SOURCE
    # Counted by the form that *calls* it, not by the bare name: the name also appears in the
    # comment explaining why the call moved, and counting prose as a call site would make this
    # assertion fail for the wrong reason.
    assert SOURCE.count("KnowledgeBootstrapController(self.root).completion_hook(") == 1, (
        "one call site: a second one is how the wrong rung comes back"
    )


def test_the_completion_is_idempotent_by_evidence_not_by_a_flag(tmp_path: Path):
    """A second call for the same reuse episode must do nothing.

    Proved by pre-seeding the row the guard looks for: a memory flag would be lost on the
    restart this design exists to survive, so the evidence *is* the guard.
    """
    adapter = _adapter(tmp_path, [
        {"event": "knowledge_updated", "key": KEY, "capability": "SPEND_STAMINA_ON_BEAST",
         "outcome": "PRODUCTION_REUSE_PASS", "reuse_episode_id": "ep-prod-1"},
    ])
    record = adapter.ledger.snapshot().get(KEY)
    from winter_agent_v2.escalation_queue import EscalationRecord

    record = record or EscalationRecord(key=KEY, capability="SPEND_STAMINA_ON_BEAST",
                                        origin="bootstrap")
    before = len(adapter.ledger.events())
    assert adapter._complete_bootstrap(record, episode_id="ep-prod-1", moment=NOW) == []
    assert len(adapter.ledger.events()) == before, "a completed capability must not re-complete"


def test_a_non_bootstrap_trace_never_completes_the_bootstrap(tmp_path: Path):
    """A runtime escalation's next step is the runtime, not the preloader."""
    from winter_agent_v2.escalation_queue import EscalationRecord

    adapter = _adapter(tmp_path)
    record = EscalationRecord(key=KEY, capability="A", origin="queue")
    assert adapter._complete_bootstrap(record, episode_id="ep-1", moment=NOW) == []


def test_settling_a_bootstrap_record_writes_the_intermediate_state(tmp_path: Path):
    """The half that is still allowed, asserted so it is not removed by a future cleanup."""
    adapter = _adapter(tmp_path, [
        {"event": "escalation_created", "key": KEY, "capability": "SPEND_STAMINA_ON_BEAST",
         "skill": "SCAN_MAP_FOR_BEAST", "origin": "bootstrap", "state": "NEW",
         "recorded_at": "2026-09-19T00:00:00+00:00"},
        {"event": "submitted", "key": KEY, "job_id": "j1", "repo_head": "a" * 40,
         "recorded_at": "2026-09-19T00:01:00+00:00"},
        {"event": "job_state", "key": KEY, "job_id": "j1", "state": "WORKING",
         "recorded_at": "2026-09-19T00:02:00+00:00"},
    ])
    from winter_agent_v2.escalation_queue import RepoRevision, reconcile_outcome

    after = RepoRevision("b" * 40, 0, True)
    outcome, _, _ = reconcile_outcome(
        capability="SPEND_STAMINA_ON_BEAST", skill="SCAN_MAP_FOR_BEAST",
        submitted_at=NOW, job_verdict=DONE,
        before=RepoRevision("a" * 40, 0, True), after=after,
        wiring_problems=0, root=tmp_path, failure_type="NO_GOAL_PROGRESS",
        settled_at=NOW, from_development_job=True,
    )
    assert outcome == CODE_CHANGED, outcome
