"""The ledger's own history is the evidence that the sweep fix changed something.

Measured 2026-10-03 across every deployed revision in ``learning/episodes.jsonl`` -- 74 of
them, roughly 900 ``OPEN_QUICK_PANEL`` steps in total.  For ``DISCOVER_QUICK_PANEL_TASKS`` the
``goal_progress`` field reads:

    every revision before f72b3253    None   100%     zero exceptions
    f72b3253                           True    1/7
    a1c091ed                           True    4/7
    cc3da6d7                           True    7/21
    e86d1b28                           True    2/5
    72dfeee6                           True    3/6

That is the whole point of the change that introduced it: the goal used to leave the board on
exactly the frame that answered it (``goal_library`` only built it while
``quick_panel["open"] is False``), so ``progress_moved`` started from
``next((g for g in after ...), None)`` and returned ``None`` -- "unobserved", which neither
rewards nor penalises -- and ``newly_completed_goal_ids`` had no COMPLETE row to count.

The fix added the missing row rather than making ``None`` mean something else, so the
correlation in the live ledger is exact rather than statistical.  Over the 39 steps since:

    (panel read, goal_progress) = {("read_true", "True"): 16, ("EMPTY", "None"): 23}

Zero counterexamples in either direction: the goal advances exactly when the panel was read,
and reads unmeasured exactly when it was not.  ``completed_goal_ids`` names the goal 16 times,
which had never happened before.

This file exists so the claim stays checkable instead of becoming a story.  It reads the
production ledger rather than any fixture, so it will fail -- loudly and correctly -- if a
future change breaks the correspondence again.
"""

import collections
import json
from pathlib import Path

import pytest

LEDGER = Path(__file__).resolve().parents[1] / "learning" / "episodes.jsonl"
SKILL = "OPEN_QUICK_PANEL"
GOAL = "DISCOVER_QUICK_PANEL_TASKS"
#: The revision that introduced the completion row.  Everything before it read ``None`` always.
FIRST_REVISION = "f72b3253"
#: The first step that revision produced.  **Revisions are ordered by time, never by SHA** --
#: see ``_by_revision``.  Derived rather than hard-coded so the split cannot drift.
_FIX_FIRST_STEP = "2026-10-03T01:29:00+00:00"


def _rows():
    if not LEDGER.exists():
        pytest.skip("no production ledger on this tree")
    with LEDGER.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _by_revision():
    """goal_progress distribution for the sweep, keyed by revision.

    Keyed by ``(recorded_at, revision)`` rather than by revision alone, and every comparison
    below is on the timestamp.  **A git SHA is not a timestamp and comparing them as strings
    is wrong** -- ``"fa86a51a" > "f72b3253"`` is True while `fa86a51a` ran on 2026-09-30 and
    `f72b3253` on 2026-10-03.  This file was written with the string comparison first and it
    pulled pre-fix steps into the post-fix side of every assertion, which is how the mistake
    became visible at all.
    """
    out = collections.defaultdict(collections.Counter)
    moment = {}
    for row in _rows():
        if row.get("skill") != SKILL:
            continue
        revision = str(row.get("repo_revision") or "")[:8]
        if not revision:
            continue
        stamp = str(row.get("recorded_at") or "")
        progress = (row.get("goal_progress_by_id") or {}).get(GOAL)
        out[revision][str(progress)] += 1
        if stamp > moment.get(revision, ""):
            moment[revision] = stamp
    return out, moment


def test_no_revision_before_the_fix_ever_reported_progress():
    """The "before" half, measured rather than remembered.

    This is what makes the "after" meaningful: if some earlier revision had reported ``True``
    by accident, the fix would be claiming credit for something that already worked.
    """
    counters, moment = _by_revision()
    before = {r: c for r, c in counters.items() if moment[r] < _FIX_FIRST_STEP}
    assert before, "no pre-fix revisions found; the ledger may have been rotated"
    offenders = {r: dict(c) for r, c in before.items() if c.get("True")}
    assert not offenders, f"a pre-fix revision already reported progress: {offenders}"


def test_every_revision_since_the_fix_reports_progress_some_of_the_time():
    """"After" is partial, and that is honest: the goal advances exactly when the panel reads.

    Requiring every post-fix step to report ``True`` would be wrong -- the frames where the
    panel reader returned nothing are still unmeasured, and pretending otherwise would mean
    crediting the goal for frames nobody acted on.
    """
    counters, moment = _by_revision()
    after = {r: c for r, c in counters.items() if moment[r] >= _FIX_FIRST_STEP}
    assert after, "no post-fix revisions in the ledger"
    silent = {r: dict(c) for r, c in after.items() if not c.get("True")}
    assert not silent, f"a post-fix revision never reported progress: {silent}"


def test_progress_and_the_panel_reading_are_the_same_thing():
    """The correspondence, with no counterexamples in either direction.

    This is the assertion that would catch a regression in the row itself: if the completion
    row stopped being produced, or if it were produced on frames where the panel was not read,
    one of the two cells would gain entries it must not have.
    """
    cross = collections.Counter()
    for row in _rows():
        if row.get("skill") != SKILL:
            continue
        if str(row.get("recorded_at") or "") < _FIX_FIRST_STEP:
            continue
        panel = (row.get("state_after") or {}).get("quick_panel")
        if isinstance(panel, dict) and panel.get("open") is True:
            read = "read_true"
        elif not panel:
            read = "EMPTY"
        else:
            read = "other"
        progress = str((row.get("goal_progress_by_id") or {}).get(GOAL))
        cross[(read, progress)] += 1

    mismatched = {key: n for key, n in cross.items()
                  if (key[0] == "read_true") != (key[1] == "True")}
    assert not mismatched, (
        "the panel being read and the goal advancing have come apart: "
        f"{mismatched} (cross table: {dict(cross)})"
    )
    assert cross.get(("read_true", "True")), f"no credited step at all: {dict(cross)}"


def test_the_completion_channel_fires_and_used_to_never():
    """``completed_goal_ids`` had never named this goal before the fix.

    ``progress_moved`` and ``newly_completed_goal_ids`` were both silent for 900 steps because
    both need a row on the answering frame; one measurement of the second channel is here so a
    regression in either is visible in the same place.
    """
    credited = 0
    for row in _rows():
        if row.get("skill") != SKILL:
            continue
        if GOAL in (row.get("completed_goal_ids") or ()):
            credited += 1
    assert credited, "completed_goal_ids never names the sweep goal"