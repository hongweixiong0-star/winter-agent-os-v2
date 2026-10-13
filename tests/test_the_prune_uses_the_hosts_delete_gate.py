"""The pruned crop must go through the host's delete gate, not straight to ``unlink``.

Why this exists (2026-10-14)
---------------------------
``UiCandidateStore.prune`` removes the crops a dropped candidate owns.  It does that through
``delete_past_the_hosts_gate`` -- the guard ``retention.py`` documents as the production half of
a rule the test suite learned first: a sandbox around this machine intercepts the delete and,
once one turn has removed more than 50 files, raises ``SystemExit(1)`` *instead of* deleting.
An uncaught ``SystemExit`` prints no traceback and exits 1, which is the shape of the crash
record measured 2026-10-08 (four in 100 seconds, the watchdog's recovery budget spent, AUTO
paused).  ``prune`` is one of that guard's own named call sites: its docstring lists "a pruned
crop" among the ``missing_is_fine`` cases.

But ``ui_collection.py`` never imported the name.  The calls sat inside ``try/except OSError``,
and ``NameError`` is not an ``OSError``, so the first prune that actually had a candidate to drop
would have raised instead of deleting.  Nothing caught it: the file's own retention test fails
earlier (its store is never populated past the limit, so ``prune`` returns ``[]`` at the
``len(self._records) <= limit`` guard) and never reaches the call.

So this test does the one thing that test cannot: it fills the store past the limit with records
whose crops are really on disk, then prunes.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from winter_agent_v2.ui_collection import UiCandidateStore

BOX = {"x_norm": 0.4, "y_norm": 0.4, "w_norm": 0.2, "h_norm": 0.1}


def _store(tmp_path: Path) -> UiCandidateStore:
    return UiCandidateStore(tmp_path / "candidates", manifest=tmp_path / "manifest.json")


def _stage(store: UiCandidateStore, frame: Path, count: int) -> None:
    for index in range(count):
        staged = store.stage(
            frame_path=frame, page="HOME", semantic=f"ROW_{index}", box_norm=BOX
        )
        assert staged is not None, "the fixture frame must yield a candidate"


def test_prune_drops_records_and_removes_the_crops_it_owns(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (200, 200), "white").save(frame)
    store = _store(tmp_path)
    _stage(store, frame, 6)
    assert len(store.all()) == 6

    dropped = store.prune(limit=2)

    assert dropped, "prune must drop the records past the limit"
    assert len(store.all()) == 2
    for candidate_id in dropped:
        assert not (store.root / candidate_id).exists(), (
            "a dropped candidate's crop directory must be gone"
        )


def test_prune_keeps_a_verified_record_and_its_crops(tmp_path):
    """The other half of §九: pruned are the hypotheses, never what a real step proved."""
    frame = tmp_path / "frame.png"
    Image.new("RGB", (200, 200), "white").save(frame)
    store = _store(tmp_path)
    _stage(store, frame, 6)
    kept = store.all()[0]
    kept.verification_status = "VERIFIED"

    dropped = store.prune(limit=1)

    assert kept.candidate_id not in dropped
    assert (store.root / kept.candidate_id).exists()


def test_the_prune_does_not_raise_when_a_crop_is_already_gone(tmp_path):
    """``missing_is_fine`` is the whole point: a crop that is not there is not a failure."""
    frame = tmp_path / "frame.png"
    Image.new("RGB", (200, 200), "white").save(frame)
    store = _store(tmp_path)
    _stage(store, frame, 4)
    for record in store.all():
        directory = store.root / record.candidate_id
        for name in ("element.png", "context.png", "metadata.yaml"):
            (directory / name).unlink(missing_ok=True)

    dropped = store.prune(limit=1)

    assert dropped
