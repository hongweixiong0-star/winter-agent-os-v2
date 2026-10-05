"""The species-specific beast target: where the frame printed the name, or not at all.

Measured 2026-10-05 on ``SELECT_BEAST_TARGET_MAMMOTH``: 35 rows, 0 successes, and every one of
them with an *empty* ``after_screenshot`` -- no tap was ever sent, in 0.062-0.11 s.  The skill
declares ``TARGET_BEAST_MAMMOTH_5``, a sprite template, and over those same 35 recorded frames
the sprite matched **none**; the resolver then fell through to the navigation advisor, which
refuses anything whose skill id does not start with ``OPEN_`` and recorded
``UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION``.

The frame was carrying the answer: ``state_before.beast`` read
``{"visible_target": "MAMMOTH", "source": "BEAST_LABEL", "label_text": "猛犸象",
"label_confidence": 0.9868, "tap_norm": [0.516, 0.586]}`` -- the client printed the animal's own
name, and the sibling ``SELECT_BEAST_TARGET_LABELLED`` taps exactly that through ``BEAST_ON_MAP``.

These tests pin the branch that closes the gap, and in particular that it is **not** pre-empting:
``visible_target`` is set from the sprite template as well as from the label, so a frame the
sprite does match must still reach the template fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import BEAST_LABEL_TARGET_SPECIES, LiveRuntime  # noqa: E402

MAMMOTH = "TARGET_BEAST_MAMMOTH_5"
MUSK_OX = "TARGET_BEAST_MUSK_OX_9"
FRAME = Path("frame-that-only-the-fake-reads.png")


class _Match:
    def __init__(self, point):
        self.center_norm = point


class _Resolvers:
    """A stand-in for the three collaborators the resolver reaches on these paths.

    ``template`` is what the sprite search answers; it is a parameter because the whole point of
    one of the tests below is that the sprite still gets its turn.
    """

    def __init__(self, template=None):
        self.template = template
        self.template_asked = 0
        self._semantic = self
        self.brain = None

    def find(self, image_path, semantic):
        self.template_asked += 1
        return _Match(self.template) if self.template is not None else None

    def _client_printed_control(self, semantic, frame, frame_path):
        return None, None

    def _dictionary_hint(self, semantic, frame, frame_path, *, frame_derived_only=False):
        return None

    def resolve(self, semantic, frame):
        return LiveRuntime._resolve_semantic_target(self, semantic, frame, frame_path=FRAME)


def labelled(target="MAMMOTH", point=(0.516, 0.586), source="BEAST_LABEL"):
    return WorldState(page=Page.MAP, beast={
        "visible_target": target, "source": source, "label_text": "猛犸象",
        "label_confidence": 0.9868, "tap_norm": list(point),
    })


def test_the_frame_s_own_label_answers_the_species_target():
    resolvers = _Resolvers()
    assert resolvers.resolve(MAMMOTH, labelled()) == (0.516, 0.586)
    # The label answered, so the sprite was not needed -- but it is the *point* that matters.
    assert resolvers.template_asked == 0


def test_a_label_naming_another_animal_does_not_answer_the_mammoth_target():
    # The brain picks a species-specific skill from the observation it read; the resolver is
    # handed the dispatch-time frame, and a label naming a different animal must not be tapped
    # by the skill that names this one.
    resolvers = _Resolvers()
    assert resolvers.resolve(MAMMOTH, labelled(target="MUSK_OX", point=(0.08, 0.40))) is None
    assert resolvers.template_asked == 1, "the sprite must still get its turn"


def test_the_label_answers_for_the_species_it_names_and_not_the_other():
    resolvers = _Resolvers()
    assert resolvers.resolve(MUSK_OX, labelled(target="MUSK_OX", point=(0.08, 0.40))) == (0.08, 0.40)


def test_the_branch_is_not_reached_from_another_page():
    resolvers = _Resolvers()
    frame = WorldState(page=Page.HOME, beast=dict(labelled().beast))
    assert resolvers.resolve(MAMMOTH, frame) is None
    assert resolvers.template_asked == 1


def test_a_template_reading_is_left_to_the_template():
    # ``vision`` fills ``visible_target`` from the sprite as well as from the label, so a frame
    # whose reading came from the sprite must not be diverted here.
    resolvers = _Resolvers(template=(0.42, 0.31))
    frame = labelled(source="MAMMOTH_SPRITE")
    assert resolvers.resolve(MAMMOTH, frame) == (0.42, 0.31)


def test_a_sprite_the_label_also_agrees_with_still_reaches_the_template():
    # Belt and braces: if the label answers we use the label, but a frame the sprite matched and
    # the label did not must still be answered by the sprite.
    resolvers = _Resolvers(template=(0.42, 0.31))
    frame = labelled(source="TEMPLATE", target="MAMMOTH")
    assert resolvers.resolve(MAMMOTH, frame) == (0.42, 0.31)


def test_a_malformed_label_point_falls_through_instead_of_raising():
    resolvers = _Resolvers()
    frame = labelled(point=("x", "y"))
    assert resolvers.resolve(MAMMOTH, frame) is None
    assert resolvers.template_asked == 1


def test_a_label_point_outside_the_frame_is_refused():
    resolvers = _Resolvers()
    assert resolvers.resolve(MAMMOTH, labelled(point=(1.4, 0.586))) is None


def test_the_table_names_the_two_registered_species_templates():
    # Both species templates the vision layer knows about, so the resolver cannot be asked for a
    # species target it will silently ignore.
    assert BEAST_LABEL_TARGET_SPECIES == {MAMMOTH: "MAMMOTH", MUSK_OX: "MUSK_OX"}
