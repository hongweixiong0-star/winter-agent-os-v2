"""Which beast the route may spend stamina on -- one table, not four literals.

Measured 2026-09-17 (CAP-Z01).  The dispatchable target was encoded as the
literal pair ``("MUSK_OX", 9)`` in four places that must agree:

    brain.py      the route that decides to spend the stamina
    verifier.py   verify_beast_target_selected / _march_open / _dispatch

and the route's own scanning templates in ``vision.py`` were cropped from one
level-9 musk ox.  The client, meanwhile, prints a whole table of world beasts --
``knowledge/game/beasts.json`` already carries 麝牛/9, 北极狼/6 and 雪豹/29 with
the assessment string each one prints and, for the level-29 leopard, the measured
``action_result: BLOCKED_BEFORE_DISPATCH``.  None of that could reach the route:
the current role's map holds a level-24/25 moose and the route cannot say
"spend on this" or "refuse that" about it at all, because the answer was a code
literal rather than a lookup.

So the *decision* moves here: a row is dispatchable only when its own data says
so, and today exactly one row says so -- which is why this change cannot regress
the live-verified musk ox route.  Recognition (which templates exist for which
species) stays in ``vision.py`` and is deliberately not faked here: a species
with no template has no ``visible_target`` and therefore never reaches this
module.  Adding a target is then a data row plus its templates, not a code edit
in four files.

Every field read here is copied from the client, never invented.  ``victory_assessment``
is the string the BEAST dialog actually printed on a run whose dispatch verified
live ("本次出征胜券在握" green, "本次出征胜算较低" red); the red row is kept in
the table *with* its refusal so a future reader can see why it is refused.

REVISED 2026-09-20 -- the gate is the client's verdict, not a per-species pre-approval.
==============================================================================
Measured on a live MAP frame (dataset/raw/live_runtime/stamina_verify2/
stamina_verify2_step_001_before_20260919T144336706139.png), through the production chain:

    named_beast_label   -> 霜鳞避役            (the client prints the name beside the animal)
    level_beside_label  -> 20
    lookup_by_name      -> FROST_SCALED_RUNNER_20   (the row is registered)
    is_dispatchable     -> False   <- the row says ``dispatchable: false``, so the route
                                      recorded nothing and fell back to panning the map

Recognition was never the problem; one hand-written per-species flag was.  Its own note said
the flag existed because "recommended power and the stamina cost decide whether a march is
dispatched, and neither has been observed, so neither is guessed" -- and the answer to that
objection is already in this module: the dialog's own words.

So the table now answers two different questions instead of one:

    may_evaluate()     may the route TAP this beast to open its card?   identity is enough
    is_dispatchable()  may the route SPEND stamina on it?               the client's green
                                                                        verdict is required
                                                                        unless the row is
                                                                        already pre-cleared

A row's ``dispatchable: true`` keeps its old standing (the LIVE_VERIFIED musk ox and the
mammoth are unaffected -- the map fragment carries no verdict, so their rows still decide).
A row that was *measured refused* -- the level-29 leopard with its printed
"本次出征胜算较低" and ``BLOCKED_BEFORE_DISPATCH`` -- is refused harder than before: it is not
even tapped, whereas under the old inference a frame without a verdict could have admitted it.
Everything else (registered but unmeasured, like 霜鳞避役, or verified without a recorded
verdict, like 大角鹿) becomes *evaluable*: tapping opens the card, that costs no stamina, and
what happens next is decided by the client's own words on the card.

This is the generalisation the operator asked for -- "as long as we can beat it, we may hit
it" -- expressed in the client's own terms rather than in ours: one rule per species is
replaced by one rule per frame, and a species nobody has measured yet needs no prior work to
be *considered*, only the client's green light to be *attacked*.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
BEASTS_PATH = ROOT / "knowledge/game/beasts.json"

# The one assessment string a live dispatch has been verified against.  A target
# whose dialog prints anything else is refused, which is what the operator asked
# for after the level-29 leopard was rejected on its red assessment.
GREEN_ASSESSMENT = "本次出征胜券在握"


@dataclass(frozen=True)
class BeastTarget:
    """One row of the client's beast table, as far as the route may use it."""

    species: str
    name: str
    level: int
    dispatchable: bool
    victory_assessment: str | None
    status: str
    source_id: str
    # Why this row may be dispatched, in the row's own words.  Carried through rather than
    # left in the JSON because it is the *evidence* for a CANDIDATE being dispatchable at
    # all: a row with no green assessment is allowed only when it says which verifier still
    # gates each spend, and that claim should be checkable without opening the file.
    notes: str = ""
    #: The client has already been seen refusing this target: it printed an assessment
    #: that is not the green one, or the dispatch was recorded as blocked before it
    #: happened.  This is *evidence*, not an unmeasured default -- which is exactly why
    #: it is the one thing that survives the revision above and keeps refusing without
    #: consulting a frame.  ``victory_assessment: 本次出征胜算较低`` on the level-29
    #: leopard is the case it exists for.
    refused: bool = False

    @property
    def route(self) -> str:
        """``("MUSK_OX", 9)`` as the name the route speaks: ``MUSK_OX_9``."""
        return f"{self.species}_{self.level}"

    def describe(self) -> str:
        return f"{self.name} Lv{self.level} ({self.species})"


def _species_of(source_id: str) -> str | None:
    """``MUSK_OX_9_LIVE`` -> ``MUSK_OX``; a row with no level has no species."""
    text = re.sub(r"_LIVE$", "", str(source_id or "").strip())
    match = re.fullmatch(r"(.+?)_(\d+)", text)
    return match.group(1) if match else None


def _level_of(record: Mapping[str, Any], source_id: str) -> int | None:
    level = record.get("level")
    if isinstance(level, int):
        return level
    match = re.search(r"_(\d+)(?:_LIVE)?$", str(source_id or ""))
    return int(match.group(1)) if match else None


def _species_from_record(record: Mapping[str, Any], source_id: str) -> str | None:
    """An explicit ``species`` field wins; otherwise it comes from the id."""
    explicit = str(record.get("species") or "").strip()
    return explicit or _species_of(source_id)


def load(path: Path | str | None = None) -> tuple[BeastTarget, ...]:
    """Every route-readable target in the client's table, in file order."""
    source = Path(path) if path is not None else BEASTS_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, list):
        return ()

    out: list[BeastTarget] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("id") or "")
        species = _species_from_record(record, source_id)
        level = _level_of(record, source_id)
        if not species or level is None:
            # BEAST_GENERIC and friends describe the class, not a target.
            continue
        assessment = record.get("victory_assessment")
        # An explicit ``dispatchable`` decides on its own -- including ``false``,
        # which is how a measured refusal (雪豹/29) is recorded.  Only a row that
        # never states it falls back to the inference, and then it must both print
        # the green assessment and be VERIFIED.
        explicit = record.get("dispatchable")
        if isinstance(explicit, bool):
            allowed = explicit
        else:
            allowed = (
                isinstance(assessment, str)
                and assessment.strip() == GREEN_ASSESSMENT
                and str(record.get("status", "")).upper() == "VERIFIED"
            )
        # Measured refusals, from the client's own words or from the recorded outcome.
        # Both are facts about an actual attempt, so unlike the old inference they may
        # refuse without a frame to re-decide on.  Kept separate from ``dispatchable``
        # because they answer different questions: this one is "has the client already
        # said no", that one is "has anyone cleared it to spend".
        refused = (
            (isinstance(assessment, str) and assessment.strip() != "" and assessment.strip() != GREEN_ASSESSMENT)
            or str(record.get("action_result") or "").upper() == "BLOCKED_BEFORE_DISPATCH"
        )
        out.append(
            BeastTarget(
                species=species,
                name=str(record.get("name") or ""),
                level=int(level),
                dispatchable=allowed,
                victory_assessment=str(assessment) if isinstance(assessment, str) else None,
                status=str(record.get("status") or ""),
                source_id=source_id,
                notes=str(record.get("notes") or ""),
                refused=refused,
            )
        )
    return tuple(out)


def lookup(
    species: object,
    level: object,
    targets: Sequence[BeastTarget] | None = None,
) -> BeastTarget | None:
    """The row for one (species, level), or ``None`` when the table has no row."""
    if not isinstance(species, str) or not isinstance(level, int):
        return None
    wanted = species.strip().upper()
    for target in targets if targets is not None else load():
        if target.species.upper() == wanted and target.level == level:
            return target
    return None


def refused_by_evidence(
    beast: Mapping[str, Any] | None,
    targets: Sequence[BeastTarget] | None = None,
) -> bool:
    """Has the client already been seen refusing this exact target?

    True only for a *measured* refusal (see :attr:`BeastTarget.refused`).  An
    unregistered species or an unmeasured one answers False -- "nobody has said no"
    is not the same as "someone said no", and conflating them is what made the route
    unable to consider any beast the table did not already bless.
    """
    if not isinstance(beast, Mapping):
        return False
    target = lookup(beast.get("visible_target"), beast.get("level"), targets)
    return bool(target is not None and target.refused)


def may_evaluate(
    beast: Mapping[str, Any] | None,
    targets: Sequence[BeastTarget] | None = None,
) -> bool:
    """May the route TAP this beast, to open its card and read the client's verdict?

    Identity is the whole requirement: the beast map fragment must name a target the
    table knows, because the tap coordinate comes from that identity being read off
    the frame in the first place.  No spend is authorised here and none happens --
    opening a card costs nothing -- which is why an *unmeasured* species passes and
    why this is deliberately weaker than :func:`is_dispatchable`.

    The one thing that still refuses is a target the client has already been seen
    turning down, so the level-29 leopard is not re-tapped on every pass.
    """
    if not isinstance(beast, Mapping):
        return False
    if lookup(beast.get("visible_target"), beast.get("level"), targets) is None:
        return False
    return not refused_by_evidence(beast, targets)


def is_dispatchable(
    beast: Mapping[str, Any] | None,
    targets: Sequence[BeastTarget] | None = None,
) -> bool:
    """May the route spend stamina on what the frame is currently showing?

    Three cases, in the order they are decided:

    * the target was **measured refused** -> no, whatever else the frame says;
    * the frame carries the dialog's own assessment -> that string decides, which is
      the rule this module has always stated: "the dialog's own words decide when they
      are on the frame";
    * no verdict on this frame -> only a row already cleared to spend may spend.

    So a row with ``dispatchable: true`` reads exactly as it did before (the
    LIVE_VERIFIED musk ox, the mammoth), an unmeasured species is refused *here* but
    still reachable through :func:`may_evaluate`, and the verdict collected on the
    card is what promotes it.  Nothing in this function guesses: every True it returns
    traces to either a row someone measured or a string the client printed.
    """
    if not isinstance(beast, Mapping):
        return False
    target = lookup(beast.get("visible_target"), beast.get("level"), targets)
    if target is None or target.refused:
        return False
    printed = beast.get("victory_assessment")
    if isinstance(printed, str) and printed.strip():
        # The dialog's own words decide when they are on the frame.  Compared against
        # the one string a verified dispatch actually printed, not against the row's:
        # a row whose assessment was never read has no string to compare with, and
        # requiring one would put the per-species bar back through the side door.
        return printed.strip() == GREEN_ASSESSMENT
    return target.dispatchable


def dispatchable(targets: Iterable[BeastTarget] | None = None) -> tuple[BeastTarget, ...]:
    """The rows the route is currently allowed to spend on."""
    return tuple(t for t in (targets if targets is not None else load()) if t.dispatchable)


def display_name(species: object, level: object, targets: Sequence[BeastTarget] | None = None) -> str | None:
    """The name the client prints for a target ("麝牛"), from the table only."""
    target = lookup(species, level, targets)
    return target.name or None if target is not None else None


def lookup_by_name(
    name: object,
    level: object = None,
    targets: Sequence[BeastTarget] | None = None,
) -> BeastTarget | None:
    """The row a printed name belongs to -- the dialog side of the same table.

    The map side knows the species (from the recognition template) and the dialog
    side prints the name, so the identity has to travel between them somewhere.
    It travels here rather than through a literal in each verifier.

    ``level`` is optional because the client does not print it on every page: the
    BEAST card prints ``等级9 麝牛``, while the MARCH page prints only
    ``目标：<name>``.  Callers that can see a level pass it and get the stricter
    match; callers that cannot still resolve the row by name.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    wanted = name.strip()
    level_wanted = level if isinstance(level, int) else None
    for target in targets if targets is not None else load():
        if target.name == wanted and (level_wanted is None or target.level == level_wanted):
            return target
    return None
