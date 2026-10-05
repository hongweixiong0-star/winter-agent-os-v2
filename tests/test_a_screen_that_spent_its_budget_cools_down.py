"""§48's per-screen budget must outlive the run that spent it.

The within-run half already worked; this pins the half that was missing.  The arithmetic that
established it: ``learning/ui_venus_online.jsonl`` held 228 ``VENUS_CALLED`` rows across 13
``request_id``s, one screen asked 84 times -- about 42 runs at the advisor's two per run, because
``runtime.py`` rebuilds the advisor fresh per cycle and ``_per_screen`` is an in-memory dict.

So these tests are about the three circuit-breaker states and, just as importantly, about the two
directions the rule could fail in: a screen that must be refused is refused, a screen that must be
reconsidered IS reconsidered, and a screen with no attempt history is never collateral damage.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import venus_screen_budget as sb

T0 = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
SCREEN = "home__control__36e65c39"


def _store(tmp_path: Path) -> Path:
    return tmp_path / "learning" / "venus_screen_attempts.json"


# -- the states ----------------------------------------------------------------


def test_a_screen_with_no_history_is_allowed(tmp_path):
    allowed, why = sb.allow(SCREEN, path=_store(tmp_path), now=T0)
    assert allowed
    assert why == "first_attempt"


def test_the_budget_is_two_attempts_then_refused(tmp_path):
    """§48: 同一 Screen 默认最多约 2 次 Venus 尝试."""
    store = _store(tmp_path)
    assert sb.allow(SCREEN, path=store, now=T0)[0] is True
    sb.record(SCREEN, path=store, now=T0)
    assert sb.allow(SCREEN, path=store, now=T0)[0] is True
    sb.record(SCREEN, path=store, now=T0)

    allowed, why = sb.allow(SCREEN, path=store, now=T0)
    assert not allowed, "a third attempt inside the cooldown is the loop §48 forbids"
    assert why.startswith("screen_cooldown_active")


def test_the_budget_survives_a_new_process(tmp_path):
    """The whole point: it is the store, not the instance, that remembers.

    This is the defect in one test.  A fresh ``load`` stands in for a fresh advisor, which is what
    ``runtime.py`` builds every cycle.
    """
    store = _store(tmp_path)
    for _ in range(sb.BUDGET_PER_SCREEN):
        sb.record(SCREEN, path=store, now=T0)
    assert sb.load(store)[SCREEN]["attempts"] == sb.BUDGET_PER_SCREEN
    assert sb.allow(SCREEN, path=store, now=T0 + timedelta(seconds=5))[0] is False


def test_a_screen_is_reconsidered_after_the_cooldown(tmp_path):
    """**Liveness**, and the reason this is a deferral rather than a starvation (§36/§38).

    A screen that becomes readable an hour later must get another look, or the fix would trade an
    infinite loop for a permanent hole.
    """
    store = _store(tmp_path)
    for _ in range(sb.BUDGET_PER_SCREEN):
        sb.record(SCREEN, path=store, now=T0)

    later = T0 + timedelta(seconds=sb.COOLDOWN_SECONDS + 1)
    allowed, why = sb.allow(SCREEN, path=store, now=later)
    assert allowed, "a cooled-down screen must be reconsidered"
    assert why == "probe_after_cooldown"


def test_exactly_one_probe_fits_in_each_cooldown_window(tmp_path):
    """Half-open, without a second field: recording the probe restarts the cooldown."""
    store = _store(tmp_path)
    for _ in range(sb.BUDGET_PER_SCREEN):
        sb.record(SCREEN, path=store, now=T0)
    later = T0 + timedelta(seconds=sb.COOLDOWN_SECONDS + 1)

    assert sb.allow(SCREEN, path=store, now=later)[0] is True
    sb.record(SCREEN, path=store, now=later)          # the probe was spent
    assert sb.allow(SCREEN, path=store, now=later + timedelta(seconds=1))[0] is False
    assert sb.allow(SCREEN, path=store, now=later + timedelta(seconds=sb.COOLDOWN_SECONDS + 1))[0]


def test_the_cooldown_uses_the_projects_existing_number(tmp_path):
    """One rule, one cooldown.  ``unknown_advisor`` already decided this for the same shape."""
    from winter_agent_v2 import unknown_advisor

    assert sb.COOLDOWN_SECONDS == unknown_advisor.REQUEST_COOLDOWN_SECONDS
    assert sb.BUDGET_PER_SCREEN == unknown_advisor.MAX_REQUESTS_PER_RUN


# -- what must NOT be swallowed ------------------------------------------------


def test_a_different_screen_is_untouched(tmp_path):
    """The bound is per screen, so spending one must not refuse another."""
    store = _store(tmp_path)
    for _ in range(sb.BUDGET_PER_SCREEN + 3):
        sb.record(SCREEN, path=store, now=T0)
    assert sb.allow("map__control__4cf644d7", path=store, now=T0)[0] is True


def test_a_screen_with_no_identity_is_not_refused(tmp_path):
    """An id-less caller gives no evidence of a repeat; refusing it would block every anonymous
    question, which is the "cannot read the budget" failure direction."""
    store = _store(tmp_path)
    for _ in range(4):
        sb.record(SCREEN, path=store, now=T0)
    assert sb.allow("", path=store, now=T0)[0] is True
    assert sb.record("", path=store, now=T0) == sb.load(store)


@pytest.mark.parametrize("broken", ["{not json", "[]", "null"])
def test_an_unreadable_store_does_not_refuse_everything(tmp_path, broken):
    """A corrupted byte must not stop the learning path.

    The opposite failure direction would be worse here than the loop: a loop wastes calls, a
    blanket refusal makes the system unable to learn at all.
    """
    store = _store(tmp_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(broken, encoding="utf-8")
    assert sb.allow(SCREEN, path=store, now=T0)[0] is True


def test_a_failed_call_still_spends_the_budget(tmp_path):
    """Failures count.  A screen whose attempts were mostly call failures must still cool down."""
    store = _store(tmp_path)
    for _ in range(sb.BUDGET_PER_SCREEN):
        sb.record(SCREEN, path=store, now=T0)         # imagine each ended in VENUS_CALL_FAILED
    assert sb.allow(SCREEN, path=store, now=T0)[0] is False


def test_the_store_holds_exactly_the_screens_still_cooling(tmp_path):
    """The real bound is time, not a size.

    My first two attempts at this test were both wrong in instructive ways.  The first asserted the
    trim target (256) and failed because the code trims *to* 256 when it exceeds 512.  The second
    kept the trim but asserted "<= 512 whatever the history", and then the fix that made trimming
    safe -- only forget an entry once it has stopped suppressing -- failed it at 2000, correctly:
    with a one-hour cooldown, a burst of 2000 distinct screens inside 33 minutes is 2000 screens
    that all still refuse something.

    So the invariant is stated as what it is: the table holds the screens attempted within the
    cooldown, and it shrinks once they expire.  In production that set is tiny -- the ledger that
    motivated this held 13 ``request_id``s -- and correctness beats size here, because evicting a
    cooling entry silently reopens the loop.
    """
    store = _store(tmp_path)
    for index in range(600):
        sb.record(f"page__control__{index:08x}", path=store,
                  now=T0 + timedelta(seconds=index))
    assert len(sb.load(store)) == 600, "all still cooling: none may be dropped"

    # An hour later they have all stopped suppressing anything, and the table empties itself.
    later = T0 + timedelta(seconds=sb.COOLDOWN_SECONDS + 700)
    sb.record(SCREEN, path=store, now=later)
    assert set(sb.load(store)) == {SCREEN}


def test_pruning_never_drops_a_screen_inside_its_cooldown(tmp_path):
    """The reason the previous trim was wrong: the oldest attempts are the ones still cooling.

    A trim that evicted them would silently release the loop this module exists to close -- which is
    what this test caught, in a version that evicted by age alone.
    """
    store = _store(tmp_path)
    for _ in range(sb.BUDGET_PER_SCREEN):
        sb.record(SCREEN, path=store, now=T0)          # the screen we care about
    for index in range(700):                            # a lot of younger churn
        sb.record(f"page__control__{index:08x}", path=store,
                  now=T0 + timedelta(seconds=index))
    assert sb.allow(SCREEN, path=store, now=T0 + timedelta(seconds=1))[0] is False
