# -*- coding: utf-8 -*-
"""The page vocabulary and the ``Page`` enum are two sources of truth.  This is the direction nobody checked.

`knowledge/ui/pages.json` declares "the pages this project knows about".  `winter_agent_v2.models.Page`
is what any reader can actually emit.  The static drift check compares *specs* against the vocabulary
(`test_declared_pages_and_elements_are_registered.py`), and the vocabulary against the enum was never
compared by anything.

Measured 2026-10-10:

    pages.json          29 names
    Page.__members__    22 members
    declared, no member 11   ARENA BEAR DANGER_TRAVEL ENDLESS_JOURNEY GIANT_BEAST PET PROFILE
                             SETTINGS SNOWFIELD_TRAVEL UNDERGROUND_EXPLORATION VIP
    member, undeclared   4   LOADING MAINTENANCE PET_TREASURE UNKNOWN

Neither side is changed here, and that is deliberate: adding `Page.ARENA` changes what the classifier
may emit, and deleting a declared name deletes knowledge.  What this file does is make the mismatch
**owned** -- an explicit list, a reason per entry, a stale-entry check, and a ceiling so the list cannot
grow one name at a time without anyone deciding to.

It also **confirms** the record `USE_FREE_ARENA_ATTEMPTS` already carries about itself:
`"missing_page_identity": "ARENA" not in Page.__members__` is true as written.
"""
from __future__ import annotations

import json
from pathlib import Path

from winter_agent_v2.models import Page

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "knowledge" / "ui" / "pages.json"

#: Declared in the vocabulary, and no ``Page`` member can ever emit them.  One shared reason, because
#: the reason really is the same for all of them: the vocabulary is a *declaration* and the enum is a
#: *capability*, and eleven declarations have no capability behind them.  Whether each declaration is
#: aspirational (a page the project intends to read, e.g. ``ARENA`` -- the goal library already
#: carries ``"ARENA" not in Page.__members__`` as its own missing-identity note) or stale, is a
#: ruling.  Nothing here decides it.
DECLARED_WITHOUT_A_MEMBER: tuple[str, ...] = (
    "ARENA", "BEAR", "DANGER_TRAVEL", "ENDLESS_JOURNEY", "GIANT_BEAST", "PET",
    "PROFILE", "SETTINGS", "SNOWFIELD_TRAVEL", "UNDERGROUND_EXPLORATION", "VIP",
)

#: ``Page`` members the vocabulary does not list.  Three of them are runtime *states* rather than
#: navigable pages -- a frame cannot be "navigated to" ``LOADING``, ``MAINTENANCE`` or ``UNKNOWN`` --
#: which is a coherent reason for a page *vocabulary* to omit them.  ``PET_TREASURE`` does not fit
#: that reading: it names a screen, so it is the one entry here that looks like an omission rather
#: than a category difference.  Recorded, not resolved.
MEMBER_WITHOUT_A_DECLARATION: tuple[str, ...] = (
    "LOADING", "MAINTENANCE", "PET_TREASURE", "UNKNOWN",
)

#: The ceiling, set to the measured count of the day it was written: 11 + 4 = 15.  A quarantine that
#: can grow without an edit is a quarantine that will, so the *next* divergence has to be an explicit
#: decision -- raise this number and say why -- rather than a silent drift.
#:
#: (Kept honest by its own test: the first draft of this constant said 12 and the test failed, which
#: is the behaviour wanted from it.)
MAX_QUARANTINE = 15


def _vocabulary() -> set[str]:
    return {str(name) for name in json.loads(PAGES.read_text(encoding="utf-8"))["pages"]}


def test_every_declared_page_is_a_member_or_is_named_here():
    unowned = sorted(_vocabulary() - {m for m in Page.__members__} - set(DECLARED_WITHOUT_A_MEMBER))
    assert unowned == [], (
        "these names are declared as pages and no Page member can emit them; either implement one or "
        f"add it to DECLARED_WITHOUT_A_MEMBER with a reason: {unowned}"
    )


def test_every_member_is_declared_or_is_named_here():
    unowned = sorted({m for m in Page.__members__} - _vocabulary() - set(MEMBER_WITHOUT_A_DECLARATION))
    assert unowned == [], (
        "these Page members are not in the vocabulary, so no consumer can see them by name; either "
        f"declare them or add them to MEMBER_WITHOUT_A_DECLARATION with a reason: {unowned}"
    )


def test_the_named_lists_have_no_stale_entries():
    """A quarantine entry that has since been fixed must be removed, or the list stops meaning anything."""
    members = {m for m in Page.__members__}
    vocabulary = _vocabulary()

    now_members = [n for n in DECLARED_WITHOUT_A_MEMBER if n in members]
    assert now_members == [], (
        f"these are Page members now, so their quarantine entries are stale: {now_members}"
    )
    now_declared = [n for n in MEMBER_WITHOUT_A_DECLARATION if n in vocabulary]
    assert now_declared == [], (
        f"these are declared in the vocabulary now, so their quarantine entries are stale: {now_declared}"
    )


def test_the_quarantine_is_not_doing_the_whole_job():
    """If most names were quarantined, the two tests above would pass while checking nothing."""
    total = len(_vocabulary()) + len({m for m in Page.__members__})
    quarantined = len(DECLARED_WITHOUT_A_MEMBER) + len(MEMBER_WITHOUT_A_DECLARATION)
    assert quarantined <= MAX_QUARANTINE, (
        f"{quarantined} names quarantined ({quarantined}/{total} of the union) -- the lists have grown "
        "past their ceiling, which means they are absorbing a drift instead of naming one"
    )
    agreeing = total - quarantined
    assert agreeing >= quarantined, (
        f"only {agreeing} names agree between the two sources and {quarantined} do not; "
        "at that point the comparison is describing the exceptions rather than the rule"
    )


def test_the_arena_note_the_goal_library_carries_is_true():
    """``USE_FREE_ARENA_ATTEMPTS`` says this about itself; pin it so the claim cannot rot."""
    assert "ARENA" not in Page.__members__
    assert "ARENA" in _vocabulary()
