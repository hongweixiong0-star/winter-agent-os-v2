"""A month-old refusal about one animal must not veto every animal of that name.

Measured 2026-10-03 on the production ledger.  ``BEAST_DISPATCH_NOT_PROVEN`` appeared 3 times
under ``a1c091ed`` and 9 times in the whole corpus, and **none of the 9 is caught by a later
success of the same skill with the same input** -- so by the project's own pairing rule this is
a real defect, not a designed recovery.  All three new ones carry identical evidence:

    before.page=MARCH   before.beast={"victory_assured": true, "name": "雪豹",
                                      "target_kind": "WILDERNESS"}
    after.page=MAP      after.marches=[MARCHING]      after.march_used=1

The dispatch **succeeded**: the client printed its own green verdict, a march went out, and the
queue counter moved.  The verifier said no because of this:

    winter_agent_v2/verifier.py:1207
        and not target.refused

and ``target`` comes from ``lookup_by_name(before.beast.get("name"))`` -- **called without a
level**.  The table has one 雪豹 row, recorded on 2026-09-06 at level 29 with
``victory_assessment: "本次出征胜算较低"`` and ``action_result: BLOCKED_BEFORE_DISPATCH``
(``knowledge/game/beasts.json``, ``SNOW_LEOPARD_29_LIVE``).  So today's snow leopard is refused
by a fact about a different animal a month ago.

The module already knows better, and says so
--------------------------------------------
``beast_targets.py`` was generalised from "one rule per species" to "one rule per frame" -- its
own module docstring says so, and ``refused_by_evidence`` implements it: it looks up the exact
``(species, level)`` pair **first** and only then falls back to the species.  ``verify_beast_dispatch``
does not use that function and does not pass the level, so it gets the species-only answer.

That makes this the project's recurring shape rather than a new one: **the same decision written
twice in two places, and the looser copy is the one on the production path.**  The fix follows
the rule that already exists here -- read the sibling, copy the stricter form -- rather than
inventing a third one.

What this file does **not** claim
---------------------------------
It does not claim the refusal was wrong.  A 29-level leopard that printed
``本次出征胜算较低`` really was refused, and refusing it again on a frame that prints the same
red string is correct.  The defect is narrower: **a frame that prints the green string is
refused by a record that is not about that frame.**  So the fix is to let the frame's own words
decide when they are on the frame -- which is what ``is_dispatchable``'s own docstring already
declares as the rule ("the dialog's own words decide when they are on the frame") -- and to
leave the record in force on frames where the frame says nothing.
"""

import json

import pytest

from winter_agent_v2.beast_targets import (
    BeastTarget,
    lookup_by_name,
    refused_by_evidence,
)
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.verifier import verify_beast_dispatch


def _table():
    """The two rows that matter, as ``load()`` builds them.

    ``refused`` is **derived** by ``load()`` from the record -- a non-green assessment or a
    ``BLOCKED_BEFORE_DISPATCH`` outcome -- so it is passed here rather than computed.  An
    earlier version of this file passed it as a constructor argument, silently produced
    ``refused=False``, and every assertion about the record passed for the wrong reason.
    That is worth stating here so the next reader does not make the same shape error.
    """
    return (
        BeastTarget(
            species="SNOW_LEOPARD", name="雪豹", level=29, dispatchable=False,
            victory_assessment="本次出征胜算较低", status="BLOCKED_BEFORE_DISPATCH",
            source_id="SNOW_LEOPARD_29_LIVE", refused=True,
        ),
        BeastTarget(
            species="BEAST_GENERIC", name="野兽", level=1, dispatchable=True,
            victory_assessment=None, status="LIVE_VERIFIED", source_id="BEAST_GENERIC",
            refused=False,
        ),
    )


GREEN = "本次出征胜券在握"


def _before(assessment=GREEN, name="雪豹", level=None):
    beast = {"victory_assured": assessment == GREEN, "name": name, "target_kind": "WILDERNESS"}
    if level is not None:
        beast["level"] = level
    return WorldState(page=Page.MARCH, beast=beast)


def _after():
    return WorldState(
        page=Page.MAP, marches=["MARCHING"], march_used=1, march_max=6, confidence=0.99,
    )


def test_a_green_verdict_on_the_frame_is_not_vetoed_by_an_unrelated_record():
    """The defect, asserted as what the verifier should answer.

    Everything real is green -- the client printed 本次出征胜券在握, a march went out, the
    queue counter moved -- and the only thing standing in the way is a record about a
    different animal from a month ago.  The frame's own words decide when they are on the
    frame; that is this module's stated rule and this verifier is the one place not applying it.
    """
    result = verify_beast_dispatch(_before(), _after(), targets=_table())
    assert result.ok is True, (
        "the frame carries the client's own green verdict and the march landed; a record about "
        "a level-29 leopard on 2026-09-06 must not veto it"
    )
    # ``victory_assured`` is ``before_ok``, so it is True now; the extra keys are what
    # makes the reason legible in the ledger instead of having to be re-derived from the code.
    assert result.evidence == {
        "victory_assured": True, "active_march": True, "march_used": 1,
        "refused_here": False, "frame_verdict": True, "named": True,
    }


def test_a_frame_that_names_nothing_still_refuses():
    """The guard the first version of this fix dropped, and an existing test caught it.

    ``tests/test_beast_formation_identity.py`` pins three refusals -- no readable name, no
    verdict, a measured refusal -- and the nameless one went red on the first run here.  It is
    right: the victory strip answers "can we beat it", never "is this the animal we aimed at".
    A frame with no name has identified nothing, so it is not a dispatch no matter what its
    strip says.

    Kept as its own test rather than folded into the green one, because the failure mode it
    guards is a loosening, and a loosening's guard is the thing that must not be lost.
    """
    nameless = WorldState(page=Page.MARCH, beast={"victory_assured": True})
    result = verify_beast_dispatch(nameless, _after(), targets=_table())
    assert result.ok is False, "a frame with no name has identified no target"
    assert result.evidence["named"] is False

    # And with no name the record cannot veto anything either -- there is nothing to match.
    assert result.evidence["refused_here"] is False


def test_the_green_verdict_on_the_frame_is_what_failed():
    """Names the cause without naming a line of the verifier.

    Every lookup of that name finds the refused row -- with a level, without one, by species --
    so the record itself is never in question.  What separates a legitimate refusal from this
    false negative is entirely whether the frame carries the client's own words, which is why
    the fix keys on that and not on the lookup.
    """
    before = _before()
    assert before.beast.get("victory_assured") is True
    assert before.beast.get("name") == "雪豹"
    assert lookup_by_name("雪豹", 29, targets=_table()).refused is True
    assert lookup_by_name("雪豹", targets=_table()).refused is True


def test_the_frame_with_the_red_string_is_still_refused():
    """The control that stops this from becoming "always allow the leopard".

    A frame that prints the client's own red verdict must still be refused, and must be refused
    for the same reason as before -- the record plus the frame agreeing.
    """
    before = _before(assessment="本次出征胜算较低")
    result = verify_beast_dispatch(before, _after(), targets=_table())
    assert result.ok is False


def test_the_sibling_that_got_it_right_never_consults_the_table():
    """Where the fix comes from -- and it is **not** the function I first assumed.

    ``refused_by_evidence`` looks like it has the stricter form: it resolves the exact
    ``(species, level)`` pair first.  But its docstring is explicit that the species fallback is
    deliberate ("the leopard's refusal is a fact about the animal, so it survives that animal
    turning up at another level"), and running it confirms the fallback fires either way:

        refused_by_evidence({"visible_target": "SNOW_LEOPARD", "level": 29}) -> True
        refused_by_evidence({"visible_target": "SNOW_LEOPARD"})              -> True
        refused_by_evidence({})                                              -> False

    So passing the level to a lookup does **not** fix this, and that is worth pinning: it is the
    obvious first attempt and it is a dead end.  The sibling that already had it right is
    ``verify_intel_beast_dispatch``, which reads only the frame's own verdict.
    """
    from winter_agent_v2.verifier import verify_intel_beast_dispatch

    exact = {"visible_target": "SNOW_LEOPARD", "level": 29}
    species_only = {"visible_target": "SNOW_LEOPARD"}
    assert refused_by_evidence(exact, targets=_table()) is True
    assert refused_by_evidence(species_only, targets=_table()) is True, (
        "the species fallback is intentional, so the level is not the remedy"
    )
    assert refused_by_evidence({}, targets=_table()) is False

    # The sibling: no table argument at all, because it never asks the table.
    import inspect

    assert "targets" not in inspect.signature(verify_intel_beast_dispatch).parameters
    green = verify_intel_beast_dispatch(_before(), _after())
    assert green.ok is True


def test_the_record_in_the_table_is_what_a_month_of_evidence_would_rewrite():
    """Why the data cannot simply be deleted, and what would justify changing it.

    The row is a real measurement with ``confidence 0.99`` and ``statusREVIEWED``; deleting it
    to stop the false negative would throw away the only reason the route does not spend
    stamina on a target the client turns down.  What would justify a change is another
    measurement: a frame that prints 胜券在握and lands a march.
    """
    record = next(
        row for row in json.loads(
            (__import__("pathlib").Path(__file__).resolve().parents[1]
             / "knowledge" / "game" / "beasts.json").read_text(encoding="utf-8")
        )["records"]
        if row["id"] == "SNOW_LEOPARD_29_LIVE"
    )
    assert record["action_result"] == "BLOCKED_BEFORE_DISPATCH"
    assert record["victory_assessment"] == "本次出征胜算较低"
    assert record["last_verified"] == "2026-09-06", (
        "the record is a month old; if it is ever re-verified this test's premise changes and "
        "the refusal should be re-measured rather than reasoned about"
    )