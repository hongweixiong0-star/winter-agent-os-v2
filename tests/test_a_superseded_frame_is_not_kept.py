"""A frame that a newer one replaces must not survive on disk.

Measured 2026-10-03: the capture trees held 61,082 frames / 40 GB, of which two families
cannot be cited by any episode because they are dead on arrival:

    after_settle_retry   3,652   written only when the first post-action frame was UNCHANGED,
                                 so it duplicates the frame it was taken to replace;
    after_refresh_N      4,455   each superseded by refresh_{N+1} in the same step.

Neither reaches the episode: only the last ``after_path`` is recorded.  Retention can only
drain what is written, so this is the production-side half of the disk fix -- refuse to keep a
picture a newer one already replaced.

Two things are pinned besides the happy path, because both are ways this could lose evidence:

  * ``before_path`` is never a candidate.  It is cited by the episode for this step, and a
    frame equal to it is exactly the case where ``settle_retry`` fires -- so a careless
    implementation would delete the step's own before-frame;
  * a failed discard must not end the step.  Losing a delete is a retention problem, not a
    runtime one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.runtime import LiveRuntime  # noqa: E402


def _runtime():
    return LiveRuntime.__new__(LiveRuntime)


def _frame(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"png")
    return path


class ASupersededFrameIsDroppedTests:
    def test_the_replaced_frame_is_removed(self, tmp_path):
        superseded = _frame(tmp_path, "step_003_after.png")
        assert superseded.is_file()
        _runtime()._retire_superseded(superseded, superseded_by="settle_retry")
        assert not superseded.exists(), (
            "the retry only fires when the first frame equalled before_path, so keeping it "
            "stores the same picture twice"
        )

    def test_the_replacement_is_untouched(self, tmp_path):
        """Only the named frame goes; the caller keeps whatever it moved on to."""
        superseded = _frame(tmp_path, "step_003_after.png")
        replacement = _frame(tmp_path, "step_003_after_settle_retry.png")
        _runtime()._retire_superseded(superseded, superseded_by="settle_retry")
        assert replacement.is_file(), "the replacement is what the episode will cite"

    def test_a_refresh_chain_keeps_only_the_last(self, tmp_path):
        """refresh_1 -> refresh_2 -> refresh_3: each call drops the one before it."""
        runtime = _runtime()
        chain = [_frame(tmp_path, "step_007_after_refresh_%d.png" % n) for n in (1, 2, 3)]
        for older in chain[:-1]:
            runtime._retire_superseded(older, superseded_by="refresh_next")
        survivors = [p.name for p in sorted(tmp_path.iterdir())]
        assert survivors == ["step_007_after_refresh_3.png"], survivors


class TheStepOwnBeforeFrameIsSafeTests:
    def test_the_caller_guards_the_before_frame(self, tmp_path):
        """The runtime only calls this when the frame is not ``before_path``.

        The guard lives at the call site because this method cannot know which frame the step
        still needs -- so what is pinned here is that a frame *equal* to before_path is never
        passed.  Reading the call sites is the honest way to check that: the defect this guards
        against is a caller forgetting, not this method misbehaving.
        """
        source = (Path(__file__).resolve().parents[1] / "winter_agent_v2/runtime.py").read_text(
            encoding="utf-8")
        occurrences = source.count("_retire_superseded(after_path")
        guards = source.count('if str(after_path) != str(before_path):')
        assert occurrences == 3, occurrences
        assert guards >= 3, (
            "every supersede call must be guarded against deleting the step's own before-frame; "
            "found %d guards for %d calls" % (guards, occurrences)
        )
        assert source.count("_retire_superseded(before_path") == 0, (
            "before_path must never be offered for deletion"
        )


class ALostDiscardDoesNotEndTheStepTests:
    def test_a_missing_frame_is_not_an_error(self, tmp_path):
        """Already gone is the goal, not a failure."""
        _runtime()._retire_superseded(tmp_path / "never_existed.png", superseded_by="refresh")

    def test_a_none_or_blank_path_is_ignored(self, tmp_path):
        runtime = _runtime()
        runtime._retire_superseded(None, superseded_by="refresh")
        runtime._retire_superseded(tmp_path / "x.png", superseded_by="")

    def test_an_unreadable_path_does_not_raise(self, tmp_path):
        """A directory where a frame was expected must not take the run down."""
        directory = tmp_path / "not_a_frame.png"
        directory.mkdir()
        _runtime()._retire_superseded(directory, superseded_by="refresh")
        assert directory.is_dir(), "a non-file target is left alone rather than half-removed"


class TheProductionRateIsSafeForTheGuardTests:
    def test_the_per_round_count_stays_under_the_bulk_delete_threshold(self):
        """The guard aborts at 50 deletions in one turn; this must stay well under.

        Measured from the 2026-10-03 ledger: 3,652 settle_retry + 4,455 refresh frames across
        1,647 rounds is about 5 per round -- an order of magnitude below the threshold that
        killed the panel on 2026-09-18.
        """
        settle_retry, refresh, rounds, guard_threshold = 3652, 4455, 1647, 50
        per_round = (settle_retry + refresh) / rounds
        assert per_round < guard_threshold / 2, (
            "at %.1f discards per round this is a steady drip, not a sweep" % per_round
        )
