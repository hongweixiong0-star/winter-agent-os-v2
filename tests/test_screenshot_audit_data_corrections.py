# -*- coding: utf-8 -*-
"""Regression tests for the round-2 pure-data corrections (GAP-03 / 04 / 05 / 06).

Each test pins a knowledge-store fact that was added on 2026-10-10 from named screenshots. They are
consistency tests over data, so they change no runtime behaviour.

Why each one exists

  GAP-05  a badge can print `99+`, which is a clamp and not the count 99. A reader that parses a
          badge as an integer would treat a clamp as data.
  GAP-06  two dots were observed with no measured search window. This file's own rule is that an
          unbound dot must not be read as PRESENT or ABSENT, so they must appear as unmeasured and
          must NOT appear as readable entries.
  GAP-04  one frame prints two different activity names and nothing says which the control acts on.
          It must stay NEEDS_LIVE_VERIFICATION rather than being resolved offline.
  GAP-03  `领取` / `前往` appear on several visually identical rows. The label alone is not a target.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "knowledge" / "ui"
EVENTS = ROOT / "knowledge" / "events"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- GAP-05


def test_a_clamped_badge_is_recorded_as_a_distinct_state_not_a_number():
    data = _json(UI / "entry_badges.json")
    clamped = data.get("clamped_badge")
    assert clamped, "the clamped-badge rule is missing; a `99+` badge could be read as the number 99"
    assert clamped["clamped_form"] == "99+"
    assert "never" in clamped["rule"] and "number" in clamped["rule"]
    # The ambiguity must stay explicit rather than being filled in.
    assert clamped["interaction_meaning"].startswith("UNKNOWN")


def test_the_clamped_badge_evidence_frame_is_a_real_file():
    data = _json(UI / "entry_badges.json")
    frame = ROOT / data["clamped_badge"]["evidence_frame"]
    assert frame.is_file(), f"the evidence frame is missing on disk: {frame}"


# ---------------------------------------------------------------- GAP-06


def test_the_two_newly_observed_dots_are_recorded_as_unmeasured():
    data = _json(UI / "entry_badges.json")
    joined = " ".join(str(x) for x in data.get("not_measured") or [])
    assert "联盟商店" in joined, "the 联盟商店 dot was observed but is not recorded as unmeasured"
    assert "陷阱强化" in joined, "the 陷阱强化 dot was observed but is not recorded as unmeasured"


def test_an_unmeasured_dot_is_never_also_a_readable_entry():
    """The file's own rule: an unbound dot must not be read. So a dot cannot be both.

    Compared by SYMBOLIC id, not by prose. The first draft of this test compared entry labels
    against the whole `not_measured` text and fired on the pre-existing note about 邮件页签, because
    the label 邮件 is a substring of that prose - a false positive on data that was already correct.
    """
    data = _json(UI / "entry_badges.json")
    unbound = set()
    for note in data.get("not_measured") or []:
        unbound |= set(re.findall(r"[A-Z][A-Z0-9_]{3,}", str(note)))
    measured = {str(entry.get("entry") or "") for entry in data.get("entries") or []}
    overlap = sorted(measured & unbound)
    assert not overlap, f"these ids are both measured and declared unbound: {overlap}"


def test_the_newly_recorded_dots_are_not_measured_entries():
    """The two dots observed on 2026-10-10 must not have been smuggled into the readable table."""
    data = _json(UI / "entry_badges.json")
    ids = {str(entry.get("entry") or "") for entry in data.get("entries") or []}
    for name in ("RED_DOT_ALLIANCE_SHOP", "RED_DOT_BEAR_TRAP_UPGRADE"):
        assert name not in ids, f"{name} is readable but was never measured"


def test_every_measured_entry_still_carries_its_measurement():
    """A guard against a future edit adding an entry without a window, which would make the dot
    readable without ever having been measured."""
    data = _json(UI / "entry_badges.json")
    for entry in data.get("entries") or []:
        assert entry.get("search_window_norm"), f"{entry.get('entry')} has no measured search window"
        assert entry.get("measured_blob_norm"), f"{entry.get('entry')} has no measured blob"


# ---------------------------------------------------------------- GAP-04


def test_the_two_activity_names_stay_needs_live_verification():
    data = _json(EVENTS / "bear_participation_chain_status.json")
    section = data.get("the_two_activity_names_on_one_screen_20261010")
    assert section, "the two-activity-names observation was not recorded"
    assert section["classification"] == "NEEDS_LIVE_VERIFICATION"
    # Both names must be preserved verbatim, and the unattributed one must stay unknown.
    printed = section["what_the_frame_prints"]
    assert printed["the_rally_rows_target"] == "等级1变异巨熊"
    assert "冰原巨兽" in printed["the_sentence_above_the_button"]
    assert section["what_is_NOT_proven"].startswith("UNKNOWN")
    assert "不得" in section["why_not_resolved_offline"] or "假事实" in section["why_not_resolved_offline"]


def test_the_two_name_conflict_evidence_frame_is_real():
    data = _json(EVENTS / "bear_participation_chain_status.json")
    frame = ROOT / data["the_two_activity_names_on_one_screen_20261010"]["evidence_frame"]
    assert frame.is_file(), f"the evidence frame is missing on disk: {frame}"


# ---------------------------------------------------------------- GAP-03


def test_labels_that_need_a_row_anchor_are_recorded_as_ambiguous():
    data = _json(UI / "icon_label_controls.json")
    block = data.get("labels_that_need_a_row_anchor")
    assert block, "the row-anchor ambiguity was not recorded"
    for label in ("领取", "前往"):
        entry = block["labels"][label]
        assert entry["row_anchor_required"] is True
        assert entry["ambiguity"]
    assert "提升" in block["observed_but_NOT_registered"], (
        "提升 was observed but has no template or unique meaning; it must stay unregistered"
    )


def test_a_row_anchor_requirement_does_not_create_a_click_rule():
    """The note must be declarative. It may not carry a coordinate.

    Checked against coordinate SHAPES, not against the word "click" - the note's own text says
    "NOT a click rule", which made the first draft of this test fail on correct data.
    """
    data = _json(UI / "icon_label_controls.json")
    text = json.dumps(data["labels_that_need_a_row_anchor"], ensure_ascii=False)
    for label, pattern in (
        ("a tap_norm field", r"tap_norm"),
        ("a bbox field", r"\bbbox\b"),
        ("a bracketed number tuple", r"\[\s*\d+(\.\d+)?\s*,\s*\d+"),
        ("an x/y assignment", r"\b[xy]\s*=\s*\d"),
    ):
        assert not re.search(pattern, text), f"the row-anchor note contains {label}"


def test_the_row_anchor_block_does_not_duplicate_the_registered_controls():
    """`领取` and `前往` are already registered; the note annotates them rather than re-registering."""
    data = _json(UI / "icon_label_controls.json")
    controls = data.get("controls") or {}
    block = data["labels_that_need_a_row_anchor"]
    for label in block["already_registered_but_ambiguous"]:
        assert label in controls, f"{label} is called already-registered but is not in controls"
    # And nothing may be added to controls by this note.
    assert "提升" not in controls, "提升 must not be silently registered by this change"
