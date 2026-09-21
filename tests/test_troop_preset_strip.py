"""The 出征 page's troop-preset strip: read it, and prove you read the right page.

Why this exists. ``CAP-G09 TROOP_SELECT`` is the dispatch page's preset row, and
the bootstrap brief for it said the recognition semantic ``TROOP_PRESET`` was
unregistered and that its fields came from a *related* skill's draft rather than
from this client.  Rather than pin eight coordinates, the row is measured and
found per frame, because how many presets exist is player-defined: this account
draws eight plus a save control, and other frames in the same corpus draw the
same eight at a different cell width, so any table of centres would be wrong on
the next role.

The measurements, all read back from the frames (2026-09-21, 720x1280 client,
``tools/probe_troop_preset_rule.py``):

    bar, page gate      y=88..96 averages (13,129,198); the lookalike
                        alliance-tech bar averages (19,141,227) and is excluded
                        by the blue test alone
    chips              the runs of non-bar columns inside y=104..144 -- found,
                        not pinned
    selected           a chip's border is gold (245,188,61) when selected and
                        light blue (87,190,255) when not; on
                        bear_preset6.png chip 5 scores gold=81 / blue=0 and the
                        other eight score gold=0
    whole corpus       454 archived frames, 26 read as the dispatch page, 0
                        false positives after the blue test was added

What is deliberately NOT claimed here: that tapping a chip moves the ring.  The
one frame carrying a gold chip is not a before/after pair of a tap (its 战力
reads 55,813,315 against 96,098,265 on the ungilded frame), so the action ->
state link is what live calibration still has to establish.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from winter_agent_v2.vision import (
    TROOP_PRESET_BAR_REF,
    TROOP_PRESET_CHIP_ROWS,
    TroopPresetStrip,
    read_troop_preset_strip,
)

ROOT = Path(__file__).resolve().parents[1]

BAR = TROOP_PRESET_BAR_REF
UNSELECTED_FILL = (4, 88, 146)
SELECTED_FILL = (202, 217, 233)
BLUE_RING = (87, 190, 255)
GOLD_RING = (245, 188, 61)
SAVE_FILL = (4, 115, 232)

CHIP_CENTRES = (62, 139, 211, 283, 359, 434, 508, 576)
HALF_W = 29
BORDER = 8


def _draw_strip(selected: int | None, *, chips=8, with_save=True) -> Image.Image:
    """A synthetic 出征 page carrying exactly what the reader looks for."""
    image = Image.new("RGB", (720, 1280), (13, 50, 95))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 88, 719, 162), fill=BAR)
    ring = GOLD_RING if selected is not None else BLUE_RING
    for index in range(chips):
        cx = CHIP_CENTRES[index] if index < len(CHIP_CENTRES) else 62 + index * 73
        left, right = cx - HALF_W, cx + HALF_W
        top, bottom = TROOP_PRESET_CHIP_ROWS[0] - 4, 150
        this_ring = GOLD_RING if index == selected else BLUE_RING
        fill = SELECTED_FILL if index == selected else UNSELECTED_FILL
        draw.rectangle((left, top, right, bottom), fill=fill)
        draw.rectangle((left, top, left + BORDER - 1, bottom), fill=this_ring)
        draw.rectangle((right - BORDER + 1, top, right, bottom), fill=this_ring)
        draw.rectangle((left, top, right, top + BORDER - 1), fill=this_ring)
        draw.rectangle((left, bottom - BORDER + 1, right, bottom), fill=this_ring)
    if with_save:
        left, right = 621, 685
        draw.rectangle((left, 94, right, 158), fill=SAVE_FILL)
    del ring
    return image


def _write(tmp_path: Path, name: str, image: Image.Image) -> Path:
    path = tmp_path / name
    image.save(path)
    return path


# --------------------------------------------------------------- synthetic


def test_finds_the_presets_and_the_save_control(tmp_path: Path) -> None:
    strip = read_troop_preset_strip(_write(tmp_path, "plain.png", _draw_strip(None)))
    assert strip is not None
    assert strip.count == 8, "the save control is not a preset"
    assert strip.save_button is not None
    assert strip.selected_index is None, "no chip carries the gold ring on this frame"


def test_reads_which_preset_is_selected(tmp_path: Path) -> None:
    for index in (0, 3, 5, 7):
        strip = read_troop_preset_strip(
            _write(tmp_path, f"sel{index}.png", _draw_strip(index))
        )
        assert strip is not None
        assert strip.selected_index == index, f"expected chip {index} to read as selected"


def test_cells_are_in_draw_order_and_normalized(tmp_path: Path) -> None:
    strip = read_troop_preset_strip(_write(tmp_path, "plain.png", _draw_strip(None)))
    assert strip is not None
    lefts = [left for left, _ in strip.cells]
    assert lefts == sorted(lefts), "cells must be reported left to right"
    for left, right in strip.cells:
        assert 0.0 <= left < right <= 1.0
    centre = strip.center_norm(0)
    assert centre is not None
    x, y = centre
    assert 0.0 < x < 1.0 and 0.0 < y < 1.0
    assert strip.center_norm(8) is None, "there is no ninth preset"
    assert strip.center_norm(-1) is None


def test_a_page_without_the_bar_is_not_the_dispatch_page(tmp_path: Path) -> None:
    bare = Image.new("RGB", (720, 1280), (13, 50, 95))
    assert read_troop_preset_strip(_write(tmp_path, "bare.png", bare)) is None


def test_the_alliance_tech_bar_is_not_the_dispatch_bar(tmp_path: Path) -> None:
    """The one false positive the symmetric tolerance produced, pinned forever.

    Measured on dataset/raw/live_alliance_tech_page.png: the alliance-tech page
    draws a similar bar at (19,141,227).  A radius test around (13,129,198) of 30
    admits it -- blue differs by 29 -- so the gate is written on blue.
    """
    image = Image.new("RGB", (720, 1280), (13, 50, 95))
    ImageDraw.Draw(image).rectangle((0, 88, 719, 162), fill=(19, 141, 227))
    assert read_troop_preset_strip(_write(tmp_path, "tech.png", image)) is None


def test_a_wrongly_sized_frame_is_refused(tmp_path: Path) -> None:
    small = _draw_strip(None).resize((360, 640))
    assert read_troop_preset_strip(_write(tmp_path, "small.png", small)) is None


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    assert read_troop_preset_strip(tmp_path / "nope.png") is None


# ------------------------------------------------------------ live fixtures


def _live(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"live fixture missing: {relative}")
    return path


def test_live_frame_with_a_gold_chip() -> None:
    strip = read_troop_preset_strip(_live("dataset/raw/bear_live_20260909/bear_preset6.png"))
    assert strip is not None, "this is the dispatch page"
    assert strip.count == 8
    assert strip.selected_index == 5, "the account's preset named 熊6 is the sixth chip"


def test_live_frame_with_no_gold_chip_reads_none_not_an_error() -> None:
    strip = read_troop_preset_strip(
        _live("dataset/raw/bear_live_20260909/bear_troop_setup.png")
    )
    assert strip is not None
    assert strip.count == 8
    assert strip.selected_index is None


def test_live_map_frame_is_not_the_dispatch_page() -> None:
    assert read_troop_preset_strip(_live("dataset/raw/live_bear_preset6.png")) is None


def test_the_gate_over_the_whole_archived_corpus() -> None:
    """Every frame read as the dispatch page must really be one.

    The corpus is machine-local, so this skips on a fresh clone -- but where it
    can run it is the check that matters: 454 frames, 26 dispatch pages, and the
    four alliance-tech frames that the first (symmetric) gate wrongly admitted
    must stay out.
    """
    raw = ROOT / "dataset/raw"
    if not raw.is_dir():
        pytest.skip("archived corpus not present on this machine")
    seen = 0
    hits: list[str] = []
    for directory in (raw, raw / "bear_live_20260909"):
        if not directory.is_dir():
            continue
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith(".png"):
                continue
            path = directory / name
            try:
                with Image.open(path) as opened:
                    if opened.size != (720, 1280):
                        continue
            except OSError:
                continue
            seen += 1
            if read_troop_preset_strip(path) is not None:
                hits.append(name)
    if not seen:
        pytest.skip("no 720x1280 frames under dataset/raw")
    assert seen >= 200, f"the corpus shrank unexpectedly: {seen} frames"
    for name in hits:
        assert "alliance_tech" not in name, f"alliance-tech page read as a dispatch page: {name}"
        assert "cycle2_alliance" not in name, f"alliance page read as a dispatch page: {name}"
        assert "multitask_current" not in name, f"alliance page read as a dispatch page: {name}"
    assert "bear_preset6.png" in hits and "bear_troop_setup.png" in hits, (
        "the two frames the geometry was measured on must be found"
    )


def test_the_strip_value_object_is_immutable() -> None:
    strip = TroopPresetStrip(cells=((0.1, 0.2),), selected_index=0,
                             save_button=None, bar_colour=BAR)
    with pytest.raises(Exception):
        strip.selected_index = 1  # type: ignore[misc]
