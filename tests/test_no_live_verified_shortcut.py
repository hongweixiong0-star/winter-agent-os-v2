"""A developed trace may not be certified by a production success (operator §4).

The shortcut this closes was the *first* branch of `reconcile_outcome`: if any production
episode with `verifier_ok` existed on a tree that differed from dispatch time, the outcome was
LIVE_VERIFIED.  For a trace that came from a WorkBuddy job that is false credit twice over --

* the episode proves the capability works on the tree it ran, not on the version the job
  produced, and `version_changed_from` admits *any* differing tree, including a third one;
* the same episode would exist if the agent had done nothing, so nothing about it is evidence
  that the job taught V2 anything.

The operator's rule is that a developed trace goes VERSION_ACTIVE -> LIVE_VERIFY_PENDING ->
Development Validation -> LIVE_TRIED -> LIVE_VERIFIED.  The old production-proof logic is kept
for the case it was written for: a capability that has no job at all, where the runtime proving
it to itself *is* the proof.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import escalation_queue as q  # noqa: E402

NOW = datetime(2026, 9, 18, 22, 0, tzinfo=timezone.utc)
DISPATCH = "a" * 40
PRODUCED = "b" * 40


def _episodes(root: Path, rows: list[dict]) -> None:
    (root / "learning").mkdir(parents=True, exist_ok=True)
    (root / "learning/episodes.jsonl").write_text(
        "\n".join(__import__("json").dumps(row) for row in rows) + "\n", encoding="utf-8")


def _production_episode(revision: str) -> dict:
    return {
        "episode_id": "ep-prod-1", "capability": "SPEND_STAMINA_ON_BEAST",
        "skill": "SCAN_MAP_FOR_BEAST",
        "recorded_at": (NOW + timedelta(minutes=5)).isoformat(),
        "repo_revision": revision, "verifier_ok": True, "goal_progress": True,
        "before_screenshot": "dataset/raw/a.png", "after_screenshot": "dataset/raw/b.png",
    }


def _reconcile(root: Path, **over):
    kwargs = dict(
        capability="SPEND_STAMINA_ON_BEAST", skill="SCAN_MAP_FOR_BEAST",
        submitted_at=NOW, job_verdict="DONE",
        before=q.RepoRevision(DISPATCH, 0, True), after=q.RepoRevision(PRODUCED, 0, True),
        wiring_problems=0, root=root, failure_type="NO_GOAL_PROGRESS",
        settled_at=NOW + timedelta(minutes=1),
    )
    kwargs.update(over)
    return q.reconcile_outcome(**kwargs)


def test_a_production_success_cannot_certify_a_developed_trace():
    """The operator's counterexample 4, verbatim."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _episodes(root, [_production_episode(PRODUCED)])
        outcome, explanation, _ = _reconcile(root, from_development_job=True)
    assert outcome != q.LIVE_VERIFIED, "a production success is not the job's proof"
    assert outcome == q.VERSION_ACTIVATION_PENDING, (
        "it must route into the activation/validation ladder, not end at a verdict"
    )
    assert "development job" in explanation
    assert "真机校准" in explanation


def test_the_same_episode_still_certifies_a_capability_with_no_job():
    """The old logic is kept for what it was written for: the runtime proving itself."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _episodes(root, [_production_episode(PRODUCED)])
        outcome, explanation, episodes = _reconcile(root, from_development_job=False)
    assert outcome == q.LIVE_VERIFIED
    assert episodes, "the evidence is still returned"


def test_both_production_call_sites_carry_the_flag():
    """The enforcement point, stated exactly.

    ``from_development_job`` defaults to ``False``, i.e. the *permissive* branch, because the
    same pure function also answers "did the runtime prove a capability that has no job at
    all" -- a case where the production-proof logic is correct and the default must let it
    through.  So the guard is enforced by the two call sites in the adapter, each of which
    derives it from the record's own job id.

    That is a real residual gap and it is named rather than papered over: a *future* caller that
    forgets the keyword gets the shortcut.  Making the default ``True`` would be the safer
    shape, and it is deliberately not done here because it changes the meaning of the
    no-job case and the existing reconcile tests encode that meaning -- changing both at once,
    at the end of a session, is how a rule gets broken in the name of enforcing it.
    """
    source = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
    assert source.count("from_development_job=bool(record.job_id)") == 2, (
        "both reconcile call sites must carry it"
    )
    # And the default is still the documented, permissive one.
    assert "from_development_job: bool = False" in source
