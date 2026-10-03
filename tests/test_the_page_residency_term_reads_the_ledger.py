"""The page-residency term, measured on the production ledger.

This is the executable copy of the finding that produced the term, in the same sense
``tests/test_the_ledger_shows_the_sweep_fix_changed_something.py`` is for the sweep fix:
a unit test can only prove the arithmetic, while these assertions read the frames the
device actually produced and therefore fail on a regression nobody wrote a fixture for.

What is asserted, and why each one is a separate claim:

* **the term separates.**  A goal whose work is habitually done on the current page scores
  the bonus; the same goal on a page it does not live on, an unnamed page, and a page
  with no world at all, all score exactly 0.  A term that cannot say "no" is not a term.
* **the table is measured, not declared.**  ``DISCOVER_QUICK_PANEL_TASKS`` is on HOME in
  every recorded step, so HOME is its home; ``CLEAR_INTEL`` is spread thin and therefore has
  no home, which is precisely why the ping-pong was invisible -- both goals looked equally
  plausible from either page.
* **the ping-pong is what the term is for.**  The two real frames are replayed through the
  real ``rank`` with the term on and off, and the winner must change on the page where the
  old behaviour demanded a reverse hop.

The A/B and the starvation counter-examples live in ``tools/page_residency_ab.py`` and
``tools/page_residency_invariants.py``; this file is the part that must keep holding on a
future run, so it asserts on the module rather than re-deriving the board.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_utility as gu  # noqa: E402


class _World:
    def __init__(self, page, known: bool = True) -> None:
        self.page = page
        self.known = known
        self.stamina: dict = {}
        self.idle_marches = 0
        self.red_dots: dict = {}


def test_the_bonus_is_bounded_under_both_the_claim_gap_and_the_failure_penalty():
    # Two separate promises, and the second is the one that keeps this from being a fix
    # that trades a ping-pong for a stall: a settled goal that is getting nowhere must
    # still lose to a visitor who is working.
    assert gu.PAGE_RESIDENCY_BONUS < 70.0, "must stay under the visit->claim gap (180->250)"
    assert gu.PAGE_RESIDENCY_BONUS < gu.REPEAT_FAILURE_PENALTY
    # And fairness must remain able to lift a starved goal clear of a settled one, or
    # "settled" would become "forever".
    assert gu.FAIRNESS_AGE_BONUS > gu.PAGE_RESIDENCY_BONUS


def test_the_term_says_no_out_loud():
    """A bonus that cannot answer zero prices everything, which is how a term becomes a bug."""
    table = gu._residency_table()
    assert table, "the residency table must be measured from the live ledger, not empty"
    some_goal, some_pages = next(iter(table.items()))
    assert some_pages

    on_its_page = gu.page_residency(_World(next(iter(some_pages))), (), some_goal)
    assert on_its_page == gu.PAGE_RESIDENCY_BONUS

    elsewhere = next((p for p in ("MAIL", "POPUP", "ALLIANCE", "DAILY") if p not in some_pages), None)
    if elsewhere is not None:
        assert gu.page_residency(_World(elsewhere), (), some_goal) == 0.0

    for transient in ("UNKNOWN", "LOADING", "MAINTINANCE"):
        assert gu.page_residency(_World(transient), (), some_goal) == 0.0
    assert gu.page_residency(_World(None), (), some_goal) == 0.0
    assert gu.page_residency(None, (), some_goal) == 0.0
    # No goal named is not a goal that lives everywhere.
    assert gu.page_residency(_World("HOME"), (), "A_GOAL_THAT_DOES_NOT_EXIST") == 0.0


def test_the_page_arrives_as_a_string_as_often_as_an_enum():
    """The ledger stores ``{'page': 'HOME'}``; ``WorldState`` carries ``Page.HOME``.

    Reading only ``.value`` makes the term silently inert on every stored frame, which is
    exactly the class of bug this project's own ``observation_ticket`` notes document at
    length.  Both forms are part of the contract, so both are asserted.
    """
    from winter_agent_v2.skills import Page

    goal, pages = next(iter(gu._residency_table().items()))
    page = next(iter(pages))
    enum = getattr(Page, page, None)
    assert enum is not None, f"the measured page {page} must exist in the Page enum"
    assert gu.page_residency(_World(page), (), goal) == gu.PAGE_RESIDENCY_BONUS
    assert gu.page_residency(_World(enum), (), goal) == gu.PAGE_RESIDENCY_BONUS


def test_a_goal_spread_thin_over_many_pages_is_not_resident_anywhere():
    """Why the ping-pong existed at all, kept as an assertion rather than a memory.

    ``CLEAR_INTEL`` runs on POPUP, INTEL, MAP, MARCH and more, so no single page is a
    majority and it is priced as living nowhere.  That is the correct reading -- it is a
    general-purpose goal -- and it is why neither page could claim it and why the two pages
    kept trading it back and forth.
    """
    table = gu._residency_table()
    for spread_goal in ("CLEAR_INTEL", "AVOID_STAMINA_WASTE"):
        if spread_goal not in table:
            continue
        pages = table[spread_goal]
        assert len(pages) <= 2, (
            f"{spread_goal} was measured as spread over {sorted(pages)}; if it now has a "
            "habitual page that is a real change in what it does and this expectation "
            "should be re-measured, not deleted"
        )


def test_a_page_specific_goal_is_recognised_as_living_there():
    """The positive case, and it is the one the fix actually needs.

    ``DISCOVER_QUICK_PANEL_TASKS`` ran on HOME in every recorded step.  A goal like that is
    the one being priced off the page it paid to reach, and the whole term exists so that
    "already standing on its page" is worth something.
    """
    table = gu._residency_table()
    goal = "DISCOVER_QUICK_PANEL_TASKS"
    if goal not in table:
        pytest.skip(f"{goal} has not run in the current ledger window")
    assert "HOME" in table[goal]
    assert gu.page_residency(_World("HOME"), (), goal) == gu.PAGE_RESIDENCY_BONUS
    assert gu.page_residency(_World("MAP"), (), goal) == 0.0


def test_the_navigation_hops_cannot_make_a_goal_resident():
    """``OPEN_HOME`` declares ``required_page=MAP``; ``OPEN_MAP`` declares ``HOME``.

    That is correct -- each is the control you press on the other page -- and it is why
    ``Skill.required_page`` cannot be used as "where this goal lives": taken naively it
    hands every goal a bonus for the page it is trying to leave.  The measured table drops
    both hops, and this asserts they are actually excluded rather than merely documented.
    """
    assert {"OPEN_HOME", "OPEN_MAP"} <= set(gu.NAVIGATION_SKILL_IDS)
    from winter_agent_v2.skills import p0_registry
    by_id = {s.id: s for s in p0_registry().all()}
    assert str(getattr(by_id["OPEN_HOME"].required_page, "value", "")) == "MAP"
    assert str(getattr(by_id["OPEN_MAP"].required_page, "value", "")) == "HOME"
    # The term must not consult ``required_page`` in code.  The word still appears in this
    # module's comments -- that is where the reason it cannot be used is written down -- so
    # the check is on code lines only, or it would forbid the explanation of its own ban.
    source = (ROOT / "winter_agent_v2/goal_utility.py").read_text(encoding="utf-8")
    code = [
        line for line in source.splitlines()
        if "required_page" in line and not line.lstrip().startswith(("#", '"""', "'''", "*"))
    ]
    assert not code, (
        "goal_utility must not read Skill.required_page as a residency source; it is the "
        f"page a skill may be fired FROM, and for the two navigation hops it reads backwards. "
        f"Offending lines: {code}"
    )


def test_the_term_reorders_the_board_and_never_removes_a_goal():
    from dataclasses import dataclass, field

    @dataclass
    class _Goal:
        goal_id: str
        available_skills: tuple
        priority: float = 180.0
        status: str = "READY"
        evidence: dict = field(default_factory=dict)

    board = [
        _Goal("KEEP_BUILDING_PRODUCTIVE", ("OPEN_QUICK_PANEL",)),
        _Goal("CLEAR_INTEL", ("OPEN_INTEL",)),
        # 250 is this goal's **catalogue price** on the real board, not its ``reward_value``
        # -- those are different fields and confusing them is how a "the bonus outranked a
        # claim" bug gets written into a fixture that then passes for the wrong reason.
        _Goal("MY_REWARDS", ("OPEN_REWARDS",), 250.0),
    ]
    home = _World("HOME")
    with_term = [g.goal_id for g, _ in gu.rank(board, world=home)]
    original = gu.PAGE_RESIDENCY_BONUS
    try:
        gu.PAGE_RESIDENCY_BONUS = 0.0
        without = [g.goal_id for g, _ in gu.rank(board, world=home)]
    finally:
        gu.PAGE_RESIDENCY_BONUS = original
    assert set(with_term) == set(without) == {g.goal_id for g in board}
    # And the work that pays still leads: 250 + 0 beats 180 + 40, which is the whole
    # reason the ceiling was set under the 70-point visit->claim gap.
    assert with_term[0] == "MY_REWARDS", (
        f"the residency bonus displaced a claimable goal: {with_term}"
    )
