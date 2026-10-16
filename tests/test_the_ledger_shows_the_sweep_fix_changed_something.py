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

Re-measured 2026-10-16 (the pre-fix era has since rotated out of the live ledger, so the
"before" half below is a skip now): 53 post-fix revisions, 491 read frames -- 490
read-and-``True`` against one read-and-``None``, a ``2026-10-08`` ``after_settle_retry`` frame
whose page the reader could not classify (``"UNKNOWN"``).  On such a frame the goal's own
rows are not emitted at all -- both of them require a classified page -- so ``None`` there
is "not observable", the documented third state, and not a counterexample.  The two
directions that carry the claim survive with zero exceptions: nothing is credited without a
read, and nothing that read the panel is recorded as no progress.

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
    if not before:
        # The ledger this file reads is the live one, capped at 10k rows, and the pre-fix era
        # rotated out of it long ago (measured 2026-10-16: 13 days after the fix, zero
        # pre-fix revisions remain).  The "before" half of the claim is therefore no longer
        # measurable from this artifact -- a skip with the reason is the honest state, and the
        # "after" halves below still hold against the post-fix rows that do remain.
        pytest.skip("no pre-fix revisions left in learning/episodes.jsonl: the ledger has "
                    "rotated past 2026-10-03, so the before/after comparison this test was "
                    "written for cannot be measured from it any more")
    offenders = {r: dict(c) for r, c in before.items() if c.get("True")}
    assert not offenders, f"a pre-fix revision already reported progress: {offenders}"


def test_every_revision_since_the_fix_reports_progress_some_of_the_time():
    """"After" is partial, and that is honest: the goal advances exactly when the panel reads.

    Requiring every post-fix step to report ``True`` would be wrong -- the frames where the
    panel reader returned nothing are still unmeasured, and pretending otherwise would mean
    crediting the goal for frames nobody acted on.

    A revision can be silent for the same honest reason.  Five of them (``23c48a5c``,
    ``e2bc6d97``, ``22619d36``, ``5d60f1d2``, ``de3b1066``, measured 2026-10-16) are
    single-step runs whose one frame carried no panel at all, so there was nothing to
    report and ``None`` is that row's correct value.  The regression this test exists to
    catch is the other combination: a revision that *did* read the panel on a classified
    page and still never reported progress -- because on the frame that reads the panel
    the goal is on the board, and the row below measures that the two move together.
    """
    counters, moment = _by_revision()
    after = {r: c for r, c in counters.items() if moment[r] >= _FIX_FIRST_STEP}
    assert after, "no post-fix revisions in the ledger"
    reads = collections.Counter()
    for row in _rows():
        if row.get("skill") != SKILL:
            continue
        if str(row.get("recorded_at") or "") < _FIX_FIRST_STEP:
            continue
        after_state = row.get("state_after") or {}
        panel = after_state.get("quick_panel")
        page = str(after_state.get("page") or "")
        # ``UNKNOWN`` is the page reader declining to classify a mid-transition frame, not
        # a second way of reading the panel: on such a frame the goal's own rows are not
        # emitted (both branches of the emitter require a classified page), so ``None``
        # there is "off the board" rather than "read and silent".  Counted as not-a-read.
        if (isinstance(panel, dict) and panel.get("open") is True
                and page not in ("", "UNKNOWN")):
            reads[str(row.get("repo_revision") or "")[:8]] += 1
    silent = {r: dict(c) for r, c in after.items() if not c.get("True")}
    unexplained = {r: c for r, c in silent.items() if reads.get(r)}
    assert not unexplained, (
        "a post-fix revision read the panel on a classified page but never reported "
        f"progress: {unexplained} (all silent revisions: {silent})"
    )


def test_progress_and_the_panel_reading_are_the_same_thing():
    """The correspondence, with its one documented third state spelled out.

    This is the assertion that would catch a regression in the row itself: if the completion
    row stopped being produced, or if it were produced on frames where the panel was not read,
    one of the two cells would gain entries it must not have.

    The third state is ``None`` -- "the goal was not observable", which the meter documents as
    *not* the same as "no progress" (it neither rewards nor penalises; only ``False`` feeds
    the streak).  On a *read* frame it has exactly one honest source: the page reader
    declining to classify the frame, because both of the goal's own rows are emitted only on
    a classified page, so on ``page == "UNKNOWN"`` the panel can be read while the goal is
    legitimately off the board.  Measured 2026-10-16: exactly one such row across 491 reads
    (``2026-10-08T21:04:45``, an ``after_settle_retry`` frame).  What must not appear is
    ``None`` on a read frame whose page *was* classified -- that would be the goal getting
    dropped from a board it was supposed to be on, quietly undoing the fix.
    """
    cross = collections.Counter()
    unobserved_on_a_classified_page = []
    for row in _rows():
        if row.get("skill") != SKILL:
            continue
        if str(row.get("recorded_at") or "") < _FIX_FIRST_STEP:
            continue
        after_state = row.get("state_after") or {}
        panel = after_state.get("quick_panel")
        if isinstance(panel, dict) and panel.get("open") is True:
            read = "read_true"
        elif not panel:
            read = "EMPTY"
        else:
            read = "other"
        progress = str((row.get("goal_progress_by_id") or {}).get(GOAL))
        cross[(read, progress)] += 1
        if read == "read_true" and progress == "None":
            page = str(after_state.get("page") or "")
            if page not in ("", "UNKNOWN"):
                unobserved_on_a_classified_page.append(
                    (str(row.get("recorded_at") or ""), page, row.get("repo_revision")))

    credited_without_a_read = {key: n for key, n in cross.items()
                               if key[1] == "True" and key[0] != "read_true"}
    assert not credited_without_a_read, (
        "the goal advanced on a frame whose panel was not read: "
        f"{credited_without_a_read} (cross table: {dict(cross)})"
    )
    penalised_while_read = {key: n for key, n in cross.items()
                            if key[0] == "read_true" and key[1] == "False"}
    assert not penalised_while_read, (
        f"a frame that read the panel was recorded as no progress: {penalised_while_read} "
        f"(cross table: {dict(cross)})"
    )
    assert not unobserved_on_a_classified_page, (
        "a read frame with a classified page produced no verdict at all: "
        f"{unobserved_on_a_classified_page}"
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