"""Lock the anchor-based resource-tab classifier against live frames.

Regression history
------------------
``selected_resource`` used to probe four *hand-typed* x centres with pHash.  Two
things were wrong with that, and both were reproduced on the live client on
2026-09-14:

1. The strip scrolls, and the client re-centres the active tab, so the fixed
   centres are only valid for one scroll offset.  In the session captured here
   the offset was +400 px, which meant tapping "MEAT at 0.25" selected the
   second tab (giant beast).  Live SELECT_RESOURCE succeeded 3/44 times.
2. The classifier had no page gate: on the HOME screen — a frame with no
   resource panel open at all — it returned ``RESOURCE_COAL_SELECTED`` with 0.875
   confidence, because the corner-signal tiebreaker fired on snow.

The shipped classifier now locates the white selection bracket (a *pair* of
near-white vertical strokes 130-175 px apart), crops the anchored cell, and
identifies the resource from the cell contents, rejecting anything that is not
decisively close.  These tests pin the behaviour on the real frames.

Measured separation on these frames: the active resource scores <= 1.2 while
every non-active tab scores >= 13.0.

CORRECTION 2026-09-16.  That last pair was measured with the probe crop taken FROM
the bracket, i.e. from the selected cell itself, and it is not the population the
gate actually sees: the gate scores a PREDICTED cell, which equals the selected one
only when the anchor happens to be that tab.  Re-measured over 10 frames with
verified anchors (27 correct and 37 wrong observations):

    correct (predicted position vs its own template)   0.00 .. 6.49
    wrong   (same cell, another template)             10.65 .. 16.17
    wrong   (non-gatherable tab vs any template)      14.74 .. 25.09

so the ceiling must satisfy 6.49 < gate < 10.65 -- and it was 6.0, BELOW the largest
value its own calibration frames produce.  Those two frames (6.45 and 6.49) were
being rejected by it, which is why the gather chain stalled at SELECT_RESOURCE on
the live client.  The ceiling is now 8.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.vision import (
    SemanticWorldVision,
    _cell_signature,
    _cell_template_signature,
    _signature_distance,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

# Sentinel for "the anchored tab is one whose NAME this client does not keep
# stable, so only the geometry may be asserted".  See the 2026-09-18 note in CASES.
VOLATILE_TAB = "<volatile>"

# (label, frame, expected selected resource or None)  (**) see VOLATILE_TAB
CASES = [
    # HOME / MAP: no resource panel open at all -> must not name a resource.
    ("home", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_001_home.png", None),
    ("map", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_002_map.png", None),
    # CHANGED 2026-09-16 (resource-strip gate).  These two expected None, because
    # when the anchor search could not resolve them "refuse" was the only safe
    # contract.  The ceiling fix lets them resolve, so the expectation had to be
    # re-derived rather than assumed -- and it was, by evidence that does NOT use the
    # anchor: sliding the strip over every offset and keeping those where the
    # gatherable templates land on their own cells gives a single answer (+399),
    # under which the bracket's x inverts to tab index 0.00 on the first frame and
    # 1.00 on the second.  Index 0 is BEAST and index 1 is GIANT_BEAST, which is what
    # the classifier says.  Both are non-gatherable: the invariant that matters is
    # that a GATHERABLE identity is never invented, not that a non-gatherable tab is
    # never named.
    # CHANGED 2026-09-18 (SPEND_STAMINA_ON_BEAST escalation).  These three used to
    # assert the frozen names BEAST / GIANT_BEAST / SAWMILL, because the strip
    # order was read as a property of the game.  It is not: the first three tabs
    # DRIFT with the client's content, and the frames are their own best witness.
    # RapidOCR on each frame's own tab band reads
    #
    #   09-14 session (this frame)  : idx0 野兽  idx1 冰原巨兽  idx2 大型锯木厂  idx3 生肉
    #   09-15 + 09-18 client        : idx0 失控的雪怪  idx1 野兽  idx2 冰原巨兽  idx3 生肉
    #
    # so index 0 was 野兽 when this frame was captured and is 失控的雪怪 today.  Any
    # frozen list is therefore wrong for one of the two client states, and asserting
    # one is how the strip order came to be trusted as a fact.  What is stable --
    # on every session measured -- is the TAIL: MEAT/WOOD/COAL/IRON sit at indices
    # 3/4/5/6, which is exactly what the reviewed cell templates pin the offset to.
    # So these cases keep the part that is knowledge (the resolved offset, recorded
    # below and re-derived independently by the reviewed templates) and drop the
    # part that is not (the name of a volatile tab).  The invariant that actually
    # protects production is asserted instead in
    # ``test_a_volatile_anchor_never_invents_a_gatherable_identity``.
    # Evidence: dataset/truth_audit/beast_search_wiring_20260918/.
    ("beast", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_003_search_panel.png", VOLATILE_TAB),
    ("giant_beast", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_004_tab_tap_MEAT.png", VOLATILE_TAB),
    # CHANGED 2026-09-16 (WB-R19-SELECT-RESOURCE-ANCHOR).  This frame was refused
    # like the two above, and refusing it is what left `resource_tab_offset` at
    # None so the executor could neither tap nor scroll -- it stalled the whole
    # gather chain.  The offset is now resolved from the known strip order and
    # judged by the four reviewed templates, and on this frame exactly one
    # combination survives (support=1, margin=9.12, offset=400.0).  Its anchor is
    # again a volatile tab (see above), so the name is not asserted.
    ("sawmill", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_005_tab_tap_WOOD.png", VOLATILE_TAB),
    # MEAT selected, and the strip sits 400 px right of the nominal offset.
    ("meat", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_006_tab_tap_COAL.png", "MEAT"),
    # WOOD selected but the cell is clipped by the right edge: refuse rather than guess.
    ("wood_clipped", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_007_tab_tap_IRON.png", None),
    # Explicit select-each capture, all four resources, all fully visible.
    ("select_meat", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png", "MEAT"),
    ("select_wood", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png", "WOOD"),
    ("select_coal", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png", "COAL"),
    ("select_iron", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png", "IRON"),
    # The production failures this gate change exists for.  The chain reached
    # SELECT_RESOURCE on each of these and stopped, because the geometry was right
    # and the crop scored 6.49 against a 6.0 ceiling.  The bracket is on tab index 1
    # at x=172, which predicts 生肉 at x=486, and 生肉 is visibly there.  Both
    # anchors are in the volatile front (see above), so only the geometry [offset]
    # is asserted; these frames' own printed labels are 野兽 / 冰原巨兽 at idx1 / idx2.
    ("live_fail_233727", "dataset/truth_audit/resource_strip_20260916/live_fail_233727__live_runtime_step_003_before_20260915T233727132656.png", VOLATILE_TAB),
    ("live_fail_233739", "dataset/truth_audit/resource_strip_20260916/live_fail_233739__live_runtime_step_001_before_20260915T233739598714.png", VOLATILE_TAB),
    ("live_fail_160609", "dataset/truth_audit/resource_strip_20260916/live_fail_160609__live_runtime_step_003_before_20260915T160609443785.png", VOLATILE_TAB),
]


# ``selected_resource`` returns None for these four exactly when the anchored cell
# is not one of them; naming a volatile tab is not knowledge.
GATHERABLE = ("MEAT", "WOOD", "COAL", "IRON")


@pytest.fixture(scope="module")
def vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


@pytest.mark.parametrize("label,relative,expected", CASES, ids=[case[0] for case in CASES])
def test_selected_resource_on_live_frames(vision: SemanticWorldVision, label: str, relative: str, expected: str | None) -> None:
    path = ROOT / relative
    if not path.is_file():
        pytest.skip(f"live evidence missing: {relative}")
    match = vision.semantic.selected_resource(path)
    if expected is VOLATILE_TAB:
        # Geometry is knowledge; the name of a drifting tab is not.  What must
        # hold is that the strip was located (so the executor can tap or scroll)
        # and that a volatile anchor was never reported as one of the four
        # gatherable resources -- inventing one would send a gathering march at
        # the wrong node.
        assert vision.semantic.resource_tab_offset is not None, (
            f"{label}: the strip must still be located on a volatile-anchor frame"
        )
        got = match.semantic[len("RESOURCE_"):-len("_SELECTED")] if match else None
        assert got not in GATHERABLE, f"{label}: volatile anchor reported as {got}"
        return
    got = match.semantic[len("RESOURCE_"):-len("_SELECTED")] if match else None
    assert got == expected, f"{label}: expected {expected}, classifier said {got}"


def test_a_volatile_anchor_never_invents_a_gatherable_identity(vision: SemanticWorldVision) -> None:
    """The invariant the SPEND_STAMINA_ON_BEAST escalation turned on.

    ``resource_tab_order`` names the first three tabs, and those names changed
    between the 2026-09-14 and 2026-09-15 clients (measured: the frames' own OCR
    reads 野兽/冰原巨兽/大型锯木厂 there and 失控的雪怪/野兽/冰原巨兽 today).  A frozen
    list therefore cannot be trusted for the front of the strip -- and because
    ``resource_cell_center_norm`` is index-based, trusting it is what placed the
    client's own 野兽 tab one pitch off the screen so that no route could ever tap
    it.  The four GATHERABLE tabs are the stable part: their reviewed cell
    templates decide both their identity and the offset.  So on every archived
    frame that has a resource panel open, naming a gatherable resource must be
    backed by its template, never by an index.
    """
    for label, relative, expected in CASES:
        path = ROOT / relative
        if not path.is_file() or expected is None or expected is VOLATILE_TAB:
            continue
        match = vision.semantic.selected_resource(path)
        assert match is not None, f"{label}: gatherable frame must resolve"
        got = match.semantic[len("RESOURCE_"):-len("_SELECTED")]
        assert got in GATHERABLE, f"{label}: only a reviewed template may name {got}"
        assert got == expected


def test_tap_target_follows_the_observed_offset(vision: SemanticWorldVision) -> None:
    """The whole point of the anchor: a located cell determines every other cell.

    On the frame where MEAT is active the strip is 400 px right of nominal, so
    the derived MEAT tap centre must move with it — that is what stops the
    executor from tapping whichever tab happens to sit at a fixed x.
    """
    frame = ROOT / "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png"
    if not frame.is_file():
        pytest.skip("live evidence missing")
    assert vision.semantic.selected_resource(frame) is not None
    offset = vision.semantic.resource_tab_offset
    assert offset is not None
    centres = {name: vision.semantic.resource_cell_center_norm(name) for name in ("MEAT", "WOOD", "COAL", "IRON")}
    assert centres["WOOD"] is not None
    ordered = [value[0] for value in centres.values() if value is not None]
    assert ordered == sorted(ordered), "gatherable tap targets must advance left to right"
    # Shifting the offset shifts every derived target by the same amount.
    original = centres["WOOD"][0]
    vision.semantic.resource_tab_offset = offset + 72
    assert abs(vision.semantic.resource_cell_center_norm("WOOD")[0] - (original + 0.1)) < 1e-6


# ---------------------------------------------------------------------------
# The anchor must be chosen by evidence, not by stroke order.
#
# Added 2026-09-16 (WB-R19-SELECT-RESOURCE-ANCHOR).  The gather chain reached
# SELECT_RESOURCE for the first time after the march-count fix, and died there.
# The work order's hypothesis was a template-coverage gap -- and the symptom
# fits, since the manifest holds cell templates for MEAT/WOOD/COAL/IRON only.
# Measurement says otherwise:
#
#   strokes at x = 2.0, 68.5, 88.0, 156.5, 214.5, 282.5, 384.0, 394.5, 428.0
#   four stroke pairs fall in the accepted 130..175 px window
#   selected_tab_left() returned the FIRST of them: 2.0
#
# but the white bracket in that frame sits on the third visible cell, x=282.5.
# So the anchor was 280 px wrong and the template mismatch that followed
# (33.75 / 34.63 / 35.98 / 36.48 against a 6.0 gate) was a consequence: those
# crops were taken from the wrong place.  Had the mis-anchored cell matched a
# template, a wrong offset would have been accepted and the executor handed a
# wrong tap target -- the exact failure this geometry exists to prevent.
#
# The resolution crosses every accepted stroke pair with every tab identity the
# strip order allows, and keeps the unique winner.  On the failing frame exactly
# one of 28 combinations is supported, so nothing is guessed.
# ---------------------------------------------------------------------------

ANCHOR_EVIDENCE = ROOT / "dataset/truth_audit/resource_tab_anchor_20260916"
GAP_FRAME = ANCHOR_EVIDENCE / "gap_ice_beast_anchor__live_runtime_step_003_before_20260915T160609443785.png"


def test_the_bracket_is_not_simply_the_first_stroke_pair(vision: SemanticWorldVision) -> None:
    """The premise, pinned: stroke order alone picks the wrong pair here."""
    if not GAP_FRAME.is_file():
        pytest.skip("live evidence missing")
    lefts = vision.semantic.candidate_tab_lefts(GAP_FRAME)
    assert 2.0 in lefts, "the spurious pair is what stroke order picks"
    assert 282.5 in lefts, "the real bracket pair must be a candidate too"
    assert len(lefts) > 1, "ambiguity is the whole point"


def test_the_frame_that_blocked_gather_resolves_with_a_real_offset(vision: SemanticWorldVision) -> None:
    if not GAP_FRAME.is_file():
        pytest.skip("live evidence missing")
    match = vision.semantic.selected_resource(GAP_FRAME)
    assert match is not None, "the frame that stalled the gather chain must resolve"
    assert vision.semantic.resource_tab_offset == 352.5
    assert match.roi["offset_source"] == "ANCHOR_AND_IDENTITY_RESOLVED_BY_REVIEWED_TABS"
    assert match.roi["supporting_reviewed_tabs"] >= 1


def test_a_resolved_offset_makes_every_target_reachable(vision: SemanticWorldVision) -> None:
    """With the offset known the executor can act; with None it could not.

    Either the cell is already on screen (a centre) or the strip can be brought
    there (a swipe).  `resource_cell_center_norm` and `resource_tab_swipe_for`
    both return None when the offset is None, which is what stalled the chain.
    """
    if not GAP_FRAME.is_file():
        pytest.skip("live evidence missing")
    assert vision.semantic.selected_resource(GAP_FRAME) is not None
    for target in ("MEAT", "WOOD", "COAL", "IRON"):
        centre = vision.semantic.resource_cell_center_norm(target)
        swipe = vision.semantic.resource_tab_swipe_for(target)
        assert centre is not None or swipe is not None, f"{target} unreachable"


def test_the_beast_tab_is_reachable_and_the_swipe_sign_follows_the_clipped_edge(
    vision: SemanticWorldVision,
) -> None:
    """The SPEND_STAMINA_ON_BEAST escalation, pinned.

    ``AVOID_STAMINA_WASTE`` can only advance by reaching a beast, and the client's
    own way to do that is the search panel's 野兽 tab.  Two defects kept it out of
    reach, both measured live on 2026-09-18
    (dataset/truth_audit/beast_search_wiring_20260918/):

    * the tab strip's first three names had drifted, so ``BEAST`` resolved to strip
      index 0 -- one 157 px pitch left of the real 野兽 tab and off the screen;
    * the left-clip branch of ``resource_tab_swipe_for`` returned the *right*-clip
      sign, so even a correctly addressed left-clipped tab would have been scrolled
      further off the screen.  The branch had never fired in production, because
      the four gatherable tabs only ever clip on the right.

    A tab that is clipped on the left must be dragged rightward (positive delta);
    one clipped on the right must be dragged leftward (negative delta).  Either the
    cell already has a centre or it must have a swipe -- both None means the
    executor can neither tap nor scroll, which is the stall this escalation is.
    """
    frame = ROOT / "dataset/truth_audit/beast_search_wiring_20260918/key/measure_now.png"
    if not frame.is_file():
        pytest.skip(f"live evidence missing: {frame}")
    assert vision.semantic.selected_resource(frame) is not None
    for target in ("BEAST", "GIANT_BEAST", "MEAT", "WOOD", "COAL", "IRON"):
        centre = vision.semantic.resource_cell_center_norm(target)
        swipe = vision.semantic.resource_tab_swipe_for(target)
        assert centre is not None or swipe is not None, f"{target} unreachable"
        if centre is not None or swipe == 0.0:
            continue
        index = vision.semantic.resource_tab_order.index(target)
        left = (
            vision.semantic.resource_tab_first_left * 720.0
            + index * vision.semantic.resource_tab_pitch * 720.0
            + vision.semantic.resource_tab_offset
        )
        cell_px = vision.semantic.resource_tab_cell * 720.0
        if left < 4:
            assert swipe > 0, f"{target} clips on the left, so the drag must be rightward"
        elif left + cell_px > 716:
            assert swipe < 0, f"{target} clips on the right, so the drag must be leftward"


# ---------------------------------------------------------------------------
# The ceiling must sit between two measured populations, not at a remembered
# number.
#
# Added 2026-09-16 (resource-strip gate).  The configured 6.0 was below the largest
# value the calibration frames themselves produce, so it rejected correct readings;
# that, and not the strip geometry, is what stopped the gather chain.  This test
# recomputes both populations from the archived frames and fails if the ceiling
# stops separating them -- in either direction, so a later "tighten it back" or
# "loosen it to be safe" both have to bring evidence.
# ---------------------------------------------------------------------------

# (frame, offset in px, and the tab index the bracket is on)
ANCHORED_FRAMES = [
    ("dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png", 0.0, 3),
    ("dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png", 0.0, 4),
    ("dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png", 1.0, 5),
    ("dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png", 1.0, 6),
    ("dataset/truth_audit/resource_strip_20260916/live_fail_233727__live_runtime_step_003_before_20260915T233727132656.png", 399.0, 1),
    ("dataset/truth_audit/resource_strip_20260916/live_fail_233739__live_runtime_step_001_before_20260915T233739598714.png", 399.0, 1),
    ("dataset/truth_audit/resource_strip_20260916/live_fail_160609__live_runtime_step_003_before_20260915T160609443785.png", 352.5, 2),
]

GATHERABLE = ("MEAT", "WOOD", "COAL", "IRON")


def _populations(vision: SemanticWorldVision) -> tuple[list[float], list[float]]:
    from PIL import Image

    templates = {
        name: [_cell_template_signature(Path(p)) for p in paths]
        for name, paths in vision.semantic.resource_tab_cell_templates.items()
    }
    correct: list[float] = []
    wrong: list[float] = []
    for relative, offset, _anchor_index in ANCHORED_FRAMES:
        path = ROOT / relative
        if not path.is_file():
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        y0, y1 = vision.semantic._tab_band_rows(height)
        cell_px = round(vision.semantic.resource_tab_cell * width)
        for index, name in enumerate(vision.semantic.resource_tab_order):
            x0 = round((vision.semantic.resource_tab_first_left
                        + index * vision.semantic.resource_tab_pitch) * width + offset)
            if x0 < 0 or x0 + cell_px > width:
                continue
            probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
            distances = {
                other: min(_signature_distance(probe, s) for s in signatures)
                for other, signatures in templates.items()
            }
            if name in templates:
                correct.append(distances[name])
                wrong.append(min(v for k, v in distances.items() if k != name))
            else:
                # A non-gatherable slot scored against every template: the false
                # positive that a raised ceiling could start accepting.
                wrong.append(min(distances.values()))
    return correct, wrong


def test_the_ceiling_sits_between_the_two_measured_populations(vision: SemanticWorldVision) -> None:
    correct, wrong = _populations(vision)
    if len(correct) < 8 or len(wrong) < 8:
        pytest.skip("archived strip evidence missing")
    ceiling = vision.semantic.resource_tab_max_distance
    import statistics

    print("\ncorrect: n=%d min=%.2f median=%.2f max=%.2f"
          % (len(correct), min(correct), statistics.median(correct), max(correct)))
    print("wrong:   n=%d min=%.2f median=%.2f max=%.2f"
          % (len(wrong), min(wrong), statistics.median(wrong), max(wrong)))
    assert max(correct) < ceiling, (
        "the ceiling rejects a correct reading: worst correct %.2f vs ceiling %.2f"
        % (max(correct), ceiling)
    )
    assert ceiling < min(wrong), (
        "the ceiling would accept a wrong reading: ceiling %.2f vs best wrong %.2f"
        % (ceiling, min(wrong))
    )


# ---------------------------------------------------------------------------
# The offset and the identity are two independent facts.
#
# Added 2026-09-16.  The client draws NO bracket until a tab has been selected, and
# that is precisely the state of a freshly opened search panel.  Requiring a bracket
# in order to know the offset therefore meant the run could neither tap (the
# target's position was unknown) nor scroll (the scroll branch requires an offset),
# so SELECT_RESOURCE failed against a target that was already on screen -- measured
# live 2026-09-16T04:09:31, goal GATHER_RESOURCE wanting COAL, with 生肉/木材/煤矿
# all fully visible.
# ---------------------------------------------------------------------------

BRACKETLESS = (
    ROOT
    / "dataset/truth_audit/resource_strip_20260916"
    / "bracketless_panel__live_runtime_step_007_before_20260916T040931067046.png"
)
PANEL_ABSENT = (
    ROOT / "dataset/truth_audit/resource_tab_anchor_20260916/negative_home__live_page_20260915_151524.png"
)


def test_a_panel_with_no_bracket_still_yields_a_geometry(vision: SemanticWorldVision) -> None:
    if not BRACKETLESS.is_file():
        pytest.skip("live evidence missing")
    assert vision.semantic.candidate_tab_lefts(BRACKETLESS) == [], "premise: no stroke pair at all"
    match = vision.semantic.selected_resource(BRACKETLESS)
    assert match is None, "no tab is marked selected, so no identity may be claimed"
    offset = vision.semantic.resource_tab_offset
    assert offset is not None, "but the strip position must still be known"
    assert 80.0 <= offset <= 100.0, "measured +89 on this frame"
    centre = vision.semantic.resource_cell_center_norm("COAL")
    assert centre is not None, "the target the run wanted must be reachable"
    assert 0.75 <= centre[0] <= 0.81, "measured 0.7812"


def test_a_panel_absent_frame_gets_no_geometry_either(vision: SemanticWorldVision) -> None:
    """The content path's negative control: no panel, so no offset and no targets."""
    if not PANEL_ABSENT.is_file():
        pytest.skip("live evidence missing")
    assert vision.semantic.selected_resource(PANEL_ABSENT) is None
    assert vision.semantic.resource_tab_offset is None
    for target in GATHERABLE:
        assert vision.semantic.resource_cell_center_norm(target) is None
