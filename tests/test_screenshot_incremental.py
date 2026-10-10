# -*- coding: utf-8 -*-
"""Incremental screenshot processing: dedup by content, skip what is done, resume after a stop."""

from __future__ import annotations

import json
from pathlib import Path

from tools import screenshot_incremental as inc


def _img(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_two_files_with_the_same_content_are_one_new_image(tmp_path):
    """Dedup is by content, so a re-captured screen is not new work."""
    root = tmp_path / "root"
    _img(root / "a" / "one.png", b"same-bytes")
    _img(root / "b" / "copy.png", b"same-bytes")
    _img(root / "a" / "two.png", b"different")

    result = inc.plan(root, tmp_path / "audit")
    assert result["images_present"] == 3
    assert result["unique_by_content"] == 2
    assert len(result["new_since_inventory"]) == 2


def test_a_rename_is_not_new_work(tmp_path):
    root = tmp_path / "root"
    audit = tmp_path / "audit"
    _img(root / "one.png", b"payload")
    first = inc.plan(root, audit)
    digest = first["new_since_inventory"][0]
    # Record it in an inventory as if it had been inventoried before.
    audit.mkdir(parents=True)
    (audit / inc.INVENTORY_NAME).write_text(
        "screenshot_id,dup_group,is_canonical_copy,original_path,sha256,bytes,copy_index_within_group\n"
        f"SCR-x,DUP-1,TRUE,{root / 'one.png'},{digest},7,1\n", encoding="utf-8")

    (root / "one.png").rename(root / "renamed.png")
    second = inc.plan(root, audit)
    assert second["new_since_inventory"] == [], "a pure rename must not look like new work"
    assert second["gone_since_inventory"] == []


def test_an_analysed_image_is_not_re_analysed(tmp_path):
    root = tmp_path / "root"
    audit = tmp_path / "audit"
    _img(root / "one.png", b"payload")
    digest = inc.plan(root, audit)["new_since_inventory"][0]
    audit.mkdir(parents=True)
    (audit / inc.ANALYSIS_NAME).write_text(
        json.dumps({"sha256": digest, "analysis_status": "ANALYSED"}) + "\n", encoding="utf-8")

    result = inc.plan(root, audit)
    assert result["already_processed"] == [digest]
    assert result["needs_analysis"] == [], "an analysed image must not enter the work list"


def test_a_not_analysed_row_does_not_count_as_processed(tmp_path):
    """The placeholder status means 'nobody looked', and must not be mistaken for work done."""
    root = tmp_path / "root"
    audit = tmp_path / "audit"
    _img(root / "one.png", b"payload")
    digest = inc.plan(root, audit)["new_since_inventory"][0]
    audit.mkdir(parents=True)
    (audit / inc.ANALYSIS_NAME).write_text(
        json.dumps({"sha256": digest, "analysis_status": inc.NOT_PROCESSED_STATUS}) + "\n",
        encoding="utf-8")

    result = inc.plan(root, audit)
    assert result["already_processed"] == []
    assert result["needs_analysis"] == [digest]


def test_progress_survives_an_interruption(tmp_path):
    """A resumed run knows what it already finished, and what is left."""
    root = tmp_path / "root"
    audit = tmp_path / "audit"
    for i in range(3):
        _img(root / f"{i}.png", f"payload-{i}".encode())

    result = inc.plan(root, audit)
    assert len(result["new_since_inventory"]) == 3
    inc.write_progress(audit, result, completed=[result["new_since_inventory"][0]])

    resumed = inc.load_progress(audit)
    assert len(resumed["completed"]) == 1
    assert len(resumed["remaining"]) == 2
    assert resumed["counts"]["new_since_inventory"] == 3

    # A second, larger completion merges rather than replaces.
    inc.write_progress(audit, result, completed=[result["new_since_inventory"][1]])
    merged = inc.load_progress(audit)
    assert len(merged["completed"]) == 2
    assert len(merged["remaining"]) == 1


def test_a_failure_is_recorded_with_its_reason_and_is_replaceable(tmp_path):
    audit = tmp_path / "audit"
    inc.record_failure(audit, "abc123", "image could not be decoded")
    inc.record_failure(audit, "abc123", "still failing")
    failures = inc.load_progress(audit)["failures"]
    assert len(failures) == 1, "the same image must not accumulate duplicate failure rows"
    assert failures[0]["reason"] == "still failing"
    assert failures[0]["sha256"] == "abc123"


def test_an_unreadable_file_is_skipped_rather_than_crashing(tmp_path):
    root = tmp_path / "root"
    _img(root / "ok.png", b"payload")
    (root / "locked.png").write_bytes(b"x")
    # Simulate an unreadable file by pointing the hasher at a missing path.
    assert inc.sha256_of(root / "does-not-exist.png") is None
    result = inc.plan(root, tmp_path / "audit")
    assert result["unique_by_content"] == 2
