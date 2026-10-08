"""The gate may only claim what its window can see, and the window was one goal wide.

``_episode_tail`` seeked back ``limit * 4096`` bytes, and its own comment called 4 KiB "a
generous upper bound" for an episode.  Measured 2026-10-08 on the live ledger: the mean row
is **13,508 B**, so ``EPISODE_TAIL=400`` returned **138 rows** -- 1 h 50 m of
``AVOID_STAMINA_WASTE`` and nothing else.  ``attempted`` held one goal out of the 24 that
had really run, ``streaks`` held one entry, and the no-progress rule -- the one rule that
exists to stop AUTO re-entering a path that is not advancing -- could only ever fire for the
goal that happened to dominate the tail.

These tests pin the two halves of the repair:

* the reader returns the rows it says it returns, for any row size, and honours the time
  window that defines "recent attempts";
* a goal whose attempts sit further back than the old read ever reached is still reachable,
  so its deferral fires.

The bounds are tested in the direction that matters: a cap may shrink the window and make
the gate quieter, and must never be able to invent a deferral.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from winter_agent_v2 import capability_gate
from winter_agent_v2.capability_gate import (
    EPISODE_TAIL,
    CapabilityGate,
    _episode_tail,
)
from winter_agent_v2.goal_library import GoalState, GoalStatus

#: A fixed clock, because the window is a time bound and a moving clock cannot be asserted.
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

#: Enough padding per row to reproduce the live ledger's shape.  The defect this file is
#: about only appears once a row is fatter than the 4 KiB the old reader assumed; 6,000 B is
#: deliberately under the measured 13,508 B so the fixtures stay small and still fail loudly.
FAT = 6000


def _row(stamp, goal_id, *, progress=False, run_id="run", pad=0, omit_stamp=False):
    row = {
        "episode_id": run_id,
        "goal_id": goal_id,
        "skill": "SKILL",
        "goal_progress": progress,
    }
    if not omit_stamp:
        row["recorded_at"] = stamp.isoformat()
    if pad:
        row["payload"] = "x" * pad
    return row


def _ledger(root, rows):
    """Write the rows in the order given, and refuse to write one a real writer could not.

    This guard exists because a fixture is easy to build backwards, and a backwards fixture
    silently turns a test into a test of something else: measured while writing this file, a
    "1,200 rows over 40 hours" fixture built newest-first made the read -- which reads from
    the *end* -- start at the oldest row, stop immediately, and return **zero** rows.  The
    real ledger is append-only and its timestamps rise with file order (measured: 0
    inversions in 10,179 live rows), so a descending fixture is not a harder case, it is a
    different one, and it must be written on purpose rather than by accident.
    """
    stamps = [row.get("recorded_at") for row in rows if row.get("recorded_at")]
    if stamps != sorted(stamps):
        raise AssertionError(
            "fixture timestamps must rise with file order, as the real ledger's do"
        )
    path = Path(root) / "learning" / "episodes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def _goal(goal_id):
    return GoalState(goal_id, GoalStatus.READY, available_skills=("SKILL",))


class TheReaderReturnsWhatItSaysTests(unittest.TestCase):
    """``limit`` rows means ``limit`` rows, whatever one row weighs."""

    def test_a_row_fatter_than_the_old_bound_does_not_shorten_the_tail(self):
        """The regression, in the smallest fixture that shows it.

        1,000 rows of 6,000 B each, ask for 400.  The old reader seeked back
        ``400 * 4096`` B and returned **273** rows -- 32% short -- and every rule downstream
        believed it had seen 400.  6 MB also forces the read to stop before the start of the
        file, which is the path where the first line is a partial record.
        """
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(seconds=1000 - index), "G", pad=FAT)
                for index in range(1000)
            ]
            path = _ledger(root, rows)

            tail = _episode_tail(path, limit=400, hours=None)

            self.assertEqual(len(tail), 400, "the read must deliver the rows it was asked for")
            self.assertEqual(tail[-1]["goal_id"], rows[-1]["goal_id"])
            self.assertLess(path.stat().st_size, len(rows) * (FAT + 200))
            # The partial first line was dropped, not counted: every returned row is a
            # complete object with the field the caller reads.
            for row in tail:
                self.assertIn("recorded_at", row)

    def test_a_very_fat_row_still_returns_the_whole_tail(self):
        """40,000 B per row: the old bound returned 5 of the 50 asked for."""
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(minutes=50 - index), "G", pad=40_000)
                for index in range(50)
            ]
            path = _ledger(root, rows)

            self.assertEqual(len(_episode_tail(path, limit=50, hours=None)), 50)

    def test_the_read_stops_at_the_start_of_the_file(self):
        """Asking for more rows than exist is not an error, and loses no row."""
        with TemporaryDirectory() as root:
            rows = [_row(NOW - timedelta(minutes=10 - index), "G") for index in range(10)]
            path = _ledger(root, rows)

            tail = _episode_tail(path, limit=500, hours=None)

            self.assertEqual([row["goal_id"] for row in tail], ["G"] * 10)
            self.assertEqual(len(tail), len(rows))

    def test_a_missing_ledger_defers_nothing(self):
        with TemporaryDirectory() as root:
            self.assertEqual(_episode_tail(Path(root) / "nope.jsonl"), [])

    def test_a_broken_line_is_skipped_rather_than_ending_the_read(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "learning" / "episodes.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '{"recorded_at": "2026-10-08T11:00:00+00:00", "goal_id": "G"}\n'
                "this line is not json\n"
                '{"recorded_at": "2026-10-08T11:30:00+00:00", "goal_id": "G"}\n',
                encoding="utf-8",
            )
            self.assertEqual(len(_episode_tail(path, hours=None)), 2)


class TheWindowIsATimeBoundTests(unittest.TestCase):
    """``EPISODE_WINDOW_HOURS`` decides which attempts are still evidence."""

    def test_attempts_older_than_the_window_are_not_read(self):
        with TemporaryDirectory() as root:
            rows = [
                # 96 attempts 30 minutes apart -- 48 hours -- written oldest first.
                _row(NOW - timedelta(minutes=30 * (95 - step)), "G")
                for step in range(96)
            ]
            path = _ledger(root, rows)

            tail = _episode_tail(path, hours=24, now=NOW)

            self.assertTrue(tail)
            cutoff = NOW - timedelta(hours=24)
            for row in tail:
                self.assertGreaterEqual(datetime.fromisoformat(row["recorded_at"]), cutoff)
            self.assertLess(len(tail), len(rows), "the window must exclude the older half")

    def test_the_window_can_be_turned_off_for_a_caller_that_wants_the_cap_alone(self):
        with TemporaryDirectory() as root:
            rows = [_row(NOW - timedelta(minutes=59 - step), "G") for step in range(60)]
            path = _ledger(root, rows)

            self.assertEqual(len(_episode_tail(path, limit=25, hours=None)), 25)

    def test_a_row_the_reader_cannot_place_in_time_is_kept(self):
        """Discarding evidence it cannot read is how a count drifts from its ledger."""
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(hours=40), "G"),
                _row(NOW, "G", omit_stamp=True),
            ]
            path = _ledger(root, rows)

            tail = _episode_tail(path, hours=24, now=NOW)

            self.assertEqual(len(tail), 1)
            self.assertNotIn("recorded_at", tail[0])


class ACapMayOnlyShrinkTheWindowTests(unittest.TestCase):
    """A bound that can invent a deferral is worse than no bound."""

    def test_a_small_byte_budget_returns_fewer_rows_and_never_more(self):
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(seconds=2000 - index), f"G{index % 4}", pad=FAT)
                for index in range(2000)
            ]
            path = _ledger(root, rows)

            everything = _episode_tail(path, limit=EPISODE_TAIL, hours=None)
            with mock.patch.object(capability_gate, "EPISODE_TAIL_BYTES", 40_000):
                capped = _episode_tail(path, limit=EPISODE_TAIL, hours=None)

            self.assertLess(len(capped), len(everything))
            self.assertEqual(capped, everything[-len(capped):],
                             "a cap trims from the old end and changes nothing else")


class TheGateUsesTheWindowTests(unittest.TestCase):
    """End to end: what the gate can see, and therefore what it can defer."""

    def _load(self, root, **kwargs):
        kwargs.setdefault("now", NOW)
        kwargs.setdefault("no_progress_threshold", 3)
        return CapabilityGate.load(root, **kwargs)

    def test_a_goal_three_runs_back_is_still_reachable(self):
        """The coverage the old window could not buy.

        ``G`` makes three attempts in three runs, then 200 rows about another goal land on
        top of them.  The old read returned the newest 138 rows -- all noise -- so ``G`` was
        not in the window at all: not "not stalled", but **invisible**, with no rule able to
        speak about it.  The attempts stay inside the 30-minute probe window on purpose:
        further back the deferral is correct and *lapses* (``_probe_anchor`` measures from
        the last attempt, so a stale one is re-admitted), which would test the probe timer
        rather than the window.
        """
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(minutes=25), "G", run_id="g1"),
                _row(NOW - timedelta(minutes=20), "G", run_id="g2"),
                _row(NOW - timedelta(minutes=15), "G", run_id="g3"),
            ]
            rows += [
                _row(NOW - timedelta(seconds=840 - index), "OTHER", run_id="noise")
                for index in range(200)
            ]
            _ledger(root, rows)

            gate = self._load(root)

            self.assertIn("G", gate.attempted)
            found = gate.blocks(_goal("G"), now=NOW)
            self.assertIsNotNone(found, "three no-progress runs 200 rows back must still defer")
            self.assertEqual(found.streak, 3)

    def test_an_attempt_outside_the_window_does_not_count(self):
        """The other direction, so the depth above is a window and not just "read more"."""
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(hours=48), "G", run_id="old1"),
                _row(NOW - timedelta(hours=47), "G", run_id="old2"),
                _row(NOW - timedelta(hours=46), "G", run_id="old3"),
                _row(NOW - timedelta(minutes=5), "OTHER", run_id="fresh"),
            ]
            _ledger(root, rows)

            gate = self._load(root)

            self.assertNotIn("G", gate.attempted)
            self.assertIsNone(gate.blocks(_goal("G"), now=NOW))

    def test_load_reads_the_ledger_and_the_window_with_one_clock(self):
        """A boundary and the rows it bounds must not disagree about the time."""
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(hours=30), "OUTSIDE", run_id="r2"),
                _row(NOW - timedelta(minutes=70), "INSIDE", run_id="r1"),
            ]
            _ledger(root, rows)

            gate = self._load(root)

            self.assertIn("INSIDE", gate.attempted)
            self.assertNotIn("OUTSIDE", gate.attempted)


class TheEarlyStopChangesNothingTests(unittest.TestCase):
    """Reading less must not mean *deciding* differently.

    The read stops as soon as the oldest row it has is older than the window.  That is only
    safe while ``recorded_at`` rises with file order, so the equivalence is asserted rather
    than assumed: the same fixture is read with the early stop and with the time bound
    removed, and the two must agree exactly.  The failure this guards against is specific and
    one-directional -- a *progress* row dropped by an over-eager stop would hold a streak
    open, and a streak that should have been reset is a false deferral.
    """

    def test_stopping_early_returns_exactly_what_the_full_read_would(self):
        with TemporaryDirectory() as root:
            # 1,200 fat rows over 40 hours: the file spans several 1 MiB chunks and half its
            # rows are outside the window, so the read really does stop part-way rather than
            # falling through to the end of the file.  Small rows would fit in one chunk and
            # the early stop would never be exercised -- a fixture that cannot show the
            # difference this test is about.
            rows = [
                _row(NOW - timedelta(minutes=2 * (1199 - step)), f"G{step % 5}",
                     run_id=f"r{step}", pad=FAT)
                for step in range(1200)
            ]
            path = _ledger(root, rows)
            self.assertGreater(path.stat().st_size, 4 << 20)

            stopped_early = _episode_tail(path, limit=EPISODE_TAIL, hours=24, now=NOW)
            everything_then_filtered = [
                row for row in _episode_tail(path, limit=EPISODE_TAIL, hours=None, now=NOW)
                if datetime.fromisoformat(row["recorded_at"]) >= NOW - timedelta(hours=24)
            ]

            self.assertTrue(stopped_early)
            self.assertEqual(stopped_early, everything_then_filtered)
            # And it really did stop early rather than reading the lot.
            self.assertLess(len(stopped_early), len(rows))

    def test_a_progress_row_inside_the_window_is_never_dropped_by_the_stop(self):
        """The one-directional failure, stated as a case.

        The newest run shows progress; behind it are enough no-progress runs that a short
        window would keep a streak alive.  The progress row must reach the gate, which is
        what makes the goal *not* deferred.
        """
        with TemporaryDirectory() as root:
            rows = [
                _row(NOW - timedelta(minutes=40), "G", run_id="old1"),
                _row(NOW - timedelta(minutes=30), "G", run_id="old2"),
                _row(NOW - timedelta(minutes=20), "G", run_id="old3"),
                _row(NOW - timedelta(minutes=5), "G", progress=True, run_id="newest"),
            ]
            _ledger(root, rows)

            gate = CapabilityGate.load(root, now=NOW, no_progress_threshold=3)

            self.assertIsNone(
                gate.blocks(_goal("G"), now=NOW),
                "the progress row is inside the window and must reset the streak",
            )


if __name__ == "__main__":
    unittest.main()
